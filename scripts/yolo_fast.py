#!/usr/bin/env python3
"""快速版 YOLO 人体扫描（顺序解码 + grab 跳帧，替代 qc_clip_scan 的每帧 POS_MSEC 寻址）
用法: python3 yolo_fast.py <素材根> [fps=1.5] [thresh=0.28] [size=960] [workers=8] [清单文件(可选)]
输出: <根>/_qc_person_hits_fast.json（格式同 qc_clip_scan: {rel: {dur, hits:[{t,score,box}]}}）
"""
import sys, os, json, time, subprocess
from pathlib import Path
import cv2

cv2.setNumThreads(int(os.environ.get("CV_THREADS", "1")))

ROOT = Path(sys.argv[1]).resolve()
FPS = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5
TH = float(sys.argv[3]) if len(sys.argv) > 3 else 0.28
SIZE = int(sys.argv[4]) if len(sys.argv) > 4 else 960
NW = int(sys.argv[5]) if len(sys.argv) > 5 else 8
LIST = Path(sys.argv[6]) if len(sys.argv) > 6 else None

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/mnt/d/AI软件/GitHub/bookmadebook/scripts")
from person_yolo import detect  # noqa

if LIST:
    CLIPS = [Path(l.strip()) for l in LIST.read_text().splitlines() if l.strip()]
else:
    CLIPS = sorted(p for p in ROOT.rglob("*.mp4") if not any(s.startswith("_") for s in p.parts))


def scan(path_str):
    path = Path(path_str)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return str(path.relative_to(ROOT)), {"dur": 0, "hits": [], "err": "open_failed"}
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(src_fps / FPS)))
    hits, idx, t = [], 0, 0.0
    while True:
        if idx % step == 0:
            ok = cap.grab()
            if not ok:
                break
            ok, fr = cap.retrieve()
            if ok and fr is not None:
                det = detect(fr, thresh=TH, size=SIZE)
                if det:
                    d = max(det, key=lambda z: z[4])
                    hits.append({"t": round(t, 2), "score": round(float(d[4]), 3),
                                 "box": [int(v) for v in d[:4]]})
        else:
            if not cap.grab():
                break
        idx += 1
        t += 1.0 / src_fps
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / src_fps if src_fps else 0
    cap.release()
    return str(path.relative_to(ROOT)), {"dur": round(dur, 2), "hits": hits}


if __name__ == "__main__":
    from multiprocessing import Pool
    print(f"快速 YOLO | clip {len(CLIPS)} | {FPS}fps 采样 | size={SIZE} | {NW} 进程", flush=True)
    t0 = time.time()
    with Pool(NW) as pool:
        res = pool.map(scan, [str(c) for c in CLIPS], chunksize=1)
    out = {k: v for k, v in res}
    bad = {k: v for k, v in out.items() if v.get("hits")}
    (ROOT / "_qc_person_hits_fast.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"耗时 {time.time()-t0:.0f}s | 干净 {len(out)-len(bad)} / 命中 {len(bad)}")
    for k, v in sorted(bad.items()):
        print(f"   ❌ {k} {v['dur']}s 命中{len(v['hits'])}处 {[h['t'] for h in v['hits']][:6]}")
