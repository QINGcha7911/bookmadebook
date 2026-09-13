#!/usr/bin/env python3
"""YOLOv11 单人检测器（deepghs/real_person_detection l_yv11）——用于素材/成片'禁真人'审计。
输入动态尺寸，输出 [1,5,N] = cx,cy,w,h,score（单类 person）。"""
import onnxruntime as ort, numpy as np, cv2, subprocess, sys, json
from pathlib import Path

MODEL = (str(Path(__file__).resolve().parent.parent / "models/person_l.onnx")
         if (Path(__file__).resolve().parent.parent / "models/person_l.onnx").exists()
         else "/tmp/person_l.onnx")
_sess = None
def sess():
    global _sess
    if _sess is None:
        so = ort.SessionOptions(); so.intra_op_num_threads = 4; so.log_severity_level = 3
        _sess = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
    return _sess

def letterbox(im, size=960):
    h, w = im.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    res = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_LINEAR)
    top = (size - nh) // 2; left = (size - nw) // 2
    out = np.full((size, size, 3), 114, np.uint8)
    out[top:top+nh, left:left+nw] = res
    return out, r, left, top

def nms(boxes, scores, thr=0.45):
    idx = scores.argsort()[::-1]; keep = []
    while idx.size:
        i = idx[0]; keep.append(i)
        if idx.size == 1: break
        xx1 = np.maximum(boxes[i,0], boxes[idx[1:],0]); yy1 = np.maximum(boxes[i,1], boxes[idx[1:],1])
        xx2 = np.minimum(boxes[i,2], boxes[idx[1:],2]); yy2 = np.minimum(boxes[i,3], boxes[idx[1:],3])
        w = np.maximum(0, xx2-xx1); h = np.maximum(0, yy2-yy1)
        iou = w*h / (np.maximum(1e-6,(boxes[i,2]-boxes[i,0])*(boxes[i,3]-boxes[i,1]) + (boxes[idx[1:],2]-boxes[idx[1:],0])*(boxes[idx[1:],3]-boxes[idx[1:],1]) - w*h))
        idx = idx[1:][iou <= thr]
    return keep

def detect(im, thresh=0.28, size=960):
    """返回 [(x1,y1,x2,y2,score)]，坐标已映射回原图。"""
    lb, r, l, t = letterbox(im, size)
    x = lb[:, :, ::-1].astype(np.float32).transpose(2,0,1)[None] / 255.0
    out = sess().run(None, {"images": x})[0][0]           # [5,N]
    cx, cy, w, h, sc = out[0], out[1], out[2], out[3], out[4]
    m = sc >= thresh
    if not m.any(): return []
    b = np.stack([cx-w/2, cy-h/2, cx+w/2, cy+h/2], 1)[m]
    s = sc[m]
    keep = nms(b, s)
    res = []
    for i in keep:
        x1,y1,x2,y2 = b[i]
        res.append(((x1-l)/r, (y1-t)/r, (x2-l)/r, (y2-t)/r, float(s[i])))
    return res

def sample_frames(path, n=40, maxw=0):
    cap = cv2.VideoCapture(str(path))
    N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out = []
    if N <= 0: cap.release(); return out
    idxs = np.linspace(0, N-1, min(n, N)).astype(int)
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i)); ok, fr = cap.read()
        if ok: out.append((int(i), fr))
    cap.release(); return out

if __name__ == "__main__":
    arg = sys.argv[1]
    th = float(sys.argv[2]) if len(sys.argv) > 2 else 0.28
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    p = Path(arg)
    if p.is_file():
        files = [p]
    else:
        files = sorted(p.glob("*.mp4"))
    for f in files:
        frames = sample_frames(f, n)
        hits = []
        for i, fr in frames:
            for d in detect(fr, th):
                hits.append((i, [round(v,1) for v in d[:4]], round(d[4],3)))
        big = [h for h in hits if h[2] >= 0.35]
        print(f"{'⚠️' if hits else '  '} {f.name:44s} dur_frames={len(frames)} hits={len(hits)} strong={len(big)}")
        for h in hits[:12]:
            print(f"      f{h[0]:5d} score={h[2]:.2f} box={h[1]}")
