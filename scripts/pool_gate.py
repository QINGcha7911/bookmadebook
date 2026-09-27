#!/usr/bin/env python3
"""pool_gate.py —— 「常驻干净池台账」免费前置门禁库（只读，零 VL 调用）

用法（作为库）:
    import sys; sys.path.insert(0, "/root/.hermes/scripts")
    from pool_gate import PoolGate
    g = PoolGate()
    g.is_clean("ancient_armor_china/01.mp4")      # -> True / False
    g.verdict("abacus_wood/01.mp4")               # -> "face"
    g.clean_index()["ancient_armor_china"]        # -> ["01.mp4","02.mp4", ...] 确定性排序

设计口径（不砍判据、不改台账）:
  · 唯一权威 = `/mnt/d/AI软件/GitHub/bookmadebook/assets/scenes/pool_common_china/_qc_pool_certify.json`
    判据 pc-v6-20260926-noinfo-guard3-regionnorm1-fullnotes（flash 单跑 + 白名单守卫 + 地域归一化，32/32 对照背书）
  · 「干净」= verdict == "clean"。face / non_japan / modern 一律不得入选（fail-closed）。
  · **不在台账里的段一律视为不可用**（fail-closed）：池是按台账 1:1 建的（4740 段 ↔ 4740 条，实测零差集），
    不在台账 ⇒ 要么是池外旧素材、要么是新抓未体检素材 —— 两者都没过判据，不得入片。
  · 本库**绝不**写台账、池文件或仓库任何文件。
"""
import json
import os
import re
from pathlib import Path

REPO = Path("/mnt/d/AI软件/GitHub/bookmadebook")
DEFAULT_POOL = REPO / "assets" / "scenes" / "pool_common_china"
DEFAULT_LEDGER = DEFAULT_POOL / "_qc_pool_certify.json"
DEFAULT_CLEAN = DEFAULT_POOL / "_clean_clips_v6guard.json"

BAD_VERDICTS = ("face", "non_japan", "modern")


def norm_key(key: str) -> str:
    """把 `<目录>/<文件名>` 与 `<目录>/video/<文件名>` 归一成 `<目录>/video/<文件名>`。

    池的物理布局是 `<目录>/video/<文件名>.mp4`，台账键同此格式。
    """
    key = key.replace("\\", "/").lstrip("./")
    if "/video/" not in key:
        parts = key.rsplit("/", 1)
        if len(parts) == 2:
            key = f"{parts[0]}/video/{parts[1]}"
    return key


def short_key(key: str) -> str:
    """归一成仓库惯用的短格式 `<目录>/<文件名>`（排除清单用这个）。"""
    return norm_key(key).replace("/video/", "/")


def _name_sort_key(name: str):
    """确定性文件名排序：先数字主干升序，再整名——保证「可复现」而非随机。"""
    stem = re.sub(r"\.mp4$", "", name, flags=re.I)
    m = re.match(r"^(\d+)$", stem)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


