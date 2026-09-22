"""The only database-owning process; no Google or model imports here."""

from contextlib import asynccontextmanager
import asyncio
import secrets
from pathlib import Path
import threading
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import (
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
    HTTPAuthorizationCredentials,
)
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pydantic import Field
from .config import APIConfig
from .models import StrictModel, BatchInput, Media
from .store import Store, Conflict, Missing


class WorkerMessage(StrictModel):
    id: str = Field(default="", max_length=200)
    token: str = Field(default="", max_length=200)
    generation: int = Field(default=0, ge=0)
    sequence: int = Field(default=0, ge=0)
    phase: Literal["downloading", "transcribing", "uploading"] | None = None
    progress: dict | None = None
    media: list[Media] | None = None
    error: str | None = Field(default=None, max_length=1000)
    blocked: bool = False
    skipped: int = Field(default=0, ge=0)
    state: Literal["completed", "retry_wait", "blocked", "failed"] = "failed"
    kind: str = Field(default="", max_length=100)
    remote_id: str = Field(default="", max_length=200)
    checksum: str = Field(default="", max_length=200)
    name: Literal["worker", "scanner"] = "worker"


class PauseInput(StrictModel):
    paused: bool


def create_app(config=None):
    config = config or APIConfig.environment()
    store = Store(config.db)
    signer = URLSafeTimedSerializer(config.signing_key, salt="asr-csrf")
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app):
        thread = None
        if config.dispatch:
            from .dispatch import dispatch_loop

            thread = threading.Thread(
                target=dispatch_loop, args=(store, config.redis_url, stop), daemon=True
            )
            thread.start()
        yield
        stop.set()
        if thread:
            await asyncio.to_thread(thread.join, 10)

    app = FastAPI(
        title="ASR 任務服務", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.store = store
    basic = HTTPBasic()
    bearer = HTTPBearer()
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    def admin(credentials: HTTPBasicCredentials = Depends(basic)):
        user_ok = secrets.compare_digest(credentials.username.encode(), b"admin")
        password_ok = secrets.compare_digest(
            credentials.password.encode(), config.password.encode()
        )
        if not (user_ok and password_ok):
            raise HTTPException(401, "登入失敗", headers={"WWW-Authenticate": "Basic"})

    def mutation(request: Request, _=Depends(admin)):
        cookie = request.cookies.get("asr_csrf", "")
        header = request.headers.get("x-csrf-token", "")
        try:
            signer.loads(cookie, max_age=86400)
        except BadSignature:
            raise HTTPException(403, "CSRF token expired or missing")
        if not header or not secrets.compare_digest(cookie, header):
            raise HTTPException(403, "CSRF validation failed")

    def worker(auth: HTTPAuthorizationCredentials = Depends(bearer)):
        if not secrets.compare_digest(
            auth.credentials.encode(), config.worker_token.encode()
        ):
            raise HTTPException(403, "Worker authentication failed")

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Missing)
    async def missing(request, exc):
        return JSONResponse({"detail": "Record not found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def home(request: Request):
        token = signer.dumps(secrets.token_hex(24))
        response = templates.TemplateResponse(
            request=request, name="index.html", context={"csrf": token}
        )
        response.set_cookie(
            "asr_csrf", token, httponly=True, samesite="strict", max_age=86400
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/overview", dependencies=[Depends(admin)])
    def overview():
        return store.overview()

    @app.post("/api/batches", dependencies=[Depends(mutation)])
    def batch(body: BatchInput):
        return {"id": store.batch(body.model_dump())}

    @app.get("/api/batches/{id}", dependencies=[Depends(admin)])
    def batch_detail(id: str):
        return store.get("batches", id)

    @app.get("/api/jobs/{id}", dependencies=[Depends(admin)])
    def job_detail(id: str):
        return store.get("jobs", id)

    @app.post("/api/batches/{id}/rescan", dependencies=[Depends(mutation)])
    def rescan(id: str):
        store.rescan(id)
        return {"ok": True}

    @app.post("/api/jobs/{id}/retry", dependencies=[Depends(mutation)])
    def retry(id: str):
        store.retry(id)
        return {"ok": True}

    @app.post("/api/pause", dependencies=[Depends(mutation)])
    def pause(body: PauseInput):
        store.pause(body.paused)
        return {"ok": True}

    @app.post("/worker/{action}", dependencies=[Depends(worker)])
    def rpc(action: str, body: WorkerMessage):
        if action == "control":
            store.heartbeat(body.name)
            return {"paused": store.overview()["paused"]}
        if action == "scan-claim":
            return store.scan_claim()
        if action == "scan-update":
            store.scan_update(
                body.id,
                body.token,
                media=[m.model_dump() for m in body.media]
                if body.media is not None
                else None,
                error=body.error,
                blocked=body.blocked,
                skipped=body.skipped,
            )
        elif action == "get":
            return store.get("jobs", body.id)
        elif action == "claim":
            if len(body.token) < 24:
                raise ValueError("Missing execution token")
            return store.claim(body.id, body.generation, body.token)
        elif action == "event":
            store.event(body.id, body.token, body.sequence, body.phase, body.progress)
        elif action == "finish":
            store.finish(body.id, body.token, body.state, body.error or "")
        elif action == "recover":
            store.recover()
        elif action == "reserve":
            return store.reserve(body.id, body.token, body.kind, body.remote_id)
        elif action == "verify":
            store.verify(body.id, body.token, body.kind, body.remote_id, body.checksum)
        elif action != "scan-update":
            raise HTTPException(404, "Unknown worker operation")
        return {"ok": True}

    return app
