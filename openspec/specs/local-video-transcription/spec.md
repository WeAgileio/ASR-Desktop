# local-video-transcription Specification

## Purpose
TBD - created by archiving change build-local-video-srt-generator. Update Purpose after archive.
## Requirements
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
系統 SHALL 允許使用者選擇登錄配置中支援的模型，包括 `fun-asr-nano`、`paraformer`、Taiwan Tongues ASR CE 與 Breeze ASR 25，並於結果 metadata 記錄選用模型與固定版本。

#### Scenario: Fun-ASR-Nano is selected
- **WHEN** 使用者選擇 `fun-asr-nano`
- **THEN** 系統使用既有 Fun-ASR-Nano-2512 Adapter，將文字與時間戳轉為共用 transcript

#### Scenario: Paraformer is selected
- **WHEN** 使用者選擇 `paraformer`
- **THEN** 系統使用既有 paraformer-zh、VAD 與標點流程，輸出共用 transcript

#### Scenario: Additional local model is selected
- **WHEN** 使用者選擇已登錄且準備完成的 Taiwan Tongues ASR CE 或 Breeze ASR 25
- **THEN** 系統在本機 CPU 執行對應引擎，並將文字與真實時間戳轉為共用 transcript

#### Scenario: Unsupported model is selected
- **WHEN** 使用者提供未登錄的模型識別碼
- **THEN** 系統在下載或載入模型前拒絕工作，並列出支援的識別碼

### Requirement: Support Chinese-dominant mixed-language recognition
The system SHALL configure each supported model for Chinese-dominant speech while preserving recognized English terms, Latin characters, and casing returned by the model.

#### Scenario: Speech contains English terminology
- **WHEN** a Chinese utterance contains recognized English product names or terminology
- **THEN** the normalized transcript retains the English text without applying Chinese script conversion to it

### Requirement: Apply user-provided hotwords
系統 SHALL 接受有序且非空的熱詞集合，依選定模型支援的參數格式傳入推論，並將正規化熱詞納入快取識別。模型未支援熱詞時 SHALL 在接受工作前明確拒絕非空熱詞，不得靜默忽略。

#### Scenario: Hotwords are supplied
- **WHEN** 使用者為支援熱詞的模型提供有效熱詞
- **THEN** 系統在辨識時使用並記錄熱詞

#### Scenario: No hotwords are supplied
- **WHEN** 使用者未提供熱詞
- **THEN** 系統不加入合成熱詞

#### Scenario: Model does not support hotwords
- **WHEN** 使用者為不支援熱詞的模型指定非空熱詞
- **THEN** 系統在接受工作前回報該模型不支援熱詞

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

### Requirement: Report job progress and failures
The system SHALL report the current phase of validation, audio extraction, model preparation, transcription, subtitle generation, and output writing, and SHALL return a non-zero result with a concise diagnostic when a phase fails.

#### Scenario: Job completes
- **WHEN** all processing phases succeed
- **THEN** the system reports completion and the paths of the generated artifacts

#### Scenario: A processing phase fails
- **WHEN** any phase cannot complete
- **THEN** the system identifies the failed phase, returns a non-zero result, and does not claim that an SRT was successfully generated

### Requirement: Validate model device capabilities
系統 SHALL 在接受工作前依選定模型的裝置能力驗證設定。第一階段兩個新增模型 SHALL 支援 CPU，`auto` SHALL 選擇 CPU；明確指定不支援的 GPU 或 MPS SHALL 被拒絕。既有模型的裝置政策 SHALL 維持原有行為。

#### Scenario: Additional model uses automatic device selection
- **WHEN** 使用者為任一新增模型選擇 `auto`
- **THEN** 系統選擇 CPU 並記錄實際執行裝置

#### Scenario: Additional model is explicitly assigned an unsupported device
- **WHEN** 使用者為僅支援 CPU 的模型選擇 GPU 或 MPS
- **THEN** 系統在接受工作前說明該模型支援的裝置

