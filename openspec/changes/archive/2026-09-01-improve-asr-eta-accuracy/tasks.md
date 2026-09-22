## 1. Unit-Safe Progress Contract

- [x] 1.1 Add progress-event and renderer regression tests proving millisecond, item, and segment workload values are never interpreted as ETA seconds
- [x] 1.2 Update the shared renderer snapshot behavior to preserve explicit `eta_seconds`, decrement it only by heartbeat wall time, and avoid mixing elapsed seconds with non-second workload values
- [x] 1.3 Add matching plain and rich renderer tests for explicit ETA, missing ETA, heartbeat countdown, terminal completion, and invalid-estimate fallback

## 2. ETA Estimator

- [x] 2.1 Introduce a unit-tested ETA estimator that validates finite non-negative seconds, loads compatible robust historical RTF evidence, and returns no estimate when evidence is insufficient
- [x] 2.2 Implement independent percentage and ETA state so segment workload callbacks can retain percentage while carrying the latest valid `eta_seconds`
- [x] 2.3 Add bounded within-chunk smoothing and tests showing tiny early segment fractions do not create extreme extrapolations or abrupt oscillation

## 3. Short-Form Workflow Integration

- [x] 3.1 Connect compatible historical RTF estimates to short-form transcription events without allowing segment workload units to overwrite ETA
- [x] 3.2 Preserve the existing global-progress, segment-progress, historical fallback, indeterminate, retry-epoch, and cache-hit hierarchy with workflow regression tests
- [x] 3.3 Verify short-form recognition arguments, transcript content, timestamps, cache identity, and SRT output remain unchanged by ETA calculation

## 4. Long-Form Calibration and Resume

- [x] 4.1 Calculate committed unique audio duration and cumulative observed chunk RTF from valid checkpoint transcript processing metadata without double-counting overlap
- [x] 4.2 Blend compatible historical RTF with committed-work RTF and attach recalculated `eta_seconds` to chunk progress and checkpoint events
- [x] 4.3 Make resume ETA exclude completed chunks while using their compatible timing evidence, with tests for mixed valid, corrupt, and incompatible checkpoints
- [x] 4.4 Add tests proving slower committed chunks may honestly increase ETA, checkpoint evidence may recalibrate immediately, and running ETA cannot falsely reach zero before completion

## 5. Accuracy Evidence and Verification

- [x] 5.1 Add deterministic replay fixtures from representative local ASR traces with durations, units, chunk boundaries, segment fractions, processing times, resume state, and final completion time
- [x] 5.2 Add an accuracy regression test reporting initial and checkpoint absolute percentage error and enforcing median error no greater than 20 percent where compatible evidence exists
- [x] 5.3 Run the complete unit and real-media-safe test suite and confirm ETA-only changes do not invalidate transcript or checkpoint caches
- [x] 5.4 Update README progress documentation to describe explicit ETA seconds, checkpoint recalibration, estimated-value uncertainty, and elapsed-only fallback when evidence is unavailable
