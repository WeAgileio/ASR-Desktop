# Runtime and service validation evidence

## Current implementation status — 2026-09-21

32/33 tasks are complete, including the user-requested OAuth extension and real Drive delivery acceptance. Only task 7.4 (M4/16GB long-audio acceptance) remains open. The historical sections below describe earlier stages; their “unimplemented/unverified” statements are superseded by the evidence here.

Implemented `src/asr_service`: authenticated FastAPI operator UI, SQLite WAL business records, transactional outbox, Redis/RQ JSON dispatch, single native SpawnWorker supervisor, separate recursive Drive scanner, persisted execution fencing/pause, local recovery manifests, preallocated Drive artifact IDs, TXT/SRT/completion delivery, restricted Dashboard, cleanup and backup commands. Compose and LaunchAgent templates plus operational instructions are in `deployment/`.

### Verified on the current M1 Max / 32 GiB Mac

- **79 existing/CLI/output tests and 29 service tests pass.** The service suite covers authentication/CSRF, database transactions and leases, deduplication, serial claims, retry limits, stale tokens, queue loss, Drive scope and pagination, source changes, multipart upload, capacity admission, cleanup, permission recovery and Dashboard mutation rejection. The original `.venv` remains separate.
- Docker Linux ARM64 API starts with **no installed PyTorch**, and `torch` is not imported. Dependencies installed successfully from the service lock. The native service inference adapter, independently exercised on the authorized local 45-second sample, produced nonempty TXT/SRT on MPS in **40.926 seconds**, emitting 14 progress callbacks.
- Real API + SQLite + Redis + RQ SpawnWorker, with explicit **fake Drive and fake inference**, processed two queued media jobs. First upload lost its response after remote creation; the second job completed while the first waited. Retry finished both jobs with **2 inference calls and 10 remote fixture objects** (five each), no duplicate result objects.
- Forced **SIGKILL of an actual RQ child** while it held the execution lock: a concurrent lock acquisition was denied; after the child exited, recovery advanced generation 0 to 1 and the job completed. No real Drive or ASR was used in this fault drill.
- Deleted only a synthetic job's real Redis/RQ record; the API outbox automatically recreated it. After a separate injected final API response loss, the durable job remained completed; duplicate invocation was skipped, with **1 inference call and 5 remote fixture objects**. The worker now reads durable state after a lost final acknowledgement and writes local completion without unnecessary RQ retry.
- Upload permission revocation is tested separately: no completion marker is written on 403; manual retry after restoration reuses local outputs and stable remote IDs, with **one inference call**.
- Replaced API and Redis containers using existing test volumes. **All 5 jobs present at that test snapshot and the global pause survived**. A native supervisor started before dependencies were available, retried connections, reconnected and exited cleanly after the signal-handling fix.
- Consistent SQLite backup restored into a **different Docker volume**: integrity check `ok`; 3 jobs, 4 outbox entries and 15 artifact rows at the backup snapshot. Later fault tests added further synthetic records. Restore never overwrote the active test database.
- Headless Chrome browser checks pass: batch submission/rescan, pause across reload, result links, nested source paths, offline labels, estimated percentage, permission errors and retry interaction. Zero JavaScript errors. Offline/progress/error fixtures were intercepted browser responses; submission/pause/result retrieval used the actual API.
- Both LaunchAgent plist templates pass `plutil -lint`. They were **not registered** with launchd. The service-account JSON was not loaded during this implementation's fixture tests and no real Drive writes were performed.

### Reproduction and evidence locations

- Unit tests: commands in `deployment/README.md`.
- Dedicated-stack fault runners: `evaluation/service_roundtrip.py`, `evaluation/service_faults.py`, `evaluation/service_ack_loss.py`. They require a private test env at `/private/tmp/asr-service-validation/compose.env`, a dedicated API on port 18090 and Redis on 16379. Use a clean test stack/workspace for the roundtrip and kill drills; never point them at production. They deliberately substitute fixture job functions and must not be exposed by the application API.
- Sanitized JSON reports and screenshot are copied to `.e2e-cache/service-validation/` (ignored local evidence). Transient logs, browser helper and restore backup are in the private `/private/tmp/asr-service-validation/` directory. No credentials are copied into reports or committed artifacts.
- Running preview stack: Compose project `asr-service-validation-2`, Web `http://127.0.0.1:18090`, restricted Dashboard `http://127.0.0.1:19181`; it contains synthetic test data. Native workers used for tests have stopped. The earlier test project was stopped; its volumes were preserved. The dedicated restore volume is separate.

### Remaining acceptance gates

1. **7.2:** The user must identify two authorized test media and a service-account-writable folder in a shared drive. Existing source access alone is insufficient for the delivery test. Do not batch-process the original source while waiting.
2. **7.4:** This machine is M1 Max/32 GiB, not M4/16 GiB. Long-audio memory, swap, MPS, heartbeat, timeout and recovery acceptance on the intended target remains outstanding.

