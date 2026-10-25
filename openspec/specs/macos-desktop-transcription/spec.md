# macos-desktop-transcription Specification

## Purpose

Provide an installable Apple Silicon desktop application for local transcription, with a native window, managed background work, and a complete runtime that does not require developer environment setup.

## Requirements

### Requirement: Distinguish development background execution
Development builds SHALL explicitly identify their execution mode and MAY directly launch the same-user helper for functional development. Distribution builds SHALL use the managed background-service path and SHALL NOT silently fall back to development execution when registration or authorization fails. Both modes SHALL preserve accepted work independently of clients.

#### Scenario: Development client exits
- **WHEN** a development build starts its helper and the initiating CLI or window closes
- **THEN** the helper remains available to another client and reports development mode

#### Scenario: Distribution registration fails
- **WHEN** the managed service cannot be registered or authorized in a distribution build
- **THEN** the application reports the unmet prerequisite without launching the development helper path

### Requirement: Install a self-contained Apple Silicon application
The application SHALL support Apple Silicon Macs running macOS 14 or later and SHALL include all execution and media-processing dependencies. Model weights SHALL be downloaded after installation. Unsupported platforms SHALL receive an actionable explanation rather than a runtime installation prompt.

#### Scenario: Clean supported Mac
- **WHEN** a user installs the application on a supported Mac without Python, Homebrew, FFmpeg, Docker, or a project checkout
- **THEN** the window and bundled CLI can start and prepare a model without installing any of those tools separately

#### Scenario: Unsupported platform
- **WHEN** the application is launched on an unsupported architecture or macOS version
- **THEN** the user is informed of the supported platform and no transcription is started

### Requirement: Guide first-use model preparation
The application SHALL show the available supported models, required download and storage sizes, and preparation state before the user starts a model download. A missing or incomplete model SHALL be distinguishable from a ready model.

#### Scenario: First launch has no model
- **WHEN** the user opens the newly installed application
- **THEN** it offers model selection and download without claiming that transcription is already ready

#### Scenario: Download has failed
- **WHEN** model preparation fails or loses connectivity
- **THEN** the application displays the reason and a retry action while preserving usable download progress

### Requirement: Operate the shared transcription workspace
The desktop application SHALL expose batch submission, task inspection and control, queue pause and resume, output access, model management, recognition defaults, device explanation and calibration, service control, and diagnostics through the same state used by the CLI.

#### Scenario: Submit media from the window
- **WHEN** the user selects or drops local audio, video, or folders
- **THEN** the application previews the source and output plan and submits the confirmed batch to the shared queue

#### Scenario: CLI changes a task
- **WHEN** the CLI submits, cancels, retries, or otherwise changes a task
- **THEN** the open desktop application reflects the same task ID, state, and operation result

### Requirement: Display truthful job and batch progress
The application SHALL display each task's phase, elapsed time, requested and resolved device, selection or fallback reason, output location, and actionable failures. Estimates SHALL be labelled, unavailable ETA SHALL be omitted, and batch file counts SHALL NOT be represented as measured compute-time progress.

#### Scenario: ASR has no reliable ETA
- **WHEN** a running task has no compatible time estimate
- **THEN** the window shows its active phase and elapsed time without inventing a remaining duration

#### Scenario: Batch has mixed outcomes
- **WHEN** a batch contains completed, failed, cancelled, and pending tasks
- **THEN** the window shows separate counts and identifies which tasks need action rather than declaring the whole batch successful

### Requirement: Keep accepted work independent of the window
Closing the desktop window or exiting a CLI client SHALL NOT stop accepted work. The application SHALL distinguish background-service readiness from queue execution state and SHALL expose an explicit operation to stop the service safely.

#### Scenario: Window closes during transcription
- **WHEN** the user closes the window while a task is running
- **THEN** the task continues and reopening the application shows its current state or completed result

#### Scenario: Background execution is disallowed
- **WHEN** macOS has not permitted the required background service
- **THEN** the GUI and CLI report that the service is unavailable and give recovery instructions without claiming a job has started

#### Scenario: User stops the service
- **WHEN** the user requests a normal service stop with a task running
- **THEN** new work stops being claimed and the service waits for the active task to finish unless the user explicitly requests cancellation

### Requirement: Preserve user data across application maintenance
Application updates SHALL preserve model downloads, task history, recoverable checkpoints, settings, and exported results. An incompatible data version SHALL be rejected without modification, and updating the executable SHALL NOT silently replace the settings or model snapshot of accepted jobs.

#### Scenario: Application is updated
- **WHEN** the user installs a newer compatible application version
- **THEN** existing models and task records remain available without downloading the same verified model again

#### Scenario: Older application sees newer data
- **WHEN** an older application cannot interpret the stored data version
- **THEN** it refuses to modify the data and explains how to use a compatible version or backup

### Requirement: Diagnose installation and access failures
The application SHALL report failures of bundled dependencies, background execution, storage capacity, and source or output permissions with corrective actions. It SHALL NOT require users to disable operating-system protections or install development tools to repair a supported release.

#### Scenario: Source access is denied
- **WHEN** the operating system denies access to a selected source or output directory
- **THEN** the application identifies the affected item and allows access to be corrected before retrying without changing the original media

#### Scenario: Bundled dependency is damaged
- **WHEN** an included runtime or media executable fails validation
- **THEN** diagnostics identify the damaged component and recommend repairing or reinstalling the application
