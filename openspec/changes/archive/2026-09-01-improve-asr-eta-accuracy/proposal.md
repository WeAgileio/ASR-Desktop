## Why

ASR progress currently combines workload values expressed in milliseconds with elapsed and ETA values expressed in seconds, causing long-form jobs that finish in about an hour to display ETAs of hundreds or thousands of hours. Compatible historical RTF evidence and chunk checkpoints already exist, so ETA should use those time-based signals without changing recognition, transcript, cache, or subtitle behavior.

## What Changes

- Make ETA rendering unit-safe: renderers display only explicit `eta_seconds` and never reinterpret arbitrary `current`/`total` workload units as seconds.
- Keep segment-derived workload responsible for estimated percentage while using compatible historical RTF evidence for the initial ETA.
- Recalibrate long-form ETA after each committed chunk using this run's observed processing rate blended with compatible history.
- Smooth and bound within-chunk ETA updates so early sparse segment progress cannot create extreme jumps or implausible completion times.
- Suppress ETA when no compatible or sufficiently reliable time estimate exists, while continuing to show elapsed time and estimated segment percentage when available.
- Add unit, renderer, workflow, resume, fallback, and representative long-form accuracy regression coverage.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `job-progress-reporting`: Define unit-safe ETA semantics, explicit time-estimate ownership, reliability fallback, and consistent plain/rich rendering.
- `asr-segment-progress`: Separate segment-derived percentage from time ETA and require compatible historical or calibrated runtime evidence for ETA updates.
- `long-form-transcription`: Recalibrate remaining time at chunk checkpoints and correctly account for resumed completed work.

## Impact

- Affected code: progress event emission, plain/rich render snapshots, performance-profile estimation, and long-form transcription progress coordination.
- Affected persisted data: existing performance profile samples remain readable; no transcript or checkpoint identity change is required unless estimator metadata is added.
- Affected user experience: ETA becomes an explicitly estimated remaining duration, may be absent until reliable evidence exists, and should converge as chunks complete.
- No changes to model invocation, VAD segmentation, ASR output, timestamps, cache keys, SRT generation, or CLI arguments.
