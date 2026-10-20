# Implementation progress — 2026-10-20

Overall **35/46 tasks complete**. Groups 1–4, 5.1–5.5, 6.2–6.5 and 8.1 are complete. Tasks 5.6, 6.1, 7.1–7.5 and 8.2–8.5 remain open. Do not archive this change yet.

Evidence and reproduction commands: [desktop/VALIDATION.md](../../../desktop/VALIDATION.md) and [desktop/README.md](../../../desktop/README.md).

## Confirmed implementation

- Native arm64 SwiftUI, CLI and helper targets build; 5 native tests and 121 source regression tests pass.
- Pinned Python 3.11.15/FunASR runtime freezes independently of the existing worker environment. Standalone FFmpeg/FFprobe have only system-library dependencies.
- Frozen-runtime imports, OpenCC and actual 16 kHz mono media normalization pass with developer PATH removed and invalid external Python paths set.
- Catalog pins four components to immutable commits and hashes. All 29 required assets have been verified in independent build-only snapshots.
- Eight real packaged CPU/MPS smoke cases pass for two models and Mandarin/mixed public examples, with nonempty text and valid timestamps.
- Shared immutable model preparation, SQLite jobs/events/settings, idempotent mutations, serial process-group workers, cancellation/recovery and protected TXT/SRT/JSON delivery are implemented and tested.
- Four real packaged Nano/Paraformer public-file batch jobs complete with all requested exports. Real control checks cover cancellation/retry, replay, observer interruption, calibration, partial failure and exit codes 0/1/2/3/130.
- The development image is built, checksum-verified, mounted read-only and tested after relocation. All 281 Mach-O files support arm64 and have no non-system absolute dependencies. No model weights are bundled.

## Blocking evidence

The staged ad-hoc-signed App passes strict signature verification, but SMAppService-managed launch is rejected by AMFI/launchd with `has no CMS blob?`, `Launch Constraint Violation`, and `OS_REASON_CODESIGNING`. This host has zero available Apple code-signing identities. Registration reporting enabled is not proof of a running service.

The user explicitly selected direct-helper development mode. Development App and CLI are visibly marked, service survives CLI and GUI exit, repeated starts use the same PID, and safe stop cleans up the socket. The formal profile rejects development launch. Task 1.5 is complete under that approved scope; managed-service acceptance remains pending in task 8.2. A second clean locked Python environment reproduced the frozen runtime/import/media smoke, completing 1.6. This does not substitute for a second Mac or minimum-OS acceptance. No operating-system protection was disabled; all test services were stopped.

The GUI with local private data visibly loads the same 12-job history (11 completed, 1 failed). Subsequent UI automation failed with `Sky Computer Use native pipe closed before response`; reset/rebind did not recover it. Full interaction acceptance stays unchecked. An iCloud data-root probe stalled in os_open; local data worked, and the precise cause remains unconfirmed. The product defaults to local Application Support. All test services were stopped.

Reviewed quality baselines are not established: real observations cannot promote auto GPU. Fresh-account/minimum-OS and representative long recordings remain unverified. Formal managed-service acceptance remains deferred under the user's explicit development-mode choice.

## GUI connection retry — 2026-10-20

At the user's request, CUA reconnected to the isolated development App and read the import-window accessibility tree. The development/paused labels, four tabs, import/output controls, model/device/script selectors and export checkboxes were visible. Preview and submit were correctly disabled with no selected input. Clicking Models then returned `Sky Computer Use native pipe closed before response`; the resulting tab state could not be verified. Kernel reset and exact-path rebind failed again. Inventory still worked, so the evidence identifies failed native App interaction rather than proving every tool surface is unavailable. The shared bundle identifier is ambiguous across installed/build/test copies; retrying the tool-reported `/tmp` test path also failed. No task in 7.1–7.5 is newly accepted. The App was relaunched during this retry; service shutdown has not been rechecked. Detailed evidence is in `build/desktop/gui-validation-evidence.json`. Formal signing remains deferred as instructed.

No Git commands, commits, tags, pushes or releases were performed. The current product remains under development; successful smoke cases do not establish macOS 14, long-recording performance, complete GUI/CLI parity, or formal-distribution acceptance.
