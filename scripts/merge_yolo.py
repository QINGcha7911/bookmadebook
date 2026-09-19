#!/usr/bin/env python3
"""merge_yolo.py —— 把逐目录的 <dir>/_qc_person_hits.json 合并成根级 _qc_person_hits.json"""
import json, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
merged, dirs = {}, 0
for d in sorted(p for p in root.iterdir() if p.is_dir()):
    f = d / "_qc_person_hits.json"
    if not f.exists():
        continue
    dirs += 1
    for k, v in json.load(open(f, encoding="utf-8")).items():
        if not k.startswith(d.name + "/"):
            k = f"{d.name}/{k}"
        merged[k] = v
(root / "_qc_person_hits.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
hit = {k: v for k, v in merged.items() if v.get("hits")}
print(f"合并 {dirs} 个目录 | {len(merged)} 段 | 命中 {len(hit)} 段")
