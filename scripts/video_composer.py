#!/usr/bin/env python3
"""listen-book 视频合成器 —— 讲书音频 → 实景动态视频

设计原则（效果先行，2026-08-07 用户确认）：
- 实景写实照片（Unsplash 免费图库），不用 AI 生图
- 同主题连贯画面（如沙漠星空系列），避免场景跳跃
- 交叉溶解过渡（xfade 1.5s），画面平滑流动
- 文字只保留金句 + 书名，淡入淡出
- Ken Burns 缓慢缩放（zoompan），动态不呆板

用法:
    python video_composer.py --script 讲书稿.txt --audio 音频.mp3 --output out.mp4
    python video_composer.py --script 讲书稿.txt --audio 音频.mp3 --theme desert --output out.mp4

主题（--theme）:
    desert    沙漠星空（暖橙→蓝调→夜空，昼夜渐变）
    forest    森林（绿→深绿，静谧）
    ocean     海洋（蓝→深蓝，辽阔）
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
os.chdir(Path(__file__).parent)
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

W, H = 1080, 1920          # 竖版 9:16
FPS = 25
XFADE_DUR = 1.5             # 交叉溶解时长
FONT_BOLD = str(Path(__file__).parent.parent / "assets" / "fonts" / "msyhbd.ttc")
FONT_REG = str(Path(__file__).parent.parent / "assets" / "fonts" / "msyh.ttc")

# 主题 → 实景图 URL（Unsplash 免费图库，同主题相近画面）
THEMES = {
    "desert": [  # 沙漠星空：黄昏→蓝调→夜空 昼夜渐变
        "https://images.unsplash.com/photo-1542401886-65d6c61db217?w=2160&q=80",
        "https://images.unsplash.com/photo-1509395176047-4a66953fd231?w=2160&q=80",
        "https://images.unsplash.com/photo-1547234935-80c7145ec969?w=2160&q=80",
        "https://images.unsplash.com/photo-1473580044384-7ba9967e16a0?w=2160&q=80",
        "https://images.unsplash.com/photo-1419833173245-f59e1b93f9ee?w=2160&q=80",
        "https://images.unsplash.com/photo-1502134249126-9f3755a50d78?w=2160&q=80",
    ],
    "forest": [
        "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=2160&q=80",
        "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?w=2160&q=80",
        "https://images.unsplash.com/photo-1425913397330-cf8af2ff40a1?w=2160&q=80",
        "https://images.unsplash.com/photo-1448375240586-882707db888b?w=2160&q=80",
    ],
    "ocean": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=2160&q=80",
        "https://images.unsplash.com/photo-1518837695005-2083093ee35b?w=2160&q=80",
        "https://images.unsplash.com/photo-1439405326854-014607f694d7?w=2160&q=80",
        "https://images.unsplash.com/photo-1505142468610-359e7d316be0?w=2160&q=80",
    ],
}


def download_images(theme: str, tmpdir: Path) -> list[Path]:
    """下载主题实景图，竖版裁剪"""
    urls = THEMES.get(theme, THEMES["desert"])
    paths = []
    for i, url in enumerate(urls):
        raw = tmpdir / f"raw_{i}.jpg"
        v = tmpdir / f"img_{i}.jpg"
        try:
            subprocess.run(["curl", "-sL", "-o", str(raw), url],
                           check=True, timeout=60, capture_output=True)
            if HAS_PIL and raw.stat().st_size > 10000:
                from PIL import Image as _Img
                im = _Img.open(raw).convert("RGB")
                w, h = im.size
                target_ratio = H / W
                cur_ratio = h / w
                if cur_ratio > target_ratio:
                    new_h = int(w * target_ratio)
                    top = (h - new_h) // 2
                    im = im.crop((0, top, w, top + new_h))
                else:
                    new_w = int(h / target_ratio)
                    left = (w - new_w) // 2
                    im = im.crop((left, 0, left + new_w, h))
                im = im.resize((W, H), _Img.LANCZOS)
                im.save(v, quality=92)
                paths.append(v)
        except Exception:
            continue
    return paths


def extract_quotes(script_text: str) -> list[str]:
    """从讲书稿提取金句（【金句】标记，优先取引号内本体）"""
    quotes = []
    for m in re.finditer(r"【金句】\s*([^【】\n]{8,120})", script_text):
        q = m.group(1).strip()
        # 优先取「」引号内的内容（金句本体）
        inner = re.findall(r"「([^「」]{6,80})」", q)
        if inner:
            q = inner[-1]  # 取最后一个引号内容
        q = q.strip().strip("「」\"")
        q = re.split(r"[。！？]", q)[0].strip()
        if 6 <= len(q) <= 40 and q not in quotes:
            quotes.append(q)
    return quotes[:4]  # 最多4句


def make_filter(images: list[Path], audio_dur: float, quotes: list[str],
                book_title: str, author: str = "") -> str:
    """构建 ffmpeg filter_complex：Ken Burns + xfade + 金句文字"""
    n = len(images)
    seg_dur = audio_dur / n
    parts = []
    # 每张图 Ken Burns 缩放
    for i in range(n):
        zoom_in = (i % 2 == 0)
        zexpr = f"min(zoom+0.0015,1.15)" if zoom_in else f"max(1.15-zoom*0.0015,1.0)"
        parts.append(
            f"[{i}:v]scale=2160:3840,zoompan=z='{zexpr}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={int(seg_dur*FPS)}:s={W}x{H}:fps={FPS},"
            f"trim=duration={seg_dur+XFADE_DUR},setpts=PTS-STARTPTS[v{i}]"
        )
    # xfade 交叉溶解
    prev = "v0"
    total = seg_dur
    for i in range(1, n):
        out = f"x{i}"
        offset = total - XFADE_DUR
        parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}[{out}]")
        prev = out
        total += seg_dur - XFADE_DUR

    # 文字层（书名开头 + 金句）
    text_filters = []
    if book_title:
        text_filters.append(
            f"drawtext=fontfile={FONT_BOLD}:text='{book_title}':fontsize=70:fontcolor=white:"
            f"borderw=4:bordercolor=black@0.6:x=(w-text_w)/2:y=180:"
            f"alpha='if(lt(t,1),0,if(lt(t,2),(t-1),if(lt(t,6),1,if(lt(t,7),(7-t),0))))'"
        )
    # 金句平均分布在视频后半段
    if quotes:
        quote_zone_start = total * 0.3
        quote_zone = total * 0.65
        for qi, q in enumerate(quotes):
            # 金句断行（14字/行）
            lines = []
            cur = ""
            for ch in q:
                cur += ch
                if len(cur) >= 14:
                    lines.append(cur)
                    cur = ""
            if cur:
                lines.append(cur)
            lines = lines[:2]
            # 时间窗口
            ts = quote_zone_start + qi * (quote_zone / len(quotes))
            te = ts + 8
            for li, line in enumerate(lines):
                text_filters.append(
                    f"drawtext=fontfile={FONT_BOLD}:text='{line}':fontsize=50:fontcolor=white:"
                    f"borderw=3:bordercolor=black@0.6:x=(w-text_w)/2:y={260+li*80}:"
                    f"alpha='if(lt(t,{ts+1}),0,if(lt(t,{ts+2}),(t-{ts+1}),"
                    f"if(lt(t,{te-1}),1,if(lt(t,{te}),({te}-t),0))))'"
                )
            text_filters.append(
                f"drawtext=fontfile={FONT_BOLD}:text='—— {book_title}':fontsize=34:"
                f"fontcolor=0xD8B04A:borderw=2:bordercolor=black@0.5:"
                f"x=(w-text_w)/2:y={260+len(lines)*80}:"
                f"alpha='if(lt(t,{ts+1}),0,if(lt(t,{ts+2}),(t-{ts+1}),"
                f"if(lt(t,{te-1}),1,if(lt(t,{te}),({te}-t),0))))'"
            )

    parts.append(f"[{prev}]{','.join(text_filters) if text_filters else 'null'},format=yuv420p[vout]")
    return ";".join(parts)


def get_duration(audio: str) -> float:
    """获取音频时长"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", audio], capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip() or 60)


