#!/usr/bin/env python3
"""《深夜食堂》单跑合成包装器（不改 scripts/ 受管文件）

为什么要包装：
1) compose_scene_map.split_chapters() 按【画面】标记组切章，本稿 18 组 ≠ scene_map 8 章
   → 直接退出。本稿 8 个 `#` 标题与 scene_map 8 章严格一一对应，改按标题切章。
2) compose_scene_map 的章节卡标题由 scene_map 标签派生（"第{k+1}章 + name"），
   本稿标签本身已是「第一章 红香肠与玉子烧」，会派生出「第二章 第一章 …」重名
   → 这里直接用标签，第 0 章（书名章）给「开场：深夜食堂」→ 渲染成「序章 / 深夜食堂」。
3) video_composer._fallback_chapter_times 按「含标记的全文字符比例」估算章节卡时间，
   本稿标记行占比高，实测比真实朗读位置早最多 18.5s（芒果街同类错位）
   → 补丁为「朗读字符比例」，与 pick_items 的章节时间窗同源。

用法：
  python3 /tmp/audit005/compose_deep.py --audio ... --output ... [--dry-run]
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/mnt/d/AI软件/GitHub/bookmadebook")
sys.path.insert(0, str(REPO / "scripts"))

import compose_scene_map as C           # noqa: E402
import video_composer as VC             # noqa: E402
import scene_selector                   # noqa: E402

MARKER_LINE = re.compile(r"^\s*【[^】]+】\s*$")


def extract_quotes_full(script_text: str) -> list:
    """金句字卡文本：取【金句】「…」引号内**完整**内容（不按句号截断）。

    video_composer.extract_quotes 会在第一个 。！？ 处截断，本稿两处金句是
    一问一答（"…有没有维也纳香肠？老板问：要不要切成章鱼形状？"）、
    以及收尾反问（"…会不会有客人来？喔，还不少喔！"），截断后只剩提问半句，
    字卡会看得莫名其妙。这里保留完整引文（长度仍限 6-40 字，与既有规格一致）。
    """
    out = []
    for m in re.finditer(r"【金句】\s*([^【】\n]{8,120})", script_text):
        q = m.group(1).strip()
        inner = re.findall(r"「([^「」]{4,80})」", q)
        if inner:
            q = inner[-1]
        q = q.strip().strip("「」\"")
        if 6 <= len(q) <= 40 and q not in out:
            out.append(q)
    return out[:6]


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


def pick_items_dedup(root, chapters, times, lines, scene_map, motion, total, n_ch,
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
    for it in range(3):
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
                   if gj not in used and sig_dist(sigs[gi], sigs[gj]) <= 5.0]
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
        if added_total + len(plan) > 0.2 * pool_n:
            print(f"  ⚠️ 内容去重本轮拟排除 {len(plan)} 段（累计 {added_total + len(plan)}/{pool_n} > 20%）"
                  f"→ 停止去重，保留当前选材（避免把章节池抽干）")
            return segs, items, titles
        added = 0
        for rel in plan:
            if rel not in excl:
                excl.add(rel); added += 1
        print(f"  🧹 第 {it+1} 轮发现 {len(dups)} 组同源重复 → 追加排除 {added} 段后重挑")
        added_total += added
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


def chapter_card_title(label: str, k: int) -> str:
    """章节卡标题：首章=开场（渲染成「序章 / 书名」），其余标签本身已合规。"""
    if k == 0:
        return "开场：深夜食堂"
    return label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--scene-map", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--book", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--motion-cache", default=None)
    ap.add_argument("--exclude", default=None)
    ap.add_argument("--allow-static", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for a in ("script", "scene_map", "audio", "output", "motion_cache"):
        setattr(args, a, str(Path(getattr(args, a)).resolve()))

    lines = Path(args.script).read_text(encoding="utf-8").splitlines()
    sm = json.load(open(args.scene_map, encoding="utf-8"))
    scene_map, avail = sm["scene_map"], sm.get("available") or {}
    root = Path(sm["scene_root"])
    if not root.is_absolute():        # 运动量缓存 key 是绝对路径，相对路径会 miss 并逐段现算
        root = REPO / root
    motion = C.load_motion(args.motion_cache)

    full_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", args.audio], capture_output=True, text=True).stdout.strip())

    chapters = split_chapters_by_heading(lines, scene_map)
    n_ch = len(chapters)
    titles = [c[0] for c in chapters]
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


    card_titles = [chapter_card_title(lb, k) for k, (lb, _, _) in enumerate(chapters)]
    composer_text = C.build_text_with_chapters(lines, chapters, card_titles)
    quotes = extract_quotes_full(composer_text)
    print('💬 金句字卡(完整引文): ' + ' | '.join(quotes))
    print(f"💬 金句字卡: {len(quotes)} 句 → {quotes}")

    poster_dir = Path(tempfile.mkdtemp(prefix="lb_posters_"))
    exclude = set(json.load(open(args.exclude, encoding="utf-8"))) if args.exclude else set()
    allow_static = set(json.load(open(args.allow_static, encoding="utf-8"))) if args.allow_static else set()
    if exclude:
        print(f"🚫 人工复核排除 {len(exclude)} 段（来自 {Path(args.exclude).name}）")

    segs, items, _ = pick_items_dedup(root, chapters, times, lines, scene_map, motion,
                                      full_dur, n_ch, poster_dir, avail, exclude, allow_static)
    n_vid = len(items)
    print(f"🎬 共 {n_vid} 镜 | 素材去重 {len(set(i[0] for i in items))}/{n_vid}")

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
        print("\n逐镜清单：")
        for k, it in enumerate(items):
            ci = getattr(segs[k], "chapter_idx", -1)
            mark = "  ← 与上一镜同素材" if k and items[k][0] == items[k - 1][0] else ""
            print(f"   [{ci+1}] {it[3]:26s} {Path(it[0]).name:10s} {it[1]:5.1f}s{mark}")
        print(f"\nDRY-RUN 结论：{'✅ 四项全部通过' if ok else '❌ 存在不达标项'}")
        return

    plan = scene_selector.ScenePlan(segments=segs, duration=full_dur)
    with tempfile.TemporaryDirectory(prefix="lb_scenemap_") as td:
        items3 = [(p, d, "video") for p, d, _, _ in items]
        flt, png_inputs, png_windows = VC.make_filter(
            plan, full_dur, quotes, args.book, args.author, composer_text, args.audio,
            items=items3, pure_video=True, no_cta=True)
        print("🗂️ 文字层时间窗（章节卡 / 金句卡）：")
        for _p, _w in zip(png_inputs, png_windows):
            _n = Path(_p).stem
            if _w is not None and (_n.startswith("card_") or _n.startswith("quote_")
                                   or _n.startswith("attr")):
                print(f"   {_n:12s} {_w[0]:7.2f} → {_w[1]:7.2f}s")
        vout = Path(td) / "video_noaudio.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for p, _d, _k in items3:
            cmd += ["-stream_loop", "-1", "-i", p]
        for png, win in zip(png_inputs, png_windows):
            if win is None:
                cmd += ["-loop", "1", "-t", str(full_dur), "-i", str(png)]
            else:
                st, et = win
                cmd += ["-itsoffset", f"{st:.3f}", "-loop", "1",
                        "-t", f"{max(0.5, et - st):.3f}", "-i", str(png)]
        cmd += ["-filter_complex", flt, "-map", "[vout]",
                "-c:v", "libx264", "-preset", "faster", "-crf", "23",
                "-t", f"{full_dur}", str(vout)]
        print(f"🎬 合成中（{n_vid} 镜 / {full_dur:.0f}s，原速播放+黑场转场+章节卡+金句卡）...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10800)
        if r.returncode != 0:
            print("❌ 合成失败:", r.stderr[-1200:])
            sys.exit(1)
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


if __name__ == "__main__":
    main()
