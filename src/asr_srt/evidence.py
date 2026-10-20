"""Versioned, conservative device decisions from comparable observed samples."""

import hashlib
from importlib import metadata
import json
import math
import platform
from statistics import median
import subprocess

POLICY_VERSION = 1


def sysctl(name):
    try:
        return subprocess.check_output(["/usr/sbin/sysctl", "-n", name], text=True, timeout=3).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def profile_identity(snapshot, options, duration_seconds):
    versions = {}
    for name in ("funasr", "torch", "torchaudio", "transformers", "modelscope", "tiktoken"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {"policy_version": POLICY_VERSION, "hardware": sysctl("hw.model"),
            "ram_bytes": int(sysctl("hw.memsize") or 0), "os": platform.mac_ver()[0],
            "python": platform.python_version(), "packages": versions, "snapshot": snapshot,
            "runtime_distributions": {d.metadata["Name"]: d.version for d in metadata.distributions() if d.metadata.get("Name")},
            "recognition": {"language": options["language"], "hotwords": options["hotwords"]},
            "loading": "cold-per-file", "planner": "long-form-v1",
            "duration_band": "short" if duration_seconds < 600 else "medium" if duration_seconds <= 3600 else "long"}


def identity_key(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def eligible(sample, ram_bytes):
    try:
        return _eligible(sample, ram_bytes)
    except (KeyError, TypeError, ValueError):
        return False


def _eligible(sample, ram_bytes):
    if (sample.get("state") != "completed" or sample.get("cache_hit") or sample.get("resumed")
        or sample.get("fallback") or sample.get("duration_seconds", 0) < 30
        or sample.get("quality_ok") is not True or sample.get("timestamps_ok") is not True
        or sample.get("cost_seconds", 0) <= 0 or not math.isfinite(sample["cost_seconds"])):
        return False
    resource = sample.get("resources", {})
    peak = resource.get("peak_rss_bytes")
    observations = resource.get("observations", [])
    expected_sources = {"rss": "getrusage.RUSAGE_SELF.ru_maxrss.darwin_bytes",
                        "pressure": "sysctl.kern.memorystatus_vm_pressure_level.dispatch_flags",
                        "swap": "psutil.swap_memory.used"}
    if resource.get("policy_version") != POLICY_VERSION or resource.get("sources") != expected_sources:
        return False
    if (not ram_bytes or type(peak) not in (int, float) or not math.isfinite(peak) or peak > ram_bytes * .7 or peak <= 0
        or len(observations) < 2 or any(o.get("pressure") != "normal" or o.get("swap_bytes") is None for o in observations)):
        return False
    # Missing observations never imply a passing resource result.
    baseline = observations[0]["swap_bytes"]
    elevated = [o["seconds"] for o in observations if o["swap_bytes"] - baseline > 64 * 1024 * 1024]
    if observations[-1]["seconds"] - observations[0]["seconds"] < 5:
        return False
    return not (len(elevated) >= 2 and elevated[-1] - elevated[0] >= 5)


def select(identity, samples, quarantined=False):
    missing_identity = (identity.get("policy_version") != POLICY_VERSION or not identity.get("hardware")
                        or not identity.get("ram_bytes") or not identity.get("os")
                        or any(not identity.get("packages", {}).get(name) for name in ("funasr", "torch", "torchaudio", "transformers", "modelscope", "tiktoken"))
                        or not all(key in identity for key in ("python", "snapshot", "recognition", "loading", "planner", "duration_band", "runtime_distributions")))
    result = {"device": "cpu", "fallback_allowed": False, "reason": "insufficient_evidence", "eligible_cpu": 0, "eligible_mps": 0}
    if missing_identity:
        return {**result, "reason": "incomplete_profile_identity"}
    if quarantined:
        return {**result, "reason": "gpu_combination_quarantined"}
    valid = [s for s in samples if eligible(s, identity["ram_bytes"])]
    groups = {}
    for sample in valid:
        device = sample.get("device")
        if device in ("cpu", "mps") and sample.get("source_sha256"):
            groups.setdefault(sample["source_sha256"], {"cpu": [], "mps": []})[device].append(sample["cost_seconds"])
    cpu, mps = [], []
    # Balance source and repetition counts so one device cannot win on easier inputs.
    for values in groups.values():
        count = min(len(values["cpu"]), len(values["mps"]))
        if count:
            cpu.extend(values["cpu"][-count:]); mps.extend(values["mps"][-count:])
    result.update(eligible_cpu=len(cpu), eligible_mps=len(mps))
    if len(cpu) < 3 or len(mps) < 3:
        return result
    result.update(cpu_median_seconds=median(cpu), mps_median_seconds=median(mps))
    if median(mps) <= median(cpu) * .9:
        result.update(device="mps", fallback_allowed=True, reason="qualified_gpu_improvement")
    else:
        result["reason"] = "gpu_below_improvement_threshold"
    return result
