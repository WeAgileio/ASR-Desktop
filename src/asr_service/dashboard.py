"""Authenticated read-only wrapper around the pinned RQ Dashboard blueprint."""

import os
import secrets
from flask import Flask, request, Response
from rq.serializers import JSONSerializer
from .config import secret

READ_ENDPOINTS = {
    "queues_overview",
    "workers_overview",
    "jobs_overview",
    "job_view",
    "list_queues",
    "list_jobs",
    "job_info",
    "list_workers",
    "static",
    "favicon",
}


def create_dashboard(password=None, url=None):
    import rq_dashboard.web as web

    app = Flask(__name__)
    password = password or secret("ASR_DASHBOARD_PASSWORD")
    app.config.update(
        RQ_DASHBOARD_REDIS_URL=url
        or os.environ.get("ASR_REDIS_URL", "redis://127.0.0.1:16379/0"),
        RQ_DASHBOARD_DISABLE_DELETE=True,
        RQ_DASHBOARD_POLL_INTERVAL=5000,
    )
    web.config.serializer = JSONSerializer

    @app.before_request
    def protect():
        auth = request.authorization
        if (
            not auth
            or not secrets.compare_digest((auth.username or "").encode(), b"admin")
            or not secrets.compare_digest(
                (auth.password or "").encode(), password.encode()
            )
        ):
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="RQ monitor"'},
            )
        name = (request.endpoint or "").split(".")[-1]
        if request.method not in ("GET", "HEAD") or name not in READ_ENDPOINTS:
            return Response("Read-only dashboard; use ASR control API", 403)

    app.register_blueprint(web.blueprint, url_prefix="")
    web.setup_rq_connection(app)
    return app


def main():
    import uvicorn
    from starlette.middleware.wsgi import WSGIMiddleware

    uvicorn.run(WSGIMiddleware(create_dashboard()), host="0.0.0.0", port=9181)


if __name__ == "__main__":
    main()
