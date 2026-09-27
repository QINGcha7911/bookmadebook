#!/usr/bin/env python3
"""《深夜食堂》单跑合成包装器（不改 scripts/ 受管文件）

为什么要包装：
1) compose_scene_map.split_chapters() 按【画面】标记组切章，本稿 18 组 ≠ scene_map 8 章
   → 直接退出。本稿 8 个 `#` 标题与 scene_map 8 章严格一一对应，改按标题切章。
2) compose_scene_map 的章节卡标题由 scene_map 标签派生（"第{k+1}章 + name"），
   本稿标签本身已是「第一章 红香肠与玉子烧」，会派生出「第二章 第一章 …」重名
   → 这里直接用标签，第 0 章（书名章）给「开场：<书名>」→ 渲染成「序章 / 书名」。
3) video_composer._fallback_chapter_times 按「含标记的全文字符比例」估算章节卡时间，
   本稿标记行占比高，实测比真实朗读位置早最多 18.5s（芒果街同类错位）
   → 补丁为「朗读字符比例」，与 pick_items 的章节时间窗同源。

用法：
  python3 /tmp/audit005/compose_deep.py --audio ... --output ... [--dry-run]
"""
import argparse
import contextlib
import json
import os
import re
import subprocess
from collections import defaultdict
import sys
import tempfile
from pathlib import Path

REPO = Path("/mnt/d/AI软件/GitHub/bookmadebook")
sys.path.insert(0, str(REPO / "scripts"))

import compose_scene_map as C           # noqa: E402
import video_composer as VC             # noqa: E402
import scene_selector                   # noqa: E402

MARKER_LINE = re.compile(r"^\s*【[^】]+】\s*$")


def _excl_key(s) -> str:
    """排除清单键归一化：`<目录>/video/<文件>` 与 `<目录>/<文件>` 视为同一段 → 统一成 `<目录>/<文件>`。

    ⚠️ 2026-09-14《大医》事故根因：`qc_clip_scan.py` 用 `relative_to(ROOT)` 输出
    `<目录>/video/<文件>`（长格式），而本文件按 `<目录>/<文件>`（短格式）匹配
    → 130 条排除**全部匹配不上、长期空转**，dry-run 报「命中排除清单 0 段」= **假通过**，
    三段脏素材（真人手 / 手指 / 现代汽车）因此进了正片。
    教训：**排除清单"命中 0 段"不等于"干净"**，必须同时报告"有多少条匹配不上任何素材"。
    """
    parts = [p for p in str(s).replace("\\", "/").split("/") if p]
    if len(parts) >= 2 and parts[-2] == "video":
        parts = parts[:-2] + [parts[-1]]      # 去掉中间的 video/ 层
    return "/".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else "")


def crosscheck_playlists(avail, sm_excluded, sm_excluded_count=None, raw_exclude=None) -> dict:
    """compose 前的**清单交叉校验**（2026-09-21 深夜 007 裁决 ②，排在次日 6:15 前）。

    两份清单**不能各自手工维护**：`scene_map.json`（备稿班体检快照：available + 自带
    excluded）与 `_excluded.json`（操作侧黑名单，随人工复核不断加严）。这里对一遍，
    不一致就打醒目告警并列出差异 —— **绝不静默**。

    为什么必须有（本片实锤）：`nomad_tent/07.mp4`（法国国旗 + 真人正脸）**既在** scene_map
    的 available 里、**又已进**操作侧排除清单，而快照自己的 excluded 还漏了它 → 只要有人
    不传 `--exclude`（或别的工具直接读 available），这段就会进片。

    语义（007 认定）：**不做「由 excluded 派生 scene_map」** —— 快照有它自己的时点语义，
    派生会破坏语义；**校验 + 报警**才是正解。

    四个告警类别（严重度据**「本工具只读 available、不读快照自带 excluded」**这一事实定）：
      🔴 A 自相矛盾：同一段既在 available 又在快照 excluded → 不传 --exclude 必进片
      🔴 B 保护缺口：快照 excluded 有、操作侧 --exclude 没有 → **当前无人拦**，会进片
      ⚠️ C 快照落后：操作侧已排除、快照仍列为 available → 本次已拦（不进片），
            但**任何不传 --exclude 的运行都会放它进来**（今晚 07 即此类）
      ℹ️ D 孤立加严：只在操作侧清单里（正常，人工可加严，快照不必同步）
    """
    avail_set = {_excl_key(f"{d}/{f}") for d, files in (avail or {}).items() for f in (files or [])}
    snap = {_excl_key(x) for x in (sm_excluded or [])}
    ops = {_excl_key(x) for x in (raw_exclude or [])}
    a_contradict = sorted(avail_set & snap)
    b_unprotected = sorted(snap - ops) if ops else []   # 不传 --exclude 时无从对账（见上方专用告警）
    c_stale = sorted(avail_set & ops)
    d_ops_only = sorted(ops - snap - avail_set)
    n_mismatch = (sm_excluded_count is not None and sm_excluded_count != len(snap))

    print(f"🔎 排除清单交叉校验（操作侧 --exclude ↔ scene_map 快照）：available {len(avail_set)} 段 ｜ "
          f"快照 excluded {len(snap)} 条 ｜ 操作侧排除 {len(ops)} 条")
    if not ops:
        print(f"  🚨 未传 --exclude：本工具**不读** scene_map 自带的 excluded 字段 → 等于"
              f"**零排除**（available {len(avail_set)} 段全部可选）。清单里若有正脸/污染段，"
              f"请务必传 --exclude，否则必进片。")
    if a_contradict:
        print(f"  🔴 A 自相矛盾 {len(a_contradict)} 条：同一段既在 available 又在快照 excluded "
              f"（本工具只读 available → 不传 --exclude 必进片）：{a_contradict[:5]}"
              f"{' …' if len(a_contradict) > 5 else ''}")
    if ops and b_unprotected:
        print(f"  🔴 B 保护缺口 {len(b_unprotected)} 条：快照排了、操作侧 --exclude 里没有 "
              f"→ **当前无人拦**，会被选进片：{b_unprotected[:5]}"
              f"{' …' if len(b_unprotected) > 5 else ''}")
    if c_stale:
        print(f"  ⚠️ C 快照落后 {len(c_stale)} 条：已被排除、快照仍列为 available "
              f"（本次 --exclude 已拦住、**不进片**；但不传 --exclude 的跑法会放它们进来，"
              f"请备稿班同步快照）：{c_stale[:5]}{' …' if len(c_stale) > 5 else ''}")
    if ops and d_ops_only:
        print(f"  ℹ️ D 孤立加严 {len(d_ops_only)} 条：只在操作侧清单里（正常，快照不必同步）："
              f"{d_ops_only[:5]}{' …' if len(d_ops_only) > 5 else ''}")
    if n_mismatch:
        print(f"  ⚠️ scene_map.excluded_count = {sm_excluded_count} ≠ excluded 实际 "
              f"{len(snap)} 条（字段没跟上，请一并修）")
    if not a_contradict and not (ops and b_unprotected):
        print("  ✅ 零硬冲突：没有「必进片」的清单打架（A/B 均 0）")
    return {"contradict": a_contradict, "unprotected": b_unprotected, "stale_snapshot": c_stale,
            "ops_only": d_ops_only, "count_mismatch": bool(n_mismatch)}


# 金句长度 / 条数上限 —— 2026-09-21 由 007 裁决（「上限放宽」+「超限必须报警」两条同时做）。
# **上限不是拍脑袋定的，是按金句卡竖向容量反推的**：
#   · 单卡容量：text_layers._quote_line_layout() 实测 —— fs=56（>24 字用）单卡 **5 行**；fs=64（≤24 字）4 行；
#   · 最坏换行密度：wrap_by_px(max_width=640) 下 6 字语义单元恰好 1 单元/行 ⇒ 约 **6 字/行**；
#   · 56 字在该密度下 = **9 行 → 拆卡 [5,4] = 2 张**（已枚举单元 3–12 字，9 行即最坏）
#     ⇒ 上限 56 字保证**最多 2 张卡、绝不出现第 3 张**，且单卡仍守 5 行硬约束。
# 修复背景（比"卡内丢一行"更严重）：拆卡治好了"卡内丢字"，但原 `4 <= len(q) <= 40`
#   会让**整条金句凭空消失、连卡都不出、作者零感知** ✗ → 故上限放宽 + 一律报警。
# 2026-09-25（007 裁决，随「时长按书本体量定稿量」新规）：条数上限 6 → **7**，与
#   check_script_quality 的 ≥13 分钟档（5-7 金句）对齐 —— 旧值 6 会让长篇档 7 条稿
#   **丢掉最后一条**（《张居正大传》：尾声 bookend「恩怨尽时方论定，封疆危日见才难」
#   被静默丢弃，而稿面「留着两句题诗——」的铺垫会悬空 ✗）。
#   7 张卡铺在 14 分钟片 = 1 张/2 分钟，节奏正常；长度上限 56 字不变。
QUOTE_MAX_CHARS = 56
QUOTE_MAX_CARDS = 7


