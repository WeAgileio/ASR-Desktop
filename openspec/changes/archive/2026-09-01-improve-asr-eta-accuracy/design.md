## Context

Progress events carry two different concepts: a workload fraction (`current`, `total`, and `unit`) and a remaining wall-clock estimate (`eta_seconds`). Segment-derived ASR progress uses speech or media duration measured in milliseconds, while the renderer's estimated snapshot currently compares those values with elapsed seconds and replaces `eta_seconds` with `total - current`. This produces correct-looking percentages but ETAs that are inflated by roughly 1000× for long-form jobs.

The application already persists compatible RTF samples by model id, model revision, device, and runtime. Long-form jobs also persist chunk transcripts containing per-chunk processing time, so completed checkpoints provide content-specific evidence that can improve the estimate without changing recognition or cache identity.

## Goals / Non-Goals

**Goals:**

- Enforce one unit-safe contract from workflow through plain and rich renderers.
- Preserve segment-derived percentage independently from ETA.
- Produce an initial ETA from compatible historical RTF evidence when available.
- Make long-form ETA converge by recalibrating after committed chunks and by smoothly updating within a chunk.
- Resume with an ETA based only on unfinished work while reusing valid checkpoint timing evidence.
- Prefer no ETA over an unsupported or dimensionally invalid number.

**Non-Goals:**

- Changing FunASR arguments, VAD segmentation, model scheduling, timestamps, transcript normalization, or subtitle output.
- Promising exact completion time for every audio density, machine load, or thermal state.
- Adding a remote telemetry or benchmark service.
- Invalidating transcript caches or existing long-form checkpoints.

## Decisions

### 1. Treat `eta_seconds` as the authoritative ETA value

`ProgressEvent.current` and `total` remain workload values interpreted only with `unit`. `ProgressEvent.eta_seconds` is the sole remaining-time value and is always seconds. Renderers MUST NOT derive ETA from `total - current` for arbitrary units or compare elapsed seconds with non-second workload values.

For a running heartbeat, a renderer may decrement a supplied `eta_seconds` by wall-clock time since receipt. It may advance `current` from elapsed time only for an explicitly time-based estimate whose unit is seconds. Segment, item, token, and millisecond workload snapshots remain unchanged until the producer emits another event.

This keeps formatting presentation-only and prevents the plain and rich renderers from implementing competing estimators.

**Alternative considered:** Convert every progress event to seconds before rendering. Rejected because actual extraction progress and segment workload have useful native units and are not interchangeable with compute time.

### 2. Keep percentage and ETA as independent signals

The priority for percentage remains:

1. globally scoped actual adapter progress;
2. valid whole-input segment-derived estimated progress;
3. compatible historical time-based estimated progress;
4. indeterminate elapsed-only progress.

ETA follows a separate priority:

1. calibrated remaining-time estimate from committed work plus compatible history;
2. compatible historical RTF estimate;
3. absent.

A segment callback updates percentage but does not manufacture seconds from speech-duration units. The workflow attaches the latest valid `eta_seconds` to the event. If no valid estimate exists, percentage may still be shown without ETA.

### 3. Use compatible historical RTF as the prior

The initial estimate is:

`predicted_total_seconds = historical_rtf × source_audio_seconds`

Compatibility remains model id, resolved revision, device, and runtime identity. At least the existing minimum sample count is required. Invalid, corrupt, non-finite, or implausible samples are ignored. Existing version-1 performance profiles remain readable and require no migration.

The estimator uses a robust statistic over bounded recent samples rather than a single last run. Recorded local traces become regression fixtures so selection changes can be assessed against real variability.

**Alternative considered:** Always use the latest sample. Rejected because temporary CPU load and thermal throttling would make the next estimate unstable.

### 4. Recalibrate long-form ETA at chunk checkpoints

For each committed chunk, use the chunk transcript's processing duration and unique non-overlap audio duration to calculate cumulative observed RTF. Blend it with the historical prior according to the proportion of unique source duration committed:

`effective_rtf = prior_rtf × (1 - confidence) + observed_rtf × confidence`

where `confidence` is bounded and increases with committed source duration. If no prior exists, the first valid committed chunk establishes the estimate. The remaining estimate is based on unfinished unique duration, so overlap is not double-counted.

For resume, valid checkpoint processing metadata contributes to observed RTF, but checkpoint audio duration is excluded from remaining work. Model load and final merge overhead may be represented by small measured or historical fixed components when evidence exists; otherwise they remain outside the numeric ETA rather than being guessed.

**Alternative considered:** Project `elapsed / segment_fraction` continuously. Rejected because very small early fractions amplify noise into multi-hour estimates and segment speech duration is not perfectly proportional to compute cost.

### 5. Smooth within-chunk updates without hiding checkpoint evidence

Within a chunk, the latest effective RTF is applied to the remaining workload implied by valid segment progress. ETA updates use a bounded smoother to avoid oscillation caused by dynamic batching. Normal wall-clock countdown continues between producer events. A completed checkpoint is allowed to recalibrate immediately because it is materially stronger evidence.

The estimator never allows a running ETA to reach zero before successful completion. Non-finite, negative, dimensionally invalid, or grossly implausible results are discarded and the UI falls back to no ETA.

### 6. Measure accuracy with replayable traces

Tests include dimension checks and deterministic replay traces containing source duration, event units, chunk boundaries, processing seconds, segment fractions, resume state, and final completion time. For the repository's compatible recorded traces, initial and checkpoint ETA accuracy is evaluated with absolute percentage error; the target is median error at or below 20% after compatible evidence is available, while unit-safety and no-fabrication rules remain hard requirements.

This metric is a regression gate for known traces, not a universal SLA for every recording.

## Risks / Trade-offs

- [Historical RTF varies with speech density, CPU contention, and thermal state] → Use robust recent history and progressively weight content-specific committed chunks.
- [Smoothing can make ETA react too slowly] → Permit immediate checkpoint recalibration and smooth only lower-confidence within-chunk updates.
- [ETA may increase during a slower-than-history run] → Allow honest increases, label the value estimated, and prevent abrupt oscillation rather than forcing monotonic decrease.
- [Checkpoint processing metadata may come from an older interrupted session] → Require existing checkpoint identity compatibility and use it only for the same model, device, runtime-sensitive job identity.
- [A strict accuracy threshold could encourage overfitting to current samples] → Keep dimensional correctness and fallback behavior primary; use replay traces from multiple durations and content densities.

## Migration Plan

1. Add unit-safe renderer behavior while preserving the current `ProgressEvent` public fields.
2. Introduce the workflow ETA estimator behind existing compatible performance-profile loading.
3. Connect short-form segment events and long-form chunk/resume events to explicit `eta_seconds`.
4. Run unit, workflow, renderer, resume, and trace-replay regression tests.
5. Existing profile and checkpoint files remain valid; rollback restores the prior presentation logic without data conversion.

## Open Questions

- Whether the CLI should later display an uncertainty range (for example `~18–24 min`) instead of a single estimated duration. This change keeps the existing single-value interface.
