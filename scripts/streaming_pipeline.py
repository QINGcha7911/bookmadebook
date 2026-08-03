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

def detect_language(text: str) -> str:
    """检测文本主要语言：zh / en / other"""
    import re
    # 统计中文字符占比
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_words = len(re.findall(r'[a-zA-Z]{2,}', text))
    total = zh_chars + en_words
    if total == 0:
        return "zh"
    return "zh" if zh_chars / total > 0.3 else "en"


# 各语言默认声音
LANG_VOICES = {
    "zh": "zh-CN-XiaoxiaoNeural",       # 中文默认：晓晓
    "en": "en-US-ChristopherNeural",    # 英文默认：Christopher（沉稳男声）
}


def resolve_voice(voice: str, text: str) -> str:
    """解析声音：用户显式指定则用指定的；否则按语言自动选"""
    if voice and voice != "auto":
        return voice
    lang = detect_language(text)
    return LANG_VOICES.get(lang, "zh-CN-XiaoxiaoNeural")


def clean_markdown_for_tts(text: str) -> str:
    """清理 markdown 符号，防止 TTS 朗读出 #、*、- 等字符
    标题行（# 开头）整个删除，不朗读章节标题，直接进入正文"""
    import re
    # 1. 标题行整个删除（# 开头的一行，含标题文字）
    text = re.sub(r'^#{1,6}\s*.*$', '', text, flags=re.MULTILINE)
    # 2. 去掉粗体/斜体符号 (** **, * *)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'\1', text)
    # 3. 去掉行内代码和代码块
    text = re.sub(r'`{1,3}.*?`{1,3}', '', text, flags=re.DOTALL)
    # 4. 去掉链接 [text](url) → text
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # 5. 去掉列表符号 (-, *, 1.)
    text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # 6. 去掉引用符 (>)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    # 7. 去掉分隔线 (---)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    # 8. 去掉 markdown 表格竖线和表头符号
    text = re.sub(r'\|', '，', text)
    # 9. 去掉"（共鸣式，40秒）"这类制作说明括号
    text = re.sub(r'[（(](?:共鸣式|共情式|约\d+秒|\d+分钟|开场|结尾)[^）)]*[）)]', '', text)
    # 10. 压缩多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def smart_split_text(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> List[str]:
    # 先清理 markdown 符号，防止 TTS 朗读 # * - 等字符
    text = clean_markdown_for_tts(text)
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

async def generate_segment(text: str, voice: str, rate: str, out_path: Path,
                           volume: str = "+0%", pitch: str = "+0Hz"):
    max_retries = 2
    # 负 rate（如 -15%）必须用 --rate= 等号形式，否则被 argparse 误判为选项
    # pitch 用 Hz（edge-tts 不支持 pitch 的 % 格式，如 +5% 无效，须 +5Hz）
    args = ["edge-tts", "--voice", voice, f"--rate={rate}",
            f"--volume={volume}", f"--pitch={pitch}",
            "--text", text, "--write-media", str(out_path)]
    for attempt in range(max_retries + 1):
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
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


