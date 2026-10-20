"""Coordinator-owned SQLite state and transactional command replay."""

from contextlib import contextmanager
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


class StateError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def new_id(kind):
    return kind + "-" + uuid.uuid4().hex


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = self.path.exists()
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
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

    def jobs(self, offset=0, limit=100, batch_id=None):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise StateError("invalid_arguments", "Invalid job page")
        condition, params = ("WHERE batch_id=?", [batch_id]) if batch_id else ("", [])
        rows = self.connection.execute(f"SELECT id FROM jobs {condition} ORDER BY created,id LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return [{key: value for key, value in self.job(row[0]).items()
                 if key not in ("model_definition", "performance_spans", "resources", "outputs_ledger")}
                for row in rows]

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