def extract_quotes_full(script_text: str) -> list:
    """金句字卡文本：取【金句】「…」引号内**完整**内容（不按句号截断）。

    video_composer.extract_quotes 会在第一个 。！？ 处截断，本稿两处金句是
    一问一答（"…有没有维也纳香肠？老板问：要不要切成章鱼形状？"）、
    以及收尾反问（"…会不会有客人来？喔，还不少喔！"），截断后只剩提问半句，
    字卡会看得莫名其妙。这里保留完整引文。

    **2026-09-21（007 裁决）：长度上限 40 → 56 字（按单卡容量反推，见 QUOTE_MAX_CHARS）；
    且超限/过短/条数封顶/标注行解析失败一律打印 🚨 告警，绝不静默丢弃。**
    """
    out, dropped = [], []
    n_tags = 0
    # 2026-09-14：外层量词 {8,120} 也会把「禁止期待」（含引号 6 字符）整条挡掉 → 放宽到 4
    for m in re.finditer(r"【金句】\s*([^【】\n]{4,120})", script_text):
        n_tags += 1
        q = m.group(1).strip()
        inner = re.findall(r"「([^「」]{4,80})」", q)
        if inner:
            q = inner[-1]
        q = q.strip().strip("「」\"")
        if q in out:
            continue                        # 重复句：既有语义，静默去重
        # 2026-09-14 修：《老师的提包》「禁止期待」是 4 字金句（正文还专门点明
        # 「反复提醒自己四个字：禁止期待」），原下限 6 会把它静默丢弃 → 5 金句只出 4 张卡。
        # 放宽到 4 字（作者已用【金句】标记，短句更该出卡）。
        if not (4 <= len(q) <= QUOTE_MAX_CHARS):
            dropped.append((len(q), q))
            continue
        out.append(q)

    # ① 单条超限 / 过短 → 报警（本轮修复核心：原来整条静默消失、作者零感知）
    for n, q in dropped:
        why = (f"超上限（{n} 字 > {QUOTE_MAX_CHARS} 字）" if n > QUOTE_MAX_CHARS
               else f"过短（{n} 字 < 4 字）")
        print(f"  🚨 金句告警·{why} → **该条已丢弃、不会出卡**："
              f"{q[:20]}{'…' if len(q) > 20 else ''}")
    # ② 条数封顶 → 报警（原来 out[:6] 把第 7 条默默砍掉）
    if len(out) > QUOTE_MAX_CARDS:
        print(f"  🚨 金句告警·条数 {len(out)} 超上限 {QUOTE_MAX_CARDS} → 只出前 {QUOTE_MAX_CARDS} 张，"
              f"**丢弃**：{[x[:12] for x in out[QUOTE_MAX_CARDS:]]}")
        out = out[:QUOTE_MAX_CARDS]
    # ③ 标注行没能解析出文本（如整行 >120 字被外层正则挡住）→ 报警
    total_tags = len(re.findall(r"【金句】", script_text))
    if total_tags > n_tags:
        print(f"  🚨 金句告警·有 {total_tags - n_tags} 处【金句】标注未能解析出文本"
              f"（可能整行过长或格式异常），**未出卡**")
    return out


def make_quote_times(composer_text: str, audio_dur: float, quotes: list):
    """金句时间轴：与章节卡同源（朗读字符比例），替换 video_composer._quote_times。

    video_composer 默认按「含【画面】标记的全文字符位置」比例映射。本稿标记行
    占全文 49%，实测把第 3 句金句排到 504s（真实朗读 515s，早 10.5s）。
    改用朗读字符比例后与 faster-whisper 转写实测对齐（误差 ≤2s）：
      q1 朗读 173.8s / q2 472.8s / q3 514.8s / q4 574.6s。
    首句 ≤12s 的留存规则（007 定，2026-09-07 芒果街复核确认保留）照旧生效。
    """
    clines = composer_text.splitlines()
    cjk = [0 if (MARKER_LINE.match(l) or l.lstrip().startswith("#"))
           else len(re.findall(r"[\u4e00-\u9fff]", l)) for l in clines]
    pre, acc = [0], 0
    for c in cjk:
        acc += c
        pre.append(acc)
    tot = max(pre[-1], 1)
    out = []
    for qi, q in enumerate(quotes):
        key = q.strip("「」 ")[:12]
        idx = next((i for i, l in enumerate(clines) if key and key in l), -1)
        t = audio_dur * pre[idx] / tot if idx >= 0 else audio_dur * qi / max(len(quotes), 1)
        if qi == 0:
            t = min(t, 12.0)          # 首句金句 ≤12s（留存关键区）
        out.append(t)
    return out


def md5_of(path: str) -> str:
    import hashlib
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ── 感知签名去重（005 补，2026-09-13）──────────────────────────────────────
# 素材库里同一段 Pexels 视频被不同关键词重复入库，被 007 分别命名到不同目录，
# 文件 md5 不同（转码/裁切不同）但画面几乎一致；仅靠 md5 去重会漏。
# 实测：同源同段「32x57 灰度均值缩略」L1 距离 = 0，非同源最小 25 → 阈值 5 安全。
_LOWCACHE = {}
# 同源判定阈值（感知签名 L1 距离）。2026-09-19 从 005 运行时补丁回移仓库；可用环境变量覆盖。
SIG_THRESH = float(__import__("os").environ.get("QY_SIG_THRESH", "5.0"))
def low_sig(path, win_extra=1.6):
    """clip 可见窗口(0 ~ dur+xfade)内 4 帧的 32x57 灰度均值缩略图。"""
    import numpy as _np, cv2 as _cv2
    if path in _LOWCACHE:
        return _LOWCACHE[path]
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout or 0)
    end = min(max(dur - 0.25, 1.0), 8.0 + win_extra)
    cap = _cv2.VideoCapture(path); acc = None; n = 0
    for t in _np.linspace(0.2, end, 4):
        cap.set(_cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        g = _cv2.cvtColor(_cv2.resize(fr, (57, 32)), _cv2.COLOR_BGR2GRAY).astype(_np.float32)
        acc = g if acc is None else acc + g
        n += 1
    cap.release()
    sig = (acc / n) if n else _np.zeros((32, 57), _np.float32)
    _LOWCACHE[path] = sig
    return sig


def sig_dist(a, b):
    import numpy as _np
    return float(_np.abs(a - b).mean())


# ══════════════════════════════════════════════════════════════════════════════
# 目录级全局唯一分配（两段式最大流）—— 2026-09-19 由 005 运行时补丁回移仓库
#   原 pick_items_dedup 用「迭代排除 + 20% 护栏」逼近零复用：池交集大时必然残留
#   （《一个人的好天气》v2b 就出现同一条片被排进 Ch1 与 Ch3；根因是护栏一到 20% 就
#   「停止去重、保留当前选材」= 静默放行重复）。
#   本实现把它建模成运输问题：目录 d 供给 supply[d]，章 k 需 n_k 镜，要求
#   sum_d x[k][d]=n_k 且 sum_k x[k][d] <= supply[d] → Dinic 最大流求解；
#   不可行时**如实降镜数**（单镜自动拉长 = 原速），绝不循环复用同一条素材。
# ══════════════════════════════════════════════════════════════════════════════
_MOTION_TAIL = {"idx": None}      # 2026-09-21：motion_cache 尾部索引（键为路径末 40 字符）

# 2026-09-27：常驻运动缓存（全池共享，避免每片现场 probe_motion 白烧 ~480s）。
#   默认路径固定；文件不存在不报错，缺失键现场探测后**增量写回**，只新增键、绝不覆盖既有键值。
DEFAULT_MOTION_CACHE = REPO / "assets/scenes/pool_common_china/_motion_cache.json"
_MOTION_CACHE_PATH = {"path": None}   # 由 main 设置；供 _build_dir_pools 写回


def _flush_motion_cache(pending):
    """把现场探测出的新键增量落盘；只新增，不覆盖既有键值（007 2026-09-27）。返回新增键数。"""
    if not pending:
        return 0
    items = dict(pending)
    pending.clear()
    path = _MOTION_CACHE_PATH.get("path")
    if not path:
        return 0
    try:
        p = Path(path)
        cur = {}
        if p.exists():
            try:
                cur = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"⚠️ 运动缓存解析失败，跳过本次落盘（不覆盖原文件）：{e}")
                return 0
        added = {k: v for k, v in items.items() if k not in cur}
        if not added:
            return 0
        cur.update(added)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return len(added)
    except Exception as e:
        print(f"⚠️ 运动缓存落盘失败（不影响本次合成）：{e}")
        return 0


def _build_dir_pools(root, avail, motion, exclude, allow_static):
    """目录 → [(motion, path, dir, name)]，按运动量降序；口径与 C.pick_items 一致。"""
    pools = {}
    _md5_seen = {}          # 2026-09-19：同源双胞胎去重（同一内容被 Pexels 挂进两个关键词目录，
    _new = {}               # 2026-09-27：本次现场探测出的新键（增量写回常驻缓存）
    _new_total = 0
    for d, names in (avail or {}).items():   # 文件不同、md5 相同 —— 按文件名/md5 去重都查不出，必须按内容 md5 跨目录去重）
        keep, seen = [], set()
        for name in names:
            key = f"{d}/{name}"
            if key in (exclude or set()) or key in seen:
                continue
            seen.add(key)
            f = Path(root) / d / "video" / name
            if not f.exists():
                print(f"⚠️ 白名单文件缺失：{f}")
                continue
            # 2026-09-21 修复：motion_cache 的键是**绝对路径**，而此处 f 由 scene_root 拼出，
            # scene_root 常是相对路径 → 键对不上 → 命中率恒为 0、静默回退实时探测（005 测出）。
            # 统一按 abspath 查找（并兼容旧的相对键缓存）。
            _fp = str(f)
            try:
                _fk = _fp if os.path.isabs(_fp) else str(Path(_fp).resolve())
            except Exception:
                _fk = _fp
            m = motion.get(_fk, {}).get("mean")
            if m is None:
                m = motion.get(_fp, {}).get("mean")
            if m is None:
                # 兜底：按「目录/文件名」尾部匹配（对 cwd / 两棵树差异免疫）
                if _MOTION_TAIL.get("idx") is None:
                    _MOTION_TAIL["idx"] = {kk.replace("\\", "/")[-40:]: vv for kk, vv in motion.items() if isinstance(vv, dict)}
                m = (_MOTION_TAIL["idx"].get(_fp.replace("\\", "/")[-40:]) or {}).get("mean")
            if m is None:
                _probed = C.probe_motion(_fp)
                m = _probed["mean"]
                motion[_fk] = {"mean": m}
                _new[_fk] = _probed          # 2026-09-27：待增量写回常驻缓存（含 n，口径不变）
            if m < C.MIN_MOTION and key not in (allow_static or set()):
                continue
            try:
                _h = md5_of(str(f))
            except Exception:
                _h = ""
            if _h and _h in _md5_seen:
                print(f"  🔁 同源双胞胎剔除：{key}（内容与 {_md5_seen[_h]} 相同）")
                continue
            if _h:
                _md5_seen[_h] = key
            keep.append((m, f, d, name))
        keep.sort(key=lambda x: -x[0])
        pools[d] = keep
        _new_total += _flush_motion_cache(_new)   # 2026-09-27：按目录增量落盘
    if _new_total:
        print(f"💾 运动缓存增量写回：本次新增 {_new_total} 键 → {_MOTION_CACHE_PATH.get('path')}")
    return pools


