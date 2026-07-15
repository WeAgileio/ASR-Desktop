## 1. Adapter progress contract

- [ ] 1.1 Extend `AdapterProgress` with explicit measurement kind, whole-input scope, unit, and attempt/epoch semantics while preserving compatibility for adapters that emit no structured progress
- [ ] 1.2 Add validation for finite positive totals, bounded current values, stable totals, and supported kind/scope combinations
- [ ] 1.3 Add contract tests proving batch-local callbacks cannot be promoted to whole-input progress and valid segment measurements remain estimated

## 2. Segment workload ledger

- [ ] 2.1 Implement an isolated ledger that validates VAD `[start_ms, end_ms]` ranges, reproduces the required duration ordering, and calculates a fixed total speech duration
- [ ] 2.2 Track successfully completed segment durations across unequal dynamic batches and emit bounded monotonic current/total measurements capped below completion
- [ ] 2.3 Disable the ledger without raising a transcription error when segment data, result counts, numeric values, or schedule mappings are inconsistent
- [ ] 2.4 Add unit tests for unequal durations, empty and malformed VAD output, zero-duration segments, batch boundaries, overflow, and final pre-terminal capping

## 3. FunASR observation bridge

- [ ] 3.1 Verify and document the installed FunASR VAD/ASR call topology and choose a guarded runtime capability probe for supported versions
- [ ] 3.2 Implement a context-managed pass-through observation bridge that captures VAD results and main ASR completion boundaries without modifying arguments, return values, or scheduling
- [ ] 3.3 Guarantee observer restoration on success, inference failure, malformed runtime behavior, and repeated model use
- [ ] 3.4 Add compatibility tests using representative FunASR call shapes and prove unsupported shapes fall back cleanly

## 4. Adapter and workflow integration

- [ ] 4.1 Integrate the observation bridge and segment ledger into FunASR Nano while retaining its existing VAD parameters, model arguments, normalization, timestamps, and native progress-bar suppression
- [ ] 4.2 Integrate the same capability into Paraformer without changing punctuation, hotword, dynamic batch, or timestamp behavior
- [ ] 4.3 Update the workflow to prefer valid segment-derived estimated percentage, retain compatible historical RTF for ETA, and otherwise preserve the existing RTF/indeterminate fallback hierarchy
- [ ] 4.4 Reset the measurement epoch on MPS-to-CPU retry, emit a clear retry message, and prevent completed work from the failed attempt being combined with the CPU attempt

## 5. Verification and documentation

- [ ] 5.1 Add workflow tests for monotonic duration-weighted estimates, stable totals, running progress below 100%, terminal completion, fallback hierarchy, and retry epochs
- [ ] 5.2 Add adapter regression tests confirming progress enabled and disabled produce identical transcript text, timestamps, model calls, and cache identity
- [ ] 5.3 Run the full automated suite and installed Nano/Paraformer smoke tests on supported macOS devices, including an input with unequal VAD segment durations
- [ ] 5.4 Document that transcription percentage is segment-duration estimated, explain why it can differ from wall-clock progress, and describe runtime fallback behavior
