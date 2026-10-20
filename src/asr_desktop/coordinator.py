"""Single-user control service bootstrap; transcription scheduling is separate."""

import ctypes
import errno
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import stat

from .models import ModelError, ModelStore
from .database import StateError
from .workspace import OPERATIONS, Workspace
from .scheduler import Scheduler


PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 65536


def socket_directory():
    return Path(os.environ.get("ASR_DESKTOP_RUN_DIR", f"/private/tmp/asr-desktop-{os.getuid()}"))


def peer_uid(connection):
    library = ctypes.CDLL(None, use_errno=True)
    function = library.getpeereid
    function.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    function.restype = ctypes.c_int
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    if function(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)):
        raise OSError(ctypes.get_errno(), "Cannot verify local peer identity")
    return uid.value


def prepare_directory(root):
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError("Control directory must be an owned private directory, not a symlink")


def read_request(connection):
    data = bytearray()
    while b"\n" not in data:
        block = connection.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(data)))
        if not block:
            raise ValueError("Incomplete request")
        data.extend(block)
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("Request too large")
    line, remainder = bytes(data).split(b"\n", 1)
    if remainder.strip():
        raise ValueError("Only one request per connection is supported")
    request = json.loads(line)
    if not isinstance(request, dict):
        raise ValueError("Request must be an object")
    return request


def serve(root=None):
    root = Path(root) if root else socket_directory()
    prepare_directory(root)
    lock_path = root / "coordinator.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    lock_info = os.fstat(descriptor)
    if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or stat.S_IMODE(lock_info.st_mode) != 0o600:
        os.close(descriptor)
        raise PermissionError("Unsafe coordinator lock")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(descriptor)
        raise RuntimeError("A coordinator already owns this workspace")
    path = root / "control.sock"
    running = True
    termination_requested = False

    def stop(signum, frame):
        nonlocal termination_requested
        termination_requested = True

    previous_handlers = {number:signal.signal(number, stop) for number in (signal.SIGTERM, signal.SIGINT)}
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    data_descriptor = None
    try:
        data_root = Path(os.environ.get("ASR_DESKTOP_DATA_DIR", str(Path.home() / "Library/Application Support/ASR Desktop")))
        data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data_descriptor = os.open(data_root / "coordinator.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(data_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A coordinator already owns this data directory")
        bundle = os.environ.get("ASR_DESKTOP_BUNDLE")
        ffprobe = Path(bundle) / "Contents/Resources/media/ffprobe" if bundle else data_root / "missing-ffprobe"
        workspace = Workspace(data_root, ffprobe)
        scheduler = Scheduler(workspace)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError("Unsafe stale control socket")
            path.unlink()
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(16)
        server.settimeout(0.25)
        while running:
            if termination_requested:
                scheduler.request_stop(force=True)
                termination_requested = False
            scheduler.tick()
            if scheduler.stopping and scheduler.idle:
                break
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(3)
                response = {"protocol_version": PROTOCOL_VERSION, "success": False}
                try:
                    if peer_uid(connection) != os.getuid():
                        raise PermissionError("Local peer belongs to another user")
                    request = read_request(connection)
                    response["id"] = request.get("id")
                    if request.get("protocol_version") != PROTOCOL_VERSION:
                        response["error"] = {"code": "protocol_mismatch", "message": "Use the same App and CLI version."}
                    elif request.get("operation") == "service.status":
                        response.update(success=True, result={"state": "stopping" if scheduler.stopping else "running", "pid": os.getpid(),
                                        "uid": os.getuid(), "execution_ready": True,
                                        "service_mode": os.environ.get("ASR_DESKTOP_SERVICE_MODE", "managed"),
                                        "capabilities": ["service.status", "service.stop", *OPERATIONS]})
                    elif request.get("operation") == "service.stop":
                        arguments = request.get("arguments", {})
                        if not isinstance(arguments, dict) or type(arguments.get("force", False)) is not bool:
                            raise ValueError("force must be a boolean")
                        scheduler.request_stop(force=arguments.get("force", False))
                        response.update(success=True, result={"state": "stopping"})
                    else:
                        response.update(success=True, result=workspace.dispatch(request))
                except (ModelError, StateError) as error:
                    response["error"] = {"code": error.code, "message": str(error), **error.details}
                except (ValueError, OSError) as error:
                    response["error"] = {"code": "invalid_request", "message": str(error)}
                try:
                    connection.sendall(json.dumps(response, ensure_ascii=False).encode() + b"\n")
                except OSError:
                    pass
    finally:
        server.close()
        if path.exists() and stat.S_ISSOCK(path.lstat().st_mode):
            path.unlink()
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
        os.close(descriptor)
        if "workspace" in locals():
            workspace.database.close()
        if data_descriptor is not None:
            os.close(data_descriptor)


if __name__ == "__main__":
    serve()
