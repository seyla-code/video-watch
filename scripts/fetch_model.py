"""Prefetch a faster-whisper model so the first run is not blocked on download.

Usage:
    python scripts/fetch_model.py                 # small, default cache
    python scripts/fetch_model.py large-v3
    python scripts/fetch_model.py small --endpoint https://hf-mirror.com
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("size", nargs="?", default=os.environ.get("WHISPER_MODEL", "small"))
    ap.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT"),
                    help="e.g. https://hf-mirror.com when huggingface.co is unreachable")
    ap.add_argument("--root",
                    default=os.environ.get("WHISPER_DOWNLOAD_ROOT")
                    or str(Path.home() / ".cache" / "video-watch" / "models"))
    args = ap.parse_args()

    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint

    from faster_whisper import WhisperModel

    started = time.time()
    WhisperModel(args.size, device="cpu", compute_type="int8", download_root=args.root)
    print(f"{args.size} ready in {time.time() - started:.1f}s -> {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
