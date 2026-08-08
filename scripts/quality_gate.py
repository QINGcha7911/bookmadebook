#!/usr/bin/env python3
"""bookmadebook Harness — 内容质量门 (quality gate)

在 TTS 生成前对讲书稿做强制质量校验，不通过则停止（诚实告知），
杜绝注水/重复/标题残留。这是 harness 控制循环的核心环节之一。

用法:
    python quality_gate.py --text 讲书稿.txt --target-minutes 45 --voice zh-CN-XiaoxiaoNeural
    python quality_gate.py --text 讲书稿.txt --target-minutes 45 --book-title "活着" --lang zh

退出码: 0=通过, 1=不通过（错误报告打印到 stderr）
"""
import argparse
import hashlib
import re
import sys
from collections import Counter

# 现代版权书黑名单（禁止全文朗读的标志——只做精读）
MODERN_BOOKS = {
    "活着", "太白金星有点烦", "长安的荔枝", "强风吹拂", "三体",
    "人类简史", "明朝那些事儿", "围城", "东京爱情故事",
}


def strip_markdown(text: str) -> str:
    """去除 markdown 标题行与符号，返回纯文本。"""
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        if re.match(r'^#{1,6}\s', s):  # 标题行整行删除
            continue
        if s.startswith("|") and s.endswith("|"):  # 表格行删除
            continue
        s = re.sub(r'[#*`>]', '', s)
        lines.append(s)
    return "\n".join(lines)


def effective_chars(text: str) -> int:
    """有效字数（去空白/注解/标点后按语言计）。"""
    clean = strip_markdown(text)
    clean = re.sub(r'【[^】]*】', '', clean)  # 去注解
    clean = re.sub(r'[，。！？、；：""''（）\\s\\d]', '', clean)
    return len(clean)


def detect_language(text: str) -> str:
    zh = len(re.findall(r'[\u4e00-\u9fff]', text))
    ja = len(re.findall(r'[\u3040-\u30ff]', text))
    en = len(re.findall(r'[a-zA-Z]', text))
    if ja > zh and ja > en:
        return "ja"
    if en > zh:
        return "en"
    return "zh"


def get_speed_cached(voice: str, lang: str, style: str = "normal") -> float:
    """从 speed_cache.json 读实测语速，缺省按语言估算。

    兼容两种缓存格式（speed_probe 的历史格式 vs entries 列表格式）：
    - 扁平: {"zh-CN-XiaoxiaoNeural|+0%": 282.0}
    - 列表: {"entries": [{"voice": ..., "rate": ..., "chars_per_min": ...}]}

    style="ted" 时乘 0.85 系数——TED 模式的情绪标注（rate-3%/放慢-5%）
    和停顿会让实际语速比测速慢约 15%（实测 282→约240字/分）。
    """
    import json, os
    cache_path = os.path.expanduser("~/.hermes/cache/bookmadebook/speed_cache.json")
    speed = {"zh": 282.0, "ja": 273.0, "en": 200.0}.get(lang, 260.0)
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        if isinstance(cache, dict):
            # 格式1: 扁平 {"voice|rate": speed}
            flat_key = f"{voice}|+0%"
            if flat_key in cache:
                speed = float(cache[flat_key])
            # 格式2: {"entries": [...]}
            for entry in cache.get("entries", []):
                if entry.get("voice") == voice and entry.get("rate") == "+0%":
                    speed = float(entry["chars_per_min"])
                    break
    except Exception:
        pass
    if style == "ted":
        speed *= 0.85
    return speed


def find_duplicate_paragraphs(text: str, threshold: float = 0.75) -> list:
    """检测重复段落：n-gram 相似度超过阈值的段落对。"""
    clean = strip_markdown(text)
    paras = [p.strip() for p in clean.split("\n") if len(p.strip()) > 20]
    results = []
    for i in range(len(paras)):
        for j in range(i + 1, len(paras)):
            a, b = paras[i], paras[j]
            if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.3:
                continue
            # 简化相似度：公共子串比例
            shorter = min(len(a), len(b))
            if shorter < 30:
                continue
            # 用 4-gram 集合重叠度
            ga = set(a[k:k+4] for k in range(len(a) - 3))
            gb = set(b[k:k+4] for k in range(len(b) - 3))
            if not ga or not gb:
                continue
            overlap = len(ga & gb) / min(len(ga), len(gb))
            if overlap > threshold:
                results.append((i + 1, j + 1, round(overlap, 2)))
    return results[:5]


def find_duplicate_quotes(text: str) -> list:
    """检测金句重复：同一句引号内文字出现多次。"""
    # 兼容中文「」『』与英文引号
    quotes = re.findall(r'[「『""]([^「『""」』]{5,80})[」』""]', text)
    counter = Counter(quotes)
    return [(q, n) for q, n in counter.items() if n > 1]


