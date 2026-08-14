#!/usr/bin/env python3
"""bookmadebook 视频合成器 —— 讲书音频 → 实景动态视频

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
_ORIG_CWD = os.getcwd()
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
FONT_BOLD = "../assets/fonts/msyhbd.ttc"
FONT_REG = "../assets/fonts/msyh.ttc"

# 主题色板（与场景主题联动，Step 5 完整接入）
THEME_PALETTES = {
    "palace":    {"accent": "0xC9A063", "title_font": "serif"},
    "desert":    {"accent": "0xD8B04A", "title_font": "sans"},
    "forest":    {"accent": "0x8FBC8F", "title_font": "sans"},
    "ocean":     {"accent": "0x58C6F5", "title_font": "sans"},
    "sunrise":   {"accent": "0xE8933F", "title_font": "sans"},
    "starry":    {"accent": "0x9B7EDE", "title_font": "sans"},
    "rain":      {"accent": "0xB23A48", "title_font": "sans"},
    "library":   {"accent": "0xC9A063", "title_font": "serif"},
    "warm_home": {"accent": "0xE0A899", "title_font": "sans"},
    "snow":      {"accent": "0xA8C6E0", "title_font": "sans"},
    "tech_city": {"accent": "0x58C6F5", "title_font": "sans"},
    "temple":    {"accent": "0xC9A063", "title_font": "serif"},
}

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


def make_filter(plan, audio_dur: float, quotes: list[str],
                book_title: str, author: str = "", script_text: str = ""):
    """构建 ffmpeg filter_complex：Ken Burns + xfade + 金句文字
    plan: ScenePlan（支持可变时长分段 + 多场景）"""
    items = plan.images_with_durations() if hasattr(plan, "images_with_durations") else \
        [(p, audio_dur / len(plan)) for p in plan]
    n = len(items)
    parts = []
    # 每张图 Ken Burns 缩放（独立时长）；scale 用 cover 模式防拉伸变形
    # 缩放速度按段时长分配：zoom 从 1.0→1.15 铺满整段（on=输出帧号），避免"4秒后静止"
    for i, (img, dur) in enumerate(items):
        zoom_in = (i % 2 == 0)
        zexpr = (f"min(1.0+0.15*on/{max(int(dur*FPS),1)},1.15)"
                 if zoom_in else
                 f"max(1.15-0.15*on/{max(int(dur*FPS),1)},1.0)")
        parts.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,zoompan=z='{zexpr}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={int(dur*FPS)}:s={W}x{H}:fps={FPS},"
            f"trim=duration={dur+XFADE_DUR},setpts=PTS-STARTPTS[v{i}]"
        )
    # xfade 交叉溶解（累计可变时长）
    prev = "v0"
    total = items[0][1]
    for i in range(1, n):
        out = f"x{i}"
        offset = total - XFADE_DUR
        parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}[{out}]")
        prev = out
        total += items[i][1] - XFADE_DUR

    # ── 文字层（PIL 预渲染 PNG overlay，替代 drawtext）──
    import text_layers as tl
    # 章节标题提取（## 标题）
    chapters = []
    for line in script_text.splitlines():
        line = line.strip()
        if line.startswith("##") or line.startswith("#"):
            t = re.sub(r"^#+\s*", "", line).strip()
            if t:
                chapters.append(t)
    layers = tl.render_all(book_title, quotes, chapters, author=author,
                           watermark=book_title)
    # 全部文字层作为 PNG 输入
    png_inputs = []
    png_map = {}
    for k, v in layers.items():
        if k == "_tmpdir":
            continue
        png_inputs.append(v)
        png_map[k] = len(png_inputs) - 1
    n_png = len(png_inputs)
    png_base = n  # PNG 输入基础偏移 = 图片输入数

    text_parts = []
    prev_v = prev
    # ① 书名：0s 全显 → 8.5s 淡出
    bk_idx = png_map["book"]
    text_parts.append(f"[{png_base+bk_idx}:v]format=rgba,"
                      f"fade=t=in:st=0:d=0.3:alpha=1,"
                      f"fade=t=out:st=8.5:d=0.8:alpha=1[bk]")
    text_parts.append(f"[{prev_v}][bk]overlay=0:0[o_book]")
    prev_v = "o_book"

    # ② 章节标签：每章闪现 ≤5s（时间轴按字数比例估算）
    audio_dur_chars = len(script_text) or 1
    if chapters:
        char_cursor = 0
        chapter_times = []
        for ci, ch in enumerate(chapters):
            idx = script_text.find(ch, char_cursor)
            chapter_times.append((audio_dur * idx / audio_dur_chars) if idx >= 0
                                 else (audio_dur * ci / len(chapters)))
            char_cursor = max(char_cursor, idx + len(ch)) if idx >= 0 else char_cursor
        for ci, ch in enumerate(chapters):
            ck = f"chapter_{ci}"
            if ck not in png_map:
                continue
            st = chapter_times[ci]
            if ci < len(chapters) - 1:
                et = min(st + 5, chapter_times[ci + 1] - 0.5)
            else:
                et = min(st + 5, audio_dur - 0.5)
            if et <= st:
                continue
            c_idx = png_map[ck]
            text_parts.append(f"[{png_base+c_idx}:v]format=rgba,"
                              f"fade=t=in:st={st}:d=0.5:alpha=1,"
                              f"fade=t=out:st={et}:d=0.5:alpha=1[ch{ci}]")
            text_parts.append(f"[{prev_v}][ch{ci}]overlay=0:0[o_ch{ci}]")
            prev_v = f"o_ch{ci}"

    # ③ 金句：时间窗保留现状逻辑（后段均布，最后一句留片尾）
    if quotes:
        quote_zone_start = audio_dur * 0.3
        quote_zone = audio_dur * 0.65
        for qi, q in enumerate(quotes):
            qk = f"quote_{qi}"
            ts = quote_zone_start + qi * (quote_zone / len(quotes))
            is_last = (qi == len(quotes) - 1)
            te = audio_dur if is_last else ts + 8
            if is_last:
                fade_out = ""
            else:
                fade_out = f",fade=t=out:st={te-0.8}:d=0.8:alpha=1"
            q_idx = png_map[qk]
            text_parts.append(f"[{png_base+q_idx}:v]format=rgba,"
                              f"fade=t=in:st={ts+0.5}:d=0.8:alpha=1{fade_out}[q{qi}]")
            text_parts.append(f"[{prev_v}][q{qi}]overlay=0:0[p{qi}]")
            prev_v = f"p{qi}"
            # 出处：仅最后一句
            if is_last and "attribution" in png_map:
                a_idx = png_map["attribution"]
                text_parts.append(f"[{png_base+a_idx}:v]format=rgba,"
                                  f"fade=t=in:st={ts+0.5}:d=0.8:alpha=1[attr]")
                text_parts.append(f"[{prev_v}][attr]overlay=0:0[p_attr]")
                prev_v = "p_attr"

    # ④⑤ 进度条：轨道常驻 + 填充 crop 增长
    pt_idx = png_map["progress_track"]
    text_parts.append(f"[{png_base+pt_idx}:v]format=rgba[pt]")
    text_parts.append(f"[{prev_v}][pt]overlay=0:0[t_pt]")
    prev_v = "t_pt"
    pf_idx = png_map["progress_fill"]
    text_parts.append(f"[{png_base+pf_idx}:v]format=rgba,"
                      f"crop=w=max(2\\,iw*min(t/{audio_dur}\\,1)):h=ih[pf]")
    text_parts.append(f"[{prev_v}][pf]overlay=0:0[t_pf]")
    prev_v = "t_pf"

    # ⑥ 水印
    if "watermark" in png_map:
        w_idx = png_map["watermark"]
        text_parts.append(f"[{png_base+w_idx}:v]format=rgba[wm]")
        text_parts.append(f"[{prev_v}][wm]overlay=0:0[wm_out]")
        prev_v = "wm_out"

    # ⑧ AI 生成角标（合规标识，常驻最上层）
    if "ai_badge" in png_map:
        a_idx = png_map["ai_badge"]
        text_parts.append(f"[{png_base+a_idx}:v]format=rgba[ab]")
        text_parts.append(f"[{prev_v}][ab]overlay=0:0,format=yuv420p[vout]")
    else:
        text_parts.append(f"[{prev_v}]format=yuv420p[vout]")

    parts.extend(text_parts)
    return ";".join(parts), png_inputs


def get_duration(audio: str) -> float:
    """获取音频时长"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", audio], capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip() or 60)


