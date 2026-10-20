# Spec Delta

## MODIFIED Requirements

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
