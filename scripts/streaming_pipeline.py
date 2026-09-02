#!/usr/bin/env python3
"""bookmadebook 流式流水线 v3 — 分段生成+截断检测+章节标记+批量

v3 新增：
1. ID3v2 CHAP 章节标记（优先 mutagen，fallback ffmpeg）
2. 批量模式：多本书排队生成
3. 接入 cache_manager 三级缓存
"""
import asyncio, subprocess, json, os, sys, time, hashlib, re, uuid
from pathlib import Path
from typing import List, Optional

try:
    from scripts.cache_manager import CacheManager
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from cache_manager import CacheManager

CACHE_DIR = Path(os.path.expanduser("~/.hermes/cache/bookmadebook"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 《人工智能生成合成内容标识办法》2025-09-01 合规：音频开头声明
AI_DISCLOSURE_TEXT = "本音频由 AI 生成，内容为书籍解读与观点引用，版权归原作者所有。"
AI_DISCLOSURE_KEY = "ai_disclosure_v1"

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
    """检测文本主要语言：zh / en / ja / other"""
    import re
    # 统计中文字符占比
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 统计日文假名
    ja_chars = len(re.findall(r'[\u3040-\u30ff\u31f0-\u31ff]', text))
    en_words = len(re.findall(r'[a-zA-Z]{2,}', text))
    # 日文优先（假名是日文独有）
    if ja_chars > 0 and ja_chars >= zh_chars * 0.3:
        return "ja"
    total = zh_chars + en_words
    if total == 0:
        return "zh"
    return "zh" if zh_chars / total > 0.3 else "en"


# 各语言默认声音
LANG_VOICES = {
    "zh": "zh-CN-XiaoxiaoNeural",       # 中文默认：晓晓
    "en": "en-US-ChristopherNeural",    # 英文默认：Christopher（沉稳男声）
    "ja": "ja-JP-NanamiNeural",         # 日文默认：Nanami（日本女声）
}

# 内容类型 → 声音映射（优化①：依据内容定声音）
# 2026-08-21 设计音色接入：历史→hist_deep_male(百炼)、童话/儿童→design_kid(百炼)、情感/散文→husky_tender(百炼)
# 设计音色 voice ID 以 qwen-tts-vd- 开头，generate_segment 检测到后走百炼 API（voice_design.py synth）
# 其余类型保持 edge-tts 免费声兜底
CONTENT_VOICES = [
    ("童话", ["童话", "睡前", "小王子", "丑小鸭", "小红帽", "格林", "安徒生", "儿童", "宝宝", "宝贝"],
     "qwen-tts-vd-design_kid-voice-20260821205612330-e42c", "design_kid：活泼童声(百炼设计音色)，适合儿童/童话"),
    ("儿童科普", ["十万个", "百科", "科普", "好奇", "科学实验", "恐龙", "动物世界"],
     "qwen-tts-vd-design_kid-voice-20260821205612330-e42c", "design_kid：活泼童声(百炼设计音色)，适合儿童科普"),
    ("职场", ["职场", "汇报", "管理", "会议", "同事", "老板", "工作", "项目", "制度", "体制", "上班"],
     "zh-CN-YunjianNeural", "云健：沉稳专业，适合职场/干货"),
    ("悬疑", ["悬疑", "谋杀", "案件", "侦探", "推理", "秘密", "真相", "阴谋", "死亡"],
     "zh-CN-YunyangNeural", "云扬：低沉神秘，适合悬疑/推理"),
    ("励志", ["励志", "加油", "奋斗", "梦想", "坚持", "不要放弃", "热血", "努力", "成功"],
     "zh-CN-YunxiNeural", "云希：阳光有力，适合励志/燃向"),
    ("情感", ["爱情", "恋爱", "喜欢", "分手", "想念", "心动", "告白", "婚姻", "泪", "哭"],
     "qwen-tts-vd-husky_tender-voice-20260821220323362-ebb0", "husky_tender：沙哑温柔(百炼设计音色)，适合情感/散文"),
    ("历史", ["历史", "朝代", "皇帝", "战争", "王朝", "古代", "明朝", "唐朝", "宋朝",
             "楚汉", "争霸", "刘邦", "项羽", "韩信", "帝王", "将相", "君主", "谋略",
             "史记", "演义", "三国", "名将", "丞相", "列传", "春秋", "战国", "诸侯",
             "起义", "江山", "宫廷", "北伐", "王位之争", "江山社稷"],
     "qwen-tts-vd-hist_deep_male-voice-20260821204552033-d7bc", "hist_deep_male：沉稳厚重(百炼设计音色)，适合历史/传记"),
]

# 百炼设计音色短名 → 完整 voice ID（2026-09-02 用户指定 --voice husky_tender 时
# resolve_voice 原样返回短名，generate_segment 不认 qwen-tts-vd- 前缀会误走 edge-tts）
VOICE_ALIASES = {
    "husky_tender": "qwen-tts-vd-husky_tender-voice-20260821220323362-ebb0",
    "hist_deep_male": "qwen-tts-vd-hist_deep_male-voice-20260821204552033-d7bc",
    "design_kid": "qwen-tts-vd-design_kid-voice-20260821205612330-e42c",
}


def detect_content_type(text: str) -> str:
    """检测内容类型：童话/职场/悬疑/励志/情感/历史/通用（加权：命中关键词最多者胜，2026-08-14改）
    平票规则：严格大于才替换，列表靠前者胜（童话优先）；零命中回退通用。
    注意：关键词必须用双字以上，单字会子串误配（如"帝"→上帝/帝企鹅）。"""
    best, best_cnt = "通用", 0
    for ctype, keywords, voice, desc in CONTENT_VOICES:
        cnt = sum(1 for kw in keywords if kw in text)
        if cnt > best_cnt:
            best, best_cnt = ctype, cnt
    return best


def resolve_voice(voice: str, text: str) -> str:
    """解析声音：用户显式指定则用指定的；否则按内容类型+语言自动选（优化①）"""
    if voice and voice != "auto":
        if voice in VOICE_ALIASES:
            return VOICE_ALIASES[voice]
        return voice
    # 先检测语言（日语/英语优先按语言选）
    lang = detect_language(text)
    if lang == "ja":
        return "ja-JP-NanamiNeural"
    if lang == "en":
        return "en-US-ChristopherNeural"
    # 中文：按内容类型匹配声音
    ctype = detect_content_type(text)
    for ct, kws, v, desc in CONTENT_VOICES:
        if ct == ctype:
            return v
    return "zh-CN-XiaoxiaoNeural"


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
    # 空输入/纯标题文本保护：避免空 segments 导致 concat 空列表报错
    if not segments:
        raise BookToAudioError("文本为空或无可朗读内容（全是标题/注解标记），无法生成音频。")
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
    engine = os.environ.get("LISTEN_TTS_ENGINE", "edge-tts")
    if engine == "cosyvoice":
        # CosyVoice 引擎（m1 男声：longxiang + 低沉参数，2026-08-17 用户认可）
        cosy_voice = os.environ.get("LISTEN_COSY_VOICE", "longxiang")
        cosy_pitch = os.environ.get("LISTEN_COSY_PITCH", "-8Hz")
        cosy_rate = os.environ.get("LISTEN_COSY_RATE", "-5%")
        args = [sys.executable, str(Path(__file__).parent / "tts_cosy.py"),
                "--voice", cosy_voice, f"--pitch={cosy_pitch}", f"--rate={cosy_rate}",
                "--text", text, "--output", str(out_path)]
    elif voice.startswith("qwen-tts-vd-"):
        # 阿里百炼 Qwen3-TTS 声音设计 API（2026-08-21 接入）：voice 是设计音色 ID 时走百炼
        # 按量计费 0.8元/万字符；DASHSCOPE_API_KEY 从 ~/.hermes/.env 读取（voice_design.py 内处理）
        args = [sys.executable, str(Path(__file__).parent / "voice_design.py"),
                "synth", "--voice", voice, "--text", text, "--out", str(out_path)]
    else:
        args = ["edge-tts", "--voice", voice, f"--rate={rate}",
                f"--volume={volume}", f"--pitch={pitch}",
                "--text", text, "--write-media", str(out_path)]
    # 单段子进程超时：edge-tts 并发下可能 hang（token 竞争），必须超时 kill 释放 Semaphore
    proc_timeout = 90
    for attempt in range(max_retries + 1):
        proc = None
        try:
            # 重试前先删旧文件，防止上次被 kill 的残缺 mp3（>0 字节）被误判成功
            if out_path.exists():
                out_path.unlink()
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            await asyncio.wait_for(proc.wait(), timeout=proc_timeout)
            if proc.returncode != 0:
                # 2026-08-17 捕获 stderr 保留真实错误（CosyVoice 诊断）
                err_txt = ""
                try:
                    err_txt = (await proc.stderr.read()).decode("utf-8", errors="replace")[:200]
                except Exception:
                    pass
                raise BookToAudioError(f"TTS退出码{proc.returncode}: {err_txt}")
            if not out_path.exists() or out_path.stat().st_size == 0:
                raise BookToAudioError("NoAudioReceived")
            # 完整性校验：ffprobe 能读出时长才算有效音频（残缺文件会解析失败）
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(out_path)],
                    capture_output=True, text=True, timeout=30)
                if not probe.stdout.strip():
                    raise BookToAudioError("CorruptAudio")
            except BookToAudioError:
                raise
            except Exception:
                # ffprobe 本身异常（如被 kill）也视为无效
                if out_path.exists():
                    out_path.unlink()
                raise BookToAudioError("CorruptAudio")
            return out_path
        except asyncio.TimeoutError:
            # hang 进程必须 kill，否则占住 Semaphore 导致 gather 永不返回
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            if attempt < max_retries:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            raise BookToAudioError("语音服务无响应（超时90s），已终止进程。"
                                   "网络/并发限流时请降低并发或稍后重试。")
        except Exception as e:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
            if attempt < max_retries:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            raise BookToAudioError(friendly_error(e))

