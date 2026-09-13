#!/usr/bin/env python3
"""按讲书稿生成「章节 → 素材目录」映射表（生产班/单跑的通用工具）

用法:
  python3 scripts/make_scene_map.py \\
      --script   bookmadebook-output/讲书稿_深夜食堂.txt \\
      --available assets/scenes/book_深夜食堂_available.json \\
      --scene-root assets/scenes/book_深夜食堂 \\
      --out      assets/scenes/book_深夜食堂_scene_map.json

available.json 结构（由门禁产出）: {"<场景目录>": ["01.mp4", ...], ...}

映射优先级:
  1) 【画面：...】里直接写了场景目录名（如 "empty_bar_counter —— 空无一人的木吧台"）
  2) 中文关键词兜底表（--keywords 可传自定义 JSON 覆盖/补充）
  3) 章节标题里的关键词
  4) 兜底：全片最通用的几个目录（保证每章至少 N 个目录，N 由 --min-dirs 控制，默认 3）

校验：每章必须映射到 ≥ --min-dirs 个可用目录；引用的目录必须都在 available 里。
"""
import argparse, json, os, re, sys
from collections import OrderedDict

DEFAULT_KEYWORDS = {
    # 通用兜底（各书可覆盖）
    "夜": ["night_street_empty", "street_lamp"], "街": ["night_street_empty", "night_street"],
    "巷": ["alley_night"], "后巷": ["alley_night"], "灯": ["lantern", "street_lamp"],
    "暖帘": ["noren_curtain"], "店": ["izakaya_night", "small_diner_japan"],
    "吧台": ["empty_bar_counter", "izakaya_alt"], "食堂": ["empty_bar_counter", "izakaya_alt"],
    "店内": ["empty_bar_counter"], "房间": ["shoji_window_light_b", "shoji_light"],
    "榻榻米": ["shoji_window_light_b"], "窗": ["shoji_window_light_b", "rain_window"],
    "饭": ["rice_bowl_still", "rice_wooden_table"], "白饭": ["rice_bowl_still"],
    "猫饭": ["rice_bowl_still", "rice_steam_bowl"], "茶泡饭": ["ochazuke_bowl_still", "teapot_cup_still"],
    "茶": ["teapot_cup_still", "miso_bowl_top"], "汤": ["miso_soup_pot", "miso_soup"],
    "味噌": ["miso_soup_pot", "miso_bowl_top"], "锅": ["miso_soup_pot", "kitchen_night_steam"],
    "厨房": ["kitchen_night_steam"], "蛋": ["tamagoyaki"], "玉子": ["tamagoyaki"],
    "香肠": ["sausage_pan"], "烤": ["yakitori_skewers", "grilled_fish_japan"],
    "酒": ["sake_bottle_japan", "glass_table"], "啤酒": ["beer_glass_night"],
    "杯": ["glass_table", "beer_glass_night"], "料理": ["food", "food_table", "tempura"],
    "雨": ["rain_window", "rain_glass"], "车窗": ["train_window"], "电车": ["station_platform", "last_train_platform"],
    "站台": ["station_platform", "last_train_platform"], "便利店": ["konbini_shelf", "konbini_night"],
    "庭院": ["garden"], "四季": ["garden"],
    "小菜": ["small_side_dishes"], "碗": ["two_bowls", "food_table"],
}


def parse_script(path):
    """→ [(章节标题, [画面行...])]"""
    txt = open(path, "rb").read().decode("utf-8-sig", errors="replace")
    chapters, cur = [], ("开场", [])
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("#"):
            if cur[1] or cur[0] != "开场":
                chapters.append(cur)
            cur = (re.sub(r"^#+\s*", "", s), [])
        elif s.startswith("【画面"):
            cur[1].append(s)
    chapters.append(cur)
    return [(t, f) for t, f in chapters if t or f]


def pick(shots, avail, keywords, slot_names):
    """从画面标注里取目录。
    权威来源 = 标注行里直接写出的目录名（【画面：xxx —— 描述】）。
    只有当整行都找不到目录名时，才退到中文关键词兜底——并且只看方括号后的描述部分，
    避免「料理」「汤」这类词误触发。"""
    out, seen = [], set()
    for sh in shots:
        hit = [d for d in slot_names if d in sh]
        # 去掉被更长目录名包含的短名（food 是 food_table 的子串，不该被同时命中）
        hit = [d for d in hit if not any(d != e and d in e for e in hit)]
        if hit:
            for d in hit:                       # 行内已指明目录 → 直接采用，不再兜底
                if d not in seen:
                    seen.add(d); out.append(d)
            continue
        desc = re.sub(r"^【[^】]*】", "", sh)     # 去掉标注头，只用描述部分做关键词匹配
        for kw, dirs in keywords.items():
            if kw in desc:
                for d in dirs:
                    if d in avail and d not in seen:
                        seen.add(d); out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--available", required=True)
    ap.add_argument("--scene-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keywords", help="自定义关键词表 JSON（会与默认表合并，同名覆盖）")
    ap.add_argument("--min-dirs", type=int, default=3)
    ap.add_argument("--excluded-count", type=int, default=0)
    a = ap.parse_args()

    avail = json.load(open(a.available, encoding="utf-8"))
    slot_names = sorted(avail, key=len, reverse=True)      # 长名优先，避免子串误配
    kw = dict(DEFAULT_KEYWORDS)
    if a.keywords and os.path.exists(a.keywords):
        kw.update(json.load(open(a.keywords, encoding="utf-8")))

    chapters = parse_script(a.script)
    scene_map, warn = [], []
    for title, shots in chapters:
        dirs = pick(shots, avail, kw, slot_names)
        if len(dirs) < a.min_dirs:                          # 兜底：补全最通用的目录
            for d in ("night_street_empty", "street_lamp", "empty_bar_counter",
                      "miso_soup_pot", "glass_table", "garden"):
                if d in avail and d not in dirs:
                    dirs.append(d)
                if len(dirs) >= a.min_dirs:
                    break
        if len(dirs) < a.min_dirs:
            warn.append(f"{title}: 仅 {len(dirs)} 个目录")
        scene_map.append([title, dirs])

    # 跨章节去重：同一素材目录尽量只出现在一个章节，避免同款画面在片子里重复出现
    _used = set()
    for i, (title, dirs) in enumerate(scene_map):
        keep = [d for d in dirs if d not in _used]
        if len(keep) >= a.min_dirs:
            scene_map[i] = [title, keep]
            _used.update(keep)
        else:
            _used.update(dirs)

    result = {
        "script": a.script,
        "scene_root": a.scene_root,
        "available": avail,
        "scene_map": scene_map,
        "excluded_count": a.excluded_count,
    }
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(result, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    total = sum(len(v) for v in avail.values())
    print(f"章节 {len(scene_map)} 章 | 可用素材 {total} 段 / {len(avail)} 个目录")
    for t, d in scene_map:
        print(f"  {t[:34]:36s} → {len(d)} 目录: {', '.join(d[:6])}{' ...' if len(d) > 6 else ''}")
    if warn:
        print("\n⚠️ 警告:"); [print("  -", w) for w in warn]
    print("\n已写:", out)


if __name__ == "__main__":
    main()
