"""Explicit service entry points; worker imports remain on the host."""

import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["api", "worker", "scanner", "backup", "cleanup"]
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--database")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.command == "api":
        import uvicorn

        uvicorn.run(
            "asr_service.api:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=1,
        )
    elif args.command == "backup":
        if not args.database or not args.output:
            parser.error("backup requires --database and --output")
        from .store import Store

        Store(args.database).backup(args.output)
    else:
        from . import native

        getattr(native, args.command)()


if __name__ == "__main__":
    main()
