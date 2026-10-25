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

## Batch names

`batches.list` accepts `offset` (0) and `limit` (100, maximum 500), returning
`batches` and the total number of batches. Each summary contains `id`, `name`,
`created`, `total` jobs and `counts` by state. Ordering is `created DESC,id`;
queue ordering is unchanged. Old unnamed batches use local submission time and
the first valid source filename from the original submission plan.

`batches.rename` accepts batch `id` and `name`. The trimmed name must contain
1–100 Unicode code points (not grapheme clusters); duplicate names are allowed.
It returns `id` and the saved `name`, emits `batch.renamed`, and uses transactional
request-ID replay. Names do not change IDs, submission settings or output paths.
Both operations are advertised in `service.status` capabilities.

## Search and selection

`jobs.list` additionally accepts string `query` and array `states`. Trimmed,
case-insensitive literal filename or effective batch-name matching intersects
with the batch scope and union of states. Empty conditions mean all; unknown
states and wrong types are rejected. Filtering precedes pagination; order remains
`created,id`. `counts` and `scope_counts` count the selected batch (or all jobs)
before query/state filtering. `matched_counts` and `total` cover all filtered pages.
Searching reads metadata only, not media or delivery ledgers.

`jobs.selection.preview` accepts `selector`, either `{"ids":["job-example"]}`
or a query object containing optional `batch_id`, `query`, `states` (empty object
means all jobs). These forms cannot be mixed. Missing explicit IDs/batches return
`not_found`; empty matches return zero. Duplicate IDs are deduplicated.
The readonly response contains normalized `selector`, `total`, `counts`,
`retryable_count`, `cannot_remove` (IDs and reasons), and `target_token`.
The token covers normalized conditions and all matched IDs/states/attempt IDs,
not just the current page. Optional `target_token` checks an existing selection;
changes return `selection_changed`, requiring refresh and reconfirmation.

```json
{"protocol_version":1,"id":"preview-example","operation":"jobs.selection.preview","arguments":{"selector":{"query":"中文_%'","states":["failed","cancelled"]}}}
```

## Retry and record removal

Capability markers `jobs.list.query` and `jobs.retry.selection` advertise the new
parameters on existing operations. They are feature markers, not standalone RPCs.
`jobs.retry` still accepts legacy `id` with unchanged failed/cancelled/interrupted
scope. Alternatively pass `selector` and optional boolean `failed_only` (default
false), never mixed with `id`. An unfiltered batch selector evaluates all jobs in
that batch at action time; a query selection requires its `target_token`.
Explicit IDs are evaluated in their current states. New responses contain
`retried_count`, `skipped_count`, `skipped` IDs/reasons and retried `job_ids`.
Zero eligible jobs is a successful zero count for this new form. Source validation
is atomic: `source_unavailable` or `source_changed` includes the affected job ID;
no eligible job is partially retried. Clients retain the same request ID and
payload after transport failure; native retry uses a 120-second timeout.

`jobs.remove` requires `selector` and `target_token` from preview. In one
transaction it rechecks selection, refuses running/cancelling or unreaped attempts
(`worker_not_reaped`), deletes attempts then jobs, and removes only empty batches.
It returns `removed_count` and `job_ids`, emitting `job.removed` for each ID.
Queued jobs are removed from future scheduling. Both new mutations use persisted
request replay, including a replay after rows no longer exist. A replayed submit
returns its historical IDs but does not recreate removed jobs. Authoritative
list/show/snapshot must be refreshed; removed detail returns `not_found`.
No source, output, cache, ledger or log files are deleted. There is no undo.
Requests above 64 KiB must be reduced or use query selection, never truncated or
split into several non-atomic removals.

## Media inspection and output availability

`intake.inspect` starts a read-only inspection with `paths` and optional boolean
`recursive`, returning `id` and `state: reading`. Poll the same operation with
only `id` until `state: complete`, which includes per-file `entries` with `source`,
`status`, `duration_ms` or individual `error`/`error_code`. It needs neither output
settings nor models. Discovery/deduplication/symlink exclusion match preview;
no full source fingerprint, batch or job is created. Two background workers and
two outstanding inspections bound resource use; `inspection_busy` means retry
later. Completed results are retained in a small in-memory cache (not durable);
`not_found` means inspect again. FFprobe has a 30-second per-file timeout.
Control requests and scheduling continue while these workers probe media.

Single-job `jobs.show` adds `delivered_outputs` (format to existing file path),
`missing_outputs`, `undelivered_outputs` and `legacy_outputs`. Only committed
records for that job and its planned paths count as delivered; prepared records
never do. With no ledger, old completed jobs use existing planned outputs as a
compatibility fallback. A malformed ledger does not permit that fallback.
Lists/search do not read ledgers or hash outputs; planned `outputs` alone are not
evidence of delivery.
