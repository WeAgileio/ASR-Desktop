"""SQLite is the source of truth; only the API process opens this database."""

from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import sqlite3
import time
from .models import BatchInput, Media, fingerprint, natural_key

ACTIVE = ("downloading", "transcribing", "uploading")
TERMINAL = ("completed", "failed", "blocked")
RETRY_DELAYS = (60, 300, 900)


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            if c.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise RuntimeError("Database schema is newer than this application")
            c.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS batches (
              id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              token TEXT, lease REAL NOT NULL DEFAULT 0, next_scan REAL NOT NULL DEFAULT 0,
              created REAL NOT NULL, error TEXT, skipped INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
              generation INTEGER NOT NULL DEFAULT 0, token TEXT, sequence INTEGER NOT NULL DEFAULT -1,
              heartbeat REAL, progress TEXT NOT NULL DEFAULT '{}', error TEXT,
              failures INTEGER NOT NULL DEFAULT 0, next_retry REAL NOT NULL DEFAULT 0,
              created REAL NOT NULL, completed REAL);
            CREATE TABLE IF NOT EXISTS batch_jobs (
              batch_id TEXT NOT NULL REFERENCES batches(id), job_id TEXT NOT NULL REFERENCES jobs(id),
              position INTEGER NOT NULL, PRIMARY KEY(batch_id, job_id));
            CREATE TABLE IF NOT EXISTS attempts (
              token TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), generation INTEGER NOT NULL,
              started REAL NOT NULL, ended REAL, outcome TEXT);
            CREATE TABLE IF NOT EXISTS artifacts (
              owner TEXT NOT NULL, kind TEXT NOT NULL, remote_id TEXT NOT NULL UNIQUE,
              verified INTEGER NOT NULL DEFAULT 0, checksum TEXT NOT NULL DEFAULT '',
              PRIMARY KEY(owner,kind));
            CREATE TABLE IF NOT EXISTS outbox (
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), generation INTEGER NOT NULL,
              sent INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS workers (
              name TEXT PRIMARY KEY, heartbeat REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL);
            INSERT OR IGNORE INTO control VALUES(1,0);
            PRAGMA user_version=1;
            COMMIT;
            """)

    @contextmanager
    def connect(self, write=False):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        try:
            if write:
                c.execute("BEGIN IMMEDIATE")
            yield c
            if write:
                c.commit()
        except BaseException:
            if write:
                c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def row(c, table, id):
        assert table in ("jobs", "batches")
        row = c.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone()
        if row is None:
            raise Missing(id)
        return row

    @staticmethod
    def public(row):
        d = dict(row)
        d.pop("token", None)
        for field in ("payload", "progress"):
            if field in d:
                d[field] = json.loads(d[field])
        if d.get("status") in ACTIVE:
            d["offline"] = time.time() - (d.get("heartbeat") or 0) > 90
        return d

    def batch(self, payload):
        payload = BatchInput.model_validate(payload).model_dump()
        if payload["source"] == payload["destination"]:
            raise ValueError("來源與目的地不可相同")
        id = secrets.token_hex(16)
        with self.connect(True) as c:
            c.execute(
                "INSERT INTO batches(id,payload,created) VALUES(?,?,?)",
                (id, encode(payload), time.time()),
            )
        return id

    def get(self, table, id):
        with self.connect() as c:
            result = self.public(self.row(c, table, id))
            if table == "batches":
                result["jobs"] = [
                    self.public(r)
                    for r in c.execute(
                        "SELECT j.* FROM jobs j JOIN batch_jobs b ON j.id=b.job_id WHERE b.batch_id=? ORDER BY b.position",
                        (id,),
                    )
                ]
            else:
                result["artifacts"] = [
                    dict(r)
                    for r in c.execute("SELECT * FROM artifacts WHERE owner=?", (id,))
                ]
            return result

    def overview(self):
        with self.connect() as c:
            return {
                "batches": [
                    self.public(r)
                    for r in c.execute(
                        "SELECT * FROM batches ORDER BY created DESC LIMIT 200"
                    )
                ],
                "jobs": [
                    self.public(r)
                    for r in c.execute(
                        "SELECT * FROM jobs ORDER BY created DESC LIMIT 500"
                    )
                ],
                "workers": [dict(r) for r in c.execute("SELECT * FROM workers")],
                "paused": bool(c.execute("SELECT paused FROM control").fetchone()[0]),
            }

    def pause(self, value):
        with self.connect(True) as c:
            c.execute("UPDATE control SET paused=?", (int(value),))

    def rescan(self, id):
        with self.connect(True) as c:
            row = self.row(c, "batches", id)
            if row["status"] == "scanning" and row["lease"] > time.time():
                raise Conflict("掃描仍在執行")
            c.execute(
                "UPDATE batches SET status='pending',token=NULL,error=NULL WHERE id=?",
                (id,),
            )

    def scan_claim(self):
        now = time.time()
        with self.connect(True) as c:
            # Periodic scans create a fresh attempt on the same logical batch.
            for row in c.execute(
                "SELECT * FROM batches WHERE status='completed' AND next_scan>0 AND next_scan<=?",
                (now,),
            ).fetchall():
                c.execute(
                    "UPDATE batches SET status='pending' WHERE id=?", (row["id"],)
                )
            row = c.execute(
                "SELECT * FROM batches WHERE status='pending' OR (status='scanning' AND lease<?) ORDER BY created LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            token = secrets.token_hex(24)
            c.execute(
                "UPDATE batches SET status='scanning',token=?,lease=? WHERE id=?",
                (token, now + 90, row["id"]),
            )
            result = self.public(row)
            result["token"] = token
            return result

    def scan_update(
        self, id, token, *, media=None, error=None, blocked=False, skipped=0
    ):
        with self.connect(True) as c:
            row = self.row(c, "batches", id)
            if (
                row["status"] != "scanning"
                or row["token"] != token
                or row["lease"] < time.time()
            ):
                raise Conflict("掃描租約已失效")
            c.execute("UPDATE batches SET lease=? WHERE id=?", (time.time() + 90, id))
            if error is not None:
                c.execute(
                    "UPDATE batches SET status=?,error=?,token=NULL WHERE id=?",
                    ("blocked" if blocked else "failed", error[:1000], id),
                )
            elif media is not None:
                batch = json.loads(row["payload"])
                items = [Media.model_validate(m).model_dump() for m in media]
                for position, item in enumerate(
                    sorted(items, key=lambda m: natural_key(m["path"]))
                ):
                    identity = {
                        "source": item["id"],
                        "version": item["version"],
                        "settings": batch["settings"],
                        "destination": batch["destination"],
                    }
                    job_id = fingerprint(identity)
                    payload = {**identity, "media": item}
                    now = time.time()
                    inserted = c.execute(
                        "INSERT OR IGNORE INTO jobs(id,payload,created) VALUES(?,?,?)",
                        (job_id, encode(payload), now),
                    ).rowcount
                    if inserted:
                        self._outbox(c, job_id, 0, now)
                    c.execute(
                        "INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?)",
                        (id, job_id, position),
                    )
                interval = batch["interval_seconds"]
                c.execute(
                    "UPDATE batches SET status='completed',token=NULL,error=NULL,skipped=?,next_scan=? WHERE id=?",
                    (skipped, time.time() + interval if interval else 0, id),
                )

    @staticmethod
    def _outbox(c, id, generation, now):
        c.execute(
            "INSERT OR IGNORE INTO outbox VALUES(?,?,?,0,?)",
            (f"{id}-{generation}", id, generation, now),
        )

    def dispatch_rows(self):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute("""SELECT o.*,j.status,j.next_retry,j.failures FROM outbox o
                JOIN jobs j ON j.id=o.job_id AND j.generation=o.generation
                WHERE j.status IN ('queued','retry_wait','interrupted') ORDER BY o.created,o.rowid""")
            ]

    def sent(self, id):
        with self.connect(True) as c:
            c.execute("UPDATE outbox SET sent=1 WHERE id=?", (id,))

    def redis_requeue(self, id, generation):
        with self.connect(True) as c:
            row = self.row(c, "jobs", id)
            if row["generation"] != generation or row["status"] not in (
                "queued",
                "retry_wait",
                "interrupted",
            ):
                return
            new = generation + 1
            c.execute("UPDATE jobs SET generation=? WHERE id=?", (new, id))
            self._outbox(c, id, new, time.time())

    def claim(self, id, generation, token):
        with self.connect(True) as c:
            row = self.row(c, "jobs", id)
            if row["token"] == token and row["status"] in ACTIVE:
                return self.public(row)  # Safe replay of an acknowledged-or-lost claim.
            if c.execute("SELECT paused FROM control").fetchone()[0]:
                raise Conflict("派工已暫停")
            if (
                row["generation"] != generation
                or row["status"] not in ("queued", "retry_wait", "interrupted")
                or row["next_retry"] > time.time()
            ):
                raise Conflict("任務不允許開始")
            if c.execute(
                "SELECT 1 FROM jobs WHERE status IN ('downloading','transcribing','uploading')"
            ).fetchone():
                raise Conflict("已有執行中的任務")
            now = time.time()
            c.execute(
                "UPDATE jobs SET token=?,sequence=-1,status='downloading',heartbeat=?,error=NULL WHERE id=?",
                (token, now, id),
            )
            c.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,NULL,NULL)",
                (token, id, generation, now),
            )
            return self.public(self.row(c, "jobs", id))

    def authority(self, c, id, token):
        row = self.row(c, "jobs", id)
        if row["token"] != token or row["status"] not in ACTIVE:
            raise Conflict("執行權已失效")
        return row

    def event(self, id, token, sequence, phase=None, progress=None):
        with self.connect(True) as c:
            row = self.authority(c, id, token)
            if phase is not None:
                if phase not in ACTIVE or ACTIVE.index(phase) < ACTIVE.index(
                    row["status"]
                ):
                    raise Conflict("非法階段轉換")
            if sequence <= row["sequence"]:
                return
            c.execute(
                "UPDATE jobs SET sequence=?,heartbeat=?,status=?,progress=? WHERE id=?",
                (
                    sequence,
                    time.time(),
                    phase or row["status"],
                    encode(
                        progress
                        if progress is not None
                        else json.loads(row["progress"])
                    ),
                    id,
                ),
            )

    def finish(self, id, token, state, error=""):
        if state not in ("completed", "retry_wait", "blocked", "failed"):
            raise ValueError("非法終態")
        with self.connect(True) as c:
            row = self.row(c, "jobs", id)
            if row["token"] == token and row["status"] == state:
                return  # Lost final acknowledgement.
            self.authority(c, id, token)
            if state == "completed":
                if row["status"] != "uploading":
                    raise Conflict("尚未進入上傳階段")
                verified = {
                    r["kind"]
                    for r in c.execute(
                        "SELECT kind FROM artifacts WHERE owner=? AND verified=1", (id,)
                    )
                }
                if (
                    not {
                        "version_folder",
                        "transcript.txt",
                        "subtitles.srt",
                        "completion.json",
                    }
                    <= verified
                ):
                    raise Conflict("交付尚未驗證")
            failures = row["failures"] + (state == "retry_wait")
            if state == "retry_wait" and failures > len(RETRY_DELAYS):
                state = "failed"
            retry_at = (
                time.time() + RETRY_DELAYS[failures - 1] if state == "retry_wait" else 0
            )
            c.execute(
                "UPDATE jobs SET status=?,error=?,failures=?,next_retry=?,completed=? WHERE id=?",
                (
                    state,
                    error[:1000],
                    failures,
                    retry_at,
                    time.time() if state == "completed" else None,
                    id,
                ),
            )
            c.execute(
                "UPDATE attempts SET ended=?,outcome=? WHERE token=?",
                (time.time(), state, token),
            )

    def retry(self, id):
        with self.connect(True) as c:
            row = self.row(c, "jobs", id)
            if row["status"] not in ("failed", "blocked", "interrupted"):
                raise Conflict("只有失敗或中斷的任務可手動重試")
            generation = row["generation"] + 1
            c.execute(
                "UPDATE jobs SET status='queued',generation=?,token=NULL,failures=0,next_retry=0,error=NULL WHERE id=?",
                (generation, id),
            )
            self._outbox(c, id, generation, time.time())

    def recover(self):
        # Called only by the singleton host supervisor while it holds the execution lock.
        # A heartbeat timeout alone is deliberately insufficient authority to reassign.
        with self.connect(True) as c:
            for row in c.execute(
                "SELECT * FROM jobs WHERE status IN ('downloading','transcribing','uploading')"
            ).fetchall():
                c.execute(
                    "UPDATE attempts SET ended=?,outcome='interrupted' WHERE token=?",
                    (time.time(), row["token"]),
                )
                failures = row["failures"] + 1
                if failures > 3:
                    c.execute(
                        "UPDATE jobs SET status='failed',token=NULL,error='Repeated worker interruption' WHERE id=?",
                        (row["id"],),
                    )
                    continue
                c.execute(
                    "UPDATE jobs SET failures=? WHERE id=?", (failures, row["id"])
                )
                gen = row["generation"] + 1
                c.execute(
                    "UPDATE jobs SET status='interrupted',token=NULL,generation=?,next_retry=0 WHERE id=?",
                    (gen, row["id"]),
                )
                self._outbox(c, row["id"], gen, time.time())

    def reserve(self, id, token, kind, remote_id):
        allowed = {
            "source_folder",
            "version_folder",
            "transcript.txt",
            "subtitles.srt",
            "completion.json",
        }
        if kind not in allowed:
            raise ValueError("未知輸出類型")
        with self.connect(True) as c:
            job = self.authority(c, id, token)
            payload = json.loads(job["payload"])
            owner = (
                fingerprint([payload["source"], payload["destination"]])
                if kind == "source_folder"
                else id
            )
            c.execute(
                "INSERT OR IGNORE INTO artifacts(owner,kind,remote_id) VALUES(?,?,?)",
                (owner, kind, remote_id),
            )
            return dict(
                c.execute(
                    "SELECT * FROM artifacts WHERE owner=? AND kind=?", (owner, kind)
                ).fetchone()
            )

    def verify(self, id, token, kind, remote_id, checksum):
        with self.connect(True) as c:
            row = self.authority(c, id, token)
            payload = json.loads(row["payload"])
            owner = (
                fingerprint([payload["source"], payload["destination"]])
                if kind == "source_folder"
                else id
            )
            changed = c.execute(
                "UPDATE artifacts SET verified=1,checksum=? WHERE owner=? AND kind=? AND remote_id=?",
                (checksum, owner, kind, remote_id),
            ).rowcount
            if not changed:
                raise Conflict("輸出 ID 未登記")

    def heartbeat(self, name):
        with self.connect(True) as c:
            c.execute(
                "INSERT INTO workers VALUES(?,?) ON CONFLICT(name) DO UPDATE SET heartbeat=excluded.heartbeat",
                (name, time.time()),
            )

    def backup(self, target):
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("備份不可覆寫來源")
        with self.connect() as source, sqlite3.connect(target) as dest:
            source.backup(dest)
