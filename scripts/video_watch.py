"""video-watch: turn a video file into layered, citable text for the agent.

Three layers, deliberately separated so facts never masquerade as interpretation:

  transcript.full.md  L0  per-segment rows: audio track, subtitle track, diff.
                          Nothing rewritten. The citable source of truth.
  timeline.md         L1  one chronological index of speech + keyframes.
  summary.md          L2  skeleton only; the agent writes interpretation here
                          and must cite L0.

Two independent text tracks:
  audio   faster-whisper  -> what was said
  subtitle OCR (RapidOCR) -> what the burned-in captions claim
They disagree often (editing, censorship, simplification), and the disagreement
is itself the information. The subtitle track also corrects ASR errors.

Requires: ffmpeg, ffprobe (FFMPEG_DIR), faster-whisper + rapidocr_onnxruntime (PYTHONPATH).

Usage:
  python video_watch.py <video> [--model small] [--out DIR] [--max-frames 60]
                        [--scene 0.25] [--interval 8] [--sub-fps 1.0]
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ffmpeg/ffprobe come from FFMPEG_DIR, then PATH
WATERMARKS = ("bilibili", "哔哩哔哩")


def ffmpeg_bin(name: str) -> str:
    """Resolve ffmpeg/ffprobe: FFMPEG_DIR wins, then PATH."""
    env_dir = os.environ.get("FFMPEG_DIR")
    if env_dir:
        for candidate in (Path(env_dir) / (name + ".exe"), Path(env_dir) / name):
            if candidate.exists():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    sys.exit(f"missing {name}: install ffmpeg, or set FFMPEG_DIR to the folder holding it")


def run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit("command failed:\n  " + " ".join(cmd) + "\n" + (r.stderr or "")[-2000:])
    return r.stdout


def probe(video: Path) -> dict:
    out = run([
        ffmpeg_bin("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video),
    ])
    info = json.loads(out)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": float(info["format"].get("duration") or 0),
        "video": v,
        "audio": a,
        "fps": (v or {}).get("avg_frame_rate", ""),
    }


# ---------------------------------------------------------------- visual frames

def _frame_pass(video: Path, out_dir: Path, vf: str, extra: list[str]) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([
        ffmpeg_bin("ffmpeg"), "-hide_banner", "-loglevel", "info", "-i", str(video),
        "-vf", vf, *extra, str(out_dir / "%05d.jpg"),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit("frame pass failed:\n" + (r.stderr or "")[-2000:])
    return r.stderr or ""


def extract_frames(video: Path, out: Path, scene: float, interval: float, max_frames: int) -> list[dict]:
    picks: list[dict] = []

    scene_dir = out / "_scene"
    log = _frame_pass(video, scene_dir, f"select='gt(scene,{scene})',showinfo,scale=960:-2",
                      ["-vsync", "vfr", "-q:v", "4"])
    scene_times = [float(m) for m in re.findall(r"pts_time:([0-9]+\.?[0-9]*)", log)]
    for t, f in zip(scene_times, sorted(scene_dir.glob("*.jpg"))):
        picks.append({"t": t, "path": str(f)})

    interval_dir = out / "_interval"
    _frame_pass(video, interval_dir, f"fps=1/{interval},scale=960:-2", ["-q:v", "5"])
    for i, f in enumerate(sorted(interval_dir.glob("*.jpg"))):
        picks.append({"t": i * interval, "path": str(f)})

    picks.sort(key=lambda p: p["t"])
    kept: list[dict] = []
    for p in picks:
        if any(abs(p["t"] - k["t"]) < 1.5 for k in kept):
            continue
        kept.append(p)
    if len(kept) > max_frames:
        step = len(kept) / max_frames
        kept = [kept[int(i * step)] for i in range(max_frames)]

    final = out / "frames"
    final.mkdir(parents=True, exist_ok=True)
    result: list[dict] = []
    for idx, p in enumerate(kept):
        src = Path(p["path"])
        dst = final / f"{idx:03d}_t{p['t']:08.2f}.jpg"
        shutil.copy2(src, dst)
        result.append({"t": round(p["t"], 2), "path": str(dst)})
    shutil.rmtree(scene_dir, ignore_errors=True)
    shutil.rmtree(interval_dir, ignore_errors=True)
    return result


# ---------------------------------------------------------------------- audio

def load_wav_pcm(wav: Path):
    """Read 16 kHz mono PCM straight from ffmpeg's output.

    faster-whisper 1.2.1 calls av.open(metadata_errors=...), which PyAV 19 no
    longer accepts and older PyAV has no cp312 wheel for, so the model is fed a
    numpy array instead of a path.
    """
    import wave

    import numpy as np

    with wave.open(str(wav), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            sys.exit("expected 16-bit mono wav from ffmpeg")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(video: Path, out: Path, model_name: str, download_root: str) -> list[dict]:
    from faster_whisper import WhisperModel

    wav = out / "audio.wav"
    run([ffmpeg_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(wav)])

    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         download_root=download_root)
    segments, _ = model.transcribe(load_wav_pcm(wav), vad_filter=True, beam_size=1)
    return [{"start": round(s.start, 2), "end": round(s.end, 2),
             "text": s.text.strip()}
            for s in segments if s.text.strip()]


# ------------------------------------------------------------------ subtitles

def _norm(s: str) -> str:
    return re.sub(r"[\s\u3000，。！？、,.!?…—·\"'“”‘’()（）\[\]【】:：;；]", "", s)


_CC = None


def _simp(s: str) -> str:
    """Whisper often emits traditional Chinese; normalise so both tracks compare."""
    global _CC
    if _CC is None:
        try:
            from opencc import OpenCC

            _CC = OpenCC("t2s")
        except Exception:
            _CC = False
    return _CC.convert(s) if _CC else s


def _similar(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    # A fragment contained in the other track is agreement, not disagreement:
    # ASR splits by sentence, captions split by display line.
    if min(len(na), len(nb)) >= 3 and (na in nb or nb in na):
        return max(0.85, min(len(na), len(nb)) / max(len(na), len(nb)))
    return difflib.SequenceMatcher(None, na, nb).ratio()


def ocr_subtitles(video: Path, out: Path, sub_fps: float, crop: float, min_score: float) -> list[dict]:
    """OCR the bottom band of the frame at sub_fps, collapse repeats into blocks."""
    sub_dir = out / "_subs"
    sub_dir.mkdir(parents=True, exist_ok=True)
    vf = f"fps={sub_fps},crop=iw:ih*{crop}:0:ih*{1 - crop},scale=960:-2"
    subprocess.run([
        ffmpeg_bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", vf, str(sub_dir / "%05d.png"),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")

    images = sorted(sub_dir.glob("*.png"))
    if not images:
        return []

    from concurrent.futures import ThreadPoolExecutor
    from collections import Counter

    from rapidocr_onnxruntime import RapidOCR

    try:
        engine = RapidOCR(use_cls=False)  # captions are never rotated
    except TypeError:
        engine = RapidOCR()

    def ocr_one(img: Path) -> list[str]:
        res, _ = engine(str(img))
        lines: list[tuple[float, str]] = []
        for box, text, score in (res or []):
            if score < min_score:
                continue
            t = text.strip()
            if not t or any(w in t.lower() for w in WATERMARKS):
                continue
            lines.append((min(p[1] for p in box), t))
        lines.sort(key=lambda x: x[0])
        return [t for _, t in lines]

    # onnxruntime releases the GIL during inference, so threads scale here.
    with ThreadPoolExecutor(max_workers=4) as pool:
        per_frame = list(pool.map(ocr_one, images))

    # A caption is transient; a logo/banner/checklist overlay persists. Anything
    # present in more than half the sampled frames is furniture, not speech.
    seen = Counter()
    for lines in per_frame:
        for t in set(lines):
            seen[t] += 1
    furniture = {t for t, c in seen.items() if c > 0.5 * len(images)}

    samples: list[tuple[float, str]] = []
    for i, lines in enumerate(per_frame):
        kept = [t for t in lines if t not in furniture]
        samples.append((i / sub_fps, " ".join(kept)))

    # Collapse consecutive near-identical captions into one block.
    blocks: list[dict] = []
    for t, text in samples:
        if not text:
            continue
        if blocks and _similar(blocks[-1]["text"], text) > 0.75:
            blocks[-1]["end"] = round(t + 1 / sub_fps, 2)
            continue
        blocks.append({"start": round(t, 2), "end": round(t + 1 / sub_fps, 2), "text": text})
    shutil.rmtree(sub_dir, ignore_errors=True)
    return blocks


# ----------------------------------------------------------------- alignment

def align(segments: list[dict], subs: list[dict]) -> list[dict]:
    """Align on the subtitle block, the finer-grained of the two tracks.

    Whisper splits on sentences and captions split on display lines, so each
    block absorbs every ASR segment that overlaps it; comparing on one block's
    window keeps the two sides the same unit. ASR left over with no caption
    stays in the transcript, flagged as uncaptioned.
    """
    rows: list[dict] = []
    assigned: dict[int, list[dict]] = {i: [] for i in range(len(subs))}
    loose: list[dict] = []
    for seg in segments:
        best_i, best_overlap = -1, 0.0
        for i, blk in enumerate(subs):
            overlap = min(seg["end"], blk["end"]) - max(seg["start"], blk["start"])
            if overlap > best_overlap:
                best_overlap, best_i = overlap, i
        if best_i >= 0:
            assigned[best_i].append(seg)
        else:
            loose.append(seg)

    for i, blk in enumerate(subs):
        asr = _simp(" ".join(s["text"] for s in assigned[i]).strip())
        ratio = _similar(asr, blk["text"]) if asr else None
        if ratio is None:
            verdict = "无音频"
        elif ratio >= 0.85:
            verdict = "一致"
        elif ratio >= 0.5:
            verdict = "相近"
        else:
            verdict = "不同"
        rows.append({"start": blk["start"], "end": blk["end"], "text": asr,
                     "sub": blk["text"], "ratio": ratio, "verdict": verdict})

    for seg in loose:
        rows.append({"start": seg["start"], "end": seg["end"], "text": _simp(seg["text"]),
                     "sub": "", "ratio": None, "verdict": "无字幕"})

    rows.sort(key=lambda r: r["start"])
    return rows


def hhmmss(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# --------------------------------------------------------------------- output

def write_layers(video: Path, out: Path, info: dict, frames: list[dict],
                 rows: list[dict], subs: list[dict]) -> None:
    counts = {"一致": 0, "相近": 0, "不同": 0, "无字幕": 0}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    # L0 -- the citable source of truth.
    l0 = [
        f"# {video.name} — 逐句对照（L0：事实层，未改写）",
        "",
        f"- 时长：{hhmmss(info['duration'])}（{info['duration']:.1f}s）",
        f"- 音频轨：{(info['audio'] or {}).get('codec_name')} "
        f"{(info['audio'] or {}).get('sample_rate')} Hz",
        f"- 字幕轨：OCR 得到 {len(subs)} 个字幕块",
        f"- 比对：一致 {counts['一致']} / 相近 {counts['相近']} / "
        f"不同 {counts['不同']} / 无字幕 {counts['无字幕']}",
        "",
        "> 本文件只记录两路原文与差异，不做解释。解释见 summary.md。",
        "",
    ]
    for r in rows:
        l0.append(f"### `{hhmmss(r['start'])}` — {r['verdict']}")
        l0.append(f"- **音频**：{r['text']}")
        if r["sub"]:
            l0.append(f"- **字幕**：{r['sub']}")
            if r["ratio"] is not None:
                l0.append(f"- **相似度**：{r['ratio']:.2f}")
        l0.append("")
    (out / "transcript.full.md").write_text("\n".join(l0), encoding="utf-8")

    # L1 -- chronological index.
    events = [{"t": r["start"], "kind": "speech", "row": r} for r in rows]
    events += [{"t": f["t"], "kind": "frame", "path": f["path"]} for f in frames]
    events.sort(key=lambda e: e["t"])
    l1 = [
        f"# {video.name} — 时间轴（L1：索引）",
        "",
        f"- 时长：{hhmmss(info['duration'])}",
        f"- 关键帧：{len(frames)}",
        f"- 台词段：{len(rows)}",
        "",
    ]
    for e in events:
        if e["kind"] == "speech":
            row = e["row"]
            mark = "" if row["verdict"] == "一致" else f"  ⟨{row['verdict']}⟩"
            l1.append(f"- `{hhmmss(e['t'])}` [说] {row['text']}{mark}")
        else:
            l1.append(f"- `{hhmmss(e['t'])}` [画面] {Path(e['path']).name}")
    (out / "timeline.md").write_text("\n".join(l1) + "\n", encoding="utf-8")

    # L2 -- interpretation, filled in by the agent.
    if not (out / "summary.md").exists():
        (out / "summary.md").write_text(
            f"# {video.name} — 解读（L2：观点层）\n\n"
            "> 规则：每条论断都要给出 L0 的时间戳引证；推断必须标注「（推断）」。\n"
            "> 原文看 transcript.full.md，索引看 timeline.md。\n",
            encoding="utf-8",
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default=os.environ.get("WHISPER_MODEL", "small"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-frames", type=int, default=60)
    ap.add_argument("--scene", type=float, default=0.25)
    ap.add_argument("--interval", type=float, default=8.0)
    ap.add_argument("--sub-fps", type=float, default=0.5)
    ap.add_argument("--crop", type=float, default=0.30)
    ap.add_argument("--min-score", type=float, default=0.5)
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        sys.exit(f"no such file: {video}")
    out = Path(args.out or (video.parent / (video.stem + "_watch"))).resolve()
    out.mkdir(parents=True, exist_ok=True)

    info = probe(video)
    frames = extract_frames(video, out, args.scene, args.interval, args.max_frames)

    download_root = os.environ.get("WHISPER_DOWNLOAD_ROOT") or str(
        Path.home() / ".cache" / "video-watch" / "models")
    rows: list[dict] = []
    subs: list[dict] = []
    if info["audio"]:
        subs_cache = out / "subs.json"
        asr_cache = out / "asr.json"
        if subs_cache.exists() and not args.refresh:
            subs = json.loads(subs_cache.read_text(encoding="utf-8"))
        elif not args.no_ocr:
            subs = ocr_subtitles(video, out, args.sub_fps, args.crop, args.min_score)
            subs_cache.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")

        if asr_cache.exists() and not args.refresh:
            segments = json.loads(asr_cache.read_text(encoding="utf-8"))
        else:
            segments = transcribe(video, out, args.model, download_root)
            asr_cache.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = align(segments, subs)

    write_layers(video, out, info, frames, rows, subs)
    (out / "frames.json").write_text(json.dumps(frames, indent=2), encoding="utf-8")

    verdicts = {}
    for r in rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    print(f"out={out}")
    print(f"frames={len(frames)} segments={len(rows)} subtitles={len(subs)} "
          f"duration={info['duration']:.1f}s {verdicts}")


if __name__ == "__main__":
    main()
