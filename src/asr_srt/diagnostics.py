import importlib.util
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .config import default_cache_dir


@dataclass(frozen=True)
class DiagnosticReport:
    python: str
    macos: str
    machine: str
    apple_silicon: bool
    torch_installed: bool
    mps_available: bool
    funasr_installed: bool
    ffmpeg: Optional[str]
    ffprobe: Optional[str]
    cache_dir: str

    def to_text(self) -> str:
        values = asdict(self)
        return "\n".join(f"{key}: {value}" for key, value in values.items())


def collect_diagnostics(cache_dir: Optional[Path] = None) -> DiagnosticReport:
    torch_installed = importlib.util.find_spec("torch") is not None
    mps_available = False
    if torch_installed:
        try:
            import torch
            mps_available = bool(
                hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            )
        except Exception:
            mps_available = False
    machine = platform.machine()
    return DiagnosticReport(
        python=sys.version.split()[0],
        macos=platform.mac_ver()[0] or platform.system(),
        machine=machine,
        apple_silicon=platform.system() == "Darwin" and machine == "arm64",
        torch_installed=torch_installed,
        mps_available=mps_available,
        funasr_installed=importlib.util.find_spec("funasr") is not None,
        ffmpeg=shutil.which("ffmpeg"),
        ffprobe=shutil.which("ffprobe"),
        cache_dir=str((cache_dir or default_cache_dir()).expanduser()),
    )

