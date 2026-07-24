## 1. Progress domain and workflow lifecycle

- [x] 1.1 Expand the progress domain model with phase status, progress kind, measurements, elapsed time, ETA, validation, and terminal-state semantics while preserving callback compatibility
- [x] 1.2 Add workflow lifecycle emission for input validation, extraction, model preparation, ASR, subtitle generation, and output writing, including exactly one completed or failed terminal event per executed phase
- [x] 1.3 Emit explicit skipped events for cache-bypassed extraction and transcription without changing transcript cache keys or recognition output
- [x] 1.4 Add unit tests for monotonic measurements, completion-only 100%, failure propagation, phase ordering, and cache-hit lifecycle events

## 2. Measured media extraction progress

- [x] 2.1 Add an isolated parser for FFmpeg `-progress` key/value output, including supported media-time fields and malformed/partial records
- [x] 2.2 Run extraction with FFmpeg's machine-readable progress channel while retaining stderr, exit-code handling, temporary-output cleanup, and output validation
- [x] 2.3 Convert processed media time and ffprobe duration into bounded actual progress, falling back to indeterminate when duration is unavailable and withholding 100% until successful validation
- [x] 2.4 Add parser, missing-duration, premature-end, failure-cleanup, and real-media integration tests for extraction progress

## 3. ASR progress and performance estimates

- [x] 3.1 Extend the adapter request/capability contract to accept progress reporting and declare whether callback values have stable whole-input scope
- [x] 3.2 Update Nano and Paraformer adapters to disable FunASR's native tqdm output and classify integrated-VAD batch callbacks as non-global
- [x] 3.3 Implement an atomically persisted, versioned RTF performance profile keyed by model revision, device/backend, and runtime identity, with safe handling for missing, incompatible, or corrupt data
- [x] 3.4 Record representative successful uncached ASR samples while excluding failed, cancelled, cached, and too-short runs
- [x] 3.5 Produce explicitly estimated ASR percentage and ETA from sufficient compatible history, cap it below 100% while running, and otherwise remain indeterminate with elapsed time
- [x] 3.6 Add adapter and performance-profile tests covering global callbacks, batch-local callbacks, sample eligibility, key isolation, corrupt files, estimate labeling, and transcript-cache independence

## 4. CLI renderers

- [x] 4.1 Add Rich as a direct project dependency and implement a bounded live TTY renderer for actual bars, estimated bars, indeterminate spinners, elapsed time, ETA, and terminal states
- [x] 4.2 Implement a throttled plain-text renderer with no ANSI sequences and lifecycle/heartbeat output suitable for redirected stdout, logs, and CI
- [x] 4.3 Add `--progress auto|rich|plain|off`, TTY auto-detection, clean renderer shutdown on success or error, and preservation of internal timing when display is off
- [x] 4.4 Add CLI tests for TTY and non-TTY selection, forced modes, disabled output, heartbeat throttling, bounded live updates, cache skips, failures, and absence of duplicate FunASR progress bars

## 5. Integration and documentation

- [x] 5.1 Wire media and adapter progress producers through the workflow to the selected renderer without changing model selection, VAD/batching, timestamps, subtitle contents, or output atomicity
- [x] 5.2 Add end-to-end tests for actual extraction progress followed by indeterminate or estimated ASR progress and successful SRT output
- [x] 5.3 Run the full automated suite plus an installed Nano-model smoke test on macOS, confirming local-only model resolution and unchanged transcription results with progress enabled and disabled
- [x] 5.4 Document progress modes, actual versus estimated semantics, first-run ETA limitations, performance-profile storage, cache skip behavior, and troubleshooting for redirected output
