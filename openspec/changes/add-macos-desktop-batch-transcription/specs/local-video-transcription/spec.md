# Spec Delta

## MODIFIED Requirements

### Requirement: Resolve an Apple Silicon inference device
The system SHALL support auto, mps, and cpu choices, with GPU in the desktop interface mapping to mps. Auto SHALL select MPS only with sufficient compatible evidence satisfying performance, quality, and resource gates; otherwise it SHALL select CPU and explain why. A recognized MPS compatibility failure in auto SHALL trigger one reported CPU retry. Explicit choices SHALL never be silently overridden.

#### Scenario: Auto mode uses MPS
- **WHEN** MPS is available and sufficient compatible evidence demonstrates a safe performance benefit for the selected model and workload
- **THEN** auto selects MPS, records the evidence-based reason, and records mps as the resolved inference device if execution succeeds

#### Scenario: Auto mode falls back to CPU
- **WHEN** MPS is unavailable or an auto-selected MPS attempt produces a recognized compatibility failure
- **THEN** the system explains the CPU selection and, if an MPS attempt actually failed, releases that attempt and retries once on CPU without repeatedly switching devices

#### Scenario: Explicit MPS fails
- **WHEN** the user explicitly selects mps and inference cannot run on MPS
- **THEN** the system reports the MPS failure and does not silently change to CPU

#### Scenario: Evidence is insufficient
- **WHEN** compatible device evidence is absent, corrupt, stale, or insufficient
- **THEN** auto uses CPU with an insufficient-evidence reason even if MPS is available

#### Scenario: Explicit CPU is selected
- **WHEN** the user explicitly selects cpu
- **THEN** all required inference runs on CPU regardless of any GPU benchmark advantage

#### Scenario: Failure is unrelated to MPS compatibility
- **WHEN** execution encounters a source error, output permission failure, disk-full condition, or unclassified exception
- **THEN** the system reports that failure without treating it as permission to retry on a different device

## ADDED Requirements

### Requirement: Scope device evidence to the actual environment
Device evidence SHALL identify hardware and memory, OS and inference runtime versions, immutable model and auxiliary-asset revisions, recognition settings, loading policy, duration range, and decision-policy version. Records missing required identity or incompatible with the current workload SHALL not influence automatic device selection.

#### Scenario: Runtime or model changes
- **WHEN** a model snapshot, runtime component, or relevant environment identity changes
- **THEN** the old evidence no longer qualifies for automatic selection under the new combination

#### Scenario: Short recording has a fast GPU result
- **WHEN** GPU evidence exists only for short recordings but the new input belongs to a longer duration range
- **THEN** that evidence alone does not authorize automatic GPU selection for the longer recording

### Requirement: Qualify measurements before changing automatic defaults
Automatic selection SHALL use successful, uncached, non-resumed, representative inference samples and robust comparable timing. Promotion to GPU SHALL require sufficient CPU and GPU samples, a meaningful performance benefit, a validated quality and timestamp baseline, and passing resource measurements. Unknown resource values SHALL not be treated as passing.

#### Scenario: Default promotion threshold is met
- **WHEN** each device has at least three valid samples of at least 30 seconds for the applicable workload, the GPU median comparable processing cost is at least 10 percent lower, and all baseline and resource gates pass
- **THEN** GPU is eligible for automatic selection and the reason identifies the evidence and policy used

#### Scenario: Fast sample has missing resource data
- **WHEN** a successful GPU sample lacks required memory-pressure or swap measurements
- **THEN** it does not qualify for automatic GPU promotion, although the user can still explicitly choose GPU

#### Scenario: Run does not measure representative work
- **WHEN** a run is served from cache, resumes partial work, fails, is cancelled, or is too short
- **THEN** it is excluded from automatic device-comparison samples

### Requirement: Explain and deliberately bootstrap device evidence
The system SHALL expose the selection reason and provide explicit local CPU/GPU calibration through GUI and CLI. Calibration SHALL use the same sample and comparable settings for both devices, preserve user media, and remain scoped to its actual workload. It SHALL not silently duplicate a user's full transcription to obtain evidence.

#### Scenario: User requests calibration
- **WHEN** the user explicitly starts calibration on a local sample
- **THEN** both devices are evaluated under comparable conditions and the result reports limitations, failures, and evidence eligibility without uploading the sample

#### Scenario: No calibration was requested
- **WHEN** auto has insufficient evidence for a submitted job
- **THEN** it performs the job using the conservative policy without running a hidden second full-file benchmark

### Requirement: Invalidate failed GPU compatibility evidence
A recognized MPS compatibility failure SHALL disqualify automatic GPU selection for the affected environment and model combination until explicit revalidation succeeds. Prior successful timings SHALL not immediately re-enable the failed combination.

#### Scenario: Later task follows a GPU compatibility failure
- **WHEN** a new auto task matches the combination that just failed on MPS
- **THEN** it uses CPU and exposes the compatibility-failure reason until revalidation establishes eligibility again
