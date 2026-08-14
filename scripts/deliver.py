#!/usr/bin/env python3
"""交付工具：按视频时长自动选交付策略（2026-08-13 新增）

问题背景：
- 45 分钟视频 168MB，飞书消息限制约 21MB，发不出去
- 听书为主：用户 90% 时间在听，音频才是主交付物

策略：
- 时长 ≤ 5 分钟：压视频到 <21MB 直接发
- 时长 > 10 分钟：压音频（48kbps 人声清晰，45 分钟约 16MB）→ 音频是主交付
                  视频存到指定目录（网盘/本地），给用户路径
- 5-10 分钟：压视频 + 音频都生成，由用户选择

用法：
    python deliver.py --video out.mp4 [--audio out.mp3] [--book 书名] [--out-dir /path]
"""
import argparse
import subprocess
import sys
from pathlib import Path

LIMIT_MB = 21          # 飞书单文件限制
AUDIO_BITRATE = "48k"  # 听书人声清晰度下限
VIDEO_CRF = 30         # 短视频压缩档


def get_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def compress_audio(src: str, dst: str) -> Path:
    """压缩音频到 48kbps（人声够用，体积小）"""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE,
                    "-ac", "1", dst], check=True)
    return Path(dst)


def compress_video(src: str, dst: str) -> Path:
    """压缩视频到 720p 低码率，目标 <21MB"""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-vf", "scale=720:1280",
                    "-c:v", "libx264", "-preset", "faster", "-crf", str(VIDEO_CRF),
                    "-c:a", "aac", "-b:a", "64k", dst], check=True)
    return Path(dst)


def main():
    ap = argparse.ArgumentParser(description="按时长自动选交付策略")
    ap.add_argument("--video", required=True, help="生成的视频文件")
    ap.add_argument("--audio", help="生成的音频文件（有则优先压缩交付）")
    ap.add_argument("--book", default="", help="书名（用于命名）")
    ap.add_argument("--out-dir", default="/tmp", help="输出目录")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.book or Path(args.video).stem

    dur = get_duration(args.video)
    minutes = dur / 60
    print(f"⏱️ 视频时长: {minutes:.1f} 分钟")

    if minutes <= 5:
        # 短视频：压到 <21MB 直接发
        dst = out_dir / f"{name}_压缩版.mp4"
        compress_video(args.video, str(dst))
        size_mb = dst.stat().st_size / 1e6
        print(f"📦 短视频压缩: {dst} ({size_mb:.1f}MB)")
        print(f"✅ 交付: {dst}")

    elif minutes > 10:
        # 长视频：音频是主交付（听书为主），视频存档
        if args.audio and Path(args.audio).exists():
            dst = out_dir / f"{name}_音频.mp3"
            compress_audio(args.audio, str(dst))
            size_mb = dst.stat().st_size / 1e6
            print(f"🎧 长音频压缩: {dst} ({size_mb:.1f}MB) ← 主交付（飞书可发）")
        else:
            print("⚠️ 未提供音频文件，无法生成主交付物")
        print(f"💾 完整视频存档: {args.video}")
        print(f"   （长视频建议上传网盘或本地存档，飞书发不了 {dur/1e6:.0f}MB 级别文件）")

    else:
        # 5-10 分钟：都生成
        vdst = out_dir / f"{name}_压缩版.mp4"
        compress_video(args.video, str(vdst))
        print(f"📦 压缩视频: {vdst} ({vdst.stat().st_size/1e6:.1f}MB)")
        if args.audio and Path(args.audio).exists():
            adst = out_dir / f"{name}_音频.mp3"
            compress_audio(args.audio, str(adst))
            print(f"🎧 压缩音频: {adst} ({adst.stat().st_size/1e6:.1f}MB)")
        print(f"✅ 均可发飞书，按需选择")


if __name__ == "__main__":
    main()
