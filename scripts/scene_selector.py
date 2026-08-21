#!/usr/bin/env python3
"""scene_selector.py —— 按讲书稿内容自动选择视频场景主题

决策优先级（从高到低）：
    1. 手动 --theme/--scene 指定（整片单一主题）
    2. 讲书稿内【场景：XX】标记（章节级）
    3. 自动检测：复用 streaming_pipeline.detect_content_type → 内容类型 → 主题
    4. 兜底 desert

设计依据：multi-agent 研讨《bookmadebook_scene_library_design.md》§3
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

# 内容类型 → 主题映射（与 CONTENT_VOICES 类别对齐，新增主题见 manifest.json）
CONTENT_THEME_MAP = {
    "童话":     "forest",      # 童话/少儿 → 森林
    "儿童科普": "forest",      # 科普 → 森林
    "职场":     "tech_city",   # 职场 → 都市夜景
    "悬疑":     "rain",        # 悬疑 → 雨夜城市
    "励志":     "sunrise",     # 励志 → 日出山川
    "情感":     "warm_home",   # 情感 → 暖光家居
    "历史":     "palace",      # 历史/传记 → 古建宫殿（账号主力）
    "通用":     "desert",      # 兜底 → 沙漠星空
}

# 【场景：XX】中文别名 → 主题 ID（支持中文标记）
THEME_ALIASES = {
    "宫殿": "palace", "古建": "palace", "皇宫": "palace", "历史": "palace",
    "古风": "gufeng", "园林": "gufeng", "水墨": "gufeng", "江南": "gufeng", "庭院": "gufeng", "古籍": "gufeng", "汉服": "gufeng", "文人": "gufeng",
    "沙漠": "desert", "星空": "desert", "沙丘": "desert",
    "海洋": "ocean", "海边": "ocean", "大海": "ocean", "海": "ocean",
    "森林": "forest", "树林": "forest", "自然": "forest", "童话": "forest",
    "日出": "sunrise", "山巅": "sunrise", "山川": "sunrise", "山": "sunrise",
    "银河": "starry", "夜空": "starry", "宇宙": "starry", "科幻": "starry",
    "雨夜": "rain", "城市雨夜": "rain", "悬疑": "rain", "暗夜": "rain",
    "书房": "library", "书香": "library", "书": "library", "学习": "library",
    "暖光": "warm_home", "家居": "warm_home", "家庭": "warm_home", "情感": "warm_home",
    "雪": "snow", "雪境": "snow", "冬日": "snow",
    "战争": "ww2", "军事": "ww2", "士兵": "ww2", "战役": "ww2", "战场": "ww2", "二战": "ww2", "纳粹": "ww2", "德苏": "ww2", "盟军": "ww2", "日军": "ww2",
    "都市": "tech_city", "城市": "tech_city", "夜景": "tech_city", "商业": "tech_city",
    "船": "ship", "航运": "ship", "货轮": "ship", "集装箱": "ship", "港口": "ship", "海港": "ship", "船舶": "ship",
    "香港": "hongkong", "特首": "hongkong", "维多利亚港": "hongkong",
    "羊": "pasture", "羊群": "pasture", "牧场": "pasture", "牧民": "pasture", "牧羊": "pasture", "转场": "pasture", "牲畜": "pasture",
    "寺庙": "temple", "禅意": "temple", "禅": "temple",
}

SCENE_MARKER_RE = re.compile(r"【场景[:：]\s*([^】\n]{1,20})】")


@dataclass
class SceneSegment:
    """一个场景段：主题 + 时间窗 + 章节标题"""
    theme: str
    start: float = 0.0
    end: float = 0.0
    chapter_title: str = ""
    images: list = field(default_factory=list)


@dataclass
class ScenePlan:
    """整片场景规划"""
    segments: list
    duration: float = 0.0

    def images_with_durations(self) -> list:
        """展平为 [(图片路径, 该图时长), ...]"""
        plan = []
        for seg in self.segments:
            n = max(1, len(seg.images))
            d = (seg.end - seg.start) / n
            for img in seg.images:
                plan.append((img, d))
        return plan


def normalize_theme(raw: str) -> str:
    """把任意主题名/别名归一化为主题 ID，无效返回空串"""
    raw = raw.strip()
    if raw in THEME_ALIASES:
        return THEME_ALIASES[raw]
    # 直接是主题 ID？
    from scene_library import all_themes
    if raw in all_themes():
        return raw
    return ""


def detect_content_type_local(text: str) -> str:
    """内容类型检测（加权版）：统计各类关键词命中数，取命中最多者。
    修复首命中缺陷（如张居正传'汇报'命中职场但'皇帝/王朝/明朝'×5属历史）。"""
    try:
        from streaming_pipeline import CONTENT_VOICES
        best_type, best_count = "通用", 0
        for ctype, keywords, voice, desc in CONTENT_VOICES:
            cnt = sum(1 for kw in keywords if kw in text)
            if cnt > best_count:
                best_type, best_count = ctype, cnt
        return best_type
    except ImportError:
        # 兜底：简单关键词
        for kw in ("历史", "朝代", "皇帝", "王朝", "古代", "传记"):
            if kw in text:
                return "历史"
        return "通用"


def auto_theme(script_text: str) -> str:
    """整稿自动检测内容类型 → 主题"""
    ctype = detect_content_type_local(script_text)
    return CONTENT_THEME_MAP.get(ctype, "desert")


def parse_scene_markers(script_text: str) -> list:
    """解析【场景：XX】→ [(字符位置, 主题ID), ...]
    只合并位置极近（<50字符，同一段落内的重复标记）的连续同主题，
    不同章节的同主题标记保留各自位置（否则会吞掉中间内容，2026-08-13修复）。"""
    out = []
    for m in SCENE_MARKER_RE.finditer(script_text):
        theme = normalize_theme(m.group(1))
        if not theme:
            continue
        if out and out[-1][1] == theme and (m.start() - out[-1][0]) < 50:
            continue  # 同段内重复同主题标记 → 忽略
        out.append((m.start(), theme))
    return out


def extract_chapter_title(seg_text: str) -> str:
    """从段落文本提取章节标题（## 标题 或 首行）"""
    for line in seg_text.splitlines():
        line = line.strip()
        if line.startswith("##") or line.startswith("#"):
            t = re.sub(r"^#+\s*", "", line).strip()
            if t:
                return t
    return ""


