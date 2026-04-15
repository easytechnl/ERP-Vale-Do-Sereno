from __future__ import annotations

import argparse
import sys
from multiprocessing import freeze_support

SUPPORTED_PYTHON = ((3, 12), (3, 13))


def _ensure_supported_python() -> None:
    version = sys.version_info[:2]
    if SUPPORTED_PYTHON[0] <= version <= SUPPORTED_PYTHON[1]:
        return
    raise SystemExit(
        "Python 3.12 or 3.13 is required for this project. "
        "Recreate the virtual environment with `py -3.12 -m venv .venv` "
        "and reinstall `requirements.txt`."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ERP API in development mode.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="TCP port (default: 8000)")
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload watcher",
    )
    return parser


def main() -> None:
    _ensure_supported_python()
    import uvicorn

    args = _build_parser().parse_args()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )


if __name__ == "__main__":
    # Required on Windows when reload uses spawn-based child processes.
    freeze_support()
    main()
