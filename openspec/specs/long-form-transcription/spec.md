# long-form-transcription Specification

## Purpose
TBD - created by archiving change optimize-long-form-transcription. Update Purpose after archive.
## Requirements
### Requirement: Instrument long-form transcription stages
The system SHALL measure model loading, VAD or chunk planning, ASR inference, result normalization, and merge time separately for uncached long-form jobs.

#### Scenario: A long-form job completes
- **WHEN** an uncached long-form transcription finishes successfully
- **THEN** the evaluation record contains separate stage durations, total duration, audio duration, speech or planned chunk duration, model revision, resolved device, RTF, and peak process memory

#### Scenario: Resource metrics are unavailable
- **WHEN** the operating system does not expose a supported memory-pressure or swap measurement
- **THEN** transcription continues and the unavailable metric is recorded explicitly rather than fabricated

### Requirement: Produce a deterministic long-form chunk plan
For input exceeding the configured long-form threshold, the system SHALL create an ordered deterministic chunk plan that covers the complete audio timeline, prefers silence near each target boundary, and records every chunk's global start and end time.

#### Scenario: Silence exists near a target boundary
- **WHEN** a valid silence interval occurs inside the configured boundary search window
- **THEN** the planner places the chunk boundary at a deterministic point within that silence interval

#### Scenario: No suitable silence exists
- **WHEN** no valid silence interval occurs inside the boundary search window
- **THEN** the planner uses a deterministic fallback boundary with bounded overlap sufficient for boundary reconciliation

#### Scenario: The same compatible input is planned again
- **WHEN** source identity and chunk-planning settings are unchanged
- **THEN** the system produces the same ordered chunk boundaries and plan identity

### Requirement: Reuse one model session across chunks
The system SHALL load one model session for a sequential long-form attempt and reuse it for all pending compatible chunks in that attempt.

#### Scenario: Multiple chunks require recognition
- **WHEN** a long-form job has more than one uncached chunk
- **THEN** the selected model and device are initialized once and each pending chunk is transcribed sequentially through that session

#### Scenario: Device fallback restarts the attempt
- **WHEN** an auto-selected MPS session fails with a recognized compatibility error
- **THEN** the system closes that session, initializes one CPU session, and resumes from the first chunk without a valid completed checkpoint for the CPU-compatible attempt

### Requirement: Persist resumable chunk checkpoints
The system SHALL atomically persist each successfully normalized chunk transcript with its global boundary, checkpoint schema version, source identity, audio preprocessing identity, chunk-plan identity, model revision, device compatibility identity, language, hotwords, and recognition-affecting settings.

#### Scenario: A chunk completes successfully
- **WHEN** a chunk produces valid normalized text and timestamps
- **THEN** its checkpoint is written atomically before the next chunk begins

#### Scenario: A long-form run is interrupted
- **WHEN** the process terminates after one or more chunk checkpoints were committed
- **THEN** the next compatible run skips those chunks and resumes at the first chunk without a valid checkpoint

#### Scenario: A checkpoint is corrupt or incompatible
- **WHEN** checkpoint parsing fails or any recognition-affecting identity differs
- **THEN** the system ignores that checkpoint, retranscribes the affected chunk, and does not treat the condition as a valid cache hit

### Requirement: Merge chunk transcripts onto the global timeline
The system MUST convert chunk-local timestamps to the source-global timeline, reconcile bounded overlap deterministically, and emit one valid common Transcript with ordered non-overlapping units bounded by the source duration.

#### Scenario: Adjacent chunks have no overlap
- **WHEN** two adjacent chunks meet at a silence-selected boundary without overlap
- **THEN** their timestamped units are offset and concatenated in global chronological order

#### Scenario: Adjacent chunks contain overlap
- **WHEN** fallback planning causes adjacent chunks to recognize overlapping audio
- **THEN** the merger removes duplicated boundary units using timestamps and normalized text while preserving unique speech from both chunks

#### Scenario: Boundary reconciliation is ambiguous
- **WHEN** overlapping outputs cannot be reconciled without risking silent text loss
- **THEN** the merger preserves the competing unique units, enforces a valid monotonic timeline, and records a diagnostic for later review

### Requirement: Report resumable long-form progress truthfully
The system SHALL report completed and resumed chunks, current chunk boundaries, elapsed time, and an explicitly estimated whole-transcription percentage weighted by planned audio duration.

#### Scenario: Compatible checkpoints are loaded
- **WHEN** a resumed job starts with valid completed chunk checkpoints
- **THEN** the transcription phase reports the resumed completed duration and identifies the number of skipped completed chunks

#### Scenario: A chunk is running
- **WHEN** recognition is active for one chunk
- **THEN** the system combines committed chunk duration with valid adapter progress for the current chunk without presenting the estimate as actual whole-job progress

#### Scenario: All chunks are committed but merge is pending
- **WHEN** every chunk checkpoint exists but final merge and transcript validation have not succeeded
- **THEN** running progress remains below 100 percent

### Requirement: Select long-form device from compatible evidence
For `auto` device selection, the system SHALL prefer a device with sufficient compatible long-form performance evidence for the explicitly selected model and SHALL retain the existing safe fallback when evidence is absent or execution fails.

#### Scenario: Comparable CPU and MPS profiles exist
- **WHEN** sufficient valid long-form profiles exist for the same model revision and runtime on both devices
- **THEN** auto mode selects the device with the lower robust RTF that has not violated configured stability or memory guardrails

#### Scenario: Compatible evidence is insufficient
- **WHEN** no device has sufficient comparable long-form evidence
- **THEN** the system uses the configured conservative default and clearly records that the selection was not benchmark-derived

#### Scenario: The user explicitly selects a device
- **WHEN** the user chooses `cpu` or `mps` explicitly
- **THEN** benchmark profiles do not override that choice

### Requirement: Gate performance tuning on quality and resources
The system MUST NOT adopt a long-form batching, VAD, model, or device default solely because it is faster; candidate settings SHALL satisfy transcript, timestamp, memory, and stability acceptance criteria against a recorded baseline.

#### Scenario: A candidate improves RTF safely
- **WHEN** a candidate produces the required RTF improvement without unacceptable transcript or timestamp regression, sustained swap growth, memory-limit violation, or failed chunks
- **THEN** the evaluation report marks it eligible for adoption

#### Scenario: A faster candidate violates a guardrail
- **WHEN** a candidate is faster but violates any configured quality, memory, or stability threshold
- **THEN** the existing default remains unchanged and the rejection reason is recorded

