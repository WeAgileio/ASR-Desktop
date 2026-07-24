# Apple Silicon Evaluation Results

Record one row per model/device/case. Do not commit private media or transcripts.

| Date | Mac / RAM | Case | Model | Device | Audio min | Processing sec | RTF | Timestamp usable | Peak memory | Notes |
|---|---|---|---|---|---:|---:|---:|---|---|---|
| 2026-07-15 | Apple Silicon / unknown RAM | bundled Mandarin example | fun-asr-nano | mps | 0.094 | 8.60 inference / 39.00 including load | 1.530 inference | yes, 15 units | 6361.9 MB RSS | Correct text; slower than CPU for this short clip |
| 2026-07-15 | Apple Silicon / unknown RAM | bundled Mandarin example | fun-asr-nano | cpu | 0.094 | 3.58 inference / 29.31 including load | 0.637 inference | yes, 15 units | 6660.4 MB RSS | Correct text and timestamps |
| 2026-07-15 | Apple Silicon / unknown RAM | bundled Mandarin example | paraformer | mps | | | | blocked | | Paraformer weights are not present in the user's existing caches |
| 2026-07-15 | Apple Silicon / unknown RAM | synthetic Mandarin | paraformer | cpu | 0.06 | | | blocked | | Model download reached 38/944 MB at about 0.5 MB/s, then was interrupted to avoid a 30+ minute wait; partial hub cache retained |

## Nano runtime decision

The Python `AutoModel` path is the implemented runtime because it exposes character timestamps through the documented `timestamps` result. The llama.cpp/GGUF path remains unsupported for SRT generation until its command output is verified to expose equivalent character timestamps; plain-text-only output is insufficient.

## Environment diagnostics

- macOS: 26.5.1, arm64
- Python: 3.9.6
- FunASR: 1.3.12
- PyTorch / torchaudio: 2.8.0
- `torch.backends.mps.is_built()`: true
- `torch.backends.mps.is_available()`: true outside the execution sandbox; both Nano MPS and CPU smoke tests completed
- FFmpeg: 8.0.1
- Logic, adapter-contract, CLI, and real FFmpeg end-to-end tests: 25 passed
- Full real-model CLI check: MP4 → FFmpeg → Nano CPU → OpenCC → valid SRT succeeded; a second run was a transcript cache hit

## Long-form conservative defaults

- Long-form threshold: 30 minutes
- Target chunk: 20 minutes; allowed range: 15–30 minutes
- Silence search window: ±60 seconds; minimum silence: 600 ms
- Dense-speech fallback overlap: 1.5 seconds
- Execution: sequential chunks, one model session per device attempt
- Auto device: retain availability-based fallback until both CPU and MPS have at least two compatible safe long-form samples
- Candidate tuning gate: at least 10% RTF improvement, no transcript/timestamp regression, no sustained swap growth, and no peak-memory guardrail violation
- Current blocker: installed Paraformer weights and representative private 10–60 minute/two-hour speech media are unavailable, so no new model/device/batch default is adopted
