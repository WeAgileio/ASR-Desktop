## Purpose

Define the durable mapping between source media and delivered transcript artifacts so retries and source revisions produce traceable results without duplicate publication or lost local work.

## ADDED Requirements

### Requirement: Produce reviewable transcript artifacts
The system SHALL produce a Taiwan-traditional TXT transcript, an SRT following existing subtitle requirements, and completion metadata containing source identity, settings, model details and artifact checksums. Text SHALL be identified as machine transcription without inventing corrections or summaries.

#### Scenario: Recognition succeeds
- **WHEN** a media job produces a valid transcript
- **THEN** TXT and SRT preserve recognized content subject to declared script conversion and formatting, and metadata identifies the source version

### Requirement: Map results by stable source and version identity
The system SHALL place outputs under the configured destination in source-specific and version-specific folders and persist remote artifact identities before creation. Display names SHALL NOT be the sole identity mechanism.

#### Scenario: Same source name appears twice
- **WHEN** distinct sources share a filename
- **THEN** their outputs have separate stable mappings and do not overwrite each other

#### Scenario: Creation succeeds but acknowledgement is lost
- **WHEN** a result folder or file exists remotely after a lost response
- **THEN** a retry verifies and reuses the recorded remote identity rather than creating another same-purpose object

### Requirement: Mark completion only after verified delivery
The system SHALL retain local results until all required artifacts are uploaded and verified. The completion marker SHALL be published last, and completed status SHALL include result links only after delivery is confirmed under a valid attempt.

#### Scenario: Only one artifact uploads successfully
- **WHEN** TXT uploads but SRT upload fails
- **THEN** the job is not completed, local results remain available and retry repairs only missing or invalid delivery work

#### Scenario: Final status response lost
- **WHEN** all remote artifacts are delivered but the completion status acknowledgement is lost
- **THEN** recovery verifies existing outputs and completes the business record without re-transcription or duplicate publication

### Requirement: Preserve source and pending results
The system SHALL leave source files unchanged and SHALL NOT automatically delete undelivered outputs. Completed local working data SHALL be eligible for documented configurable retention cleanup.

#### Scenario: Cleanup runs during delivery outage
- **WHEN** local cleanup runs while a job is waiting for upload retry
- **THEN** the job's undelivered outputs and required recovery data are retained
