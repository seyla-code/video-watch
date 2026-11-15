---
name: video-watch
description: 'Use when asked to watch, summarize, or answer questions about a video file (or a URL that yt-dlp can download): extracts keyframes with ffmpeg, transcribes audio with faster-whisper AND OCRs burned-in captions with RapidOCR as two independent tracks, then emits layered output — a verbatim transcript, a timeline index, and a summary skeleton the agent fills with cited interpretation.'
---

# Watch a video

Video is not a native model input. This skill turns a video into three layers,
deliberately separated so **facts never masquerade as interpretation**:

| Layer | File | Nature |
|---|---|---|
| L0 | `transcript.full.md` | Per-block 音频 / 字幕 / similarity. Nothing rewritten. **Cite from here.** |
| L1 | `timeline.md` | One chronological index of speech + keyframes. |
| L2 | `summary.md` | Skeleton only — the agent writes interpretation here, with timestamps, marking guesses. |

Two text tracks are captured independently, **because they disagree**:

- **audio** — Whisper, what was said
- **subtitles** — RapidOCR on the bottom band, what the captions claim

The disagreement is information. Captions are usually human-proofread and carry
proper nouns, product names, and URLs that ASR mangles (`AI Slop` →
`AISOB AI干水`).

## Setup

```bash
python scripts/setup.py            # installs Python deps, checks ffmpeg
python scripts/fetch_model.py      # optional: prefetch the whisper model
```

Environment (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `FFMPEG_DIR` | `PATH` | folder holding `ffmpeg`/`ffprobe` |
| `WHISPER_DOWNLOAD_ROOT` | `~/.cache/video-watch/models` | where whisper weights live |
| `HF_ENDPOINT` | huggingface.co | set to `https://hf-mirror.com` where the Hub is blocked |
| `WHISPER_MODEL` | `small` | default model size |

## Run

```bash
python scripts/video_watch.py "<video path>" --max-frames 40
```

Output lands in `<video folder>/<stem>_watch/`. `subs.json` and `asr.json` are
cached — reruns skip OCR and transcription; pass `--refresh` to force.

## Reading the result

1. Read `timeline.md` first — the whole video in order, with `⟨相近⟩` / `⟨不同⟩`
   markers where the tracks diverge.
2. Read the `不同` rows of `transcript.full.md` closely — that is where the
   caption carries something the audio lost.
3. View the frames that matter with an image-reading tool.
4. Write `summary.md` yourself: every claim gets a `mm:ss`, every guess gets
   marked as an inference.

## Knobs

| Flag | Default | Meaning |
|---|---|---|
| `--scene` | `0.25` | scene-cut threshold; lower = more cuts |
| `--interval` | `8` | uniform safety net, one frame every N seconds |
| `--max-frames` | `60` | visual frame cap; ~1-1.6k tokens per frame |
| `--sub-fps` | `0.5` | subtitle sampling rate; raise to `1.0` for fast cuts |
| `--crop` | `0.30` | bottom band OCRed as captions; lower to `0.18` when the video also shows screen content |
| `--no-ocr` | off | audio track only |
| `--model` | `small` | whisper size: `tiny`/`base`/`small`/`medium`/`large-v3` |
| `--refresh` | off | ignore `subs.json` / `asr.json` caches |

## Links

`yt-dlp` must be installed separately:

```bash
python -m yt_dlp -f "bestvideo[height<=720]+bestaudio/best[height<=720]" \
  --merge-output-format mp4 -o "%(id)s.%(ext)s" "<url>"
```

## Traps this handles, and the ones it does not

Handled:

- **Persistent overlays are not captions** — a banner present in >50% of sampled
  frames is filtered as furniture.
- **Granularity mismatch** — Whisper splits on sentences, captions on display
  lines; alignment runs block-by-block, assigning each ASR segment to exactly
  one block (assigning by overlap duplicates text across neighbours).
- **Traditional Chinese** — Whisper often emits it; OpenCC `t2s` normalises
  before diffing, else identical sentences score as different.

Not handled (known gaps):

- Dialects. `small` falls apart on anything past mild Mandarin. Use
  `--model large-v3`, or swap in a dialect-aware ASR (SenseVoice / Paraformer).
- Vertical video or captions outside the bottom band — tune `--crop`.
- On-screen text in screen recordings — OCR will read the UI, not only captions.
