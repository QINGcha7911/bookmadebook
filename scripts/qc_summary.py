#!/usr/bin/env python3
"""汇总各门禁报告：分目录可疑比例"""
import json, sys
from pathlib import Path
from collections import defaultdict

root = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/scenes/book_长日将尽")

for rep_file in sorted(root.glob("_qc_*report*.json")) + sorted(root.glob("_qc_person_hits.json")):
    try:
        rep = json.load(open(rep_file, encoding="utf-8"))
    except Exception as e:
        print("skip", rep_file, e); continue
    if not isinstance(rep, dict):
        continue
    axis = rep_file.stem.replace("_qc_", "").replace("_report", "").replace("_hits", "")
    c = defaultdict(lambda: [0, 0])
    susp = []
    for k, v in rep.items():
        d = k.split("/")[0]
        c[d][1] += 1
        hit = False
        if isinstance(v, dict):
            hit = (v.get("verdict") == "suspect") or bool(v.get("suspect")) or \
                  (isinstance(v.get("yes"), int) and v.get("yes", 0) > 0 and v.get("verdict") != "ok")
        elif isinstance(v, list):
            hit = len(v) > 0
        elif isinstance(v, (int, float)):
            hit = v > 0
        if hit:
            c[d][0] += 1
            susp.append(k)
    tot_s = sum(x[0] for x in c.values()); tot_t = sum(x[1] for x in c.values())
    print(f"\n===== 轴 {axis} | 可疑 {tot_s}/{tot_t} =====")
    for d, (s, t) in sorted(c.items(), key=lambda x: -x[1][0] / max(x[1][1], 1)):
        if s:
            print(f"  {s:2d}/{t:2d}  {s/t*100:5.0f}%  {d}")
    if susp:
        print("  [可疑明细前80]")
        for k in susp[:80]:
            print("   -", k)
