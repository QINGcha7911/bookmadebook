#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voice_design.py — 阿里百炼 Qwen3-TTS「声音设计」API 封装
========================================================
用文字描述生成任意中文音色（无需音频样本），永久保存 voice ID，
后续用该 ID 合成任意文本的语音。

用法：
  # 1) 设计新音色（返回 voice ID + 预览音频）
  python voice_design.py create --name my_voice --prompt "沉稳厚重的老年男声..." \
      --preview "测试文本" [--out preview.wav]

  # 2) 用已设计音色合成语音（非流式，返回音频文件）
  python voice_design.py synth --voice <VOICE_ID> --text "要合成的文本" --out out.wav

  # 3) 列出已创建的所有音色
  python voice_design.py list

  # 4) 删除音色
  python voice_design.py delete --voice <VOICE_ID>

环境变量：DASHSCOPE_API_KEY（百炼 key，北京地域；.env 或 config.yaml）
北京地域端点：https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization
新加坡地域：https://dashscope-intl.aliyuncs.com/api/v1/services/audio/tts/customization（key 需新加坡地域）

声音描述要点（voice_prompt）：
  - 中文/英文描述，Qwen3-TTS 最长 2048 字符，CosyVoice 最长 500
  - 描述越具体越好：性别/年龄/音色特质（沙哑、磁性、清亮）/语调/情绪/适用场景
  - 例："温柔抒情的女声，带一点沙哑的烟嗓质感，音色低沉磁性，慵懒而深情，
         像深夜电台女主持在轻声讲述故事，语速舒缓，治愈又迷人，适合抒情散文和治愈系小说"
  - 不满意就改描述重新 create（每次 create 生成新 voice ID）
"""
import argparse
import base64
import json
import os
import subprocess
import sys

import requests

# 默认端点（北京地域）
DEFAULT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
# 语音合成端点（非流式，返回音频 URL，北京地域）
SYNTH_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
# 声音设计模型（create 用）
DESIGN_MODEL = "qwen-voice-design"
# 目标语音合成模型（create 的 target_model / synth 的 model）
SYNTH_MODEL = "qwen3-tts-vd-2026-01-26"


def get_api_key():
    """从环境变量 / .env / config.yaml 依次找百炼 key"""
    key = os.environ.get("DASHSCOPE_API_KEY")
    if key:
        return key.strip()
    # .env
    env_paths = [os.path.expanduser("~/.hermes/.env")]
    for p in env_paths:
        if os.path.exists(p):
            for line in open(p, encoding="utf-8", errors="ignore"):
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    # config.yaml
    cfg_path = os.path.expanduser("~/.hermes/config.yaml")
    if os.path.exists(cfg_path):
        try:
            import yaml
            cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
            for p in cfg.get("custom_providers", []):
                if "dashscope" in str(p.get("base_url", "")):
                    k = p.get("api_key")
                    if k and not k.startswith("***"):
                        return k
        except Exception:
            pass
    raise SystemExit("错误: 找不到 DASHSCOPE_API_KEY（请设置环境变量或写入 ~/.hermes/.env）")


def api_call(payload, timeout=120):
    key = get_api_key()
    resp = requests.post(
        DEFAULT_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    data = resp.json()
    if "code" in data and data["code"] not in ("", None):
        raise SystemExit(f"API 错误 {data['code']}: {data.get('message', '')}")
    return data


def cmd_create(args):
    payload = {
        "model": DESIGN_MODEL,
        "input": {
            "action": "create",
            "target_model": SYNTH_MODEL,
            "preferred_name": args.name,
            "voice_prompt": args.prompt,
            "preview_text": args.preview,
        },
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }
    data = api_call(payload)
    out = data.get("output", {})
    voice_id = out.get("voice", "")
    print(f"✅ 音色已创建: {voice_id}")
    b64 = out.get("preview_audio", {}).get("data", "")
    if b64:
        wav = base64.b64decode(b64)
        out_path = args.out or f"{args.name}_preview.wav"
        with open(out_path, "wb") as f:
            f.write(wav)
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
            capture_output=True, text=True,
        ).stdout.strip()
        print(f"🎧 预览音频已保存: {out_path} ({dur}s)")
    return voice_id


def cmd_synth(args):
    payload = {
        "model": SYNTH_MODEL,
        "input": {"text": args.text, "voice": args.voice},
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }
    key = get_api_key()
    resp = requests.post(
        SYNTH_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=300,
    )
    data = resp.json()
    if "code" in data and data["code"] not in ("", None):
        raise SystemExit(f"API 错误 {data['code']}: {data.get('message', '')}")
    out = data.get("output", {})
    # 非流式返回音频 URL（24 小时有效）
    url = out.get("audio", {}).get("url", "")
    if url:
        r = requests.get(url, timeout=300)
        with open(args.out, "wb") as f:
            f.write(r.content)
        print(f"✅ 音频已保存: {args.out}")
        return
    print("⚠️ 未直接返回音频，响应:", json.dumps(data, ensure_ascii=False)[:400])


def cmd_list(args):
    data = api_call({"model": DESIGN_MODEL, "input": {"action": "list", "page_size": 50}})
    voices = data.get("output", {}).get("voice_list", [])
    print(f"共 {data.get('output', {}).get('total_count', 0)} 个音色:")
    for v in voices:
        name = v.get("voice", "").split("-voice-")[0].replace("qwen-tts-vd-", "")
        print(f"  {name:20s} | {v['voice']}")
        print(f"    prompt: {v.get('voice_prompt', '')[:60]}")


def cmd_delete(args):
    data = api_call({"model": DESIGN_MODEL, "input": {"action": "delete", "voice": args.voice}})
    print("✅ 已删除:", args.voice)


def main():
    ap = argparse.ArgumentParser(description="阿里百炼 Qwen3-TTS 声音设计 API")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create", help="设计新音色")
    p.add_argument("--name", required=True, help="音色名（短，如 husky_female2）")
    p.add_argument("--prompt", required=True, help="声音描述（中文，越具体越好）")
    p.add_argument("--preview", required=True, help="预览文本（生成的预览音频会读这段）")
    p.add_argument("--out", default=None, help="预览音频输出路径")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("synth", help="用音色合成语音")
    p.add_argument("--voice", required=True, help="voice ID")
    p.add_argument("--text", required=True, help="要合成的文本")
    p.add_argument("--out", required=True, help="输出 wav 路径")
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("list", help="列出所有音色")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="删除音色")
    p.add_argument("--voice", required=True)
    p.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
