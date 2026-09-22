## ADDED Requirements

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
