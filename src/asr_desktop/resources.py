"""Per-worker resource observations; unavailable data is explicit."""

import resource
import threading
import time

import psutil
from asr_srt.evidence import sysctl


class ResourceMonitor:
    def __init__(self):
        self.started = time.monotonic()
        self.stop_event = threading.Event()
        self.observations = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            raw = sysctl("kern.memorystatus_vm_pressure_level")
            try:
                swap = psutil.swap_memory().used
            except (OSError, RuntimeError):
                swap = None
            self.observations.append({"seconds": time.monotonic() - self.started,
                                      "pressure": {"1": "normal", "2": "warning", "4": "critical"}.get(raw),
                                      "pressure_raw": raw, "swap_bytes": swap})
            self.stop_event.wait(5)

    def finish(self):
        self.stop_event.set()
        self.thread.join(timeout=4)
        return {"peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "observations": list(self.observations), "policy_version": 1,
                "sources": {"rss": "getrusage.RUSAGE_SELF.ru_maxrss.darwin_bytes",
                            "pressure": "sysctl.kern.memorystatus_vm_pressure_level.dispatch_flags",
                            "swap": "psutil.swap_memory.used"}}
