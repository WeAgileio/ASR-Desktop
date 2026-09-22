import sys
import threading
import time
import math
from typing import Dict, Optional, TextIO, Tuple

from .progress import ProgressEvent


def _snapshot(event: ProgressEvent, received_at: float) -> Tuple[float, Optional[float], Optional[float]]:
    heartbeat_elapsed = 0.0
    elapsed = event.elapsed_seconds
    if event.status == "running":
        heartbeat_elapsed = max(0.0, time.monotonic() - received_at)
        elapsed += heartbeat_elapsed
    current, eta = event.current, event.eta_seconds
    if eta is not None:
        eta = max(0.0, eta - heartbeat_elapsed) if math.isfinite(eta) else None
    if (
        event.status == "running"
        and event.progress_kind == "estimated"
        and event.unit == "seconds"
        and event.total is not None
        and current is not None
    ):
        current = min(current + heartbeat_elapsed, event.total * 0.95)
    return elapsed, current, eta


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    value = max(0, round(seconds))
    minutes, second = divmod(value, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minute:02d}:{second:02d}"
    return f"{minute:02d}:{second:02d}"


class NullProgressRenderer:
    def __call__(self, event: ProgressEvent) -> None:
        pass

    def close(self) -> None:
        pass


class PlainProgressRenderer:
    def __init__(self, stream: TextIO = sys.stderr, heartbeat_interval: float = 30.0):
        self.stream = stream
        self.heartbeat_interval = heartbeat_interval
        self._lock = threading.Lock()
        self._latest: Optional[Tuple[ProgressEvent, float]] = None
        self._last_printed = 0.0
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def __call__(self, event: ProgressEvent) -> None:
        now = time.monotonic()
        with self._lock:
            previous = self._latest[0] if self._latest else None
            self._latest = (event, now)
            should_print = (
                event.terminal
                or self._last_printed == 0
                or previous is None
                or previous.phase != event.phase
                or previous.status != event.status
                or now - self._last_printed >= self.heartbeat_interval
            )
            if should_print:
                self._write(event, now)

    def _heartbeat(self) -> None:
        wait = max(0.05, min(self.heartbeat_interval, 1.0))
        while not self._closed.wait(wait):
            now = time.monotonic()
            with self._lock:
                if not self._latest:
                    continue
                event, received = self._latest
                if event.status == "running" and now - self._last_printed >= self.heartbeat_interval:
                    self._write(event, received)

    def _write(self, event: ProgressEvent, received: float) -> None:
        elapsed, current, eta = _snapshot(event, received)
        progress = ""
        if current is not None and event.total:
            percent = min(100.0, max(0.0, current / event.total * 100))
            label = "estimated " if event.progress_kind == "estimated" else ""
            progress = f" {label}{percent:.1f}%"
        eta_text = f" ETA {_format_duration(eta)}" if eta is not None else ""
        self.stream.write(
            f"[{event.phase}] {event.status}{progress} elapsed {_format_duration(elapsed)}{eta_text} - {event.message}\n"
        )
        self.stream.flush()
        self._last_printed = time.monotonic()

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=2)


class RichProgressRenderer:
    def __init__(self, stream: TextIO = sys.stderr, refresh_per_second: float = 8.0):
        try:
            from rich.console import Console
            from rich.live import Live
        except ImportError as exc:
            raise RuntimeError("Rich progress requires the 'rich' package") from exc
        self._Console = Console
        self._Live = Live
        self.stream = stream
        self.refresh_interval = 1 / refresh_per_second
        self._events: Dict[str, Tuple[ProgressEvent, float]] = {}
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._console = Console(file=stream, force_terminal=True)
        self._live = Live(self._build_table(), console=self._console, refresh_per_second=refresh_per_second)
        self._live.start(refresh=True)
        self._thread = threading.Thread(target=self._refresh, daemon=True)
        self._thread.start()

    def __call__(self, event: ProgressEvent) -> None:
        with self._lock:
            self._events[event.phase] = (event, time.monotonic())
            self._live.update(self._build_table(), refresh=True)

    def _build_table(self):
        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, expand=True)
        table.add_column("Phase", no_wrap=True)
        table.add_column("State", no_wrap=True)
        table.add_column("Progress", no_wrap=True)
        table.add_column("Elapsed", no_wrap=True)
        table.add_column("ETA", no_wrap=True)
        table.add_column("Message", overflow="fold")
        for phase, (event, received) in self._events.items():
            elapsed, current, eta = _snapshot(event, received)
            if current is None or not event.total:
                progress = "…" if event.status == "running" else "-"
            else:
                prefix = "~" if event.progress_kind == "estimated" else ""
                progress = f"{prefix}{min(100, current / event.total * 100):.1f}%"
            state_style = {
                "completed": "green",
                "failed": "red",
                "skipped": "yellow",
                "running": "cyan",
            }.get(event.status, "white")
            table.add_row(
                phase,
                f"[{state_style}]{event.status}[/{state_style}]",
                progress,
                _format_duration(elapsed),
                _format_duration(eta),
                event.message,
            )
        return table

    def _refresh(self) -> None:
        while not self._closed.wait(self.refresh_interval):
            with self._lock:
                self._live.update(self._build_table(), refresh=True)

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=2)
        with self._lock:
            self._live.update(self._build_table(), refresh=True)
            self._live.stop()


def create_progress_renderer(
    mode: str,
    stream: TextIO = sys.stderr,
    *,
    heartbeat_interval: float = 30.0,
):
    selected = mode
    if selected == "auto":
        selected = "rich" if bool(getattr(stream, "isatty", lambda: False)()) else "plain"
    if selected == "off":
        return NullProgressRenderer()
    if selected == "plain":
        return PlainProgressRenderer(stream, heartbeat_interval=heartbeat_interval)
    if selected == "rich":
        return RichProgressRenderer(stream)
    raise ValueError(f"Unsupported progress mode: {mode}")