def find_markdown_leak(text: str) -> list:
    """检测 markdown 残留。

    注意：行首 # 标题是讲书稿的正常结构（TTS 前由 ted_director 清理），
    不算残留。真正的残留是：
    - 正文行内夹带的 # 号（会被 TTS 读成"井号"）
    - 符号簇（** ` > 等）
    """
    leaks = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s:
            continue
        # 行首标题（正常结构，跳过）
        if re.match(r'^#{1,6}\s', s):
            continue
        # 正文行内夹带 #（残留）
        if '#' in s:
            leaks.append((i, "行内井号", s[:40]))
        # 符号簇
        elif re.search(r'\*{2,}|`{2,}|>{1,}\s', s):
            leaks.append((i, "符号簇", s[:40]))
    return leaks[:5]


def check_copyright(text: str, book_title: str) -> list:
    """版权检查：现代版权书不允许全文朗读特征（无分段主旨的长文朗读）。"""
    issues = []
    if book_title and book_title in MODERN_BOOKS:
        # 现代书：检测是否有解读特征（标题/分段），纯全文朗读则警告
        has_hooks = bool(re.search(r'^#|^##|^【', text, re.MULTILINE))
        if not has_hooks and len(text) > 3000:
            issues.append("现代版权书疑似全文朗读（无分段/解读特征），请确认是精读而非朗读全文")
    return issues


def validate(text: str, target_minutes: float, voice: str, book_title: str = None,
             lang: str = None, style: str = "normal") -> dict:
    """执行全部质量校验，返回报告。"""
    report = {"passed": True, "errors": [], "warnings": [], "stats": {}}

    # 1. 语言
    if not lang:
        lang = detect_language(text)
    report["stats"]["lang"] = lang

    # 2. 字数/时长校验
    chars = effective_chars(text)
    speed = get_speed_cached(voice, lang, style)
    est_minutes = chars / speed
    report["stats"]["chars"] = chars
    report["stats"]["speed"] = speed
    report["stats"]["est_minutes"] = round(est_minutes, 1)

    if target_minutes and est_minutes < target_minutes * 0.9:
        report["passed"] = False
        report["errors"].append(
            f"内容量不足：当前约{est_minutes:.0f}分钟，距目标{target_minutes:.0f}分钟"
            f"还差{int(target_minutes * speed - chars)}字。"
            f"请①补充更多书中真实情节 ②缩短目标时长到约{est_minutes:.0f}分钟 ③换书。"
            f"禁止用重复内容/空话凑时长。"
        )

    # 3. 重复段落检测
    dup_paras = find_duplicate_paragraphs(text)
    if dup_paras:
        report["passed"] = False
        report["errors"].append(
            f"检测到{len(dup_paras)}处重复段落（相似度>75%）：" +
            "; ".join(f"第{p[0]}段↔第{p[1]}段({p[2]})" for p in dup_paras) +
            "。零重复原则：同一情节只讲一次，请删除重复内容。"
        )

    # 4. 金句重复
    dup_quotes = find_duplicate_quotes(text)
    if dup_quotes:
        report["passed"] = False
        report["errors"].append(
            f"检测到金句重复：{'、'.join(f'「{q}」×{n}' for q, n in dup_quotes[:3])}" +
            "。金句只出现一次，请去重。"
        )

    # 5. markdown 残留
    leaks = find_markdown_leak(text)
    if leaks:
        report["warnings"].append(
            f"检测到{len(leaks)}处 markdown 残留（将导致TTS朗读符号）：" +
            "; ".join(f"第{l[0]}行{l[1]}" for l in leaks) + "。建议清理。"
        )

    # 6. 版权
    copyright_issues = check_copyright(text, book_title)
    if copyright_issues:
        report["warnings"].extend(copyright_issues)

    return report


def main():
    ap = argparse.ArgumentParser(description="bookmadebook 内容质量门")
    ap.add_argument("--text", required=True, help="讲书稿文件路径")
    ap.add_argument("--target-minutes", type=float, help="目标时长（分钟）")
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural", help="TTS声音")
    ap.add_argument("--book-title", help="书名（用于版权检查）")
    ap.add_argument("--lang", choices=["zh", "en", "ja"], help="语言（自动检测）")
    ap.add_argument("--style", default="normal", choices=["normal", "ted"],
                    help="风格（ted=TED导演层，语速×0.85校准）")
    args = ap.parse_args()

    with open(args.text, encoding="utf-8") as f:
        text = f.read()

    report = validate(text, args.target_minutes, args.voice,
                      args.book_title, args.lang, args.style)

    print(f"📊 质量门报告:")
    print(f"   语言: {report['stats']['lang']} | 字数: {report['stats']['chars']} | "
          f"语速: {report['stats']['speed']}字/分 | 预估: {report['stats']['est_minutes']}分钟")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ⚠️ {w}")
    if report["errors"]:
        for e in report["errors"]:
            print(f"  ❌ {e}")
        print(f"\n📢 内容质量门不通过（{len(report['errors'])}项错误）——停止生成，请修正后重试。")
        sys.exit(1)
    print("  ✅ 全部校验通过，可以生成。")
    sys.exit(0)


if __name__ == "__main__":
    main()
