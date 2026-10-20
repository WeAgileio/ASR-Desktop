# Local desktop protocol

Both native clients use protocol version 1, a private Unix socket and one JSON line per connection. Requests contain `protocol_version`, `id`, `operation`, and an `arguments` object. Responses echo the version and request ID, then contain `success` and either `result` or `error` (`code`, `message`, optional details). No model logs are written to this stream. Paths sent by clients are absolute. Request size is bounded at 64 KiB; native responses at 8 MiB.

```json
{"protocol_version":1,"id":"client-command-1","operation":"submit","arguments":{"paths":["/Users/example/recording.mp4"],"output_dir":"/Users/example/Transcripts","settings":{"model":"paraformer","device":"auto","formats":["txt","srt"],"script":"traditional"}}}
```

Submission returns an accepted batch ID and job IDs. It does not imply execution completed. The source fingerprint, exact model definition, settings and planned output paths are frozen. Missing models produce `blocked` jobs without downloading them. The queue starts paused on service launch; `queue.resume` explicitly allows work. A missing model does not prevent later ready jobs from running.

```json
{"protocol_version":1,"id":"client-command-1","success":true,"result":{"id":"batch-example","job_ids":["job-example"],"accepted_count":1,"excluded":[]}}
```

`submit`, `jobs.retry`, `jobs.cancel`, `settings.set`, `queue.pause`, `queue.resume` and `device.calibrate` persist request ID, a canonical payload digest and their result in the same SQLite transaction. Repeating the ID with identical content replays the result. Different content receives `request_id_conflict`. Clients must preserve IDs when retrying a lost response. Model preparation uses a snapshot file lock and immutable asset identity instead of creating duplicate transfers.

| Operation | Arguments / behavior |
| --- | --- |
| `service.status` | Actual process ID, mode, supported operations and execution readiness |
| `service.stop` | Optional boolean `force`; pause new work, wait for the current group, or cancel it when forced |
| `intake.preview`, `submit` | `paths`, `output_dir`, optional `recursive`, `settings` |
| `jobs.list` | `offset` (default 0), `limit` (default 100, maximum 500), optional `batch_id` |
| `jobs.show` | `id`; batch responses include authoritative counts across every file and a paged job list |
| `jobs.cancel`, `jobs.retry` | `id` of job or batch; batch mutations apply to every matching file |
| `queue.status`, `queue.pause`, `queue.resume` | Persisted pause controls only new claims |
| `models.list` | Catalog identity, progress, storage requirement and actual readiness |
| `models.download`, `models.verify`, `models.remove` | Model ID or immutable snapshot `id`; preparation returns before inference readiness |
| `settings.show`, `settings.set` | `set` accepts a partial `settings` object; only future jobs change |
| `device.explain` | Optional job `id`, otherwise current settings and optional `duration_seconds` |
| `device.calibrate` | Exactly one `paths` entry, optional `settings`; creates explicit CPU/GPU jobs sharing the serial queue |
| `events.poll` | Nonnegative `cursor`, optional `limit` up to 1000; durable ordered event pages |

`events.poll` returns `events` and a new `cursor`. Events contain sequence, kind, entity ID, time and details. A cursor outside retained history receives `reset=true`, the newest cursor and an authoritative first-page snapshot; clients fetch additional job pages as needed. Lifecycle events persist immediately; running progress is coalesced to at most one update per 250 ms. Worker events are accepted only for the active attempt ID. At most 10,000 recent events are retained; job records remain authoritative.

Jobs transition through `blocked`, `queued`, `running`, `cancelling`, `completed`, `failed`, `cancelled`, or `interrupted`. Worker/service crashes pause the queue and require explicit retry; queue resume alone never changes an interrupted job to queued. Retry verifies source content and the pinned model again. Cancellation allows 5 seconds of cooperative shutdown, then TERM, then 5 seconds before KILL; no next inference starts until all live group members have exited.

Errors include `protocol_mismatch`, `invalid_request`, `invalid_arguments`, `invalid_settings`, `request_id_conflict`, `not_found`, `model_not_ready`, `model_in_use`, `insufficient_space`, `download_failed`, `checksum_mismatch`, `source_changed`, `output_conflict`, `newer_schema`, and `worker_interrupted`. Permission failures never grant readiness. A cached transcript or delivery ledger can be reused after output failure; an unowned existing file cannot be silently replaced.

CLI output is JSON; watch uses NDJSON events. Exit codes: 0 operation accepted/success, 1 failed/cancelled wait, 2 invalid arguments, 3 missing prerequisite, 130 interrupted observation. `submit --wait` returns 3 for blocked, interrupted or paused pending work. Ctrl-C exits the observer only. The user must explicitly cancel accepted work.
