"""LaunchAgent-friendly host bootstrap with an external JSON configuration file."""

import json
import os
from pathlib import Path
import sys

if len(sys.argv) != 3 or sys.argv[1] not in ("worker", "scanner", "cleanup"):
    raise SystemExit(
        "Usage: run_host.py worker|scanner|cleanup /absolute/path/host.json"
    )
config_path = Path(sys.argv[2]).expanduser().resolve()
if "Mobile Documents" in config_path.parts or "CloudStorage" in config_path.parts:
    raise SystemExit("Keep host configuration outside cloud-synchronized directories")
config = json.loads(config_path.read_text())
allowed = {
    "ASR_API_URL",
    "ASR_REDIS_URL",
    "ASR_WORKER_TOKEN_FILE",
    "ASR_WORKSPACE",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "ASR_DRIVE_AUTH",
    "ASR_GOOGLE_TOKEN_FILE",
    "ASR_RETENTION_DAYS",
    "ASR_MIN_FREE_BYTES",
}
if set(config) - allowed:
    raise SystemExit("Unknown configuration keys")
os.environ.update({k: str(v) for k, v in config.items()})
source = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, source)
os.environ["PYTHONPATH"] = source
from asr_service import native

getattr(native, sys.argv[1])()
