#!/usr/bin/env python3
"""YOLO 存活子集扫描收尾器：等 qc_clip_scan 结束 → 命中段自动进排除清单 → 重建 scene_map → 重跑收口校验
保守策略：YOLO 命中即排除（不做接受裁决）
"""
import json, subprocess, time, os
from pathlib import Path

LOG = open("/root/yolo_apply.log", "w", encoding="utf-8")
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); LOG.write(s + "\n"); LOG.flush()

# 1) 等 YOLO 结束
for _ in range(240):   # 最多等 40 分钟
    r = subprocess.run(["pgrep", "-f", "qc_clip_scan.py"], capture_output=True, text=True)
    if not r.stdout.strip():
        break
    time.sleep(10)
else:
    log("⚠️ 等待超时，YOLO 可能仍在跑"); raise SystemExit(1)
log("YOLO 进程已结束")

os.chdir("/mnt/d/AI软件/GitHub/bookmadebook")
rep = Path("assets/scenes/book_长日将尽/_qc_yolo_survivors.json")
if not rep.exists():
    log("无 _qc_yolo_survivors.json（YOLO 无命中或失败）"); raise SystemExit(0)

hits = json.load(open(rep, encoding="utf-8"))
hits = {k: v for k, v in hits.items() if v.get("hits")}
log("YOLO 命中段数:", len(hits))

excl_path = Path("assets/scenes/book_长日将尽_excluded.json")
dec_path = Path("assets/scenes/book_长日将尽_qc_decisions.json")
excl = set(json.load(open(excl_path, encoding="utf-8")))
dec = json.load(open(dec_path, encoding="utf-8"))
added = 0
for k, v in sorted(hits.items()):
    short = k.replace("/video/", "/")
    if short in excl:
        continue
    excl.add(short)
    dec[short] = {"verdict": "exclude",
                  "why": "YOLO 逐帧人体扫描（1.5fps, th=0.28, 960px）命中 %d 处" % len(v["hits"])}
    added += 1
    log("  +排除", short, len(v["hits"]), "处")
excl_path.write_text(json.dumps(sorted(excl), ensure_ascii=False, indent=1), encoding="utf-8")
dec_path.write_text(json.dumps(dec, ensure_ascii=False, indent=1), encoding="utf-8")
log("新增排除", added, "| 排除总数", len(excl))

# 2) 重建 scene_map
r = subprocess.run(["python3", "scripts/make_scene_map_changri.py"], capture_output=True, text=True)
log(r.stdout[-900:])
# 3) 收口校验
r2 = subprocess.run(["python3", "scripts/qc_gate_audit.py", "assets/scenes/book_长日将尽"],
                    capture_output=True, text=True)
log(r2.stdout[-600:], "exit=", r2.returncode)
