"""Fault drill for the dedicated validation stack. No real Drive credentials used."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def crash_fixture(id, generation):
    from asr_service import native
    from service_roundtrip import FixtureDrive, fixture_infer

    native.Drive = FixtureDrive

    def waiting(*args):
        (Path(os.environ["ASR_WORKSPACE"]) / "kill-target.json").write_text(
            json.dumps({"pid": os.getpid(), "id": id})
        )
        time.sleep(120)
        return fixture_infer(*args)

    native.infer = waiting
    return native.execute(id, generation)


def runner():
    from redis import Redis
    from rq import Queue, SpawnWorker
    from rq.serializers import JSONSerializer

    r = Redis.from_url(os.environ["ASR_REDIS_URL"])
    SpawnWorker(
        [Queue("asr", connection=r, serializer=JSONSerializer)],
        connection=r,
        serializer=JSONSerializer,
        job_monitoring_interval=1,
    ).work(burst=True, max_jobs=1)


def main():
    import httpx
    from redis import Redis
    from rq.job import Job
    from rq.serializers import JSONSerializer
    from asr_service.client import Client
    from asr_service.native import host_lock

    root = Path("/private/tmp/asr-service-validation")
    v = dict(
        l.split("=", 1)
        for l in (root / "compose.env").read_text().splitlines()
        if "=" in l
    )
    os.environ.update(
        ASR_API_URL="http://127.0.0.1:18090",
        ASR_REDIS_URL="redis://127.0.0.1:16379/0",
        ASR_WORKER_TOKEN=v["ASR_WORKER_TOKEN"],
        ASR_WORKSPACE=str(root / "fault-workspace"),
    )
    Path(os.environ["ASR_WORKSPACE"]).mkdir(exist_ok=True)
    c = Client()
    a = httpx.Client(
        base_url=os.environ["ASR_API_URL"], auth=("admin", v["ASR_ADMIN_PASSWORD"])
    )
    a.get("/")
    headers = {"x-csrf-token": a.cookies["asr_csrf"]}
    a.post("/api/pause", headers=headers, json={"paused": False}).raise_for_status()
    b = a.post(
        "/api/batches",
        headers=headers,
        json={"source": "fault-source", "destination": "fault-destination"},
    ).json()["id"]
    # Settle only synthetic browser submissions before claiming this drill's batch.
    while True:
        scan = c.call("scan-claim")
        if scan["id"] == b:
            break
        c.call("scan-update", id=scan["id"], token=scan["token"], media=[])
    c.call(
        "scan-update",
        id=b,
        token=scan["token"],
        media=[
            {
                "id": "fault-file",
                "name": "fault.mp3",
                "path": "fault.mp3",
                "version": "fault-v1",
                "size": 10,
            }
        ],
    )
    id = a.get("/api/batches/" + b).json()["jobs"][0]["id"]
    redis = Redis.from_url(os.environ["ASR_REDIS_URL"])

    def redirect(func):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = c.call("get", id=id)
            try:
                job = Job.fetch(
                    id + "-" + str(record["generation"]),
                    connection=redis,
                    serializer=JSONSerializer,
                )
            except Exception:
                time.sleep(0.3)
                continue
            job.data = JSONSerializer.dumps((func, None, job.args, job.kwargs))
            job.save()
            return
        raise AssertionError("Dispatcher failed to enqueue")

    redirect("service_faults.crash_fixture")
    log = (root / "fault-child.log").open("w")
    process = subprocess.Popen(
        [sys.executable, __file__, "runner"], env=os.environ, stdout=log, stderr=log
    )
    marker = Path(os.environ["ASR_WORKSPACE"]) / "kill-target.json"
    deadline = time.monotonic() + 30
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    target = json.loads(marker.read_text())
    try:
        with host_lock("execution.lock"):
            raise AssertionError("Live child did not hold execution lock")
    except BlockingIOError:
        pass
    os.kill(target["pid"], signal.SIGKILL)
    process.wait(timeout=30)
    record = c.call("get", id=id)
    assert record["status"] == "transcribing", record
    with host_lock("execution.lock"):
        c.call("recover")
    recovered = c.call("get", id=id)
    assert recovered["generation"] == 1 and recovered["status"] == "interrupted"
    # Disable upload failure in this drill; roundtrip tests it separately.
    remote = Path(os.environ["ASR_WORKSPACE"]) / "remote"
    remote.mkdir(exist_ok=True)
    (remote / "lost-response").touch()
    redirect("service_roundtrip.run_fixture")
    subprocess.run(
        [sys.executable, __file__, "runner"],
        env=os.environ,
        stdout=log,
        stderr=log,
        check=True,
        timeout=30,
    )
    result = c.call("get", id=id)
    assert result["status"] == "completed", result
    report = {
        "sigkill_recovered": True,
        "live_child_lock_exclusive": True,
        "generation": result["generation"],
        "status": result["status"],
        "real_drive": False,
        "real_asr": False,
    }
    (root / "fault-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    c.close()
    a.close()
    log.close()


if __name__ == "__main__":
    runner() if len(sys.argv) > 1 else main()
