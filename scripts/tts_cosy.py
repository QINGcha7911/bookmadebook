#!/usr/bin/env python3
"""CosyVoice TTS 封装（兼容 edge-tts 命令行风格，供 streaming_pipeline 调用）

用法:
    python tts_cosy.py --voice longxiang --pitch -8Hz --rate -5% --text 文本 --output out.mp3
    python tts_cosy.py --voice longxiang --text-file in.txt --output out.mp3

参数说明:
    --voice   CosyVoice 预设音色（longxiang 等）或自定义克隆音色 ID
    --pitch   音调调整（-8Hz 表示降 8Hz，cosyvoice 用 pitch_rate 换算）
    --rate    语速调整（-5% 表示降 5%）
"""
import argparse, os, sys

def load_key():
    for p in [os.path.expanduser(r"~\AppData\Local\hermes\.env"),
              r"C:\Users\dongj\AppData\Local\hermes\.env"]:
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DASHSCOPE_API_KEY", "")

def parse_hz(s):
    """'-8Hz' → 0.85（pitch_rate）"""
    try:
        v = float(s.replace("Hz", "").replace("%", "").strip("+"))
        return 1 + v / 50  # cosyvoice pitch_rate：1.0 基准，-8Hz→0.84
    except Exception:
        return 1.0

def parse_rate(s):
    """'-5%' → 0.95（speech_rate）"""
    try:
        v = float(s.replace("%", "").strip("+"))
        return 1 + v / 100
    except Exception:
        return 1.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="longxiang")
    ap.add_argument("--pitch", default="+0Hz")
    ap.add_argument("--rate", default="+0%")
    ap.add_argument("--text")
    ap.add_argument("--text-file")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    text = args.text
    if not text and args.text_file:
        text = open(args.text_file, encoding="utf-8").read()
    if not text:
        print("ERROR: no text", file=sys.stderr); sys.exit(1)

    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    dashscope.api_key = load_key()
    if not dashscope.api_key:
        print("ERROR: DASHSCOPE_API_KEY 未找到", file=sys.stderr); sys.exit(1)

    pitch_rate = parse_hz(args.pitch)
    speech_rate = parse_rate(args.rate)
    # 2026-08-17 加重试：dashscope websocket 间歇失败（Connection/Timeout），重试 3 次
    last_err = ""
    for attempt in range(3):
        try:
            s = SpeechSynthesizer(model="cosyvoice-v1", voice=args.voice,
                                  pitch_rate=pitch_rate, speech_rate=speech_rate)
            audio = s.call(text)
            if audio:
                with open(args.output, "wb") as f:
                    f.write(audio)
                print(f"OK: {args.output}")
                sys.exit(0)
            last_err = "no audio returned"
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < 2:
                import time
                time.sleep(3 * (attempt + 1))
    print(f"ERROR: {last_err}", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
