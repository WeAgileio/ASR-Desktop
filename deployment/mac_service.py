"""Manage native macOS scanner/worker; configuration and credentials stay local."""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import plistlib
import secrets
import shutil
import subprocess
import sys
import urllib.request

APP = Path(__file__).resolve().parents[1]
ROLES = ("scanner", "worker")


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def local(path):
    path = Path(path).expanduser().resolve()
    if "Mobile Documents" in path.parts or "CloudStorage" in path.parts:
        raise ValueError("程式、設定與資料請放非雲端同步目錄，例如 ~/Projects/ASR。")
    return path


def private_write(path, content):
    # Exclusive creation: reruns must never rotate an existing secret.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


class Manager:
    def __init__(self, config, host=None):
        self.config = local(config)
        self.host = local(host) if host else self.config / "host.json"
        if host is None and not self.host.exists() and (self.config / "host.oauth.json").exists():
            self.host = self.config / "host.oauth.json"
        self.python = APP / ".venv-worker/bin/python"
        self.agents = Path.home() / "Library/LaunchAgents"
        self.logs = self.config / "logs"
        self.domain = f"gui/{os.getuid()}"

    def settings(self):
        return json.loads(self.host.read_text())

    def label(self, role):
        return f"com.local.asr.{role}"

    def plist(self, role):
        return self.agents / f"{self.label(role)}.plist"

    def loaded(self, role):
        return subprocess.run(["launchctl", "print", f"{self.domain}/{self.label(role)}"],
                              capture_output=True).returncode == 0

    def definition(self, role):
        with (APP / "deployment/launchd" / f"{self.label(role)}.plist").open("rb") as stream:
            data = plistlib.load(stream)
        data["ProgramArguments"] = [str(self.python), str(APP / "deployment/run_host.py"), role, str(self.host)]
        data["EnvironmentVariables"]["PYTHONPATH"] = str(APP / "src")
        ffmpeg_dir = str(Path(shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg").parent)
        data["EnvironmentVariables"]["PATH"] = ffmpeg_dir + ":/opt/homebrew/bin:/usr/bin:/bin"
        data["StandardOutPath"] = str(self.logs / f"{role}.log")
        data["StandardErrorPath"] = str(self.logs / f"{role}-error.log")
        return data

    def check_agents(self):
        for role in ROLES:
            path = self.plist(role)
            if path.exists():
                with path.open("rb") as stream:
                    saved = plistlib.load(stream)
                if saved != self.definition(role):
                    raise ValueError(f"已有不同設定的 LaunchAgent：{path}；請先檢查，工具不會覆寫。")

    @contextmanager
    def locks(self, names):
        directory = local(self.settings()["ASR_WORKSPACE"])
        directory.mkdir(parents=True, exist_ok=True)
        handles = []
        try:
            for name in names:
                handle = (directory / name).open("a+")
                handles.append(handle)
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError("仍有程序或任務執行中；請等待完成後重試。") from None
            yield
        finally:
            for handle in handles:
                handle.close()

    def initialize(self):
        self.config.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config.chmod(0o700)
        if self.host.exists():
            self.settings()
            return
        # Partial configurations need explicit repair; never replace their credentials.
        env_path = self.config / "compose.env"
        token_path = self.config / "worker-token.txt"
        if env_path.exists() or token_path.exists():
            raise ValueError("已有部分設定但沒有 host.json；請依部署指南補齊，工具不會覆寫。")
        values = {name: secrets.token_urlsafe(32) for name in (
            "ASR_ADMIN_PASSWORD", "ASR_WORKER_TOKEN", "ASR_SIGNING_KEY", "ASR_DASHBOARD_PASSWORD")}
        values.update(ASR_WEB_PORT="8090", ASR_REDIS_PORT="16379", ASR_DASHBOARD_PORT="9181",
                      ASR_IMAGE="ghcr.io/weagileio/asrjob:v0.1.0")
        data = local(Path.home() / "Library/Application Support/asr-service")
        settings = {
            "ASR_API_URL": "http://127.0.0.1:8090", "ASR_REDIS_URL": "redis://127.0.0.1:16379/0",
            "ASR_WORKER_TOKEN_FILE": str(token_path), "ASR_WORKSPACE": str(data),
            "ASR_DRIVE_AUTH": "oauth", "ASR_GOOGLE_TOKEN_FILE": str(self.config / "google-user-token.json"),
            "ASR_RETENTION_DAYS": "7", "ASR_MIN_FREE_BYTES": "5368709120",
        }
        private_write(env_path, "".join(f"{k}={v}\n" for k, v in values.items()))
        private_write(token_path, values["ASR_WORKER_TOKEN"] + "\n")
        private_write(self.host, json.dumps(settings, indent=2) + "\n")
        data.mkdir(parents=True, exist_ok=True, mode=0o700)

    def install(self):
        local(APP)
        if not shutil.which("ffmpeg"):
            raise ValueError("找不到 FFmpeg，請先執行 brew install uv ffmpeg。")
        self.check_agents()
        if any(self.loaded(role) for role in ROLES):
            raise ValueError("服務已載入；更新請用 update，安裝不會覆寫運作中的環境。")
        self.initialize()
        with self.locks(("supervisor.lock", "scanner.lock", "execution.lock")):
            if not self.python.exists():
                run("uv", "venv", APP / ".venv-worker", "--python", "3.11.15")
            run("uv", "pip", "sync", APP / "deployment/requirements/worker-macos-arm64.lock",
                "--python", self.python)
            run(self.python, "-c", "import torch; print('MPS available:', torch.backends.mps.is_available())")
            self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.agents.mkdir(parents=True, exist_ok=True)
            for role in ROLES:
                if not self.plist(role).exists():
                    with self.plist(role).open("xb") as stream:
                        plistlib.dump(self.definition(role), stream)
        print(f"安裝完成。設定：{self.host}；尚未啟動服務。")

    def api(self, path, body=None):
        settings = self.settings()
        url = settings["ASR_API_URL"].rstrip("/")
        values = read_env(self.config / "compose.env")
        auth = base64.b64encode(("admin:" + values["ASR_ADMIN_PASSWORD"]).encode()).decode()
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        opener.addheaders = [("Authorization", "Basic " + auth)]
        headers = {}
        if body is not None:
            with opener.open(url + "/", timeout=10) as response:
                response.read()
            csrf = next(cookie.value for cookie in jar if cookie.name == "asr_csrf")
            headers = {"x-csrf-token": csrf, "Content-Type": "application/json"}
        request = urllib.request.Request(url + path, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    def pause(self, paused):
        self.api("/api/pause", {"paused": paused})
        print("已暫停下一筆領取。" if paused else "已恢復領取。")

    def stop(self):
        self.check_agents()
        self.pause(True)
        with self.locks(("execution.lock",)):
            for role in ROLES:
                if self.loaded(role):
                    run("launchctl", "bootout", f"{self.domain}/{self.label(role)}")
        print("原生服務已停止；Docker 保持運行，佇列維持暫停。")

    def start(self):
        self.check_agents()
        settings = self.settings()
        credential_key = "ASR_GOOGLE_TOKEN_FILE" if settings.get("ASR_DRIVE_AUTH") == "oauth" else "GOOGLE_APPLICATION_CREDENTIALS"
        if not Path(settings[credential_key]).is_file():
            raise ValueError("缺少 Google 憑證；OAuth 模式請先執行 login。")
        state = self.api("/api/overview")
        for role in ROLES:
            if not self.plist(role).exists():
                raise ValueError("缺少 LaunchAgent，請先執行 install。")
        for role in ROLES:
            if not self.loaded(role):
                run("launchctl", "bootstrap", self.domain, self.plist(role))
        print("啟動指令已送出；請用 status 確認程序與心跳。")
        if state["paused"]:
            print("佇列仍暫停；確認正常後執行 resume。")

    def login(self, client):
        if any(self.loaded(role) for role in ROLES):
            raise ValueError("請先 stop，避免運行中切換 Google 身份。")
        settings = self.settings()
        if settings.get("ASR_DRIVE_AUTH") != "oauth":
            raise ValueError("目前不是 OAuth 模式，請依完整指南設定服務帳號。")
        source = local(client)  # Downloads is allowed; synced credential files are not.
        config = json.loads(source.read_text())
        if "installed" not in config:
            raise ValueError("需要 Desktop app OAuth client JSON。")
        with self.locks(("supervisor.lock", "scanner.lock", "execution.lock")):
            env = dict(os.environ, PYTHONPATH=str(APP / "src"))
            run(self.python, "-m", "asr_service.oauth", "--client-secrets", source,
                "--token-file", settings["ASR_GOOGLE_TOKEN_FILE"], env=env)

    def status(self):
        for role in ROLES:
            print(f"{role}: {'launchd 已載入' if self.loaded(role) else 'launchd 未載入'}")
        state = self.api("/api/overview")
        print(f"API: 可連線；暫停領取: {state['paused']}")
        print("程序心跳：", json.dumps(state.get("workers", state.get("heartbeats", {})), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="ASR Mac 原生服務管理（不修改 Git 或 Docker stack）")
    parser.add_argument("--config-dir", default=str(Path.home() / "Library/Application Support/asr-service-config"))
    parser.add_argument("--host-config", help="沿用既有 host 設定，預設自動選 host.json／host.oauth.json")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("install", "start", "stop", "status", "pause", "resume", "update"):
        sub.add_parser(command)
    login = sub.add_parser("login")
    login.add_argument("--client", required=True, help="Google Desktop OAuth client JSON")
    logs = sub.add_parser("logs")
    logs.add_argument("role", choices=ROLES, nargs="?", default="worker")
    ui = sub.add_parser("ui", help="開啟本機可視化管理頁")
    ui.add_argument("--port", type=int, default=9182)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("此工具適用原生 Apple Silicon macOS。")
    try:
        manager = Manager(args.config_dir, args.host_config)
        if args.command == "ui":
            local(APP)
            manager.initialize()
            from mac_panel import serve
            serve(manager, args.port)
        elif args.command in ("pause", "resume"):
            manager.pause(args.command == "pause")
        elif args.command == "login":
            manager.login(args.client)
        elif args.command == "logs":
            run("tail", "-n", "100", "-f", manager.logs / f"{args.role}-error.log")
        elif args.command == "update":
            manager.stop()
            manager.install()
            manager.start()
            print("已同步目前程式碼的依賴並重啟；確認正常後執行 resume。")
        else:
            getattr(manager, args.command)()
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as exc:
        # HTTP/auth payloads and subprocess arguments may contain private details.
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        else:
            print(f"操作未完成（{type(exc).__name__}）。請檢查 Docker、設定、權限及本機日誌。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
