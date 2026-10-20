# Spec Delta

## Purpose

Prepare supported transcription models after application installation and keep complete, verified, versioned assets available to both desktop and command-line jobs without inference-time downloads.

## ADDED Requirements

### Requirement: Describe complete supported model snapshots
The system SHALL expose a versioned catalog for fun-asr-nano and paraformer containing immutable model revisions, all required auxiliary assets, expected sizes, and integrity hashes. Floating branch names or the presence of a few files SHALL NOT establish snapshot identity or readiness.

#### Scenario: Model requires auxiliary assets
- **WHEN** a selected model also needs VAD, punctuation, tokenizer, or configuration assets
- **THEN** the preparation plan includes all those assets and reports their combined download and storage requirements

#### Scenario: Cached folder is incomplete
- **WHEN** only primary weights and configuration exist but other required assets are absent
- **THEN** the snapshot is not reported as ready

### Requirement: Download models through either interface
The GUI and CLI SHALL start and observe downloads in one shared model store. Downloads SHALL begin only after a user requests preparation, SHALL report progress and failures separately from transcription, and SHALL not duplicate a concurrent download of the same snapshot.

#### Scenario: Both clients request the same model
- **WHEN** the window and CLI request the same snapshot concurrently
- **THEN** they observe one preparation operation and reuse the same downloaded assets

#### Scenario: Network is unavailable
- **WHEN** a requested model cannot be downloaded
- **THEN** the system reports a recoverable preparation failure without substituting another model or starting inference

### Requirement: Resume downloads without trusting stale partial files
The system SHALL preserve verified completed assets and eligible partial transfers after interruption. A partial file SHALL be resumed only if remote asset identity and range support are validated; otherwise that file SHALL restart while other verified assets remain reusable.

#### Scenario: Interrupted transfer can resume
- **WHEN** a download is retried and the source still represents the same asset with supported range requests
- **THEN** transfer resumes from the validated partial offset

#### Scenario: Source identity changed or ranges are unsupported
- **WHEN** a partial file cannot be safely resumed
- **THEN** that asset is downloaded again and the final content must still match the catalog hash

### Requirement: Publish readiness only after complete verification
A snapshot SHALL become ready only after every required asset passes integrity and completeness checks. Insufficient storage, checksum mismatch, or interrupted publication SHALL leave it unavailable for inference and SHALL not damage a previously ready snapshot.

#### Scenario: Storage is insufficient
- **WHEN** free space cannot accommodate the remaining transfer and preparation workspace
- **THEN** preparation reports the capacity requirement without presenting a partial snapshot as ready

#### Scenario: Integrity verification fails
- **WHEN** any downloaded asset differs from its expected hash
- **THEN** the asset is rejected, retry is offered, and jobs cannot load the failed snapshot

#### Scenario: Publication is interrupted
- **WHEN** the process exits before readiness is committed
- **THEN** the next launch verifies or completes preparation before advertising the snapshot as usable

### Requirement: Run prepared models entirely offline
Ready snapshots SHALL contain all assets needed by the bundled runtime. Inference SHALL use only the selected local snapshot and SHALL not fetch missing assets, check for model updates, install dependencies, or upload user data. Missing or damaged assets SHALL produce a model-readiness error.

#### Scenario: Outbound network is disabled
- **WHEN** a ready supported model is used to transcribe local recorded media with network access blocked
- **THEN** extraction, inference, and requested exports can complete

#### Scenario: Asset is removed after preparation
- **WHEN** execution discovers that a required asset is missing or damaged
- **THEN** the snapshot is marked unready and the user is directed to repair it without a hidden download during transcription

### Requirement: Pin model versions for accepted jobs
Accepted jobs SHALL retain the selected immutable snapshot even when a newer catalog or snapshot becomes available. A missing pinned snapshot SHALL block that job visibly until the exact snapshot is prepared, without occupying the transcription slot or silently switching versions.

#### Scenario: Model update arrives while jobs are queued
- **WHEN** a new model version is made available after batch submission
- **THEN** accepted jobs continue to reference their original snapshot and new jobs can select the new version

#### Scenario: Pinned snapshot becomes ready
- **WHEN** preparation of the exact snapshot required by a blocked job succeeds
- **THEN** that job can join the ready queue subject to the persisted queue pause state

### Requirement: Remove snapshots without disrupting accepted work
Model removal SHALL report storage usage and refuse to delete snapshots referenced by nonterminal jobs or active preparation. Completed or cancelled history SHALL not permanently prevent removal, but retry SHALL require the original snapshot again. Removing a model SHALL not delete source media or exported results.

#### Scenario: Queued job references a snapshot
- **WHEN** the user requests removal of that snapshot
- **THEN** the system refuses deletion and identifies the jobs that still require it

#### Scenario: Only historical jobs reference a snapshot
- **WHEN** the user removes that unused snapshot
- **THEN** its model files are removed while history and outputs remain, and a later retry explains any required redownload