def get_audio_duration(path: Path) -> float:
    try:
        probe = subprocess.run(
            ["ffprobe", "-i", str(path), "-show_entries", "format=duration",
             "-v", "quiet", "-of", "csv=p=0"],
            capture_output=True, text=True, timeout=30
        )
        try:
            return float(probe.stdout.strip())
        except ValueError:
            return 0.0
    except subprocess.TimeoutExpired:
        # ffprobe 卡住不能悬挂 pipeline（实测偶发），返回 0 走兜底
        return 0.0


def mix_bgm(voice_path: Path, cache_dir: Path, bgm_path: str = None,
            bgm_level: float = 0.18,
            golden_times: Optional[List[float]] = None) -> Path:
    """TED 智能 BGM 混音：开头+结尾垫乐，人声主导（闪避）

    设计（用户偏好 2026-08-06）：
    - 开头：BGM 淡入垫乐，时长 = min(60s, 音频时长×25%)，至少 30s
    - 结尾：BGM 淡出收尾，同样时长
    - 中间：无人声时也无 BGM（纯讲书）
    - bgm_level: 音乐基础音量（0.18≈-24dB 轻柔版）
    - golden_times: 兼容保留（不再使用金句垫乐，用户偏好开头结尾）
    """
    import math
    bgm = Path(bgm_path) if bgm_path else Path(os.path.expanduser(
        "~/bookmadebook/assets/bgm_ambient.mp3"))
    if not bgm.exists():
        # 回退到仓库 assets
        alt = Path(__file__).parent.parent / "assets" / "bgm_ambient.mp3"
        if alt.exists():
            bgm = alt
        else:
            raise FileNotFoundError(f"BGM素材不存在: {bgm}")

    out = cache_dir / f"mixed_{voice_path.stem}.mp3"

    # 获取人声时长（决定开头/结尾垫乐时长）
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(voice_path)],
            capture_output=True, text=True, timeout=30)
        total_dur = float(probe.stdout.strip() or 120)
    except Exception:
        total_dur = 120.0

    # 开头/结尾垫乐时长：min(60s, 25%总时长)，下限30s
    edge_dur = max(30, min(60, int(total_dur * 0.25)))
    # 防止超出音频时长的一半（短音频保护）
    edge_dur = min(edge_dur, int(total_dur / 2))

    # 音乐流 asplit 两路：开头 + 结尾
    filter_parts = ["[1:a]asplit=2[m_open][m_close]"]

    # 开头垫乐：从0开始 edge_dur 秒，淡入淡出
    filter_parts.append(
        f"[m_open]atrim=start=0:duration={edge_dur},asetpts=PTS-STARTPTS,"
        f"volume={bgm_level*3.0},afade=t=in:d=3,afade=t=out:st={edge_dur-4}:d=4[bgm_open]"
    )

    # 结尾垫乐：从 total_dur-edge_dur 开始 edge_dur 秒，淡入淡出
    end_start = max(0, total_dur - edge_dur)
    filter_parts.append(
        f"[m_close]atrim=start=0:duration={edge_dur},asetpts=PTS-STARTPTS,"
        f"volume={bgm_level*3.0},afade=t=in:d=3,afade=t=out:st={edge_dur-4}:d=4,"
        f"adelay={int(end_start*1000)}|{int(end_start*1000)}[bgm_close]"
    )

    # 直接 3 路混音：人声 + 开头音乐 + 结尾音乐（normalize=0 保留音量）
    filter_parts.append(
        "[0:a][bgm_open][bgm_close]amix=inputs=3:duration=first:normalize=0:dropout_transition=2,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "alimiter=limit=0.95[aout]"
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
                               durations: List[float],
                               segment_offsets: List[float] = None) -> List[dict]:
    """根据文本标题和分段时长生成章节信息

    segment_offsets: 每段在最终音频中的起始偏移（含 TED 停顿等插入时长）。
    传 None 时退化为纯累加（无停顿场景），保持向后兼容。
    """
    chapters = []
    cursor = 0.0
    # 用章节标题切分（第N章/回/节），没有则按段落分
    title_pattern = re.compile(r'^(第[一二三四五六七八九十百0-9]+[章节回]|[^\n]{2,20}?)[：:\s]', re.MULTILINE)
    for i, seg in enumerate(segments):
        m = title_pattern.search(seg)
        title = m.group(1).strip() if m else f"Part {i+1}"
        # 段起始偏移：优先用真实偏移（含停顿），否则累加
        start = segment_offsets[i] if segment_offsets and i < len(segment_offsets) else cursor
        end = start + (durations[i] if i < len(durations) else 0)
        chapters.append({"title": title, "start": start, "end": end})
        cursor = end
    return chapters

