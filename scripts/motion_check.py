"""实测成片里的"近似静态"段落（不依赖下游评级）
用法: python3 /tmp/motion_check.py <video> <outdir>
原理: 每秒抽 1 帧(缩到 160x284) → 算相邻帧平均绝对差 → 找出"连续 ≥2 秒差异极小"的段 → 拼图供目视裁决
注意: 字卡/金句卡/片头/片尾声明本身就是静态的，会把它们的时段一并列出，由目视区分"卡片(可接受)"与"素材镜头(缺陷)"。
"""
import subprocess, sys, json
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

F = sys.argv[1]
OUT = Path(sys.argv[2]); OUT.mkdir(exist_ok=True, parents=True)
tmp = OUT/"frames"; tmp.mkdir(exist_ok=True)

subprocess.run(["ffmpeg","-v","error","-y","-i",F,"-vf","fps=1,scale=160:284","-q:v","4",str(tmp/"f_%04d.jpg")], check=False)
files = sorted(tmp.glob("f_*.jpg"))
if not files:
    print("ERROR: 未抽到帧"); sys.exit(3)

arrs = []
for p in files:
    a = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
    arrs.append(a)

diffs = []
for i in range(1, len(arrs)):
    d = float(np.abs(arrs[i] - arrs[i-1]).mean())
    diffs.append(d)

THRESH = 1.0
runs = []
cur = None
for i, d in enumerate(diffs):
    sec = i + 1  # diffs[i] = 第 i+1 秒与第 i 秒之差
    if d < THRESH:
        if cur is None: cur = [sec, sec, d]
        else: cur[1] = sec; cur[2] = min(cur[2], d)
    else:
        if cur is not None:
            if cur[1] - cur[0] >= 1: runs.append(cur)
            cur = None
if cur is not None and cur[1]-cur[0] >= 1: runs.append(cur)

print(f"视频: {F}")
print(f"抽帧 {len(files)} 张（1fps）| 全片帧间平均差均值 {sum(diffs)/len(diffs):.3f} | 最小 {min(diffs):.3f} | 最大 {max(diffs):.3f}")
print(f"阈值 {THRESH} 以下、且持续 ≥2 秒的近似静态段: {len(runs)} 处")
print("时间轴（秒）:")
for a,b,d in runs:
    print(f"   {a}–{b}s  (差最小 {d:.3f})")

# 拼图：每处取首/中/末三帧
tiles = []
for a,b,d in runs[:14]:
    for t in (a, (a+b)//2, b):
        idx = min(max(t,1), len(files))
        im = Image.open(files[idx-1]).convert("RGB").resize((180, 320))
        dr = ImageDraw.Draw(im); dr.text((4,4), f"{t}s", fill="red")
        tiles.append(im)
if tiles:
    cols = 6
    rows = (len(tiles)+cols-1)//cols
    sheet = Image.new("RGB",(180*cols, 320*rows),"white")
    for i,im in enumerate(tiles):
        sheet.paste(im, ((i%cols)*180, (i//cols)*320))
    sheet.save(OUT/"static_sheet.jpg", quality=88)
    print(f"拼图: {OUT/'static_sheet.jpg'}（{len(tiles)} 格 = 每处首/中/末）")
json.dump({"runs":[{"start":a,"end":b,"min_diff":d} for a,b,d in runs],
           "mean":sum(diffs)/len(diffs),"min":min(diffs),"max":max(diffs)},
          open(OUT/"motion.json","w"), ensure_ascii=False, indent=1)
print("ALLDONE")
