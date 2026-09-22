"""Transactional outbox sender. RQ retries own scheduling while their job exists."""

import logging
import time
from redis import Redis
from rq import Queue, Retry
from rq.job import Job
from rq.exceptions import NoSuchJobError
from rq.serializers import JSONSerializer
from .store import RETRY_DELAYS

log = logging.getLogger(__name__)


def dispatch_once(store, queue):
    for row in store.dispatch_rows():
        try:
            job = Job.fetch(
                row["id"], connection=queue.connection, serializer=JSONSerializer
            )
            status = job.get_status().value
        except NoSuchJobError:
            job = None
            status = None
        if job is not None:
            if status in ("queued", "started", "scheduled", "deferred"):
                store.sent(row["id"])
                continue
            # Terminal queue record with unfinished business work: create a new
            # generation, never overwrite the existing RQ job while it may be read.
            if row["next_retry"] <= time.time():
                store.redis_requeue(row["job_id"], row["generation"])
            continue
        if row["next_retry"] > time.time():
            continue
        queue.enqueue(
            "asr_service.native.execute",
            row["job_id"],
            row["generation"],
            job_id=row["id"],
            job_timeout=21600,
            result_ttl=86400,
            failure_ttl=604800,
            retry=Retry(max=max(0, 3 - row["failures"]), interval=list(RETRY_DELAYS))
            if row["failures"] < 3
            else None,
        )
        store.sent(row["id"])


def dispatch_loop(store, url, stop):
    connection = Redis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
    queue = Queue("asr", connection=connection, serializer=JSONSerializer)
    while not stop.is_set():
        try:
            dispatch_once(store, queue)
        except Exception as exc:
            log.warning("Dispatch temporarily unavailable: %s", type(exc).__name__)
        stop.wait(3)
