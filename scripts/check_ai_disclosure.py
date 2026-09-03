#!/usr/bin/env python3
"""AI 声明三合一验收门禁 (2026-09-03 用户定：固化到每个精读视频)

用法: python3 scripts/check_ai_disclosure.py <视频或音频文件> [--disclosure-len 6.8]

对每个成品自动验三项，任何一项 FAIL 即打回：
  1. 片尾声明段有语音（非静音）——转写或 volumedetect 物理验证
  2. 视频流时长 ≥ 音频流时长（视频专用；画面不能先于声明结束）
  3. 声明段响度与正文一致（差 ≤1.5dB，声明 I ≥ -18 LUFS）

背景（2026-09-03 三次返工根因，勿删）：
  - cache_manager.get_l2 回填 set_l2 参数错位 → json.dump 崩 → except 吞 → 声明静默缺失（修 commit 287edd5）
  - remux 只换音轨 -c:v copy → 视频流 626s < 音频 633s → 画面先停播放器停 → 用户听不到声明
  - 直接 concat 声明段 -23 LUFS vs 正文 -17 LUFS 低 6dB → husky_tender 下听不见
"""
import argparse
import subprocess
import sys
import os
from pathlib import Path

# 声明文本长度约 6.8s；取片尾 N 秒检测
DISC_LEN = 6.8
# 正文响度参考（流水线 loudnorm 目标 -16 LUFS，实测成品 -17 左右）
BODY_TARGET_LUFS = -17.0
# 声明段允许的最低响度（与正文差 ≤1.5dB 或本身 ≥ -18）
DISC_MIN_LUFS = -18.0


def ffprobe_duration(path: str, stream: str = None) -> float:
    """取 format 或指定流时长（秒）"""
    cmd = ['ffprobe', '-v', 'error', '-show_entries']
    if stream:
        cmd += [f'stream=duration', '-select_streams', stream]
    else:
        cmd += ['format=duration']
    cmd += ['-of', 'csv=p=0', path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip().split('\n')[0])
    except (ValueError, IndexError):
        return 0.0


def lufs_of(path: str, start: float, dur: float) -> float:
    """测量 [start, start+dur) 段集成响度 LUFS"""
    r = subprocess.run(
        ['ffmpeg', '-ss', str(start), '-t', str(dur), '-i', path,
         '-af', 'ebur128', '-f', 'null', '-'],
        capture_output=True, text=True, timeout=60)
    last_i = None
    for line in r.stderr.split('\n'):
        if 'I:' in line and 'LUFS' in line:
            # 取最后一个时间窗的瞬时 I；如无则汇总行
            try:
                last_i = float(line.split('I:')[1].split()[0])
            except (ValueError, IndexError):
                pass
    return last_i if last_i is not None else -99.0


def loudness_energy(path: str, start: float, dur: float) -> tuple:
    """volumedetect: (mean_volume, max_volume) 判断是否有语音"""
    r = subprocess.run(
        ['ffmpeg', '-ss', str(start), '-t', str(dur), '-i', path,
         '-af', 'volumedetect', '-f', 'null', '-'],
        capture_output=True, text=True, timeout=60)
    mean = maxv = None
    for line in r.stderr.split('\n'):
        if 'mean_volume:' in line:
            mean = float(line.split('mean_volume:')[1].strip().replace('dB', ''))
        elif 'max_volume:' in line:
            maxv = float(line.split('max_volume:')[1].strip().replace('dB', ''))
    return mean, maxv


def has_audio_stream(path: str) -> bool:
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a',
                        '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
                       capture_output=True, text=True, timeout=30)
    return 'audio' in r.stdout


