"""Install the Python dependencies and check for ffmpeg.

Usage:
    python scripts/setup.py
    python scripts/setup.py --with-yt-dlp
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

REQUIRED = [
    "faster-whisper>=1.0",
    "rapidocr-onnxruntime>=1.3",
    "opencc-python-reimplemented>=0.1.7",
]
OPTIONAL = ["yt-dlp"]


def check_ffmpeg() -> bool:
    ok = True
    for name in ("ffmpeg", "ffprobe"):
        found = shutil.which(name)
        print(f"  {name:8s} {'OK  ' + found if found else 'MISSING'}")
        ok = ok and bool(found)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-yt-dlp", action="store_true", help="also install yt-dlp for URL downloads")
    args = ap.parse_args()

    print(f"python {sys.version.split()[0]}")
    if sys.version_info < (3, 9):
        print("need Python 3.9+")
        return 1

    print("\nffmpeg:")
    has_ffmpeg = check_ffmpeg()
    if not has_ffmpeg:
        print("  -> install ffmpeg (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg)")
        print("     or set FFMPEG_DIR to the folder containing the binaries")

    pkgs = REQUIRED + (OPTIONAL if args.with_yt_dlp else [])
    print(f"\ninstalling: {' '.join(pkgs)}")
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])
    if rc != 0:
        print("\npip failed. On Windows inside a restricted sandbox, pip can fail with")
        print("EACCES inside its temp dir; point TEMP at a normal writable folder and retry.")
        return rc

    print("\ndone.")
    if not has_ffmpeg:
        print("remember to install ffmpeg before running video_watch.py")
    print("next:  python scripts/fetch_model.py     # optional, prefetches whisper")
    print("       python scripts/video_watch.py <video>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
