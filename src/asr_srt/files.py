import os
import tempfile
from pathlib import Path

from .errors import OutputExistsError


def atomic_write_text(path: Path, content: str, overwrite: bool = True) -> None:
    path = Path(path)
    if path.exists() and not overwrite:
        raise OutputExistsError(f"Output already exists: {path}. Use --overwrite to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() and not overwrite:
            raise OutputExistsError(f"Output already exists: {path}. Use --overwrite to replace it.")
        os.replace(str(temp_path), str(path))
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

