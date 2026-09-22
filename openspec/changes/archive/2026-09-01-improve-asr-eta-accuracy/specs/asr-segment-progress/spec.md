## MODIFIED Requirements

### Requirement: Progress fallback hierarchy
The system SHALL prefer a valid whole-input segment estimate for transcription percentage, otherwise use a compatible historical RTF estimate, and otherwise report indeterminate progress. ETA SHALL be computed independently from compatible historical RTF or calibrated runtime evidence and MUST NOT be derived by treating segment workload units as seconds.

#### Scenario: Segment workload and compatible time evidence are available
- **WHEN** valid whole-input segment measurements and a compatible historical or calibrated time estimate are available
- **THEN** the workflow uses segment measurements for estimated percentage and supplies the independent time estimate as `eta_seconds`

#### Scenario: Segment workload exists without compatible time evidence
- **WHEN** valid whole-input segment measurements are available but no compatible historical or calibrated time estimate exists
- **THEN** the workflow displays estimated percentage and elapsed time without ETA

#### Scenario: Segment workload is unavailable but compatible history exists
- **WHEN** no valid segment measurement is available and a compatible historical RTF estimate exists
- **THEN** the workflow shows time-based estimated percentage and ETA in seconds

#### Scenario: Neither measurement is available
- **WHEN** neither valid segment workload nor compatible historical or calibrated time evidence is available
- **THEN** transcription remains indeterminate with an active indicator and elapsed time

#### Scenario: Early segment fraction is very small
- **WHEN** a segment-derived percentage begins with a small non-zero fraction
- **THEN** the system MUST NOT extrapolate ETA solely by dividing elapsed time by that fraction
