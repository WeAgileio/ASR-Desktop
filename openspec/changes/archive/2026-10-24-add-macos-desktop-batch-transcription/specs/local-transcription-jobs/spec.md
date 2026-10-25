# Spec Delta

## Purpose

Manage durable local batches of recorded audio and video, including source validation, controlled sequential execution, recoverable attempts, and reliable delivery of transcripts and subtitles.

## ADDED Requirements

### Requirement: Preview and submit local media batches
The system SHALL accept multiple local audio files, video files, and folders, with explicit recursive folder discovery. It SHALL preview discovered sources and planned output paths, deduplicate overlapping source paths within a submission, and report invalid or unsupported entries without modifying source media.

#### Scenario: Overlapping folders are submitted
- **WHEN** selected files and recursively selected folders include the same canonical source path
- **THEN** the preview includes that source once and reports the duplicate selection

#### Scenario: Batch contains invalid media
- **WHEN** some entries cannot be read or decoded as audio
- **THEN** the system identifies those entries and allows valid entries to proceed without running ASR on the invalid entries

#### Scenario: Directory contains symbolic links
- **WHEN** discovery encounters a symbolic link or a directory outside the requested recursion scope
- **THEN** it does not traverse that entry and reports its exclusion

### Requirement: Freeze accepted job inputs and settings
Each accepted job SHALL retain a stable ID, source content identity, model snapshot, recognition settings, output settings, and output paths. Later default-setting changes SHALL affect only new submissions. Source changes SHALL be detected before execution or retry and SHALL require a new submission.

#### Scenario: Defaults change while a task waits
- **WHEN** the user changes the default model, device, or output format after submission
- **THEN** the queued job continues to use its accepted settings

#### Scenario: Source content changes
- **WHEN** the source no longer matches its accepted content identity
- **THEN** execution reports source_changed and does not reuse the old job's transcript or checkpoints for the changed content

### Requirement: Execute one ready file at a time
The shared desktop queue SHALL run at most one transcription attempt at a time, including during recovery. Ready jobs SHALL be selected in submission order; jobs blocked by unavailable models SHALL not occupy the execution slot. A single-file failure SHALL not stop other ready files.

#### Scenario: Several jobs are ready
- **WHEN** multiple ready files are queued
- **THEN** exactly one starts and the next starts only after the previous attempt and its child processes have stopped

#### Scenario: Earlier job needs a model
- **WHEN** an earlier job is blocked on a missing model and a later job has a ready model
- **THEN** the blocked reason remains visible and the later ready job can execute

#### Scenario: One file fails
- **WHEN** a task fails with a file-specific error
- **THEN** that task retains its failure reason and the next ready task can run

### Requirement: Persist queue pause independently of active jobs
Pausing the queue SHALL prevent new claims while allowing the active task to finish. The pause flag SHALL survive client and service restarts and SHALL require an explicit resume operation to clear.

#### Scenario: Queue is paused during inference
- **WHEN** the user pauses the queue while a task is running
- **THEN** the active task continues and no next task starts after it finishes

#### Scenario: Service restarts with a paused queue
- **WHEN** a paused queue is reopened
- **THEN** pending tasks remain unclaimed until the user resumes

### Requirement: Cancel tasks without corrupting committed work
The system SHALL support cancelling pending and running tasks or all unfinished tasks in a batch. Running cancellation SHALL expose a cancelling state, terminate all processes belonging to that attempt, preserve valid completed checkpoints, and become cancelled only after execution has stopped.

#### Scenario: Pending job is cancelled
- **WHEN** a queued or model-blocked job is cancelled
- **THEN** it becomes cancelled without starting inference or downloading its model

#### Scenario: Inference ignores cooperative cancellation
- **WHEN** a running attempt does not stop after the configured cancellation grace period
- **THEN** the system forcibly terminates that attempt's processes before freeing the execution slot and does not publish its unfinished chunk as valid

### Requirement: Recover interruptions without duplicate execution
After an unexpected service or worker exit, the system SHALL identify unresolved attempts, stop or fence stale execution, mark uncertain jobs interrupted, and pause new claims until explicit recovery. It SHALL NOT accept late events from an old attempt as results of a new attempt.

#### Scenario: Coordinator exits while inference runs
- **WHEN** the service restarts and finds an unresolved running attempt
- **THEN** it resolves the old execution before allowing another attempt, records interrupted state where completion is unproven, and exposes a recovery action

#### Scenario: Computer restarts
- **WHEN** the user returns after a reboot with unfinished jobs
- **THEN** job history and checkpoints remain available but pending transcription does not resume without user action

### Requirement: Retry with compatible completed work
Explicit retry SHALL create a new attempt for a failed, cancelled, or interrupted job while preserving attempt history. It SHALL reuse only compatible verified transcripts, output records, and completed chunk checkpoints, and SHALL report when missing models or incompatible data prevent continuation.

#### Scenario: Long recording has completed chunks
- **WHEN** an interrupted job is retried with matching source, model, device compatibility, and recognition settings
- **THEN** the attempt resumes from the first missing valid chunk and reports the reused work

#### Scenario: Only export failed
- **WHEN** a complete compatible transcript exists but one requested output failed to write
- **THEN** retry regenerates only missing or invalid outputs without rerunning ASR

### Requirement: Deliver requested transcript and subtitle formats
Successful jobs SHALL produce Taiwan Traditional Chinese TXT and SRT by default and SHALL allow original-script output and optional structured transcript JSON. SRT SHALL satisfy the existing subtitle-generation contract. A job SHALL be completed only after every requested output has been validated and committed.

#### Scenario: Default job succeeds
- **WHEN** recognition and both default exports succeed
- **THEN** the job exposes readable TXT and valid SRT paths and records its model snapshot and actual inference device

#### Scenario: One output write fails
- **WHEN** the disk fills after one format is written but before another is committed
- **THEN** the task is not marked completed and records enough verified output state to retry safely

#### Scenario: No usable speech is recognized
- **WHEN** no valid transcript or subtitle text can be produced
- **THEN** the task reports no usable speech and does not create a misleading successful empty subtitle result

### Requirement: Protect sources and resolve output conflicts
The system SHALL use the accepted output plan, preserve relative folder organization, and disambiguate colliding source names within a batch. It SHALL require explicit overwrite permission for existing unrelated results and SHALL never overwrite a source file, even with overwrite enabled.

#### Scenario: Sources share a basename
- **WHEN** multiple accepted sources would map to the same destination
- **THEN** the preview assigns stable distinct output paths before execution

#### Scenario: Unrelated output already exists
- **WHEN** a planned destination is occupied and overwrite was not granted
- **THEN** that job reports output_conflict, preserves the existing file, and does not block other ready jobs

#### Scenario: Retry encounters its own completed output
- **WHEN** an existing output matches a verified output record for that job
- **THEN** retry preserves that valid output and processes only remaining requested formats

### Requirement: Keep local media and results private
Transcription SHALL execute locally and SHALL NOT upload source media, transcripts, or calibration samples. Downloading model assets SHALL be separate from inference. Clients belonging to another local user SHALL NOT access the workspace's control interface.

#### Scenario: Prepared job runs without network
- **WHEN** all selected model assets are ready and outbound network access is blocked
- **THEN** local media extraction, inference, and output delivery can complete

#### Scenario: Another local user attempts control
- **WHEN** a client from another user account attempts to inspect or change tasks
- **THEN** access is denied and the workspace remains unchanged
