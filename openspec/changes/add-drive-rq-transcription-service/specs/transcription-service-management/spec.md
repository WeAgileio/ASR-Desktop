## Purpose

Define the operator-facing submission and monitoring experience and the deployment boundaries needed to run a recoverable transcription service on one Apple Silicon Mac.

## ADDED Requirements

### Requirement: Provide a persistent operator view
The service SHALL expose authenticated batch submission, batch and job lists, scan status, stage progress, retry and pause controls, error reasons, worker liveness and completed result links. Long-term records SHALL survive queue result expiration and container replacement.

#### Scenario: Queue history expires
- **WHEN** execution-tool history for a completed job expires
- **THEN** the operator can still see the source, outcome and delivered result links

#### Scenario: Unauthenticated mutation
- **WHEN** a request lacks valid operator or worker authorization
- **THEN** submission, state updates and service-control mutations are rejected

### Requirement: Isolate host inference and credentials
The system SHALL run inference natively on macOS, keep service-account credentials on the host outside synchronized project directories, and keep the database accessible only through the service API for host workers. Queue payloads SHALL NOT contain credentials or arbitrary user-selected executable commands.

#### Scenario: Job submitted from browser
- **WHEN** a user submits folder references and supported recognition settings
- **THEN** only validated job references are dispatched and no private key is sent to the browser or queue

### Requirement: Recover service startup and dependencies
The deployment SHALL persist database and queue storage and manage the native worker independently of the web process. It SHALL retry dependency connection failures and document user-login, Docker readiness and system-sleep prerequisites.

#### Scenario: Worker starts before Docker
- **WHEN** the worker starts before the API and queue are available
- **THEN** it waits with bounded backoff and reconnects without losing registered jobs

#### Scenario: Container replaced
- **WHEN** service containers are replaced using the existing persistent volumes
- **THEN** job records remain and unfinished dispatch is reconciled before new execution

### Requirement: Bound resource usage and protect local recovery
The system SHALL keep model concurrency at one, check available workspace storage before download, and provide documented consistent database backup and rollback procedures. Existing standalone transcription behavior SHALL remain available.

#### Scenario: Insufficient local storage
- **WHEN** workspace capacity is below the configured admission threshold
- **THEN** new downloads do not begin and the operator receives an actionable blocked reason

#### Scenario: Service disabled
- **WHEN** the web and queue service are stopped
- **THEN** the existing standalone CLI remains usable without requiring the service stack
