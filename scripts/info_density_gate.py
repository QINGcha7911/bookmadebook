#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信息密度门禁（治「空洞」· 2026-09-25 立，v2）

判据：**每 90 秒口播（≈400 字）必须出现 ≥1 个具体细节**
具体细节 = 数字（阿拉伯/汉字数词/年份）/ 原文引号内容（「」“”）/ 具体量词短语（三口人、六亩地）
定位：**召回型**门禁 —— 报出「空白窗」交人复核，不做语义判定（避免误杀）。

⚠️ v1 的两个自埋 bug（2026-09-25 实跑抓到，务必别退回）：
  ① **口播量虚高**：只剥【…】外壳 ⇒ 留下「【画面：slug —— 明代老宅的两扇木门…】」里的
     **画面描述文字**被当口播 ⇒ 实测 2,838 字被算成 3,470 字（虚高 22%）✗
     ⇒ 修法：**含标注且去掉标注后汉字 ≤ 20 ⇒ 整行丢弃**（讲书稿的标注是独立整行）。
     例外：`【金句】「…」` **要念** ⇒ 保留引号内文字。
  ② **阴性对照假通过**：全文被剥空（0 窗）时判「达标率 0% ⇒ ✅」✗
     ⇒ 修法：**0 窗且口播 ≥100 汉字 ⇒ FAIL**（整篇没有一个具体细节 = 典型空洞）。

用法：
  python3 scripts/info_density_gate.py 讲书稿_XX.txt [--window 400] [--json out.json]
退出码：0 = 全窗达标 / 1 = 存在空白窗或整篇无细节 / 2 = 文件不可读或样本过短
"""
import argparse
import json
import re
import sys
from pathlib import Path

TAG_ANY = re.compile(r"【[^】]{0,80}】")
GOLD_LINE = re.compile(r"【金句】")
GOLD_INNER = re.compile(r"[「“]([^」”]{2,})[」”]")
MD_TITLE = re.compile(r"^\s*#{1,6}\s")
NAME_LIKE = re.compile(r"^[\x00-\x7f\s_\-/,.·—]*$")

NUM_AR = re.compile(r"\d")
NUM_CN = re.compile(r"[零一二三四五六七八九十百千万两]{1,4}(?:年|月|日|岁|人|口|亩|两|斤|里|块|件|次|个|天|万|亿|章|步|条|座|匹|头|位|道|本|文|贯|石|斗)")
YEAR = re.compile(r"(?:公元)?\d{3,4}\s*年")
QUOTE = re.compile(r"[「“][^」”]{2,}[」”]")

HAN = re.compile(r"[\u4e00-\u9fff]")


def han_len(s: str) -> int:
    return len(HAN.findall(s))


def spoken_text(raw: str) -> str:
    """抽出真正会被朗读的文本（v2：整行判定，不残留标注描述）"""
    out = []
    for line in raw.splitlines():
        if MD_TITLE.match(line):
            continue
        if TAG_ANY.search(line):
            if GOLD_LINE.search(line):                 # 金句：只留引号里的内容
                inner = "".join(GOLD_INNER.findall(line))
                if han_len(inner) >= 2:
                    out.append(inner)
                continue
            rest = TAG_ANY.sub("", line).strip()
            # 标注是独立整行 ⇒ 去掉标注后基本没剩口播 ⇒ 整行丢弃
            if han_len(rest) <= 20 or NAME_LIKE.match(rest):
                continue
            line = rest                               # 罕见：标注与口播同行 ⇒ 保留口播
        out.append(line)
    return re.sub(r"\s+", "", "".join(out))


def details_in(seg: str) -> list:
    d = []
    for m in YEAR.finditer(seg):
        d.append(m.group(0))
    for rx in (NUM_AR, NUM_CN, QUOTE):
        for m in rx.finditer(seg):
            d.append(m.group(0))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--window", type=int, default=400, help="窗口汉字数（400 ≈ 90 秒口播）")
    ap.add_argument("--json")
    a = ap.parse_args()

    p = Path(a.script)
    if not p.exists():
        print(f"✗ 文件不可读: {p}")
        return 2
    spoken = spoken_text(p.read_text(encoding="utf-8", errors="ignore"))
    total = han_len(spoken)
    if total < 100:
        print(f"⚠️ {p.name}: 口播仅 {total} 汉字 ⇒ 样本过短，不做判定（exit 2）")
        return 2

    W = a.window
    nw = total // W
    windows = [spoken[i * W:(i + 1) * W] for i in range(nw)]
    if spoken[nw * W:]:
        windows.append(spoken[nw * W:])
    empty = [(i + 1, w) for i, w in enumerate(windows) if not details_in(w)]

    mins = total / 4.4 / 60
    print(f"📊 {p.name}")
    print(f"   口播 {total} 字 ≈ {mins:.1f} 分钟 ｜ 窗口 {W} 字（≈90 秒）｜ 共 {len(windows)} 窗")
    print(f"   达标 {len(windows) - len(empty)} 窗 ｜ **空白窗 {len(empty)} 个**")
    for i, w in empty[:6]:
        print(f"     · 第{i}窗无具体细节：{w[:70]}…")
    if len(empty) == len(windows) and len(windows) >= 1:
        print("   ❌ 整篇没有一个具体细节（典型空洞）")
    ok = not empty
    print(f"   {'✅ 信息密度达标' if ok else '❌ 存在空洞窗，请补具体细节'}（空白窗 {len(empty)}/{len(windows)}）")
    if a.json:
        Path(a.json).write_text(json.dumps({
            "script": str(p), "口播汉字": total, "预估分钟": round(mins, 2),
            "窗口数": len(windows), "空白窗": [i for i, _ in empty],
            "达标": ok}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
