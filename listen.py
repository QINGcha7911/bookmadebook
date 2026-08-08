#!/usr/bin/env python3
"""bookmadebook 一键入口（音频/视频自适应）

把"书 → 音频/视频"简化为一条命令（yt-dlp 风格）：
    python listen.py "《小王子》10分钟"            # 默认音频
    python listen.py "《小王子》10分钟视频"        # 视频（实景动态画面+金句）
    python listen.py "小王子 做个视频"             # 视频
    python listen.py "《原子习惯》跑步8分钟"       # 音频（跑步场景）

自然语言解析：书名 + 时长（分钟）+ 输出类型（视频/音频）+ 可选场景词。
流程：音频 → harness 主控（质量门→生成→验证门）；视频 → 音频 + video_composer 合成。

用法:
    python listen.py "书名 时长分钟[视频|音频]" [--voice VOICE] [--style normal|ted] [--theme desert|forest|ocean] [--output PATH]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"

# 视频关键词（出现则输出视频）
VIDEO_KEYWORDS = ["视频", "短片", "配画面", "有画面", "video", "vlog"]
# 音频关键词（明确要音频）
AUDIO_KEYWORDS = ["音频", "听书", "播客", "audio", "podcast", "mp3", "听"]
# 场景词（从书名后剥离）
SCENE_WORDS = ["跑步", "通勤", "睡前", "开车", "运动", "开车时", "散步"]


def parse_request(text: str) -> dict:
    """解析自然语言：书名、时长（分钟）、输出类型、场景。"""
    t = text.strip()
    lower = t.lower()
    # 输出类型判断（视频优先，明确音频才音频）
    output_type = "audio"
    if any(k in lower for k in VIDEO_KEYWORDS):
        output_type = "video"
    elif any(k in lower for k in AUDIO_KEYWORDS):
        output_type = "audio"

    # 书名：去书名号
    t = t.replace('《', '').replace('》', '').replace('"', '').strip()
    # 时长：匹配 "X分钟" / "X 分钟" / "Xmin"
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:分钟|min)', t, re.IGNORECASE)
    minutes = float(m.group(1)) if m else 10.0
    if m:
        t = t[:m.start()].strip()
    # 去输出类型词（书名里不该有"视频/音频"）
    for kw in VIDEO_KEYWORDS + AUDIO_KEYWORDS:
        t = t.replace(kw, "").strip()
    # 去动词（做个/要个/来一个/生成 等，可组合：帮我生成/帮我做）
    t = re.sub(r"(做个|要个|来一个|来段|生成|做一段|来一段|给我|帮我)\s*$", "", t).strip()
    t = re.sub(r"^(给我|帮我)\s*(做个|要个|生成|做一段)?\s*", "", t).strip()
    t = re.sub(r"^(做个|要个|来一个|来段|生成|做一段|来一段)\s*", "", t).strip()
    # 书名 = 剩余部分（去场景词尾）
    for word in SCENE_WORDS:
        if t.endswith(word):
            t = t[: -len(word)].strip()
            break
    t = t.strip("，。、 ")
    return {"book": t, "minutes": minutes, "output_type": output_type}


def main():
    ap = argparse.ArgumentParser(description="bookmadebook 一键入口（音频/视频自适应）")
    ap.add_argument("request", nargs="?", help='自然语言请求，如 "《小王子》10分钟" 或 "小王子 10分钟视频"')
    ap.add_argument("--voice", default="auto", help="TTS声音（auto=按内容自动选）")
    ap.add_argument("--style", default="ted", choices=["normal", "ted"], help="朗读风格")
    ap.add_argument("--theme", default="desert", choices=["desert", "forest", "ocean"],
                    help="视频实景主题（视频模式）")
    ap.add_argument("--output", help="输出文件路径（默认 ./bookmadebook-output/<书名>.mp4/.mp3）")
    ap.add_argument("--target-minutes", type=float, help="目标时长（分钟，覆盖自然语言解析）")
    ap.add_argument("--output-type", choices=["audio", "video"],
                    help="输出类型（覆盖自然语言识别：audio=音频 video=视频）")
    args = ap.parse_args()

    if not args.request:
        ap.error('需要请求，如: python listen.py "《小王子》10分钟视频"')

    req = parse_request(args.request)
    minutes = args.target_minutes or req["minutes"]
    book = req["book"]
    output_type = args.output_type or req["output_type"]
    print(f"📖 请求解析: 书名={book} | 时长={minutes}分钟 | 输出={output_type} | 声音={args.voice}")

    out_dir = Path("bookmadebook-output")
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = ".mp4" if output_type == "video" else ".mp3"
    output = args.output or str(out_dir / f"{book}-{int(minutes)}min{ext}")

    # ── 第一步：生成音频（harness 主控：质量门→生成→验证门）──
    audio_tmp = str(out_dir / f"{book}-{int(minutes)}min_tmp.mp3")
    cmd = [sys.executable, str(SCRIPTS / "harness.py"),
           "--book", book,
           "--target-minutes", str(minutes),
           "--voice", args.voice, "--style", args.style,
           "--output", audio_tmp]
    print(f"🔗 [1/2] 生成音频: {' '.join(cmd)}\n")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"\n📢 音频生成失败（exit {r.returncode}）。如为质量门/验证门拦截，请补充内容或调整时长。")
        sys.exit(r.returncode)
    print(f"✅ 音频完成: {audio_tmp}")

    # ── 第二步（视频模式）：合成实景动态视频 ──
    if output_type == "video":
        print(f"\n🔗 [2/2] 合成视频（主题={args.theme}）...")
        vcmd = [sys.executable, str(SCRIPTS / "video_composer.py"),
                "--script", "（讲书稿）", "--audio", audio_tmp,
                "--book", book, "--theme", args.theme,
                "--output", output]
        # 注：harness --book 模式内部生成速览稿；正式用 --file 传入讲书稿
        # 这里简化：video_composer 需要讲书稿提取金句，用临时空稿（金句自动从音频文本提取）
        # 实际使用时：先生成讲书稿文件 → --script 传入
        print(f"  （注：视频模式需讲书稿提取金句，建议先写稿再合成）")
        # 直接调用 video_composer（用 harness 的速览稿逻辑）
        script_path = out_dir / f"{book}-{int(minutes)}min_script.txt"
        # 尝试获取书籍信息生成速览稿
        try:
            r2 = subprocess.run([sys.executable, str(SCRIPTS / "book_info.py"), book],
                                capture_output=True, text=True, timeout=60)
            script_path.write_text(r2.stdout[-3000:] or f"关于《{book}》的讲书内容。\n",
                                   encoding="utf-8")
        except Exception:
            script_path.write_text(f"《{book}》精讲。\n", encoding="utf-8")
        vcmd[1] = str(SCRIPTS / "video_composer.py")
        vcmd[vcmd.index("--script") + 1] = str(script_path)
        print(f"🔗 调用: {' '.join(vcmd)}\n")
        rv = subprocess.run(vcmd)
        if rv.returncode != 0:
            print(f"\n📢 视频合成失败（exit {rv.returncode}）")
            sys.exit(rv.returncode)
        print(f"\n✅ 完成！视频输出到: {output}")
    else:
        # 音频模式：重命名临时音频为最终输出
        import shutil
        shutil.copy2(audio_tmp, output)
        print(f"\n✅ 完成！音频输出到: {output}")


if __name__ == "__main__":
    main()
