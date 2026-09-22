"""Integration test against the dedicated Docker validation stack only.

Real API, SQLite, Redis, RQ SpawnWorker; fake media inference and Drive writes.
Never load service-account credentials. Not a production worker entry point.
"""

import json
import os
from pathlib import Path
import time


def fixture_infer(payload, audio, directory, reporter):
    root = Path(os.environ["ASR_WORKSPACE"])
    with (root / "inference.jsonl").open("a") as f:
        f.write(
            json.dumps(
                {"id": payload["source"], "start": time.time(), "pid": os.getpid()}
            )
            + "\n"
        )
    (directory / "transcript.txt").write_text("機器逐字稿（未校訂）\n測試文字。\n")
    (directory / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n測試文字。\n"
    )
    time.sleep(1)
    return {"model_id": "integration-fixture", "device": "fixture"}


class FixtureDrive:
    def __init__(self):

        self.root = Path(os.environ["ASR_WORKSPACE"]) / "remote"
        self.root.mkdir(exist_ok=True)
        self.session = self

    def close(self):
        pass

    def generate_id(self):
        import uuid

        return uuid.uuid4().hex

    def download(self, item, path):
        from asr_service.drive import file_md5

        path.write_bytes(b"mock media")
        return file_md5(path)

    def ensure(self, id, name, parent, identity, path=None):
        from asr_service.drive import file_md5, DriveError

        target = self.root / id
        content = {"name": name, "parent": parent, "identity": identity}
        if target.exists():
            assert json.loads(target.read_text()) == content
        target.write_text(json.dumps(content))
        marker = self.root / "lost-response"
        if name == "subtitles.srt" and not marker.exists():
            marker.write_text("Injected after successful remote create")
            raise DriveError("Simulated lost upload response")
        return "" if path is None else file_md5(path)


def run_fixture(id, generation):
    from asr_service import native

    native.Drive = FixtureDrive
    native.infer = fixture_infer
    return native.execute(id, generation)


def main():
    import httpx
    from redis import Redis
    from rq import Queue, SpawnWorker
    from rq.job import Job
    from rq.serializers import JSONSerializer
    from asr_service.client import Client
    from asr_service.native import scan_once

    secrets_path = Path("/private/tmp/asr-service-validation/compose.env")
    values = dict(
        line.split("=", 1)
        for line in secrets_path.read_text().splitlines()
        if "=" in line
    )
    os.environ.update(
        ASR_API_URL="http://127.0.0.1:18090",
        ASR_REDIS_URL="redis://127.0.0.1:16379/0",
        ASR_WORKER_TOKEN=values["ASR_WORKER_TOKEN"],
        ASR_WORKSPACE="/private/tmp/asr-service-validation/workspace",
        ASR_MIN_FREE_BYTES="1073741824",
    )
    root = Path(os.environ["ASR_WORKSPACE"])
    root.mkdir(exist_ok=True)
    admin = httpx.Client(
        base_url=os.environ["ASR_API_URL"], auth=("admin", values["ASR_ADMIN_PASSWORD"])
    )
    assert admin.get("/").status_code == 200
    headers = {"x-csrf-token": admin.cookies["asr_csrf"]}
    overview = admin.get("/api/overview").json()
    pending = [b for b in overview["batches"] if b["status"] == "pending"]
    batch_id = (
        pending[0]["id"]
        if pending
        else admin.post(
            "/api/batches",
            headers=headers,
            json={"source": "test-source", "destination": "test-destination"},
        ).json()["id"]
    )
    client = Client()

    class Scan:
        def scan(self, *args):
            return (
                [
                    {
                        "id": "test-file-" + str(i),
                        "name": f"clip{i}.mp3",
                        "path": f"clip{i}.mp3",
                        "version": "fixture-v1",
                        "size": 10,
                    }
                    for i in (1, 2)
                ],
                0,
            )

    scan_once(client, Scan())
    client.call("recover")
    batch = admin.get("/api/batches/" + batch_id).json()
    ids = [j["id"] for j in batch["jobs"]]
    redis = Redis.from_url(os.environ["ASR_REDIS_URL"])
    queue = Queue("asr", connection=redis, serializer=JSONSerializer)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        # Redirect this test's known jobs only. The actual application always enqueues native.execute.
        for id in ids:
            record = client.call("get", id=id)
            rqid = id + "-" + str(record["generation"])
            try:
                job = Job.fetch(rqid, connection=redis, serializer=JSONSerializer)
            except Exception:
                continue
            if job.get_status().value in ("queued", "scheduled"):
                # Materialize the original arguments before replacing RQ's data tuple.
                job.data = JSONSerializer.dumps(
                    ("service_roundtrip.run_fixture", None, job.args, job.kwargs)
                )
                job.save()
        if queue.count:
            SpawnWorker(
                [queue],
                connection=redis,
                serializer=JSONSerializer,
                job_monitoring_interval=2,
            ).work(burst=True, with_scheduler=True)
        # A fresh burst starts the RQ scheduler periodically for delayed retries.
        from rq.scheduler import RQScheduler

        scheduler = RQScheduler(["asr"], connection=redis)
        scheduler.acquire_locks()
        scheduler.enqueue_scheduled_jobs()
        scheduler.release_locks()
        states = [client.call("get", id=id)["status"] for id in ids]
        if all(s == "completed" for s in states):
            break
        print("Integration states:", states, flush=True)
        time.sleep(5)
    assert states == ["completed", "completed"], states
    calls = [
        json.loads(line) for line in (root / "inference.jsonl").read_text().splitlines()
    ]
    assert len(calls) == 2, "Upload retry repeated inference"
    remote = [p for p in (root / "remote").iterdir() if p.name != "lost-response"]
    assert len(remote) == 10, "Duplicate publication"
    report = {
        "jobs": len(ids),
        "completed": states,
        "inference_calls": len(calls),
        "remote_objects": len(remote),
        "upload_response_loss_recovered": True,
        "real_drive": False,
        "real_asr": False,
    }
    (root / "roundtrip-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    client.close()
    admin.close()


if __name__ == "__main__":
    main()