def mix_bgm(voice_path: Path, cache_dir: Path, bgm_path: str = None,
            bgm_level: float = 0.06,
            golden_times: Optional[List[float]] = None) -> Path:
    """TED 智能 BGM 混音：开场+结尾+情感点轻垫，人声主导（闪避）

    设计（参考 TED 官方风格 + 智能配乐）：
    - 开场 0-15s：音乐淡入淡出（-22dB）
    - 情感点（金句/激昂处）：音乐轻浮起 3-5s
    - 结尾 15s：音乐淡出收尾
    - 正文说话时：音乐极低（-28dB）甚至无声
    bgm_level: 音乐基础音量（0.06≈-28dB 克制版；0.15≈-20dB 明显版）
    golden_times: 情感点时间列表（秒），在这些位置轻垫音乐
    """
    import math
    bgm = Path(bgm_path) if bgm_path else Path(os.path.expanduser(
        "~/listen-book/assets/bgm_ambient.mp3"))
    if not bgm.exists():
        # 回退到仓库 assets
        alt = Path(__file__).parent.parent / "assets" / "bgm_ambient.mp3"
        if alt.exists():
            bgm = alt
        else:
            raise FileNotFoundError(f"BGM素材不存在: {bgm}")

    out = cache_dir / f"mixed_{voice_path.stem}.mp3"

    # 情感点垫乐：每个金句处 5s 轻浮起（淡入淡出）
    # 音乐流先 asplit 分成多路（开场1路 + 每个情感点1路）
    # 注意：各部分之间用 ; 连接（join 负责），不要在元素内部加分号
    n_music = 1 + len(golden_times or [])
    asplit_str = f"[1:a]asplit={n_music}"
    for i in range(n_music):
        asplit_str += f"[m{i}]"
    filter_parts = [asplit_str]

    # 开场垫乐：前 15s（用 m0）
    filter_parts.append(
        f"[m0]atrim=start=0:duration=15,asetpts=PTS-STARTPTS,"
        f"volume={bgm_level},afade=t=in:d=2,afade=t=out:st=11:d=4[bgm_open]"
    )

    # 情感点垫乐（用 m1..mN）
    swell_tags = []
    if golden_times:
        for gi, gt in enumerate(golden_times):
            start = max(0, gt - 1)
            tag = f"sw{gi}"
            swell_tags.append(f"[{tag}]")
            filter_parts.append(
                f"[m{gi+1}]atrim=start={start}:duration=5,asetpts=PTS-STARTPTS,"
                f"volume={bgm_level*1.5},afade=t=in:d=1,afade=t=out:st=3.5:d=1.5[{tag}]"
            )

    # 人声分流
    filter_parts.append("[0:a]asplit=2[voice_main][voice_side]")

    # 混合所有音乐轨（开场 + 情感点）
    music_inputs = ["[bgm_open]"] + swell_tags
    if len(music_inputs) > 1:
        amix_str = "".join(music_inputs)
        filter_parts.append(
            f"{amix_str}amix=inputs={len(music_inputs)}:normalize=0[music_all]"
        )
        music_ref = "[music_all]"
    else:
        music_ref = "[bgm_open]"

    # 闪避 + 最终混音（两个独立 filter 链，用分号分隔）
    filter_parts.append(
        f"{music_ref}[voice_side]sidechaincompress="
        f"threshold=0.05:ratio=6:attack=100:release=600[ducked]"
    )
    filter_parts.append(
        f"[voice_main][ducked]amix=inputs=2:duration=first:dropout_transition=2,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_path),       # 0: 人声
        "-i", str(bgm),              # 1: 音乐
        "-filter_complex", ";".join(filter_parts),
        "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "192k", str(out)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"混音失败: {result.stderr[-300:]}")
    return out

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

async def pipeline(book_title: str, full_text: str, voice: str = "auto",
                   rate: str = "+0%", mode: str = "full",
                   add_chapters: bool = True, style: str = "normal",
                   target_minutes: float = None,
                   user_key: str = None) -> tuple[str, float]:
    """完整流水线：分段→TTS→拼接→章节标记→输出
    voice="auto" 时按文本语言自动选声音（中文→晓晓，英文→Christopher）
    style="ted" 时启用导演层（解析【注解】表演标记，语速起伏+停顿）
    user_key 用于 BGM 用户配置覆盖（内容+用户 → 选曲）
    """
    try:
        # 语言自动选声音（用户指定了具体声音则用用户的）
        voice = resolve_voice(voice, full_text)

        # 目标时长校验（核心：时长是目标，语速是常量，字数是变量）
        if target_minutes:
            try:
                from speed_probe import get_speed, calc_target_chars
                measured_speed = get_speed(voice, rate)
                # 去除 markdown 标记后的有效字数
                import re as _re
                clean_text = _re.sub(r'[#*`>|\-\n]', '', full_text)
                actual_chars = len(clean_text.replace(' ', ''))
                needed_chars = calc_target_chars(target_minutes, measured_speed)
                est_minutes = actual_chars / measured_speed
                print(f"📐 目标 {target_minutes}分钟 | 实测语速 {measured_speed:.0f}字/分 | "
                      f"当前 {actual_chars}字 ≈ {est_minutes:.1f}分钟 | 需要 {needed_chars}字")
                if est_minutes < target_minutes * 0.9:
                    print(f"⚠️ 内容不足：当前约{est_minutes:.0f}分钟，距目标还差"
                          f"{needed_chars - actual_chars}字，请补充内容后重试")
            except Exception as e:
                print(f"⚠️ 时长预估失败（继续生成）：{e}")

        # TED 模式：检测到注解标记则启用导演层
        ted_blocks = None
        if style == "ted" or "【" in full_text and "】" in full_text:
            try:
                from ted_director import parse_annotations, TTSBlock
                ted_blocks = parse_annotations(full_text, voice)
                print(f"🎬 TED 导演层启用：解析出 {len(ted_blocks)} 个表演块")
            except Exception as e:
                print(f"⚠️ 导演层解析失败，回退普通模式：{e}")
                ted_blocks = None

        # L3 缓存检查
        script_hash = hashlib.md5(full_text.encode()).hexdigest()
        speed_key = "1.0" if rate == "+0%" else rate
        l3_hit = cache_mgr.get_l3(script_hash, voice, speed_key)
        if l3_hit:
            print(f"✅ L3 缓存命中：{l3_hit}")
            return str(l3_hit), get_audio_duration(l3_hit)

        if ted_blocks:
            # TED 模式：用导演层块（含停顿/情绪/BGM标记）
            segments = [b.text for b in ted_blocks]
            print(f"🎬 导演层分段完成：{len(segments)} 个表演块")
        else:
            segments = smart_split_text(full_text)
            print(f"📚 分段完成：{len(segments)} 段")

        seg_files = []
        durations = []
        total_duration = 0
        for i, seg in enumerate(segments):
            # TED 模式的块级参数
            seg_voice = voice
            seg_rate = rate
            seg_volume = "+0%"
            seg_pitch = "+0Hz"
            pause_before = 0.0
            if ted_blocks and i < len(ted_blocks):
                b = ted_blocks[i]
                seg_voice = b.voice or voice
                seg_rate = b.rate or rate
                seg_volume = b.volume or "+0%"
                seg_pitch = b.pitch or "+0Hz"
                pause_before = b.pause_before or 0.0
                if b.is_golden_line:
                    seg_rate = "-3%"
                    seg_volume = "+3%"
                    pause_before = max(pause_before, 0.6)
            # L2 缓存检查（含风格指纹）
            l2_key = f"{seg}|{seg_voice}|{seg_rate}|{seg_volume}|{seg_pitch}"
            l2_hit = cache_mgr.get_l2(seg, seg_voice, seg_rate)
            if l2_hit:
                seg_files.append(str(l2_hit))
                d = get_audio_duration(l2_hit)
                durations.append(d)
                total_duration += d
                continue
            out = CACHE_DIR / f"{hashlib.md5(l2_key.encode()).hexdigest()[:12]}.mp3"
            print(f"  🎤 [{i+1}/{len(segments)}] 生成中... (rate={seg_rate} vol={seg_volume})")
            await generate_segment(seg, seg_voice, seg_rate, out, seg_volume, seg_pitch)
            cache_mgr.set_l2(seg, seg_voice, seg_rate, out)
            # set_l2 会把文件移到 l2 子目录，使用缓存命中路径
            l2_final = cache_mgr.get_l2(seg, seg_voice, seg_rate) or out
            d = get_audio_duration(l2_final)
            durations.append(d)
            total_duration += d
            if detect_truncation(d, len(seg)):
                print(f"  ⚠️ 第{i+1}段可能被截断（{d:.0f}s），建议缩短该段")
            seg_files.append(str(l2_final))
            # TED 模式：块后插入停顿（静音）
            if ted_blocks and i < len(ted_blocks) and ted_blocks[i].pause_after > 0:
                pause = ted_blocks[i].pause_after
                silence = CACHE_DIR / f"silence_{pause}.mp3"
                if not silence.exists():
                    subprocess.run(
                        ["ffmpeg", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                         "-t", str(pause), "-q:a", "9", str(silence)],
                        capture_output=True
                    )
                if silence.exists():
                    seg_files.append(str(silence))
                    durations.append(pause)
                    total_duration += pause
                    print(f"  ⏸️ 插入停顿 {pause}s")

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

        # TED 模式：智能 BGM 混音（开场+金句垫乐+结尾）
        if ted_blocks:
            try:
                bgm_level = float(os.environ.get("LISTEN_BOOK_BGM", "0.06"))
                # 计算金句/激昂块的时间点（用于情感点垫乐）
                golden_times = []
                cum_time = 0.0
                for gi, b in enumerate(ted_blocks):
                    if b.is_golden_line:
                        golden_times.append(cum_time)
                    # 估算块时长：字数/5字每秒 + 停顿
                    blk_dur = max(1.0, len(b.text) / 5.0)
                    cum_time += blk_dur + (b.pause_after or 0)
                if golden_times:
                    print(f"🎵 检测到 {len(golden_times)} 个情感点（金句垫乐）")
                # 内容+用户配置 → 自动选 BGM
                try:
                    from bgm_selector import select_bgm
                    bgm_path, bgm_topic = select_bgm(full_text, user_key=user_key)
                    print(f"🎵 BGM 选择：主题={bgm_topic or '通用'} → {Path(bgm_path).name}")
                except Exception as e:
                    print(f"⚠️ BGM 选择失败（用默认）：{e}")
                    bgm_path = None
                final_path = mix_bgm(final_path, CACHE_DIR,
                                     bgm_path=bgm_path,
                                     bgm_level=bgm_level,
                                     golden_times=golden_times)
                print(f"🎵 BGM 混音完成（电平{bgm_level}）")
            except Exception as e:
                print(f"⚠️ BGM 混音失败（跳过）：{e}")

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
    parser.add_argument("--voice", default="auto",
                        help="声音（auto=按语言自动选，或指定如 zh-CN-XiaoxiaoNeural / en-US-ChristopherNeural）")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--mode", default="full", choices=["full", "progressive"])
    parser.add_argument("--style", default="normal", choices=["normal", "ted"],
                        help="TED 模式（导演层表演标记）")
    parser.add_argument("--user", default=None,
                        help="用户标识（用于 BGM 用户配置覆盖，如 --user alice）")
    parser.add_argument("--target-minutes", type=float, default=None,
                        help="目标时长(分钟)：生成前按实测语速校验字数是否达标")
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
        add_chapters=not args.no_chapters, style=args.style,
        target_minutes=args.target_minutes,
        user_key=args.user
    ))
    print(f"输出：{out_path}")
