from dataclasses import dataclass
from typing import Callable, Optional

PROGRESS_STATUSES = ("pending", "running", "completed", "skipped", "failed")
PROGRESS_KINDS = ("actual", "estimated", "indeterminate")
TERMINAL_STATUSES = ("completed", "skipped", "failed")


@dataclass(frozen=True)
class ProgressEvent:
    """A renderer-independent snapshot of one processing phase."""

    phase: str
    message: str
    status: str = "running"
    progress_kind: str = "indeterminate"
    current: Optional[float] = None
    total: Optional[float] = None
    unit: Optional[str] = None
    elapsed_seconds: float = 0.0
    eta_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        if self.status not in PROGRESS_STATUSES:
            raise ValueError(f"Unsupported progress status: {self.status}")
        if self.progress_kind not in PROGRESS_KINDS:
            raise ValueError(f"Unsupported progress kind: {self.progress_kind}")
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        if self.eta_seconds is not None and self.eta_seconds < 0:
            raise ValueError("eta_seconds cannot be negative")
        measured = self.current is not None or self.total is not None
        if self.progress_kind == "indeterminate" and measured:
            raise ValueError("Indeterminate progress cannot contain current/total")
        if self.progress_kind != "indeterminate":
            if self.current is None or self.total is None or self.total <= 0:
                raise ValueError("Measured progress requires current and a positive total")
            if self.current < 0 or self.current > self.total:
                raise ValueError("Progress current must be between zero and total")
            if self.status == "running" and self.current >= self.total:
                raise ValueError("Running progress cannot reach 100 percent")

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def fraction(self) -> Optional[float]:
        if self.current is None or self.total is None:
            return None
        return self.current / self.total


ProgressCallback = Callable[[ProgressEvent], None]