def split_by_positions(script_text: str, marked: list) -> tuple:
    """按标记位置切文本 → (段文本列表, 段主题列表)"""
    seg_texts, seg_themes = [], []
    for i, (pos, theme) in enumerate(marked):
        end = marked[i + 1][0] if i + 1 < len(marked) else len(script_text)
        seg_texts.append(script_text[pos:end])
        seg_themes.append(theme)
    return seg_texts, seg_themes


def read_audio_chapters(audio_path: str) -> list:
    """读音频 ID3v2 章节（ffprobe），拿不到返回空"""
    if not audio_path:
        return []
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_chapters",
             "-of", "json", audio_path],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return []
        import json
        data = json.loads(r.stdout)
        chapters = []
        for ch in data.get("chapters", []):
            chapters.append({
                "start": float(ch.get("start_time", 0)),
                "end": float(ch.get("end_time", 0)),
                "title": ch.get("tags", {}).get("title", ""),
            })
        # ffprobe 读 MP3 ID3 CHAP 按字符串排序（"560"<"57"），必须按数字重排
        # （2026-08-14 实测：10分钟稿章节被排成 0→560→57→193...，导致场景时间轴负区间 → 合成失败）
        chapters.sort(key=lambda c: c["start"])
        return chapters
    except Exception:
        return []


def build_plan_from_markers(script_text: str, marked: list, audio_dur: float,
                            audio_path: str = "") -> ScenePlan:
    """按标记把全文切成多段：标记位置=新段起点，每段独立主题。
    段时长优先取音频章节标记，取不到按字数比例分配。"""
    seg_texts, seg_themes = split_by_positions(script_text, marked)
    if not seg_texts:
        return ScenePlan(segments=[SceneSegment(theme="desert", start=0,
                                                end=audio_dur)],
                         duration=audio_dur)
    # 时间轴：音频章节数与场景段数一致时用章节边界（精确对齐），
    # 否则按字数比例分配（修复：21章节 vs 6标记时最后一段吞掉全部时长）
    chapters = read_audio_chapters(audio_path)
    segs = []
    if len(chapters) == len(seg_texts):
        bounds = [c["start"] for c in chapters[:len(seg_texts)]] + [audio_dur]
        for i, theme in enumerate(seg_themes):
            title = chapters[i].get("title", "") or extract_chapter_title(seg_texts[i])
            segs.append(SceneSegment(theme=theme, start=bounds[i],
                                     end=bounds[i + 1], chapter_title=title))
    else:
        total_chars = sum(len(t) for t in seg_texts) or 1
        cursor = 0.0
        for i, txt in enumerate(seg_texts):
            dur = audio_dur * len(txt) / total_chars
            title = extract_chapter_title(txt) or f"第 {i + 1} 部分"
            segs.append(SceneSegment(theme=seg_themes[i], start=cursor,
                                     end=cursor + dur, chapter_title=title))
            cursor += dur
    return ScenePlan(segments=segs, duration=audio_dur)


def select_scenes(script_text: str, theme_arg: str, audio_dur: float,
                  audio_path: str = "") -> ScenePlan:
    """总入口：手动指定 > 【场景：XX】标记 > 自动检测 > 兜底"""
    if theme_arg and theme_arg != "auto":
        # ① 手动指定：整片单一主题
        t = normalize_theme(theme_arg) or theme_arg
        return ScenePlan(segments=[SceneSegment(theme=t, start=0.0,
                                                end=audio_dur)],
                         duration=audio_dur)
    marked = parse_scene_markers(script_text)
    if marked:
        # ② 显式标记
        return build_plan_from_markers(script_text, marked, audio_dur, audio_path)
    # ③ 自动检测
    theme = auto_theme(script_text)
    return ScenePlan(segments=[SceneSegment(theme=theme, start=0.0,
                                            end=audio_dur)],
                     duration=audio_dur)


if __name__ == "__main__":
    import sys
    text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace") if len(sys.argv) > 1 else ""
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 330.0
    plan = select_scenes(text, "auto", dur)
    for seg in plan.segments:
        print(f"  [{seg.start:.0f}s-{seg.end:.0f}s] {seg.theme} {seg.chapter_title}")
