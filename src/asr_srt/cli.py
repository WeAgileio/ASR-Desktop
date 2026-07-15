import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import JobConfig, SUPPORTED_DEVICES, SUPPORTED_MODELS, default_cache_dir
from .diagnostics import collect_diagnostics
from .domain import SubtitleSettings
from .errors import AsrSrtError, ValidationError
from .progress_render import create_progress_renderer
from .workflow import LocalTranscriptionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asr-srt", description="Generate a local SRT file from a video using FunASR."
    )
    parser.add_argument("input", nargs="?", type=Path, help="source video path")
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default="fun-asr-nano")
    parser.add_argument("--device", choices=SUPPORTED_DEVICES, default="auto")
    parser.add_argument("--hotword", action="append", default=[], help="repeat or comma-separate")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir())
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--traditional", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-units", type=int, default=22)
    parser.add_argument("--max-duration", type=float, default=6.0, metavar="SECONDS")
    parser.add_argument("--min-duration", type=float, default=1.0, metavar="SECONDS")
    parser.add_argument("--silence-gap", type=float, default=0.65, metavar="SECONDS")
    parser.add_argument("--diagnose", action="store_true", help="print environment diagnostics")
    parser.add_argument(
        "--progress", choices=("auto", "rich", "plain", "off"), default="auto",
        help="progress display mode (default: auto)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None, service=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.diagnose:
        print(collect_diagnostics(args.cache_dir).to_text())
        if args.input is None:
            return 0
    if args.input is None:
        parser.error("the following arguments are required: input (unless --diagnose is used)")
    renderer = create_progress_renderer(args.progress, sys.stderr)
    try:
        settings = SubtitleSettings(
            max_display_units=args.max_units,
            max_duration_ms=round(args.max_duration * 1000),
            target_min_duration_ms=round(args.min_duration * 1000),
            silence_gap_ms=round(args.silence_gap * 1000),
        )
        config = JobConfig(
            input_path=args.input,
            model=args.model,
            device=args.device,
            hotwords=tuple(args.hotword),
            output_path=args.output,
            cache_dir=args.cache_dir,
            use_cache=not args.no_cache,
            overwrite=args.overwrite,
            traditional=args.traditional,
            subtitle=settings,
        )
        runner = service or LocalTranscriptionService(progress=renderer)
        result = runner.run(config)
    except (AsrSrtError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        renderer.close()
    print(f"SRT: {result.output_path}")
    print(f"Transcript: {result.transcript_path}")
    print(f"Cache: {'hit' if result.cache_hit else 'miss'}")
    return 0
