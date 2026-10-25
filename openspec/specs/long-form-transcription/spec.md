# long-form-transcription Specification

## Purpose

讓長音訊轉錄透過可重現的分段計畫、模型工作階段重用與可恢復的分段檢查點持續執行，將結果合併至一致的全域時間軸，並提供可信的進度與剩餘時間估計；效能與裝置選擇以相容的品質、穩定性及資源證據為依據。

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
For auto selection, the system SHALL use sufficient compatible evidence for the selected model, actual environment, loading policy, and long-form duration range. GPU eligibility SHALL satisfy the shared performance, quality, and resource gates. Insufficient evidence SHALL select CPU. Explicit choices SHALL remain authoritative, and recognized auto MPS failures SHALL retain the one-time CPU fallback with compatible-checkpoint recovery.

#### Scenario: Comparable CPU and MPS profiles exist
- **WHEN** sufficient valid long-form profiles exist for the same immutable model snapshot, environment, recognition settings, loading policy, and duration range on both devices
- **THEN** auto selects MPS only if its robust comparable cost improves upon CPU by the required margin and its stability, quality, timestamp, and resource gates pass; otherwise it selects CPU

#### Scenario: Compatible evidence is insufficient
- **WHEN** no sufficient comparable long-form evidence exists
- **THEN** the system uses CPU and clearly records that the selection was a conservative default rather than a benchmark-derived GPU choice

#### Scenario: The user explicitly selects a device
- **WHEN** the user chooses cpu or mps explicitly
- **THEN** benchmark profiles do not override that choice

#### Scenario: Only short calibration evidence exists
- **WHEN** a long recording is submitted after successful short-sample calibration
- **THEN** short-sample evidence does not qualify the GPU for automatic selection in the long recording's duration range

#### Scenario: GPU failure changes checkpoint compatibility
- **WHEN** auto falls back from MPS to CPU during a long-form attempt
- **THEN** the system reuses only checkpoints valid for the CPU-compatible attempt and does not combine incompatible GPU results with new CPU chunks

### Requirement: Gate performance tuning on quality and resources
The system MUST NOT adopt a long-form batching, VAD, model, or device default solely because it is faster; candidate settings SHALL satisfy transcript, timestamp, measured memory, and stability acceptance criteria against a recorded baseline. Unavailable required resource measurements SHALL be recorded as unknown and SHALL not qualify a candidate for automatic adoption.

#### Scenario: A candidate improves RTF safely
- **WHEN** a candidate produces the required RTF improvement without unacceptable transcript or timestamp regression, sustained swap growth, memory-limit violation, or failed chunks and required measurements are available
- **THEN** the evaluation report marks it eligible for adoption within its measured environment and workload range

#### Scenario: A faster candidate violates a guardrail
- **WHEN** a candidate is faster but violates any configured quality, memory, or stability threshold
- **THEN** the existing safe default remains unchanged and the rejection reason is recorded

#### Scenario: Resource measurements are unavailable
- **WHEN** a long-form candidate lacks a required memory-pressure or swap observation
- **THEN** transcription can still finish, the observation is marked unknown, and the sample is ineligible for automatic default promotion

#### Scenario: Resumed work appears faster
- **WHEN** a run skips previously committed chunks or uses a completed transcript cache
- **THEN** it does not become a full-workload device-comparison sample merely because its elapsed time is low

### Requirement: Checkpoint-calibrated long-form ETA
The system SHALL recalibrate long-form remaining time from compatible historical RTF evidence and processing evidence from successfully committed chunks. Remaining work MUST use unique non-overlap source duration so planned overlap is not counted twice.

#### Scenario: Compatible history exists before the first chunk
- **WHEN** a long-form transcription begins with sufficient compatible RTF history
- **THEN** the system supplies an explicitly estimated ETA based on source duration and historical RTF

#### Scenario: A chunk is committed
- **WHEN** a chunk completes with valid processing duration and source-boundary metadata
- **THEN** the system blends the observed committed-work rate with compatible prior evidence and recalculates ETA for unfinished unique source duration

#### Scenario: No history exists and the first chunk completes
- **WHEN** a long-form job starts without sufficient compatible history and commits its first valid chunk
- **THEN** the system may begin displaying ETA based on committed-work evidence for the remaining chunks

### Requirement: Resume-aware remaining time
The system SHALL exclude valid completed checkpoints from remaining ETA work while retaining their compatible processing metadata as calibration evidence.

#### Scenario: A job resumes with valid checkpoints
- **WHEN** long-form transcription resumes with one or more compatible completed chunk checkpoints
- **THEN** ETA covers only pending unique source duration and may use the completed checkpoints' processing durations to calibrate the remaining rate

#### Scenario: Checkpoint evidence is incompatible or invalid
- **WHEN** checkpoint identity, timing metadata, checksum, or chunk boundaries are incompatible or invalid
- **THEN** the system excludes that checkpoint from ETA calibration and applies the existing safe checkpoint recovery behavior

### Requirement: Stable within-chunk ETA updates
The system SHALL smooth lower-confidence ETA updates within a running chunk while allowing materially stronger committed-chunk evidence to recalibrate the estimate.

#### Scenario: Dynamic batches produce uneven progress intervals
- **WHEN** segment progress advances unevenly within a chunk because of VAD or dynamic batching
- **THEN** displayed ETA avoids abrupt oscillation while continuing to count down between valid producer updates

#### Scenario: Current chunk is slower than historical evidence
- **WHEN** committed-chunk evidence indicates a slower processing rate than the historical prior
- **THEN** ETA is allowed to increase to an honest recalibrated value and remains explicitly marked estimated
