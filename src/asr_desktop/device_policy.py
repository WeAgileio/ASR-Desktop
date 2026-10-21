"""SQLite-backed evidence; normal job text never becomes a quality baseline."""

import json
from asr_srt.evidence import identity_key, profile_identity, select
from .database import encode


class DevicePolicy:
    def __init__(self, database):
        self.db = database

    def explain(self, snapshot, options, duration_seconds, definition=None):
        identity = profile_identity(snapshot, options, duration_seconds)
        key = identity_key(identity)
        row = self.db.connection.execute("SELECT details FROM device_profiles WHERE id=?", (key,)).fetchone()
        profile = json.loads(row[0]) if row else {"identity": identity, "samples": [], "quarantined": False}
        decision = select(identity, profile["samples"], profile.get("quarantined", False))
        if definition is not None:
            from asr_srt.registry import execution
            if "mps" not in execution(definition)["devices"]:
                decision.update(device="cpu", reason="model_cpu_only", fallback_allowed=False)
        if options["device"] != "auto":
            decision.update(device="mps" if options["device"] in ("gpu", "mps") else "cpu",
                            reason="explicit_device", fallback_allowed=False)
        return {**decision, "profile_id": key, "identity": identity,
                "quality_baseline": "not_established", "sample_count": len(profile["samples"])}

    def record(self, job, decision, result):
        key = decision["profile_id"]
        row = self.db.connection.execute("SELECT details FROM device_profiles WHERE id=?", (key,)).fetchone()
        profile = json.loads(row[0]) if row else {"identity": decision["identity"], "samples": [], "quarantined": False}
        spans = result.get("performance_spans", [])
        # Model load and inference are timed separately by core stage callbacks.
        loads = sum(s.get("seconds", 0) for s in spans if s.get("name") == "model-load")
        inference = [s for s in spans if s.get("name") == "asr-inference"]
        cost = loads + sum(s.get("seconds", 0) for s in (inference or [s for s in spans if s.get("name") == "chunk-asr"]))
        fallback = decision["device"] == "mps" and result.get("actual_device") == "cpu"
        sample = {"state": result.get("state"), "device": result.get("actual_device"),
                  "source_sha256": job["fingerprint"]["sha256"], "duration_seconds": job["duration_ms"] / 1000,
                  "cache_hit": result.get("cache_hit", False), "resumed": any(s.get("name") == "checkpoint-resumed" for s in spans),
                  "fallback": fallback, "cost_seconds": cost, "quality_ok": False, "timestamps_ok": False,
                  "resources": result.get("resources", {})}
        profile["samples"].append(sample)
        profile["samples"] = profile["samples"][-120:]
        if fallback or result.get("error", {}).get("code") == "mps_compatibility":
            profile["quarantined"] = True
        elif job.get("kind") == "calibration" and result.get("state") == "completed" and result.get("actual_device") == "mps":
            profile["quarantined"] = False
        self.db.connection.execute("INSERT INTO device_profiles VALUES(?,?) ON CONFLICT(id) DO UPDATE SET details=excluded.details", (key, encode(profile)))
