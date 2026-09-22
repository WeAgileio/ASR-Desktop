"""Explicit two-file live acceptance. Copies inputs; never scans the original tree.

Use only with authorized file IDs and an authorized destination. Does real Drive
writes and real inference. Keep the manifest to resume without another test tree.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import httpx
from asr_service.client import Client
from asr_service.drive import Drive
from asr_service.native import atomic_json, host_lock, scan_once


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host-config", required=True)
    p.add_argument("--admin-env", required=True)
    p.add_argument("--destination", required=True)
    p.add_argument("--source-file", action="append", required=True)
    p.add_argument("--evidence-dir", required=True)
    args = p.parse_args()
    assert len(set(args.source_file)) == 2, "Exactly two distinct inputs required"
    config = json.loads(Path(args.host_config).read_text())
    os.environ.update(config)
    os.environ["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    evidence = Path(args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {"destination": args.destination, "originals": args.source_file}
    )
    assert (
        manifest["destination"] == args.destination
        and manifest["originals"] == args.source_file
    )

    def save():
        atomic_json(manifest_path, manifest)

    values = dict(
        l.split("=", 1)
        for l in Path(args.admin_env).read_text().splitlines()
        if "=" in l
    )
    admin = httpx.Client(
        base_url=config["ASR_API_URL"],
        auth=("admin", values["ASR_ADMIN_PASSWORD"]),
        timeout=30,
    )
    admin.get("/").raise_for_status()
    headers = {"x-csrf-token": admin.cookies["asr_csrf"]}
    overview = admin.get("/api/overview").json()
    allowed = set(manifest.get("jobs", []))
    assert not any(
        j["status"] not in ("completed", "failed", "blocked") and j["id"] not in allowed
        for j in overview["jobs"]
    ), "Other unfinished jobs present"
    assert not any(
        b["status"] == "pending" and b["id"] != manifest.get("batch")
        for b in overview["batches"]
    ), "Other pending scans present"
    drive = Drive()
    client = Client()

    def folder(key, name, parent):
        if key not in manifest:
            manifest[key] = drive.generate_id()
            save()
        drive.ensure(manifest[key], name, parent, "live-acceptance:" + manifest[key])
        return manifest[key]

    root = folder("root", "ASR 驗收 2026-09-21", args.destination)
    source = folder("source", "測試輸入（兩個副本）", root)
    dest = folder("results", "逐字稿結果", root)
    copies = manifest.setdefault("copies", {})
    existing = list(drive.children(source))
    for original in args.source_file:
        item = drive.metadata(original)
        matching = [
            m
            for m in existing
            if m.get("appProperties", {}).get("acceptanceSource") == original
        ]
        if original not in copies:
            copy = (
                matching[0]
                if matching
                else drive.request(
                    "POST",
                    "drive/v3/files/" + original + "/copy",
                    params={"supportsAllDrives": "true", "fields": "id,md5Checksum"},
                    json={
                        "name": item["name"],
                        "parents": [source],
                        "appProperties": {"acceptanceSource": original},
                    },
                ).json()
            )
            copies[original] = copy["id"]
            save()
        assert drive.metadata(copies[original])["md5Checksum"] == item["md5Checksum"]
    drive.preflight(source, dest)
    if "batch" not in manifest:
        response = admin.post(
            "/api/batches",
            headers=headers,
            json={
                "source": source,
                "destination": dest,
                "settings": {"device": "mps"},
                "interval_seconds": 0,
            },
        )
        response.raise_for_status()
        manifest["batch"] = response.json()["id"]
        save()
    batch = admin.get("/api/batches/" + manifest["batch"]).json()
    if batch["status"] == "pending":
        with host_lock("scanner.lock"):
            scan_once(client, drive)
    batch = admin.get("/api/batches/" + manifest["batch"]).json()
    assert batch["status"] == "completed", batch.get("error")
    manifest["jobs"] = [j["id"] for j in batch["jobs"]]
    save()
    assert len(manifest["jobs"]) == 2
    assert {j["payload"]["source"] for j in batch["jobs"]} == set(copies.values())
    admin.post("/api/pause", headers=headers, json={"paused": False}).raise_for_status()
    log = (evidence / "worker.log").open("a")
    worker = subprocess.Popen(
        [
            sys.executable,
            "deployment/run_host.py",
            "worker",
            str(Path(args.host_config).resolve()),
        ],
        env=os.environ,
        stdout=log,
        stderr=log,
    )
    last = None
    deadline = time.monotonic() + 900
    try:
        while time.monotonic() < deadline:
            records = [client.call("get", id=id) for id in manifest["jobs"]]
            states = [r["status"] for r in records]
            if states != last:
                print(
                    json.dumps(
                        {"states": states, "errors": [r.get("error") for r in records]},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                last = states
            atomic_json(evidence / "latest.json", records)
            if all(s == "completed" for s in states):
                break
            if any(s in ("failed", "blocked") for s in states):
                raise RuntimeError(
                    "Acceptance job blocked or failed; inspect latest.json"
                )
            if worker.poll() is not None:
                raise RuntimeError("Native supervisor exited")
            time.sleep(2)
        else:
            raise TimeoutError("Acceptance timeout")
    finally:
        # Warm shutdown: allow a still-running child to finish instead of orphaning it.
        worker.send_signal(signal.SIGINT)
        try:
            worker.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print(
                "Worker is finishing its current job; retained PID " + str(worker.pid),
                flush=True,
            )
        log.close()
    from redis import Redis
    from rq.job import Job
    from rq.serializers import JSONSerializer

    redis = Redis.from_url(config["ASR_REDIS_URL"])
    timings = []
    jobs = []
    for record in records:
        for artifact in record["artifacts"]:
            remote = drive.metadata(artifact["remote_id"])
            if artifact["checksum"]:
                assert remote["md5Checksum"] == artifact["checksum"]
        local = Path(config["ASR_WORKSPACE"]) / "jobs" / record["id"]
        checkpoint = json.loads((local / "manifest.json").read_text())
        assert checkpoint["model"]["device"] == "mps"
        job = Job.fetch(
            record["id"] + "-" + str(record["generation"]),
            connection=redis,
            serializer=JSONSerializer,
        )
        timings.append((job.started_at.timestamp(), job.ended_at.timestamp()))
        jobs.append(
            {
                "id": record["id"],
                "name": record["payload"]["media"]["name"],
                "status": record["status"],
                "device": checkpoint["model"]["device"],
                "artifacts": record["artifacts"],
                "txt_bytes": (local / "transcript.txt").stat().st_size,
                "srt_bytes": (local / "subtitles.srt").stat().st_size,
            }
        )
    assert timings[1][0] >= timings[0][1], "Jobs overlapped"
    report = {
        "real_drive": True,
        "real_inference": True,
        "batch_id": manifest["batch"],
        "result_folder": dest,
        "jobs": jobs,
        "rq_timings": timings,
        "serial": True,
        "checksums_verified": True,
        "originals_unchanged": True,
    }
    atomic_json(evidence / "report.json", report)
    print(
        json.dumps(
            {
                "completed": 2,
                "result_folder": dest,
                "serial": True,
                "checksums_verified": True,
            }
        ),
        flush=True,
    )
    drive.session.close()
    client.close()
    admin.close()


if __name__ == "__main__":
    main()