class _Dinic:
    def __init__(self, n):
        self.n = n
        self.g = [[] for _ in range(n)]

    def add(self, u, v, c):
        self.g[u].append([v, c, len(self.g[v])])
        self.g[v].append([u, 0, len(self.g[u]) - 1])

    def maxflow(self, s, t):
        flow = 0
        while True:
            lvl = {s: 0}
            q = [s]
            while q:
                u = q.pop(0)
                for e in self.g[u]:
                    if e[1] > 0 and e[0] not in lvl:
                        lvl[e[0]] = lvl[u] + 1
                        q.append(e[0])
            if t not in lvl:
                return flow
            it = [0] * self.n

            def dfs(u, f):
                if u == t:
                    return f
                while it[u] < len(self.g[u]):
                    e = self.g[u][it[u]]
                    if e[1] > 0 and lvl.get(e[0], -1) == lvl[u] + 1:
                        r = dfs(e[0], min(f, e[1]))
                        if r:
                            e[1] -= r
                            self.g[e[0]][e[2]][1] += r
                            return r
                    it[u] += 1
                return 0
            while True:
                f = dfs(s, 10 ** 9)
                if not f:
                    break
                flow += f


def pick_items_dedup_global(root, chapters, times, lines, scene_map, motion, total, n_ch,
                            poster_dir, avail, exclude, allow_static):
    pools = _build_dir_pools(root, avail, motion, exclude, allow_static)
    supply = {d: len(v) for d, v in pools.items()}
    print(f"📦 净池（available − exclude − 静止镜头）：{sum(supply.values())} 段 / {len(supply)} 目录")

    spans, dirs_k = [], []
    for k in range(n_ch):
        label, st, en = chapters[k]
        c0 = times[k]
        c1 = times[k + 1] if (k + 1 < n_ch and k + 1 < len(chapters)) else total
        spans.append(max(2.0, c1 - c0))
        dirs_k.append([d for d in C.chapter_dirs(label, scene_map[k][1], lines, st, en)
                       if pools.get(d)])
    L = float(C.SHOT_LEN)
    targets = [max(2, int(round(spans[k] / L))) for k in range(n_ch)]
    alloc = [defaultdict(int) for _ in range(n_ch)]
    left = {d: supply[d] for d in supply}

    # ① 覆盖保留：每章每个映射目录先拿 1 镜（供给允许时）
    for k in range(n_ch):
        for d in dirs_k[k]:
            if alloc[k][d] == 0 and left[d] > 0 and sum(alloc[k].values()) < targets[k]:
                alloc[k][d] += 1
                left[d] -= 1

    # ② 剩余需求 → 最大流
    need = [targets[k] - sum(alloc[k].values()) for k in range(n_ch)]
    didx = {d: i for i, d in enumerate(sorted(supply))}
    S = n_ch + len(didx)
    T = S + 1
    FLOW = _Dinic(T + 1)
    for k in range(n_ch):
        if need[k] > 0:
            FLOW.add(S, k, need[k])
        for d in dirs_k[k]:
            if left[d] > 0:
                FLOW.add(k, n_ch + didx[d], 9999)
    for d, i in didx.items():
        if left[d] > 0:
            FLOW.add(n_ch + i, T, left[d])
    FLOW.maxflow(S, T)
    got = list(need)
    for k in range(n_ch):
        for e in FLOW.g[k]:
            v = e[0]
            if n_ch <= v < n_ch + len(didx):
                fwd = e[2]
                fl = FLOW.g[v][fwd][1]          # 反向边剩余容量 == 正向边流量
                if fl > 0:
                    d = [dd for dd, ii in didx.items() if ii == v - n_ch][0]
                    alloc[k][d] += fl
                    got[k] -= fl
    if any(got):
        print("⚠️ 以下章节未排满（单镜自动拉长，原速不循环）: "
              + str([(k + 1, targets[k] - got[k]) for k in range(n_ch) if got[k]]))

    # ③ 章内排序（相邻换目录）+ 目录内按运动量降序切片发素材
    ptr = {d: 0 for d in pools}
    segs, items, titles = [], [], []
    for k in range(n_ch):
        label = chapters[k][0]
        titles.append(label)
        rem = dict(alloc[k])
        order, last = [], None
        while sum(rem.values()) > 0:
            cands = [d for d, c in rem.items() if c > 0 and d != last] or \
                    [d for d, c in rem.items() if c > 0]
            d = max(cands, key=lambda x: (rem[x], -dirs_k[k].index(x)))
            order.append(d)
            rem[d] -= 1
            last = d
        picks = []
        for d in order:
            m, f, dd, name = pools[d][ptr[d]]
            ptr[d] += 1
            picks.append((m, f, dd, name))
        files = [x[1] for x in picks]
        durs = C.fit_shot_durations(files, spans[k], len(picks))
        t = times[k]
        for j, ((m, f, d, name), sd) in enumerate(zip(picks, durs)):
            seg = scene_selector.SceneSegment(theme=f"jp_daily/{d}", start=t, end=t + sd,
                                              chapter_title=label)
            t += sd
            setattr(seg, "chapter_idx", k)
            if j == 0:
                poster = poster_dir / f"ch{k+1}.jpg"
                subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(f),
                                "-frames:v", "1", "-vf", "scale=1080:-1",
                                "-q:v", "3", str(poster)], capture_output=True)
                if poster.exists():
                    seg.images = [str(poster)]
            segs.append(seg)
            items.append((str(f), sd, "video", d))
        print(f"  Ch{k+1} {label}: {len(picks)} 镜 × {spans[k]/max(1,len(picks)):.1f}s"
              f" | 目录 {len(set(d for _,_,d,_ in picks))}/{len(dirs_k[k])}")
    return segs, items, titles


