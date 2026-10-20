from dataclasses import dataclass
from typing import Callable, Optional

from .errors import DependencyError, MPSCompatibilityError, ValidationError


@dataclass(frozen=True)
class DeviceDecision:
    requested: str
    resolved: str
    fallback_allowed: bool
    reason: str = ""


def _torch_mps_available() -> bool:
    try:
        import torch
    except ImportError as exc:
        raise DependencyError("PyTorch is not installed. Run: pip install -e .") from exc
    return bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())


def resolve_device(
    requested: str,
    availability: Callable[[], bool] = _torch_mps_available,
) -> DeviceDecision:
    if requested == "cpu":
        return DeviceDecision(requested, "cpu", False, "CPU explicitly selected")
    if requested == "mps":
        if not availability():
            raise MPSCompatibilityError("MPS was explicitly selected but is unavailable")
        return DeviceDecision(requested, "mps", False, "MPS explicitly selected")
    if requested != "auto":
        raise ValidationError("Device must be one of: auto, mps, cpu")
    return DeviceDecision(requested, "cpu", False, "insufficient_evidence")


def looks_like_mps_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    markers = (
        "not implemented for the mps", "not implemented for mps", "placeholder storage",
        "mps backend", "mps device", "mps op unsupported", "metal performance shaders",
        "unsupported device type: mps",
    )
    return any(marker in message for marker in markers)

