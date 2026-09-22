"""Host-only Drive integration. No credentials or file bytes enter queue payloads."""

import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from .models import natural_key

FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
FIELDS = "id,name,mimeType,size,md5Checksum,version,parents,driveId,trashed,appProperties,capabilities(canListChildren,canAddChildren,canDownload)"


class DriveError(Exception):
    def __init__(self, message, blocked=False):
        super().__init__(message)
        self.blocked = blocked


class SourceChanged(DriveError):
    pass


def content_version(item):
    if item.get("md5Checksum"):
        return "md5:" + item["md5Checksum"]
    if not item.get("version"):
        raise DriveError("來源缺少可識別的版本", blocked=True)
    return "version:" + str(item["version"]) + ":" + str(item.get("size", 0))


def file_md5(path):
    digest = hashlib.md5()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Drive:
    auth_mode = "service_account"

    def __init__(self, credentials_path=None, session=None, auth_mode=None):
        self.auth_mode = auth_mode or os.environ.get(
            "ASR_DRIVE_AUTH", "service_account"
        )
        if self.auth_mode not in ("service_account", "oauth"):
            raise ValueError("ASR_DRIVE_AUTH must be service_account or oauth")
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            from .oauth import local_path, load_credentials

            if self.auth_mode == "oauth":
                credentials = load_credentials(
                    credentials_path or os.environ["ASR_GOOGLE_TOKEN_FILE"]
                )
            else:
                from google.oauth2.service_account import Credentials

                path = local_path(
                    credentials_path or os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
                )
                credentials = Credentials.from_service_account_file(
                    str(path), scopes=["https://www.googleapis.com/auth/drive"]
                )
            session = AuthorizedSession(credentials)
        self.session = session

    def request(self, method, path, **kwargs):
        url = "https://www.googleapis.com/" + path
        streams = [
            part[1][1]
            for part in kwargs.get("files", [])
            if hasattr(part[1][1], "seek")
        ]
        offsets = [stream.tell() for stream in streams]
        for attempt in range(4):
            for stream, offset in zip(streams, offsets):
                stream.seek(offset)
            from google.auth.exceptions import RefreshError

            try:
                response = self.session.request(method, url, timeout=60, **kwargs)
            except RefreshError as exc:
                raise DriveError(
                    "Google 授權無法更新，請重新登入或檢查帳號授權",
                    blocked=not exc.retryable,
                ) from None
            if response.ok:
                return response
            try:
                reasons = [
                    e.get("reason")
                    for e in response.json().get("error", {}).get("errors", [])
                ]
            except (ValueError, AttributeError):
                reasons = []
            transient = (
                response.status_code == 429
                or response.status_code >= 500
                or any(
                    r in ("rateLimitExceeded", "userRateLimitExceeded") for r in reasons
                )
            )
            if transient and attempt < 3:
                response.close()
                time.sleep(min(2**attempt, 8))
                continue
            status = response.status_code
            response.close()
            # Never echo server error bodies: they can include credential or resource details.
            raise DriveError(
                f"Drive HTTP {status}",
                blocked=status in (401, 403, 404) and not transient,
            )
        raise DriveError("Drive request exhausted retries")

    def metadata(self, id):
        return self.request(
            "GET",
            "drive/v3/files/" + id,
            params={"supportsAllDrives": "true", "fields": FIELDS},
        ).json()

    def children(self, id):
        params = {
            "q": f"'{id}' in parents and trashed = false",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "fields": f"nextPageToken,incompleteSearch,files({FIELDS})",
        }
        while True:
            page = self.request("GET", "drive/v3/files", params=params).json()
            if page.get("incompleteSearch"):
                raise DriveError("Drive 回傳不完整搜尋結果")
            yield from page.get("files", [])
            if not page.get("nextPageToken"):
                break
            params["pageToken"] = page["nextPageToken"]

    def preflight(self, source, destination):
        src, dst = self.metadata(source), self.metadata(destination)
        if (
            src.get("trashed")
            or src.get("mimeType") != FOLDER
            or not src.get("capabilities", {}).get("canListChildren")
        ):
            raise DriveError("來源資料夾不可列出", blocked=True)
        if (
            dst.get("trashed")
            or dst.get("mimeType") != FOLDER
            or not dst.get("capabilities", {}).get("canAddChildren")
        ):
            raise DriveError("目的地必須是可新增內容的資料夾", blocked=True)
        if self.auth_mode == "service_account" and not dst.get("driveId"):
            raise DriveError(
                "服務帳號目的地必須位於共用雲端硬碟；My Drive 請使用 OAuth",
                blocked=True,
            )
        parents = [source]
        visited = set()
        while parents:
            id = parents.pop()
            if id == destination:
                raise DriveError("目的地不能是來源本身或其祖先", blocked=True)
            if id in visited:
                continue
            visited.add(id)
            parents.extend(self.metadata(id).get("parents", []))

    def scan(self, source, destination):
        self.preflight(source, destination)
        pending = [(source, "")]
        visited = set()
        files = {}
        skipped = 0
        while pending:
            folder, prefix = pending.pop()
            if folder in visited or folder == destination:
                continue
            visited.add(folder)
            for item in self.children(folder):
                if (
                    item.get("trashed")
                    or item["id"] == destination
                    or item.get("appProperties", {}).get("asrResult") == "1"
                ):
                    skipped += 1
                    continue
                mime = item.get("mimeType", "")
                relative = prefix + item["name"]
                if mime == FOLDER:
                    pending.append((item["id"], relative + "/"))
                elif mime == SHORTCUT or not (
                    mime.startswith("audio/") or mime.startswith("video/")
                ):
                    skipped += 1
                elif not item.get("capabilities", {}).get("canDownload"):
                    raise DriveError("來源媒體不允許下載", blocked=True)
                else:
                    files[item["id"]] = {
                        "id": item["id"],
                        "name": item["name"],
                        "path": relative,
                        "version": content_version(item),
                        "size": int(item.get("size", 0)),
                        "md5": item.get("md5Checksum", ""),
                        "mime": mime,
                    }
        return sorted(files.values(), key=lambda x: natural_key(x["path"])), skipped

    def download(self, item, path):
        path = Path(path)
        before = self.metadata(item["id"])
        if content_version(before) != item["version"]:
            raise SourceChanged("來源版本已改變，請重新掃描", blocked=True)
        temp = path.with_suffix(".part")
        digest = hashlib.md5()
        size = 0
        with self.request(
            "GET",
            "drive/v3/files/" + item["id"],
            params={"alt": "media", "supportsAllDrives": "true"},
            stream=True,
        ) as response:
            with temp.open("wb") as output:
                for block in response.iter_content(1024 * 1024):
                    if block:
                        output.write(block)
                        digest.update(block)
                        size += len(block)
                output.flush()
                os.fsync(output.fileno())
        after = self.metadata(item["id"])
        if (
            content_version(after) != item["version"]
            or size != item["size"]
            or (item["md5"] and digest.hexdigest() != item["md5"])
        ):
            temp.unlink(missing_ok=True)
            raise SourceChanged("下載內容與排程版本不一致，請重新掃描", blocked=True)
        os.replace(temp, path)
        return digest.hexdigest()

    def generate_id(self):
        return self.request(
            "GET",
            "drive/v3/files/generateIds",
            params={"count": 1, "space": "drive", "type": "files"},
        ).json()["ids"][0]

    def ensure(self, id, name, parent, identity, path=None):
        properties = {"asrResult": "1", "identity": identity}
        mime = (
            FOLDER
            if path is None
            else ("application/json" if name.endswith(".json") else "text/plain")
        )
        checksum = "" if path is None else file_md5(path)
        try:
            current = self.metadata(id)
        except DriveError as exc:
            if str(exc) != "Drive HTTP 404":
                raise
            current = None
        if current:
            if (
                current.get("trashed")
                or current.get("appProperties", {}).get("identity") != identity
                or parent not in current.get("parents", [])
                or current.get("mimeType") != mime
            ):
                raise DriveError("既有輸出 ID 的身份或位置不一致", blocked=True)
            if path is None or current.get("md5Checksum") == checksum:
                return checksum
        body = {"name": name, "mimeType": mime, "appProperties": properties}
        if not current:
            body.update(id=id, parents=[parent])
        if path is None:
            self.request(
                "POST",
                "drive/v3/files",
                params={"supportsAllDrives": "true"},
                json=body,
            )
        else:
            method = "PATCH" if current else "POST"
            endpoint = "upload/drive/v3/files" + ("/" + id if current else "")
            boundary = "asr_" + uuid.uuid4().hex
            # Drive requires multipart/related, not requests' multipart/form-data.
            data = (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + json.dumps(body).encode()
                + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
                + Path(path).read_bytes()
                + f"\r\n--{boundary}--\r\n".encode()
            )
            self.request(
                method,
                endpoint,
                params={"uploadType": "multipart", "supportsAllDrives": "true"},
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                data=data,
            )
        # A timeout after create is recovered by the next call using the same reserved ID.
        final = self.metadata(id)
        if final.get("appProperties", {}).get("identity") != identity or (
            path is not None and final.get("md5Checksum") != checksum
        ):
            raise DriveError("上傳結果驗證失敗")
        return checksum