def _dump_items(items):
    try:
        json.dump([{"file": it[0], "dur": it[1], "dir": it[3]} for it in items],
                  open("/tmp/ght/final_items.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"⚠️ 选材清单导出失败: {e}")


def pick_items_dedup_legacy(root, chapters, times, lines, scene_map, motion, total, n_ch,
                            poster_dir, avail, exclude, allow_static):
    """先跑一遍 pick_items，再做「内容级去重」：素材库里有大量跨目录的同一源视频
    （Pexels 不同关键词返回同一 clip，被 007 入库到不同目录），compose_scene_map
    的 md5 去重实际只按 (目录,文件名) 去重 → 成片出现同源重复（本片实测 9 组）。
    这里对每轮 picks 做 md5 分组，除保留首个外其余加进排除集重挑，直到无重复。"""
    excl = set(exclude or set())
    # ⚠️ 收敛护栏（2026-09-13 007 备稿班加）：
    #   原实现最多迭代 12 轮、每轮把"复用同一素材"的镜头全部加入**全局**排除集。
    #   当各章映射目录有交集时，一次排除会同时抽干多个章的池 → 复用更多 → 排除更多，
    #   形成**发散**（实测《大医》第 1..7 轮：6→12→20→24→30→26→10 组，池被抽空，
    #   最终 exit 3「章节无可运动量达标素材」）。
    #   实测该池全量比对的感知相似对只有 1 组（<=5.0），说明 sig 分组在此池里
    #   抓的是"同一素材被复用"而非"不同素材长得像"；而成片里跨章复用同一素材
    #   是既有惯例（历史验收通过：《深夜食堂》16 对、《撒哈拉》等），
    #   所以这里加两道护栏：最多 3 轮；任一章剩余池 < 该章镜数就立刻停手。
    added_total = 0
    for it in range(8):
        segs, items, titles = C.pick_items(root, chapters, times, lines, scene_map, motion,
                                           total, n_ch, poster_dir, avail, excl, allow_static)
        groups = {}
        for gi, (p_, _d, _k, _dr) in enumerate(items):
            groups.setdefault("md5:" + md5_of(p_), []).append(gi)
        # 感知签名分组：同源不同 md5（重复入库/转码）也归为一组
        sigs = [low_sig(p_) for p_, _d, _k, _dr in items]
        used = set()
        for gi in range(len(items)):
            if gi in used:
                continue
            grp = [gj for gj in range(gi + 1, len(items))
                   if gj not in used and sig_dist(sigs[gi], sigs[gj]) <= SIG_THRESH]
            if grp:
                groups.setdefault("sig:%d" % gi, []).append(gi)
                for gj in grp:
                    groups["sig:%d" % gi].append(gj); used.add(gj)
            used.add(gi)
        dups = {h: g for h, g in groups.items() if len(g) > 1}
        if not dups:
            if it:
                print(f"  🧹 内容去重完成：迭代 {it} 轮后无同源重复")
            return segs, items, titles
        # 停止条件（护栏②）：**本轮准备追加的**排除量若把「循环内累计」推过全池 20%，
        # 就不排除、直接保留当前选材——实测《大医》第 4 轮累计 26% 后开始「章池 < 镜数」。
        # 只统计循环内追加量；调用方传入的 --exclude 不计入（否则一开轮就触发）。
        pool_n = sum(len(v) for v in (avail or {}).values()) or len(items)
        plan = [f"{items[gi][3]}/{Path(items[gi][0]).name}"
                for g in dups.values() for gi in g[1:]]
        plan = [r for r in plan if r not in excl]
        # 2026-09-19 007：原护栏「>20% 就停手并**保留重复选材**」= 静默放行同源重复（本片双胞胎
        # 即由此漏出：同一条片被排进 Ch1+Ch3）。改为：只有「既超 20% 又超过 8 段」才停手；
        # 小规模修复（双胞胎这类）必须做完。即便停手，返回前也不再静默——见函数尾的最终护栏。
        if added_total + len(plan) > 0.2 * pool_n and added_total + len(plan) > 8:
            print(f"  ⚠️ 内容去重本轮拟排除 {len(plan)} 段（累计 {added_total + len(plan)}/{pool_n} > 20% 且 >8 段）"
                  f"→ 停止去重（避免把章节池抽干）；将由函数尾最终护栏复核有无残留重复")
            break
        added = 0
        for rel in plan:
            if rel not in excl:
                excl.add(rel); added += 1
        print(f"  🧹 第 {it+1} 轮发现 {len(dups)} 组同源重复 → 追加排除 {added} 段后重挑")
        added_total += added
    print("  🧹 dedup 达轮次上限 → 用最终排除集重挑一次（保证返回选材与排除集一致）")
    segs, items, titles = C.pick_items(root, chapters, times, lines, scene_map, motion,
                                       total, n_ch, poster_dir, avail, excl, allow_static)
    # 最终护栏（2026-09-19 007）：返回前强制复核「零同源重复」；有残留则写标记文件，
    # 由生产门禁拦截 —— 绝不静默放行（本片 v2b 就是这样把一条片同时排进 Ch1 与 Ch3 的）。
    _grp, _used = {}, set()
    for _gi, (_p, _d, _k, _dr) in enumerate(items):
        _grp.setdefault("md5:" + md5_of(_p), []).append(f"{_dr}/{Path(_p).name}")
    _sigs = [low_sig(_p) for _p, _d, _k, _dr in items]
    for _gi in range(len(items)):
        if _gi in _used:
            continue
        for _gj in range(_gi + 1, len(items)):
            if _gj in _used:
                continue
            if sig_dist(_sigs[_gi], _sigs[_gj]) <= SIG_THRESH:
                _grp.setdefault("sig:%d" % _gi, []).append(f"{items[_gj][3]}/{Path(items[_gj][0]).name}")
                _used.add(_gj)
        _used.add(_gi)
    _dups = {h: g for h, g in _grp.items() if len(g) > 1}
    if _dups:
        import json as _json
        Path("/tmp/qc_dups_unresolved.json").write_text(
            _json.dumps(_dups, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  ❌ 最终选材仍有 {len(_dups)} 组同源重复 → /tmp/qc_dups_unresolved.json（门禁须拦截，不得交付）")
    else:
        print("  ✅ 最终选材零同源重复")
    return segs, items, titles


def split_chapters_by_heading(lines: list, scene_map: list) -> list:
    """按 `#` 标题切章（书名首行也是第 1 章 = 开场章），与 scene_map 严格对齐。"""
    hs = [i for i, l in enumerate(lines) if l.startswith("#") and len(l) > 1 and l[1] != "#"]
    if len(hs) != len(scene_map):
        print(f"❌ 标题数 {len(hs)} ≠ scene_map 章数 {len(scene_map)}")
        sys.exit(2)
    out = []
    for k, st in enumerate(hs):
        en = hs[k + 1] - 1 if k + 1 < len(hs) else len(lines) - 1
        while en > st and not lines[en].strip():
            en -= 1
        out.append((scene_map[k][0], st, en))
    return out


def spoken_prefix_counts(lines: list) -> list:
    """每行「朗读字符数」前缀和（标记行/标题行不朗读）——章节时间轴唯一口径。"""
    cjk = [0 if (MARKER_LINE.match(l) or l.lstrip().startswith("#"))
           else len(re.findall(r"[\u4e00-\u9fff]", l)) for l in lines]
    pre, acc = [0], 0
    for c in cjk:
        acc += c
        pre.append(acc)
    return pre


def chapter_card_title(label: str, k: int, book: str = "") -> str:
    """章节卡标题：首章=开场（渲染成「序章 / 书名」），其余标签本身已合规。

    2026-09-14 修：首章卡标题原先硬编码「开场：深夜食堂」，任何非《深夜食堂》
    的书（如《大医》）首章卡都会被印成「序 深夜食堂」。改为按 --book 生成
    「开场：<书名>」；book 为空时回退到 scene_map 的标签，绝不印错书。
    """
    if k == 0:
        return f"开场：{book}" if book else label
    return label


# ══ 选材前置台账门禁 + 自愈换段（2026-09-26 · 007 SPEC_for_005 v1.0）═════════════
# 背景（实测）：最新生产指令复跑，115 镜里 12 镜（10.4%）素材在常驻池台账里是违规段
# （face / non_japan / modern），而当时没有任何门禁拦截 → 它们直接进了成片。
# 本段实现两条 fail-closed 防线（零 VL、零改台账、零改判据）：
#   ① 选材前置：available 先过「台账 verdict==clean 白名单」→ 脏段从源头进不来；
#   ② 选材后复核 + 自愈换段：万一仍有违规段（台账更新 / 显式 --shot-override 注入），
#      在「本章节映射目录 ∩ 白名单」里找干净替代段，**只换素材路径、镜长与镜数不变**
#      —— 几何不变是「只重渲受影响批次（--only-batch）」成立的前提，必须写死在代码里。
POOL_GATE_CRITERION = "pc-v6-20260926-noinfo-guard3-regionnorm1-fullnotes"


def _load_pool_gate():
    """加载常驻池台账门禁库（只读、零 VL、不写台账）。

    优先仓库内 `scripts/pool_gate.py`（生产自持），回退 /root/.hermes/scripts（原型侧）。
    """
    for p in (str(REPO / "scripts"), "/root/.hermes/scripts"):
        if p not in sys.path:
            sys.path.insert(0, p)
    import pool_gate
    return pool_gate


def _item_key(it):
    """items 元组 → 台账/排除清单惯用短键 `<目录>/<文件名>`。"""
    return f"{it[3]}/{Path(it[0]).name}"


def _parse_only_batch(v):
    """'1' / '2,5' / '0' → 批号集合（SPEC §6.4：必须支持逗号列表）。"""
    out = set()
    for x in str(v or "0").replace("，", ",").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            n = int(x)
        except ValueError:
            print(f"❌ --only-batch 非法批号：{x!r}（应为 1-based 整数或逗号列表）")
            sys.exit(2)
        if n > 0:
            out.add(n)
    return out


def _chapter_candidate_pool(scene_map, avail, ci):
    """本章节映射目录 ∩ 白名单 → {目录: [允许文件名...]}（顺序=优先级）。

    只在本章映射目录内换段，且**只取白名单里的文件名**（SPEC §6.2 方案 a）：
    既保证 dry-run ④ 素材白名单继续通过，又避免把别的章节素材塞进本章造成语义错位。
    """
    pool = {}
    if 0 <= ci < len(scene_map):
        for d in scene_map[ci][1]:
            if avail.get(d):
                pool[d] = list(avail[d])
    return pool


def _heal_swap(pgmod, pg, cur_key, shot_dur, cand_pool, used, failed, probe_root):
    """同槽位换段：返回 (新短键 或 None, 诊断 dict)。纯函数、无随机、无副作用。

    候选来源 = 本章映射目录 ∩ 白名单（cand_pool）；候选必须同时满足：
    verdict==clean ｜ 磁盘存在 ｜ 实长 ≥ 原镜长×0.8
    （SPEC §6.3：防换入过短素材被 `-stream_loop -1` 循环成「同一镜重复」）。
    """
    cur = pgmod.short_key(cur_key)
    cur_dir = cur.split("/")[0]
    order = list(cand_pool)
    if cur_dir in order:                      # 优先同目录（视觉连续），再跨目录
        order = [cur_dir] + [d for d in order if d != cur_dir]
    tried = []
    for d in order:
        names = list(cand_pool[d])
        start = 0
        if d == cur_dir:
            cn = cur.split("/")[-1]
            if cn in names:
                start = names.index(cn) + 1
        for name in names[start:] + names[:start]:
            k = f"{d}/{name}"
            if k in used or k in failed:
                tried.append((k, "used_or_failed")); continue
            if not pg.exists_on_disk(k):
                tried.append((k, "missing_on_disk")); continue
            if not pg.is_clean(k):
                tried.append((k, "not_clean")); continue
            try:
                cl = C.probe_duration(str(Path(probe_root) / pgmod.norm_key(k)))
            except Exception:
                cl = 0.0
            if shot_dur and cl and cl < shot_dur * 0.8:
                tried.append((k, f"too_short({cl:.1f}s<{shot_dur * 0.8:.1f}s)")); continue
            return k, {"current": cur, "current_verdict": pg.verdict(cur),
                       "same_dir": d == cur_dir, "dir": d,
                       "clean_in_dir": len(names), "skipped": tried[-5:],
                       "skipped_n": len(tried)}
        tried.append((f"{d}/*", "dir_has_no_clean_left"))
    return None, {"current": cur, "current_verdict": pg.verdict(cur), "same_dir": None,
                  "dir": None, "clean_in_dir": 0, "skipped": tried[-8:],
                  "skipped_n": len(tried)}


def _batch_fingerprint(items_sub, i0, i1, off, dur):
    """分段指纹：几何 + 该批逐镜（路径/镜长）→ 防「旧几何分段拼新几何片」（SPEC §6.5）。"""
    import hashlib
    h = hashlib.md5()
    h.update(f"n{len(items_sub)}|{i0}-{i1}|{off:.3f}|{dur:.3f}"
             f"|chunk{os.environ.get('COMPOSE_CHUNK', '24')}".encode())
    for p, d, _k in items_sub:
        h.update(f"|{Path(p).name}:{d:.4f}:{p}".encode())
    return h.hexdigest()


def _part_sidecar_write(pth, items_sub, i0, i1, off, dur):
    try:
        Path(str(pth) + ".json").write_text(json.dumps({
            "fingerprint": _batch_fingerprint(items_sub, i0, i1, off, dur),
            "shots": len(items_sub), "bounds": [i0, i1], "start": round(off, 3),
            "dur": round(dur, 3), "chunk": os.environ.get("COMPOSE_CHUNK", "24"),
            "crf": 23, "preset": "faster"}, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 分段指纹写入失败（不影响本批渲染）：{e}")


def _part_sidecar_check(pth, items_sub, i0, i1, off, dur):
    """None=一致或无法校验（出声放行）；str=不一致原因（调用方 exit 7）。"""
    sp = Path(str(pth) + ".json")
    fp = _batch_fingerprint(items_sub, i0, i1, off, dur)
    if not sp.exists():
        print(f"⚠️ 批 {pth.name} 无指纹 sidecar，无法校验几何一致性（旧产物）→ 出声放行")
        return None
    try:
        d = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as e:
        return f"sidecar 解析失败 {e}"
    if d.get("fingerprint") != fp:
        return (f"fingerprint {str(d.get('fingerprint'))[:12]}… != 当前 {fp[:12]}…"
                f"（shots {d.get('shots')} vs {len(items_sub)}，bounds {d.get('bounds')} vs [{i0},{i1}]）")
    return None


def _dump_gate_report(args, rep):
    p = (getattr(args, "pool_gate_report", "") or "").strip()
    if not p:
        return
    try:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"💾 门禁/自愈报告: {p}")
    except Exception as e:
        print(f"⚠️ 门禁报告写入失败：{e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--scene-map", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--book", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--motion-cache", default=str(DEFAULT_MOTION_CACHE),
                    help="运动量缓存（全池常驻，缺失键现场探测后增量写回；文件不存在不报错）")
    ap.add_argument("--exclude", default=None)
    ap.add_argument("--allow-dead-exclude", action="store_true",
                    help="排除清单死条目过半时仍继续（默认拒绝——防脏素材入片，2026-09-14 事故护栏）")
    ap.add_argument("--allow-static", default=None)
    ap.add_argument("--allow-source-mismatch", action="store_true",
                    help="音源/稿源文件名不含书名时仍继续（默认拒绝——防「拿了别的书的 mp3/讲书稿」"
                         "导致整片音画全错，2026-09-17《目送》dry-run 事故护栏）")
    ap.add_argument("--dry-run", action="store_true")
    # ── 选材前置台账门禁 + 自愈换段（2026-09-26 · 007 SPEC_for_005 v1.0）────
    # 判据固定 pc-v6-20260926-noinfo-guard3-regionnorm1-fullnotes（qwen3-vl-flash 单跑，
    # 确认层 off，PC_REGION=中国）。这里**只读台账**，绝不改判据/台账/池文件。
    ap.add_argument("--pool-gate", choices=["enforce", "audit", "off"], default="enforce",
                    help="选材前置台账门禁：enforce=只取 verdict==clean（默认）｜audit=只报不改｜off=关")
    ap.add_argument("--reserve", type=int, default=3,
                    help="每个映射目录要求保留的干净候选数下限（自愈换段的弹药体检）")
    ap.add_argument("--max-swaps", type=int, default=3,
                    help="单镜自愈换段次数上限；超过即 exit 4 停下叫人")
    ap.add_argument("--only-batch", default="0",
                    help="只真渲第 N 批（1-based，支持逗号列表如 '2,5'）；其余批次从 "
                         "--parts-dir 复用已渲分段。0/缺省 = 整片全渲")
    ap.add_argument("--parts-dir", default="",
                    help="分段持久目录（video_partNN.mp4）。空 = 沿用临时目录并随进程删除（旧行为）")
    ap.add_argument("--shot-override", action="append", default=[],
                    help="同槽位换段，可重复：'<镜头序号1-based>=<目录>/<文件名>'。"
                         "只换素材路径，镜长/镜数不变（自愈换段专用）")
    ap.add_argument("--pool-root", default="assets/scenes/pool_common_china",
                    help="--shot-override 的解析根（常驻池）")
    ap.add_argument("--pool-gate-report", default="",
                    help="可选：门禁/自愈机读报告 JSON 输出路径")
    args = ap.parse_args()
    for a in ("script", "scene_map", "audio", "output", "motion_cache"):
        v = getattr(args, a)
        if v is None:                     # 2026-09-16: 可选参数不传时原先会 NoneType 崩溃
            continue
        setattr(args, a, str(Path(v).resolve()))

    lines = Path(args.script).read_text(encoding="utf-8").splitlines()
    sm = json.load(open(args.scene_map, encoding="utf-8"))
    scene_map, avail = sm["scene_map"], sm.get("available") or {}
    root = Path(sm["scene_root"])
    if not root.is_absolute():        # 运动量缓存 key 是绝对路径，相对路径会 miss 并逐段现算
        root = REPO / root
    motion = C.load_motion(args.motion_cache)
    _MOTION_CACHE_PATH["path"] = args.motion_cache

    full_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", args.audio], capture_output=True, text=True).stdout.strip())

    chapters = split_chapters_by_heading(lines, scene_map)
    n_ch = len(chapters)
    titles = [c[0] for c in chapters]
    # ── 音源/稿源身份硬门禁（2026-09-17）────────────────────────────
    # 事故：正式渲染的 --audio 被写成**别的书**的 mp3（同目录复制粘贴），
    # 原日志只打时长（`音频: 615.8s`），两本书时长接近时肉眼无法分辨 →
    # 整片音画全错、只能废弃。故：打印音源指纹（文件名+md5前8+mtime）并**校验文件名含书名**。
    def _md5_8(path):
        h = subprocess.run(["md5sum", path], capture_output=True, text=True).stdout.split()
        return h[0][:8] if h else "?"

    audio_p, script_p = Path(args.audio), Path(args.script)
    audio_name, script_name = audio_p.name, script_p.name
    print(f"🔊 音源: {audio_name}  md5:{_md5_8(args.audio)}  "
          f"mtime:{__import__('datetime').datetime.fromtimestamp(audio_p.stat().st_mtime):%Y-%m-%d %H:%M}  "
          f"路径: {args.audio}")
    print(f"📝 稿源: {script_name}  mtime:{__import__('datetime').datetime.fromtimestamp(script_p.stat().st_mtime):%Y-%m-%d %H:%M}  "
          f"路径: {args.script}")
    if args.book:
        bad = [("音源", audio_name), ("稿源", script_name)]
        bad = [(k, n) for k, n in bad if args.book not in n]
        if bad:
            for k, n in bad:
                print(f"❌ {k}文件名不含书名「{args.book}」：{n}")
            print("   → 疑似拿了**别的书**的音源/讲书稿（同目录复制粘贴）。"
                  "整片音画全错、只能废弃，故默认拒绝。")
            print(f"   若确属有意命名，请加 --allow-source-mismatch 重跑。")
            if not args.allow_source_mismatch:
                sys.exit(5)
    print(f"📖 书名: {args.book} | 作者: {args.author} | 音频: {full_dur:.1f}s | 章节: {n_ch}")
    for k, (label, st, en) in enumerate(chapters):
        n_spoken = sum(len(re.findall(r"[\u4e00-\u9fff]", l)) for l in lines[st:en + 1]
                       if not MARKER_LINE.match(l))
        print(f"  Ch{k+1} {label}: 行 {st+1}-{en+1} 朗读CJK {n_spoken}")

    # 章节时间轴：朗读字符比例（与 pick_items 同源），并注入 video_composer
    pre = spoken_prefix_counts(lines)
    tot = max(pre[-1], 1)
    times = [full_dur * pre[st] / tot for _, st, _ in chapters]
    print("⏱️ 章节起点: " + " ".join(f"Ch{k+1}={t:.0f}s" for k, t in enumerate(times)))
    VC._fallback_chapter_times = lambda chs, script_text, audio_dur: list(times)
    VC._quote_times = lambda quotes, script_text, starts, audio_dur: make_quote_times(composer_text, audio_dur, quotes)

    # 镜头时长分配：注水式（water-filling）——把短视频省下的余量**均匀**补给仍有
    # 余量的镜，而不是全砸给最长的那个素材（默认实现按 headroom 比例分配，实测把
    # 一个 14.7s 素材撑成 15.3s 长镜，画面节奏突兀）。上限仍不超过素材实长。
    def _fit_water(files, span, n):
        """files: 素材路径列表（与 compose_scene_map.fit_shot_durations 同签名）。"""
        base = span / max(1, n)
        caps = [C.probe_duration(str(f)) for f in files]
        caps = [c if c > 1.0 else base for c in caps]
        base = span / max(1, n)
        d = [min(base, c) for c in caps]
        for _ in range(200):
            need = span - sum(d)
            if need <= 0.01:
                break
            cand = [i for i in range(len(d)) if d[i] < caps[i] - 1e-6]
            if not cand:
                break
            share = need / len(cand)
            moved = False
            for i in cand:
                add_ = min(share, caps[i] - d[i])
                if add_ > 1e-6:
                    d[i] += add_
                    moved = True
            if not moved:
                break
        if sum(d) < span - 0.01:            # 全部素材用满仍不够 → 轻微循环铺满
            k = span / sum(d)
            d = [x * k for x in d]
        d[-1] += span - sum(d)
        return d

    C.fit_shot_durations = _fit_water
    import compose_scene_map as _CSM
    _CSM.fit_shot_durations = _fit_water
    print("🎛️ 镜头时长分配：注水式（避免单镜过长）")


    card_titles = [chapter_card_title(lb, k, args.book) for k, (lb, _, _) in enumerate(chapters)]
    # 2026-09-14 修：《大医》等稿用「# + ##」双标记（# 供本包装器切章、## 供审稿门
    # check_script_quality）。build_text_with_chapters 会给每章再插一行 `## 卡标题`，
    # 于是 composer_text 里 ## 行 = 原稿 7 + 注入 7 = 14，而 video_composer.make_filter
    # 数 ## 得到 14 章、章节时间轴只有 7 条 → chapter_times[ci+1] IndexError（正式合成崩，
    # dry-run 因不经过 make_filter 漏检）。这里把原稿自带的 ## 行**原地置空**（保留行号，
    # 否则 build_text_with_chapters 按章节起始行号 insert 会错位；标题行本就不朗读，
    # 置空不影响朗读字符比例/金句时间轴），保证注入后 ## 数 == 章节数。
    lines_no_dup = ["" if l.lstrip().startswith("##") else l for l in lines]
    composer_text = C.build_text_with_chapters(lines_no_dup, chapters, card_titles)
    n_h = sum(1 for l in composer_text.splitlines() if l.strip().startswith("##"))
    if n_h != len(chapters):
        print(f"⚠️ composer_text ## 行 {n_h} ≠ 章节 {len(chapters)}，章节卡时间轴可能错位")
    quotes = extract_quotes_full(composer_text)
    print('💬 金句字卡(完整引文): ' + ' | '.join(quotes))
    print(f"💬 金句字卡: {len(quotes)} 句 → {quotes}")

    poster_dir = Path(tempfile.mkdtemp(prefix="lb_posters_"))
    raw_exclude = set(json.load(open(args.exclude, encoding="utf-8"))) if args.exclude else set()
    allow_static = set(json.load(open(args.allow_static, encoding="utf-8"))) if args.allow_static else set()
    # 归一化：兼容 <目录>/video/<文件>（门禁工具输出）与 <目录>/<文件>（历史清单）两种写法
    exclude = {_excl_key(x) for x in raw_exclude}
    if raw_exclude:
        print(f"🚫 人工复核排除 {len(raw_exclude)} 条 → 归一化 {len(exclude)} 条"
              f"（来自 {Path(args.exclude).name}）")
        # 护栏③·死条目检测：每条排除键必须能对上磁盘上真实存在的素材，
        # 否则 = 格式不匹配 → 整份清单空转（2026-09-14《大医》130 条假通过事故）
        disk_keys = set()
        for p in root.rglob("*.mp4"):
            try:
                disk_keys.add(_excl_key(str(p.relative_to(root))))
            except ValueError:
                disk_keys.add(_excl_key(p.name))
        dead = sorted(x for x in raw_exclude if _excl_key(x) not in disk_keys)
        if dead:
            pct = 100.0 * len(dead) / len(raw_exclude)
            lvl = "❌" if pct > 50 else "⚠️"
            print(f"{lvl} 排除清单死条目 {len(dead)}/{len(raw_exclude)} 条（{pct:.0f}%）"
                  f"匹配不到任何素材（格式可能不对）｜例：{dead[:3]}")
            if pct > 50 and not args.allow_dead_exclude:
                print("❌ 排除清单过半失效 → 拒绝合成（否则脏素材会入片）。"
                      "确认无误可加 --allow-dead-exclude 强制继续。")
                sys.exit(2)

    crosscheck_playlists(avail, sm.get("excluded"), sm.get("excluded_count"), raw_exclude)

    # ── ① 选材前置台账门禁（2026-09-26 · 007 SPEC_for_005 v1.0）────────────
    # available 先过「台账 verdict==clean 白名单」⇒ 脏段（face / non_japan / modern）
    # 从源头进不来。判据固定 POOL_GATE_CRITERION（qwen3-vl-flash 单跑 / 确认层 off /
    # PC_REGION=中国）；**只读台账**，绝不改判据 / 台账 / 池文件。fail-closed：
    # 不在台账 = 不可用。任何放行/降级都不允许。
    _pg = _pgmod = None
    _gate_rep = {"criterion": POOL_GATE_CRITERION, "mode": args.pool_gate,
                 "available_in": sum(len(v) for v in avail.values()),
                 "available_dirs_in": len(avail)}
    if args.pool_gate != "off":
        try:
            _pgmod = _load_pool_gate()
            _pg = _pgmod.PoolGate()
            _filt, _rep = _pg.filter_available(avail)
        except Exception as _e:
            print(f"❌ 台账门禁不可用 → 拒绝合成（fail-closed）：{_e!r}")
            sys.exit(3)
        _by = {}
        for _b in _rep["blocked"]:
            _by[_b["verdict"]] = _by.get(_b["verdict"], 0) + 1
        _compose_by = " / ".join(f"{k}×{v}" for k, v in sorted(_by.items())) or "无"
        print(f"🔒 台账门禁（{'强制 enforce' if args.pool_gate == 'enforce' else '仅审计 audit'}"
              f"｜判据 {POOL_GATE_CRITERION}）：")
        print(f"   available {_gate_rep['available_in']} 段 / {_gate_rep['available_dirs_in']} 目录"
              f" → clean {_rep['kept']} 段 / {_rep['dirs_kept']} 目录"
              f" ｜ ⛔ 拦截 {_rep['blocked_count']} 段（{_compose_by}）"
              + (f"｜丢弃目录 {len(_rep['dirs_dropped'])}" if _rep["dirs_dropped"] else ""))
        if _rep["blocked_count"]:
            print(f"   拦截例：{_rep['blocked'][:5]}")
        _gate_rep.update({"kept": _rep["kept"], "dirs_kept": _rep["dirs_kept"],
                          "blocked": _rep["blocked_count"], "blocked_by": _by,
                          "dirs_dropped": _rep["dirs_dropped"], "per_dir": _rep["per_dir"]})
        if args.pool_gate == "enforce":
            avail = _filt
        _dead_ch = [k + 1 for k, (_lb, _dirs) in enumerate(scene_map)
                    if not any(avail.get(d) for d in _dirs)]
        if _dead_ch:
            print(f"❌ 门禁后这些章节无任何干净候选目录：Ch{_dead_ch} → 停下叫人"
                  f"（不降判据、不放行、不整片重渲）")
            sys.exit(3)
        if args.reserve > 0:                  # 弹药体检：干净候选太薄的目录报警
            _thin = {d: len(v) for d, v in avail.items() if len(v) < args.reserve}
            _gate_rep["thin_dirs"] = _thin
            if _thin:
                print(f"⚠️ 弹药体检：{len(_thin)} 个目录干净候选 < reserve={args.reserve}："
                      f"{dict(sorted(_thin.items())[:6])}")
    else:
        print("🔒 台账门禁：已关闭（--pool-gate off）——不推荐用于交付")
    _dump_gate_report(args, _gate_rep)

    segs, items, _ = pick_items_dedup(root, chapters, times, lines, scene_map, motion,
                                      full_dur, n_ch, poster_dir, avail, exclude, allow_static)
    n_vid = len(items)
    print(f"🎬 共 {n_vid} 镜 | 素材去重 {len(set(i[0] for i in items))}/{n_vid}")

    # ── ② 同槽位换段钩子（--shot-override；只换素材路径，镜长/镜数不变）──────
    # 自愈换段的唯一入口。硬约束（SPEC §0）：items[i][1]（镜长）与镜数一律不变，
    # 否则 _starts 变 ⇒ 批次切点/后续各批 t_off 全变 ⇒ 分段缓存全废。
    _ch_first = {}
    for _i, _sg in enumerate(segs):
        _ch_first.setdefault(getattr(_sg, "chapter_idx", -1), _i)

    def _refresh_ch_poster(_i, _new_path):
        """换段落在本章首镜时，重建章节卡海报（否则画面仍是旧素材）。"""
        _ci = getattr(segs[_i], "chapter_idx", -1)
        if _ch_first.get(_ci) != _i or _ci < 0:
            return
        _p = Path(poster_dir) / f"ch{_ci + 1}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.0", "-i", str(_new_path),
                        "-frames:v", "1", "-vf", "scale=1080:-1", "-q:v", "3", str(_p)],
                       capture_output=True)
        if _p.exists():
            segs[_i].images = [str(_p)]

    if args.shot_override:
        _pool = Path(args.pool_root)
        if not _pool.is_absolute():
            _pool = REPO / _pool
        items = list(items)
        for _spec in args.shot_override:
            if "=" not in _spec:
                print(f"❌ --shot-override 格式应为 <镜头序号>=<目录>/<文件名>：{_spec!r}")
                sys.exit(2)
            _k, _repl = _spec.split("=", 1)
            try:
                _i = int(_k) - 1
            except ValueError:
                print(f"❌ --shot-override 镜头序号非整数：{_k!r}"); sys.exit(2)
            if not (0 <= _i < len(items)):
                print(f"❌ --shot-override 镜头序号越界：{_k}（本片共 {len(items)} 镜）")
                sys.exit(2)
            _rp = _repl.replace("\\", "/").strip("/").split("/")
            if len(_rp) < 2:
                print(f"❌ --shot-override 目标应为 <目录>/<文件名>：{_repl!r}"); sys.exit(2)
            _d, _n = _rp[0], _rp[-1]
            if not _n.lower().endswith(".mp4"):
                _n += ".mp4"
            _new = str(_pool / _d / "video" / _n)
            if not Path(_new).exists():
                print(f"❌ --shot-override 目标不存在：{_new}"); sys.exit(2)
            _old, _sd, _kind, _ = items[_i]
            items[_i] = (_new, _sd, _kind, _d)     # ★ 镜长 _sd 原样保留 ⇒ 几何不变
            print(f"🔁 换段：镜 #{_i+1} {Path(_old).name} → {_d}/{_n}（镜长保持 {_sd:.2f}s）")
            _refresh_ch_poster(_i, _new)

    # ── ③ 选材后台账复核 + 自愈换段（fail-closed：只换段，绝不放行/降级）────
    # 仅 enforce 模式执行（audit=只报不改，off=跳过；二者是 A/B 逃生阀，不得用于交付）。
    # 万一 items 里仍有非 clean 段（台账更新 / --shot-override 注入），在「本章映射目录
    # ∩ 白名单」里做同槽位换段；镜长与镜数不变 ⇒ 批次几何不变。
    # exit 3 = 池内候选耗尽（叫人）｜exit 4 = 单镜换段尝试 ≥ --max-swaps（叫人）。
    _heal_rep = {"checked": n_vid, "violations": [], "swaps": [], "status": "ok"}
    if _pg is not None and args.pool_gate == "enforce":
        _used = {_item_key(it) for it in items}
        for _i, _it in enumerate(items):
            _k = _item_key(_it)
            if _pg.is_clean(_k):
                continue
            _ci = getattr(segs[_i], "chapter_idx", -1)
            _heal_rep["violations"].append({"shot": _i + 1, "key": _k,
                                            "verdict": _pg.verdict(_k),
                                            "bad": _pg.bad_axes(_k)})
            print(f"⚠️ 选材后复核命中违规段：镜 #{_i+1} Ch{_ci+1} {_k}"
                  f"（verdict={_pg.verdict(_k)} / bad={_pg.bad_axes(_k)}）→ 自愈换段")
            _pool_map = _chapter_candidate_pool(scene_map, avail, _ci)
            _failed = {_k}
            _new_k = None
            _tries = 0
            while _tries < args.max_swaps and _new_k is None:
                _tries += 1
                _cand, _diag = _heal_swap(_pgmod, _pg, _k, _it[1], _pool_map,
                                          _used, _failed, root)
                if _cand is not None:
                    _new_k = _cand
                    break
                _failed |= {x for x, _w in _diag.get("skipped", [])
                            if "/" in x and not x.endswith("/*")}
                if not _pool_map or _diag.get("skipped_n", 0) == 0:
                    break                # 池内零候选 ⇒ 真耗尽，不空转
            if _new_k is None:
                if _tries >= args.max_swaps:
                    print(f"⛔ 镜 #{_i+1} 换段尝试已达上限 {args.max_swaps} 次仍无可用干净替代"
                          f" → exit 4 **停下叫人**（不得放行、不得降判据、不得整片重渲）")
                    _heal_rep["status"] = "max_swaps_exceeded"
                    _dump_gate_report(args, _heal_rep)
                    sys.exit(4)
                print(f"⛔ 镜 #{_i+1} 候选耗尽：本章映射目录 ∩ 白名单内已无可用干净替代段"
                      f"（已试 {_tries} 次）→ exit 3 **停下叫人**（不得放行、不得整片重渲）")
                _heal_rep["status"] = "candidates_exhausted"
                _dump_gate_report(args, _heal_rep)
                sys.exit(3)
            _old_path = items[_i][0]
            _new_path = str(root / _pgmod.norm_key(_new_k))
            items[_i] = (_new_path, _it[1], _it[2], _new_k.split("/")[0])
            _used.add(_new_k)
            _heal_rep["swaps"].append({"shot": _i + 1, "from": _k, "to": _new_k,
                                       "shot_dur": round(_it[1], 3)})
            print(f"✅ 自愈换段：镜 #{_i+1} {Path(_old_path).name} → {_new_k}"
                  f"（同槽位，镜长保持 {_it[1]:.2f}s）")
            _refresh_ch_poster(_i, _new_path)
        print(f"🩺 选材后复核：{n_vid} 镜｜违规 {len(_heal_rep['violations'])} 段｜"
              f"换段 {len(_heal_rep['swaps'])} 段"
              + ("" if not _heal_rep["violations"] else " → 台账前置门禁未能覆盖（见上）"))
    elif _pg is not None:                      # audit：只报不改（A/B 对照用）
        _viol = [(i + 1, _item_key(it)) for i, it in enumerate(items)
                 if not _pg.is_clean(_item_key(it))]
        _heal_rep["violations"] = [{"shot": s, "key": k} for s, k in _viol]
        _heal_rep["status"] = "audit_has_violations" if _viol else "audit_clean"
        if _viol:
            print(f"📋 台账门禁 audit（只报不改）：{len(_viol)} 段违规**未做任何替换**"
                  f"{_viol[:5]}")
            print("   ⚠️ audit 不拦不换 ⇒ 仅用于 A/B 对照，不得用于交付")
        else:
            print(f"📋 台账门禁 audit（只报不改）：{n_vid} 镜全部 clean")
    _dump_gate_report(args, _heal_rep)

    # ── dry-run 四项核对（007 指定）──
    if args.dry_run:
        print("\n===== DRY-RUN 核对 =====")
        ok = True
        print(f"① 段数==章节数：标记组 18（本稿【画面】分组）｜标题切章 {n_ch}｜scene_map {len(scene_map)} → "
              f"{'✅ 对齐' if n_ch == len(scene_map) else '❌ 不符'}")
        # ② 时间窗对齐：逐章累加镜长 == 章节跨度
        print("② 时间窗对齐（章节起止 = 朗读字符比例）：")
        for k, (label, _, _) in enumerate(chapters):
            c0 = times[k]
            c1 = times[k + 1] if k + 1 < n_ch else full_dur
            ch_items = [it for gi, it in enumerate(items)
                        if getattr(segs[gi], "chapter_idx", -1) == k]
            s = sum(it[1] for it in ch_items)
            flag = "✅" if abs(s - (c1 - c0)) < 0.6 else "❌"
            print(f"   Ch{k+1} {label[:16]:16s} {c0:7.1f}-{c1:7.1f}s 镜{s:7.1f}s "
                  f"{len(ch_items)}镜 {flag}")
            if abs(s - (c1 - c0)) >= 0.6 and k != n_ch - 1:
                ok = False
        # ③ 相邻不重复
        dup = [i for i in range(1, n_vid) if items[i][0] == items[i - 1][0]]
        print(f"③ 相邻镜头不重复：{len(dup)} 处相邻同素材 {'✅' if not dup else '❌ ' + str(dup)}")
        ok = ok and not dup
        # ④ 素材均在 available 白名单内 + 不在排除清单
        bad = [it for it in items if Path(it[0]).name not in avail.get(it[3], [])]
        excl = [it for it in items if f"{it[3]}/{Path(it[0]).name}" in exclude]
        print(f"④ 素材白名单：越界 {len(bad)} 段 {'✅' if not bad else '❌ ' + str(bad[:3])}"
              f"｜命中排除清单 {len(excl)} 段 {'✅' if not excl else '❌'}")
        ok = ok and not bad and not excl
        # ⑤ 台账前置门禁（免费、零 VL、fail-closed）——非 0 ⇒ exit 6，绝不放行违规段
        try:
            _g5 = _pg if _pg is not None else _load_pool_gate().PoolGate()
            _blk5 = [(i + 1, f"{it[3]}/{Path(it[0]).name}")
                     for i, it in enumerate(items)
                     if not _g5.is_clean(f"{it[3]}/{Path(it[0]).name}")]
            _note5 = ""
        except Exception as _e:
            _blk5, _note5 = ["<pool_gate 不可用>"], f"（{_e!r}）"
        print(f"⑤ 台账前置门禁：拦截 {len(_blk5)} 段 {_note5} "
              f"{'✅ 全部 clean' if not _blk5 else '❌ ' + str(_blk5[:5])}")
        ok = ok and not _blk5
        print("\n逐镜清单：")
        for k, it in enumerate(items):
            ci = getattr(segs[k], "chapter_idx", -1)
            mark = "  ← 与上一镜同素材" if k and items[k][0] == items[k - 1][0] else ""
            print(f"   [{ci+1}] {it[3]:26s} {Path(it[0]).name:10s} {it[1]:5.1f}s{mark}")
        print(f"\nDRY-RUN 结论：{'✅ 五项全部通过' if ok else '❌ 存在不达标项'}")
        if _blk5:
            print(f"❌ 台账前置门禁拦截 {len(_blk5)} 段 → exit 6"
                  f"（不降判据、不放行；请先用自愈换段或换素材）")
            sys.exit(6)
        return

    plan = scene_selector.ScenePlan(segments=segs, duration=full_dur)
    # 分段目录：--parts-dir 指定则**持久化**（跨进程复用，供 --only-batch 只重渲一批）；
    # 否则沿用临时目录并随进程删除（旧行为，逐字节等价）。
    if args.parts_dir:
        Path(args.parts_dir).mkdir(parents=True, exist_ok=True)
        _td_ctx = contextlib.nullcontext(str(Path(args.parts_dir).resolve()))
    else:
        _td_ctx = tempfile.TemporaryDirectory(prefix="lb_scenemap_")
    with _td_ctx as td:
        items3 = [(p, d, "video") for p, d, _, _ in items]

        # ── 分块渲染（2026-09-26 OOM 根治 · 005）─────────────────────────
        # 单个 ffmpeg 同时打开 119 路输入 ⇒ 实测 ≈136MB/路 × 119 ≈ 16GB 常驻，
        # WSL 上限 23GB ⇒ 确定性 OOM（内核已 6 次 OOM kill）。且实测证明与
        # -stream_loop 无关：全部改普通 -i 后仍在 13s 内涨到 16GB。
        # 故拆成「每批 ≤COMPOSE_CHUNK 镜的小 ffmpeg + concat demuxer 无损拼接」，
        # 批次边界优先落在章节起点/金句卡处（天然切点）。COMPOSE_CHUNK=0 → 旧行为。
        try:
            CHUNK = int(__import__("os").environ.get("COMPOSE_CHUNK", "24") or 0)
        except ValueError:
            CHUNK = 24
        _starts, _acc = [], 0.0
        for _p, _d, _k in items3:
            _starts.append(_acc)
            _acc += _d
        _starts.append(_acc)
        _plan_segs_full = getattr(plan, "segments", [])
        if len(_plan_segs_full) == len(chapters):
            _chapter_abs = [seg.start for seg in _plan_segs_full]
        else:
            _chapter_abs = VC._fallback_chapter_times(chapters, composer_text, full_dur)
        # 整片滤镜图（t_off=0）——用于打印字卡时间窗 + 取金句卡起点当批次切点。
        # 不执行 ffmpeg，仅建图+PIL 出图，开销秒级。
        _flt0, png_inputs, png_windows = VC.make_filter(
            plan, full_dur, quotes, args.book, args.author, composer_text, args.audio,
            items=items3, pure_video=True, no_cta=True, chapter_times_abs=_chapter_abs)
        del _flt0
        print("🗂️ 文字层时间窗（章节卡 / 金句卡）：")
        for _p, _w in zip(png_inputs, png_windows):
            _n = Path(_p).stem
            if _w is not None and (_n.startswith("card_") or _n.startswith("quote_")
                                   or _n.startswith("attr")):
                print(f"   {_n:12s} {_w[0]:7.2f} → {_w[1]:7.2f}s")
        print(f"🧮 分块渲染：COMPOSE_CHUNK={CHUNK}｜镜 {len(items3)}｜整片 {_acc:.1f}s")

        def _render_batch(items_sub, segs_sub, t_off, dur, out_path, is_final, tag,
                          pad_tail=0.0):
            sub_plan = scene_selector.ScenePlan(segments=segs_sub, duration=dur)
            flt, pngs, wins = VC.make_filter(
                sub_plan, dur, quotes, args.book, args.author, composer_text, args.audio,
                items=items_sub, pure_video=True, no_cta=True,
                t_off=t_off, global_dur=full_dur,
                chapter_times_abs=_chapter_abs, is_final_chunk=is_final)
            cmd = ["ffmpeg", "-y", "-v", "error"]
            # 仅当镜头时长 > 素材实长时才 -stream_loop -1（fit_shot_durations 已按素材
            # 实长封顶 ⇒ 正常情况 0 路循环）；COMPOSE_LOOP=all 回退旧行为。
            _loop_mode = __import__("os").environ.get("COMPOSE_LOOP", "auto").lower()
            _n_loop = _n_plain = 0
            for p, _d, _k in items_sub:
                _need = True
                if _loop_mode != "all":
                    try:
                        _clip = C.probe_duration(str(p)) or 0.0
                    except Exception:
                        _clip = 0.0
                    _need = bool(_clip > 0 and _d > _clip + 0.05)
                if _need:
                    cmd += ["-stream_loop", "-1", "-i", p]; _n_loop += 1
                else:
                    cmd += ["-i", p]; _n_plain += 1
            for png, win in zip(pngs, wins):
                if win is None:
                    cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)]
                else:
                    st, et = win
                    cmd += ["-itsoffset", f"{st:.3f}", "-loop", "1",
                            "-t", f"{max(0.5, et - st):.3f}", "-i", str(png)]
            _map, _dur_req = "[vout]", dur
            if pad_tail > 0.01:
                # 末批补齐到整片时长（tpad 克隆尾帧）——镜头总和可能比音频短 Ns
                # （稿首预卷未被镜头覆盖），不补则 -shortest 会截掉片尾 AI 声明（门禁①）
                flt += f";[vout]tpad=stop_mode=clone:stop_duration={pad_tail:.3f}[voutp]"
                _map, _dur_req = "[voutp]", dur + pad_tail
            cmd += ["-filter_complex", flt, "-map", _map,
                    "-c:v", "libx264", "-preset", "faster", "-crf", "23",
                    "-t", f"{_dur_req:.3f}", str(out_path)]
            print(f"🎬 {tag}：{len(items_sub)} 镜 / {dur:.1f}s（整片 {t_off:.1f}s 起）｜"
                  f"普通 {_n_plain} 路 / 循环 {_n_loop} 路视频 + {len(pngs)} 路字卡"
                  + (f"｜尾补齐 {pad_tail:.2f}s" if pad_tail > 0.01 else ""), flush=True)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10800)
            if r.returncode != 0:
                print(f"❌ {tag} 合成失败:", r.stderr[-1200:])
                sys.exit(1)

        _only = _parse_only_batch(args.only_batch)
        vout = Path(td) / "video_noaudio.mp4"
        if CHUNK <= 0 or len(items3) <= CHUNK:
            if _only and 1 not in _only:
                print(f"❌ --only-batch {sorted(_only)} 越界：实际共 1 批"
                      f"（镜数 {len(items3)} ≤ COMPOSE_CHUNK={CHUNK}）")
                sys.exit(2)
            _render_batch(items3, segs, 0.0, full_dur, vout, True, "合成中")
        else:
            # 候选切点：章节起点 ∪ 每 CHUNK 镜 ∪ 金句卡窗口起点（天然切点，避免突兀硬切）
            _cand = set(range(CHUNK, len(items3), CHUNK))
            for _i, _sg in enumerate(segs):
                if _i and getattr(_sg, "chapter_idx", 0) != getattr(segs[_i - 1], "chapter_idx", 0):
                    _cand.add(_i)
            for _w in png_windows:
                if _w is not None and len(_w) == 2:
                    _t, _j = float(_w[0]), 1
                    for _k in range(len(_starts) - 1):
                        if _starts[_k] <= _t:
                            _j = _k + 1
                    _cand.add(min(_j, len(items3) - 1))
            _bounds = [0]
            for _c in sorted(x for x in _cand if 0 < x < len(items3)):
                if _c - _bounds[-1] >= max(8, CHUNK // 2):
                    _bounds.append(_c)
            if _bounds[-1] != len(items3):
                _bounds.append(len(items3))
            _pairs = []
            for _bi in range(len(_bounds) - 1):
                _i0, _i1 = _bounds[_bi], _bounds[_bi + 1]
                while _i1 - _i0 > CHUNK:            # 兜底：单批硬上限
                    _pairs.append((_i0, _i0 + CHUNK)); _i0 += CHUNK
                _pairs.append((_i0, _i1))
            print("🧩 批次切点(镜下标)：" + " | ".join(f"{a}-{b}" for a, b in _pairs))
            _bad_only = sorted(n for n in _only if not (1 <= n <= len(_pairs)))
            if _bad_only:
                print(f"❌ --only-batch {_bad_only} 越界：实际共 {len(_pairs)} 批"
                      f"（1..{len(_pairs)}）")
                sys.exit(2)
            _parts = []
            _n_render = _n_reuse = 0
            for _bi, (_i0, _i1) in enumerate(_pairs):
                _pth = Path(td) / f"video_part{_bi:02d}.mp4"
                if _only and (_bi + 1) not in _only:     # ── 非目标批：复用旧分段 ──
                    if not _pth.exists():
                        print(f"❌ 批 #{_bi+1} 非目标批但无可用分段 {_pth}；"
                              f"请先整片渲一次（--parts-dir 指定同一目录）"
                              f"→ exit 6（绝不静默整片重渲）")
                        sys.exit(6)
                    _sc = _part_sidecar_check(_pth, items3[_i0:_i1], _i0, _i1,
                                              _starts[_i0], _starts[_i1] - _starts[_i0])
                    if _sc:
                        print(f"❌ 批 #{_bi+1} 分段指纹不一致：{_sc} → exit 7"
                              f"（防「旧几何分段拼新几何片」）")
                        sys.exit(7)
                    print(f"♻️ 批 #{_bi+1}：复用 {_pth.name}"
                          f"（{_pth.stat().st_size/1e6:.1f} MB）", flush=True)
                    _parts.append(_pth); _n_reuse += 1
                    continue
                _off = _starts[_i0]
                _dur = _starts[_i1] - _off
                _pad = 0.0
                if _bi == len(_pairs) - 1:          # 末批补齐到整片时长（与旧 -t full_dur 同口径）
                    _pad = max(0.0, (full_dur - _off) - _dur) + 0.3
                _render_batch(items3[_i0:_i1], segs[_i0:_i1], _off, _dur, _pth,
                              _bi == len(_pairs) - 1, f"分块 {_bi + 1}/{len(_pairs)}",
                              pad_tail=_pad)
                _part_sidecar_write(_pth, items3[_i0:_i1], _i0, _i1, _off, _dur)
                _parts.append(_pth); _n_render += 1
            print(f"🧾 本批渲染 {_n_render} 批 / 复用 {_n_reuse} 批")
            _lst = Path(td) / "concat.txt"
            _lst.write_text("".join(f"file '{p}'\n" for p in _parts), encoding="utf-8")
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                                "-i", str(_lst), "-c", "copy", str(vout)],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                print("⚠️ concat -c copy 失败 → 回退重编码拼接:", r.stderr[-300:])
                r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                                    "-i", str(_lst), "-c:v", "libx264", "-preset", "faster",
                                    "-crf", "23", "-pix_fmt", "yuv420p", str(vout)],
                                   capture_output=True, text=True, timeout=10800)
                if r.returncode != 0:
                    print("❌ 分块拼接失败:", r.stderr[-800:])
                    sys.exit(1)
            print(f"🔗 分块拼接完成（{len(_parts)} 批）")
        print("🎵 混入音频（loudnorm -16）...")
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(vout), "-i", args.audio,
             "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "-1",
             "-c:v", "copy", "-c:a", "aac", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-b:a", "128k", "-movflags", "+faststart", "-shortest", args.output],
            capture_output=True, text=True, timeout=600)
        if r2.returncode != 0:
            print("❌ 混音失败:", r2.stderr[-500:])
            sys.exit(1)
    print(f"✅ 完成！输出: {args.output}")


