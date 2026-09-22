"""Lost final API acknowledgement against the dedicated validation stack."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def fixture(id, generation):
    import httpx
    from asr_service import native
    from asr_service.client import Client
    from service_roundtrip import FixtureDrive, fixture_infer

    class LostAck(Client):
        def call(self, action, **body):
            result = super().call(action, **body)
            if action == "finish" and body.get("state") == "completed":
                raise httpx.ReadTimeout("Injected after API committed completion")
            return result

    native.Client = LostAck
    native.Drive = FixtureDrive
    native.infer = fixture_infer
    return native.execute(id, generation)


def main():
    import httpx
    from redis import Redis
    from rq.job import Job
    from rq.serializers import JSONSerializer
    from asr_service.client import Client
    from asr_service.native import execute

    root = Path("/private/tmp/asr-service-validation")
    v = dict(
        l.split("=", 1)
        for l in (root / "compose.env").read_text().splitlines()
        if "=" in l
    )
    workspace = root / ("ack-" + uuid.uuid4().hex[:8])
    workspace.mkdir()
    (workspace / "remote").mkdir()
    (workspace / "remote/lost-response").touch()
    os.environ.update(
        ASR_API_URL="http://127.0.0.1:18090",
        ASR_REDIS_URL="redis://127.0.0.1:16379/0",
        ASR_WORKER_TOKEN=v["ASR_WORKER_TOKEN"],
        ASR_WORKSPACE=str(workspace),
    )
    client = Client()
    admin = httpx.Client(
        base_url=os.environ["ASR_API_URL"], auth=("admin", v["ASR_ADMIN_PASSWORD"])
    )
    admin.get("/")
    headers = {"x-csrf-token": admin.cookies["asr_csrf"]}
    b = admin.post(
        "/api/batches",
        headers=headers,
        json={
            "source": "ack-source",
            "destination": "ack-destination",
            "settings": {"hotwords": [workspace.name]},
        },
    ).json()["id"]
    while True:
        scan = client.call("scan-claim")
        if scan["id"] == b:
            break
        client.call("scan-update", id=scan["id"], token=scan["token"], media=[])
    client.call(
        "scan-update",
        id=b,
        token=scan["token"],
        media=[
            {
                "id": "ack-file",
                "name": "ack.mp3",
                "path": "ack.mp3",
                "version": "ack-v1",
                "size": 10,
            }
        ],
    )
    id = admin.get("/api/batches/" + b).json()["jobs"][0]["id"]
    redis = Redis.from_url(os.environ["ASR_REDIS_URL"])
    deadline = time.monotonic() + 30
    deleted = False
    while time.monotonic() < deadline:
        try:
            job = Job.fetch(id + "-0", connection=redis, serializer=JSONSerializer)
        except Exception:
            time.sleep(0.2)
            continue
        if not deleted:
            # Delete only this synthetic job, never flush a shared Redis database.
            job.delete()
            deleted = True
            continue
        job.data = JSONSerializer.dumps(
            ("service_ack_loss.fixture", None, job.args, job.kwargs)
        )
        job.save()
        break
    else:
        raise AssertionError("No dispatch")
    with (root / "ack-child.log").open("w") as log:
        subprocess.run(
            [sys.executable, "evaluation/service_faults.py", "runner"],
            env=os.environ,
            stdout=log,
            stderr=log,
            timeout=30,
            check=True,
        )
    assert client.call("get", id=id)["status"] == "completed"
    assert execute(id, 0) == {"skipped": True}
    calls = (workspace / "inference.jsonl").read_text().splitlines()
    assert len(calls) == 1
    assert len(list((workspace / "remote").iterdir())) == 6
    report = {
        "lost_queue_entry_recreated": deleted,
        "api_completion_ack_lost": True,
        "durable_status": "completed",
        "duplicate_execution_skipped": True,
        "inference_calls": len(calls),
        "remote_objects": 5,
        "real_drive": False,
        "real_asr": False,
    }
    (root / "ack-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    client.close()
    admin.close()


if __name__ == "__main__":
    main()
