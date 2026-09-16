#!/usr/bin/env python3
"""成片「禁真人」终审（多进程并行版）：按 fps 逐帧 YOLO 单人检测。

用法: python3 qc_person_scan_par.py <视频> [fps] [阈值] [进程数] [输入尺寸]
输出: /tmp/qcperson/<名>_hits.json + 命中拼图 <名>_hits.jpg
"""
import os
import sys, os, json, subprocess, time
from pathlib import Path
import numpy as np, cv2

VID  = sys.argv[1]
FPS  = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
TH   = float(sys.argv[3]) if len(sys.argv) > 3 else 0.26
NW = int(os.environ.get("QC_PROCS") or (sys.argv[4] if len(sys.argv) > 4 else 3))  # 2026-09-16：默认 3 路，14 核机器上防止与 VL/ffmpeg 互抢
SIZE = int(sys.argv[5])   if len(sys.argv) > 5 else 640

sys.path.insert(0, str(Path(__file__).resolve().parent))
from person_yolo import detect           # noqa: E402

OUT = Path("/tmp/qcperson"); OUT.mkdir(parents=True, exist_ok=True)
NAME = Path(VID).stem
DUR = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", VID], capture_output=True, text=True).stdout or 0)


def worker(args):
    idx, t0, t1 = args
    cap = cv2.VideoCapture(VID)
    hits = []
    t = t0
    while t < t1:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            break
        det = detect(fr, thresh=TH, size=SIZE)
        if det:
            d = max(det, key=lambda z: z[4])
            hits.append({"t": round(t, 2), "score": round(float(d[4]), 3),
                         "box": [int(v) for v in d[:4]], "n": len(d)})
        t += 1.0 / FPS
    cap.release()
    return idx, hits


if __name__ == "__main__":
    from multiprocessing import Pool
    span = DUR / NW
    jobs = [(i, i * span, min((i + 1) * span, DUR)) for i in range(NW)]
    print(f"视频 {NAME} | {DUR:.1f}s | {FPS}fps | {NW} 进程 | size={SIZE} | 阈值{TH}", flush=True)
    t0 = time.time()
    with Pool(NW) as p:
        res = p.map(worker, jobs)
    hits = sorted([h for _, hs in res for h in hs], key=lambda x: x["t"])
    print(f"扫描耗时 {time.time()-t0:.0f}s | 共检 {int(DUR*FPS)} 帧 | 命中 {len(hits)} 帧")

    json.dump(hits, open(OUT / f"{NAME}_hits.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if not hits:
        print("✅ 全程零人体命中 —— 可交付")
        sys.exit(0)

    print("命中时间点:", [h["t"] for h in hits][:40])
    # 命中帧拼图（红框标注）
    import PIL.Image as I, PIL.ImageDraw as D
    TW, COLS = 260, 6
    tiles = []
    cap = cv2.VideoCapture(VID)
    for h in hits[:48]:
        cap.set(cv2.CAP_PROP_POS_MSEC, h["t"] * 1000)
        ok, fr = cap.read()
        if ok:
            tiles.append((h, fr))
    cap.release()
    rows = (len(tiles) + COLS - 1) // COLS
    sheet = I.new("RGB", (COLS * TW, rows * int(TW * 1.78)), "white")
    dr = D.Draw(sheet)
    for k, (h, fr) in enumerate(tiles):
        H, W = fr.shape[:2]
        im = I.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
        im.thumbnail((TW, TW * 1.9))
        px, py = (k % COLS) * TW, (k // COLS) * int(TW * 1.78)
        sheet.paste(im, (px, py))
        x1, y1, x2, y2 = h["box"]
        dr.rectangle([px + x1 * TW / W, py + y1 * TW / W, px + x2 * TW / W, py + y2 * TW / W],
                     outline="red", width=3)
        dr.text((px + 4, py + 4), f'{h["t"]:.0f}s {h["score"]:.2f}', fill="red")
    p = OUT / f"{NAME}_hits.jpg"
    sheet.save(p, quality=88)
    print("命中拼图:", p)
