#!/usr/bin/env python3
"""qc_clip_scan_fast.py —— qc_clip_scan.py 的提速版（同判定口径，同输出格式）

为什么：原版对每一帧 cap.set(POS_MSEC) 逐帧 seek → 每次都从关键帧重解码，实测
9 段 ~15s 素材要 2m21s（4 进程），290 段跑不完。本版改成：
  ① ffmpeg 一次顺序解码抽帧（fps=N，无 seek）
  ② 多帧拼 batch 一次 ONNX 推理
判定规则与输出格式（_qc_person_hits.json）与原版完全一致。

用法: python3 qc_clip_scan_fast.py <素材根> [fps=1.5] [thresh=0.28] [size=960] [workers=6]
"""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
import numpy as np, cv2

cv2.setNumThreads(1)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from person_yolo import letterbox, nms, sess   # noqa: E402

ROOT = Path(sys.argv[1]).resolve()
FPS = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5
TH = float(sys.argv[3]) if len(sys.argv) > 3 else 0.28
SIZE = int(sys.argv[4]) if len(sys.argv) > 4 else 960
NW = int(sys.argv[5]) if len(sys.argv) > 5 else 6
BATCH = int(os.environ.get("YOLO_BATCH", "6"))

CLIPS = sorted(p for p in ROOT.rglob("*.mp4") if not any(s.startswith("_excluded") for s in p.parts))
print(f"素材根 {ROOT} | clip {len(CLIPS)} 个 | {FPS}fps | size={SIZE} | 阈值{TH} | {NW} 进程 | batch {BATCH}", flush=True)


def batch_detect(frames):
    """frames: list[np.ndarray] → list[list[(x1,y1,x2,y2,score)]]"""
    xs, metas = [], []
    for im in frames:
        lb, r, l, t = letterbox(im, SIZE)
        xs.append(lb[:, :, ::-1].astype(np.float32).transpose(2, 0, 1) / 255.0)
        metas.append((r, l, t, im.shape))
    out = sess().run(None, {"images": np.stack(xs)})[0]     # [B,5,N]
    res = []
    for bi in range(len(frames)):
        cx, cy, w, h, sc = out[bi][0], out[bi][1], out[bi][2], out[bi][3], out[bi][4]
        m = sc >= TH
        if not m.any():
            res.append([])
            continue
        b = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 1)[m]
        s = sc[m]
        keep = nms(b, s)
        r, l, t, shape = metas[bi]
        res.append([((b[i][0] - l) / r, (b[i][1] - t) / r, (b[i][2] - l) / r, (b[i][3] - t) / r, float(s[i]))
                    for i in keep])
    return res


def scan(path_str):
    path = Path(path_str)
    tmp = Path(tempfile.mkdtemp())
    dur = 0.0
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        dur = float(r.stdout.strip() or 0)
    except Exception:
        pass
    if dur <= 0:
        return str(path.relative_to(ROOT)), {"dur": 0, "hits": [], "err": "probe_failed"}
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={FPS}",
                    "-q:v", "3", str(tmp / "%04d.jpg")], capture_output=True, timeout=900)
    frames, times = [], []
    for i, f in enumerate(sorted(tmp.glob("*.jpg"))):
        im = cv2.imread(str(f))
        if im is not None:
            frames.append(im)
            times.append(round(i / FPS, 2))
    hits = []
    for i in range(0, len(frames), BATCH):
        chunk = frames[i:i + BATCH]
        for j, dets in enumerate(batch_detect(chunk)):
            if dets:
                d = max(dets, key=lambda z: z[4])
                hits.append({"t": times[i + j], "score": round(float(d[4]), 3),
                             "box": [int(v) for v in d[:4]]})
    for f in tmp.glob("*.jpg"):
        f.unlink(missing_ok=True)
    try:
        tmp.rmdir()
    except Exception:
        pass
    return str(path.relative_to(ROOT)), {"dur": round(dur, 2), "hits": hits}


if __name__ == "__main__":
    from multiprocessing import Pool

    def _dur(c):
        try:
            return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", str(c)], capture_output=True,
                                        text=True, timeout=60).stdout or 0)
        except Exception:
            return 0.0

    order = sorted(CLIPS, key=_dur, reverse=True)
    t0 = time.time()
    with Pool(NW) as pool:
        res = pool.map(scan, [str(c) for c in order], chunksize=1)
    out = {k: v for k, v in res}
    bad = {k: v for k, v in out.items() if v.get("hits")}
    (ROOT / "_qc_person_hits.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成 {len(out)} 段，耗时 {time.time()-t0:.0f}s，命中 {len(bad)} 段")
    for k, v in list(bad.items())[:40]:
        print(f"   ❌ {k}  {v['dur']}s  命中{len(v['hits'])}处")