The combined fixture service test and real local MPS test do not establish that actual Drive delivery or target-machine long recordings have passed. No Git commands or release operations were performed.


## Completed: task 1.1

- Host read-only probe: Apple M1 Max, 34,359,738,368 bytes RAM (32 GiB); this is not the specified M4/16GB target.
- Python 3.11.15 isolated environments created at `.venv-service` and `.venv-worker`; the original `.venv` was not changed.
- Clean `uv pip sync` succeeded: 25 control-plane packages and 98 native-worker packages, pinned in `deployment/requirements/`.
- API environment imports succeeded: FastAPI 0.141.1, RQ 2.12.0, Redis client 6.4.0, `rq.SpawnWorker`; `torch` is not installed in this environment.
- Worker environment imports succeeded: `rq.SpawnWorker`, Google service-account credentials, Google discovery client, Torch, torchaudio and FunASR `AutoModel`.
- Worker versions: google-auth 2.58.0, google-api-python-client 2.200.0, FunASR 1.3.12, Torch/torchaudio 2.8.0, Transformers 4.57.6.
- Existing `.venv/bin/python -m asr_srt --help` still exits successfully.

## Initial blockers (resolved for local smoke testing)

- Docker client 28.3.3 is installed, but the desktop-linux daemon is unavailable. The same connection failure occurred outside the sandbox.
- No real Redis/RQ execution or MPS inference was performed in the new environments; successful imports do not prove runtime/model compatibility.
- The target M4/16GB machine is not currently attached to this task. This host cannot supply target-hardware performance acceptance evidence.
- No Drive mutations, downloads, launchd registration, Git operations or changes to existing source modules were performed.
- Linux container dependency installation, Docker restart recovery and real Drive publication remain unverified. A writable test destination is still required.

The user subsequently started Docker and authorized testing on the current host. Task 1.2 now covers local compatibility testing; task 7.4 retains target-hardware acceptance. Application entry points (task 1.3) have not yet been implemented.

## Completed: task 1.2 local compatibility smoke

- Docker Desktop 4.45.0, Engine 28.3.3, Linux ARM64. Isolated Redis 7.4 Alpine container, loopback port 16379, no persistent data, separate generated queue name.
- Redis image digest: `sha256:520775a41a63e77e06c73e35d2fd9cc15921a609516818796b4ecbb813078bc7`.
- Runner: `evaluation/rq_smoke.py`, executed with the native `.venv-worker`, `PYTHONPATH=src:evaluation`, JSON queue serialization and `rq.SpawnWorker`.
- Source: 45 seconds extracted from the already-local audio cache of the earlier user-supplied talk. The original Downloads MP3 is no longer present. No Drive access or mutations.
- Both jobs disabled transcript-cache reuse and completed on `mps`, each generating 237 characters and 16 subtitle cues.

| Metric | Job 1 | Job 2 |
| --- | --- | --- |
| Job wall time including model load (seconds) | 50.944 | 36.481 |
| Peak process RSS (MiB) | 6494.203 | 6616.797 |
| In-process heartbeat samples | 49 | 36 |
| Maximum heartbeat gap (seconds) | 2.223 | 1.168 |
| Child exited after completion | yes | yes |
| System swap before / after (MiB) | 9889.56 / 13100.31 | 13100.31 / 13790.25 |
| System-wide free-memory percentage before / after | 43 / 29 | 48 / 31 |

The second job started 0.365 seconds after the first finished. Both child PIDs no longer existed when checked, demonstrating process teardown (not a direct GPU allocation measurement). The timer heartbeat proves a background thread continued during this workload; future API heartbeat delivery and failure recovery are not yet tested. The RQ parent used a five-second job monitoring interval.

Raw report: `.e2e-cache/rq-smoke/run-1/report.json` (ignored local test data). The runner asserts MPS use, nonempty output, child exit, no overlap and maximum heartbeat gap below 90 seconds.

System swap was already high before testing and other applications were not controlled. These are whole-system measurements, not ASR-only memory attribution or M4/16GB sizing evidence. Peak RSS also does not represent total unified GPU memory usage.

This test validates Docker Redis -> native RQ -> real FunASR/MPS -> local SRT. Web submission, SQLite state, Drive delivery and service restart recovery remain unimplemented/unverified and are not claimed to have passed.

## Destination preflight — user-provided folder

Read-only check using the user-provided service-account credentials for folder `1nTmsohSnxRdTbrUGjkl-KJSW5rMg85dD` returned name `test`, folder MIME type, `trashed=false`, `canListChildren=true`, and `canAddChildren=true`. The response did not contain `driveId`; this is not a shared-drive folder. No upload or folder creation was attempted. The current service's shared-drive destination preflight therefore blocks this destination, and task 7.2 remains open. Supporting this My Drive destination would require user OAuth or an appropriately authorized impersonated Workspace user rather than standalone service-account ownership.

