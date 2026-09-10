#!/usr/bin/env python3
"""TTS 时长归一 + 响度对齐（2026-09-11 定案）

背景（《梦里花落知多少》早班踩坑）：
  TTS 产出比目标时长偏长时，此前用手工 ffmpeg `atempo=X` 把音频压回目标秒数，
  但**只做了 atempo、没补 loudnorm**。结果：独立交付 mp3 实测 -17.2 LUFS，
  而视频合成时 video_composer 又对音轨做了一次 loudnorm(I=-16)，MP4 音轨 -16.1。
  两条交付物响度差 1.1dB，播放器切换时忽大忽小。

本脚本固化「atempo 之后必补 loudnorm」流程，一步产出与 MP4 音轨一致（≈-16 LUFS）的
独立音频，杜绝再次遗漏。

用法:
    # 按目标秒数归一（常用：把 TTS 输出压到 640s）
    python3 scripts/tempo_normalize.py in.mp3 out.mp3 --target-seconds 640

    # 按目标分钟归一
    python3 scripts/tempo_normalize.py in.mp3 out.mp3 --target-minutes 10

    # 已知倍速，直接指定
    python3 scripts/tempo_normalize.py in.mp3 out.mp3 --atempo 1.1132

    # 只做响度对齐、不改时长
    python3 scripts/tempo_normalize.py in.mp3 out.mp3 --atempo 1.0

约束：loudnorm 参数与 video_composer/streaming_pipeline 保持一致
      (I=-16:TP=-1.5:LRA=11)，确保 mp3 与 MP4 音轨响度同一标尺。
"""
import argparse
import subprocess
import sys
from pathlib import Path

# 与流水线/合成器统一（勿改，否则 mp3 与 MP4 音轨响度又会分叉）
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def probe_duration(path: str) -> float:
    """返回音频容器时长（秒），失败抛错。"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        raise SystemExit(f"❌ 无法读取时长: {path}\n{r.stderr[-200:]}")


def measure_lufs(path: str) -> float:
    """测整段集成响度 LUFS（ebur128），失败返回 nan。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    last = None
    for line in r.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                last = float(line.split("I:")[1].split()[0])
            except (ValueError, IndexError):
                pass
    return last if last is not None else float("nan")


def build_atempo(tempo: float) -> str:
    """atempo 支持 0.5~100；超出范围时链式串联。"""
    if 0.5 <= tempo <= 100.0:
        return f"atempo={tempo:.6f}"
    parts, t = [], tempo
    # 保守：逐级分解到允许区间
    while t > 2.0:
        parts.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        parts.append("atempo=0.5")
        t /= 0.5
    parts.append(f"atempo={t:.6f}")
    return ",".join(parts)


def main():
    ap = argparse.ArgumentParser(description="TTS 时长归一(atempo) + 响度对齐(loudnorm)")
    ap.add_argument("input", help="输入音频（TTS 原始产物）")
    ap.add_argument("output", help="输出音频（归一后交付版）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--target-seconds", type=float, help="目标总时长（秒）")
    g.add_argument("--target-minutes", type=float, help="目标总时长（分钟）")
    g.add_argument("--atempo", type=float, help="直接指定 atempo 倍速（>1 加速）")
    ap.add_argument("--lufs", type=float, default=-16.0, help="目标响度 LUFS（默认 -16）")
    ap.add_argument("--bitrate", default="128k", help="输出 mp3 码率（默认 128k）")
    ap.add_argument("--no-loudnorm", action="store_true",
                    help="仅 atempo 不做响度对齐（调试用，不建议交付）")
    args = ap.parse_args()

    if not Path(args.input).exists():
        raise SystemExit(f"❌ 输入不存在: {args.input}")
    in_dur = probe_duration(args.input)

    if args.atempo is not None:
        tempo = args.atempo
        target = in_dur / tempo if tempo else in_dur
    else:
        if args.target_seconds:
            target = args.target_seconds
        elif args.target_minutes:
            target = args.target_minutes * 60.0
        else:
            raise SystemExit("❌ 需指定 --target-seconds / --target-minutes / --atempo 之一")
        tempo = in_dur / target

    print(f"🎚️ 输入 {in_dur:.2f}s → 目标 {target:.2f}s (atempo={tempo:.4f})")

    # atempo 之后必补 loudnorm（本脚本存在的唯一理由）
    af = build_atempo(tempo)
    if not args.no_loudnorm:
        ln = LOUDNORM if args.lufs == -16.0 else \
            f"loudnorm=I={args.lufs}:TP=-1.5:LRA=11"
        af = f"{af},{ln}"

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", args.input,
           "-af", af, "-c:a", "libmp3lame", "-b:a", args.bitrate,
           "-map_metadata", "-1", args.output]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise SystemExit(f"❌ 归一失败: {r.stderr[-400:]}")

    out_dur = probe_duration(args.output)
    out_lufs = measure_lufs(args.output) if not args.no_loudnorm else float("nan")
    print(f"✅ 输出 {args.output}")
    print(f"   时长 {out_dur:.2f}s (偏差 {out_dur - target:+.2f}s)")
    if not args.no_loudnorm:
        print(f"   响度 {out_lufs:.1f} LUFS（目标 {args.lufs}，与 MP4 音轨同标尺）")


if __name__ == "__main__":
    main()
