## Purpose

Define reliable serial execution of long-running media jobs, including durable dispatch, observable attempts, interruption recovery and stage-aware retries on one Mac host.

## ADDED Requirements

### Requirement: Execute one complete media job at a time
The system SHALL run at most one media job across download, inference and upload on the host. Additional submissions SHALL remain queued and duplicate delivery SHALL NOT cause overlapping execution or repeat a completed job.

#### Scenario: Multiple jobs are queued
- **WHEN** jobs A and B are ready in that order
- **THEN** B starts only after A completes or leaves execution in a recorded failure or retry state

#### Scenario: Duplicate worker start
- **WHEN** another worker or duplicate message attempts to start a job while a media job is running
- **THEN** no second media execution starts

### Requirement: Recover durable dispatch
The system SHALL persist dispatch intent with job creation and reconcile interrupted dispatch or lost queue state. Job execution SHALL require a current attempt identity; superseded attempts SHALL NOT overwrite current state.

#### Scenario: Queue unavailable during submission
- **WHEN** job creation succeeds but queue publication fails
- **THEN** the job remains visible as pending dispatch and is eligible for automatic delivery after recovery

#### Scenario: Publication response lost
- **WHEN** publication succeeds but its acknowledgement is lost
- **THEN** retry does not cause duplicate effective execution

#### Scenario: Queue data lost
- **WHEN** durable business records survive but queue entries are lost
- **THEN** reconciliation recovers eligible unfinished jobs without replaying completed jobs or overlapping a live execution

### Requirement: Report execution phases and liveness
The system SHALL persist downloading, transcribing, uploading, completed, retry-wait, blocked, failed and interrupted states with attempt identity, current phase, heartbeat and diagnostic information. Estimated progress SHALL remain labelled estimated and stale events SHALL NOT regress state.

#### Scenario: Model runs without immediate progress events
- **WHEN** inference continues for longer than the heartbeat interval
- **THEN** liveness remains observable independently of inference percentage

#### Scenario: Worker loses connectivity
- **WHEN** a worker cannot renew its execution authority
- **THEN** the service reports loss of contact, does not infer that the old process stopped, and prevents result publication until authority is revalidated

### Requirement: Retry according to failure stage
The system SHALL use bounded delayed retries for transient failures, block permission failures, fail invalid media, and allow manual retry. Retries SHALL preserve compatible completed work and SHALL NOT permanently block unrelated jobs.

#### Scenario: Upload fails after successful inference
- **WHEN** a transient Drive error prevents delivery
- **THEN** a later retry uses the completed local outputs without rerunning inference

#### Scenario: Inference interrupted
- **WHEN** a worker restarts after interruption and the old execution is confirmed stopped
- **THEN** a new attempt reuses compatible long-form checkpoints rather than treating partial outputs as completion

#### Scenario: Long job exceeds its configured limit
- **WHEN** a job exceeds the explicit execution time limit
- **THEN** execution is stopped without orphaned inference processes and the failed phase is recorded

### Requirement: Pause future execution safely
The system SHALL support a persistent global pause that stops new media execution while allowing the current task to finish and new submissions to queue.

#### Scenario: Pause during transcription
- **WHEN** the operator pauses while one job is transcribing
- **THEN** that job can finish but the next job does not start until resumed, including after a worker restart
