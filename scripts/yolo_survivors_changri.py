#!/usr/bin/env python3
"""对存活子集建符号链接视图并跑 YOLO（补齐人体轴全池覆盖）"""
import json, os, subprocess, shutil
from pathlib import Path

SRC = Path("assets/scenes/book_长日将尽")
DST = Path("/tmp/surv/book_长日将尽")
excluded = set(json.load(open("assets/scenes/book_长日将尽_excluded.json", encoding="utf-8")))
if DST.exists():
    shutil.rmtree(DST)
n = 0
for d in sorted(SRC.iterdir()):
    if not d.is_dir() or d.name.startswith("_"):
        continue
    for f in sorted((d / "video").glob("*.mp4")):
        if f"{d.name}/{f.name}" in excluded:
            continue
        tgt = DST / d.name / "video" / f.name
        tgt.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(f.resolve(), tgt)
        n += 1
print("存活子集符号链接:", n)
r = subprocess.run(["python3", "scripts/qc_clip_scan.py", str(DST), "1.5", "0.28", "960", "8"],
                   capture_output=True, text=True, timeout=3600)
print(r.stdout[-1500:])
print("ERR", r.stderr[-500:])
rep = DST / "_qc_person_hits.json"
if rep.exists():
    hits = json.load(open(rep, encoding="utf-8"))
    hits = {k: v for k, v in hits.items() if v.get("hits")}
    out = {k.replace("book_长日将尽/", ""): v for k, v in hits.items()}
    Path("assets/scenes/book_长日将尽/_qc_yolo_survivors.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("YOLO 命中段数:", len(out))
    for k in sorted(out):
        print("  ", k, len(out[k]["hits"]), "处")