def main():
    ap = argparse.ArgumentParser(description="bookmadebook 视频合成器")
    ap.add_argument("--script", required=True, help="讲书稿 txt")
    ap.add_argument("--audio", required=True, help="音频 mp3")
    ap.add_argument("--output", default="output.mp4", help="输出视频路径")
    ap.add_argument("--theme", default="auto", choices=["auto"] + sorted(set(
        list(THEMES.keys()) + ["palace", "sunrise", "starry", "rain", "library",
                               "warm_home", "snow", "tech_city", "temple"])),
                    help="实景主题；auto=按内容自动选择（默认）；手动指定则整片使用该主题")
    ap.add_argument("--scene-from", default="auto", choices=["auto", "script", "manual"],
                    help="场景来源：auto=标记+自动检测，script=仅用标记，manual=仅用--theme")
    ap.add_argument("--dry-run", action="store_true", help="只输出场景规划不合成")
    ap.add_argument("--book", default="", help="书名（封面文字）")
    ap.add_argument("--author", default="", help="作者")
    ap.add_argument("--fast", action="store_true", help="快速模式：preset faster + crf 26（长视频/预览用）")
    args = ap.parse_args()

    def _abs(p: str) -> str:
        pth = Path(p)
        return str(pth if pth.is_absolute() else Path(_ORIG_CWD) / pth)

    args.script = _abs(args.script)
    args.audio = _abs(args.audio)
    args.output = _abs(args.output)

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

    # 场景规划（scene_selector：手动 > 标记 > 自动检测）
    import scene_selector
    theme_arg = args.theme
    if args.scene_from == "manual":
        theme_arg = args.theme if args.theme != "auto" else "desert"
    plan = scene_selector.select_scenes(script_text, theme_arg, audio_dur, args.audio)
    print(f"🎬 场景规划: {len(plan.segments)} 段")
    for seg in plan.segments:
        print(f"   [{seg.start:.0f}s-{seg.end:.0f}s] {seg.theme}"
              + (f" {seg.chapter_title}" if seg.chapter_title else ""))

    if args.dry_run:
        print("✅ dry-run 完成（未合成）")
        return

    with tempfile.TemporaryDirectory(prefix="lb_video_") as td:
        tmpdir = Path(td)
        print("🖼️ 加载本地素材库...")
        import scene_library
        plan = scene_library.load_plan_images(plan)
        items = plan.images_with_durations()
        images = [p for p, _ in items]
        durations = [d for _, d in items]
        print(f"✅ 使用 {len(images)} 张素材图")

        # 视频帧流（无音频）
        flt, png_inputs = make_filter(plan, audio_dur, quotes, book_title,
                                      args.author, script_text)
        video_mp4 = tmpdir / "video_noaudio.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for img, dur in items:
            cmd += ["-loop", "1", "-t", f"{dur + XFADE_DUR}", "-i", str(img)]
        # 文字层 PNG 输入
        for png in png_inputs:
            cmd += ["-loop", "1", "-t", str(audio_dur), "-i", str(png)]
        cmd += ["-filter_complex", flt, "-map", "[vout]",
                "-c:v", "libx264", "-preset", "faster" if args.fast else "medium",
                "-crf", "26" if args.fast else "23",
                "-t", f"{audio_dur}", str(video_mp4)]
        print("🎬 合成视频（Ken Burns + 交叉溶解 + 金句）...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
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
