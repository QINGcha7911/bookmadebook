#!/usr/bin/env python3
"""QSV 硬件编码器 —— 用 Windows 侧 ffmpeg.exe (Intel Arc Quick Sync) 加速高清交付

背景（2026-09-07 定案）：
- 10min 精读视频 x265 软编 15-18min → QSV 硬编 ~4min（实测 30s 片 16.3s→4.5s，3.6 倍）
- WSL 内无 /dev/dri（GPU 走 DX 半虚拟化），但 Windows 侧 ffmpeg 8.1.2 带 hevc_qsv 可用
- 画质验证：CFR 对齐后 PSNR 49.28 vs 49.31 / SSIM 0.9927 vs 0.9925（x265 vs QSV q18 持平）

用法:
    python qsv_encode.py <input.mp4> <output.mp4> [--bitrate 2M] [--quality 18]
        --bitrate  定码率模式（等效 x265 -b:v 2M 交付规格）
        --quality  ICQ 质量模式 18≈2.1Mbps（默认），画质优先自适应码率

自动回退：找不到 Windows ffmpeg 或编码失败 → 用本机 libx265 软编保底。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_windows_ffmpeg() -> str | None:
    """定位 Windows ffmpeg.exe（含 hevc_qsv）。找不到返回 None。"""
    exe = shutil.which("ffmpeg.exe")
    if not exe:
        return None
    # 确认含 qsv 编码器
    try:
        r = subprocess.run([exe, "-hide_banner", "-encoders"],
                           capture_output=True, text=True, timeout=30)
        return exe if "hevc_qsv" in r.stdout else None
    except Exception:
        return None


def to_windows_path(p: str) -> str:
    """WSL 路径 → Windows 路径（ffmpeg.exe 只认 Windows 路径）"""
    r = subprocess.run(["wslpath", "-w", p], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else p


def probe_stream_durations(src: str) -> tuple[float, float]:
    """返回 (视频流时长, 音频流时长)；探测失败返回 (0.0, 0.0)。

    2026-09-11 新增：成片交付铁律「视频流时长 ≥ 音频流时长」。
    composer 合成用 -shortest，若视频帧尾比音频早 3 帧（实测 639.88s vs 640.00s）
    就会出现 0.12s 缺口。转码时用 tpad 冻结末帧补齐 + -t 兜底，
    保证播放器不会在片尾 AI 声明结束前停画面。
    """
    v = a = 0.0
    for stream, key in (("v:0", "v"), ("a:0", "a")):
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", stream,
             "-show_entries", "stream=duration", "-of", "csv=p=0", src],
            capture_output=True, text=True, timeout=60)
        try:
            d = float(r.stdout.strip().split(",")[0])
        except Exception:
            d = 0.0
        if key == "v":
            v = d
        else:
            a = d
    if v <= 0 or a <= 0:  # 流时长缺失时退回容器时长
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", src],
                           capture_output=True, text=True, timeout=60)
        try:
            total = float(r.stdout.strip())
        except Exception:
            total = 0.0
        v = v or total
        a = a or total
    return v, a


def qsv_encode(src: str, dst: str, bitrate: str = "2M", quality: int = 26,
               ffmpeg_exe: str | None = None) -> bool:
    """用 Windows ffmpeg.exe + hevc_qsv 编码。成功返回 True。"""
    exe = ffmpeg_exe or find_windows_ffmpeg()
    if not exe:
        print("  ⚠️ 未找到 Windows ffmpeg.exe（含 hevc_qsv），回退软编")
        return False
    src_w = to_windows_path(os.path.abspath(src))
    dst_w = to_windows_path(os.path.abspath(dst))
    # ICQ 质量模式。quality 26≈2Mbps≈164MB/10min（2026-09-07 真实 10min 视频标定，
    # 与交付规格 x265 2Mbps ≈160MB 对齐；测试片简单场景 q18≈2.1M 会低估真实码率）
    # -c:a copy：保留原音频流，勿重编码（门禁响度/时长检查依赖原音频）
    # -map_metadata -1 -map_chapters -1：丢弃源 mp4 的 encd/chapter 元数据引用，
    #   否则 Windows muxer 会打成一条超长 bin_data 伪轨（实测 668s vs 正片 619s），
    #   播放器 seek 拖动时时间轴被干扰 → 音画不同步（2026-09-07 用户实测反馈）
    # 视频流时长 ≥ 音频流时长兜底（2026-09-11 铁律）：缺口时 tpad 冻结末帧补齐
    v_dur, a_dur = probe_stream_durations(src)
    vf_args = []
    if a_dur and v_dur and v_dur < a_dur + 0.05:
        pad = round(a_dur - v_dur + 0.25, 2)
        vf_args = ["-vf", f"tpad=stop_mode=clone:stop_duration={pad}",
                   "-t", f"{a_dur + 0.15:.2f}"]
        print(f"  🩹 视频流 {v_dur:.2f}s < 音频流 {a_dur:.2f}s → tpad 补 {pad}s 冻结末帧")
    cmd = [exe, "-y", "-v", "error", "-i", src_w,
           "-map", "0:v:0", "-map", "0:a:0", *vf_args,
           "-map_metadata", "-1", "-map_chapters", "-1",
           "-c:v", "hevc_qsv", "-global_quality", str(quality),
           "-c:a", "copy", "-preset", "medium",
           "-movflags", "+faststart", dst_w]
    print(f"  ⚡ QSV 硬编: ... -global_quality {quality} (≈2Mbps/10min 规格)")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    except Exception as exc:
        print(f"  ⚠️ QSV 编码异常: {exc}")
        return False
    if r.returncode != 0:
        print(f"  ⚠️ QSV 编码失败: {r.stderr[-300:]}")
        return False
    return True


def soft_encode(src: str, dst: str, bitrate: str = "2M") -> bool:
    """回退：本机 libx265 软编（等价旧流程 x265 2Mbps）

    与 qsv_encode 保持一致：视频流时长 < 音频流时 tpad 冻结末帧补齐，
    保证「视频流 ≥ 音频流」铁律在回退路径同样成立（2026-09-11）。
    """
    v_dur, a_dur = probe_stream_durations(src)
    vf_args = []
    if a_dur and v_dur and v_dur < a_dur + 0.05:
        pad = round(a_dur - v_dur + 0.25, 2)
        vf_args = ["-vf", f"tpad=stop_mode=clone:stop_duration={pad}",
                   "-t", f"{a_dur + 0.15:.2f}"]
        print(f"  🩹 视频流 {v_dur:.2f}s < 音频流 {a_dur:.2f}s → tpad 补 {pad}s 冻结末帧")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, *vf_args,
           "-c:v", "libx265", "-preset", "medium",
           "-b:v", bitrate, "-maxrate", bitrate,
           "-bufsize", f"{int(float(bitrate[:-1]) * 1000) * 2}k",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst]
    print(f"  🐢 x265 软编回退: {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        print(f"  ❌ 软编失败: {r.stderr[-300:]}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="QSV 硬件编码器（Arc 加速 x265）")
    ap.add_argument("input", help="输入视频（中间档）")
    ap.add_argument("output", help="输出视频（高清交付档）")
    ap.add_argument("--bitrate", default="2M", help="码率（回退软编用）")
    ap.add_argument("--quality", type=int, default=26, help="QSV ICQ 质量（26≈2Mbps/10min 交付规格）")
    args = ap.parse_args()

    exe = find_windows_ffmpeg()
    if exe:
        print(f"🎯 检测到 Windows ffmpeg: {exe}")
        ok = qsv_encode(args.input, args.output, args.bitrate, args.quality, exe)
        if ok:
            print(f"✅ QSV 编码完成: {args.output}")
            return
    print("🔄 回退 x265 软编...")
    if soft_encode(args.input, args.output, args.bitrate):
        print(f"✅ 软编完成: {args.output}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
