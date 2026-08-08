"""BGM 智能选择器：根据内容主题/情绪 + 用户配置选择背景音乐

选择优先级：
1. 用户配置覆盖（user_overrides[user_key]）
2. 内容主题/情绪匹配（by_topic 关键词分类）
3. 默认曲目（default）

用法：
    from bgm_selector import select_bgm
    bgm_path, topic = select_bgm(full_text, user_key="alice")
"""
import json
import os
import re
from pathlib import Path

# 主题 → 关键词（内容分类词库）
TOPIC_KEYWORDS = {
    "教育/学习": ["读书", "学习", "知识", "教育", "成长", "阅读", "书本", "课程", "思考", "智慧", "book", "study", "learn", "read"],
    "情感/励志": ["坚持", "梦想", "行动", "希望", "勇气", "努力", "奋斗", "相信", "未来", "自己", "dream", "hope", "courage", "believe"],
    "历史/史诗": ["历史", "帝国", "战争", "王朝", "征服", "古代", "文明", "皇帝", "将军", "蒙古", "罗马", "埃及", "战场", "史诗", "history", "empire", "war", "conquer", "ancient"],
    "科幻/悬疑": ["科幻", "宇宙", "三体", "外星", "星际", "机器人", "未来世界", "悬疑", "侦探", "推理", "谜团", "神秘", "非凡", "克苏鲁", "蒸汽朋克", "邪神", "旧日", "低语", "超凡", "魔药", "序列", "science fiction", "sci-fi", "mystery", "alien", "space", "horror"],
    "科技": ["人工智能", "科技", "技术", "智能", "数据", "代码", "AI", "算法", "编程", "tech", "AI", "code", "algorithm"],
    "冥想/放松": ["冥想", "放松", "平静", "内心", "呼吸", "宁静", "治愈", "安详", "冥想", "calm", "meditat", "peace", "relax", "breath"],
    "商业": ["商业", "创业", "市场", "产品", "用户", "企业", "管理", "经营", "business", "market", "startup", "product"],
}

# 默认配置（与 bgm_config.json 一致，作为兜底）
DEFAULT_CONFIG = {
    "default": "bgm_ambient.mp3",
    "by_topic": {
        "教育/学习": ["bgm_piano_open.mp3", "bgm_piano_close.mp3"],
        "情感/励志": ["bgm_piano_open.mp3", "bgm_piano_close.mp3"],
        "历史/史诗": ["bgm_ambient.mp3", "bgm_piano_open.mp3"],
        "科技": ["bgm_ambient.mp3"],
        "冥想/放松": ["bgm_piano_close.mp3"],
        "商业": ["bgm_ambient.mp3"],
    },
    "user_overrides": {},
}


def _find_assets_dir() -> Path:
    """定位 assets 目录（技能目录或仓库目录）"""
    # 1. 本文件上级的 assets（scripts/../assets）
    p = Path(__file__).resolve().parent.parent / "assets"
    if p.exists():
        return p
    # 2. ~/bookmadebook/assets
    p = Path.home() / "bookmadebook" / "assets"
    if p.exists():
        return p
    # 3. 仓库目录
    for cand in [Path(r"D:\AI软件\GitHub\bookmadebook\assets"),
                 Path(__file__).parent.parent / "assets"]:
        if cand.exists():
            return cand
    return Path(__file__).resolve().parent.parent / "assets"


def load_config() -> dict:
    """加载 bgm_config.json（不存在则用默认配置）"""
    assets = _find_assets_dir()
    cfg_path = assets / "bgm_config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_CONFIG


def detect_topic(text: str) -> str:
    """检测文本主题/情绪（关键词命中计数最高者）"""
    if not text:
        return ""
    scores = {}
    for topic, kws in TOPIC_KEYWORDS.items():
        cnt = 0
        for kw in kws:
            cnt += len(re.findall(kw, text, re.IGNORECASE))
        if cnt > 0:
            scores[topic] = cnt
    if not scores:
        return ""
    # 取命中数最高
    return max(scores, key=scores.get)


def select_bgm(text: str, user_key: str = None, config: dict = None) -> tuple:
    """返回 (bgm_path, topic)
    - text: 完整文本（用于主题检测）
    - user_key: 用户标识（用于用户配置覆盖）
    - config: 可选配置（默认从 bgm_config.json 加载）
    - 返回 (None, topic) 表示该主题不需要 BGM（如科幻/悬疑，用户偏好纯人声）
    """
    cfg = config or load_config()
    assets = _find_assets_dir()

    topic = detect_topic(text)
    bgm_name = cfg.get("default", "bgm_ambient.mp3")

    # 0. 无BGM主题（用户偏好：科幻/悬疑纯人声更沉浸，2026-08-07确认）
    NO_BGM_TOPICS = {"科幻/悬疑"}
    if topic in NO_BGM_TOPICS:
        return None, topic

    # 1. 用户配置覆盖（优先级最高）
    if user_key:
        user_cfg = cfg.get("user_overrides", {}).get(user_key)
        if user_cfg:
            # 用户主题映射
            if topic and topic in user_cfg.get("by_topic", {}):
                bgm_name = user_cfg["by_topic"][topic][0]
            else:
                bgm_name = user_cfg.get("default", bgm_name)

    # 2. 内容主题匹配（无用户覆盖或用户未覆盖该主题时）
    elif topic and topic in cfg.get("by_topic", {}):
        bgm_name = cfg["by_topic"][topic][0]

    # 3. 兜底：文件不存在则用默认
    bgm_path = assets / bgm_name
    if not bgm_path.exists():
        alt = assets / cfg.get("default", "bgm_ambient.mp3")
        if alt.exists():
            bgm_path = alt
            bgm_name = alt.name

    return str(bgm_path), topic


if __name__ == "__main__":
    # 自测
    tests = {
        "教育": "今天我们来聊聊读书和学习的方法，如何更高效地阅读一本书，把知识变成自己的智慧。",
        "励志": "不要等准备好了才开始，先开始再变好。坚持你的梦想，相信未来的自己。",
        "科技": "人工智能和数据技术正在改变我们的世界，代码和算法驱动着新的生产力。",
        "冥想": "深呼吸，放松身心，感受内心的平静与宁静，享受这一刻的安宁。",
        "无主题": "今天天气不错，我们去公园散步吧。",
    }
    for label, t in tests.items():
        bgm, topic = select_bgm(t)
        print(f"[{label}] 主题={topic or '无'} → BGM={bgm.split(chr(92))[-1].split('/')[-1]}")

    print("\n--- 用户配置测试（user=demo）---")
    for label, t in list(tests.items())[:3]:
        bgm, topic = select_bgm(t, user_key="demo")
        print(f"[{label}] 主题={topic or '无'} → BGM={bgm.split(chr(92))[-1].split('/')[-1]}")
