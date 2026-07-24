## 1. Long-form performance instrumentation

- [x] 1.1 Define versioned performance-span and resource-snapshot models for model load, silence planning, per-chunk ASR, normalization, checkpoint I/O, merge, total wall time, RTF, peak RSS, memory pressure, and swap availability
- [x] 1.2 Add monotonic stage timers around the existing unchunked path without changing transcription behavior or renderer output
- [x] 1.3 Extend evaluation output with model revision, runtime, resolved device, audio duration, planned/speech duration, chunk settings, batch/VAD settings, and explicit unavailable-resource markers
- [x] 1.4 Add tests for stage accounting, unsupported resource metrics, failed-run exclusion, and separation of model-load time from inference time

## 2. Deterministic silence-aware chunk planning

- [x] 2.1 Add versioned long-form planner settings with a duration threshold, target/minimum/maximum chunk duration, silence-search window, minimum silence, and bounded fallback overlap
- [x] 2.2 Implement and unit-test parsing of machine-readable silence intervals from the extracted mono WAV, including malformed, partial, empty, and boundary-clipped observations
- [x] 2.3 Implement a pure deterministic planner that prefers the closest valid silence boundary and otherwise creates bounded-overlap fallback chunks covering the full integer-millisecond timeline
- [x] 2.4 Validate plan invariants for ordering, coverage, chunk bounds, overlap limits, stable identity, short-input bypass, and reproducibility
- [x] 2.5 Add planner tests for two-hour timelines, dense speech, long silence, short final chunks, exact target boundaries, and repeated identical input

## 3. Long-form manifest and checkpoint storage

- [x] 3.1 Define versioned manifest and chunk-checkpoint schemas containing source, preprocessing, planner, model/revision, device compatibility, language, hotword, recognition-setting, boundary, checksum, and processing metadata identities
- [x] 3.2 Implement deterministic manifest/checkpoint paths and atomic persistence without changing the completed transcript cache format or identity
- [x] 3.3 Validate checkpoints independently and classify missing, corrupt, checksum-mismatched, out-of-bounds, duplicate, and incompatible chunks as reusable or pending without failing the job
- [x] 3.4 Add tests for interrupted writes, mixed valid/invalid checkpoints, recognition-setting changes, plan-version changes, and compatibility with legacy completed transcript caches

## 4. Reusable per-job model sessions

- [x] 4.1 Extend the adapter contract with an explicit context-managed session that loads one model for a device attempt and accepts multiple chunk requests
- [x] 4.2 Implement Nano session reuse while preserving VAD, hotwords, timestamp normalization, segment progress observation, model revision discovery, and MPS compatibility errors
- [x] 4.3 Implement Paraformer session reuse while preserving punctuation, dynamic batching, hotwords, timestamps, and model revision discovery
- [x] 4.4 Preserve the existing single-call adapter behavior as a compatibility wrapper around one session and one request
- [x] 4.5 Add tests proving one model creation per multi-chunk attempt, cleanup on success/error, no cross-job model leakage, and unchanged single-input transcripts

## 5. Chunk extraction and global transcript merge

- [x] 5.1 Extract each planned chunk from the normalized WAV with validated duration/boundary metadata and deterministic temporary-file cleanup
- [x] 5.2 Offset chunk-local timestamp units onto the source-global timeline and concatenate non-overlapping silence-boundary chunks
- [x] 5.3 Implement deterministic overlap reconciliation using timestamp intersection and normalized suffix/prefix text matching, preserving unique units and diagnosing ambiguous boundaries
- [x] 5.4 Validate the merged Transcript for ordered bounded units, source duration, model metadata consistency, non-empty content, and stable cache identity
- [x] 5.5 Add merge tests for Chinese-English text, punctuation, exact duplicates, partial-word overlap, ambiguous overlap, empty chunks, timestamp jitter, and final-duration clamping

## 6. Resumable long-form workflow and progress

- [x] 6.1 Route inputs above the threshold through planner/manifest loading while retaining the existing unchunked workflow for short inputs and completed transcript cache hits
- [x] 6.2 Load valid chunk checkpoints before model initialization, skip committed chunks, and start the session only when pending recognition remains
- [x] 6.3 Process pending chunks sequentially, atomically checkpoint each valid normalized result before advancing, then merge and persist the completed transcript through the existing cache
- [x] 6.4 On auto-mode MPS compatibility failure, close the MPS session, establish a CPU attempt identity, reuse only compatible checkpoints, and continue from the first pending chunk
- [x] 6.5 Report resumed/total chunks, current global boundaries, committed duration, elapsed time, and duration-weighted estimated progress capped below completion until merge and final cache validation succeed
- [x] 6.6 Add workflow tests for interruption after arbitrary chunks, resume without retranscribing valid chunks, corrupt-checkpoint recovery, all-checkpoints/no-model-load behavior, fallback attempts, and one terminal event per phase

## 7. Long-form device evidence and tuning gates

- [x] 7.1 Add a separate compatible long-form performance profile keyed by model/revision, runtime, device, duration band, planner version, and major batch/VAD settings
- [x] 7.2 Select `auto` device from robust comparable long-form profiles only when sample, RTF, memory, swap, and failure guardrails are satisfied, without overriding explicit model or device choices
- [x] 7.3 Define a repeatable Nano/Paraformer CPU/MPS experiment matrix that first screens 10–15 minute material and validates finalists on 30–60 minute and resumable two-hour cases
- [x] 7.4 Compare candidate batch/VAD settings against transcript, timestamp, RTF, peak-memory, swap, and stability baselines and record explicit eligibility or rejection reasons
- [x] 7.5 Add tests for evidence insufficiency, profile incompatibility, robust device ranking, explicit-device precedence, corrupt profiles, and rejection of faster candidates that violate guardrails

## 8. End-to-end verification and documentation

- [x] 8.1 Run the full automated suite plus real Nano and Paraformer long-form smoke tests on available CPU/MPS paths, recording blockers rather than downloading models or private media implicitly
- [x] 8.2 Verify a representative two-hour run or deterministic equivalent can be interrupted and resumed with no timestamp gaps, silent text loss, invalid SRT, source modification, or retranscription of valid chunks
- [x] 8.3 Document long-form threshold/planning behavior, checkpoint location and invalidation, resume messages, device evidence, benchmark interpretation, memory/swap diagnostics, and cleanup guidance
- [x] 8.4 Record the selected conservative defaults and measured RTF/resource results, leaving unproven model/device/batch combinations opt-in or unchanged
