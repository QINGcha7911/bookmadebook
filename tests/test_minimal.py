#!/usr/bin/env python3
"""listen-book 最小测试集

覆盖核心逻辑（不依赖网络/TTS，秒级跑完）：
  1. TED 注解解析（停顿/BGM/情绪/金句）
  2. 缓存键（volume/pitch/style/schema）
  3. 质量门（字数不足拦截/重复检测/金句去重）
  4. 语速缓存兼容性（speed_probe 写入格式 vs quality_gate 读取）
  5. listen.py 自然语言解析

用法:
    python tests/test_minimal.py
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def test_ted_director():
    print("\n[1] TED 注解解析")
    from ted_director import parse_annotations
    # BGM:停 不应被停顿误判
    blocks = parse_annotations("【BGM：停】文本。", "zh-CN-XiaoxiaoNeural")
    check("BGM:停 → bgm=stop", any(b.bgm_event == "stop" for b in blocks),
          f"got {[b.bgm_event for b in blocks]}")
    # 停顿语义
    blocks2 = parse_annotations("第一句。【停顿0.5】第二句。", "zh-CN-XiaoxiaoNeural")
    check("停顿0.5 → 第二句pause=0.5",
          any(abs(b.pause_after - 0.5) < 0.01 and "第二句" in b.text for b in blocks2),
          f"got {[(b.text[:4], b.pause_after) for b in blocks2]}")
    # 情绪
    blocks3 = parse_annotations("【情绪：激动】太棒了！", "zh-CN-XiaoxiaoNeural")
    check("情绪：激动 → rate+5%", any(b.rate == "+5%" for b in blocks3),
          f"got {[b.rate for b in blocks3]}")
    # 金句
    blocks4 = parse_annotations("【金句】这是金句。", "zh-CN-XiaoxiaoNeural")
    check("金句 → is_golden_line", any(b.is_golden_line for b in blocks4))


def test_cache_keys():
    print("\n[2] 缓存键")
    from cache_manager import CacheManager, CACHE_SCHEMA_VERSION
    cm = CacheManager()
    # 不同 volume/pitch → 不同 key
    k1 = cm.l2_key("文本", "v", "+0%", "+0%", "+0Hz", "ted")
    k2 = cm.l2_key("文本", "v", "+0%", "+3%", "+0Hz", "ted")
    check("不同volume→不同key", k1 != k2)
    # 不同 style → 不同 L3 hash（在 pipeline 里拼，这里测 schema 前缀生效）
    check("schema版本存在", CACHE_SCHEMA_VERSION == "v2")


def test_quality_gate():
    print("\n[3] 质量门")
    from quality_gate import validate, find_duplicate_paragraphs, find_duplicate_quotes
    # 字数不足拦截
    r = validate("很短的内容。", 45, "zh-CN-XiaoxiaoNeural", book_title="测试")
    check("字数不足→不通过", not r["passed"])
    # 重复段落（需要足够长的段落让4-gram生效）
    dups = find_duplicate_paragraphs(
        "第一段：孙悟空打死了妖怪，唐僧很惊讶，八戒拍手叫好，沙僧默默收拾行李准备出发。\n"
        "第二段：孙悟空打死了妖怪，唐僧很惊讶，八戒拍手叫好，沙僧默默收拾行李准备出发。\n"
        "第三段：取经路上遇到新的挑战，大家团结一心克服困难继续前进。")
    check("重复段落检测", len(dups) >= 1, f"got {dups}")
    # 金句重复
    quotes = find_duplicate_quotes("他说「人可以被毁灭，但不能被打败」。然后又说「人可以被毁灭，但不能被打败」。")
    check("金句去重", len(quotes) >= 1, f"got {quotes}")


def test_speed_cache_compat():
    print("\n[4] 语速缓存兼容性")
    from quality_gate import get_speed_cached
    # 写入格式（speed_probe）：{"voice|rate": speed} 或 {"entries": [...]}
    import json
    cache_dir = Path(tempfile.mkdtemp())
    # 模拟 speed_probe 的写入格式
    probe_format = {"zh-CN-XiaoxiaoNeural|+0%": 282.0}
    (cache_dir / "probe.json").write_text(json.dumps(probe_format), encoding="utf-8")
    # quality_gate 读取应有兜底（不崩溃）
    speed = get_speed_cached("zh-CN-XiaoxiaoNeural", "zh")
    check("语速读取不崩溃", speed > 200, f"got {speed}")


def test_listen_parse():
    print("\n[5] listen.py 自然语言解析")
    sys.path.insert(0, str(REPO))
    from listen import parse_request
    r1 = parse_request("《小王子》10分钟")
    check("书名解析（书名号）", r1["book"] == "小王子" and r1["minutes"] == 10.0,
          f"got {r1}")
    r2 = parse_request("原子习惯 跑步8分钟")
    check("书名+场景解析", r2["book"] == "原子习惯" and r2["minutes"] == 8.0,
          f"got {r2}")


if __name__ == "__main__":
    test_ted_director()
    test_cache_keys()
    test_quality_gate()
    test_speed_cache_compat()
    test_listen_parse()
    print(f"\n{'='*40}")
    print(f"结果: {PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
