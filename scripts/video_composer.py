#!/usr/bin/env python3
"""bookmadebook 视频合成器 —— 讲书音频 → 实景动态视频

设计原则（效果先行，2026-08-07 用户确认）：
- 实景写实照片（Unsplash 免费图库），不用 AI 生图
- 同主题连贯画面（如沙漠星空系列），避免场景跳跃
- 交叉溶解过渡（xfade 1.5s），画面平滑流动
- 文字只保留金句 + 书名，淡入淡出
- Ken Burns 缓慢缩放（zoompan），动态不呆板

用法:
    python video_composer.py --script 讲书稿.txt --audio 音频.mp3 --output out.mp4
    python video_composer.py --script 讲书稿.txt --audio 音频.mp3 --theme desert --output out.mp4

主题（--theme）:
    desert    沙漠星空（暖橙→蓝调→夜空，昼夜渐变）
    forest    森林（绿→深绿，静谧）
    ocean     海洋（蓝→深蓝，辽阔）
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
_ORIG_CWD = os.getcwd()
os.chdir(Path(__file__).parent)
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

W, H = 1080, 1920          # 竖版 9:16
ZOOM_W, ZOOM_H = 540, 960  # zoompan 低分辨率，输出前再放大
FPS = 25
XFADE_DUR = 1.5             # 交叉溶解时长
FONT_BOLD = "../assets/fonts/msyhbd.ttc"
FONT_REG = "../assets/fonts/msyh.ttc"

# 主题色板（与场景主题联动，Step 5 完整接入）
THEME_PALETTES = {
    "palace":    {"accent": "0xC9A063", "title_font": "serif"},
    "desert":    {"accent": "0xD8B04A", "title_font": "sans"},
    "forest":    {"accent": "0x8FBC8F", "title_font": "sans"},
    "ocean":     {"accent": "0x58C6F5", "title_font": "sans"},
    "sunrise":   {"accent": "0xE8933F", "title_font": "sans"},
    "starry":    {"accent": "0x9B7EDE", "title_font": "sans"},
    "rain":      {"accent": "0xB23A48", "title_font": "sans"},
    "library":   {"accent": "0xC9A063", "title_font": "serif"},
    "warm_home": {"accent": "0xE0A899", "title_font": "sans"},
    "snow":      {"accent": "0xA8C6E0", "title_font": "sans"},
    "tech_city": {"accent": "0x58C6F5", "title_font": "sans"},
    "temple":    {"accent": "0xC9A063", "title_font": "serif"},
}

# 主题 → 实景图 URL（Unsplash 免费图库，同主题相近画面）
THEMES = {
    "gufeng": [  # 古风：苏州园林/汉服/茶道/古籍（2026-08-21 用户反馈"画面与内容严重不符"后新增）
        "https://images.unsplash.com/photo-1558888401-5e4f3c5d9c3c?w=2160&q=80",
        "https://images.unsplash.com/photo-1567055383923-c4e2f3c0b6a0?w=2160&q=80",
    ],
    "desert": [  # 沙漠星空：黄昏→蓝调→夜空 昼夜渐变
        "https://images.unsplash.com/photo-1542401886-65d6c61db217?w=2160&q=80",
        "https://images.unsplash.com/photo-1509395176047-4a66953fd231?w=2160&q=80",
        "https://images.unsplash.com/photo-1547234935-80c7145ec969?w=2160&q=80",
        "https://images.unsplash.com/photo-1473580044384-7ba9967e16a0?w=2160&q=80",
        "https://images.unsplash.com/photo-1419833173245-f59e1b93f9ee?w=2160&q=80",
        "https://images.unsplash.com/photo-1502134249126-9f3755a50d78?w=2160&q=80",
    ],
    "forest": [
        "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=2160&q=80",
        "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?w=2160&q=80",
        "https://images.unsplash.com/photo-1425913397330-cf8af2ff40a1?w=2160&q=80",
        "https://images.unsplash.com/photo-1448375240586-882707db888b?w=2160&q=80",
    ],
    "ocean": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=2160&q=80",
        "https://images.unsplash.com/photo-1518837695005-2083093ee35b?w=2160&q=80",
        "https://images.unsplash.com/photo-1439405326854-014607f694d7?w=2160&q=80",
        "https://images.unsplash.com/photo-1505142468610-359e7d316be0?w=2160&q=80",
    ],
}


def download_images(theme: str, tmpdir: Path) -> list[Path]:
    """下载主题实景图，竖版裁剪"""
    urls = THEMES.get(theme, THEMES["desert"])
    paths = []
    for i, url in enumerate(urls):
        raw = tmpdir / f"raw_{i}.jpg"
        v = tmpdir / f"img_{i}.jpg"
        try:
            subprocess.run(["curl", "-sL", "-o", str(raw), url],
                           check=True, timeout=60, capture_output=True)
            if HAS_PIL and raw.stat().st_size > 10000:
                from PIL import Image as _Img
                im = _Img.open(raw).convert("RGB")
                w, h = im.size
                target_ratio = H / W
                cur_ratio = h / w
                if cur_ratio > target_ratio:
                    new_h = int(w * target_ratio)
                    top = (h - new_h) // 2
                    im = im.crop((0, top, w, top + new_h))
                else:
                    new_w = int(h / target_ratio)
                    left = (w - new_w) // 2
                    im = im.crop((left, 0, left + new_w, h))
                im = im.resize((W, H), _Img.LANCZOS)
                im.save(v, quality=92)
                paths.append(v)
        except Exception:
            continue
    return paths


def extract_quotes(script_text: str) -> list[str]:
    """从讲书稿提取金句（【金句】标记，优先取引号内本体）"""
    quotes = []
    for m in re.finditer(r"【金句】\s*([^【】\n]{8,120})", script_text):
        q = m.group(1).strip()
        # 优先取「」引号内的内容（金句本体）
        inner = re.findall(r"「([^「」]{6,80})」", q)
        if inner:
            q = inner[-1]  # 取最后一个引号内容
        q = q.strip().strip("「」\"")
        q = re.split(r"[。！？]", q)[0].strip()
        if 6 <= len(q) <= 40 and q not in quotes:
            quotes.append(q)
    return quotes[:6]  # 最多6句（2026-08-18：4→6，开篇提前+加密）


from functools import lru_cache

@lru_cache(maxsize=256)
def _image_is_1080x1920(img) -> bool:
    """场景库输出 1080×1920 时跳过归一化 scale/crop。带缓存（同一图多次调用不重复探测）。
    入参可能是 SceneSegment 对象，需先转 str 才可哈希。"""
    try:
        img = str(img)
    except Exception:
        return False
    try:
        if HAS_PIL:
            with Image.open(str(img)) as im:
                return im.size == (W, H)
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             str(img)],
            capture_output=True, text=True, timeout=10)
        w, h = r.stdout.strip().split("x")
        return int(w) == W and int(h) == H
    except Exception:
        return False


def read_audio_chapters(audio: str) -> list[float]:
    """读取 MP3 ID3 CHAP 章节起始时间；无章节/读取失败返回空列表。"""
    if not audio:
        return []
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_chapters", "-of", "json",
             str(audio)],
            capture_output=True, timeout=30)
        if r.returncode != 0:
            return []
        data = json.loads(r.stdout.decode("utf-8", errors="replace") or "{}")
        starts = []
        for ch in data.get("chapters", []):
            try:
                start = float(ch.get("start_time"))
            except (TypeError, ValueError):
                continue
            if start >= 0:
                starts.append(start)
        starts.sort()
        return starts
    except Exception:
        return []


def _fallback_chapter_times(chapters: list, script_text: str,
                            audio_dur: float) -> list:
    """无 CHAP 时按标题字符位置估算章节时间。"""
    audio_dur_chars = len(script_text) or 1
    times = []
    char_cursor = 0
    for ci, ch in enumerate(chapters):
        idx = script_text.find(ch, char_cursor)
        if idx >= 0:
            times.append(audio_dur * idx / audio_dur_chars)
            char_cursor = max(char_cursor, idx + len(ch))
        else:
            times.append(audio_dur * ci / len(chapters))
    return times


def _fallback_quote_times(quotes: list, audio_dur: float) -> list:
    """无 CHAP 时保留后段均布逻辑。"""
    if not quotes:
        return []
    quote_zone_start = audio_dur * 0.3
    quote_zone = audio_dur * 0.65
    return [quote_zone_start + qi * (quote_zone / len(quotes))
            for qi in range(len(quotes))]


def _quote_times(quotes: list, script_text: str,
                 audio_chapter_starts: list, audio_dur: float) -> list:
    """金句时间轴：按金句在讲书稿中的字符位置比例映射到音频时间轴。

    不能直接取前 N 个 CHAP 起点——音频 CHAP 数量 = 分段数（可远大于金句数），
    前 N 个全堆在开头（朱元璋 10min 实测：前4 CHAP=0/6.9/48.6/49.1s）。
    也不用 CHAP 取整——CHAP 后半段稀疏会再次聚集（257/262/262s）。
    线性映射（稿中位置比例 × 总时长）最贴近金句实际被念到的时刻。
    """
    fb = _fallback_quote_times(quotes, audio_dur)
    if not quotes:
        return []
    if not script_text:
        return fb
    n_chars = len(script_text)
    out = []
    for qi, q in enumerate(quotes):
        qtext = q.strip("「」 ")
        # 前缀匹配（抗标点/句号差异），取前12字定位
        idx = script_text.find(qtext[:12]) if len(qtext) >= 4 else -1
        if idx < 0:
            out.append(fb[qi])
            continue
        t = audio_dur * idx / max(n_chars, 1)
        # 2026-08-18 用户反馈"金句出现晚且少"：第一句金句强制提前
        # 正文前有 38s 开篇（可灵钩子），故首句金句须在正文内 ≤22s
        # （完整视频 38+22=60s 内可见，用户留存关键区）
        # 2026-08-30 再前压：首句金句 ≤12s（60s 留存竞争加剧，3s 判定后
        # 第一个记忆点要尽快出现，否则前 60s 无字卡截图点）
        if qi == 0:
            t = min(t, 12.0)
        out.append(t)
    return out


def _clip_display_start(start, audio_dur: float) -> float:
    """确保淡入区间不会落在音频结束之后。"""
    if audio_dur <= 0:
        return 0.0
    return max(0.0, min(float(start), audio_dur - 1.0))


def resolve_video_items(items: list) -> list:
    """视频真实化：优先使用 <theme>/video/*.mp4 实拍素材。
    输入 [(img, dur)] → 输出 [(path, dur, kind)]，kind ∈ {"image","video"}。
    视频文件充足（≥段数）按顺序轮流取用；不足时均匀间隔插入视频段，
    其余回退静态图——避免单视频被全部段循环复用导致画面严重重复（2026-09-02 修复）。
    """
    out = [None] * len(items)
    groups = {}
    for i, item in enumerate(items):
        if len(item) >= 3:
            out[i] = item  # 已解析，幂等
            continue
        img, dur = item
        vdir = Path(img).parent / "video"
        key = str(vdir)
        if key not in groups:
            groups[key] = {"vids": sorted(vdir.glob("*.mp4")) if vdir.is_dir() else [],
                           "segs": []}
        groups[key]["segs"].append((i, img, dur))
    for g in groups.values():
        vids, segs = g["vids"], g["segs"]
        n = len(segs)
        if not vids:
            for i, img, dur in segs:
                out[i] = (img, dur, "image")
            continue
        if len(vids) >= n:
            for k, (i, img, dur) in enumerate(segs):
                out[i] = (vids[k % len(vids)], dur, "video")
            continue
        # 视频不足：均匀间隔插入（同素材间隔 ≥4 段，其余回退静态图）
        k_video = min(n, max(len(vids), n // 5))
        step = n / k_video
        used = set()
        for k in range(k_video):
            pos = min(n - 1, int(round(k * step)))
            i, img, dur = segs[pos]
            out[i] = (vids[k % len(vids)], dur, "video")
            used.add(pos)
        for k, (i, img, dur) in enumerate(segs):
            if k not in used:
                out[i] = (img, dur, "image")
    return out


# ── 情绪化调色（2026-09-02 引入）──
# 按章节【情绪】标记占比切滤镜：低沉/紧张/神秘→冷暗；温暖/开心/激昂→暖亮；其余中性
EMOTION_FILTERS = {
    "cold": "eq=brightness=-0.02:saturation=0.92,colorbalance=bs=0.06:bm=0.03",
    "warm": "eq=brightness=0.02:saturation=1.06,colorbalance=rs=0.05:gs=0.02",
    "neutral": "",
}
EMOTION_KEYWORDS = {
    "cold": ["低沉", "悲伤", "压抑", "愤怒", "紧张", "神秘", "疑惑", "低落", "阴郁", "灰暗"],
    "warm": ["温暖", "温柔", "感动", "开心", "激昂", "坚定", "感慨", "惊喜", "明亮", "希望"],
}

# xfade 转场池（2026-09-02：按段轮换，章节交界强制 fadeblack 1s 黑场）
XFADE_POOL = ["fadeblack", "smoothleft", "circleopen"]
CHAPTER_XFADE_DUR = 1.0


def _chapter_texts(script_text: str, chapters: list) -> list:
    """按章节切分讲书稿文本：优先【场景】标记位置，其次 ## 标题，兜底整篇。"""
    if not chapters:
        return []
    import scene_selector as ss
    marked = ss.parse_scene_markers(script_text)
    if marked:
        segs, _ = ss.split_by_positions(script_text, marked)
        if len(segs) == len(chapters):
            return segs
    texts, cur = [], []
    for ln in script_text.splitlines():
        if ln.lstrip().startswith("##") and cur:
            texts.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        texts.append("\n".join(cur))
    if len(texts) == len(chapters):
        return texts
    return [script_text] * len(chapters)


def chapter_emotion_filters(script_text: str, chapters: list) -> list:
    """每章【情绪】标记投票 → 调色滤镜（长度=len(chapters)，中性返回空串）。
    只统计标记行（避免正文关键词误配）；cold（低沉/悲伤等强情绪）加权 1.5。"""
    texts = _chapter_texts(script_text, chapters)
    out = []
    for t in texts:
        cnt = {"cold": 0, "warm": 0}
        for m in re.finditer(r"【情绪[:：]\s*([^】]{1,12})】", t):
            name = m.group(1)
            for grp, kws in EMOTION_KEYWORDS.items():
                if any(kw in name for kw in kws):
                    cnt[grp] += 1
                    break
        cnt["cold"] = int(cnt["cold"] * 1.5)
        if cnt["cold"] > cnt["warm"]:
            out.append(EMOTION_FILTERS["cold"])
        elif cnt["warm"] > cnt["cold"]:
            out.append(EMOTION_FILTERS["warm"])
        else:
            out.append(EMOTION_FILTERS["neutral"])
    return out


def _item_emotion_filters(script_text: str, chapters: list, seg_chapter: list,
                          items_per_seg: list) -> list:
    """逐 item 情绪滤镜：item 按章节内字符位置就近取【情绪】标记（段落级）。
    仅段数=章节数（标记驱动）时启用，否则回退章节级。"""
    n = len(seg_chapter)
    if len(items_per_seg) != len(chapters) or n == 0:
        ch_filters = chapter_emotion_filters(script_text, chapters)
        return [ch_filters[seg_chapter[i]] if seg_chapter else ""
                for i in range(n)]
    texts = _chapter_texts(script_text, chapters)
    marks = []
    for t in texts:
        ms = []
        for m in re.finditer(r"【情绪[:：]\s*([^】]{1,12})】", t):
            g = None
            for grp, kws in EMOTION_KEYWORDS.items():
                if any(kw in m.group(1) for kw in kws):
                    g = grp
                    break
            ms.append((m.start(), g))
        marks.append(ms)
    counters = [0] * len(items_per_seg)
    out = []
    for i in range(n):
        seg_i = seg_chapter[i]
        t = texts[seg_i] if seg_i < len(texts) else ""
        frac = counters[seg_i] / max(items_per_seg[seg_i], 1)
        counters[seg_i] += 1
        char_pos = int(frac * len(t))
        group = None
        for pos, grp in (marks[seg_i] if seg_i < len(marks) else []):
            if pos <= char_pos:
                group = grp
            else:
                break
        out.append(EMOTION_FILTERS.get(group or "neutral", ""))
    return out


def _chapter_bg_images(plan, n_chapters: int) -> list:
    """每章章节卡的背景图：优先章节首帧场景图；段数与章节数不符时从全部素材均取。"""
    bgs = []
    segs = getattr(plan, "segments", [])
    if len(segs) == n_chapters:
        for ci, seg in enumerate(segs):
            imgs = getattr(seg, "images", []) or []
            # 同主题多章时 images 列表相同，按章节号错位取图避免背景雷同
            bgs.append(str(imgs[ci % len(imgs)]) if imgs else "")
        return bgs
    pool = []
    for seg in segs:
        pool += [str(p) for p in getattr(seg, "images", []) or []]
    if not pool:
        return [""] * n_chapters
    for ci in range(n_chapters):
        bgs.append(pool[min(ci * len(pool) // max(n_chapters, 1), len(pool) - 1)])
    return bgs


_VID_PROBE_CACHE = {}


def _probe_video_dur(path) -> float:
    """ffprobe 取视频时长（秒），失败返回 0；同素材多次探测走缓存。"""
    key = str(path)
    if key in _VID_PROBE_CACHE:
        return _VID_PROBE_CACHE[key]
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=20)
        dur = float(r.stdout.strip() or 0)
    except Exception:
        dur = 0.0
    _VID_PROBE_CACHE[key] = dur
    return dur


def _clip_motion(path, samples: int = 4) -> float:
    """快速运动量估计：1s 间隔抽 samples+1 帧，相邻帧灰度差均值。
    用于纯视频选材——优先"有运动镜头"（2026-09-02 素材铁律），
    避免选中近乎静止的室内/长焦段导致画面像静态图。结果按素材缓存。"""
    key = (str(path), samples)
    if key in _VID_PROBE_CACHE:
        return _VID_PROBE_CACHE[key]
    import tempfile
    with tempfile.TemporaryDirectory(prefix="lb_mot_") as td:
        tmpl = str(Path(td) / "f_%02d.png")
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(path),
                 "-vf", "fps=1,scale=36:64", "-frames:v", str(samples + 1), tmpl],
                capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                _VID_PROBE_CACHE[key] = 0.0
                return 0.0
        except Exception:
            _VID_PROBE_CACHE[key] = 0.0
            return 0.0
        lums = []
        for i in range(1, samples + 2):
            p = Path(td) / f"f_{i:02d}.png"
            if p.exists():
                try:
                    from PIL import Image
                    im = Image.open(p).convert("L")
                    px = list(im.getdata())
                    lums.append(sum(px) / len(px))
                except Exception:
                    pass
        if len(lums) < 2:
            _VID_PROBE_CACHE[key] = 0.0
            return 0.0
        diffs = [abs(lums[i] - lums[i - 1]) for i in range(1, len(lums))]
        _VID_PROBE_CACHE[key] = sum(diffs) / len(diffs)
        return _VID_PROBE_CACHE[key]


def _split_long_segments(plan, audio_dur: float, clip: float = 20.0):
    """长段自动子段化（2026-09-02 纯视频默认后新增，仅长片 >90s 调用）：
    长章按 ~clip 秒拆成子段，避免"一章 100s 只循环同一段素材"的画面重复。
    子段继承原章 chapter_idx，供章卡/黑场边界/情绪滤镜正确归属。
    clip 默认 20s（2026-09-02 实测校准）：warm_home 9 段素材里 ≥21.2s 的
    只有 3 段（clip=30 时），降到 20s 后 5 段动态素材（04/06/07/08/09）
    可无接缝入池轮转；画面仍远低于用户可接受的切段节奏。"""
    import scene_selector
    segs = list(getattr(plan, "segments", []))
    if not segs:
        return plan
    new_segs = []
    for ci, seg in enumerate(segs):
        dur = max(0.5, float(seg.end - seg.start))
        n = max(1, int(dur / clip + 0.999))
        if n == 1:
            setattr(seg, "chapter_idx", ci)
            new_segs.append(seg)
            continue
        step = dur / n
        for k in range(n):
            sub = scene_selector.SceneSegment(
                theme=seg.theme,
                start=seg.start + k * step,
                end=seg.start + (k + 1) * step if k < n - 1 else seg.end,
                chapter_title=seg.chapter_title,
            )
            setattr(sub, "chapter_idx", ci)
            new_segs.append(sub)
    plan.segments = new_segs
    return plan


def _pure_video_items(plan, need_slack: float = 1.2) -> list:
    """纯视频模式 items：每段挑 1 个时长 ≥ 段长+slack 的竖版实拍视频。
    选材策略：时长够的候选中按运动量降序整池轮转（有运动镜头优先 + 画面不重复）：
    一轮内不重复用素材；素材耗尽时清空计数从头轮转，仅保证不与上一段相邻同素材，
    避免"只有 2-3 段够长素材时退化成 top-2 反复交替"（2026-09-02 长片实测）。
    无足够长素材时选最长并警告。返回 [(视频路径, 段时长, 'video')]，零静态图。"""
    import scene_library
    base = scene_library.SCENES_DIR
    out = []
    picked = set()  # 本轮已用素材（一轮耗尽自动清空 → 整池轮转）
    prev_pick = None
    for seg in getattr(plan, "segments", []):
        seg_dur = max(2.0, float(seg.end - seg.start))
        need = seg_dur + need_slack
        vdir = base / seg.theme / "video"
        vids = sorted(vdir.glob("*.mp4")) if vdir.is_dir() else []
        if not vids:
            print(f"  ❌ 纯视频模式：主题 [{seg.theme}] 无 assets/scenes/<theme>/video/*.mp4")
            import sys
            sys.exit(1)
        long_enough = [v for v in vids if _probe_video_dur(v) >= need]
        if not long_enough:
            ranked = sorted(vids, key=_probe_video_dur, reverse=True)
            print(f"  ⚠️ 主题 [{seg.theme}] 无 ≥{need:.0f}s 视频，用 {ranked[0].name}（不足则截尾）")
        else:
            # 时长足够 → 运动量降序（真实运动优先）；已运动量缓存，不重复 ffmpeg
            ranked = sorted(long_enough, key=_clip_motion, reverse=True)
        rest = [v for v in ranked if v not in picked and v != prev_pick]
        if not rest:
            rest = [v for v in ranked if v != prev_pick]
            picked.clear()  # 整池轮转完一轮，清空计数从头开始
        pick = rest[0] if rest else ranked[0]
        picked.add(pick)
        prev_pick = pick
        out.append((str(pick), seg_dur, "video"))
    return out

def _place_text_window(want: float, hold: float, busy: list, dur: float,
                       min_hold: float = 2.4) -> tuple:
    """在 busy（已排序的占用窗 [(s,e)]）的空闲缝里，为一条字卡找 [ts,te]。
    起点尽量 ≥ want；窗口长度 ≤ hold 且 ≥ min_hold；找不到返回 None。"""
    if not busy:
        start = max(0.3, want)
        if start < dur - 0.3:
            return start, min(dur - 0.3, start + hold)
        return None
    cursor = 0.0
    for a, b in busy:
        if a > cursor + min_hold + 0.2:
            gap_s, gap_e = cursor, a
            # 缝隙放不下完整 hold 时起始尽量回退填满（≥ gap_s+0.3 防与上窗淡出重叠）
            start = max(gap_s + 0.3, min(max(want, gap_s + 0.3),
                                         gap_e - 0.3 - hold))
            h = min(hold, gap_e - 0.3 - start)
            if h >= min_hold:
                return start, start + h
        cursor = max(cursor, b)
    if cursor < dur - 1.0:
        start = max(cursor + 0.3, want)
        if start < dur - 1.0:
            h = min(hold, dur - start - 0.3)
            if h >= min_hold:
                return start, start + h
    return None


def make_filter(plan, audio_dur: float, quotes: list[str],
                book_title: str, author: str = "", script_text: str = "",
                audio: str = "", items=None, pure_video=False,
                no_cta=False):
    """构建 ffmpeg filter_complex：Ken Burns + xfade + 金句文字
    plan: ScenePlan（支持可变时长分段 + 多场景）
    audio: 有 CHAP 时用于对齐章节/金句时间
    items: 外部构造好的素材列表（None=内部按静帧展平+视频替换）
    pure_video: 纯视频模式（2026-09-02 用户定案）——素材原样播放，
                零静态图/零 Ken Burns/零缩放增强，只做 cover 裁切+fps 对齐
    no_cta: 不叠结尾 CTA 引导帧（演示/预览用；章节卡有尾窗时防叠）"""
    # 章节标题提取（## 标题）——先于素材循环，供情绪调色/章节卡/转场使用
    chapters = []
    for line in script_text.splitlines():
        line = line.strip()
        if line.startswith("##"):  # 只认 ## 章节标题（首行 # 书名不算章节）
            t = re.sub(r"^#+\s*", "", line).strip()
            if t:
                chapters.append(t)
    if items is None:
        items = plan.images_with_durations() if hasattr(plan, "images_with_durations") else \
            [(p, audio_dur / len(plan)) for p in plan]
        items = resolve_video_items(items)
    n = len(items)
    # item → 章节映射（段数=章节数时逐段对齐，否则兜底全部归第 0 章）
    seg_chapter, items_per_seg = [], []
    for si, seg in enumerate(getattr(plan, "segments", [])):
        cnt = 1 if pure_video else len(getattr(seg, "images", []) or [])
        ch_idx = getattr(seg, "chapter_idx", si)  # 子段化后归原章（2026-09-02）
        items_per_seg.append(cnt)
        seg_chapter += [ch_idx] * cnt
    if len(seg_chapter) != n:
        seg_chapter = [0] * n
    if pure_video:
        # 纯视频每段 1 段素材=整章，段落级就近取值无意义 → 用章节级多数投票
        ch_filters = chapter_emotion_filters(script_text, chapters)
        item_emotions = [ch_filters[seg_chapter[i]] if seg_chapter else ""
                         for i in range(n)]
    else:
        item_emotions = _item_emotion_filters(script_text, chapters, seg_chapter,
                                              items_per_seg)
    # 交叉溶解时长动态化（2026-08-30 修复短版冻结 bug）：
    # 固定 1.5s 在短版（每图 1.3-1.6s）会导致 offset=total-XFADE 为负 → xfade 冻结。
    # 取 min(1.5, 最短图时长*0.5)，保证 offset 恒为正；长版（每图 10s+）不受影响。
    min_dur = min(d for _, d, _ in items) if items else audio_dur
    xfade_dur = min(XFADE_DUR, max(0.4, min_dur * 0.5))
    parts = []
    # 每张图 Ken Burns 缩放（独立时长）；非 1080×1920 先归一化，再降采样给 zoompan
    # 缩放速度按段时长分配：zoom 从 1.0→1.15 铺满整段（on=输出帧号），避免"4秒后静止"
    # 输入用单帧（不用 -loop 1 循环流），d 扩到 dur+xfade_dur 保证 xfade 重叠区帧数，
    # 避免循环流输入被 zoompan 逐帧放大（N 输入帧 × d 输出帧 = 数百倍冗余计算）
    for i, item in enumerate(items):
        img, dur, kind = item
        zoom_in = (i % 2 == 0)
        emo = item_emotions[i] if i < len(item_emotions) else ""
        emo_sfx = f",{emo}" if emo else ""
        if kind == "video":
            if pure_video:
                # 纯视频模式（用户定案 2026-09-02）：素材原样播放，
                # 只做 cover 裁切 + fps 对齐，零 zoompan/零缩放增强/零起点偏移
                parts.append(
                    f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{H},fps={FPS},"
                    f"scale={W}:{H}:flags=lanczos{emo_sfx},"
                    f"trim=duration={dur+xfade_dur},setpts=PTS-STARTPTS[v{i}]"
                )
                continue
            # 旧视频分支（非纯视频模式保留）：cover 裁切 + 轻微 zoom(1.0→1.05)
            # + 段起点偏移（第 i 段从素材 i*3s 起播，配合 -stream_loop -1 循环取帧）
            start = i * 3
            parts.append(
                f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},fps={FPS},scale={ZOOM_W}:{ZOOM_H},"
                f"zoompan=z='min(1.0+0.05*on/{max(int(dur*FPS),1)},1.05)':"
                f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"s={ZOOM_W}x{ZOOM_H}:fps={FPS},"
                f"scale={W}:{H}:flags=lanczos{emo_sfx},"
                f"trim=start={start}:duration={dur+xfade_dur},setpts=PTS-STARTPTS[v{i}]"
            )
        else:
            zexpr = (f"min(1.0+0.15*on/{max(int(dur*FPS),1)},1.15)"
                     if zoom_in else
                     f"max(1.15-0.15*on/{max(int(dur*FPS),1)},1.0)")
            normalize = ("" if _image_is_1080x1920(str(img)) else
                         f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                         f"crop={W}:{H},")
            parts.append(
                f"[{i}:v]{normalize}scale={ZOOM_W}:{ZOOM_H},"
                f"zoompan=z='{zexpr}':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={int((dur+xfade_dur)*FPS)}:s={ZOOM_W}x{ZOOM_H}:fps={FPS},"
                f"scale={W}:{H}:flags=lanczos{emo_sfx},"
                f"trim=duration={dur+xfade_dur},setpts=PTS-STARTPTS[v{i}]"
            )
    # xfade 交叉溶解（累计可变时长）
    # 2026-08-30 修复：total 必须 += dur（不能 -= xfade）。
    # xfade 输出时长 = offset + B总长，而 offset = total - xfade 已含过渡扣除，
    # 再减 xfade 会导致累计缩水（长版每图15s缩10%不明显；短版每图1.35s错位一半，
    # 实测 40 图总长 30.4s vs 音频 56.8s，starry 段整体前移 10s）。
    prev = "v0"
    total = items[0][1]
    pool_i = 0
    for i in range(1, n):
        out = f"x{i}"
        # 章节交界 → fadeblack 1s 黑场；段内 → 转场池轮换（2026-09-02）
        is_chapter_boundary = seg_chapter[i] != seg_chapter[i - 1]
        if is_chapter_boundary:
            trans = "fadeblack"
            td = min(CHAPTER_XFADE_DUR, max(0.4, min_dur * 0.5))
        else:
            trans = XFADE_POOL[pool_i % len(XFADE_POOL)]
            pool_i += 1
            td = xfade_dur
        offset = total - td
        parts.append(f"[{prev}][v{i}]xfade=transition={trans}:duration={td}:offset={offset}[{out}]")
        prev = out
        total += items[i][1]

    # ── 文字层（PIL 预渲染 PNG overlay，替代 drawtext）──
    import text_layers as tl
    audio_chapter_starts = read_audio_chapters(audio)
    layers = tl.render_all(book_title, quotes, chapters, author=author,
                           watermark=book_title)
    # 章节卡（序号+标题+背景虚化）：替换旧的小章节标签，背景=章节首帧场景
    if chapters:
        cards = tl.render_chapter_cards(chapters, _chapter_bg_images(plan, len(chapters)))
        layers.update(cards)
        for ci in range(len(chapters)):
            layers.pop(f"chapter_{ci}", None)  # 旧小标签弃用，避免死输入
    # 全部文字层作为 PNG 输入
    png_inputs = []
    png_map = {}
    for k, v in layers.items():
        if k == "_tmpdir":
            continue
        png_inputs.append(v)
        png_map[k] = len(png_inputs) - 1
    n_png = len(png_inputs)
    png_base = n  # PNG 输入基础偏移 = 图片输入数

    text_parts = []
    prev_v = prev
    # ── 文字时间窗排程（2026-09-02 用户打回修复：任何时刻最多一组字卡）──
    # 章节卡窗口优先固定；书名卡淡出提前避让首卡；金句只放进空闲缝隙。
    busy = []  # [(start, end)] 已占用的字卡可见窗
    # ② 章节卡窗口（先算，供书名/金句避让）
    card_wins = []
    if chapters:
        # 段数=章节数（标记驱动）时直接用 plan 段起点——与 xfade 黑场边界严格对齐
        # （生产环境该起点即 CHAP 时间；无 CHAP 时按字数比例，与段边界同源）
        plan_segs = getattr(plan, "segments", [])
        if len(plan_segs) == len(chapters):
            chapter_times = [seg.start for seg in plan_segs]
        else:
            fallback_chapter_times = _fallback_chapter_times(
                chapters, script_text, audio_dur)
            chapter_times = [
                audio_chapter_starts[ci] if ci < len(audio_chapter_starts)
                else fallback_chapter_times[ci]
                for ci in range(len(chapters))
            ]
        for ci, ch in enumerate(chapters):
            if ci == 0:
                continue
            ck = f"card_{ci}"
            if ck not in png_map:
                continue
            st = chapter_times[ci]
            et_limit = audio_dur - 0.5
            if "cta" in png_map and audio_dur <= 90 and not no_cta:
                et_limit = min(et_limit, audio_dur - 4.0 - 0.3)  # CTA 前收
            if ci < len(chapters) - 1:
                et = min(st + 3.2, chapter_times[ci + 1] - 0.5, et_limit)
            else:
                et = min(st + 3.2, et_limit)
            if et - st < 1.2:
                continue
            card_wins.append((ci, st + 0.2, et))  # (章节下标, 淡入点, 淡出完成点)
    # ① 书名：0s 全显；淡出起点提前避让首张章节卡（短片章节早时不再叠卡）
    bk_fade_out = 8.5
    if card_wins:
        # 首卡淡入前需留 ≥0.8s 淡出 + 0.2s 缓冲
        bk_fade_out = min(bk_fade_out, card_wins[0][1] - 0.3 - 0.8 - 0.2)
    bk_fade_out = max(0.6, bk_fade_out)
    bk_idx = png_map["book"]
    text_parts.append(f"[{png_base+bk_idx}:v]format=rgba,"
                      f"fade=t=in:st=0:d=0.3:alpha=1,"
                      f"fade=t=out:st={bk_fade_out:.2f}:d=0.8:alpha=1[bk]")
    text_parts.append(f"[{prev_v}][bk]overlay=0:0[o_book]")
    prev_v = "o_book"
    busy.append((0.0, bk_fade_out + 0.8))
    # 生成章节卡 overlay（窗口已先占位）
    for ci, cin, cout in card_wins:
        c_idx = png_map[f"card_{ci}"]
        text_parts.append(f"[{png_base+c_idx}:v]format=rgba,"
                          f"fade=t=in:st={cin}:d=0.4:alpha=1,"
                          f"fade=t=out:st={cout-0.5}:d=0.5:alpha=1[card{ci}]")
        text_parts.append(f"[{prev_v}][card{ci}]overlay=0:0[o_card{ci}]")
        prev_v = f"o_card{ci}"
        busy.append((cin, cout))
    # CTA 帧窗也占位（防金句与结尾引导叠字）
    if "cta" in png_map and audio_dur <= 90 and not no_cta:
        busy.append((max(0.0, audio_dur - 4.0), audio_dur))
    busy.sort()

    # ③ 金句：按稿中位置映射 CHAP 时间轴，但只放进 busy 的空闲缝隙
    # （不能取前N个CHAP——数量不一致会全堆开头；2026-09-02 增加缝隙排程防叠字）
    if quotes:
        fallback_quote_times = _fallback_quote_times(quotes, audio_dur)
        quote_times = _quote_times(quotes, script_text,
                                   audio_chapter_starts, audio_dur)
        has_cta = "cta" in png_map and audio_dur <= 90
        for qi, q in enumerate(quotes):
            qk = f"quote_{qi}"
            is_last = (qi == len(quotes) - 1)
            # 短版（≤90s）金句显示 6s（3-4 句字卡不重叠）；长版 12s
            quote_hold = 6.0 if audio_dur <= 90 else 12.0
            want = _clip_display_start(quote_times[qi], audio_dur)
            # 末句若天然靠近片尾（无 CTA）则意图保持到结尾（升华收束）
            if is_last and audio_dur - want <= 18 and not has_cta:
                hold = max(2.4, audio_dur - want - 0.3)
            else:
                hold = quote_hold
            placed = _place_text_window(want, hold, busy, audio_dur)
            if placed is None:
                continue  # 无可放缝隙 → 该句不显示（宁可缺不叠字）
            ts, te = placed
            if is_last and te >= audio_dur - 0.2 and not has_cta:
                fade_out = ""  # 保持到结尾
            else:
                fade_out = f",fade=t=out:st={te-0.8:.2f}:d=0.8:alpha=1"
            q_idx = png_map[qk]
            text_parts.append(f"[{png_base+q_idx}:v]format=rgba,"
                              f"fade=t=in:st={ts+0.5:.2f}:d=0.8:alpha=1{fade_out}[q{qi}]")
            text_parts.append(f"[{prev_v}][q{qi}]overlay=0:0[p{qi}]")
            prev_v = f"p{qi}"
            # 出处：仅最后一句（与金句同窗，属同一组文字）
            if is_last and "attribution" in png_map:
                a_idx = png_map["attribution"]
                text_parts.append(f"[{png_base+a_idx}:v]format=rgba,"
                                  f"fade=t=in:st={ts+0.5:.2f}:d=0.8:alpha=1{fade_out}[attr]")
                text_parts.append(f"[{prev_v}][attr]overlay=0:0[p_attr]")
                prev_v = "p_attr"
            busy.append((ts, te))
            busy.sort()

    # ④⑤ 进度条：轨道常驻 + 填充 crop 增长
    pt_idx = png_map["progress_track"]
    text_parts.append(f"[{png_base+pt_idx}:v]format=rgba[pt]")
    text_parts.append(f"[{prev_v}][pt]overlay=0:0[t_pt]")
    prev_v = "t_pt"
    pf_idx = png_map["progress_fill"]
    text_parts.append(f"[{png_base+pf_idx}:v]format=rgba,"
                      f"crop=w=max(2\\,iw*min(t/{audio_dur}\\,1)):h=ih[pf]")
    text_parts.append(f"[{prev_v}][pf]overlay=0:0[t_pf]")
    prev_v = "t_pf"

    # ⑥ 水印
    if "watermark" in png_map:
        w_idx = png_map["watermark"]
        text_parts.append(f"[{png_base+w_idx}:v]format=rgba[wm]")
        text_parts.append(f"[{prev_v}][wm]overlay=0:0[wm_out]")
        prev_v = "wm_out"

    # ⑦.5 结尾 CTA 引导帧（2026-08-30：片尾最后 4s 淡入，蔡格尼克+互动）
    # 只对短版（≤90s）启用——长版正片末尾是金句升华，不叠加引导
    if "cta" in png_map and audio_dur <= 90 and not no_cta:
        c_idx = png_map["cta"]
        c_st = max(0.0, audio_dur - 4.0)
        text_parts.append(f"[{png_base+c_idx}:v]format=rgba,"
                          f"fade=t=in:st={c_st}:d=0.5:alpha=1[cta]")
        text_parts.append(f"[{prev_v}][cta]overlay=0:0[cta_out]")
        prev_v = "cta_out"

    # ⑧ AI 生成角标（合规标识，常驻最上层）
    if "ai_badge" in png_map:
        a_idx = png_map["ai_badge"]
        text_parts.append(f"[{png_base+a_idx}:v]format=rgba[ab]")
        text_parts.append(f"[{prev_v}][ab]overlay=0:0,format=yuv420p[vout]")
    else:
        text_parts.append(f"[{prev_v}]format=yuv420p[vout]")

    parts.extend(text_parts)
    return ";".join(parts), png_inputs


def get_duration(audio: str) -> float:
    """获取音频时长"""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", audio], capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip() or 60)


def main():
    ap = argparse.ArgumentParser(description="bookmadebook 视频合成器")
    ap.add_argument("--script", required=True, help="讲书稿 txt")
    ap.add_argument("--audio", required=True, help="音频 mp3")
    ap.add_argument("--output", default="output.mp4", help="输出视频路径")
    ap.add_argument("--theme", default="auto", choices=["auto"] + sorted(set(
        list(THEMES.keys()) + ["palace", "sunrise", "starry", "rain", "library",
                               "warm_home", "snow", "tech_city", "temple",
                               "arctic", "ww2", "ship", "hongkong", "pasture",
                               "finance", "guyuan"])),
                    help="实景主题；auto=按内容自动选择（默认）；手动指定则整片使用该主题")
    ap.add_argument("--scene-from", default="auto", choices=["auto", "script", "manual"],
                    help="场景来源：auto=标记+自动检测，script=仅用标记，manual=仅用--theme")
    ap.add_argument("--dry-run", action="store_true", help="只输出场景规划不合成")
    ap.add_argument("--book", default="", help="书名（封面文字）")
    ap.add_argument("--author", default="", help="作者")
    ap.add_argument("--fast", action="store_true", help="快速模式：crf 26（默认 preset faster；长视频/预览用）")
    ap.add_argument("--sfx", default="none", choices=["none", "tick"],
                    help="音效锚点（2026-08-30）：none=纯人声（默认）；tick=开场+每20s 低频柔和钟声（-36dB，听觉锚点不喧宾夺主）")
    ap.add_argument("--pure-video", action="store_true",
                    help="[兼容保留] 纯视频模式已为默认（2026-09-02 用户定案），显式传此参数无额外效果")
    ap.add_argument("--legacy-stills", action="store_true",
                    help="显式退回旧静态图 Ken Burns 路径（默认已纯视频：实拍视频原样播放，零静态图/零缩放）")
    ap.add_argument("--no-cta", action="store_true",
                    help="不叠结尾 CTA 引导帧（演示/预览；短片尾章卡有窗时防叠字）")
    args = ap.parse_args()
    if args.legacy_stills and args.pure_video:
        ap.error("--pure-video 与 --legacy-stills 互斥（纯视频已是默认，无需传 --pure-video）")
    pure_video = not args.legacy_stills  # 纯视频默认（2026-09-02 用户定案，cron 无需额外传参）

    def _abs(p: str) -> str:
        pth = Path(p)
        return str(pth if pth.is_absolute() else Path(_ORIG_CWD) / pth)

    args.script = _abs(args.script)
    args.audio = _abs(args.audio)
    args.output = _abs(args.output)

    script_text = Path(args.book).read_text(encoding="utf-8") if False else \
        Path(args.script).read_text(encoding="utf-8", errors="replace")
    book_title = args.book or Path(args.script).stem
    quotes = extract_quotes(script_text)

    print(f"📖 书名: {book_title}")
    print(f"💬 提取金句: {len(quotes)} 句")
    for q in quotes:
        print(f"   「{q}」")

    audio_dur = get_duration(args.audio)
    print(f"⏱️ 音频时长: {audio_dur:.1f}s")

    # 场景规划（scene_selector：手动 > 标记 > 自动检测）
    import scene_selector
    theme_arg = args.theme
    if args.scene_from == "manual":
        theme_arg = args.theme if args.theme != "auto" else "desert"
    plan = scene_selector.select_scenes(script_text, theme_arg, audio_dur, args.audio)
    if pure_video and audio_dur > 90:
        # 长片（10 分钟正文）长段子段化（~30s/子段），防"一章 100s 只循环同一段素材"；
        # 短片≤90s 本就多段轮换且需保持章卡-黑场严格对齐，不拆
        plan = _split_long_segments(plan, audio_dur)
    print(f"🎬 场景规划: {len(plan.segments)} 段" + ("（纯视频子段化）" if pure_video else ""))
    for seg in plan.segments:
        print(f"   [{seg.start:.0f}s-{seg.end:.0f}s] {seg.theme}"
              + (f" {seg.chapter_title}" if seg.chapter_title else ""))

    if args.dry_run:
        print("✅ dry-run 完成（未合成）")
        return

    with tempfile.TemporaryDirectory(prefix="lb_video_") as td:
        tmpdir = Path(td)
        print("🖼️ 加载本地素材库...")
        import scene_library
        plan = scene_library.load_plan_images(plan)
        if pure_video:
            # 纯视频模式：每段 1 个实拍视频（images 仍加载，仅作章节卡背景虚化用）
            items = _pure_video_items(plan)
            print(f"🎬 纯视频模式：每段 1 段实拍视频（{len(items)} 段，零静态图）")
        else:
            # 短片/演示限帧（2026-09-02）：BOOKMADEBOOK_IMAGES_PER_SEG=N 时每段最多用 N 张静帧，
            # 拉长单帧停留（默认不启用，10 分钟长片/60s 钩子节奏不受影响）
            _cap = os.environ.get("BOOKMADEBOOK_IMAGES_PER_SEG")
            if _cap:
                _n = max(1, int(_cap))
                for _seg in plan.segments:
                    _seg.images = _seg.images[:_n]
            items = resolve_video_items(plan.images_with_durations())
        images = [p for p, _, _ in items]
        durations = [d for _, d, _ in items]
        n_vid = sum(1 for _, _, k in items if k == "video")
        print(f"✅ 使用 {len(images)} 段素材（实拍视频 {n_vid} 段 + 静态图 {len(images)-n_vid} 段）")

        # 视频帧流（无音频）
        flt, png_inputs = make_filter(plan, audio_dur, quotes, book_title,
                                      args.author, script_text, args.audio,
                                      items=items, pure_video=pure_video,
                                      no_cta=args.no_cta)
        video_mp4 = tmpdir / "video_noaudio.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error"]
        # 图片输入用单帧（Ken Burns 由 zoompan 的 d 参数生成帧序列），
        # 不用 -loop 1 循环流——循环流会让 zoompan 对每个输入帧都输出 d 帧，
        # 产生 N×d 倍冗余中间帧（实测 175 输入帧 × d=175 = 30,625 帧）
        for path, _dur, kind in items:
            if kind == "video":
                # 短视频循环铺满段长（trim 截断）；图片保持单帧输入
                cmd += ["-stream_loop", "-1", "-i", str(path)]
            else:
                cmd += ["-i", str(path)]
        # 文字层 PNG 输入
        for png in png_inputs:
            cmd += ["-loop", "1", "-t", str(audio_dur), "-i", str(png)]
        cmd += ["-filter_complex", flt, "-map", "[vout]",
                "-c:v", "libx264", "-preset", "faster",
                "-crf", "26" if args.fast else "23",
                "-t", f"{audio_dur}", str(video_mp4)]
        if pure_video:
            print("🎬 合成视频（实拍视频原样播放 + 黑场转场 + 章节卡/金句字卡）...")
        else:
            print("🎬 合成视频（Ken Burns + 交叉溶解 + 金句）...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if r.returncode != 0:
            print(f"❌ 合成失败: {r.stderr[-500:]}")
            sys.exit(1)

        # 混入音频
        print("🎵 混入音频...")
        # -map_metadata -1：丢弃源 mp3 的 ID3 CHAP 章节，否则章节会被
        # mux 成 text 轨带进 mp4（时长可能超出正片，播放器判定文件异常）
        # -movflags +faststart：moov 移到文件头，提升流式播放兼容性
        cmd2 = ["ffmpeg", "-y", "-v", "error", "-i", str(video_mp4),
                "-i", args.audio, "-map", "0:v:0", "-map", "1:a:0",
                "-map_metadata", "-1", "-c:v", "copy", "-c:a", "aac",
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-b:a", "128k", "-movflags", "+faststart",
                "-shortest", args.output]
        # 音效锚点（2026-08-30 可选，--sfx tick：开场+每20s 一个低频柔和钟声）
        # 默认 none=纯人声红线；音量 -36dB 以下，仅作听觉锚点不喧宾夺主
        if getattr(args, "sfx", "none") == "tick":
            n_tick = max(1, int(audio_dur / 20))
            sfx_parts, sfx_mix = [], []
            for k in range(n_tick):
                delay_ms = int(k * 20 * 1000)
                sfx_parts.append(
                    f"sine=frequency=65:duration=0.12,"
                    f"volume=0.016,adelay={delay_ms}|{delay_ms}[sfx{k}]")
                sfx_mix.append(f"[sfx{k}]")
            sfx_filter = ";".join(sfx_parts + [
                f"{''.join(sfx_mix)}amix=inputs={n_tick}:normalize=0,"
                f"lowpass=f=400[sfxmix]"])
            cmd2 = ["ffmpeg", "-y", "-v", "error", "-i", str(video_mp4),
                    "-i", args.audio, "-filter_complex",
                    f"{sfx_filter};[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[am];"
                    f"[am][sfxmix]amix=inputs=2:normalize=0[aout]",
                    "-map", "0:v:0", "-map", "[aout]",
                    "-map_metadata", "-1", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "128k", "-movflags", "+faststart",
                    "-shortest", args.output]
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        if r2.returncode != 0:
            print(f"❌ 音频混入失败: {r2.stderr[-300:]}")
            sys.exit(1)

    print(f"✅ 完成！输出: {args.output}")


if __name__ == "__main__":
    main()
