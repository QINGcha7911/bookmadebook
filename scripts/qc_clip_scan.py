#!/usr/bin/env python3
"""素材级「禁真人」扫描：对素材池每个 clip 逐帧跑 YOLO 单人检测。

用法: python3 qc_clip_scan.py <素材根> [fps=1.5] [thresh=0.28] [size=960] [workers=6]
输出: <根>/_qc_person_hits.json  +  stdout 打印 hits 非空的 clip 清单

判定铁律（2026-09-13《深夜食堂》教训）:
  **hits 非空即排除，不看框大小、不看 score 高低。**
  抽帧目测（每段 2 帧）会漏掉「手/人影出现在没抽到的秒」，
  实测放行过的 4 段素材（含画面正中的骑车人）全部被本工具抓出。
  命中后仍须人工放大确认（暖帘/提灯/雕像/窗玻璃拖影是高频误报）。
"""
import sys, os, json, subprocess, time
from pathlib import Path
import numpy as np, cv2

# 2026-09-14: 多进程扫描时 OpenCV 默认每进程开满核线程 → 8 进程 × 14 线程
# 造成严重超额订阅（实测 load 112，扫描慢 3-5 倍）。限定为 1 线程，
# 并行度交给进程数控制。可用 CV_THREADS 覆盖。
try:
    cv2.setNumThreads(int(os.environ.get("CV_THREADS", "1")))
except Exception:
    pass

ROOT = Path(sys.argv[1]).resolve()
FPS  = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5
TH   = float(sys.argv[3]) if len(sys.argv) > 3 else 0.28
SIZE = int(sys.argv[4])   if len(sys.argv) > 4 else 960
NW   = int(sys.argv[5])   if len(sys.argv) > 5 else 6

sys.path.insert(0, str(Path(__file__).resolve().parent))
from person_yolo import detect                                    # noqa: E402

CLIPS = sorted(p for p in ROOT.rglob("*.mp4") if not any(s.startswith("_excluded") for s in p.parts))
print(f"素材根 {ROOT} | clip {len(CLIPS)} 个 | {FPS}fps | size={SIZE} | 阈值{TH} | {NW} 进程", flush=True)


def scan(path_str):
    path = Path(path_str)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(path)],
                               capture_output=True, text=True).stdout or 0)
    if dur <= 0:
        return str(path), {"dur": 0, "hits": [], "err": "probe_failed"}
    cap = cv2.VideoCapture(str(path))
    hits, t = [], 0.0
    while t < dur:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            break
        det = detect(fr, thresh=TH, size=SIZE)
        if det:
            d = max(det, key=lambda z: z[4])
            hits.append({"t": round(t, 2), "score": round(float(d[4]), 3),
                         "box": [int(v) for v in d[:4]]})
        t += 1.0 / FPS
    cap.release()
    rel = str(path.relative_to(ROOT))
    return rel, {"dur": round(dur, 2), "hits": hits}


if __name__ == "__main__":
    from multiprocessing import Pool

    # 先探时长，按「长片优先」排序（Pool.map 按序派发 → 长短混排避免单个长片拖尾）
    def _dur(c):
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", str(c)],
                                    capture_output=True, text=True).stdout or 0)

    order = sorted(CLIPS, key=_dur, reverse=True)          # 长片先发
    t0 = time.time()
    with Pool(NW) as pool:
        res = pool.map(scan, [str(c) for c in order], chunksize=1)
    out = {k: v for k, v in res}
    bad = {k: v for k, v in out.items() if v.get("hits")}
    (ROOT / "_qc_person_hits.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n扫描耗时 {time.time()-t0:.0f}s | 干净 {len(out)-len(bad)} / 命中 {len(bad)}")
    if bad:
        print("⚠️ 以下素材 hits 非空 → 排除（仍须放大确认是否为误报）:")
        for k, v in sorted(bad.items()):
            print(f"   ❌ {k}  {v['dur']}s  命中{len(v['hits'])}处  "
                  f"{[h['t'] for h in v['hits']][:6]}")
        print("\n放大确认: ffmpeg -i <clip> -ss <t> -frames:v 1 "
              "-vf \"crop=W:H:X:Y,scale=600:-1:flags=lanczos\" out.jpg")
    else:
        print("✅ 全池零人体命中")
