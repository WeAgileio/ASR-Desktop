# asr-segment-progress Specification

## Purpose
TBD - created by archiving change add-global-asr-segment-progress. Update Purpose after archive.
## Requirements
### Requirement: Stable whole-input segment workload
The system SHALL derive a stable whole-input transcription workload only after VAD has produced the complete set of valid speech segments for the input.

#### Scenario: VAD produces valid speech segments
- **WHEN** VAD completes with speech segments whose start and end times are valid
- **THEN** the adapter reports a fixed total workload equal to the sum of all segment durations

#### Scenario: No valid segment total is available
- **WHEN** VAD output is empty, malformed, non-finite, or cannot be mapped reliably to the ASR schedule
- **THEN** the adapter emits no segment-derived percentage and transcription continues using the configured fallback progress behavior

### Requirement: Duration-weighted estimated progress
The system MUST calculate segment-derived transcription progress from completed speech duration rather than treating every segment or dynamic batch as equal work, and MUST classify the result as `estimated`.

#### Scenario: A scheduled ASR batch completes
- **WHEN** a main ASR batch completes successfully for one or more globally tracked VAD segments
- **THEN** the adapter increases current workload by the tracked durations of those segments while retaining the fixed whole-input total

#### Scenario: Segments have unequal durations
- **WHEN** completed segments have different durations
- **THEN** each segment contributes to progress in proportion to its speech duration rather than contributing one equal count

#### Scenario: Internal callback counters reset
- **WHEN** FunASR reports batch-local current and total values that restart for an internal inference call
- **THEN** the system does not expose those counters as whole-input transcription progress

### Requirement: Bounded and monotonic segment estimates
Within one transcription attempt, the system SHALL emit segment-derived current values that are bounded by a positive stable total and monotonically non-decreasing.

#### Scenario: Multiple dynamic batches complete
- **WHEN** FunASR groups globally tracked segments into multiple batches of different sizes
- **THEN** emitted estimated progress remains monotonically non-decreasing across all batch boundaries

#### Scenario: All tracked ASR segments have completed
- **WHEN** the final tracked ASR batch returns but transcript processing has not completed successfully
- **THEN** running progress remains below 100 percent

#### Scenario: The transcript completes successfully
- **WHEN** the adapter returns a valid Transcript and the workflow completes the transcription phase
- **THEN** the workflow emits the terminal completed state at 100 percent

### Requirement: Observation must not affect transcription
The system MUST preserve FunASR input parameters, VAD segmentation, batch scheduling, model results, timestamps, normalization, and cache identity when segment progress observation is enabled or disabled.

#### Scenario: Observation is supported
- **WHEN** the installed FunASR runtime supports the validated observation integration
- **THEN** enabling progress produces the same transcript content and timestamps as running without progress observation

#### Scenario: Observation fails or is unsupported
- **WHEN** the runtime shape is incompatible or the observation data becomes inconsistent
- **THEN** the system removes or disables the observer, continues transcription, and falls back without treating the progress problem as a job failure

### Requirement: Retry-scoped progress measurements
The system SHALL keep segment workloads scoped to a single model execution attempt and MUST NOT combine completed work across a failed device attempt and its retry.

#### Scenario: MPS falls back to CPU
- **WHEN** an MPS transcription attempt fails with a compatible fallback error and restarts on CPU
- **THEN** the CPU attempt creates a new segment progress epoch and does not add MPS completed workload to the CPU measurement

### Requirement: Progress fallback hierarchy
The system SHALL prefer a valid whole-input segment estimate for transcription percentage, otherwise use a compatible historical RTF estimate, and otherwise report indeterminate progress.

#### Scenario: Segment workload is available
- **WHEN** valid whole-input segment measurements are emitted
- **THEN** the workflow uses them as the estimated transcription percentage and MAY use compatible historical RTF data for ETA

#### Scenario: Segment workload is unavailable but compatible history exists
- **WHEN** no valid segment measurement is available and a compatible historical RTF estimate exists
- **THEN** the workflow continues to show the existing time-based estimated percentage and ETA

#### Scenario: Neither measurement is available
- **WHEN** neither valid segment workload nor compatible historical RTF history is available
- **THEN** transcription remains indeterminate with an active indicator and elapsed time