Reference: https://developers.google.com/workspace/drive/api/guides/about-shareddrives (service accounts lack storage quota and cannot own files).

## User OAuth authorization completed

The user supplied an installed/Desktop OAuth client and personally completed browser authorization. Added explicit `ASR_DRIVE_AUTH=oauth`, native PKCE/loopback login, private atomic token persistence, and mode-aware destination validation. Existing service-account mode still rejects My Drive destinations. Added six native OAuth tests; all pass, as do the 29 existing service tests. No private client data, access token or refresh token is recorded here.

- The token was successfully saved outside the synchronized project with permissions `0600`.
- User OAuth preflight passed for the original source (`2025_倪海廈`, listing/download allowed) and provided destination (`test`, child creation allowed, no shared-drive ID).
- Read-only recursive discovery found 570 media items. No production batch was created and no media was downloaded during this authorization check.
- A private `host.oauth.json` configuration was prepared under the local Application Support configuration directory for the current validation API on port 18090. The credentials are not mounted in Docker. Native worker/scanner have not been started for this source.
- Tasks 8.1–8.3 are complete. Actual upload/inference acceptance (7.2) still requires the user to select two files; M4/16GB acceptance (7.4) remains open.
- Operational note: External/Testing Google OAuth apps using Drive scopes may have seven-day refresh-token expiry; the deployment guide documents reauthorization and consent-screen settings.

## Real Drive acceptance attempt — silent source samples

Task 7.2 was attempted with the two previously proposed smallest files, 金匱要略 重制 73 and 82. OAuth created a bounded test tree under the user-provided `test` folder, then copied only those two media files into a dedicated input folder. Checksums of the copies match the originals. The unchanged native scanner published exactly two jobs through the real API, and the real RQ/MPS worker downloaded both. Original media were not modified.

Both audio streams are silent: ffprobe durations 46.468 s / 31.008 s; FFmpeg volumedetect mean and maximum levels were -91.0 dB for each. FunASR returned “Model result is missing recognized text”. Both jobs reached retry_wait; subsequent claims were globally paused and the acceptance supervisor was stopped gracefully to avoid repeated inference of silent input. No TXT/SRT/completion delivery passed. This is evidence of actual Drive folder creation/copy/download, not successful end-to-end transcription acceptance.

Evidence: `.e2e-cache/drive-live/manifest.json`, `failure-report.json`, `latest.json`, `worker.log`. `evaluation/drive_live.py` is the explicit two-file live runner; it requires authorized file IDs and destination, creates copies instead of scanning the original 570-file tree, and retains its manifest for inspection. It is not automatically scheduled.

Task 7.2 remains incomplete pending non-silent test media. Task 7.4 remains incomplete: a fresh hardware probe still reports Apple M1 Max / 34,359,738,368 bytes RAM, not M4 / 16 GiB. No Git commands were performed.

## Passed: task 7.2 real Drive + MPS acceptance

After the silent samples failed, the user agreed to use the previously supplied AI project-management talk. Two 20-second spoken clips were extracted from its already-local 45-second test audio. They were uploaded only to a dedicated acceptance input folder within the authorized `test` destination. The original talk and original 570-file source tree were not modified. The two silent tasks were recorded as failed with an explicit silent-audio reason through the worker API under the host execution lock; they will no longer automatically retry.

The unmodified native scanner enumerated exactly the two audible inputs. Actual API submission, SQLite outbox, Redis/RQ, native SpawnWorker, FunASR on MPS, and OAuth Drive download/upload all ran successfully. Both tasks reached completed. Their remote TXT, SRT, and completion JSON files were read back as metadata and their MD5 checksums matched local artifacts.

| Metric | Spoken clip 1 | Spoken clip 2 |
| --- | --- | --- |
| Input duration | 20 s | 20 s |
| RQ job wall time (download + inference + upload) | 44.729 s | 38.733 s |
| Device | mps | mps |
| Subtitle cues | 8 | 6 |
| Last subtitle end | 20,000 ms | 19,920 ms |
| TXT characters including label | 127 | 128 |

Second job started 1.337 seconds after the first ended; no overlap. A real Chrome browser verified both completed rows and three Drive result links per job, with zero JavaScript errors. No response interception or fake inference/Drive was used for this acceptance. The native acceptance worker exited after both tasks completed; ongoing automatic scanning was not enabled.

Result folder: https://drive.google.com/drive/folders/1zB2_5QNEO_aO-5puHo7JAGBxfZ71Jv1T

Evidence: `.e2e-cache/drive-spoken/report.json`, `browser-report.json`, `manifest.json`, `latest.json`, `worker.log`, `web.png`. These ignored local artifacts contain no credentials. The earlier live acceptance failure remains recorded separately in `.e2e-cache/drive-live/`.

Task 7.2 is now complete. Task 7.4 remains open: these short tests ran on M1 Max/32 GiB and do not establish M4/16 GiB long-recording performance or resource acceptance.
