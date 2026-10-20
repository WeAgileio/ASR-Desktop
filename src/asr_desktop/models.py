"""Immutable model snapshots. Only explicit preparation may access the network."""

from contextlib import contextmanager
import fcntl
import hashlib
from importlib import resources
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError


class ModelError(RuntimeError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".new")
    with temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ModelStore:
    def __init__(self, root, catalog=None, references=None, opener=urlopen, free_bytes=None):
        self.root = Path(root)
        self.catalog = catalog or json.loads(resources.files("asr_desktop").joinpath("data/models.json").read_text())
        self.references = references or (lambda snapshot: [])
        self.opener = opener
        self.free_bytes = free_bytes or (lambda: shutil.disk_usage(self.root).free)
        self._threads = {}
        self._mutex = threading.Lock()
        for directory in (self.root, self.root / "snapshots", self.root / "staging", self.root / "locks", self.root / "definitions"):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if directory.is_symlink():
                raise ModelError("unsafe_store", "Model store cannot contain symlink directories")
        for model in self.catalog["models"]:
            definition = dict(model, component_definitions={key: self.catalog["components"][key] for key in model["components"]})
            self._validate_definition(definition)
            target = self.root / "definitions" / (model["snapshot_id"] + ".json")
            if not target.exists():
                atomic_json(target, definition)

    @staticmethod
    def _validate_definition(definition):
        components = definition["component_definitions"]
        identity = hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if identity != definition["snapshot_id"]:
            raise ModelError("invalid_catalog", "Snapshot identity does not match its immutable assets")
        for component in components.values():
            if not re.fullmatch(r"[0-9a-f]{40}", component["revision"]):
                raise ModelError("invalid_catalog", "Model revision must be an immutable commit")
            for asset in component["assets"]:
                path = PurePosixPath(asset["path"])
                if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in asset["path"]:
                    raise ModelError("invalid_catalog", "Unsafe model asset path")
                if asset["size"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]):
                    raise ModelError("invalid_catalog", "Invalid asset integrity metadata")

    def definition(self, identifier):
        for model in self.catalog["models"]:
            if identifier == model["id"]:
                identifier = model["snapshot_id"]
                break
        if not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise ModelError("unknown_model", "Choose a catalog model or known snapshot")
        try:
            value = json.loads((self.root / "definitions" / (identifier + ".json")).read_text())
        except FileNotFoundError:
            raise ModelError("unknown_model", "The pinned snapshot definition is unavailable")
        self._validate_definition(value)
        return value

    @contextmanager
    def _lock(self, snapshot):
        descriptor = os.open(self.root / "locks" / snapshot, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ModelError("model_busy", "This snapshot is already being prepared or verified")
            yield
        finally:
            os.close(descriptor)

    def _assets(self, definition, base):
        for key, component in definition["component_definitions"].items():
            for asset in component["assets"]:
                yield asset, base / key / asset["path"]

    @staticmethod
    def _complete(asset, path, checksum=True):
        try:
            # Reject symlinks at every level, including tokenizer directories.
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                return False
            return (stat.S_ISREG(path.stat().st_mode) and path.stat().st_size == asset["size"]
                    and (not checksum or digest_file(path) == asset["sha256"]))
        except FileNotFoundError:
            return False

    def status(self, identifier):
        definition = self.definition(identifier)
        snapshot = definition["snapshot_id"]
        base = self.root / "snapshots" / snapshot
        ready = (base / "ready.json").is_file() and all(self._complete(a, p, False) for a, p in self._assets(definition, base))
        staging = self.root / "staging" / snapshot
        state = {}
        try:
            state = json.loads((staging / "state.json").read_text())
        except (FileNotFoundError, ValueError):
            pass
        if ready:
            state = {"state": "ready", "downloaded_bytes": definition["download_bytes"]}
        elif state.get("state") in ("downloading", "verifying") and not self.active(snapshot):
            state["state"] = "interrupted"
        storage_bytes = 0
        for location in (base, staging):
            for _, path in self._assets(definition, location):
                for candidate in (path, path.with_name(path.name + ".partial")):
                    if candidate.is_file() and not candidate.is_symlink():
                        storage_bytes += candidate.stat().st_size
        return {**definition, **state, "ready": ready, "state": "ready" if ready else state.get("state", "missing"),
                "storage_bytes": storage_bytes,
                "required_free_bytes": 0 if ready else state.get("required_free_bytes", definition["download_bytes"] + max(16 * 1024 * 1024, definition["download_bytes"] // 100))}

    def active(self, snapshot):
        # File lock is authoritative across clients and store instances.
        try:
            with self._lock(snapshot):
                return False
        except ModelError:
            return True

    def list(self):
        return [self.status(model["id"]) for model in self.catalog["models"]]

    def start(self, identifier):
        definition = self.definition(identifier)
        snapshot = definition["snapshot_id"]
        with self._mutex:
            if self.active(snapshot) or (snapshot in self._threads and self._threads[snapshot].is_alive()):
                return self.status(snapshot)
            if self.status(snapshot)["ready"]:
                return self.status(snapshot)
            thread = threading.Thread(target=self._background_prepare, args=(snapshot,), daemon=True)
            self._threads[snapshot] = thread
            thread.start()
        return self.status(snapshot)

    def _background_prepare(self, snapshot):
        try:
            self.prepare(snapshot)
        except (ModelError, OSError):
            # prepare persists the failure for both interfaces.
            pass

    def prepare(self, identifier, progress=None):
        definition = self.definition(identifier)
        snapshot = definition["snapshot_id"]
        with self._lock(snapshot):
            staging = self.root / "staging" / snapshot
            staging.mkdir(exist_ok=True, mode=0o700)
            final = self.root / "snapshots" / snapshot
            state = {"state": "downloading", "downloaded_bytes": 0, "total_bytes": definition["download_bytes"]}
            def publish(**updates):
                state.update(updates, updated_at=time.time())
                atomic_json(staging / "state.json", state)
                if progress:
                    progress(dict(state))
            try:
                if final.exists() and self._verify_files(definition, final):
                    atomic_json(final / "ready.json", {"snapshot_id": snapshot, "verified_at": time.time()})
                    return self.status(snapshot)
                assets = list(self._assets(definition, staging))
                verified = sum(a["size"] for a, p in assets if self._complete(a, p))
                partial_bytes = sum(min(a["size"], p.with_name(p.name + ".partial").stat().st_size)
                                    for a, p in assets if not self._complete(a, p)
                                    and p.with_name(p.name + ".partial").is_file()
                                    and not p.with_name(p.name + ".partial").is_symlink())
                remaining = max(0, definition["download_bytes"] - verified - partial_bytes)
                required = remaining + max(16 * 1024 * 1024, definition["download_bytes"] // 100)
                if self.free_bytes() < required:
                    raise ModelError("insufficient_space", "Not enough space to prepare this model", required_bytes=required)
                publish(downloaded_bytes=verified, required_free_bytes=required)
                for asset, path in assets:
                    if self._complete(asset, path):
                        continue
                    path.parent.mkdir(parents=True, exist_ok=True)
                    def transferred(count):
                        publish(downloaded_bytes=verified + count, asset=asset["path"])
                    self._download(asset, path, transferred)
                    verified += asset["size"]
                    publish(downloaded_bytes=verified)
                publish(state="verifying")
                if not self._verify_files(definition, staging):
                    raise ModelError("checksum_mismatch", "A required model asset failed verification")
                atomic_json(staging / "ready.json", {"snapshot_id": snapshot, "verified_at": time.time()})
                # A ready snapshot is never replaced. Repair only removes an invalid snapshot.
                if final.exists():
                    shutil.rmtree(final)
                os.replace(staging, final)
                descriptor = os.open(final.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                return self.status(snapshot)
            except (OSError, ModelError) as error:
                publish(state="failed", error={"code": getattr(error, "code", "download_failed"),
                                               "message": str(error), **getattr(error, "details", {})})
                raise

    def _verify_files(self, definition, base):
        return all(self._complete(asset, path) for asset, path in self._assets(definition, base))

    def verify(self, identifier):
        definition = self.definition(identifier)
        snapshot = definition["snapshot_id"]
        with self._lock(snapshot):
            base = self.root / "snapshots" / snapshot
            if not self._verify_files(definition, base):
                (base / "ready.json").unlink(missing_ok=True)
                raise ModelError("model_not_ready", "Model assets are missing or damaged; request preparation to repair")
            atomic_json(base / "ready.json", {"snapshot_id": snapshot, "verified_at": time.time()})
        return self.status(snapshot)

    def local_paths(self, identifier):
        # Recheck full integrity at the execution boundary; no downloader is called here.
        status = self.verify(identifier)
        base = self.root / "snapshots" / status["snapshot_id"]
        return {key: str(base / key) for key in status["components"]}

    def remove(self, identifier):
        definition = self.definition(identifier)
        snapshot = definition["snapshot_id"]
        with self._lock(snapshot):
            references = self.references(snapshot)
            if references:
                raise ModelError("model_in_use", "Nonterminal jobs still need this snapshot", job_ids=references)
            for group in ("snapshots", "staging"):
                path = self.root / group / snapshot
                if path.exists():
                    shutil.rmtree(path)
        return self.status(snapshot)

    def _download(self, asset, path, progress):
        partial = path.with_name(path.name + ".partial")
        identity_path = path.with_name(path.name + ".transfer.json")
        identity = {}
        try:
            identity = json.loads(identity_path.read_text())
        except (FileNotFoundError, ValueError):
            pass
        offset = partial.stat().st_size if partial.is_file() and not partial.is_symlink() else 0
        eligible = (0 < offset < asset["size"] and identity.get("sha256") == asset["sha256"]
                    and identity.get("url") == asset["url"] and identity.get("etag")
                    and not identity["etag"].startswith("W/"))
        headers = {"Accept-Encoding": "identity", "User-Agent": "ASR-Desktop/0.1"}
        if eligible:
            headers.update(Range=f"bytes={offset}-", **{"If-Range": identity["etag"]})
        else:
            offset = 0
        try:
            response = self.opener(Request(asset["url"], headers=headers), timeout=30)
        except HTTPError as error:
            if eligible and error.code in (400, 416):
                error.close()
                partial.unlink(missing_ok=True)
                identity_path.unlink(missing_ok=True)
                return self._download(asset, path, progress)
            raise
        with response:
            resumed = (eligible and response.status == 206 and response.headers.get("ETag") == identity["etag"]
                       and response.headers.get("Content-Range") == f"bytes {offset}-{asset['size'] - 1}/{asset['size']}")
            if response.status == 206 and not resumed:
                # An invalid partial response must never be treated as a complete asset.
                partial.unlink(missing_ok=True)
                identity_path.unlink(missing_ok=True)
                if eligible:
                    response.close()
                    return self._download(asset, path, progress)
                raise ModelError("invalid_range", "Remote asset identity or byte range changed; retry from the start")
            if response.status not in (200, 206):
                raise ModelError("download_failed", "Unexpected model response status")
            if not resumed:
                offset = 0
            atomic_json(identity_path, {"sha256": asset["sha256"], "url": asset["url"],
                                        "etag": response.headers.get("ETag")})
            with partial.open("ab" if resumed else "wb") as stream:
                count = offset
                last_update = 0
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    count += len(block)
                    if count > asset["size"]:
                        raise ModelError("checksum_mismatch", "Model response exceeds expected size")
                    stream.write(block)
                    if time.monotonic() - last_update >= 0.25:
                        progress(count)
                        last_update = time.monotonic()
                stream.flush()
                os.fsync(stream.fileno())
        if count < asset["size"]:
            raise OSError("Model transfer ended early; the validated partial transfer can be retried")
        if not self._complete(asset, partial):
            partial.unlink(missing_ok=True)
            raise ModelError("checksum_mismatch", "Downloaded model asset does not match its catalog")
        os.replace(partial, path)
        identity_path.unlink(missing_ok=True)
