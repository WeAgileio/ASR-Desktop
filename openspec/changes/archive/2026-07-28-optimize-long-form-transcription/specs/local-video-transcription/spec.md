## MODIFIED Requirements

### Requirement: Cache completed recognition results
The system SHALL persist completed transcripts atomically, SHALL reuse a compatible completed transcript when the input content, model revision, language, hotwords, audio preprocessing version, and recognition-affecting parameters match, and SHALL preserve compatible atomic chunk checkpoints for resumable long-form transcription without treating an incomplete checkpoint set as a completed transcript.

#### Scenario: Compatible completed cache exists
- **WHEN** the user reruns recognition with a matching completed transcript cache identity
- **THEN** the system skips audio recognition and supplies the cached transcript to subtitle generation

#### Scenario: Compatible long-form checkpoints exist
- **WHEN** no completed transcript exists but one or more chunk checkpoints match the source, chunk plan, model revision, device compatibility, language, hotwords, audio preprocessing, and recognition-affecting settings
- **THEN** the system reuses only those valid completed chunks and resumes recognition at the first chunk without a valid checkpoint

#### Scenario: Recognition setting changes
- **WHEN** the user changes the model, model revision, language, hotwords, chunk plan, audio preprocessing, or another recognition-affecting parameter
- **THEN** the system does not reuse an incompatible transcript cache or chunk checkpoint

#### Scenario: Job is interrupted while saving
- **WHEN** the process terminates before atomic transcript or chunk-checkpoint persistence completes
- **THEN** the partial write is not treated as a valid completed transcript or valid chunk checkpoint on the next run
