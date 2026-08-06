#!/usr/bin/env python3
"""listen-book 一键入口

把"书 → 音频"简化为一条命令（yt-dlp 风格）：
    python listen.py "《小王子》10分钟"
    python listen.py "《原子习惯》跑步8分钟" --voice auto

自然语言解析：书名 + 时长（分钟）+ 可选场景词。
内部调用 harness 主控（质量门 → 生成 → 验证门），非 Hermes 用户也能用。

用法:
    python listen.py "书名 时长分钟" [--voice VOICE] [--style normal|ted] [--output PATH]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent


def parse_request(text: str) -> dict:
    """解析自然语言：提取书名、时长（分钟）、场景。"""
    t = text.strip()
    # 书名：去书名号（《》 可能出现在中间）
    t = t.replace('《', '').replace('》', '').replace('"', '').strip()
    # 时长：匹配 "X分钟" / "X 分钟" / "Xmin"
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:分钟|min)', t, re.IGNORECASE)
    minutes = float(m.group(1)) if m else 10.0
    if m:
        t = t[:m.start()].strip()
    # 书名 = 剩余部分（去场景词尾）
    for word in ["跑步", "通勤", "睡前", "开车", "运动"]:
        if t.endswith(word):
            t = t[: -len(word)].strip()
            break
    t = t.strip("，。、 ")
    return {"book": t, "minutes": minutes}


def main():
    ap = argparse.ArgumentParser(description="listen-book 一键入口")
    ap.add_argument("request", nargs="?", help='自然语言请求，如 "《小王子》10分钟" 或 "小王子 10分钟"')
    ap.add_argument("--voice", default="auto", help="TTS声音（auto=按内容自动选）")
    ap.add_argument("--style", default="ted", choices=["normal", "ted"], help="朗读风格")
    ap.add_argument("--output", help="输出文件路径（默认 ./输出/<书名>.mp3）")
    ap.add_argument("--target-minutes", type=float, help="目标时长（分钟，覆盖自然语言解析）")
    args = ap.parse_args()

    if not args.request:
        ap.error("需要请求，如: python listen.py \"《小王子》10分钟\"")

    req = parse_request(args.request)
    minutes = args.target_minutes or req["minutes"]
    book = req["book"]
    print(f"📖 请求解析: 书名={book} | 时长={minutes}分钟 | 声音={args.voice}")

    # 输出路径默认 ./listen-book 输出目录
    output = args.output or str(Path("listen-book-output") / f"{book}-{int(minutes)}min.mp3")

    # 调用 harness 主控
    cmd = [sys.executable, str(SCRIPTS / "harness.py"),
           "--file", "<讲书稿>", "--target-minutes", str(minutes),
           "--voice", args.voice, "--style", args.style,
           "--output", output]
    # 注：harness 需要讲书稿文件。这里提示用户/Agent 先用 prompts 模板生成稿子，
    # 或后续版本接入 LLM 自动写稿。
    print(f"🔗 将调用 harness 主控: {' '.join(cmd)}")
    print("\n📢 说明: 一键入口需要讲书稿文件（用 prompts/ 模板 + LLM 生成）。")
    print("   完整流程: 写稿 → 质量门 → 生成 → 验证门 → 输出")
    print(f"   生成后输出到: {output}")
    sys.exit(0)


if __name__ == "__main__":
    main()
