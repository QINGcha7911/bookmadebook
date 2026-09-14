#!/usr/bin/env python3
"""
门禁裁决校验器（2026-09-14 立，《大医》欧式老巷事故的根治件）

事故根因：门禁把 `old_alley_china` 6 段里 5 段报成 suspect（3/3 全票），
**但没人裁决、没进排除清单**，于是照用不误，成片里出现了 2 次欧式石阶老巷。
→ 问题不是"门禁没抓到"，是"抓到了没人判"。本脚本把"必须裁决"变成机制：

用法：
    python3 scripts/qc_gate_audit.py assets/scenes/book_<书名>
    python3 scripts/qc_gate_audit.py assets/scenes/book_<书名> --strict   # 备用

退出码：
    0 = 所有可疑项都已裁决（排除 or 明确接受）
    1 = 存在未裁决可疑项 / 整目录可疑但无目录级裁决  ← 生产班据此拒交

裁决台账（人工写，与排除清单分开，留理由可审计）：
    assets/scenes/book_<书名>_qc_decisions.json
    {
      "old_alley_china":          {"verdict": "exclude", "why": "整目录欧式石阶老巷，地域不符"},
      "steam_train/02.mp4":       {"verdict": "accept",  "why": "民国蒸汽机车+电力线，时代相符"},
      "tcm_herbs/03.mp4":         {"verdict": "accept",  "why": "黄底草药静物，虽有商品照感但内容贴题"}
    }
    键支持三种粒度：`<目录>`（整目录）、`<目录>/<文件>`（单段）。排除清单仍是短格式。

判读铁律（脚本强制）：
  ① 每一条 suspect 都必须有归宿：进排除清单，或在台账里写明"接受+理由"。
  ② **目录级裁决**：某目录被任一轴判可疑的比例 ≥ 阈值（默认 50%），
     就必须给"整目录"结论 —— 因为"目录名不可信"是反复踩到的坑
     （old_alley_china=欧式、snow_landscape=汽车、winter_village_china=欧式村落、
       river_boat_mist=现代小艇、calligraphy_ink=真人手）。
"""
import json, sys, argparse
from pathlib import Path
from collections import defaultdict

DEF_DIR_RATIO = 0.5


