#!/usr/bin/env python3
"""bookmadebook 语速实测器

核心思路：不再猜语速，每次生成前实测。
不同声音语速差异巨大（晓晓快、云健慢、儿童模式更慢），必须逐个实测。

用法：
    python speed_probe.py --voice zh-CN-YunjianNeural
    python speed_probe.py --voice zh-CN-YunjianNeural --rate -10%
"""
import argparse
import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path

# 测试文本：300字左右的段落（模拟真实精读稿的长段落）
TEST_TEXT = """你有没有想过一个问题：十万年前，地球上至少有六种不同的人。尼安德特人、丹尼索瓦人、直立人、梭罗人，他们和我们一样会使用工具，会照顾老弱，有些甚至比我们更强壮、脑容量更大。可是今天，世界舞台上只剩下我们智人。其他的人都去哪了？是被我们消灭了，还是融入了我们？我们凭什么活了下来？又是怎么从食物链中段的位置，一路爬到了顶端？这本人类简史回答的就是这个问题。作者尤瓦尔赫拉利是以色列历史学家，他用一本书讲完了人类从十万年前到今天的全部历程。这本书在全球卖了上千万册，被翻译成六十多种语言。它讲的不是帝王将相的历史，而是整个人类物种的宏大叙事。今天我们走完这十万年，从篝火旁讲故事的夜晚，一直走到人工智能正在重塑人类的今天。"""

# 语速缓存（避免每次重复测量）
CACHE_FILE = Path(os.path.expanduser("~/.hermes/cache/bookmadebook/speed_cache.json"))


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(open(CACHE_FILE, encoding="utf-8").read())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def char_count(text: str) -> int:
    """统计有效字符数（去除空白）"""
    return len(text.replace("\n", "").replace(" ", "").replace("\r", ""))


def probe_sync(voice: str, rate: str = "+0%") -> float:
    """同步测速：生成测试音频，测量语速（字/分）"""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    # 生成测试音频
    args = ["edge-tts", "--voice", voice, f"--rate={rate}",
            "--text", TEST_TEXT, "--write-media", tmp_path]
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or not Path(tmp_path).exists():
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise RuntimeError(f"edge-tts 生成失败: {result.stderr[:200]}")

    # 测量时长
    probe = subprocess.run(
        ["ffprobe", "-i", tmp_path, "-show_entries", "format=duration",
         "-v", "quiet", "-of", "csv=p=0"],
        capture_output=True, text=True, timeout=30
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        duration = 0.0

    try:
        os.unlink(tmp_path)
    except Exception:
        pass

    if duration <= 0:
        raise RuntimeError("无法测量音频时长")

    # 语速 = 字数 / 分钟
    chars = char_count(TEST_TEXT)
    speed = chars / (duration / 60.0)
    return speed


def get_speed(voice: str, rate: str = "+0%", force: bool = False) -> float:
    """获取语速（带缓存）"""
    key = f"{voice}|{rate}"
    cache = load_cache()
    if not force and key in cache:
        return cache[key]

    try:
        speed = probe_sync(voice, rate)
        cache[key] = round(speed, 1)
        save_cache(cache)
        return speed
    except Exception as e:
        # 失败时回退到默认值
        default_speeds = {
            # 与 quality_gate 的默认值保持一致（实测校准值，勿改回旧的高估）
            "zh-CN-XiaoxiaoNeural": 282.0,
            "zh-CN-YunjianNeural": 284.0,
            "zh-CN-YunxiNeural": 350.0,
            "zh-CN-YunyangNeural": 320.0,
            "zh-CN-XiaoshuangNeural": 250.0,
            "en-US-ChristopherNeural": 180.0,
            "en-US-AndrewNeural": 190.0,
            "ja-JP-NanamiNeural": 273.0,
        }
        fallback = default_speeds.get(voice, 282.0)
        print(f"⚠️ 测速失败({e})，使用默认值 {fallback} 字/分")
        return fallback


def calc_target_chars(target_minutes: float, speed: float) -> int:
    """根据目标时长和实测语速，反推需要的字数"""
    return int(target_minutes * speed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="bookmadebook 语速实测器")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural", help="声音")
    parser.add_argument("--rate", default="+0%", help="语速")
    parser.add_argument("--target-minutes", type=float, help="目标时长(分钟)，同时输出所需字数")
    parser.add_argument("--force", action="store_true", help="强制重新测量")
    args = parser.parse_args()

    speed = get_speed(args.voice, args.rate, args.force)
    print(f"🎤 {args.voice} (rate={args.rate}) 实测语速: {speed:.0f} 字/分")

    if args.target_minutes:
        chars = calc_target_chars(args.target_minutes, speed)
        print(f"📐 目标时长 {args.target_minutes} 分钟 → 需要写 {chars:,} 字")
        print(f"   平均每部分({chars/10:.0f}字，按10个部分分配)")
