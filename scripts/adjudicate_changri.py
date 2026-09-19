#!/usr/bin/env python3
"""《长日将尽》最终裁决落盘 v2 —— 汇总四道门禁 + 人工逐格复核
依据：/root/adjudicate/adj_0*.jpg（person_part 视角）、/root/adjudicate2/adj_0*.jpg（modern 视角）
原则：门禁判可疑 → 默认排除；只有本人目视确认干净且有理由的才 accept
"""
import json
from pathlib import Path

POOL = Path("assets/scenes/book_长日将尽")
SHORT = lambda k: k.replace("/video/", "/")   # 长格式→短格式

# ---------- 人工目视：整目录排除 ----------
DIR_EXCLUDE = {
    "english_breakfast_table": "整目录真人：儿童/女性用餐、多只手入镜",
    "english_book_pages": "整目录有手：翻书页的手/手指",
    "english_formal_dining": "整目录真人：白手套服务生手臂、西装男子",
    "english_hallway_umbrella": "整目录真人：多位女性/儿童、楼梯人影",
    "english_harbour_boats": "现代游艇码头/地中海渔港，非英国且现代（塑料浮桥、玻璃钢船体）",
    "english_manor_staircase": "整目录真人：红衫男子、楼梯上人群",
    "english_railway_station": "现代列车与电气化铁路，1956 年题材年代错配",
    "english_servants_kitchen": "整目录真人：女性/儿童/涂鸦墙人群",
    "english_silver_tray": "整目录真人：白手套的手端托盘、侍者男子",
    "english_writing_desk": "整目录真人：写字的手/女性/打字机旁男子",
    "old_english_library": "整目录现代图书馆：玻璃幕墙、平板/笔记本、熙攘人群",
    "english_seaside_pier": "7/7 段 6-8 帧 VL 全票命中人物（远景游人），无法排除干净",
    "silver_dining_table": "整目录真人 + 圣诞/光明节装饰摆拍",
    "vintage_car_country_road": "整目录现代汽车：SUV/面包车/现代轿车/方向盘上的手",
    "vintage_leather_suitcase": "整目录真人模特拎行李箱（时尚摆拍）",
    "english_autumn_country_road": "整目录空中航拍的现代公路：多车道柏油路、白色标线与行驶车辆",
    "old_english_kitchen": "整目录现代厨房：白色橱柜/燃气灶/商超货架/开抽屉的手（搜索词返回当代厨房）",
}

# ---------- 人工目视：单段排除 ----------
CLIP_EXCLUDE = {
    "english_fireplace_mantel": {"02.mp4": "炉前真人腿部/身体入镜",
                                 "04.mp4": "圣诞树与袜子装饰（与本书无关）",
                                 "07.mp4": "现代杂志/食物摆拍"},
    "english_tea_service": {"02.mp4": "现代商品照感：粉色霓虹背景+玻璃茶壶",
                            "03.mp4": "手端茶杯（6/8 帧命中）",
                            "04.mp4": "手倒茶入镜（7/7 帧命中）",
                            "06.mp4": "商品照感+手（product_shot 6/6）",
                            "07.mp4": "手与奶壶入镜"},
    "english_candle_dinner": {"03.mp4": "桌面杂乱+手部入镜"},
    "english_manor_window": {"01.mp4": "真人芭蕾舞者（双手举起）"},
    "english_sheer_curtain": {"06.mp4": "帘后人体剪影（7/7 帧命中）"},
    "english_stately_home_hall": {"03.mp4": "现代图书馆中庭（玻璃+扶梯+人群）",
                                  "05.mp4": "宫殿大厅内成排真人游客",
                                  "06.mp4": "大厅内真人游客"},
    "english_autumn_park": {"05.mp4": "现代玻璃幕墙建筑前红叶"},
    "english_country_house_manor": {"02.mp4": "航拍宅邸含停放车辆（modern 2/6）",
                                    "03.mp4": "乡道镜头内有现代汽车"},
    "english_country_lane": {"03.mp4": "航拍公路+行驶车辆",
                             "04.mp4": "公路+车辆",
                             "05.mp4": "公路+车辆",
                             "06.mp4": "航拍公路+标线",
                             "07.mp4": "公路+标线+车辆"},
    "english_hedgerow_field": {"04.mp4": "树篱间公路+车辆"},
    "english_stone_cottage": {"05.mp4": "航拍村落街景含车辆",
                              "06.mp4": "航拍村落含车辆"},
    "english_village_church": {"01.mp4": "航拍街景含车辆", "02.mp4": "航拍村落公路",
                               "03.mp4": "航拍村落+车辆", "06.mp4": "航拍村落+车辆",
                               "08.mp4": "航拍街景+车辆"},
    "rain_window_glass": {"04.mp4": "雨滴玻璃（region 判中性可疑，保守排除）"},
}