def main():
    ap = argparse.ArgumentParser(description="listen-book 视频合成器")
    ap.add_argument("--script", required=True, help="讲书稿 txt")
    ap.add_argument("--audio", required=True, help="音频 mp3")
    ap.add_argument("--output", default="output.mp4", help="输出视频路径")
    ap.add_argument("--theme", default="desert", choices=["desert", "forest", "ocean"],
                    help="实景主题")
    ap.add_argument("--book", default="", help="书名（封面文字）")
    ap.add_argument("--author", default="", help="作者")
    args = ap.parse_args()

    script_text = Path(args.book).read_text(encoding="utf-8") if False else \
        Path(args.script).read_text(encoding="utf-8", errors="replace")
    book_title = args.book or Path(args.script).stem
    quotes = extract_quotes(script_text)

    print(f"📖 书名: {book_title}")
    print(f"💬 提取金句: {len(quotes)} 句")
    for q in quotes:
        print(f"   「{q}」")

    audio_dur = get_duration(args.audio)
    print(f"⏱️ 音频时长: {audio_dur:.1f}s")

    with tempfile.TemporaryDirectory(prefix="lb_video_") as td:
        tmpdir = Path(td)
        print("⬇️ 下载实景图...")
        images = download_images(args.theme, tmpdir)
        if len(images) < 2:
            print("❌ 图片下载失败，检查网络")
            sys.exit(1)
        print(f"✅ 下载 {len(images)} 张实景图")

        # 视频帧流（无音频）
        flt = make_filter(images, audio_dur, quotes, book_title, args.author)
        video_mp4 = tmpdir / "video_noaudio.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error"]
        n = len(images)
        for img in images:
            cmd += ["-loop", "1", "-t", f"{audio_dur/n + XFADE_DUR}", "-i", str(img)]
        cmd += ["-filter_complex", flt, "-map", "[vout]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-t", f"{audio_dur}", str(video_mp4)]
        print("🎬 合成视频（Ken Burns + 交叉溶解 + 金句）...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            print(f"❌ 合成失败: {r.stderr[-500:]}")
            sys.exit(1)

        # 混入音频
        print("🎵 混入音频...")
        cmd2 = ["ffmpeg", "-y", "-v", "error", "-i", str(video_mp4),
                "-i", args.audio, "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-shortest", args.output]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if r2.returncode != 0:
            print(f"❌ 音频混入失败: {r2.stderr[-300:]}")
            sys.exit(1)

    print(f"✅ 完成！输出: {args.output}")


if __name__ == "__main__":
    main()
