#!/usr/bin/env python3
"""《长日将尽》讲书稿落盘 v2 —— 从 004 原始 card 重新清洗（只剔控制字符，保留全角标点）
并修正：章节重复、死场景标注、不完整金句、尾部流程元信息
"""
import re
from pathlib import Path

RAW = Path("/root/004_changri_raw.txt")
t = RAW.read_text(encoding="utf-8", errors="ignore")
# 只剔 C0 控制字符（保留全角标点 0xFF0C/0xFF1A/0xFF08 等）
t = "".join(ch for ch in t if ch == "\n" or ch == "\t" or ord(ch) >= 32)
t = t.replace("<card>", "").replace("</card>", "")
t = re.sub(r"^\s*收到，17:00前交稿。场景池已更新，直接开始写。\s*---\s*", "", t)
# 去掉尾部流程元信息
m = re.search(r"---\s*\*\*交稿", t)
if m:
    t = t[:m.start()]
t = re.sub(r"\n{3,}", "\n\n", t).strip()

# ---- 还原换行：把被 card 压平的内容重新分行 ----
# 1) 标题：把 "# 第X章 标题## 第X章 标题" 这种重复压平为一行
t = re.sub(r"(#{1,3}\s*第[一二三四五六七八九十]+章[^\n#]*?)(#{1,3}\s*第[一二三四五六七八九十]+章[^\n#【]*?)(?=【|\n)", r"\1", t)
t = re.sub(r"(#{1,3}\s*尾声[^\n#]*?)(#{1,3}\s*尾声[^\n#【]*?)(?=【|\n)", r"\1", t)
# 2) 标注前换行
t = re.sub(r"(?<!\n)(#{1,3}\s*第[一二三四五六七八九十]+章)", r"\n\n\1", t)
t = re.sub(r"(?<!\n)(#{1,3}\s*尾声)", r"\n\n\1", t)
t = re.sub(r"(?<!\n)(【画面)", r"\n\1", t)
t = re.sub(r"(?<!\n)(【情绪)", r"\n\1", t)
t = re.sub(r"(?<!\n)(【金句)", r"\n\1", t)
# 3) 标注行内部：】后接正文 → 断行；【金句】后的「…」独占一行
t = re.sub(r"(【[^】]*】)(?=[^\n])", r"\1\n", t)
t = re.sub(r"(【金句】)\s*\n?(「[^」]*」)", r"\1\n\2", t)
# 4) 章标题后接正文 → 断行
t = re.sub(r"(#{1,3}\s*第[一二三四五六七八九十]+章[^\n]{2,40}?)(?=【)", r"\1\n", t)
t = re.sub(r"\n{3,}", "\n\n", t)
lines = [l.strip() for l in t.split("\n")]
lines = [l for l in lines if l]
t = "\n".join(lines)

# ---- 修正：死场景标注 → 存活场景（附更具体的中文描述）----
FIX = {
 "【画面：old_english_library —— 老式书房，墙上书架摆满书，壁炉台上放着一只老座钟，指针停在某个时间】":
 "【画面：english_stately_home_hall —— 宅邸门厅，午后的斜光落在大理石地面上，楼梯口的墙上挂着一只老座钟，指针停在某个时间】",
 "【画面：english_manor_staircase —— 宅邸楼梯间，木质扶手擦得锃亮，楼梯转角处一只旧皮鞋放在地上】":
 "【画面：english_stately_home_hall —— 宅邸楼梯转角，木质扶手擦得锃亮，一级台阶上放着一只擦好的旧皮鞋】",
 "【画面：english_formal_dining —— 正式餐厅长桌，银质餐具摆得整齐，椅子空着，墙上挂着一幅画像，光线从侧面打下来】":
 "【画面：english_candle_dinner —— 烛光晚餐桌，长桌尽头一只酒杯还剩半杯，椅子空着，光从侧面斜打过来】",
 "【画面：english_writing_desk —— 老写字台上摊着一叠信纸，旁边是一支钢笔和一只墨水瓶，窗帘半掩】":
 "【画面：rain_window_glass —— 雨点打在窗玻璃上往下淌，窗台边摊着一叠信纸，纸角被风掀起】",
 "【画面：vintage_car_country_road —— 乡间小路上停着一辆黑色老爷车，车身上沾着晨露，远处是灰绿色的丘陵】":
 "【画面：english_country_lane —— 清晨的乡间砾石小路，两侧是树篱，远处是灰绿色的丘陵，路面还带着露水】",
 "【画面：english_harbour_boats —— 港口里停着几艘木渔船，船身随着海浪轻轻起伏，远处是灰蓝色的海平线】":
 "【画面：english_lake_reflection —— 平静的水面倒映着黄昏的天空，岸边系着一条空着的小船】",
 "【画面：english_seaside_pier —— 海滨栈桥尽头，栏杆上放着一顶旧帽子，远处是黄昏的海面】":
 "【画面：english_morning_mist —— 水边的雾里，一段旧木栏杆，栏杆上放着一顶旧帽子，远处水面一片灰蓝】",
}
for a, b in FIX.items():
    if a in t:
        t = t.replace(a, b)
    else:
        # 容错：按目录名替换
        key = a.split("——")[0].replace("【画面：", "").strip()
        t = re.sub(r"【画面：" + re.escape(key) + r"[^】]*】", b, t)

# ---- 修正：不完整金句 → 资料包原文完整版 ----
t = t.replace("「无论何时何地都能坚守其职业生命」",
              "「尊严云云，其至关紧要的一点即在于，一位管家无论何时何地都能坚守其职业生命的能力。」")

# ---- 修正：父亲之死的事实口径（资料包原文）----
t = t.replace("父亲去世那天，楼下在办宴会。他选择不下楼。",
              "父亲中风垂危那天，楼下正在办一场重要的宴会。他选择不离开岗位。")
t = t.replace("父亲去世那天楼下在办宴会。他选择不下楼。",
              "父亲中风垂危那天，楼下正在办一场重要的宴会。他选择不离开岗位。")

Path("bookmadebook-output/讲书稿_长日将尽.txt").write_text(t.strip() + "\n", encoding="utf-8")
body = re.sub(r"【[^】]*】", "", t)
print("长度", len(t), "| 正文净字", len(re.sub(r"\s", "", body)))
print("【金句】", t.count("【金句】"), "| 【画面】", t.count("【画面"),
      "| 【情绪】", t.count("【情绪"), "| 章", len(re.findall(r"^#{1,3}\s*第", t, re.M)),
      "| 尾声", t.count("尾声"))
print("死场景残留:", [d for d in ["old_english_library","english_manor_staircase","english_formal_dining",
      "english_writing_desk","vintage_car_country_road","english_harbour_boats","english_seaside_pier"]
      if d in t])
print("尾 3 行:", "\n".join(t.split("\n")[-3:]))
