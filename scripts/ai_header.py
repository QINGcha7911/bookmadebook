#!/usr/bin/env python3
"""
AI 片头生成器（bookmadebook）
================================
用途：为精读视频生成 AI 人物片头镜头（万相文生视频，5s / 原生1080P），
      自动补 25fps + 静音音轨 + AI 合规角标，可选直接拼接成片。

计费：通义万相 wan2.2-t2v-plus 1080P = ¥0.70/秒 → 5s = ¥3.5
      百炼新开通账号有 50 秒免费额度（先扣免费额度）

用法：
  # 1) 只生成片头（供后续手动拼接）
  python3 scripts/ai_header.py --book "万水千山走遍" --prompt "..." --out /tmp/header.mp4

  # 2) 生成并直接接到成片最前面（音频自动延迟对齐）
  python3 scripts/ai_header.py --book "万水千山走遍" --prompt "..." \
      --splice "成品视频/xxx.mp4" --out "成品视频/xxx_含AI片头.mp4"

  # 3) 复用已生成的片头（不重新扣费，只做拼接）
  python3 scripts/ai_header.py --reuse /tmp/header.mp4 --splice main.mp4 --out out.mp4
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path('/root/.hermes/.env')
DASHSCOPE_BASE = 'https://dashscope.aliyuncs.com/api/v1'
MODEL = 'wan2.2-t2v-plus'
SIZE = '1080*1920'
HEADER_FPS = 25
HEADER_AUDIO_RATE = 96000   # 与 bookmadebook 成片音轨一致（96kHz 单声道）
DEFAULT_DURATION = 5        # wan2.2-t2v-plus 固定 5s（不支持自定义时长）

# 百炼设计音色短名 → voice ID（与 streaming_pipeline.VOICE_ALIASES 保持一致）
VOICE_ALIASES = {
    'husky_tender': 'qwen-tts-vd-husky_tender-voice-20260821220323362-ebb0',      # 情感/散文
    'hist_deep_male': 'qwen-tts-vd-hist_deep_male-voice-20260821204552033-d7bc',  # 历史/传记
    'design_kid': 'qwen-tts-vd-design_kid-voice-20260821205612330-e42c',          # 儿童
}
VO_LEAD_MS = 500            # 旁白在片头内的起播延迟（留一点画面呼吸）


def log(msg):
    print(msg, flush=True)


def read_key():
    key = os.environ.get('DASHSCOPE_API_KEY', '')
    if len(key) > 10:
        return key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8', errors='ignore').splitlines():
            line = line.strip()
            if line.startswith('DASHSCOPE_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    raise SystemExit('❌ 找不到 DASHSCOPE_API_KEY（环境变量或 /root/.hermes/.env）')


# ---------------------------------------------------------------- 万相生成
def wan_generate(prompt, key, timeout_s=900):
    """提交万相文生视频任务并轮询下载，返回本地 mp4 路径"""
    def post(payload):
        h = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
             'X-DashScope-Async': 'enable'}
        req = urllib.request.Request(
            f'{DASHSCOPE_BASE}/services/aigc/video-generation/video-synthesis',
            data=json.dumps(payload).encode(), headers=h, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:400]

    st, resp = post({"model": MODEL, "input": {"prompt": prompt},
                     "parameters": {"size": SIZE, "prompt_extend": True}})
    if st != 200 or not isinstance(resp, dict) or not resp.get('output', {}).get('task_id'):
        raise SystemExit(f'❌ 万相提交失败 HTTP {st}: {resp}')
    tid = resp['output']['task_id']
    log(f'   📤 万相任务已提交 task_id={tid}（模型 {MODEL} / {SIZE}）')

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(10)
        req = urllib.request.Request(f'{DASHSCOPE_BASE}/tasks/{tid}',
                                     headers={'Authorization': f'Bearer {key}'})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode())
        except Exception as e:
            log(f'   ⏳ 轮询异常（重试）: {e}')
            continue
        status = d.get('output', {}).get('task_status', '?')
        if status == 'SUCCEEDED':
            url = d['output'].get('video_url')
            raw = '/tmp/ai_header_raw.mp4'
            urllib.request.urlretrieve(url, raw)
            use = d.get('usage', {})
            log(f'   ✅ 生成完成（用量 {use.get("video_duration", "?")}s × {use.get("video_count", 1)}）')
            return raw
        if status in ('FAILED', 'CANCELED'):
            raise SystemExit(f'❌ 万相生成失败: {json.dumps(d, ensure_ascii=False)[:300]}')
    raise SystemExit('❌ 万相生成超时')


# ---------------------------------------------------------------- 后处理
def make_badge(tmp_dir):
    """AI 合规角标 PNG（复用 text_layers.render_ai_badge，失败则自绘）"""
    out = Path(tmp_dir) / 'ai_badge.png'
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from text_layers import render_ai_badge  # noqa
        render_ai_badge().save(out)
        log('   🏷️  角标复用 text_layers.render_ai_badge')
    except Exception as e:
        log(f'   ⚠️  复用角标失败({e})，自绘')
        from PIL import Image, ImageDraw, ImageFont
        W, H = 1080, 1920
        img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fp = '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc'
        font = ImageFont.truetype(fp, 26)
        text = 'AI 生成内容'
        tw = d.textlength(text, font=font)
        pad_x, pad_y, margin = 20, 10, 36
        x1, y1 = W - margin - tw - pad_x * 2, H - margin - 26 - pad_y * 2
        d.rounded_rectangle([x1, y1, W - margin, H - margin], radius=10,
                            fill=(0, 0, 0, 110))
        d.text((x1 + pad_x, y1 + pad_y), text, font=font, fill=(255, 255, 255, 235))
        img.save(out)
    return out


def build_header(raw, out, tmp_dir='/tmp'):
    """raw 生成的视频 → 25fps + 静音 + AI 角标"""
    badge = make_badge(tmp_dir)
    vf = (f'fps={HEADER_FPS},scale=1080:1920,setsar=1[base];'
          f'[base][1:v]overlay=0:0:format=auto[v]')
    cmd = ['ffmpeg', '-y', '-v', 'error', '-i', raw, '-i', str(badge),
           '-f', 'lavfi', '-t', str(DEFAULT_DURATION), '-i',
           f'anullsrc=r={HEADER_AUDIO_RATE}:cl=mono',
           '-filter_complex', vf,
           '-map', '[v]', '-map', '2:a',
           '-c:v', 'libx264', '-crf', '16', '-preset', 'medium', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '128k', '-ac', '1', '-shortest',
           '-movflags', '+faststart', out]
    subprocess.run(cmd, check=True, timeout=600)
    log(f'   🎬 片头完成（25fps + 静音 + AI角标）: {out}')
    return out


def tts_vo(text, voice, out_wav):
    """生成片头旁白（复用 voice_design.py 的百炼 Qwen3-TTS 设计音色）"""
    vid = VOICE_ALIASES.get(voice, voice)   # 短名或完整 voice ID 均可
    script = Path(__file__).resolve().parent / 'voice_design.py'
    if not script.exists():
        raise SystemExit(f'❌ 找不到 {script}（生成旁白需要）')
    log(f'   🎙️  生成旁白（{voice}）: {text}')
    subprocess.run(['python3', str(script), 'synth', '--voice', vid,
                    '--text', text, '--out', out_wav], check=True, timeout=600)
    return out_wav


def splice(header, main, out, vo_wav=None):
    """片头 + 成片拼接。

    有 vo_wav（旁白）时：旁白铺在片头 5s 内，再与正文音轨直接 concat
      → 片头有声音（报书名），正文音轨一次未动，风格统一。
    无 vo_wav 时：沿用旧的「静音片头 + 正文音轨延迟」方式。
    """
    for label, p in (('片头', header), ('成片', main)):
        if not os.path.exists(p):
            raise SystemExit(f'❌ 找不到{label}文件: {p}\n'
                             f'   提示: 相对路径基于当前工作目录；跨目录请用绝对路径')
    if vo_wav and not os.path.exists(vo_wav):
        raise SystemExit(f'❌ 找不到旁白文件: {vo_wav}')
    dur = float(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', header], capture_output=True, text=True).stdout.strip() or 5.02)
    delay_ms = int(round(dur * 1000))
    # 主片音轨参数（保持原样）
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
         'stream=sample_rate,channels', '-of', 'csv=p=0', main],
        capture_output=True, text=True).stdout.strip()
    rate, ch = (probe.split(',') + ['48000', '1'])[:2] if probe else ('48000', '1')
    delay = f'{delay_ms}' if ch == '1' else f'{delay_ms}|{delay_ms}'
    # 铁律：视频流时长必须 >= 音频流（防播放器提前停）。
    # concat 后视频流常比音频流短零点几秒（尾帧时长截断），用 tpad 冻结末帧补齐。
    if vo_wav:
        # 旁白铺满片头段（起播留 VO_LEAD_MS），再与正文音轨 concat —— 正文音轨不被改动
        fc = (f'[0:v][1:v]concat=n=2:v=1:a=0[v];'
              f'[v]tpad=stop_mode=clone:stop_duration=0.4[vt];'
              f'[2:a]adelay={VO_LEAD_MS},apad,atrim=0:{dur},aresample={rate}[vo5];'
              f'[1:a]aresample={rate}[mn];'
              f'[vo5][mn]concat=n=2:v=0:a=1[a]')
        inputs = ['-i', header, '-i', main, '-i', vo_wav]
        log(f'   🔗 拼接中（片头 {dur:.2f}s + 书名旁白 + 正文音轨，主片 {rate}Hz/{ch}ch）...')
    else:
        fc = (f'[0:v][1:v]concat=n=2:v=1:a=0[v];'
              f'[v]tpad=stop_mode=clone:stop_duration=0.4[vt];'
              f'[1:a]adelay={delay},aresample={rate}[a]')
        inputs = ['-i', header, '-i', main]
        log(f'   🔗 拼接中（片头 {dur:.2f}s → 音轨延迟 {delay_ms}ms，主片音轨 {rate}Hz/{ch}ch）...')
    cmd = ['ffmpeg', '-y', '-v', 'error'] + inputs + [
           '-filter_complex', fc, '-map', '[vt]', '-map', '[a]',
           '-c:v', 'libx265', '-crf', '23', '-preset', 'faster', '-tag:v', 'hvc1',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
           '-movflags', '+faststart', out]
    subprocess.run(cmd, check=True, timeout=3600)
    log(f'   ✅ 完整版: {out}')
    return out


def main():
    ap = argparse.ArgumentParser(description='bookmadebook AI 片头生成器')
    ap.add_argument('--book', help='书名（记录用）')
    ap.add_argument('--prompt', help='视频描述（中文）')
    ap.add_argument('--reuse', help='复用已生成的片头 mp4（不重新生成，不扣费）')
    ap.add_argument('--out', required=True, help='输出路径')
    ap.add_argument('--splice', help='可选：要拼接的成片路径')
    ap.add_argument('--header-out', default='/tmp/ai_header.mp4', help='纯片头输出路径')
    ap.add_argument('--vo-text', help='片头旁白文本（如「三毛。万水千山走遍。」）；给了就自动配人声')
    ap.add_argument('--vo-voice', default='husky_tender',
                    help='旁白音色：husky_tender(情感/散文) | hist_deep_male(历史) | design_kid(儿童)')
    ap.add_argument('--vo-file', help='直接用现成旁白音频（跳过 TTS）')
    args = ap.parse_args()

    if args.reuse:
        header = args.reuse
        log(f'♻️  复用片头: {header}')
    else:
        if not args.prompt:
            raise SystemExit('❌ 需要 --prompt（或 --reuse）')
        key = read_key()
        log(f'🎬 生成 AI 片头{("《" + args.book + "》") if args.book else ""}')
        raw = wan_generate(args.prompt, key)
        header = build_header(raw, args.header_out)

    # 片头旁白（报书名，与正文同款音色 —— 避免开场 5s 死寂）
    vo_wav = None
    if args.vo_file:
        vo_wav = args.vo_file
    elif args.vo_text:
        vo_wav = tts_vo(args.vo_text, args.vo_voice,
                        os.path.splitext(args.header_out)[0] + '_vo.wav')

    if args.splice:
        splice(header, args.splice, args.out, vo_wav=vo_wav)
    else:
        if header != args.out:
            subprocess.run(['cp', header, args.out], check=True)
        log(f'✅ 片头已输出: {args.out}')
        if vo_wav:
            log(f'   旁白已生成: {vo_wav}（拼接时用 --vo-file 传入）')


if __name__ == '__main__':
    main()
