"""Loopback-only native control panel, independent of the worker virtualenv."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlparse, parse_qs
import webbrowser

from mac_service import ROLES, read_env


def atomic_private(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(json.dumps(data, indent=2) + "\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_settings(body):
    expected = {"ASR_API_URL", "ASR_REDIS_URL", "ASR_RETENTION_DAYS", "ASR_MIN_FREE_BYTES"}
    if set(body) != expected:
        raise ValueError("設定欄位不完整或包含不支援的欄位。")
    for key, scheme in (("ASR_API_URL", "http"), ("ASR_REDIS_URL", "redis")):
        value = urlparse(body[key])
        if value.scheme != scheme or value.hostname not in ("127.0.0.1", "localhost") or value.username or value.password:
            raise ValueError("此版本只接受本機 http／redis 連線，不接受含帳密的 URL。")
        if value.query or value.fragment or not value.port:
            raise ValueError("請輸入包含埠號的本機 URL。")
        if key == "ASR_API_URL" and value.path not in ("", "/"):
            raise ValueError("API URL 不可包含路徑。")
        if key == "ASR_REDIS_URL" and value.path != "/0":
            raise ValueError("Redis 請使用 /0 資料庫。")
    if not 1 <= int(body["ASR_RETENTION_DAYS"]) <= 3650:
        raise ValueError("保留天數須為 1–3650。")
    if int(body["ASR_MIN_FREE_BYTES"]) < 1024**3:
        raise ValueError("最低空間至少為 1 GiB。")
    return {key: str(value) for key, value in body.items()}


class Panel:
    def __init__(self, manager):
        self.manager = manager
        self.csrf = secrets.token_urlsafe(32)
        password = read_env(manager.config / "compose.env")["ASR_ADMIN_PASSWORD"]
        self.authorization = "Basic " + base64.b64encode(("admin:" + password).encode()).decode()
        self.guard = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.result = "準備就緒"

    def submit(self, command, body):
        if command not in {"install", "start", "stop", "pause", "resume", "update", "login", "settings", "oauth-client"}:
            raise ValueError("不支援此操作。")
        with self.guard:
            if self.busy:
                raise ValueError("目前有管理操作執行中，請等待完成。")
            self.busy = True
            self.result = f"正在執行 {command}；安裝及 Google 授權可能需要數分鐘。"
        self.pool.submit(self.execute, command, body)

    def execute(self, command, body):
        manager = self.manager
        try:
            if command in ("settings", "oauth-client"):
                if any(manager.loaded(role) for role in ROLES):
                    raise ValueError("請先停止原生服務再修改設定或 OAuth client。")
                with manager.locks(("supervisor.lock", "scanner.lock", "execution.lock")):
                    if command == "settings":
                        settings = manager.settings()
                        settings.update(validate_settings(body))
                        atomic_private(manager.host, settings)
                    else:
                        installed = body.get("installed", {})
                        if (installed.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth" or
                            installed.get("token_uri") != "https://oauth2.googleapis.com/token" or
                            not installed.get("client_id") or not installed.get("client_secret")):
                            raise ValueError("需要有效的 Google Desktop OAuth client JSON。")
                        atomic_private(manager.config / "oauth-client.json", body)
            elif command in ("pause", "resume"):
                manager.pause(command == "pause")
            elif command == "login":
                manager.login(manager.config / "oauth-client.json")
            elif command == "update":
                manager.stop()
                manager.install()
                manager.start()
            else:
                getattr(manager, command)()
            result = f"{command} 完成。停止或更新後，請確認狀態再按「恢復領取」。"
        except Exception as exc:
            # Never return OAuth, subprocess or HTTP exception payloads to the browser.
            result = str(exc) if type(exc) is ValueError else f"操作未完成（{type(exc).__name__}）；請檢查終端機、Docker 與本機設定。"
        with self.guard:
            self.busy = False
            self.result = result

    def state(self):
        settings = self.manager.settings()
        fields = ("ASR_API_URL", "ASR_REDIS_URL", "ASR_RETENTION_DAYS", "ASR_MIN_FREE_BYTES")
        with self.guard:
            result = {"busy": self.busy, "result": self.result}
        result.update(settings={key: settings.get(key, "") for key in fields},
                      agents={role: self.manager.loaded(role) for role in ROLES},
                      credentials=Path(settings.get("ASR_GOOGLE_TOKEN_FILE", "/nonexistent")).is_file(),
                      config=str(self.manager.host))
        values = read_env(self.manager.config / "compose.env")
        port = int(values.get("ASR_DASHBOARD_PORT", "9181"))
        result["dashboard"] = f"http://127.0.0.1:{port}"
        # Local launchd status is distinct from API heartbeat / successful connection.
        return result


def make_handler(panel):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log request headers or uploaded client data.

        def send(self, code, body, content="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", content + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 401:
                self.send_header("WWW-Authenticate", 'Basic realm="ASR Mac Manager"')
            self.end_headers()
            self.wfile.write(data)

        def authenticated(self):
            # Host validation also rejects DNS rebinding to this loopback service.
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send(403, {"error": "Invalid host"})
                return False
            if not hmac.compare_digest(self.headers.get("Authorization", ""), panel.authorization):
                self.send(401, {"error": "請使用 admin 與 compose.env 的 ASR_ADMIN_PASSWORD 登入。"})
                return False
            return True

        def do_GET(self):
            if not self.authenticated():
                return
            try:
                path = urlparse(self.path)
                if path.path == "/":
                    html = Path(__file__).with_name("mac_panel.html").read_text()
                    self.send(200, html.replace("__CSRF__", panel.csrf), "text/html")
                elif path.path == "/state":
                    self.send(200, panel.state())
                elif path.path == "/logs":
                    role = parse_qs(path.query).get("role", ["worker"])[0]
                    if role not in ROLES:
                        raise ValueError("不支援的程序名稱。")
                    file = panel.manager.logs / f"{role}-error.log"
                    if file.exists():
                        with file.open("rb") as stream:
                            stream.seek(max(0, file.stat().st_size - 16000))
                            text = stream.read(16000).decode(errors="replace")
                    else:
                        text = "尚無日誌；安裝及 OAuth 輸出請查看啟動管理頁的終端機。"
                    self.send(200, {"text": text})
                else:
                    self.send(404, {"error": "Not found"})
            except Exception:
                self.send(500, {"error": "無法讀取狀態，請檢查本機設定。"})

        def do_POST(self):
            if not self.authenticated():
                return
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), panel.csrf):
                self.send(403, {"error": "請重新整理管理頁。"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("請求大小不合法。")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("需要 JSON 物件。")
                if self.path != "/action":
                    self.send(404, {"error": "Not found"})
                    return
                panel.submit(body.get("command", ""), body.get("data", {}))
                self.send(202, {"ok": True})
            except (ValueError, TypeError):
                self.send(400, {"error": "操作無效或已有操作執行中。"})
    return Handler


def serve(manager, port):
    panel = Panel(manager)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(panel))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"管理頁：{url}\n帳號：admin；密碼位於 {manager.config / 'compose.env'} 的 ASR_ADMIN_PASSWORD。")
    print("請保持此終端機開啟；關閉管理頁程序不會停止 launchd 的 worker／scanner。")
    webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        panel.pool.shutdown(wait=True)