def load_suspects(pool: Path):
    """汇总所有门禁报告的可疑项 → {(目录, 文件名): [命中的轴...]}"""
    sus = defaultdict(set)
    src = {}
    for f in sorted(pool.glob("_qc_*report*.json")) + sorted(pool.glob("_qc_person_hits.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        axis = f.stem.replace("_qc_", "").replace("_report", "").replace("_hits", "")
        items = d.items() if isinstance(d, dict) else []
        for k, v in items:
            hit = False
            if isinstance(v, dict):
                hit = (v.get("verdict") == "suspect") or bool(v.get("suspect")) \
                      or (v.get("yes", 0) > 0 and v.get("verdict") != "ok")
            elif isinstance(v, (int, float)):
                hit = v > 0
            elif isinstance(v, list):
                hit = len(v) > 0
            if not hit:
                continue
            parts = [x for x in str(k).replace("\\", "/").split("/") if x]
            # 归一到 <目录>/<文件>
            if len(parts) >= 3 and parts[-2] == "video":
                key = f"{parts[-3]}/{parts[-1]}"
            elif len(parts) >= 2:
                key = f"{parts[-2]}/{parts[-1]}"
            else:
                key = str(k)
            sus[key].add(axis)
            src.setdefault(key, f.name)
    return sus, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pool", help="素材池目录，如 assets/scenes/book_大医")
    ap.add_argument("--exclude", default=None, help="排除清单（默认 <pool>_excluded.json）")
    ap.add_argument("--decisions", default=None, help="裁决台账（默认 <pool>_qc_decisions.json）")
    ap.add_argument("--dir-ratio", type=float, default=DEF_DIR_RATIO)
    a = ap.parse_args()

    pool = Path(a.pool)
    if not pool.is_dir():
        print(f"❌ 池子不存在：{pool}"); return 2
    ex_path = Path(a.exclude) if a.exclude else pool.with_name(pool.name + "_excluded.json")
    dc_path = Path(a.decisions) if a.decisions else pool.with_name(pool.name + "_qc_decisions.json")

    excl = set()
    if ex_path.exists():
        for x in json.load(open(ex_path, encoding="utf-8")):
            p = [s for s in str(x).replace("\\", "/").split("/") if s]
            excl.add("/".join(p[-2:]) if len(p) >= 2 else str(x))
    decisions = json.load(open(dc_path, encoding="utf-8")) if dc_path.exists() else {}

    sus, src = load_suspects(pool)
    if not sus:
        print(f"✅ 未发现任何门禁报告的可疑项（{pool}）"); return 0

    # 目录统计
    per_dir = defaultdict(lambda: {"total": 0, "sus": 0, "axes": set()})
    for key, axes in sus.items():
        d_ = key.split("/")[0]
        per_dir[d_]["total"] += 1
        per_dir[d_]["sus"] += 1
        per_dir[d_]["axes"] |= axes
    for d_ in per_dir:
        n = len(list((pool / d_ / "video").glob("*.mp4"))) if (pool / d_ / "video").is_dir() else per_dir[d_]["total"]
        per_dir[d_]["pool_n"] = max(n, per_dir[d_]["total"])

    unadj_clip, unadj_dir, accepted = [], [], 0
    for key, axes in sorted(sus.items()):
        d_ = key.split("/")[0]
        if key in excl:
            continue
        if key in decisions or d_ in decisions:
            _dec = decisions.get(key) or decisions.get(d_) or {}
            if _dec.get("verdict") == "exclude":
                print(f"  ⚠️ 台账判 exclude 但未写进排除清单：{key}")
            accepted += 1
            continue
        unadj_clip.append((key, sorted(axes), src.get(key, "")))

    for d_, st in sorted(per_dir.items()):
        ratio = st["sus"] / max(st["pool_n"], 1)
        if ratio < a.dir_ratio or d_ in decisions:
            continue
        # 整个目录的可疑段都已在排除清单里 = 目录已彻底处理，不再要求目录级裁决
        d_sus = [k for k in sus if k.split("/")[0] == d_]
        if d_sus and all(k in excl for k in d_sus):
            continue
        unadj_dir.append((d_, st["sus"], st["pool_n"], round(ratio, 2), sorted(st["axes"])))

    print(f"=== 门禁裁决校验：{pool.name} ===")
    print(f"可疑素材 {len(sus)} 段 | 已在排除清单 {len([k for k in sus if k in excl])} 段 | "
          f"已裁决接受 {accepted} 段")
    if unadj_dir:
        print(f"\n❌ 整目录可疑但无目录级裁决（{len(unadj_dir)} 个目录）—— 目录名不可信，必须给"
              f"「整目录排除」或「整目录接受+理由」：")
        for d_, s, n, r, ax in unadj_dir:
            print(f"   • {d_:28s} 可疑 {s}/{n}（{r:.0%}）  轴: {','.join(ax)}")
    if unadj_clip:
        print(f"\n❌ 未裁决可疑项 {len(unadj_clip)} 段（既不在排除清单、台账里也没结论）：")
        for k, ax, s in unadj_clip[:40]:
            print(f"   • {k:44s} 轴: {','.join(ax):24s} ({s})")
        if len(unadj_clip) > 40:
            print(f"   ... 另有 {len(unadj_clip)-40} 段")

    if unadj_clip or unadj_dir:
        print(f"\n📌 处理方式：逐格人工放大裁决 → 可疑的写进 {ex_path.name}（短格式），"
              f"判定可接受的写进 {dc_path.name}（附理由）")
        return 1
    print("\n✅ 所有可疑项均已裁决")
    return 0


if __name__ == "__main__":
    sys.exit(main())
