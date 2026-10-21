#!/usr/bin/env python3
"""Explicitly prepare and reverify new models in an isolated validation store."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from asr_desktop.models import ModelStore

ROOT = Path(__file__).resolve().parents[2]


def main():
    store = ModelStore(ROOT / "build/desktop/local-whisper/models")
    def prepare(identifier):
        print("Preparing " + identifier, flush=True)
        store.prepare(identifier)
        result = store.verify(identifier)
        if not result["ready"]:
            raise RuntimeError("Model verification failed: " + identifier)
        print(identifier + " verified", flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(prepare, ("taiwan-tongues", "breeze-asr-25")))


if __name__ == "__main__":
    main()
