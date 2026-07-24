## ADDED Requirements

### Requirement: Accept a local video input
The system SHALL accept a readable local video file as the source for one transcription job and SHALL reject missing, unreadable, or unsupported input without modifying the source file.

#### Scenario: Valid video is accepted
- **WHEN** the user supplies a readable video containing a supported audio stream
- **THEN** the system starts a local transcription job and leaves the source video unchanged

#### Scenario: Invalid input is rejected
- **WHEN** the supplied path is missing, unreadable, or has no decodable audio stream
- **THEN** the system exits without running ASR and reports the input validation failure

### Requirement: Normalize source audio locally
The system SHALL use a local FFmpeg process to extract and normalize source audio into the format required by the selected ASR pipeline, and SHALL NOT upload the video or audio to a remote transcription service.

#### Scenario: Video audio is normalized
- **WHEN** a valid video job starts
- **THEN** the system produces a local mono 16 kHz audio representation and obtains the media duration before ASR inference

#### Scenario: FFmpeg is unavailable
- **WHEN** FFmpeg or ffprobe cannot be executed
- **THEN** the system stops before model inference and reports the missing media dependency with an actionable installation hint

### Requirement: Select a supported ASR model
The system SHALL allow the user to explicitly select either `fun-asr-nano` or `paraformer` for a transcription job, and SHALL record the selected model and resolved model revision in the result metadata.

#### Scenario: Fun-ASR-Nano is selected
- **WHEN** the user selects `fun-asr-nano`
- **THEN** the system runs the Fun-ASR-Nano-2512 adapter and normalizes its text and character timestamps into the common transcript schema

#### Scenario: Paraformer is selected
- **WHEN** the user selects `paraformer`
- **THEN** the system runs the paraformer-zh pipeline with VAD and punctuation and normalizes its output into the same common transcript schema

#### Scenario: Unsupported model is selected
- **WHEN** the user supplies a model identifier other than the supported values
- **THEN** the system rejects the job before downloading or loading a model and lists the supported identifiers

### Requirement: Support Chinese-dominant mixed-language recognition
The system SHALL configure each supported model for Chinese-dominant speech while preserving recognized English terms, Latin characters, and casing returned by the model.

#### Scenario: Speech contains English terminology
- **WHEN** a Chinese utterance contains recognized English product names or terminology
- **THEN** the normalized transcript retains the English text without applying Chinese script conversion to it

### Requirement: Apply user-provided hotwords
The system SHALL accept an optional ordered collection of non-empty hotwords, pass them through the selected model adapter using that model's supported parameter format, and include the normalized hotword collection in cache identity metadata.

#### Scenario: Hotwords are supplied
- **WHEN** the user supplies one or more valid hotwords
- **THEN** the system uses them during recognition and records them in the transcript metadata

#### Scenario: No hotwords are supplied
- **WHEN** the user does not supply hotwords
- **THEN** the system runs recognition without adding synthetic hotwords

### Requirement: Resolve an Apple Silicon inference device
The system SHALL support `auto`, `mps`, and `cpu` device choices. In `auto` mode it SHALL prefer a usable MPS path and SHALL retry once on CPU when a recognized MPS compatibility failure occurs.

#### Scenario: Auto mode uses MPS
- **WHEN** MPS is available and the selected model passes device initialization and inference
- **THEN** the system completes inference on MPS and records `mps` as the resolved device

#### Scenario: Auto mode falls back to CPU
- **WHEN** MPS is unavailable or produces a recognized compatibility failure in `auto` mode
- **THEN** the system reports the fallback, reloads the selected model on CPU, and retries the failed inference once

#### Scenario: Explicit MPS fails
- **WHEN** the user explicitly selects `mps` and inference cannot run on MPS
- **THEN** the system reports the MPS failure and does not silently change to CPU

### Requirement: Produce a versioned common transcript
The system SHALL convert model-specific output into a versioned transcript containing full text, source duration, language, ordered timestamped text units, and inference metadata. All domain timestamps SHALL be non-negative integer milliseconds.

#### Scenario: Model output is normalized
- **WHEN** a supported model successfully returns text and timestamps
- **THEN** the system emits a transcript whose timestamped units are ordered, bounded by media duration, and associated with the selected model metadata

#### Scenario: Model output is incomplete
- **WHEN** model output lacks the text or timestamp information required for subtitle generation
- **THEN** the system rejects the output as incompatible and preserves diagnostic information without creating a successful cache entry

### Requirement: Cache completed recognition results
The system SHALL persist completed transcripts atomically and SHALL reuse a compatible transcript when the input content, model revision, language, hotwords, audio preprocessing version, and recognition-affecting parameters match.

#### Scenario: Compatible cache exists
- **WHEN** the user reruns recognition with a matching cache identity
- **THEN** the system skips audio recognition and supplies the cached transcript to subtitle generation

#### Scenario: Recognition setting changes
- **WHEN** the user changes the model, model revision, language, hotwords, or another recognition-affecting parameter
- **THEN** the system does not reuse an incompatible transcript cache

#### Scenario: Job is interrupted while saving
- **WHEN** the process terminates before atomic transcript persistence completes
- **THEN** the partial result is not treated as a valid completed transcript on the next run

### Requirement: Report job progress and failures
The system SHALL report the current phase of validation, audio extraction, model preparation, transcription, subtitle generation, and output writing, and SHALL return a non-zero result with a concise diagnostic when a phase fails.

#### Scenario: Job completes
- **WHEN** all processing phases succeed
- **THEN** the system reports completion and the paths of the generated artifacts

#### Scenario: A processing phase fails
- **WHEN** any phase cannot complete
- **THEN** the system identifies the failed phase, returns a non-zero result, and does not claim that an SRT was successfully generated

