## ADDED Requirements

### Requirement: Generate subtitle cues from timestamps
The system SHALL deterministically convert an ordered common transcript into subtitle cues using punctuation, silence gaps, display length, and cue duration constraints.

#### Scenario: Sentence punctuation is available
- **WHEN** timestamped text contains sentence-ending punctuation within configured limits
- **THEN** the system prefers that punctuation as a cue boundary

#### Scenario: A sentence exceeds configured limits
- **WHEN** a punctuated sentence exceeds the maximum display units or maximum cue duration
- **THEN** the system splits it at the best available comma, pause, or token boundary without splitting inside an English word

#### Scenario: A cue is too short
- **WHEN** a candidate cue is shorter than the target minimum duration
- **THEN** the system merges it with a compatible adjacent cue when the merged cue remains within hard length and duration limits

### Requirement: Enforce a valid subtitle timeline
The system SHALL emit cues with non-negative, monotonically increasing time ranges that do not overlap and do not extend beyond the source media duration.

#### Scenario: Adjacent timestamp ranges overlap
- **WHEN** normalized input timestamps would produce overlapping adjacent cues
- **THEN** the system adjusts or constrains cue boundaries so the emitted cues do not overlap while retaining their order

#### Scenario: Timestamp exceeds media duration
- **WHEN** a final text unit ends after the known media duration
- **THEN** the system clamps the final cue end to the media duration and reports the normalization in diagnostics

### Requirement: Provide configurable subtitle segmentation
The system SHALL provide configurable maximum display units and maximum cue duration, SHALL use defaults of 22 display units and 6 seconds, and SHALL target a minimum cue duration of 1 second.

#### Scenario: Default segmentation is used
- **WHEN** the user supplies no subtitle segmentation settings
- **THEN** the system generates cues using the documented default values

#### Scenario: Valid segmentation settings are supplied
- **WHEN** the user supplies positive values within supported bounds
- **THEN** the system uses those values without invalidating or rerunning the ASR transcript cache

#### Scenario: Invalid segmentation settings are supplied
- **WHEN** a segmentation value is zero, negative, or outside supported bounds
- **THEN** the system rejects the settings before writing an SRT and explains the valid range

### Requirement: Convert subtitle text to Taiwan Traditional Chinese
The system SHALL support Taiwan Traditional Chinese output through OpenCC while preserving Latin-script text, and SHALL retain the original model text in the cached transcript.

#### Scenario: Traditional Chinese output is enabled
- **WHEN** subtitle text contains Simplified Chinese characters and Taiwan Traditional Chinese output is selected
- **THEN** the SRT contains the converted Traditional Chinese text while the cached transcript remains unchanged

#### Scenario: Subtitle text contains English
- **WHEN** a cue contains Latin-script English terms
- **THEN** script conversion leaves those terms intact

### Requirement: Write a standards-compliant SRT file
The system SHALL write UTF-8 SRT with sequential one-based cue numbers, `HH:MM:SS,mmm` timestamps, a non-empty text body for each cue, and a blank line between cues.

#### Scenario: SRT generation succeeds
- **WHEN** at least one valid cue is produced
- **THEN** the resulting file can be parsed as SRT and contains all cues in chronological order

#### Scenario: Transcript contains no subtitle text
- **WHEN** the normalized transcript contains no non-whitespace text units
- **THEN** the system reports that no speech subtitles were produced and does not write a misleading successful SRT

### Requirement: Protect existing files and source media
The system SHALL default the output to a same-basename `.srt` beside the input video, SHALL never modify the source media, and SHALL require explicit overwrite authorization before replacing an existing SRT.

#### Scenario: Default output path is unused
- **WHEN** the user provides no output path and no same-basename SRT exists
- **THEN** the system writes the SRT beside the video using the video's base name

#### Scenario: Output already exists
- **WHEN** the target SRT already exists and overwrite was not explicitly authorized
- **THEN** the system stops before replacing it and reports the conflict

#### Scenario: Overwrite is authorized
- **WHEN** the target SRT exists and the user explicitly authorizes overwrite
- **THEN** the system atomically replaces the target SRT without modifying the source video

### Requirement: Reproduce subtitle output
The system SHALL produce byte-equivalent SRT output when given the same transcript schema version, subtitle settings, script conversion profile, and application version.

#### Scenario: Subtitle generation is repeated
- **WHEN** the user regenerates subtitles from the same cached transcript with identical output settings
- **THEN** the system produces the same SRT content without rerunning ASR
