#!/usr/bin/env python3
"""停顿调度器 v2（语速治理 A 项 · 2026-09-25）

诊断（5 本实测，逐词时间戳）：
  真停顿(>0.25s)占比 11.2% ~ 30.4%，跨书极差 19 个点 ✗，书内摆动也大
  根因：**流程没有停顿策略**，停顿完全由 TTS 随"空行密度"决定
  （条数 141~385 条，与稿子格式强相关）

目标：停顿占比 **14~16%**、跨书极差 **≤2 个点**、长停顿只出现在
      金句/章节处（写稿规范已有「金句独占行」）

做法：**预算分配**
  1) 按句切块（块长 ≤ max_chunk，保持韵律自然，不过碎）
  2) 预算 = 目标占比反推的总停顿秒数
  3) 按边界级别加权分配（逗<句<段<章），并裁剪到 [0.12, 1.10]s
  4) 与写稿规范对齐：金句/章节边界自动拿更大权重

用法:
    from pause_table import plan_pauses
    plan = plan_pauses(script_text)          # [{"text","pause_before","kind"}]
    stats = predict(plan)                    # 块数/字数/停顿占比/总时长
"""
import re
import os

# 边界级别 → 权重（越大 = 分到越多停顿）
WEIGHT = {"comma": 1.0, "semi": 1.5, "sent": 2.4, "para": 3.6, "chap": 5.0, "golden": 3.0}
PAUSE_MIN, PAUSE_MAX = 0.12, 1.20
TARGET_RATIO = 0.13     # 目标停顿占比（对标有声书 12~15%；现状 11%~30% 乱跳 ✗）
CPS_SPEECH = 5.4        # 发音速率目标（字/秒）
MAX_CHUNK = 34          # 单块上限（字）：停顿要 ~15% ⇒ 必须每 ~15 字一个停顿点
MIN_CHUNK = 0           # 不合并（保证停顿点密度）

_PUNCT_CLASS = {"，": "comma", "、": "comma", "：": "semi", "；": "semi",
                "。": "sent", "！": "sent", "？": "sent", "…": "sent"}
_CHAP_RE = re.compile(r"^\s*(第[一二三四五六七八九十百千0-9]+[章节回])")
_GOLD_RE = re.compile(r"^[「『\"“]|[」』\"”]$")


def _split_sents(text: str):
    """切成小句：先按句末标点切，长句再按逗/顿/分/冒切（块≈15~35字）。
    这样停顿点足够密（停顿预算才花得出去），且每块都是完整小句（韵律自然）。"""
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        if not para:
            continue
        is_chap = bool(_CHAP_RE.match(para))
        is_gold = bool(_GOLD_RE.search(para)) and len(para) <= 40
        for s in re.findall(r"[^。！？…]*[。！？…]|[^。！？…]+$", para):
            s = s.strip()
            if not s:
                continue
            # 长句再切（保留标点归属）
            pieces = [s]
            if len(s) > 34:
                pieces = [x for x in re.split(r"(?<=[，、：；])", s) if x.strip()]
                # 合并过短片段
                merged, buf = [], ""
                for x in pieces:
                    if len(buf) + len(x) <= 34:
                        buf += x
                    else:
                        if buf: merged.append(buf)
                        buf = x
                if buf: merged.append(buf)
                pieces = merged or [s]
            for i, p in enumerate(pieces):
                tail = p[-1] if p and p[-1] in _PUNCT_CLASS else "。"
                lvl = _PUNCT_CLASS.get(tail, "sent")
                if i == len(pieces) - 1 and s[-1] in "。！？…":
                    lvl = "sent"
                out.append({"s": p, "lvl": lvl})
        # 段落级：仅当该段含 ≥2 个块时才提升（讲书稿是"一句一行"，逐行当段会让分级失效 ✗）
        if out:
            if is_chap:
                out[-1]["lvl"] = "chap"
            elif is_gold:
                out[-1]["lvl"] = "golden"
            elif len([1 for x in out if x["lvl"] == "sent"]) > 1 and len(out) > 1:
                out[-1]["lvl"] = "para"
    return out


def plan_pauses(text: str, target_ratio: float = TARGET_RATIO,
                cps: float = CPS_SPEECH, max_chunk: int = MAX_CHUNK):
    """返回 [{"text","pause_before","kind"}]，停顿由预算分配、级别加权。"""
    sents = _split_sents(text)
    if not sents:
        return []
    # ---- 1) 组块 ----
    chunks, buf, blen, blvl = [], [], 0, "sent"
    for i, it in enumerate(sents):
        if buf and blen + len(it["s"]) > max_chunk and blen >= MIN_CHUNK:
            chunks.append({"text": "".join(buf), "lvl": blvl, "chars": blen})
            blvl = it["lvl"]
            buf, blen = [], 0
        elif not buf:
            blvl = it["lvl"]
        buf.append(it["s"])
        blen += len(it["s"])
    if buf:
        chunks.append({"text": "".join(buf), "lvl": blvl, "chars": blen})

    # ---- 2) 预算 ----
    total_chars = sum(c["chars"] for c in chunks)
    speech = total_chars / cps
    budget = speech * target_ratio / (1 - target_ratio)          # 总停顿秒
    wsum = sum(WEIGHT.get(c["lvl"], 2.0) for c in chunks[1:]) or 1.0
    for c in chunks[1:]:
        raw = budget * WEIGHT.get(c["lvl"], 2.0) / wsum
        c["pause_before"] = round(min(max(raw, PAUSE_MIN), PAUSE_MAX), 3)
    chunks[0]["pause_before"] = 0.0
    return chunks


