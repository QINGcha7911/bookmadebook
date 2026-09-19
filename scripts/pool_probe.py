#!/usr/bin/env python3
"""素材池体检：逐目录段数 / 最短 / 平均时长"""
import subprocess, sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/scenes/book_长日将尽")
rows = []
for d in sorted(root.iterdir()):
    if not d.is_dir():
        continue
    vids = sorted((d / "video").glob("*.mp4")) if (d / "video").is_dir() else []
    if not vids:
        continue
    durs = []
    for v in vids:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(v)], capture_output=True, text=True)
        try:
            durs.append(float(r.stdout.strip()))
        except Exception:
            durs.append(0.0)
    rows.append((len(vids), d.name, min(durs), sum(durs) / len(durs)))
rows.sort()
for n, name, mn, av in rows:
    print("%2d 段  最短%5.1fs  平均%5.1fs  %s" % (n, mn, av, name))
print("目录数 %d | 总段数 %d" % (len(rows), sum(r[0] for r in rows)))
