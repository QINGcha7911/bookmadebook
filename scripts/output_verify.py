#!/usr/bin/env python3
"""bookmadebook Harness — 输出验证门 (output verify)

在 TTS 生成完成后验证最终音频质量：
1. 开头无标题/符号朗读（波形相关性检测 vs 标题朗读样本）
2. 时长偏差 ≤10%（vs 目标时长）
3. 音频完整性（可解码、时长>0）

这是 harness 控制循环的最后一关——防止"验证干净但音频有标题"类问题
再次交付给用户。

用法:
    python output_verify.py --audio final.mp3 --target-minutes 45
    python output_verify.py --audio final.mp3 --target-minutes 45 --title-sample title_ref.mp3

退出码: 0=通过, 1=不通过
"""
import argparse
import subprocess
import sys
import tempfile
import os


def get_duration(path: str) -> float:
    """获取音频时长（秒）。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def load_pcm(path: str, duration: float = None) -> bytes:
    """转音频为 16bit mono PCM。"""
    cmd = ["ffmpeg", "-v", "quiet"]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    return r.stdout


def corr(a: bytes, b: bytes) -> float:
    """波形相关性（numpy）。"""
    import numpy as np
    if len(a) < 100 or len(b) < 100:
        return 0.0
    x = np.frombuffer(a[:min(len(a), len(b))], dtype=np.int16).astype(float)
    y = np.frombuffer(b[:min(len(a), len(b))], dtype=np.int16).astype(float)
    if len(x) != len(y):
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
    if np.std(x) < 1 or np.std(y) < 1:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def verify(audio: str, target_minutes: float = None,
           title_sample: str = None) -> dict:
    """执行输出验证，返回报告。"""
    report = {"passed": True, "errors": [], "warnings": [], "stats": {}}

    # 1. 完整性
    duration = get_duration(audio)
    report["stats"]["duration"] = round(duration, 1)
    if duration <= 0:
        report["passed"] = False
        report["errors"].append("音频不可解码或时长为0，生成失败。")
        return report

    # 2. 时长偏差
    if target_minutes:
        target_sec = target_minutes * 60
        deviation = abs(duration - target_sec) / target_sec
        report["stats"]["deviation"] = round(deviation * 100, 1)
        if deviation > 0.10:
            report["passed"] = False
            report["errors"].append(
                f"时长偏差{deviation*100:.0f}% > 10%（实际{round(duration/60,1)}分钟 "
                f"vs 目标{target_minutes:.0f}分钟）。"
                f"如内容不足请诚实缩短目标，禁止注水。"
            )

    # 3. 开头无标题朗读（波形相关性）
    if title_sample and os.path.exists(title_sample):
        head = load_pcm(audio, 2.0)      # 音频开头2秒
        title = load_pcm(title_sample)   # 标题朗读样本
        if head and title:
            c = abs(corr(head, title))
            report["stats"]["title_corr"] = round(c, 3)
            if c > 0.5:
                report["passed"] = False
                report["errors"].append(
                    f"开头{round(c,2)}秒与标题朗读相关性={c:.2f}（>0.5）——"
                    f"开头仍在朗读标题/符号！请检查 ted_director 清理 + 清L3缓存。"
                )
            elif c > 0.1:
                report["warnings"].append(f"开头与标题相关性={c:.2f}，接近阈值，建议复核。")

    return report


def main():
    ap = argparse.ArgumentParser(description="bookmadebook 输出验证门")
    ap.add_argument("--audio", required=True, help="生成的音频文件")
    ap.add_argument("--target-minutes", type=float, help="目标时长（分钟）")
    ap.add_argument("--title-sample", help="标题朗读样本（开头对比用）")
    args = ap.parse_args()

    report = verify(args.audio, args.target_minutes, args.title_sample)

    print("🔍 输出验证报告:")
    for k, v in report["stats"].items():
        print(f"   {k}: {v}")
    for w in report["warnings"]:
        print(f"  ⚠️ {w}")
    for e in report["errors"]:
        print(f"  ❌ {e}")
    if report["passed"]:
        print("  ✅ 输出验证通过。")
        sys.exit(0)
    print("  📢 输出验证不通过——禁止交付，请修复后重新生成。")
    sys.exit(1)


if __name__ == "__main__":
    main()
