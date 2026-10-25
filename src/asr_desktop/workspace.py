"""The coordinator's command surface; clients never write SQLite directly."""

from pathlib import Path
import time

from .database import Database, NONTERMINAL, StateError, encode, new_id
from .intake import preview, settings, source_matches
from .models import ModelStore
from .device_policy import DevicePolicy
from .inspection import Inspections

OPERATIONS = ("intake.inspect", "intake.preview", "submit", "jobs.list", "jobs.show", "jobs.cancel", "jobs.retry",
              "batches.list", "batches.rename", "jobs.selection.preview", "jobs.remove", "jobs.retry.selection", "jobs.list.query",
              "queue.status", "queue.pause", "queue.resume", "models.list", "models.download", "models.verify", "models.remove",
              "settings.show", "settings.set", "device.explain", "device.calibrate", "events.poll")


class Workspace:
    def __init__(self, root, ffprobe, catalog=None):
        self.root, self.ffprobe = Path(root), ffprobe
        self.database = Database(self.root / "workspace.sqlite3")
        self.models = ModelStore(self.root / "models", catalog=catalog, references=self.database.references)
        self.device = DevicePolicy(self.database)
        self.inspections = Inspections(ffprobe)
        # The scheduler reconciles old process groups before it accepts new work.
        with self.database.transaction():
            self.database.set_setting("queue_paused", True)

    def dispatch(self, request):
        operation = request.get("operation")
        arguments = request.get("arguments", {})
        if not isinstance(arguments, dict):
            raise StateError("invalid_arguments", "arguments must be an object")
        db = self.database
        if operation == "intake.inspect":
            return self.inspections.dispatch(arguments)
        if operation == "batches.list":
            return db.batches(arguments.get("offset", 0), arguments.get("limit", 100))
        if operation == "models.list":
            return self.models.list()
        if operation in ("models.download", "models.verify", "models.remove"):
            identifier = arguments.get("id")
            if not isinstance(identifier, str):
                raise StateError("invalid_arguments", "A model or snapshot id is required")
            return {"models.download": self.models.start, "models.verify": self.models.verify,
                    "models.remove": self.models.remove}[operation](identifier)
        if operation == "settings.show":
            return db.defaults()
        if operation == "device.explain":
            if arguments.get("id"):
                job = db.job(self._id(arguments))
                return self.device.explain(job["snapshot"], job["settings"], job["duration_ms"] / 1000, job["model_definition"])
            changes = arguments.get("settings", {})
            duration = arguments.get("duration_seconds", 30)
            if not isinstance(changes, dict) or type(duration) not in (int, float) or not 0 < duration < float("inf"):
                raise StateError("invalid_arguments", "Provide valid settings and a finite positive duration")
            options = settings({**db.defaults(), **changes}, self.models.catalog)
            definition = self.models.definition(options["model"])
            return self.device.explain(definition["snapshot_id"], options, duration, definition)
        if operation == "queue.status":
            return {"paused": db.setting("queue_paused")}
        if operation == "jobs.list":
            batch_id = arguments.get("batch_id")
            query, states = arguments.get("query", ""), arguments.get("states")
            counts = db.job_counts(batch_id)
            matched = db.job_counts(batch_id, query, states)
            return {"jobs": db.jobs(arguments.get("offset", 0), arguments.get("limit", 100), batch_id, query, states),
                    "total": sum(matched.values()), "counts": counts, "scope_counts": counts,
                    "matched_counts": matched, "queue_paused": db.setting("queue_paused")}
        if operation == "jobs.selection.preview":
            return db.selection(arguments.get("selector"), arguments.get("target_token"))[0]
        if operation == "jobs.show":
            identifier = self._id(arguments)
            if identifier.startswith("batch-"):
                batch = db.connection.execute("SELECT details FROM batches WHERE id=?", (identifier,)).fetchone()
                if not batch:
                    raise StateError("not_found", "No such batch")
                counts = {row["state"]: row["count"] for row in db.connection.execute(
                    "SELECT state,COUNT(*) AS count FROM jobs WHERE batch_id=? GROUP BY state", (identifier,))}
                return {"id": identifier, "counts": counts,
                        "jobs": db.jobs(arguments.get("offset", 0), arguments.get("limit", 100), identifier)}
            from .exports import output_availability
            job = db.job(identifier)
            return {**job, **output_availability(job, self.root)}
        if operation == "events.poll":
            return db.events(arguments.get("cursor", 0), arguments.get("limit", 200))
        if operation == "intake.preview":
            return self._preview(arguments)
        if operation not in ("submit", "jobs.retry", "jobs.cancel", "queue.pause", "queue.resume", "settings.set", "device.calibrate", "batches.rename", "jobs.remove"):
            raise StateError("unsupported_operation", "This workspace operation is not available")
        return db.command(request.get("id"), operation, arguments,
                          lambda: self._mutate(operation, arguments))

    @staticmethod
    def _id(arguments):
        identifier = arguments.get("id")
        if not isinstance(identifier, str):
            raise StateError("invalid_arguments", "A job or batch id is required")
        return identifier

    def _preview(self, arguments):
        changes = arguments.get("settings", {})
        if not isinstance(changes, dict):
            raise StateError("invalid_settings", "settings must be an object")
        if type(arguments.get("recursive", False)) is not bool:
            raise StateError("invalid_arguments", "recursive must be a boolean")
        return preview(arguments.get("paths"), arguments.get("output_dir"),
                       {**self.database.defaults(), **changes}, self.ffprobe, arguments.get("recursive", False), self.models.catalog)

    def _mutate(self, operation, arguments):
        db = self.database
        if operation == "batches.rename":
            return db.rename_batch(arguments.get("id"), arguments.get("name"))
        if operation == "jobs.remove" or (operation == "jobs.retry" and "selector" in arguments):
            if "id" in arguments:
                raise StateError("invalid_arguments", "id and selector cannot be mixed")
            selector = arguments.get("selector")
            token = arguments.get("target_token")
            if operation == "jobs.remove" and (not isinstance(token, str) or not token):
                raise StateError("invalid_arguments", "Removal requires a preview target_token")
            summary, rows = db.selection(selector, token)
            if operation == "jobs.remove":
                if summary["cannot_remove"]:
                    raise StateError("worker_not_reaped", "Stop jobs and wait for worker cleanup, then confirm again", jobs=summary["cannot_remove"])
                for row in rows:
                    db.connection.execute("DELETE FROM attempts WHERE job_id=?", (row["id"],))
                    db.connection.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
                    db.event("job.removed", row["id"], {"batch_id": row["batch_id"]})
                for batch_id in {r["batch_id"] for r in rows}:
                    db.connection.execute("DELETE FROM batches WHERE id=? AND NOT EXISTS(SELECT 1 FROM jobs WHERE batch_id=?)", (batch_id, batch_id))
                return {"removed_count": len(rows), "job_ids": [r["id"] for r in rows]}
            failed_only = arguments.get("failed_only", False)
            if type(failed_only) is not bool:
                raise StateError("invalid_arguments", "failed_only must be boolean")
            # Unfiltered batch retry is evaluated at action time; query-all must
            # retain the selection token to avoid silently adding new matches.
            if "ids" not in selector and set(selector) != {"batch_id"} and not isinstance(token, str):
                raise StateError("invalid_arguments", "Query retry requires the selection target_token")
            eligible_states = ("failed",) if failed_only else ("failed", "cancelled", "interrupted")
            eligible = [db.job(r["id"]) for r in rows if r["state"] in eligible_states]
            self._validate_retry_sources(eligible)
            for job in eligible:
                state = "queued" if self.models.status(job["snapshot"])["ready"] else "blocked"
                db.update_job(job["id"], state, {"error": None})
            skipped = [{"id": r["id"], "reason": r["state"]} for r in rows if r["state"] not in eligible_states]
            return {"retried_count": len(eligible), "skipped_count": len(skipped), "skipped": skipped,
                    "job_ids": [j["id"] for j in eligible]}
        if operation == "jobs.retry" and any(key in arguments for key in ("failed_only", "target_token")):
            raise StateError("invalid_arguments", "New retry options require selector")
        if operation == "device.calibrate":
            paths = arguments.get("paths")
            if not isinstance(paths, list) or len(paths) != 1:
                raise StateError("invalid_arguments", "Choose one local calibration sample")
            batch_id = new_id("batch")
            plan = self._preview({"paths": paths, "output_dir": str(self.root / "calibrations" / batch_id),
                                  "settings": arguments.get("settings", {})})
            valid = [e for e in plan["entries"] if e["status"] == "valid"]
            if len(valid) != 1:
                raise StateError("invalid_arguments", "Calibration requires one valid media file")
            definition = self.models.definition(plan["settings"]["model"])
            from asr_srt.registry import execution
            if "mps" not in execution(definition)["devices"]:
                raise StateError("unsupported_device", "This model supports CPU only; CPU/GPU calibration is unavailable")
            state = "queued" if self.models.status(definition["snapshot_id"])["ready"] else "blocked"
            created, ids = time.time(), []
            db.connection.execute("INSERT INTO batches VALUES(?,?,?)", (batch_id, created, encode({"kind": "calibration", **plan})))
            for index, device in enumerate(("cpu", "gpu")):
                identifier = new_id("job")
                entry = valid[0]
                output = Path(plan["output_dir"]) / device
                details = {**entry, "settings": {**plan["settings"], "device": device, "overwrite": False},
                           "kind": "calibration", "model_definition": definition, "output_dir": str(output),
                           "outputs": {fmt: str(output / Path(target).name) for fmt, target in entry["outputs"].items()}, "error": None}
                db.connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", (identifier, batch_id, created + index * .000001,
                                      state, definition["snapshot_id"], None, encode(details)))
                db.event("job." + state, identifier, {"batch_id": batch_id, "state": state, "kind": "calibration"})
                ids.append(identifier)
            return {"id": batch_id, "kind": "calibration", "job_ids": ids, "queue_paused": db.setting("queue_paused")}
        if operation == "settings.set":
            value = arguments.get("settings")
            if not isinstance(value, dict):
                raise StateError("invalid_settings", "Provide a settings object")
            value = settings({**db.defaults(), **value}, self.models.catalog)
            db.set_setting("defaults", value)
            return value
        if operation in ("queue.pause", "queue.resume"):
            paused = operation == "queue.pause"
            db.set_setting("queue_paused", paused)
            return {"paused": paused}
        if operation == "submit":
            plan = self._preview(arguments)
            valid = [e for e in plan["entries"] if e["status"] == "valid"]
            if not valid:
                raise StateError("no_valid_inputs", "No valid media to submit", preview=plan)
            model = self.models.definition(plan["settings"]["model"])
            ready = self.models.status(model["snapshot_id"])["ready"]
            batch_id, created = new_id("batch"), time.time()
            db.connection.execute("INSERT INTO batches VALUES(?,?,?)", (batch_id, created, encode(plan)))
            identifiers = []
            for index, entry in enumerate(valid):
                job_id = new_id("job")
                details = {**entry, "settings": plan["settings"], "model_definition": model,
                           "output_dir": plan["output_dir"], "error": None}
                state = "queued" if ready else "blocked"
                db.connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
                                      (job_id, batch_id, created + index * 0.000001, state, model["snapshot_id"], None, encode(details)))
                db.event("job." + state, job_id, {"state": state, "batch_id": batch_id})
                identifiers.append(job_id)
            return {"id": batch_id, "job_ids": identifiers, "accepted_count": len(identifiers),
                    "excluded": [e for e in plan["entries"] if e["status"] != "valid"]}
        identifier = self._id(arguments)
        jobs = ([db.job(row[0]) for row in db.connection.execute("SELECT id FROM jobs WHERE batch_id=? ORDER BY created,id", (identifier,))]
                if identifier.startswith("batch-") else [db.job(identifier)])
        if not jobs:
            raise StateError("not_found", "No such job or batch")
        if operation == "jobs.cancel":
            for job in jobs:
                if job["state"] in NONTERMINAL:
                    db.update_job(job["id"], "cancelling" if job["state"] in ("running", "cancelling") else "cancelled")
        elif operation == "jobs.retry":
            eligible = [job for job in jobs if job["state"] in ("failed", "cancelled", "interrupted")]
            if not eligible:
                raise StateError("invalid_state", "Only failed, cancelled or interrupted jobs can be retried")
            self._validate_retry_sources(eligible)
            for job in eligible:
                state = "queued" if self.models.status(job["snapshot"])["ready"] else "blocked"
                db.update_job(job["id"], state, {"error": None})
        states = {}
        for job in jobs:
            state = db.job(job["id"])["state"]
            states[state] = states.get(state, 0) + 1
        return {"id": identifier, "job_ids": [job["id"] for job in jobs], "counts": states}

    @staticmethod
    def _validate_retry_sources(jobs):
        for job in jobs:
            try:
                matches = source_matches(job["source"], job["fingerprint"])
            except StateError as error:
                raise StateError(error.code, str(error), job_id=job["id"], source=job["source"]) from error
            except OSError as error:
                raise StateError("source_unavailable", "Source cannot be read; restore it before retrying",
                                 job_id=job["id"], source=job["source"], reason=str(error)) from error
            if not matches:
                raise StateError("source_changed", "Source content changed; submit a new job", job_id=job["id"], source=job["source"])
