"""Coordinator-owned SQLite state and transactional command replay."""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


SCHEMA_VERSION = 1
DEFAULTS = {"model": "fun-asr-nano", "device": "auto", "formats": ["txt", "srt"],
            "script": "traditional", "language": "中文", "hotwords": [],
            "max_chars": 20, "max_duration_ms": 5000, "overwrite": False}
NONTERMINAL = ("blocked", "queued", "running", "cancelling", "interrupted")
STATES = (*NONTERMINAL, "completed", "failed", "cancelled")


class StateError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def new_id(kind):
    return kind + "-" + uuid.uuid4().hex


def batch_name(created, details):
    """Use the original submission plan so removals do not rename a batch."""
    if isinstance(details.get("name"), str) and details["name"].strip():
        return details["name"]
    source = next((Path(entry["source"]).name for entry in details.get("entries", [])
                   if entry.get("status") == "valid" and entry.get("source")), "轉錄批次")
    return datetime.fromtimestamp(created).astimezone().strftime("%Y-%m-%d %H:%M") + " · " + source


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = self.path.exists()
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.create_function("batch_name", 2, lambda created, details: batch_name(created, json.loads(details)))
        self.connection.create_function("filename", 1, lambda value: Path(value or "").name)
        self.connection.create_function("fold", 1, lambda value: (value or "").casefold())
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.connection.close()
            raise StateError("newer_schema", "Use the App version that created this database; this version will not write it")
        self.upgrade_backup = None
        if version < SCHEMA_VERSION:
            if existed:
                self.upgrade_backup = self.path.with_name(self.path.name + f".before-v{SCHEMA_VERSION}-{time.time_ns()}.backup")
                backup = sqlite3.connect(self.upgrade_backup)
                try:
                    self.connection.backup(backup)
                finally:
                    backup.close()
            self._migrate()
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.path.chmod(0o600)

    def _migrate(self):
        self.connection.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE batches(id TEXT PRIMARY KEY, created REAL NOT NULL, details TEXT NOT NULL);
            CREATE TABLE jobs(id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
                created REAL NOT NULL, state TEXT NOT NULL, snapshot TEXT NOT NULL,
                attempt_id TEXT, details TEXT NOT NULL);
            CREATE INDEX jobs_queue ON jobs(state,created,id);
            CREATE INDEX jobs_snapshot ON jobs(snapshot,state);
            CREATE TABLE attempts(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                created REAL NOT NULL, state TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL,
                kind TEXT NOT NULL, entity_id TEXT, details TEXT NOT NULL);
            CREATE TABLE requests(id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE device_profiles(id TEXT PRIMARY KEY, details TEXT NOT NULL);
            INSERT INTO settings VALUES('defaults','{}');
            INSERT INTO settings VALUES('queue_paused','true');
            PRAGMA user_version=1;
            COMMIT;
        """)

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def close(self):
        self.connection.close()

    def command(self, request_id, operation, arguments, action):
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise StateError("invalid_request_id", "Mutations require a request id of 1–128 characters")
        digest = hashlib.sha256(encode({"operation": operation, "arguments": arguments}).encode()).hexdigest()
        with self.transaction():
            prior = self.connection.execute("SELECT digest,result FROM requests WHERE id=?", (request_id,)).fetchone()
            if prior:
                if prior["digest"] != digest:
                    raise StateError("request_id_conflict", "This request id was already used for different content")
                return json.loads(prior["result"])
            result = action()
            self.connection.execute("INSERT INTO requests VALUES(?,?,?)", (request_id, digest, encode(result)))
            return result

    def event(self, kind, entity_id, details):
        cursor = self.connection.execute("INSERT INTO events(created,kind,entity_id,details) VALUES(?,?,?,?)",
                                         (time.time(), kind, entity_id, encode(details)))
        return cursor.lastrowid

    def events(self, cursor=0, limit=200):
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise StateError("invalid_arguments", "Invalid event cursor or limit")
        first, latest = self.connection.execute("SELECT MIN(sequence),MAX(sequence) FROM events").fetchone()
        latest = latest or 0
        reset = cursor > latest or (first is not None and cursor < first - 1)
        if reset:
            return {"reset": True, "cursor": latest, "snapshot": self.snapshot(), "events": []}
        rows = self.connection.execute("SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?", (cursor, limit)).fetchall()
        events = [{"sequence": r["sequence"], "created": r["created"], "kind": r["kind"],
                   "entity_id": r["entity_id"], "details": json.loads(r["details"])} for r in rows]
        return {"reset": False, "cursor": rows[-1]["sequence"] if rows else cursor,
                "latest_cursor": latest, "events": events}

    def prune_events(self, retain=10000):
        self.connection.execute("DELETE FROM events WHERE sequence < (SELECT COALESCE(MAX(sequence),0)-?+1 FROM events)", (retain,))

    def setting(self, key):
        row = self.connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def defaults(self):
        return {**DEFAULTS, **self.setting("defaults")}

    def set_setting(self, key, value):
        self.connection.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encode(value)))
        self.event("settings.changed", None, {key: value})

    def references(self, snapshot):
        placeholders = ",".join("?" for _ in NONTERMINAL)
        rows = self.connection.execute(f"SELECT id FROM jobs WHERE snapshot=? AND state IN ({placeholders})", (snapshot, *NONTERMINAL)).fetchall()
        return [row[0] for row in rows]

    def job(self, identifier):
        row = self.connection.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise StateError("not_found", "No such job")
        return {**json.loads(row["details"]), **{key: row[key] for key in ("id", "batch_id", "created", "state", "snapshot", "attempt_id")}}

    def batches(self, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise StateError("invalid_arguments", "Invalid batch page")
        rows = self.connection.execute("SELECT * FROM batches ORDER BY created DESC,id LIMIT ? OFFSET ?",
                                       (limit, offset)).fetchall()
        summaries = []
        for row in rows:
            counts = {r["state"]: r["count"] for r in self.connection.execute(
                "SELECT state,COUNT(*) AS count FROM jobs WHERE batch_id=? GROUP BY state", (row["id"],))}
            summaries.append({"id": row["id"], "created": row["created"],
                              "name": batch_name(row["created"], json.loads(row["details"])),
                              "counts": counts, "total": sum(counts.values())})
        return {"batches": summaries, "total": self.connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0]}

    def rename_batch(self, identifier, name):
        if not isinstance(identifier, str) or not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise StateError("invalid_arguments", "Batch name must contain 1–100 Unicode code points after trimming")
        row = self.connection.execute("SELECT details FROM batches WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise StateError("not_found", "No such batch")
        details = json.loads(row["details"])
        details["name"] = name.strip()
        self.connection.execute("UPDATE batches SET details=? WHERE id=?", (encode(details), identifier))
        self.event("batch.renamed", identifier, {"name": details["name"]})
        return {"id": identifier, "name": details["name"]}

    def query_condition(self, batch_id=None, query="", states=None):
        if batch_id is not None and not isinstance(batch_id, str):
            raise StateError("invalid_arguments", "batch_id must be a string")
        if not isinstance(query, str) or (states is not None and
                (not isinstance(states, list) or any(not isinstance(s, str) or s not in STATES for s in states))):
            raise StateError("invalid_arguments", "Provide a text query and an array of known states")
        conditions, params = [], []
        if batch_id:
            conditions.append("j.batch_id=?")
            params.append(batch_id)
        if query.strip():
            conditions.append("(instr(fold(filename(json_extract(j.details,'$.source'))),?)>0 OR "
                              "instr(fold(batch_name(b.created,b.details)),?)>0)")
            params.extend([query.strip().casefold()] * 2)
        if states:
            states = sorted(set(states))
            conditions.append("j.state IN (" + ",".join("?" for _ in states) + ")")
            params.extend(states)
        return " JOIN batches b ON b.id=j.batch_id" + (" WHERE " + " AND ".join(conditions) if conditions else ""), params

    def job_counts(self, batch_id=None, query="", states=None):
        condition, params = self.query_condition(batch_id, query, states)
        return {r["state"]: r["count"] for r in self.connection.execute(
            "SELECT j.state,COUNT(*) AS count FROM jobs j" + condition + " GROUP BY j.state", params)}

    def jobs(self, offset=0, limit=100, batch_id=None, query="", states=None):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise StateError("invalid_arguments", "Invalid job page")
        condition, params = self.query_condition(batch_id, query, states)
        rows = self.connection.execute(f"SELECT j.id FROM jobs j{condition} ORDER BY j.created,j.id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return [{key: value for key, value in self.job(row[0]).items()
                 if key not in ("model_definition", "performance_spans", "resources", "outputs_ledger")}
                for row in rows]

    def selection(self, selector, target_token=None):
        if not isinstance(selector, dict) or set(selector) - {"ids", "batch_id", "query", "states"}:
            raise StateError("invalid_arguments", "Provide an ids or query selector")
        if "ids" in selector:
            ids = selector["ids"]
            if set(selector) != {"ids"} or not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids):
                raise StateError("invalid_arguments", "ids cannot be mixed with query parameters")
            ids = sorted(set(ids))
            rows = []
            for identifier in ids:
                row = self.connection.execute("SELECT id,state,attempt_id,batch_id FROM jobs WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    raise StateError("not_found", "No such selected job", job_id=identifier)
                rows.append(dict(row))
            normalized = {"ids": ids}
        else:
            condition, params = self.query_condition(selector.get("batch_id"), selector.get("query", ""), selector.get("states"))
            if selector.get("batch_id") and self.connection.execute("SELECT id FROM batches WHERE id=?", (selector["batch_id"],)).fetchone() is None:
                raise StateError("not_found", "No such batch")
            rows = [dict(r) for r in self.connection.execute(
                "SELECT j.id,j.state,j.attempt_id,j.batch_id FROM jobs j" + condition + " ORDER BY j.id", params)]
            normalized = {"batch_id": selector.get("batch_id") or None,
                          "query": selector.get("query", "").strip().casefold(), "states": sorted(set(selector.get("states") or []))}
        token = hashlib.sha256(encode({"selector": normalized, "targets": rows}).encode()).hexdigest()
        if target_token is not None and target_token != token:
            raise StateError("selection_changed", "Targets changed; refresh selection and confirm again")
        counts, blocked = {}, []
        for row in rows:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
            active = self.connection.execute("SELECT id FROM attempts WHERE job_id=? AND state='running'", (row["id"],)).fetchone()
            if row["state"] in ("running", "cancelling") or active:
                blocked.append({"id": row["id"], "reason": "worker_not_reaped" if active else row["state"]})
        return {"selector": normalized, "total": len(rows), "counts": counts,
                "retryable_count": sum(counts.get(s, 0) for s in ("failed", "cancelled", "interrupted")),
                "cannot_remove": blocked, "target_token": token}, rows

    def snapshot(self):
        return {"queue_paused": self.setting("queue_paused"), "jobs": self.jobs(), "defaults": self.defaults()}

    def update_job(self, identifier, state, details=None, attempt_id=None):
        job = self.job(identifier)
        payload = {key: value for key, value in job.items() if key not in ("id", "batch_id", "created", "state", "snapshot", "attempt_id")}
        payload.update(details or {})
        self.connection.execute("UPDATE jobs SET state=?,details=?,attempt_id=? WHERE id=?",
                                (state, encode(payload), attempt_id if attempt_id is not None else job["attempt_id"], identifier))
        self.event("job." + state, identifier, {"state": state, "batch_id": job["batch_id"], **(details or {})})

    def accept_attempt_event(self, identifier, attempt_id, state, details):
        job = self.job(identifier)
        if job["attempt_id"] != attempt_id or job["state"] not in ("running", "cancelling"):
            return False
        self.update_job(identifier, state, details)
        return True
