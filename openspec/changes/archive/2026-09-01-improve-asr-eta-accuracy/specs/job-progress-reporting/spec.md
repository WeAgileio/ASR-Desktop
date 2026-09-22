## ADDED Requirements

### Requirement: Unit-safe ETA ownership
The system MUST treat progress workload and remaining wall-clock time as separate quantities. Renderers SHALL display ETA only from an explicit non-negative seconds value supplied by the progress producer and MUST NOT reinterpret workload `current`, `total`, or `unit` values as seconds.

#### Scenario: Estimated workload is expressed in milliseconds
- **WHEN** a running estimated progress event contains millisecond `current` and `total` values and no explicit ETA
- **THEN** the renderer shows the workload percentage and elapsed time without displaying an ETA

#### Scenario: Producer supplies an explicit ETA
- **WHEN** a running progress event supplies a valid `eta_seconds` value alongside workload values in any supported unit
- **THEN** plain and rich renderers format that seconds value as the estimated remaining duration without replacing it from workload values

#### Scenario: Heartbeat advances after an ETA event
- **WHEN** a renderer refreshes a running event after wall-clock time passes without a new producer event
- **THEN** it MAY decrement the supplied ETA by that wall-clock interval but MUST NOT mix elapsed seconds with non-second workload values

### Requirement: Reliable ETA fallback
The system SHALL omit ETA when no compatible and dimensionally valid time estimate exists, while preserving any independently valid percentage and elapsed-time display.

#### Scenario: Segment percentage exists without time evidence
- **WHEN** valid segment-derived workload progress exists but compatible historical or calibrated time evidence does not
- **THEN** the system displays the estimated percentage and elapsed time without inventing an ETA

#### Scenario: Estimate is invalid
- **WHEN** an ETA calculation produces a negative, non-finite, dimensionally invalid, or rejected implausible value
- **THEN** the system discards the ETA and continues transcription with elapsed-only time reporting

### Requirement: ETA regression evidence
The system MUST validate ETA behavior with deterministic unit and replay tests covering the supported renderers and representative ASR progress traces.

#### Scenario: Millisecond regression trace is rendered
- **WHEN** a test replays a long-form progress event whose total is several million milliseconds
- **THEN** neither renderer displays that millisecond workload as millions of remaining seconds

#### Scenario: Compatible recorded traces are replayed
- **WHEN** repository regression traces contain sufficient compatible historical and checkpoint evidence
- **THEN** the ETA estimator achieves a median absolute percentage error of no more than 20 percent at the defined evaluation points
