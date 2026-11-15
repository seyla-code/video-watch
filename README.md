# video-watch

让 AI 助手"看"视频的一个技能包。

视频不是模型的原生输入，所以这个工具把它拆成两样 AI 真正能读的东西：**关键帧**和**带时间戳的文字**，再合成一条可引用的时间轴。

## 它和"直接调用一个视频模型"有什么不同

核心设计只有一条：**两路文本互相独立，再对齐比对**。

```
              ┌─ 音频 → faster-whisper ──┐
视频 ─ ffmpeg ─┤                          ├─ 按秒对齐 → 三层输出
              └─ 字幕 → RapidOCR（OCR）──┘
```

- **音频轨**说的是什么
- **字幕轨**写的是什么（通常是人工校对过的）

两者经常不一致，而**不一致本身就是信息**：字幕里常有人名、术语、URL，ASR 一律听错。

实测例子：某支视频里音频被识别成 `叫AISOB AI干水`，而字幕写的是 `叫 AI Slop` —— 全片的核心概念，只有字幕轨捞了回来。

## 输出分三层

| 层 | 文件 | 性质 |
|---|---|---|
| L0 | `transcript.full.md` | 逐句「音频 / 字幕 / 相似度」，一个字不改。**引用从这里引** |
| L1 | `timeline.md` | 全片顺序索引，分歧处打标记 |
| L2 | `summary.md` | 由 AI 填写，每条论断必须带时间戳，猜测必须标注 |

这么分层是为了让**事实和观点不混在一起**：同一句话不同人理解不同，所以原文必须原样保留、可回查。

## 快速开始

```bash
# 1. 依赖（会自动检查 ffmpeg）
python scripts/setup.py

# 2. 可选：先把 whisper 模型下好
python scripts/fetch_model.py

# 3. 跑
python scripts/video_watch.py "path/to/video.mp4"
# 或者先下载
python -m yt_dlp -f "bestvideo[height<=720]+bestaudio/best" -o "%(id)s.%(ext)s" "<url>"
```

需要 **Python 3.9+** 和 **ffmpeg / ffprobe**（`ffmpeg` 不在 PATH 时用环境变量 `FFMPEG_DIR` 指过去）。

产物落在视频同目录的 `<文件名>_watch/`：

```
xxx_watch/
├─ transcript.full.md   # L0
├─ timeline.md          # L1
├─ summary.md           # L2（空模板，交给 AI 写）
├─ frames/              # 关键帧，文件名带秒数
├─ subs.json            # OCR 缓存
└─ asr.json             # 转写缓存
```

## 怎么让 AI 用上

这个仓库本质上是一个 **skill**：`SKILL.md` 是写给 AI 看的说明书，`scripts/` 是它要调的工具。

把整个目录放到你的 AI 客户端的技能目录里即可：

| 客户端 | 放到 |
|---|---|
| DeepSeek Harness | `~/.agents/skills/video-watch/` |
| Claude Code | `~/.claude/skills/video-watch/` |
| 其他（Codex / Cursor / 自建 agent） | 直接让 agent 读 `SKILL.md`，它就知道怎么调脚本 |

放好之后，新开对话时技能会自动加载，你说"看这个视频"它就会走这条路。

## 可调参数

| 参数 | 默认 | 作用 |
|---|---|---|
| `--max-frames` | 60 | 画面帧上限。每帧约 1~1.6k token，这是主要的成本项 |
| `--sub-fps` | 0.5 | 字幕采样率，快节奏视频可提到 1.0 |
| `--crop` | 0.30 | 取画面底部多少比例当字幕区；画面本身有大量文字时调到 0.18 |
| `--scene` | 0.25 | 场景切换阈值 |
| `--interval` | 8 | 固定间隔抽帧的间隔（秒） |
| `--model` | small | whisper 尺寸，中文建议 `small` 以上 |
| `--refresh` | 关 | 忽略缓存重算 |

## 已知局限（诚实版）

- **方言**：`small` 对强方言基本无效（粤语勉强、川渝/潮汕/温州不行）。要么 `--model large-v3`，要么换 SenseVoice / Paraformer 这类中文专用 ASR。
- **画面里本来就有大量文字**（录屏、PPT）：OCR 会把界面文字也读进来。用 `--crop` 收窄。
- **竖屏视频 / 字幕不在底部**：需要调 `--crop`，目前没有自动检测。
- **成本和时长成正比**：10 分钟视频约 40 帧 + 一轮 CPU 转写，慢的机器上要几分钟。

## 致谢与依赖

ffmpeg（GPL/LGPL）、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[RapidOCR](https://github.com/RapidAI/RapidOCR)、[OpenCC](https://github.com/BYVoid/OpenCC)、[yt-dlp](https://github.com/yt-dlp/yt-dlp)。

## License

MIT