def pick_items_dedup(root, chapters, times, lines, scene_map, motion, total, n_ch,
                     poster_dir, avail, exclude, allow_static):
    """选材入口（2026-09-19 起默认走全局唯一分配）。
    QY_ALLOC=legacy 可回退到旧「迭代排除」实现（仅排障用）。"""
    import os as _os
    if _os.environ.get("QY_ALLOC", "global").lower() == "legacy":
        print("⚠️ QY_ALLOC=legacy → 使用旧迭代排除实现（可能残留同源复用）")
        segs, items, titles = pick_items_dedup_legacy(root, chapters, times, lines, scene_map,
                                                      motion, total, n_ch, poster_dir, avail,
                                                      exclude, allow_static)
    else:
        segs, items, titles = pick_items_dedup_global(root, chapters, times, lines, scene_map,
                                                      motion, total, n_ch, poster_dir, avail,
                                                      exclude, allow_static)
    _dump_items(items)
    n = len(items)
    uniq = len(set(i[0] for i in items))
    print(f"🔒 全局唯一分配自检：{n} 镜 | 素材去重 {uniq}/{n} "
          f"{'✅ 零同源复用' if uniq == n else '❌ 仍有复用'}")
    # 内容级复核（含同源双胞胎：不同文件同 md5）—— 有残留写标记文件，交门禁拦截，绝不静默放行
    try:
        _g = {}
        for _i, _it in enumerate(items):
            _g.setdefault("md5:" + md5_of(_it[0]), []).append(f"{_it[3]}/{Path(_it[0]).name}")
        _d = {h: g for h, g in _g.items() if len(g) > 1}
        if _d:
            import json as _json
            Path("/tmp/qc_dups_unresolved.json").write_text(
                _json.dumps(_d, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"❌ 内容级复核：{len(_d)} 组同源重复 → /tmp/qc_dups_unresolved.json（门禁须拦截）")
        else:
            print("✅ 内容级复核：无同源重复（含双胞胎检查）")
            Path("/tmp/qc_dups_unresolved.json").unlink(missing_ok=True)
    except Exception as e:
        print(f"⚠️ 内容级复核失败: {e}")
    return segs, items, titles


# ⚠️ 2026-09-20 修复：`main()` 的调用必须放在**所有函数定义之后**。
# 原文件把 `if __name__ == "__main__": main()` 放在 `pick_items_dedup`（见上）**之前**，
# 导致以脚本方式运行（python3 scripts/compose_book.py ...）时 main() 先执行、
# 而 pick_items_dedup 尚未定义 → NameError（以 import 方式运行不受影响，所以此前测试漏掉）。
# 影响面：任何直接调用本脚本的生产流程都会在选材阶段直接崩，必须走在 `__main__` 之前定义。
if __name__ == "__main__":
    main()
