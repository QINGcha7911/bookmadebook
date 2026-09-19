#!/usr/bin/env python3
"""《长日将尽》章节映射表生成（生产班直接输入）
依据：讲书稿每章的【画面】标注 + 各章语义 → assets/scenes/book_长日将尽/<目录>
"""
import json, re, sys
from pathlib import Path

ROOT = Path("assets/scenes/book_长日将尽")
SCRIPT = Path("bookmadebook-output/讲书稿_长日将尽.txt")
EXCL = Path("assets/scenes/book_长日将尽_excluded.json")

excluded = set(json.load(open(EXCL, encoding="utf-8")))
text = SCRIPT.read_text(encoding="utf-8")

# available：目录 → 未排除文件
available = {}
for d in sorted(ROOT.iterdir()):
    if not d.is_dir() or d.name.startswith("_"):
        continue
    vids = sorted(f.name for f in (d / "video").glob("*.mp4")
                  if f"{d.name}/{f.name}" not in excluded)
    if vids:
        available[d.name] = vids

# 解析章节
sections = []
cur = ("开场", [])
for line in text.split("\n"):
    m = re.match(r"^##\s*(.+)$", line.strip())
    if m:
        sections.append(cur)
        cur = (m.group(1).strip(), [])
        continue
    m2 = re.match(r"^【画面[：:]\s*([A-Za-z0-9_]+)", line.strip())
    if m2:
        cur[1].append(m2.group(1))
sections.append(cur)

# 各章语义补充目录（讲书稿没标到但语义贴近的）
EXTRA = {
 "开场": ["english_stately_home_hall", "english_tea_service", "english_candle_dinner", "rain_window_glass"],
 "第一章": ["english_stately_home_hall", "english_candle_dinner", "english_fireplace_mantel",
            "rain_window_glass", "english_sheer_curtain"],
 "第二章": ["english_roses_garden", "english_garden_flowers", "english_garden_path",
            "english_sheer_curtain", "english_manor_window"],
 "第三章": ["english_candle_dinner", "english_fireplace_mantel", "english_stately_home_hall",
            "rain_window_glass", "english_wooden_door_old"],
 "第四章": ["english_country_lane", "english_countryside_hills", "english_hedgerow_field",
            "golden_wheat_field", "english_stone_cottage", "english_morning_mist", "english_autumn_park"],
 "第五章": ["english_lake_reflection", "english_morning_mist", "english_countryside_hills",
            "english_stone_wall_moss", "english_village_church"],
 "尾声": ["english_manor_window", "english_sheer_curtain", "english_autumn_park",
          "english_garden_flowers", "english_fireplace_mantel"],
}
def extras_for(title):
    for k, v in EXTRA.items():
        if title.startswith(k):
            return v
    return ["english_countryside_hills", "english_garden_flowers", "english_autumn_park"]

scene_map = []
report = []
for title, dirs in sections:
    picked = [d for d in dirs if d in available]
    for d in extras_for(title):
        if d in available and d not in picked:
            picked.append(d)
    if len(picked) < 3:
        for d in sorted(available, key=lambda x: -len(available[x])):
            if d not in picked:
                picked.append(d)
            if len(picked) >= 3:
                break
    scene_map.append([title, picked])
    report.append((title, len(dirs), len(picked)))

out = {
 "script": "bookmadebook-output/讲书稿_长日将尽.txt",
 "scene_root": "assets/scenes/book_长日将尽",
 "available": available,
 "excluded": sorted(excluded),
 "scene_map": scene_map,
}
(ROOT.parent / "book_长日将尽_scene_map.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

# ---- 校验 ----
chapters_script = [s[0] for s in sections]
chapters_map = [x[0] for x in scene_map]
ok = True
if chapters_script != chapters_map:
    ok = False; print("❌ 章节不一致")
for t, p in scene_map:
    if len(p) < 3:
        ok = False; print("❌ 目录不足 3:", t, p)
    for d in p:
        if d not in available:
            ok = False; print("❌ 目录不在 available:", t, d)
for d, v in available.items():
    if not v:
        ok = False; print("❌ 空目录:", d)
print("章节数", len(scene_map), "| 可用目录", len(available),
      "| 可用段", sum(len(v) for v in available.values()), "| 排除", len(excluded))
for t, nd, npk in report:
    print("  %-22s 稿内画面%2d → 映射目录%2d" % (t, nd, npk))
print("校验:", "✅ PASS" if ok else "❌ FAIL")
