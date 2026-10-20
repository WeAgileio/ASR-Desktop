#!/usr/bin/env python3
"""Build pinned local-file FFmpeg/ffprobe without Homebrew library dependencies."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "desktop" / "media-build"


def main():
    manifest = json.loads((ROOT / "desktop/requirements/media.json").read_text())
    BUILD.mkdir(parents=True, exist_ok=True)
    archive = BUILD / ("ffmpeg-" + manifest["version"] + ".tar.xz")
    if not archive.exists():
        partial = archive.with_suffix(".download")
        with urllib.request.urlopen(manifest["url"], timeout=60) as source, partial.open("wb") as target:
            shutil.copyfileobj(source, target)
        partial.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise SystemExit("FFmpeg source checksum mismatch; remove the rejected archive and retry.")
    source = BUILD / ("ffmpeg-" + manifest["version"])
    if not source.exists():
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                destination = (BUILD / member.name).resolve()
                if BUILD.resolve() not in destination.parents or member.issym() or member.islnk():
                    raise SystemExit("Unsafe FFmpeg source archive entry")
            stream.extractall(BUILD)
    # FFmpeg only supports whitespace in a source path for in-tree builds.
    # Invoke ./configure from that tree rather than passing its absolute path.
    objects = source
    decoders = ["aac", "aac_fixed", "mp3", "mp3float", "flac", "alac", "opus", "vorbis",
                "wavpack", "wmav1", "wmav2", "pcm_s16le", "pcm_s24le", "pcm_s32le",
                "pcm_s16be", "pcm_s24be", "pcm_s32be", "pcm_f32le", "pcm_f64le", "pcm_u8"]
    config = [
        "./configure", "--disable-autodetect", "--disable-everything",
        "--disable-network", "--disable-shared", "--enable-static", "--disable-doc", "--disable-debug",
        "--enable-ffmpeg", "--enable-ffprobe", "--disable-ffplay", "--disable-avdevice",
        "--disable-videotoolbox", "--disable-audiotoolbox", "--arch=arm64", "--target-os=darwin",
        "--cc=/usr/bin/clang", "--extra-cflags=-mmacosx-version-min=14.0",
        "--extra-ldflags=-mmacosx-version-min=14.0", "--enable-protocol=file,pipe",
        "--enable-demuxer=mov,matroska,mp3,wav,flac,ogg,aac,aiff,asf",
        "--enable-decoder=" + ",".join(decoders), "--enable-parser=aac,mpegaudio,flac,opus,vorbis",
        "--enable-muxer=wav,null", "--enable-encoder=pcm_s16le",
        "--enable-filter=aresample,aformat,anull,atrim,asetpts,silencedetect,volumedetect",
    ]
    environment = os.environ.copy()
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    environment["MACOSX_DEPLOYMENT_TARGET"] = "14.0"
    subprocess.run(config, cwd=objects, env=environment, check=True)
    subprocess.run(["/usr/bin/make", "-j", str(min(os.cpu_count() or 2, 6)), "ffmpeg", "ffprobe"],
                   cwd=objects, env=environment, check=True)
    output = ROOT / "build/desktop/media"
    output.mkdir(exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        binary = output / name
        shutil.copy2(objects / name, binary)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(binary)], check=True)
        subprocess.run([str(binary), "-version"], env={"PATH": "/usr/bin:/bin"}, check=True)
        libraries = subprocess.check_output(["/usr/bin/otool", "-L", str(binary)], text=True)
        for line in libraries.splitlines()[1:]:
            dependency = line.strip().split(" (", 1)[0]
            if not dependency.startswith(("/usr/lib/", "/System/Library/")):
                raise SystemExit("Unbundled media dependency: " + dependency)
    for name in ("COPYING.LGPLv2.1", "COPYING.LGPLv3", "LICENSE.md"):
        shutil.copy2(source / name, output / name)
    shutil.copy2(ROOT / "desktop/requirements/media.json", output / "source.json")
    (output / "configure-arguments.json").write_text(json.dumps(config[1:], indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
