# -*- coding: utf-8 -*-
"""独立 CosyVoice 精读音频生成（绕过 streaming_pipeline 集成问题）

流程：读讲书稿 → 清理标注 → 分段(≈250字) → CosyVoice SDK 逐段合成 → ffmpeg 拼接
用法: python gen_cosy.py <讲书稿.txt> <输出.mp3>
"""
import sys, re, os, tempfile, time, subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def load_key():
    for p in [Path.home() / r"AppData\Local\hermes\.env",
              Path(r"C:\Users\dongj\AppData\Local\hermes\.env")]:
        if p.exists():
            for line in open(p, encoding="utf-8"):
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DASHSCOPE_API_KEY", "")

def clean_marks(text: str) -> str:
    """清理【标注】（停顿/情绪/金句/场景/章节），保留文本内容"""
    # 金句保留内容（去掉【金句】外壳）
    text = re.sub(r"【金句】\s*[“\"']?(.*?)[”\"']?", r"\1", text)
    # 其他标注整段删除（停顿/情绪/场景/章节等）
    text = re.sub(r"【[^】]*】", "", text)
    # 清理 markdown 符号
    text = re.sub(r"[#*`>|]", "", text)
    return text.strip()

def split_into_chunks(text: str, target: int = 250) -> list:
    """按段落合并到 ~target 字"""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > target and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n" + p).strip()
    if cur:
        chunks.append(cur)
    return chunks

def synth(chunk: str, out: Path, idx: int, total: int, synthesizer) -> bool:
    for attempt in range(3):
        try:
            audio = synthesizer.call(chunk)
            if audio:
                out.write_bytes(audio)
                return True
        except Exception as e:
            print(f"  [{idx}/{total}] 重试{attempt+1}: {str(e)[:100]}", flush=True)
        time.sleep(4)
    return False

def main():
    script_path, out_path = sys.argv[1], sys.argv[2]
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    dashscope.api_key = load_key()
    if not dashscope.api_key:
        print("ERROR: DASHSCOPE_API_KEY 未找到"); sys.exit(1)

    # m1 男声参数（用户认可：longxiang 低沉）
    synthesizer = SpeechSynthesizer(model="cosyvoice-v1", voice="longxiang",
                                    pitch_rate=0.85, speech_rate=0.95)

    text = open(script_path, encoding="utf-8").read()
    clean = clean_marks(text)
    chunks = split_into_chunks(clean)
    print(f"分段完成: {len(chunks)} 段, 共 {len(clean)} 字", flush=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="cosy_gen_"))
    segs = []
    ok_count = 0
    for i, ch in enumerate(chunks, 1):
        seg = tmpdir / f"seg_{i:03d}.mp3"
        if synth(ch, seg, i, len(chunks), synthesizer):
            segs.append(str(seg))
            ok_count += 1
            print(f"  [{i}/{len(chunks)}] OK ({len(ch)}字)", flush=True)
        else:
            print(f"  [{i}/{len(chunks)}] ❌ 失败，跳过", flush=True)

    if not segs:
        print("全部失败"); sys.exit(1)
    print(f"合成成功 {ok_count}/{len(chunks)}，开始拼接...", flush=True)
    concat_file = tmpdir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{s}'" for s in segs), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat_file), "-c", "copy", out_path],
        capture_output=True, text=True, timeout=600,
    )
    if r.returncode == 0 and Path(out_path).exists():
        print(f"✅ 完成: {out_path}", flush=True)
    else:
        print(f"拼接失败: {r.stderr[:200]}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
