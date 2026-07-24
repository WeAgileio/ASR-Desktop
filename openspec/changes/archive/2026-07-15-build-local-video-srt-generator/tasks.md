## 1. Project Foundation

- [x] 1.1 Create the Python package, CLI entry point, configuration model, application service boundaries, and test directory structure.
- [x] 1.2 Declare and lock runtime/development dependencies for FunASR, PyTorch/torchaudio, model hub access, OpenCC, CLI handling, validation, and testing.
- [x] 1.3 Add startup diagnostics that report Python, macOS architecture, PyTorch/MPS availability, FFmpeg/ffprobe availability, cache location, and actionable dependency errors.

## 2. Domain Models and Persistence

- [x] 2.1 Implement validated, versioned models for transcript metadata, timestamped text units, transcripts, subtitle settings, and subtitle cues using integer millisecond timestamps.
- [x] 2.2 Implement stable JSON serialization/deserialization and reject incompatible, unordered, negative, or media-out-of-bounds transcript data.
- [x] 2.3 Implement atomic file replacement utilities for transcript caches and SRT outputs, including explicit overwrite protection.
- [x] 2.4 Add unit tests for domain validation, schema version handling, serialization round trips, and interrupted atomic writes.

## 3. Local Media Processing

- [x] 3.1 Implement source-path and audio-stream validation without modifying the input media.
- [x] 3.2 Implement safe ffprobe invocation to obtain media/audio metadata and duration without shell interpolation.
- [x] 3.3 Implement safe FFmpeg extraction to a cached mono 16 kHz WAV and clean up incomplete temporary outputs.
- [x] 3.4 Add tests for valid media, missing files, unreadable inputs, missing audio streams, unavailable FFmpeg, paths with spaces/special characters, and extraction failures.

## 4. Inference Device and Model Adapters

- [x] 4.1 Define the common ASR adapter interface and model registry with only `fun-asr-nano` and `paraformer` as supported user-facing identifiers.
- [x] 4.2 Implement `auto`, `mps`, and `cpu` device resolution, including MPS preflight, observable auto-mode CPU fallback, and no fallback for explicit MPS selection.
- [x] 4.3 Implement the Fun-ASR-Nano-2512 adapter with Chinese language configuration, VAD, hotwords, model revision capture, and character-timestamp normalization.
- [x] 4.4 Implement the paraformer-zh adapter with fsmn-vad, ct-punc, hotwords, model revision capture, and timestamp normalization.
- [x] 4.5 Validate raw model output in both adapters and emit diagnostic failures when required text or timestamps are absent or incompatible.
- [x] 4.6 Add adapter contract tests using recorded/minimal fixtures for Chinese text, mixed Chinese-English text, hotwords, timestamp conversion, malformed output, and model selection errors.
- [x] 4.7 Add device-resolution tests for usable MPS, unavailable MPS, recognized auto fallback, explicit MPS failure, and explicit CPU selection.

## 5. Recognition Cache and Workflow

- [x] 5.1 Implement content fingerprinting and cache identity using media content, model ID/revision, language, normalized hotwords, preprocessing version, and recognition-affecting settings.
- [x] 5.2 Implement compatible transcript lookup, atomic cache persistence, corrupt/partial cache rejection, and cache bypass controls for diagnostics.
- [x] 5.3 Implement the end-to-end local transcription application service with explicit validation, extraction, model preparation, inference, and persistence phases.
- [x] 5.4 Add progress events and structured errors that identify the active/failed phase and resolved inference device.
- [x] 5.5 Add workflow tests proving compatible caches skip ASR, recognition changes invalidate cache, subtitle-only changes retain cache, and failed jobs do not create successful cache entries.

## 6. Subtitle Segmentation and Traditional Chinese

- [x] 6.1 Implement display-unit tokenization that treats Chinese characters and English words as appropriate break units and never splits inside an English word.
- [x] 6.2 Implement deterministic cue segmentation using sentence punctuation, comma boundaries, silence gaps, maximum 22 display units, maximum 6-second duration, and target 1-second minimum duration defaults.
- [x] 6.3 Implement short-cue merging and final timeline normalization so cues remain ordered, non-negative, non-overlapping, non-empty, and bounded by media duration.
- [x] 6.4 Implement optional OpenCC Taiwan Traditional Chinese conversion after segmentation while preserving the original transcript and Latin-script terms.
- [x] 6.5 Add unit and property-oriented tests for punctuation boundaries, oversized sentences, rapid speech, long pauses, short cues, overlapping timestamps, duration clamping, empty speech, mixed Chinese-English text, and deterministic output.

## 7. SRT Output and CLI

- [x] 7.1 Implement UTF-8 SRT rendering with one-based indexes, `HH:MM:SS,mmm` timestamps, non-empty text, and blank-line cue separation.
- [x] 7.2 Implement the CLI command with input path, `--model`, `--device`, repeatable hotwords, output path, Traditional Chinese option, segmentation controls, cache controls, and `--overwrite`.
- [x] 7.3 Default the output to a same-basename `.srt` beside the source video, report generated artifact paths, and return non-zero exit codes for validation or processing failures.
- [x] 7.4 Add CLI integration tests for both model selections with stubbed adapters, default/custom output paths, overwrite conflicts, invalid settings, cache reuse, and error reporting.

## 8. Apple Silicon Validation and Documentation

- [x] 8.1 Create a repeatable local evaluation set/manifest covering clear Mandarin, Chinese-English terminology, noisy audio, and a longer video without committing private media.
- [ ] 8.2 Run and record Fun-ASR-Nano and Paraformer smoke tests on the target Apple Silicon Mac for MPS and CPU, including accuracy observations, timestamp usability, processing time, resolved device, and memory behavior.
- [x] 8.3 Verify whether the Python MPS path or llama.cpp/GGUF path can provide the required Nano character timestamps; document the supported runtime decision and fallback.
- [x] 8.4 Add user documentation for environment setup, FFmpeg installation, model download/cache size, example CLI commands, model trade-offs, hotwords, output files, CPU fallback, and troubleshooting.
- [x] 8.5 Run the complete automated test suite and an end-to-end real-video check, then confirm the produced SRT parses correctly and the source video remains unchanged.
