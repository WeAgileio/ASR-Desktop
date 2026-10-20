# Spec Delta

## Purpose

Expose the local desktop transcription workspace to terminal users and automation through complete commands, stable identifiers, machine-readable results, and consistent cross-client control.

## ADDED Requirements

### Requirement: Provide a bundled independent CLI
The application SHALL include an `asr-desktop` executable that runs without opening the desktop window or requiring an external runtime. It SHALL be callable by its installed absolute path and offer an explicit user-level command-link installation operation without overwriting an unrelated executable or silently changing shell configuration.

#### Scenario: First use is from Terminal
- **WHEN** the user invokes the bundled CLI before ever opening the desktop window
- **THEN** it can diagnose readiness, start the permitted local service, prepare models, and submit work

#### Scenario: Command link conflicts
- **WHEN** command-link installation finds an unrelated executable at its destination
- **THEN** it preserves that executable and reports the conflict

### Requirement: Expose complete operational commands
The CLI SHALL support batch submission, job and batch listing and inspection, event watching, cancellation, retry, queue pause and resume, model listing and download and verification and removal, default settings, device explanation and calibration, service start and stop and status, and diagnostics.

#### Scenario: Script manages a desktop-created task
- **WHEN** a CLI command targets a task ID originally created in the desktop window
- **THEN** the operation uses the same task record and the desktop observes its result

#### Scenario: Select inference device
- **WHEN** a user supplies auto, cpu, gpu, or the compatible mps alias
- **THEN** the CLI applies the same device policy as the window and records the requested and resolved choices

### Requirement: Separate submission from completion
Submission SHALL return stable batch and job identifiers after durable acceptance. The default command SHALL return without waiting for inference; an explicit wait option SHALL report final outcomes. Successful submission SHALL NOT be reported as successful transcription.

#### Scenario: Asynchronous submission succeeds
- **WHEN** a valid batch is accepted without wait
- **THEN** the CLI returns its identifiers and current states, which remain queryable after the client exits

#### Scenario: Waiting batch contains a failure
- **WHEN** wait observes terminal outcomes with at least one failed, cancelled, or output-conflicted job
- **THEN** the CLI returns a non-zero task result and identifies affected jobs while preserving completed outputs

#### Scenario: Wait requires user intervention
- **WHEN** the batch is blocked on missing models or interruption recovery
- **THEN** wait returns the unmet prerequisite and job identifiers rather than waiting indefinitely for a user action

### Requirement: Provide clean versioned machine-readable output
Commands SHALL offer a versioned JSON result and watch SHALL offer newline-delimited JSON events. Structured stdout SHALL contain only the requested result or events; diagnostics and dependency logs SHALL not corrupt it. Errors SHALL include a stable code, explanation, and relevant identifiers.

#### Scenario: JSON output is redirected
- **WHEN** a command runs with JSON output redirected to a file or pipe
- **THEN** the output parses without ANSI escapes, progress bars, or unrelated log lines

#### Scenario: Exit status is interpreted by a script
- **WHEN** a command finishes without being interrupted by a signal
- **THEN** it returns 0 for a successful operation or fully successful wait, 1 for unsuccessful task outcomes, 2 for invalid arguments, or 3 for unmet service, model, or access prerequisites

### Requirement: Reconnect to shared state safely
GUI and CLI clients SHALL obtain authoritative state after reconnecting and SHALL use event cursors to resume observation. If history has expired, the system SHALL identify the reset and supply a current snapshot. An incompatible protocol version SHALL be rejected before mutation.

#### Scenario: Client disconnects during transcription
- **WHEN** a client reconnects with its last event cursor
- **THEN** it receives remaining available events or an explicit snapshot reset without creating a duplicate job

#### Scenario: Client and service versions conflict
- **WHEN** a command uses an incompatible protocol version
- **THEN** it receives a compatibility error and no task or setting is modified

### Requirement: Make observation cancellation non-destructive
Interrupting a waiting or watching CLI client SHALL stop observation only. Cancelling accepted work SHALL require an explicit job or batch cancellation operation, and repeating a completed control request SHALL not create duplicate attempts or submissions.

#### Scenario: User presses Ctrl-C while watching
- **WHEN** the user interrupts a watch or wait command
- **THEN** the command exits with status 130 while the accepted background task remains in its existing execution state

#### Scenario: Request response is lost
- **WHEN** a client retries the same submission or retry operation with the same request identifier
- **THEN** it receives the existing accepted result rather than another batch or attempt

### Requirement: Preserve the existing single-file CLI
The existing `asr-srt` command SHALL retain its single-file arguments, output conventions, and explicit cpu and mps choices. The documented evidence-based auto policy SHALL be the intentional behavioral change; adopting the desktop application SHALL not require existing scripts to use the new command.

#### Scenario: Existing single-file script runs
- **WHEN** a user executes an existing `asr-srt` invocation
- **THEN** it continues to use the existing single-file output contract and explicitly selected device, with auto following the updated documented policy