class PoolGate:
    def __init__(self, ledger_path=DEFAULT_LEDGER, clean_path=DEFAULT_CLEAN, pool_dir=DEFAULT_POOL):
        self.pool_dir = Path(pool_dir)
        self.ledger_path = Path(ledger_path)
        self.clean_path = Path(clean_path)
        with open(self.ledger_path, encoding="utf-8") as f:
            self.ledger = json.load(f)                       # {相对路径: 判定条目}
        if self.clean_path.exists():
            with open(self.clean_path, encoding="utf-8") as f:
                self.clean_list = json.load(f)               # [相对路径, ...]
        else:
            self.clean_list = [k for k, v in self.ledger.items() if v.get("verdict") == "clean"]
        self._clean_set = {norm_key(k) for k in self.clean_list}
        self._idx = None

    # ── 判定 ─────────────────────────────────────────────────────────────
    def entry(self, key: str):
        return self.ledger.get(norm_key(key))

    def verdict(self, key: str) -> str:
        e = self.entry(key)
        if e is None:
            return "not_in_ledger"
        v = e.get("verdict")
        if v is None:
            return "no_verdict"
        if e.get("bad", {}).get("invariant_ok") is False:
            return "invariant_broken"                        # 台账自检不变量破 ⇒ fail-closed
        return v

    def is_clean(self, key: str) -> bool:
        k = norm_key(key)
        return k in self._clean_set and self.verdict(k) == "clean"

    def bad_axes(self, key: str):
        e = self.entry(key)
        if not e:
            return {}
        b = e.get("bad", {}) or {}
        return {a: b.get(a) for a in BAD_VERDICTS if b.get(a)}

    def exists_on_disk(self, key: str) -> bool:
        return (self.pool_dir / norm_key(key)).exists()

    # ── 索引 ─────────────────────────────────────────────────────────────
    def clean_index(self):
        """{目录: [干净文件名, ...]}，目录与文件名均确定性排序。"""
        if self._idx is None:
            idx = {}
            for k in self._clean_set:
                if self.verdict(k) != "clean":
                    continue                                  # 台账不变量破的不进索引
                d, name = k.split("/video/", 1)
                idx.setdefault(d, []).append(name)
            for d in idx:
                idx[d].sort(key=_name_sort_key)
            self._idx = dict(sorted(idx.items()))
        return self._idx

    def clean_clips_of_dir(self, d: str):
        return list(self.clean_index().get(d, []))

    def next_clean(self, d: str, after: str = None, used=None):
        """目录 d 内、按确定性顺序取下一个干净段；跳过 used；after 指定则从其后开始。

        返回 `目录/文件名`（短格式）或 None（该目录已无可用干净段）。
        """
        used_s = {short_key(u) for u in (used or [])}
        names = self.clean_clips_of_dir(d)
        if not names:
            return None
        start = 0
        if after:
            a = after.split("/")[-1]
            if a in names:
                start = names.index(a) + 1
        for name in names[start:] + names[:start]:
            k = f"{d}/{name}"
            if k not in used_s:
                return k
        return None

    # ── 统计 ─────────────────────────────────────────────────────────────
    def stats(self):
        vc = {}
        for v in self.ledger.values():
            vc[v.get("verdict")] = vc.get(v.get("verdict"), 0) + 1
        return {"ledger_entries": len(self.ledger),
                "clean_list_len": len(self.clean_list),
                "clean_set_len": len(self._clean_set),
                "verdict_dist": vc,
                "dirs_with_clean": len(self.clean_index())}

    def filter_available(self, avail: dict, verify_disk=True):
        """把 scene_map 的 available（{目录: [文件名]}）过滤成「台账 clean 白名单」。

        返回 (filtered, report)：
          filtered = {目录: [文件名...]}          # 全部 verdict==clean
          report   = {blocked: [...], kept: N, dirs_dropped: [...], per_dir: {...}}
        """
        filtered, blocked, dropped, per_dir = {}, [], [], {}
        for d in sorted(avail):
            names = avail[d] or []
            keeps, drops = [], []
            for n in names:
                k = f"{d}/video/{n}"
                if not self.entry(k):
                    drops.append((n, "not_in_ledger"))
                    continue
                v = self.verdict(k)
                if v != "clean":
                    drops.append((n, v))
                    continue
                if verify_disk and not self.exists_on_disk(k):
                    drops.append((n, "missing_on_disk"))
                    continue
                keeps.append(n)
            keeps.sort(key=_name_sort_key)
            per_dir[d] = {"in": len(names), "kept": len(keeps), "dropped": len(drops)}
            for n, why in drops:
                blocked.append({"key": f"{d}/{n}", "verdict": why})
            if keeps:
                filtered[d] = keeps
            else:
                dropped.append(d)
        report = {"kept": sum(len(v) for v in filtered.values()),
                  "blocked": blocked, "blocked_count": len(blocked),
                  "dirs_kept": len(filtered), "dirs_dropped": dropped,
                  "per_dir": per_dir}
        return filtered, report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="常驻池台账自检")
    ap.add_argument("--key", help="查一段的判定，如 ancient_armor_china/01.mp4")
    a = ap.parse_args()
    g = PoolGate()
    print(json.dumps(g.stats(), ensure_ascii=False, indent=1))
    if a.key:
        k = norm_key(a.key)
        print(f"{k}: verdict={g.verdict(k)} clean={g.is_clean(k)} bad={g.bad_axes(k)} on_disk={g.exists_on_disk(k)}")
