#!/usr/bin/env python3
"""listen-book 流式流水线 v2 — 分段生成+截断检测+友好错误

修复内容：
1. 分段生成：单段不超过3000字（防 edge-tts 静默截断）
2. 截断检测：检测到 600s/900s 边界时警告
3. 友好错误：断网/失败时给出中文提示而非 traceback
"""
import asyncio, subprocess, json, os, sys, time, hashlib, re
from pathlib import Path

CACHE_DIR = Path(os.path.expanduser("~/.hermes/cache/listen-book"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# edge-tts 单段安全上限（字符）
MAX_SEGMENT_CHARS = 3000
# edge-tts 已知截断边界（秒）
TRUNCATION_BOUNDARIES = [600, 900, 1200, 1800]

class BookToAudioError(Exception):
    """技能内自定义错误，用于友好提示"""
    pass

def friendly_error(e: Exception) -> str:
    """把异常转成中文友好提示"""
    msg = str(e)
    if "NoAudioReceived" in msg or "Connection" in msg or "Timeout" in msg:
        return "⚠️ 语音服务连接失败。请检查网络后重试（如果网络不稳定，可稍后再试）。"
    if "ffprobe" in msg or "ffmpeg" in msg:
        return "⚠️ 音频处理工具未安装。请运行：pip install edge-tts && apt install ffmpeg"
    if "FileNotFoundError" in msg:
        return "⚠️ 文件不存在，请检查路径。"
    return f"⚠️ 生成失败：{msg[:200]}"

def smart_split_text(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """按语义边界分段，避免切断句子"""
    # 优先按章节标题断
    segments = []
    remaining = text.strip()
    
    while len(remaining) > max_chars:
        # 找最近的段落边界（双换行）
        window = remaining[:max_chars]
        cut = -1
        # 优先级：章节标题 > 段落 > 句号 > 逗号
        for pattern in [r'\n\n', r'第[一二三四五六七八九十百]+[章节回]', r'。', r'！', r'？']:
            matches = list(re.finditer(pattern, window))
            if matches:
                # 取最后面的边界
                last = matches[-1]
                candidate = last.end()
                if candidate > max_chars * 0.5:  # 不能切太早
                    cut = candidate
                    break
        if cut == -1:
            cut = max_chars  # 找不到边界就硬切
        segments.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    
    if remaining:
        segments.append(remaining)
    return segments

def detect_truncation(duration: float, text_len: int) -> bool:
    """检测是否被截断：时长精确落在已知边界上，且文本长度预期超过该边界"""
    for boundary in TRUNCATION_BOUNDARIES:
        if abs(duration - boundary) < 1.0:
            # 按 ~200字/分钟估算，如果文本应产生更长音频则说明被截断
            expected = text_len / 200 * 60
            if expected > boundary + 30:
                return True
    return False

async def generate_segment(text: str, voice: str, rate: str, out_path: Path, idx: int, total: int):
    """生成单段音频，带重试"""
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            proc = await asyncio.create_subprocess_exec(
                "edge-tts", "--voice", voice, "--rate", rate,
                "--text", text, "--write-media", str(out_path),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            await proc.wait()
            if not out_path.exists() or out_path.stat().st_size == 0:
                raise BookToAudioError("NoAudioReceived")
            return out_path
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            raise BookToAudioError(friendly_error(e))

async def pipeline(book_title: str, full_text: str, voice: str = "zh-CN-XiaoxiaoNeural", 
                   rate: str = "+0%", mode: str = "full") -> tuple[str, float]:
    """完整流水线：分段→TTS→拼接→输出
    
    Args:
        mode: "full" 一次性输出 / "progressive" 边生成边输出
    Returns:
        (输出文件路径, 总时长秒)
    """
    try:
        segments = smart_split_text(full_text)
        print(f"📚 分段完成：{len(segments)} 段")
        
        # 生成所有段
        seg_files = []
        total_duration = 0
        for i, seg in enumerate(segments):
            out = CACHE_DIR / f"{hashlib.md5(seg.encode()).hexdigest()[:12]}.mp3"
            if not out.exists():
                print(f"  🎤 [{i+1}/{len(segments)}] 生成中...")
                await generate_segment(seg, voice, rate, out, i, len(segments))
            
            # 检查时长和截断
            probe = subprocess.run(
                ["ffprobe", "-i", str(out), "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"],
                capture_output=True, text=True
            )
            try:
                duration = float(probe.stdout.strip())
            except ValueError:
                duration = 0
                
            if detect_truncation(duration, len(seg)):
                print(f"  ⚠️ 第{i+1}段可能被截断（{duration:.0f}s），建议缩短该段")
            total_duration += duration
            seg_files.append(str(out))
        
        # 拼接
        print(f"🔗 拼接 {len(seg_files)} 段...")
        final_path = CACHE_DIR / f"{hashlib.md5((book_title+voice+rate).encode()).hexdigest()[:10]}.mp3"
        concat_file = CACHE_DIR / "concat_list.txt"
        concat_file.write_text("\n".join(f"file '{f}'" for f in seg_files))
        
        result = subprocess.run(
            ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-codec:a", "libmp3lame", "-b:a", "128k", str(final_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise BookToAudioError(f"音频拼接失败：{result.stderr[-200:]}")
        
        print(f"✅ 完成！总时长 {total_duration/60:.1f} 分钟")
        return str(final_path), total_duration
    
    except BookToAudioError as e:
        print(str(e))
        raise
    except Exception as e:
        print(friendly_error(e))
        raise

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="listen-book 流水线")
    parser.add_argument("-f", "--file", required=True, help="文本文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--mode", default="full", choices=["full", "progressive"])
    args = parser.parse_args()
    
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    out_path, duration = asyncio.run(pipeline(
        Path(args.file).stem, text, args.voice, args.rate, args.mode
    ))
    print(f"输出：{out_path}")
