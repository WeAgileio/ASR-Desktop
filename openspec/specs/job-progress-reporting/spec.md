# job-progress-reporting Specification

## Purpose
TBD - created by archiving change add-asr-progress-reporting. Update Purpose after archive.
## Requirements
### Requirement: Structured phase lifecycle
The system SHALL represent every user-visible processing phase with structured lifecycle events containing phase, status, message, elapsed time, and progress kind.

#### Scenario: A phase completes normally
- **WHEN** a processing phase begins and finishes successfully
- **THEN** the system emits a running event followed by exactly one completed terminal event for that phase

#### Scenario: A phase fails
- **WHEN** an exception prevents a running phase from completing
- **THEN** the system emits a failed terminal event before propagating the failure through the existing error path

#### Scenario: Work is bypassed by cache
- **WHEN** a cache hit means a phase is not executed
- **THEN** the system emits a skipped terminal event with a human-readable reason and does not report a fabricated 100% run

### Requirement: Truthful progress semantics
The system MUST classify progress as `actual`, `estimated`, or `indeterminate` and SHALL NOT present estimated or batch-local measurements as actual whole-job progress.

#### Scenario: A reliable total is available
- **WHEN** a producer supplies a stable total and globally scoped current value
- **THEN** the system reports actual progress with bounded, monotonically non-decreasing values

#### Scenario: Only an estimate is available
- **WHEN** progress is derived from historical timing rather than direct work measurements
- **THEN** the renderer labels both percentage and ETA as estimated and keeps estimated completion below 100% until the phase completes

#### Scenario: No reliable measurement is available
- **WHEN** neither globally scoped measurements nor a compatible estimate exists
- **THEN** the system reports indeterminate progress with elapsed time instead of inventing a percentage or ETA

### Requirement: Exact media extraction progress
The system SHALL report audio-extraction progress from FFmpeg's processed media timestamp divided by the probed source duration when that duration is valid.

#### Scenario: FFmpeg provides media timestamps
- **WHEN** FFmpeg reports an output media timestamp for an input with a valid duration
- **THEN** the system emits actual progress using media time as current and input duration as total

#### Scenario: Source duration is unavailable
- **WHEN** the source duration cannot be determined reliably
- **THEN** extraction remains functional and is shown as indeterminate with elapsed time

#### Scenario: FFmpeg reaches the source duration before successful exit
- **WHEN** the observed media timestamp reaches the probed duration but FFmpeg has not yet exited successfully and output validation has not completed
- **THEN** the phase does not emit completed or display 100%

### Requirement: Adapter-aware ASR progress
The system SHALL accept ASR progress through the adapter contract and treat it as actual only when the adapter declares that the values cover the complete input.

#### Scenario: Adapter exposes global progress
- **WHEN** an adapter guarantees globally scoped current and total values for the complete audio input
- **THEN** the ASR phase reports those values as actual progress

#### Scenario: FunASR callback is batch-local
- **WHEN** FunASR integrated VAD or batching resets callback counters for internal batches
- **THEN** the system does not reinterpret those counters as whole-file percentage and instead uses estimated or indeterminate ASR progress

#### Scenario: ASR remains active without callbacks
- **WHEN** the model call provides no reliable progress callbacks for an extended period
- **THEN** the user continues to see an active indicator and increasing elapsed time

### Requirement: Historical ASR ETA
The system SHALL persist compatible ASR real-time-factor samples from successful uncached transcriptions and MAY use them to estimate later ASR duration.

#### Scenario: Compatible history is sufficient
- **WHEN** sufficient valid samples exist for the same model revision, device/backend, and runtime identity
- **THEN** the system may show an explicitly estimated percentage and ETA based on audio duration and historical RTF

#### Scenario: History is absent or incompatible
- **WHEN** no sufficient compatible samples exist
- **THEN** the ASR phase is indeterminate and no ETA is shown

#### Scenario: Performance profile is corrupt
- **WHEN** the stored performance profile cannot be parsed or validated
- **THEN** the system ignores it, continues transcription, and starts rebuilding valid history without invalidating the transcript cache

#### Scenario: Transcription does not produce a valid sample
- **WHEN** ASR fails, is cancelled, is served from cache, or the input is too short to be representative
- **THEN** the run is excluded from the RTF history

### Requirement: Terminal-aware rendering
The CLI SHALL support automatic, rich TTY, plain-text, and disabled progress modes without changing processing behavior.

#### Scenario: Auto mode runs in an interactive TTY
- **WHEN** `--progress auto` is selected and stdout is an interactive terminal
- **THEN** the CLI uses a bounded live display that updates phases in place

#### Scenario: Auto mode output is redirected
- **WHEN** `--progress auto` is selected and stdout is not an interactive terminal
- **THEN** the CLI emits throttled plain-text lifecycle lines without ANSI control sequences

#### Scenario: Progress rendering is disabled
- **WHEN** `--progress off` is selected
- **THEN** the CLI suppresses progress presentation while preserving transcription, error handling, cache behavior, and valid performance sampling

### Requirement: Single coordinated progress display
The system MUST prevent dependency-native progress bars from competing with the application renderer.

#### Scenario: FunASR supports disabling its progress bar
- **WHEN** an ASR request is made through a FunASR adapter
- **THEN** the adapter disables FunASR's native tqdm output and routes usable measurements through the application progress contract

#### Scenario: Plain renderer reports a long-running phase
- **WHEN** a phase remains running longer than the configured heartbeat interval
- **THEN** the renderer emits at most one heartbeat per interval plus lifecycle changes, avoiding unbounded high-frequency log output

