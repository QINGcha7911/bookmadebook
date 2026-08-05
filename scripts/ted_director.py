#!/usr/bin/env python3
"""TED 导演层 — 注解解析与块级 TTS 配置

演讲稿内嵌表演标记，解析成块级 TTS 配置：
【停顿0.8】→ pause_after 0.8s
【放慢】→ rate -10%
【金句】→ 前停顿0.6 + rate -5% + volume +5%
【情绪：激动】→ rate +8% + volume +8% + pitch +5%
【BGM：起】/【BGM：止】→ bgm_event
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

# ============================================================
# 注解标记定义
# ============================================================
# 标记: 【名称】或【名称：参数】
ANNOTATION_PATTERN = re.compile(r'【([^】]+)】')

# 停顿标记: 【停顿0.8】或【停顿】或【停0.5】
PAUSE_PATTERN = re.compile(r'停顿([\d.]+)?|停([\d.]+)?')

# 情绪标记（pitch 用 Hz，edge-tts 不支持 %）
# 注意：幅度要克制！差异太大听感像"换人"，微调才有"情绪变化"
EMOTION_MAP = {
    '激动': {'rate': '+5%', 'volume': '+4%', 'pitch': '+8Hz'},
    '平静': {'rate': '+0%', 'volume': '+0%', 'pitch': '+0Hz'},
    '低沉': {'rate': '-5%', 'volume': '-3%', 'pitch': '-8Hz'},
    '温暖': {'rate': '-3%', 'volume': '+2%', 'pitch': '+4Hz'},
    '激昂': {'rate': '+6%', 'volume': '+5%', 'pitch': '+10Hz'},
    # 优化②：更多情绪维度（抑扬顿挫）
    '开心': {'rate': '+4%', 'volume': '+3%', 'pitch': '+6Hz'},   # 轻快上扬
    '悲伤': {'rate': '-6%', 'volume': '-4%', 'pitch': '-10Hz'},  # 缓慢低沉
    '紧张': {'rate': '+7%', 'volume': '+2%', 'pitch': '+3Hz'},   # 急促
    '温柔': {'rate': '-4%', 'volume': '-2%', 'pitch': '+2Hz'},   # 柔和
    '坚定': {'rate': '-2%', 'volume': '+6%', 'pitch': '+5Hz'},   # 有力
    '疑惑': {'rate': '+2%', 'volume': '+1%', 'pitch': '+12Hz'},  # 上扬疑问
    '神秘': {'rate': '-7%', 'volume': '-5%', 'pitch': '-12Hz'},  # 低沉缓慢
    '爆发': {'rate': '+9%', 'volume': '+7%', 'pitch': '+12Hz'},  # 强烈（少见，用于高潮）
    '轻声': {'rate': '-8%', 'volume': '-6%', 'pitch': '-4Hz'},   # 耳语/私语
}


@dataclass
class TTSBlock:
    """块级 TTS 配置"""
    text: str
    voice: str = "zh-CN-YunjianNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    pause_after: float = 0.0      # 段后停顿（秒）
    pause_before: float = 0.0     # 段前停顿（秒）
    bgm_event: Optional[str] = None  # "start"/"stop"/"swell"
    is_golden_line: bool = False  # 金句标记
    is_fast: bool = False         # 加速标记
    is_slow: bool = False         # 放慢标记


def parse_annotations(text: str, default_voice: str = "zh-CN-YunjianNeural") -> List[TTSBlock]:
    """解析带注解的演讲稿，返回块级 TTS 配置列表"""
    # 先清理 markdown：标题行(#开头)整行删除 + 其他符号清理，防止被朗读
    import re as _re
    text = _re.sub(r'^#{1,6}\s*.*$', '', text, flags=_re.MULTILINE)  # 标题行整行删
    text = text.replace('**', '').replace('*', '').replace('`', '')  # 粗体/斜体/代码
    text = _re.sub(r'^\s*[-*]\s+', '', text, flags=_re.MULTILINE)    # 列表符号
    text = _re.sub(r'^\s*>\s*', '', text, flags=_re.MULTILINE)       # 引用符号
    text = _re.sub(r'\|', ' ', text)                                  # 表格竖线
    blocks: List[TTSBlock] = []
    current = TTSBlock(text="", voice=default_voice)
    pending_pause = 0.0
    pending_bgm = None
    pending_emotion = {}

    pos = 0
    for m in ANNOTATION_PATTERN.finditer(text):
        # 注解前的文本
        pre = text[pos:m.start()]
        if pre.strip():
            if current.text:
                # 保存当前块，开新块
                blocks.append(current)
                current = TTSBlock(text="", voice=default_voice)
            current.text = pre.strip()
            if pending_pause:
                current.pause_after = pending_pause
                pending_pause = 0.0
            if pending_bgm:
                current.bgm_event = pending_bgm
                pending_bgm = None
            if pending_emotion:
                current.rate = pending_emotion.get('rate', '+0%')
                current.volume = pending_emotion.get('volume', '+0%')
                current.pitch = pending_emotion.get('pitch', '+0%')
                pending_emotion = {}

        # 解析注解内容
        tag = m.group(1)
        # 停顿
        pm = PAUSE_PATTERN.search(tag)
        if pm:
            val = pm.group(1) or pm.group(2) or "0.5"
            pending_pause = float(val)
            pos = m.end()
            continue
        # 情绪
        if '：' in tag or ':' in tag:
            name = tag.split('：')[-1].split(':')[-1].strip()
            if name in EMOTION_MAP:
                pending_emotion = EMOTION_MAP[name]
                pos = m.end()
                continue
        # BGM
        if 'BGM' in tag or 'bgm' in tag:
            if '起' in tag or 'start' in tag.lower():
                pending_bgm = "start"
            elif '止' in tag or '停' in tag:
                pending_bgm = "stop"
            elif 'swell' in tag.lower() or '涨' in tag:
                pending_bgm = "swell"
            pos = m.end()
            continue
        # 金句
        if '金句' in tag:
            if current.text:
                blocks.append(current)
                current = TTSBlock(text="", voice=default_voice)
            current.is_golden_line = True
            current.pause_before = 0.6
            current.rate = "-5%"
            current.volume = "+5%"
            pos = m.end()
            continue
        # 放慢
        if '放慢' in tag or '慢' in tag:
            current.is_slow = True
            current.rate = "-5%"
            pos = m.end()
            continue
        # 加速
        if '加速' in tag or '快' in tag:
            current.is_fast = True
            current.rate = "+5%"
            pos = m.end()
            continue
        # 其他标记忽略
        pos = m.end()

    # 剩余文本
    tail = text[pos:]
    if tail.strip():
        if current.text:
            blocks.append(current)
            current = TTSBlock(text="", voice=default_voice)
        current.text = tail.strip()
    if current.text:
        blocks.append(current)

    # 合并相邻无特殊属性的块
    merged = []
    for b in blocks:
        if b.text:
            merged.append(b)
    return merged


def extract_ted_chapters(blocks: List[TTSBlock]) -> List[dict]:
    """从块列表提取 TED 结构章节标记"""
    chapters = []
    start = 0.0
    keywords = ['开场', '观点', '金句', '行动', '结尾']
    for i, b in enumerate(blocks):
        for kw in keywords:
            if kw in b.text[:50]:
                chapters.append({"title": f"{kw}·{i+1}", "start": start})
                break
        start += 0.5  # 估算
    if not chapters:
        chapters = [{"title": "开场", "start": 0.0}]
    return chapters


if __name__ == "__main__":
    # 自测
    test = """【停顿0.5】大家好，今天讲一个关于坚持的故事。

【放慢】他等了八十四天，一条鱼都没等到。

【金句】人可以被打败，但不能被毁灭。

【情绪：激动】他再次出海，这一次，他相信会不一样！

【BGM：起】故事从这里开始。"""
    blocks = parse_annotations(test)
    print(f"解析出 {len(blocks)} 个块:")
    for i, b in enumerate(blocks):
        print(f"  [{i}] rate={b.rate} vol={b.volume} pause_b={b.pause_before} pause_a={b.pause_after} bgm={b.bgm_event} 金句={b.is_golden_line}")
        print(f"      {b.text[:40]}...")
