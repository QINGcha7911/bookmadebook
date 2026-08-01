#!/usr/bin/env python3
"""listen-book 流式流水线 v3 — 分段生成+截断检测+章节标记+批量

v3 新增：
1. ID3v2 CHAP 章节标记（优先 mutagen，fallback ffmpeg）
2. 批量模式：多本书排队生成
3. 接入 cache_manager 三级缓存
"""
import asyncio, subprocess, json, os, sys, time, hashlib, re
from pathlib import Path
from typing import List, Optional

try:
    from scripts.cache_manager import CacheManager
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from cache_manager import CacheManager

CACHE_DIR = Path(os.path.expanduser("~/.hermes/cache/listen-book"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_SEGMENT_CHARS = 3000
TRUNCATION_BOUNDARIES = [600, 900, 1200, 1800]
cache_mgr = CacheManager()

class BookToAudioError(Exception):
    pass

def friendly_error(e: Exception) -> str:
    msg = str(e)
    if "NoAudioReceived" in msg or "Connection" in msg or "Timeout" in msg:
        return "⚠️ 语音服务连接失败。请检查网络后重试。"
    if "ffprobe" in msg or "ffmpeg" in msg:
        return "⚠️ 音频处理工具未安装。请运行：pip install edge-tts && apt install ffmpeg"
    if "FileNotFoundError" in msg:
        return "⚠️ 文件不存在，请检查路径。"
    return f"⚠️ 生成失败：{msg[:200]}"

def smart_split_text(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> List[str]:
    segments = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = -1
        for pattern in [r'\n\n', r'第[一二三四五六七八九十百]+[章节回]', r'。', r'！', r'？']:
            matches = list(re.finditer(pattern, window))
            if matches:
                last = matches[-1]
                candidate = last.end()
                if candidate > max_chars * 0.5:
                    cut = candidate
                    break
        if cut == -1:
            cut = max_chars
        segments.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        segments.append(remaining)
    return segments

def detect_truncation(duration: float, text_len: int) -> bool:
    for boundary in TRUNCATION_BOUNDARIES:
        if abs(duration - boundary) < 1.0:
            expected = text_len / 200 * 60
            if expected > boundary + 30:
                return True
    return False

async def generate_segment(text: str, voice: str, rate: str, out_path: Path):
    max_retries = 2
    # 负 rate（如 -15%）必须用 --rate= 等号形式，否则被 argparse 误判为选项
    rate_arg = f"--rate={rate}"
    for attempt in range(max_retries + 1):
        try:
            proc = await asyncio.create_subprocess_exec(
                "edge-tts", "--voice", voice, rate_arg,
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

def get_audio_duration(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-i", str(path), "-show_entries", "format=duration",
         "-v", "quiet", "-of", "csv=p=0"],
        capture_output=True, text=True
    )
    try:
        return float(probe.stdout.strip())
    except ValueError:
        return 0.0

def add_chapter_markers(mp3_path: Path, chapters: List[dict], total_duration: float):
    """给 MP3 加 ID3v2 CHAP 章节标记
    
    chapters: [{"title": "第1章", "start": 0.0, "end": 120.0}, ...]
    优先 mutagen，fallback ffmpeg metadata
    """
    if not chapters:
        return
    try:
        import mutagen
        from mutagen.id3 import ID3, CHAP, CTOC, TIT2
        audio = mutagen.File(str(mp3_path), easy=False)
        if audio.tags is None:
            audio.add_tags()
        # 清旧章节
        for key in [k for k in audio.tags.keys() if k.startswith("CHAP") or k.startswith("CTOC")]:
            audio.tags.delall(key)
        elements = []
        for i, ch in enumerate(chapters):
            chap_id = f"chp{i:04d}"
            ch_title = ch.get("title", f"章节{i+1}")
            start_ms = int(ch.get("start", 0) * 1000)
            end_ms = int(ch.get("end", total_duration) * 1000)
            audio.tags.add(CHAP(encoding=3, element_id=chap_id,
                                start_time=start_ms, end_time=end_ms,
                                sub_frames=[TIT2(encoding=3, text=[ch_title])]))
            elements.append(chap_id)
        # 顶层 TOC（可选，某些播放器需要）
        audio.tags.add(CTOC(encoding=3, element_id="toc", children=elements,
                            sub_frames=[TIT2(encoding=3, text=["Chapters"])]))
        audio.save()
        print(f"  📑 已写入 {len(chapters)} 个章节标记 (mutagen)")
    except ImportError:
        # fallback: ffmpeg metadata
        meta_path = mp3_path.with_suffix(".meta.txt")
        lines = [";FFMETADATA1"]
        for i, ch in enumerate(chapters):
            lines.append("[CHAPTER]")
            lines.append("TIMEBASE=1/1000")
            lines.append(f"START={int(ch.get('start', 0) * 1000)}")
            lines.append(f"END={int(ch.get('end', total_duration) * 1000)}")
            lines.append(f"title={ch.get('title', f'章节{i+1}')}")
        meta_path.write_text("\n".join(lines), encoding="utf-8")
        tmp_out = mp3_path.with_suffix(".chap.mp3")
        subprocess.run(["ffmpeg", "-y", "-i", str(mp3_path), "-i", str(meta_path),
                        "-map_metadata", "1", "-c", "copy", str(tmp_out)],
                       capture_output=True, text=True)
        if tmp_out.exists():
            tmp_out.replace(mp3_path)
        meta_path.unlink(missing_ok=True)
        print(f"  📑 已写入 {len(chapters)} 个章节标记 (ffmpeg)")

def extract_chapters_from_text(full_text: str, segments: List[str],
                               durations: List[float]) -> List[dict]:
    """根据文本标题和分段时长生成章节信息"""
    chapters = []
    cursor = 0.0
    # 用章节标题切分（第N章/回/节），没有则按段落分
    title_pattern = re.compile(r'^(第[一二三四五六七八九十百0-9]+[章节回]|[^\n]{2,20}?)[：:\s]', re.MULTILINE)
    for i, seg in enumerate(segments):
        m = title_pattern.search(seg)
        title = m.group(1).strip() if m else f"Part {i+1}"
        end = cursor + durations[i] if i < len(durations) else 0
        chapters.append({"title": title, "start": cursor, "end": end})
        cursor = end
    return chapters

async def pipeline(book_title: str, full_text: str, voice: str = "zh-CN-XiaoxiaoNeural",
                   rate: str = "+0%", mode: str = "full",
                   add_chapters: bool = True) -> tuple[str, float]:
    """完整流水线：分段→TTS→拼接→章节标记→输出"""
    try:
        # L3 缓存检查
        script_hash = hashlib.md5(full_text.encode()).hexdigest()
        speed_key = "1.0" if rate == "+0%" else rate
        l3_hit = cache_mgr.get_l3(script_hash, voice, speed_key)
        if l3_hit:
            print(f"✅ L3 缓存命中：{l3_hit}")
            return str(l3_hit), get_audio_duration(l3_hit)

        segments = smart_split_text(full_text)
        print(f"📚 分段完成：{len(segments)} 段")

        seg_files = []
        durations = []
        total_duration = 0
        for i, seg in enumerate(segments):
            # L2 缓存检查
            l2_hit = cache_mgr.get_l2(seg, voice, rate)
            if l2_hit:
                seg_files.append(str(l2_hit))
                d = get_audio_duration(l2_hit)
                durations.append(d)
                total_duration += d
                continue
            out = CACHE_DIR / f"{hashlib.md5(seg.encode()).hexdigest()[:12]}.mp3"
            print(f"  🎤 [{i+1}/{len(segments)}] 生成中...")
            await generate_segment(seg, voice, rate, out)
            cache_mgr.set_l2(seg, voice, rate, out)
            # set_l2 会把文件移到 l2 子目录，使用缓存命中路径
            l2_final = cache_mgr.get_l2(seg, voice, rate) or out
            d = get_audio_duration(l2_final)
            durations.append(d)
            total_duration += d
            if detect_truncation(d, len(seg)):
                print(f"  ⚠️ 第{i+1}段可能被截断（{d:.0f}s），建议缩短该段")
            seg_files.append(str(l2_final))

        print(f"🔗 拼接 {len(seg_files)} 段...")
        final_path = CACHE_DIR / f"{hashlib.md5((book_title+voice+rate).encode()).hexdigest()[:10]}.mp3"
        concat_file = CACHE_DIR / "concat_list.txt"
        concat_file.write_text("\n".join(f"file '{f.replace(chr(92), chr(47))}'" for f in seg_files))

        result = subprocess.run(
            ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-codec:a", "libmp3lame", "-b:a", "128k", str(final_path)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise BookToAudioError(f"音频拼接失败：{result.stderr[-200:]}")

        # 章节标记
        if add_chapters:
            chapters = extract_chapters_from_text(full_text, segments, durations)
            add_chapter_markers(final_path, chapters, total_duration)

        # 存 L3（set_l3 会把文件移到 l3 子目录，返回实际路径）
        cache_mgr.set_l3(script_hash, voice, speed_key, final_path)
        l3_final = cache_mgr.get_l3(script_hash, voice, speed_key) or final_path

        print(f"✅ 完成！总时长 {total_duration/60:.1f} 分钟")
        return str(l3_final), total_duration

    except BookToAudioError as e:
        print(str(e))
        raise
    except Exception as e:
        print(friendly_error(e))
        raise

async def batch_pipeline(jobs: List[dict]):
    """批量模式：多本书排队生成

    jobs: [{"title": "...", "text": "...", "voice": "...", "rate": "...", "mode": "full"}]
    """
    results = []
    for idx, job in enumerate(jobs):
        print(f"\n📦 [{idx+1}/{len(jobs)}] {job.get('title', 'unnamed')}")
        try:
            out_path, duration = await pipeline(
                job["title"], job["text"],
                job.get("voice", "zh-CN-XiaoxiaoNeural"),
                job.get("rate", "+0%"),
                job.get("mode", "full"),
                job.get("add_chapters", True),
            )
            results.append({"title": job["title"], "status": "ok",
                            "path": out_path, "duration": duration})
        except Exception as e:
            results.append({"title": job["title"], "status": "failed", "error": str(e)})
    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="listen-book 流水线")
    parser.add_argument("-f", "--file", help="文本文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--mode", default="full", choices=["full", "progressive"])
    parser.add_argument("--no-chapters", action="store_true", help="不加章节标记")
    parser.add_argument("--batch", help="批量 JSON 文件路径（jobs 数组）")
    args = parser.parse_args()

    if args.batch:
        jobs = json.loads(Path(args.batch).read_text(encoding="utf-8-sig"))
        results = asyncio.run(batch_pipeline(jobs))
        print("\n=== 批量结果 ===")
        for r in results:
            status = "✅" if r["status"] == "ok" else "❌"
            print(f"{status} {r['title']}: {r.get('path', r.get('error', ''))}")
        sys.exit(0 if all(r["status"] == "ok" for r in results) else 1)

    if not args.file:
        parser.error("需要 -f 或 --batch")
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    out_path, duration = asyncio.run(pipeline(
        Path(args.file).stem, text, args.voice, args.rate, args.mode,
        add_chapters=not args.no_chapters
    ))
    print(f"输出：{out_path}")