async def pipeline(book_title: str, full_text: str, voice: str = "auto",
                   rate: str = "+0%", mode: str = "full",
                   add_chapters: bool = True, style: str = "normal",
                   target_minutes: float = None,
                   user_key: str = None,
                   output_path: str = None,
                   pitch: str = "+0Hz") -> tuple[str, float]:
    """完整流水线：分段→TTS→拼接→章节标记→输出
    voice="auto" 时按文本语言自动选声音（中文→晓晓，英文→Christopher）
    style="ted" 时启用导演层（解析【注解】表演标记，语速起伏+停顿）
    user_key 用于 BGM 用户配置覆盖（内容+用户 → 选曲）
    pitch 全局音调（Hz），如 -15Hz 低沉磁性（2026-08-13 新增）
    """
    try:
        # 语言自动选声音（用户指定了具体声音则用用户的）
        voice = resolve_voice(voice, full_text)

        # 目标时长校验（核心：时长是目标，语速是常量，字数是变量）
        if target_minutes:
            try:
                from speed_probe import get_speed, calc_target_chars
                if os.environ.get("LISTEN_TTS_ENGINE") == "cosyvoice":
                    # CosyVoice 模式：edge-tts 探测必失败（voice 不兼容），直接用默认语速 282
                    measured_speed = 282.0
                else:
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
                    raise BookToAudioError(
                        f"📢 内容量不足：当前稿子约{est_minutes:.0f}分钟，"
                        f"距目标{target_minutes}分钟还差{needed_chars - actual_chars}字。\n"
                        f"请二选一：\n"
                        f"  ① 补充更多书中的真实情节（推荐，不注水）\n"
                        f"  ② 缩短目标时长到约{est_minutes:.0f}分钟\n"
                        f"  ③ 换一本内容更丰富的书\n"
                        f"注意：禁止用重复内容/空话凑时长，宁短勿滥。")
            except BookToAudioError:
                raise  # 内容不足：必须停止，诚实告知用户
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

        # L3 缓存检查（key 基于清理后文本 + style + BGM设置 + pitch，防止旧版/不同风格/不同BGM/不同音调互相命中）
        import re as _re3
        cache_text = _re3.sub(r'^#{1,6}\s*.*$', '', full_text, flags=_re3.MULTILINE)
        bgm_level_key = os.environ.get("LISTEN_BOOK_BGM", "0.18")
        # 检测主题是否无BGM（科幻/悬疑→纯人声），避免带BGM/无BGM版本缓存混淆
        try:
            from bgm_selector import select_bgm as _sel
            _bgm_sel, _topic_sel = _sel(cache_text)
            bgm_mode = "nobgm" if _bgm_sel is None else "bgm"
        except Exception:
            bgm_mode = "bgm"
        script_hash = hashlib.md5(
            f"{cache_text}|style:{style}|bgm:{bgm_level_key}|mode:{bgm_mode}|pitch:{pitch}"
            f"|user:{user_key or ''}|chapters:{int(add_chapters)}|vol:v2".encode()).hexdigest()
        speed_key = "1.0" if rate == "+0%" else rate
        l3_hit = cache_mgr.get_l3(script_hash, voice, speed_key)
        if l3_hit:
            print(f"✅ L3 缓存命中：{l3_hit}")
            # --output 支持：L3 命中也要复制到指定路径（否则输出参数静默失效）
            if output_path:
                try:
                    import shutil
                    dest = Path(output_path).expanduser()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(l3_hit), dest)
                    print(f"📦 已输出到: {dest}")
                    return str(dest), get_audio_duration(l3_hit)
                except Exception as e:
                    print(f"⚠️ 复制到输出路径失败（{e}），返回缓存路径")
            return str(l3_hit), get_audio_duration(l3_hit)

        if ted_blocks:
            # TED 模式：用导演层块（含停顿/情绪/BGM标记）
            segments = [b.text for b in ted_blocks]
            print(f"🎬 导演层分段完成：{len(segments)} 个表演块")
        else:
            segments = smart_split_text(full_text)
            print(f"📚 分段完成：{len(segments)} 段")

        # 并发上限=2：edge-tts 子进程并发≥3 会被微软服务限流（hang/0字节），
        # 2 并发实测稳定；失败段走串行重试兜底
        sem = asyncio.Semaphore(2)
        run_token = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        l2_key_locks: dict = {}
        l2_final_by_key: dict = {}
        seg_records: list = [None] * len(segments)

        def _l2_lock(key: str) -> asyncio.Lock:
            lock = l2_key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                l2_key_locks[key] = lock
            return lock

        async def _render_segment(job: dict):
            i = job["i"]
            seg = job["seg"]
            seg_voice = job["voice"]
            seg_rate = job["rate"]
            seg_volume = job["volume"]
            seg_pitch = job["pitch"]
            l2_key = job["l2_key"]
            try:
                async with sem:
                    async with _l2_lock(l2_key):
                        l2_final = l2_final_by_key.get(l2_key)
                        if l2_final is None:
                            out = CACHE_DIR / f"{hashlib.md5(l2_key.encode()).hexdigest()[:12]}.mp3"
                            print(f"  🎤 [{i+1}/{len(segments)}] 生成中... (rate={seg_rate} vol={seg_volume})")
                            await generate_segment(seg, seg_voice, seg_rate, out,
                                                   seg_volume, seg_pitch)
                            cache_mgr.set_l2(seg, seg_voice, seg_rate, out,
                                             volume=seg_volume, pitch=seg_pitch)
                            # set_l2 会把文件移到 l2 子目录，使用缓存命中路径
                            l2_final = str(cache_mgr.get_l2(
                                seg, seg_voice, seg_rate,
                                volume=seg_volume, pitch=seg_pitch) or out)
                            l2_final_by_key[l2_key] = l2_final
                return i, l2_final
            except Exception as e:
                raise BookToAudioError(f"第 {i+1} 段生成失败：{e}") from e

        pending_jobs = []
        for i, seg in enumerate(segments):
            # TED 模式的块级参数
            seg_voice = voice
            seg_rate = rate
            seg_volume = "+0%"
            seg_pitch = pitch
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
                # 开场自动提速（2026-08-30：3s 判定优化——开场 15s 要紧迫感）
                # 仅第一块、且未标任何情绪/金句/放慢时生效，避免覆盖写稿人意图
                if (i == 0 and seg_rate == rate
                        and not b.is_golden_line and not b.is_slow):
                    seg_rate = "+8%"
            # L2 缓存检查（含风格指纹：volume/pitch 必须传入，否则不同情绪块互相命中）
            l2_key = f"{seg}|{seg_voice}|{seg_rate}|{seg_volume}|{seg_pitch}"
            l2_hit = cache_mgr.get_l2(seg, seg_voice, seg_rate,
                                      volume=seg_volume, pitch=seg_pitch)
            if l2_hit:
                seg_records[i] = {
                    "path": str(l2_hit),
                    "duration": get_audio_duration(l2_hit),
                    "pending": False,
                }
                continue
            pending_jobs.append({
                "i": i,
                "seg": seg,
                "voice": seg_voice,
                "rate": seg_rate,
                "volume": seg_volume,
                "pitch": seg_pitch,
                "l2_key": l2_key,
            })

        if pending_jobs:
            results = await asyncio.gather(
                *(_render_segment(job) for job in pending_jobs),
                return_exceptions=True
            )
            errors = [r for r in results if isinstance(r, Exception)]
            # 失败段串行重试兜底：并发撞限流后，逐段错峰重试（已无并发压力）
            if errors:
                print(f"  ⚠️ {len(errors)} 段并发失败，转为串行重试（错峰避限流）...")
                for idx, (job, r) in enumerate(zip(pending_jobs, results)):
                    if not isinstance(r, Exception):
                        continue
                    i = job["i"]
                    try:
                        print(f"  🔄 [{i+1}/{len(segments)}] 串行重试...")
                        ret_i, l2_final = await _render_segment(job)
                        results[idx] = (ret_i, l2_final)
                    except Exception as e2:
                        results[idx] = e2
            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                detail = "; ".join(str(e) for e in errors)
                raise BookToAudioError(f"分段并发生成失败：{detail}")
            for i, l2_final in results:
                seg_records[i] = {
                    "path": l2_final,
                    "duration": get_audio_duration(Path(l2_final)),
                    "pending": True,
                }

        seg_files = []
        durations = []
        # 每段在最终音频中的起始偏移（含停顿插入，供章节时间轴使用）
        segment_offsets = []
        total_duration = 0
        for i, rec in enumerate(seg_records):
            seg_files.append(rec["path"])
            durations.append(rec["duration"])
            segment_offsets.append(total_duration)  # 本段真实起始位置
            total_duration += rec["duration"]
            if rec["pending"] and detect_truncation(rec["duration"], len(segments[i])):
                print(f"  ⚠️ 第{i+1}段可能被截断（{rec['duration']:.0f}s），建议缩短该段")
            # TED 模式：块后插入停顿（静音）——与 L2 是否命中无关，停顿是导演层编排
            if ted_blocks and i < len(ted_blocks) and ted_blocks[i].pause_after > 0:
                pause = ted_blocks[i].pause_after
                silence = CACHE_DIR / f"silence_{pause}_{run_token}.mp3"
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
        final_path = CACHE_DIR / f"{script_hash[:10]}_{run_token}.mp3"
        # AI 生成声明（合规）：放音频尾端（2026-08-30 用户要求：开头直接出钩子，
        # 声明移到片尾避免打断前 3 秒留存；《标识办法》允许末尾标识）
        try:
            disc_l2 = cache_mgr.get_l2(AI_DISCLOSURE_TEXT, voice, rate,
                                       volume="+0%", pitch=pitch)
            if disc_l2:
                disclosure_path = str(disc_l2)
            else:
                disc_out = CACHE_DIR / f"{AI_DISCLOSURE_KEY}_{voice}_{rate}_{pitch}_{run_token}.mp3"
                await generate_segment(AI_DISCLOSURE_TEXT, voice, rate, disc_out,
                                       volume="+0%", pitch=pitch)
                cache_mgr.set_l2(AI_DISCLOSURE_TEXT, voice, rate, disc_out,
                                 volume="+0%", pitch=pitch)
                disclosure_path = str(cache_mgr.get_l2(
                    AI_DISCLOSURE_TEXT, voice, rate, volume="+0%", pitch=pitch) or disc_out)
            seg_files.append(disclosure_path)  # 片尾（原 insert(0) 在最开头）
            d0 = get_audio_duration(Path(disclosure_path))
            durations.append(d0)
            total_duration += d0
            print(f"  📢 已插入 AI 生成声明（片尾 {d0:.1f}s）")
        except Exception as e:
            print(f"  ⚠️ AI 声明插入失败（不影响主音频）：{e}")
        concat_file = CACHE_DIR / f"concat_list_{run_token}.txt"
        concat_file.write_text("\n".join(f"file '{f.replace(chr(92), chr(47))}'" for f in seg_files))  # 反斜杠→正斜杠（ffmpeg concat 要求）

        result = subprocess.run(
            ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-codec:a", "libmp3lame", "-b:a", "128k", str(final_path)],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            raise BookToAudioError(f"音频拼接失败：{result.stderr[-200:]}")

        # TED 模式：智能 BGM 混音（开场+金句垫乐+结尾）
        if ted_blocks:
            try:
                bgm_level = float(os.environ.get("LISTEN_BOOK_BGM", "0.18"))
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
                    if bgm_path is None:
                        print(f"🎵 主题={bgm_topic or '未知'} → 无BGM（纯人声，用户偏好）")
                        bgm_skip = True
                    else:
                        bgm_skip = False
                        print(f"🎵 BGM 选择：主题={bgm_topic or '通用'} → {Path(bgm_path).name}")
                except Exception as e:
                    print(f"⚠️ BGM 选择失败（用默认）：{e}")
                    bgm_path = None
                    bgm_skip = True
                if not bgm_skip:
                    final_path = mix_bgm(final_path, CACHE_DIR,
                                         bgm_path=bgm_path,
                                         bgm_level=bgm_level,
                                         golden_times=golden_times)
                    print(f"🎵 BGM 混音完成（电平{bgm_level}）")
            except Exception as e:
                print(f"⚠️ BGM 混音失败（跳过）：{e}")

        # 章节标记（失败不阻断主流程——音频已生成，标记是增强）
        if add_chapters:
            try:
                chapters = extract_chapters_from_text(full_text, segments, durations,
                                                      segment_offsets)
                add_chapter_markers(final_path, chapters, total_duration)
            except Exception as e:
                print(f"⚠️ 章节标记写入失败（不影响主音频）：{e}")

        # 存 L3（set_l3 会把文件移到 l3 子目录，返回实际路径）
        cache_mgr.set_l3(script_hash, voice, speed_key, final_path)
        l3_final = cache_mgr.get_l3(script_hash, voice, speed_key) or final_path

        print(f"✅ 完成！总时长 {total_duration/60:.1f} 分钟")

        # --output 支持：复制到指定路径（此前 -o 从未生效）
        if output_path:
            try:
                import shutil
                dest = Path(output_path).expanduser()
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(l3_final), dest)
                print(f"📦 已输出到: {dest}")
                return str(dest), total_duration
            except Exception as e:
                print(f"⚠️ 复制到输出路径失败（{e}），返回缓存路径")

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
    parser = argparse.ArgumentParser(description="bookmadebook 流水线")
    parser.add_argument("-f", "--file", help="文本文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径")
    parser.add_argument("--voice", default="auto",
                        help="声音（auto=按语言自动选，或指定如 zh-CN-XiaoxiaoNeural / en-US-ChristopherNeural）")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--pitch", default="+0Hz",
                        help="全局音调（Hz），如 -15Hz 低沉磁性、+10Hz 明亮（2026-08-13 新增）")
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

    # ── 内容安全过滤（content_filter 真正接线）──
    try:
        import importlib.util
        cf_spec = importlib.util.spec_from_file_location(
            "content_filter", Path(__file__).parent / "content_filter.py")
        cf = importlib.util.module_from_spec(cf_spec)
        cf_spec.loader.exec_module(cf)
        # 按 config.yaml 的 age_group 自动选模式（未成年人→kids严格，成人→adult宽松）
        try:
            import importlib.util as _clu
            cl_spec = importlib.util.spec_from_file_location(
                "config_loader", Path(__file__).parent / "config_loader.py")
            cl = importlib.util.module_from_spec(cl_spec)
            cl_spec.loader.exec_module(cl)
            age_group = cl.get("age_group.default", "adult")
        except Exception:
            age_group = "adult"
        cf_mode = "kids" if age_group in ("toddler", "preschool", "primary_lower",
                                          "primary_upper", "middle_school", "high_school") else "adult"
        cf_inst = cf.ContentFilter(cf_mode)
        cf_result = cf_inst.check(text)
        if not cf_result.get("safe", True):
            print(f"\n📢 内容安全拦截: {cf_result.get('reason', '')}")
            for hit in cf_result.get("hits", []):
                print(f"  ❌ {hit}")
            print("  请修正内容后重试。")
            sys.exit(5)
        print(f"  ✅ 内容安全通过（{cf_result.get('mode', cf_mode)}模式, age_group={age_group}）")
    except Exception as e:
        print(f"  ⚠️ 内容过滤跳过（{e}）")  # 过滤失败不阻断（与质量门不同，属建议层）

    # ── Harness 质量门：生成前校验（内容不足/重复/金句去重/markdown残留）──
    if args.target_minutes:
        try:
            import importlib.util
            qg_spec = importlib.util.spec_from_file_location(
                "quality_gate", Path(__file__).parent / "quality_gate.py")
            qg = importlib.util.module_from_spec(qg_spec)
            qg_spec.loader.exec_module(qg)
            qg_report = qg.validate(
                text, args.target_minutes, args.voice,
                book_title=Path(args.file).stem,
                style=args.style)
            if not qg_report["passed"]:
                print("\n📢 Harness 质量门拦截（生成前）:")
                for e in qg_report["errors"]:
                    print(f"  ❌ {e}")
                print("  请修正讲书稿后重试（补充内容/去重/缩时长），禁止注水。")
                sys.exit(2)
            if qg_report["warnings"]:
                for w in qg_report["warnings"]:
                    print(f"  ⚠️ {w}")
            print(f"  ✅ 质量门通过（{qg_report['stats']['chars']}字 ≈ "
                  f"{qg_report['stats']['est_minutes']}分钟）")
        except SystemExit:
            raise  # 质量门明确判失败（exit 2），直接传播
        except Exception as e:
            # fail-closed：质量门异常必须退出，禁止静默跳过（否则校验形同虚设）
            print(f"\n📢 Harness 质量门异常（fail-closed）: {e}")
            print("  质量门无法执行时禁止继续生成——请修复质量门或检查环境（如 numpy 缺失）。")
            sys.exit(2)

    out_path, duration = asyncio.run(pipeline(
        Path(args.file).stem, text, args.voice, args.rate, args.mode,
        add_chapters=not args.no_chapters, style=args.style,
        target_minutes=args.target_minutes,
        user_key=args.user,
        output_path=args.output,
        pitch=args.pitch
    ))
    print(f"输出：{out_path}")

    # ── Harness 输出验证门：生成后校验（标题残留/时长偏差/完整性）──
    try:
        import importlib.util
        ov_spec = importlib.util.spec_from_file_location(
            "output_verify", Path(__file__).parent / "output_verify.py")
        ov = importlib.util.module_from_spec(ov_spec)
        ov_spec.loader.exec_module(ov)
        # 生成真实标题朗读样本（书名 + 声音），让"标题残留检测"真正运行
        title_sample_path = None
        try:
            import tempfile, subprocess as _sp
            # 书名：用文件名作为标题样本文本（TTS读文件名即可验证标题朗读）
            book_title_for_sample = Path(args.file).stem if args.file else "听书"
            # 关键：args.voice 可能是 "auto"，edge-tts 不认 → 用 resolve_voice 解析真实声音
            real_voice = resolve_voice(args.voice, text)
            _td = tempfile.mkdtemp(prefix="listenbook_title_")
            title_sample_path = Path(_td) / "title_sample.mp3"
            _sp.run(
                ["edge-tts", "--voice", real_voice, "--text", book_title_for_sample,
                 "--write-media", str(title_sample_path)],
                capture_output=True, timeout=60)
            if not title_sample_path.exists() or title_sample_path.stat().st_size < 100:
                title_sample_path = None
        except Exception:
            title_sample_path = None  # 标题样本生成失败则跳过该子检测（不 fail-closed）
        ov_report = ov.verify(out_path, args.target_minutes,
                              title_sample=title_sample_path)
        if title_sample_path is None:
            print("  ⚠️ 标题样本生成失败，跳过标题残留检测（其他验证继续）")
        elif ov_report["stats"].get("title_corr") is not None:
            print(f"  📡 标题残留检测: corr={ov_report['stats']['title_corr']}")
        if not ov_report["passed"]:
            print("\n📢 Harness 输出验证拦截（生成后）:")
            for e in ov_report["errors"]:
                print(f"  ❌ {e}")
            print("  禁止交付！请修复后重新生成。")
            sys.exit(3)
        if ov_report.get("warnings"):
            for w in ov_report["warnings"]:
                print(f"  ⚠️ {w}")
        print(f"  ✅ 输出验证通过（{ov_report['stats']['duration']}秒，"
              f"偏差{ov_report['stats'].get('deviation', 0)}%）")
    except SystemExit:
        raise  # 输出验证明确判失败（exit 3），直接传播
    except Exception as e:
        # fail-closed：输出验证异常必须退出，禁止静默跳过
        print(f"\n📢 Harness 输出验证异常（fail-closed）: {e}")
        print("  输出验证无法执行时禁止交付——请修复验证门或检查环境（如 numpy 缺失）。")
        sys.exit(3)