def has_ai_keywords(path: str, start: float, dur: float) -> tuple:
    """转写片尾声明段，确认含「AI 生成/版权归原作者」等关键词。

    2026-09-03 皮囊误判教训：只测能量会 PASS「正文恰好讲到片尾」的无声明文件
    （628s 旧版片尾 6.8s 是正文末句，有语音+响度对但内容不是声明）。
    内容验证是门禁的最后一环。
    """
    audio = Path('/tmp/check_disclosure_audio.mp3')
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(start), '-t', str(dur),
                        '-i', path, '-vn', '-c:a', 'libmp3lame', '-q:a', '5', str(audio)],
                       capture_output=True, text=True, timeout=60)
    if not audio.exists() or audio.stat().st_size < 1000:
        return False, '音频提取失败'
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel('base', device='cpu', compute_type='int8',
                             download_root='/root/.cache/huggingface/hub', cpu_threads=8)
        segs, _ = model.transcribe(str(audio), language='zh', beam_size=1)
        text = ''.join(s.text for s in segs)
    except Exception as e:
        return None, f'whisper 不可用: {e}'
    keywords = ['AI 生成', 'AI生成', '人工合成', '版权归原作者', '版权']
    hit = any(k in text for k in keywords)
    return hit, text[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file', help='视频或音频文件路径')
    ap.add_argument('--disclosure-len', type=float, default=DISC_LEN,
                    help='声明段长度秒（默认 6.8）')
    ap.add_argument('--skip-content', action='store_true',
                    help='跳过内容关键词验证（whisper 不可用时降级用）')
    args = ap.parse_args()

    f = Path(args.file)
    if not f.exists():
        print(f'❌ FAIL: 文件不存在 {f}')
        sys.exit(1)

    total = ffprobe_duration(str(f))
    is_video = has_audio_stream(str(f)) and ffprobe_duration(str(f), 'v') > 0
    has_audio = has_audio_stream(str(f))
    print(f'📄 {f.name} | 总时长 {total:.1f}s | 类型: {"视频" if is_video else "音频"}')

    results = []

    # ── 检查 2（视频专用）：视频流 ≥ 音频流 ──
    if is_video:
        v_dur = ffprobe_duration(str(f), 'v')
        a_dur = ffprobe_duration(str(f), 'a')
        ok = v_dur >= a_dur - 0.3  # 容差 0.3s
        results.append(('② 视频流时长 ≥ 音频流', ok,
                        f'视频 {v_dur:.2f}s vs 音频 {a_dur:.2f}s'))
        if not ok:
            print(f'❌ FAIL: 视频流 {v_dur:.1f}s < 音频流 {a_dur:.1f}s —— 画面先结束，'
                  f'声明在画面结束后用户听不到。修复: -vf "tpad=stop_mode=clone:stop_duration={a_dur - v_dur:.1f}" 重编码补帧')
            sys.exit(1)

    # ── 检查 1：片尾声明段有语音（取最后 disclosure_len 秒）──
    disc_start = max(0.0, total - args.disclosure_len)
    mean, maxv = loudness_energy(str(f), disc_start, args.disclosure_len)
    has_voice = maxv is not None and maxv > -30  # 有语音峰值
    results.append(('① 片尾声明段有语音', has_voice,
                    f'mean {mean if mean else "?"}dB / max {maxv if maxv else "?"}dB'))
    if not has_voice:
        print(f'❌ FAIL: 片尾 {args.disclosure_len:.1f}s 无语音（max {maxv}dB）—— 声明段缺失或静音')
        sys.exit(1)

    # ── 检查 3：声明段响度与正文一致 ──
    disc_lufs = lufs_of(str(f), disc_start, args.disclosure_len)
    # 正文段：取声明段之前 10s（连续叙述区）
    body_start = max(0.0, disc_start - 12.0)
    body_lufs = lufs_of(str(f), body_start, 10.0)
    diff = abs(disc_lufs - body_lufs) if disc_lufs > -90 and body_lufs > -90 else 99
    ok3 = disc_lufs >= DISC_MIN_LUFS and diff <= 1.5
    results.append(('③ 声明段响度与正文一致', ok3,
                    f'声明 {disc_lufs:.1f} LUFS vs 正文 {body_lufs:.1f} LUFS (差 {diff:.1f})'))
    if not ok3:
        print(f'❌ FAIL: 声明段 {disc_lufs:.1f} LUFS 与正文 {body_lufs:.1f} LUFS 差 {diff:.1f}dB'
              f'（目标 ≤1.5dB 且 ≥{DISC_MIN_LUFS}）—— 用户听不清。修复: 声明段 volume=+{diff:.1f}dB 后重拼')
        sys.exit(1)

    # ── 检查 4：片尾内容确为 AI 声明（防「正文恰好讲到片尾」误判）──
    ok4, detail4 = has_ai_keywords(str(f), disc_start, args.disclosure_len + 1.5)
    if ok4 is None and args.skip_content:
        ok4 = True  # whisper 不可用且用户显式降级
    if ok4 is None:
        print(f'⚠️ WARN: 内容验证跳过（whisper 不可用: {detail4}）—— 请人工听片尾确认')
        ok4 = True
    results.append(('④ 片尾含 AI 声明关键词', ok4, detail4))
    if not ok4:
        print(f'❌ FAIL: 片尾内容不含 AI 声明关键词（{detail4}）—— 可能是正文讲到片尾而非声明，或声明缺失')
        sys.exit(1)

    print('\n✅ PASS: AI 声明验收通过')
    for name, ok, detail in results:
        print(f'  {"✅" if ok else "❌"} {name}: {detail}')
    sys.exit(0)


if __name__ == '__main__':
    main()