def predict(plan, cps: float = CPS_SPEECH):
    chars = sum(len(p["text"]) for p in plan)
    pauses = sum(p.get("pause_before", 0) for p in plan)
    speech = chars / cps
    total = speech + pauses
    return {"块数": len(plan), "字数": chars, "发音秒": round(speech, 1),
            "停顿秒": round(pauses, 1), "总时长": round(total, 1),
            "停顿占比": round(pauses / total, 3) if total else 0,
            "总时长(分)": round(total / 60, 2)}


def strip_script(text: str) -> str:
    """去标题行与【】标签（体检用）"""
    t = re.sub(r"^#{1,6}\s*.*$", "", text, flags=re.MULTILINE)
    return re.sub(r"【[^】]{1,80}】", "", t)


if __name__ == "__main__":
    import sys, json
    t = strip_script(open(sys.argv[1], encoding="utf-8", errors="replace").read())
    plan = plan_pauses(t)
    print(json.dumps(predict(plan), ensure_ascii=False, indent=1))
    import collections
    print("\n停顿分布:", dict(sorted(collections.Counter(round(p["pause_before"], 2) for p in plan).items())))
    print("级别分布:", dict(collections.Counter(p["lvl"] for p in plan)))
    for x in plan[:5]:
        print(f'  [{x["lvl"]:6s} 停{x["pause_before"]:.2f}s] {x["text"][:44]}')


# ============================================================
# TED 导演层整合（2026-09-25）：把导演层块再按小句切开
#   保留父块的 rate/volume/pitch/bgm/金句 属性 ✓
#   停顿由预算分配 ✓（父块最后一个子块沿用父块 pause_after）
# ============================================================
def expand_ted_blocks(ted_blocks, target_ratio: float = TARGET_RATIO):
    """输入 ted_director.TTSBlock 列表，返回再切细后的新列表（类型不变）"""
    out = []
    for b in ted_blocks:
        txt = (b.text or "").strip()
        if not txt:
            out.append(b)
            continue
        subs = plan_pauses(txt, target_ratio=target_ratio)
        if len(subs) <= 1:
            out.append(b)
            continue
        for j, s in enumerate(subs):
            nb = type(b)(text=s["text"], voice=b.voice, rate=b.rate, volume=b.volume,
                         pitch=b.pitch, bgm_event=b.bgm_event if j == 0 else None,
                         is_golden_line=b.is_golden_line, is_fast=getattr(b, "is_fast", False),
                         is_slow=getattr(b, "is_slow", False))
            nb.pause_before = s["pause_before"]
            # 停顿只在 pause_before 上（预算已含全部分配）；父块的 pause_after 归零，
            # 避免与分配停顿重复叠加（保持占比精确 = 目标 13%）
            nb.pause_after = 0.0
            out.append(nb)
    return out


# ============================================================
# 试点开关（2026-09-25）：按书名生效
#   生产由 005 独立会话执行 ⇒ 环境变量传不过去，改用文件开关
#   文件: ~/.hermes/cache/bookmadebook/pause_pilot.txt（一行一个书名）
#   命中 ⇒ 启用停顿调度；否则行为与改动前完全一致
# ============================================================
PILOT_FILE = os.path.join(os.path.expanduser("~"), ".hermes", "cache", "bookmadebook", "pause_pilot.txt")


def _norm_title(t: str) -> str:
    return re.sub(r"[《》\s·]", "", t or "")


def pilot_enabled(book_title: str = "", path: str = None) -> bool:
    """该书名是否在试点名单里（或全局开关已开）"""
    if os.environ.get("LISTEN_PAUSE_TABLE", "0") == "1":
        return True
    try:
        p = path or PILOT_FILE
        if not os.path.exists(p):
            return False
        want = _norm_title(book_title)
        if not want:
            return False
        for line in open(p, encoding="utf-8", errors="replace"):
            line = line.split("#")[0].strip()
            if not line:
                continue
            name = _norm_title(line)
            # 子串匹配：生产侧可能传 "《张居正大传》10分钟视频" 这类带头尾的标题
            if name and (name in want or want in name):
                return True
    except Exception:
        return False
    return False