# ---------- 人工目视：接受（留理由可审计）----------
ACCEPT = {
    "english_fountain_garden/03.mp4": "规整花园铺装与喷泉，无人物与现代物件（VL 把铺装/雕塑误判）",
    "english_fountain_garden/06.mp4": "宫殿与倒影水池远景，无人（VL 误将远景判为人物）",
    "english_garden_path/04.mp4": "规整花园与远处宅邸，无人无现代物件",
    "english_hedgerow_field/02.mp4": "树篱与农田，无车辆（modern 轴误判）",
    "english_stone_cottage/01.mp4": "石砌农舍与野草，无现代元素",
    "english_stone_cottage/03.mp4": "林间溪流与石岸，无现代元素",
    "english_stone_cottage/04.mp4": "苔石墙与草坡，无现代元素",
    "english_country_lane/01.mp4": "草坡绵羊与老树，无车辆（modern 轴误判）",
    "english_country_lane/02.mp4": "砾石乡间小路与树篱，无车辆",
    "english_country_lane/08.mp4": "林荫乡间路，无车辆",
    "english_autumn_park/01.mp4": "晨雾林间小径，无人",
    "english_autumn_park/02.mp4": "秋叶林间小径，无人",
    "english_autumn_park/03.mp4": "秋日草地，无人",
    "english_autumn_park/04.mp4": "落叶特写，无人",
    "english_autumn_park/06.mp4": "秋叶与天空，无人",
    "english_autumn_park/07.mp4": "枯枝与天空，无人",
    "english_autumn_park/08.mp4": "树叶缝隙天光，无人",
    "english_morning_mist": "整目录晨雾田野，无人无现代物件",
    "english_countryside_hills": "整目录乡野丘陵与树篱，无人无现代物件",
    "english_garden_flowers": "整目录花园花丛，无人",
    "english_roses_garden": "整目录玫瑰园，无人",
    "english_wooden_door_old": "整目录老木门，无人",
    "english_stone_wall_moss": "整目录苔石墙，无人",
    "english_lake_reflection": "整目录湖面倒影，无人",
    "english_country_house_manor/01.mp4": "都铎式砖砌门楼，无人无车辆",
    "english_country_house_manor/04.mp4": "航拍庄园宅邸与草坪，无人无车辆",
    "english_country_house_manor/05.mp4": "航拍英式村庄红瓦屋顶，无人",
    "english_country_house_manor/06.mp4": "半木构门房与木栅栏，无人",
    "english_sheer_curtain/01.mp4": "白纱帘与窗光，无人",
    "english_sheer_curtain/02.mp4": "白纱帘与窗光，无人",
    "english_sheer_curtain/03.mp4": "暖光窗帘，无人",
    "english_sheer_curtain/04.mp4": "纱帘光斑，无人",
    "english_sheer_curtain/05.mp4": "纱帘与窗外绿意，无人",
    "english_sheer_curtain/07.mp4": "亚麻窗帘特写，无人",
    "english_manor_window/02.mp4": "航拍庄园与绿地，无人",
    "english_manor_window/03.mp4": "规整花园与宅邸，无人",
    "english_manor_window/04.mp4": "窗与暖灯，无人",
    "english_manor_window/05.mp4": "窗光斜照白墙，无人",
    "english_golden_wheat_field_placeholder": "",
}

