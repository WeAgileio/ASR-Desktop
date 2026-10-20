# Preparing local models

Install the complete App, then choose **模型 → 下載／修復**, or use the bundled command:

```sh
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models list --json
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models download fun-asr-nano --json
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models list --json
```

Preparation is asynchronous. Inspect `state`, `downloaded_bytes`, `total_bytes`, and `ready`. Only `ready=true` permits new inference. Download and transcription have separate progress. Both clients use the same store in `~/Library/Application Support/ASR Desktop/models`. About 2.15 GB transfers for Nano and 1.30 GB for Paraformer; the returned `required_free_bytes` includes workspace headroom. Installation itself contains no model weights.

Retry the same download command after a network interruption or capacity failure. Completed, hash-verified files remain reusable. Eligible partial files preserve a strong ETag and immutable catalog identity; the next transfer sends Range and If-Range. A changed identity or unsupported range discards only that asset's partial transfer. All assets must match catalog size and SHA-256 before publication. No Python installation scripts run during preparation.

```sh
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models verify paraformer --json
"/Applications/ASR Desktop.app/Contents/MacOS/asr-desktop" models remove paraformer --json
```

Verification rehashes every required asset and reports damaged/missing models as unavailable. Repair is an explicit download action; inference never fetches missing data. Removal reports `model_in_use` and job IDs if queued/running/interrupted work still references the snapshot. Cancel those jobs first if they are no longer needed. Completed or cancelled history and exported results survive model removal. A later retry may require downloading the original snapshot.

The App's catalog pins main weights, VAD, punctuation, tokenizer and configuration to immutable commits. New App catalogs do not alter previously accepted jobs or saved definitions. Prepared inference uses absolute local paths and blocks Python outbound sockets. Existing developer hub caches are not the desktop model store. Offline packaging smoke is evidence for the current development environment; full OS-level offline and clean-Mac acceptance remain separate release gates.

Maintainers can reproduce real interrupted-HTTP resume using `PYTHONPATH=src build/desktop/packaging-env/bin/python -m unittest tests.desktop.test_download_http -v`. The fixture transfers 7,000 bytes then closes early; retry must send the validated offset and produce the original full checksum. It uses a local HTTP server and disposable model store, not a model registry simulation or user data. Protocol, failure and publication tests are in `tests/desktop/test_models.py`.
