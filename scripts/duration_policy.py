#!/usr/bin/env python3
"""时长策略（2026-09-25 立）—— 时长 = 口播字数 ÷ 目标语速

原则（用户已批准「按书本长度调整」）：
  ① 时长由**稿量**决定，不先定 10 分钟再塞内容
  ② 目标语速锁 4.4 字/秒（4.2–4.7）
  ③ 禁 atempo 硬压补稿量（±3% 以内仅用于微调）
  ④ 单集 6–16 分钟；超 16 分钟 ⇒ 拆集（拆集为第二阶段，需生产流程支持）

用法：
  python3 scripts/duration_policy.py 张居正大传
  python3 scripts/duration_policy.py --list
  from duration_policy import policy_for; p = policy_for("张居正大传")
"""
import os
import sys

CPS = 4.4                      # 目标综合语速（字/秒）
HERE = os.path.dirname(os.path.abspath(__file__))
LENGTHS = os.path.join(HERE, "..", "book_lengths.tsv")

# 分档表：字数区间 → (最短分钟, 最长分钟, 最少口播字, 最多口播字, 建议集数)
TIERS = [
    (0,      8,   6,  8,   1600, 2100, "短篇/散文"),
    (8,     20,   9, 12,   2400, 3200, "中篇"),
    (20,    40,  13, 16,   3400, 4200, "长篇"),
    (40,    80,  12, 14,   3200, 3700, "超长篇"),
    (80, 10**9,  12, 14,   3200, 3700, "巨著"),
]


def load_lengths(path: str = None) -> dict:
    """读 book_lengths.tsv：书名 <TAB> 万字"""
    out = {}
    p = path or LENGTHS
    if not os.path.exists(p):
        return out
    for line in open(p, encoding="utf-8", errors="replace"):
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = [x.strip() for x in line.replace("\t", "|").split("|")]
        if len(parts) < 2:
            continue
        try:
            out[parts[0]] = float(parts[1])
        except ValueError:
            continue
    return out


def policy_for(book: str, wan: float = None, lengths: dict = None):
    """返回该书的时长策略 dict；未登记体量时给中位数默认并标注 unknown=True"""
    lengths = lengths if lengths is not None else load_lengths()
    known = True
    if wan is None:
        wan = None
        for k, v in lengths.items():
            if k and (k in book or book in k):
                wan = v
                break
        if wan is None:
            wan = 15.0          # 未登记 ⇒ 按中篇默认（宁短勿赶）
            known = False
    for lo, hi, mn, mx, cmin, cmax, label in TIERS:
        if lo <= wan < hi:
            mid = round((mn + mx) / 2)
            return {
                "书名": book, "体量万字": wan, "档位": label,
                "建议分钟": f"{mn}-{mx}", "目标分钟": mid,
                "口播字数": f"{cmin}-{cmax}",
                "目标字数": int(round(mid * 60 * CPS)),
                "集数": 1 if hi <= 40 else "2-3（第二阶段）",
                "体量已登记": known,
            }
    return {}


def main():
    a = sys.argv[1:]
    if not a or a[0] == "--list":
        ls = load_lengths()
        print(f"已登记 {len(ls)} 本：")
        for k, v in sorted(ls.items(), key=lambda x: -x[1]):
            print(f"  {k:22s} {v:>6.1f} 万字")
        return
    p = policy_for(a[0])
    if not p:
        print("未匹配到档位")
        return
    print(f"《{p['书名']}》")
    print(f"  体量: {p['体量万字']} 万字{'（未登记，按中篇默认 ⇒ 建议补登 book_lengths.tsv）' if not p['体量已登记'] else ''}")
    print(f"  档位: {p['档位']}")
    print(f"  建议时长: {p['建议分钟']} 分钟（目标 {p['目标分钟']} 分钟）")
    print(f"  口播字数: {p['口播字数']} 字（目标 {p['目标字数']} 字）")
    print(f"  集数: {p['集数']}")
    print(f"  语速: {CPS} 字/秒 ⇒ 禁 atempo 硬压（±3% 内仅微调）")


if __name__ == "__main__":
    main()