# 整目录级裁决（可疑比例≥50%的目录必须给结论）
DIR_ACCEPT = {
    "english_stone_cottage": "逐段复核后整目录可留：01 石砌农舍 / 03 林间溪流石岸 / 04 苔石墙 均为干净英式乡村镜头，"
                             "region 轴把它们误判为「非英国」；被 modern 轴判可疑的 05/06（航拍村落含车辆）已单段排除；"
                             "02（草坡绵羊）/07（绿野垄沟）门禁零命中",
}

# ---------- 汇总所有门禁报告的可疑项 ----------
gate_suspects = set()
for f in sorted(POOL.glob("_qc_*report*.json")) + sorted(POOL.glob("_qc_person_hits.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(d, dict):
        continue
    for k, v in d.items():
        hit = False
        if isinstance(v, dict):
            hit = (v.get("verdict") == "suspect") or bool(v.get("suspect")) or \
                  (isinstance(v.get("yes"), int) and v.get("yes", 0) > 0 and v.get("verdict") != "ok")
        elif isinstance(v, list):
            hit = len(v) > 0
        elif isinstance(v, (int, float)):
            hit = v > 0
        if hit:
            gate_suspects.add(SHORT(k))

excluded, decisions = set(), {}

for d, why in DIR_EXCLUDE.items():
    vdir = POOL / d / "video"
    for f in sorted(vdir.glob("*.mp4")) if vdir.is_dir() else []:
        excluded.add(f"{d}/{f.name}")
    decisions[d] = {"verdict": "exclude", "why": why}

for d, m in CLIP_EXCLUDE.items():
    for f, why in m.items():
        excluded.add(f"{d}/{f}")
        decisions[f"{d}/{f}"] = {"verdict": "exclude", "why": why}

for k, why in ACCEPT.items():
    if not why:
        continue
    decisions[k] = {"verdict": "accept", "why": why}

for d, why in DIR_ACCEPT.items():
    decisions[d] = {"verdict": "accept", "why": why}

# 门禁可疑但既未人工排除也未明确接受的 → 保守排除
for k in sorted(gate_suspects):
    if k in decisions or k in excluded:
        continue
    excluded.add(k)
    decisions[k] = {"verdict": "exclude", "why": "门禁判可疑且未通过目视确认（保守排除）"}

excl_list = sorted(excluded)
# 只保留磁盘上真实存在的条目（防 compose_book 的死条目护栏误伤）
on_disk = {f"{p.parent.parent.name}/{p.name}" for p in POOL.rglob("*.mp4")}
dead = [e for e in excl_list if e not in on_disk]
if dead:
    print("剔除不存在于磁盘的条目:", dead)
excl_list = [e for e in excl_list if e in on_disk]
for e in dead:                       # 台账同步清理
    decisions.pop(e, None)
(POOL.parent / "book_长日将尽_excluded.json").write_text(
    json.dumps(excl_list, ensure_ascii=False, indent=1), encoding="utf-8")
(POOL.parent / "book_长日将尽_qc_decisions.json").write_text(
    json.dumps(decisions, ensure_ascii=False, indent=1), encoding="utf-8")

total = len(list(POOL.rglob("*.mp4")))
alive = {}
for d in sorted(POOL.iterdir()):
    if not d.is_dir() or d.name.startswith("_"):
        continue
    vids = [f.name for f in sorted((d / "video").glob("*.mp4"))
            if f"{d.name}/{f.name}" not in excluded]
    if vids:
        alive[d.name] = vids
print("总段数", total, "| 排除", len(excl_list), "| 净可用", total - len(excl_list))
print("门禁可疑总数", len(gate_suspects), "| 存活目录", len(alive),
      "| 存活段", sum(len(v) for v in alive.values()))
for d, v in alive.items():
    print("   %-32s %2d 段  %s" % (d, len(v), " ".join(x[:2] for x in v)))
