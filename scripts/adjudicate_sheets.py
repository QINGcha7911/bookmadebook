#!/usr/bin/env python3
"""按目录生成带文件名的裁决拼图（每行一个目录，列=该目录素材，每段抽 2 帧）
用法: python3 scripts/adjudicate_sheets.py <池根> <输出目录> [每图目录数] [每目录段数]
"""
import subprocess, sys, math, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

POOL = Path(sys.argv[1])
OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
DIRS_PER_SHEET = int(sys.argv[3]) if len(sys.argv) > 3 else 4
MAXCLIP = int(sys.argv[4]) if len(sys.argv) > 4 else 8
ONLY = [x for x in (sys.argv[5].split(",") if len(sys.argv) > 5 else []) if x]
FRAMES = tuple(float(x) for x in os.environ.get("ADJ_FRAMES", "0.3,0.7").split(","))
CW, CH = 200, 356          # 单帧格子（竖版 9:16）
LBLW = 210                 # 左侧目录名栏
HDR = 22                   # 列标题栏

try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15)
    FONTS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
except Exception:
    FONT = FONTS = ImageFont.load_default()

dirs = sorted([d for d in POOL.iterdir() if d.is_dir() and not d.name.startswith("_")])
if ONLY:
    dirs = [d for d in dirs if d.name in ONLY]
sheets = []
for i in range(0, len(dirs), DIRS_PER_SHEET):
    sheets.append(dirs[i:i + DIRS_PER_SHEET])

for si, group in enumerate(sheets):
    rows = []
    maxcol = 0
    tmp = OUT / f"_tmp{si}"; tmp.mkdir(exist_ok=True)
    for d in group:
        vids = sorted((d / "video").glob("*.mp4")) if (d / "video").is_dir() else []
        vids = vids[:MAXCLIP]
        maxcol = max(maxcol, len(vids) * 2)
        row = []
        for v in vids:
            dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", str(v)], capture_output=True, text=True).stdout.strip()
            try:
                D = float(dur)
            except Exception:
                D = 10.0
            for frac in (0.3, 0.7):
                p = tmp / f"{d.name}_{v.stem}_{int(frac*100)}.jpg"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{D*frac:.2f}", "-i", str(v),
                                "-frames:v", "1", "-vf", f"scale={CW}:-2", "-q:v", "4", str(p)],
                               capture_output=True)
                row.append((p if p.exists() else None, f"{v.stem}"))
        rows.append((d.name, row))

    W = LBLW + maxcol * CW
    H = HDR + len(rows) * (CH + HDR)
    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    y = HDR
    for name, row in rows:
        dr.text((6, y + CH // 2), name[:26], fill=(255, 210, 120), font=FONT)
        x = LBLW
        for img, lab in row:
            if img is not None:
                try:
                    im = Image.open(img).convert("RGB")
                    im.thumbnail((CW, CH - 2))
                    sheet.paste(im, (x, y))
                except Exception:
                    pass
            dr.rectangle([x, y, x + CW - 2, y + CH], outline=(70, 70, 80))
            dr.text((x + 3, y + 2), lab, fill=(140, 240, 160), font=FONTS)
            x += CW
        y += CH + HDR
    out = OUT / f"adj_{si:02d}.jpg"
    sheet.save(out, quality=82)
    print(out, sheet.size)
