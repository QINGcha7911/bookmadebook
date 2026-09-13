#!/usr/bin/env python3
"""按「章节→素材目录」映射合成精读视频（2026-09-12 新增，《平场之月》重制专用）

与 video_composer 的差别：素材不再来自单一主题池（一个池循环到头，
容易出现"讲日本小城却配英式壁炉"），而是按 scene_map 的章节→目录映射
逐章取用——讲医院用医院素材、讲居酒屋用居酒屋素材。

渲染层（xfade 转场 / 黑场 / 章节卡 / 书名卡 / AI 角标 / 进度条 / 情绪调色）
直接复用 video_composer.make_filter，保证与既有交付同规格、同观感。

用法：
  python3 scripts/compose_scene_map.py \
    --script bookmadebook-output/讲书稿_平场之月_v3.txt \
    --scene-map assets/scenes/hiraba_jp_scene_map.json \
    --audio bookmadebook-output/平场之月_v3_10min.mp3 \
    --book 平场之月 --output out_raw.mp4 [--until-chapter 3]

--until-chapter N：只出到第 N 章结束（样片用），默认全片。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_ORIG_CWD = Path.cwd()                 # video_composer 导入时会 chdir 到 scripts/，先记住现场
sys.path.insert(0, str(Path(__file__).resolve().parent))

import video_composer as VC           # noqa: E402  复用转场/文字层/调色
import scene_selector                  # noqa: E402
import text_layers                     # noqa: E402

os.chdir(_ORIG_CWD)                    # 恢复工作目录（相对路径参数按调用方 cwd 解析）

SHOT_LEN = 7.0          # 目标单镜头时长（调度要求 ~7s）
MIN_MOTION = 2.0        # 0.5s 帧差下限：低于此判为静止镜头，弃用（白名单池经 2.0 校准，各章均无重复）
CHAPTER_MARKER = re.compile(r"^\s*【画面[:：]")   # 章节起点标记（成组出现）
MARKER_LINE = re.compile(r"^\s*【[^】]+】\s*$")


def load_motion(cache_path: str) -> dict:
    try:
        return json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        return {}


def probe_duration(path: str) -> float:
    """素材时长（秒）——用于「镜头时长自适应」，避免短视频被 stream_loop 接成可见循环。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def probe_motion(path: str) -> dict:
    """0.5s 帧差均值（与 007 素材运动量口径一致）。"""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"mean": 0.0, "n": 0}
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    step = max(1, int(round(fps * 0.5)))
    prev, i, ds = None, 0, []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % step == 0:
            g = cv2.cvtColor(cv2.resize(fr, (160, 284)), cv2.COLOR_BGR2GRAY).astype(np.int16)
            if prev is not None:
                ds.append(float(np.abs(g - prev).mean()))
            prev = g
        i += 1
    cap.release()
    a = np.array(ds) if ds else np.array([0.0])
    return {"mean": round(float(a.mean()), 2), "n": len(ds)}


def split_chapters(lines: list, scene_map: list) -> list:
    """把讲书稿按【画面】标记组切成章节（组数=章节数；不足时再按语义切分）。

    返回 [(章节标题, 起始行号0based, 结束行号0based含)]。
    """
    marks = []           # 每个【画面】组的首行号（组内连续标记算一组）
    prev_mark = -5
    for i, ln in enumerate(lines):
        if CHAPTER_MARKER.match(ln):
            if i != prev_mark + 1:
                marks.append(i)
            prev_mark = i
    # 标记组数 < 章节数时，按语义补切（Ch3→Ch4 的日常段起点）
    extra = [i for i, ln in enumerate(lines) if ln.startswith("从那以后，青砥开始常去须藤家")]
    bounds = sorted(set(marks + extra))
    if len(bounds) != len(scene_map):
        print(f"❌ 章节切分不符：标记组 {len(marks)} + 语义补切 {len(extra)} = {len(bounds)}，"
              f"scene_map 有 {len(scene_map)} 章")
        sys.exit(2)
    out = []
    for k, st in enumerate(bounds):
        en = bounds[k + 1] - 1 if k + 1 < len(bounds) else len(lines) - 1
        while en > st and not lines[en].strip():   # 收尾去空行
            en -= 1
        out.append((scene_map[k][0], st, en))
    return out


def chapter_times(lines: list, chapters: list, audio_dur: float) -> list:
    """章节起点时间：按「朗读字符数」比例映射（标记行/标题行不朗读，不计入）。

    上一版按含标记的全文字符比例映射，标记成组出现时会整体前偏；
    这里改用朗读字符口径（已验证章节卡误差 ±0.2s 级别）。
    """
    spoken_idx = []          # 每行朗读字符数
    for ln in lines:
        if MARKER_LINE.match(ln) or ln.lstrip().startswith("#"):
            spoken_idx.append(0)
        else:
            spoken_idx.append(len(re.findall(r"[\u4e00-\u9fff]", ln)))
    total = sum(spoken_idx)
    times = []
    for _, st, _ in chapters:
        times.append(audio_dur * sum(spoken_idx[:st]) / max(total, 1))
    return times


def build_text_with_chapters(lines: list, chapters: list, titles: list) -> str:
    """注入 ## 章节标题：供章节卡与情绪调色使用（标题行不朗读）。"""
    out = list(lines)
    for (_, st, _), t in sorted(zip(chapters, titles), key=lambda x: -x[0][1]):
        out.insert(st, f"## {t}")
    return "\n".join(out)


def chapter_dirs(chapter_label: str, dirs: list, lines: list, st: int, en: int) -> list:
    """章节可用目录顺序 = scene_map 里的顺序（007 已把主场景目录排在前面）。

    章节内按该顺序轮转取素材，保证：讲医院时全是医院/候诊/小卖部素材，
    讲居酒屋时全是居酒屋/清酒/烤鸡串素材——不跨章混用。
    """
    return list(dirs)


def fit_shot_durations(files: list, span: float, n_shots: int) -> list:
    """把章节总时长 span 分配给 n_shots 个镜头，且每镜不超过素材实长（不产生循环）。

    素材普遍长于基准镜长时退化为等分（与旧行为一致）；有短视频时用其全长，
    余量按「剩余可用时长」比例补给长素材，保证总时长严格等于 span。
    """
    base = span / max(1, n_shots)
    caps = [probe_duration(str(f)) for f in files]
    caps = [c if c > 1.0 else base for c in caps]          # 探测失败则回退等分
    durs = [min(base, c) for c in caps]
    for _ in range(6):
        need = span - sum(durs)
        if need <= 0.01:
            break
        head = [max(0.0, caps[i] - durs[i]) for i in range(len(durs))]
        tot_head = sum(head)
        if tot_head <= 0.01:
            break
        add = min(need, tot_head)
        for i in range(len(durs)):
            if head[i] > 0:
                durs[i] += add * (head[i] / tot_head)
    if sum(durs) < span:                                    # 全部素材都不够长 → 按比例补
        k = span / sum(durs)
        durs = [d * k for d in durs]
    durs[-1] += span - sum(durs)                            # 收尾严格对齐
    return durs


def pick_items(root: Path, chapters: list, times: list, lines: list,
               scene_map: list, motion: dict, total: float,
               n_ch: int, poster_dir: Path, available: dict = None,
               exclude: set = None, allow_static: set = None) -> tuple:
    """逐章挑素材 → (plan 段列表, items, 章节标题列表)。"""
    segs, items, titles = [], [], []
    used_global, prev_path = set(), None
    for k in range(n_ch):
        label, st, en = chapters[k]
        dirs = chapter_dirs(label, scene_map[k][1], lines, st, en)
        titles.append(label)
        c0 = times[k]
        # 末章：样片截到 total；全片截到音频结尾
        c1 = times[k + 1] if (k + 1 < n_ch and k + 1 < len(chapters)) else total
        span = max(2.0, c1 - c0)
        n_shots = max(2, int(round(span / SHOT_LEN)))
        shot = span / n_shots
        # 目录池（每目录内按运动量降序、去静止镜头、按 md5 去重）
        pools, seen_md5 = {}, set()
        for d in dirs:
            # 严格只取 scene_map.available 列出的文件名——目录里其余文件是
            # 人脸/人影/复核剔除的隔离素材（如藏有真人的街道段），一律不得入池。
            names = (available or {}).get(d)
            if names is None:
                print(f"⚠️ 目录 {d} 不在 available 白名单内，跳过")
                continue
            # 人工复核排除（007 available 白名单里仍混有真人/手部/人影的素材）
            names = [n for n in names if f"{d}/{n}" not in (exclude or set())]
            fs = []
            for name in names:
                f = root / d / "video" / name
                if not f.exists():
                    print(f"⚠️ 白名单文件缺失：{f}")
                    continue
                m = motion.get(str(f), {}).get("mean")
                if m is None:
                    m = probe_motion(str(f))["mean"]
                    motion[str(f)] = {"mean": m}
                if m < MIN_MOTION and f"{d}/{name}" not in (allow_static or set()):
                    continue          # 静止镜头弃用；allow_static 里的干净静镜例外放行
                fs.append((m, f))
            fs.sort(key=lambda x: -x[0])
            keep = []
            for m, f in fs:
                key = (d, f.name)
                if key in seen_md5:
                    continue
                seen_md5.add(key)
                keep.append((m, f))
            if keep:
                pools[d] = keep
        if not pools:
            print(f"❌ 章节「{label}」无可运动量达标素材（映射目录：{dirs}）")
            sys.exit(3)
        # 镜头数自适应：若本章可用素材段数撑不起 SHOT_LEN 的节奏，就拉长单镜
        # （宁可镜头长一点，也不要让一个小池子循环出「肉眼可见的重复周期」——
        #  2026-09-12 实测 Ch2 池 8 段却排 13 镜，成片 6 镜一循环）。
        pool_total = sum(len(v) for v in pools.values())
        if pool_total < n_shots:
            print(f"  ℹ️ Ch{k+1} 池仅 {pool_total} 段 < 计划 {n_shots} 镜 → 单镜拉长至 "
                  f"{span/pool_total:.1f}s，避免池内循环复用")
            n_shots = max(2, pool_total)
            shot = span / n_shots
        order = [d for d in dirs if d in pools]
        # 选材分两步，兼顾「场景覆盖」与「不出现可见重复」：
        # ① 公平配额：每轮把出镜名额给「配额最少」的目录 → 稀缺池（居酒屋 2 段）
        #    不会被大池（清酒 7 段）淹没，每个映射目录都保证出镜；
        # ② 相邻打散：按「剩余名额最多且非上一目录」排序 → 相邻镜头必换目录换景，
        #    且优先消费未用过的素材（used_global），避免出现重复循环。
        selected = {d: [] for d in order}
        cursor = {d: 0 for d in order}
        quota = {d: 0 for d in order}
        assigned, last_dir = 0, None
        while assigned < n_shots:
            avail = [d for d in order if cursor[d] < len(pools[d])]
            if not avail:
                break
            cands = [d for d in avail if d != last_dir] or avail
            best = min(cands, key=lambda d: (quota[d], order.index(d)))
            # 「全书不重复」是偏好而非硬约束：只有当本池**未用过的素材仍够填满本章**
            # 时才跳过已用素材，否则尾部章节会被前面章节抽干（曾出现 Ch10 只出 1 镜、
            # fit_shot_durations 把 59s 全塞给单镜）。素材不够时必须放开复用。
            fresh_left = sum(1 for d in order for _m, f in pools[d]
                             if str(f) not in used_global)
            skip_used = (n_shots - assigned) <= fresh_left
            while cursor[best] < len(pools[best]):
                f = pools[best][cursor[best]][1]
                if (skip_used and str(f) in used_global) or str(f) == prev_path:
                    cursor[best] += 1
                    continue
                break
            if cursor[best] >= len(pools[best]):
                continue
            selected[best].append(pools[best][cursor[best]][1])
            quota[best] += 1
            cursor[best] += 1
            assigned += 1
            last_dir = best
        if assigned < n_shots:
            # 复用兜底（本章池被抽干）：按池轮转复用，只保证「相邻镜头不同素材」，
            # 宁可复用也不让单镜吃掉整章时长（2026-09-12 实测 Ch10 单镜 59s 缺陷）。
            order2 = [d for d in order if pools[d]]
            curs2 = {d: 0 for d in order2}
            guard = 0
            while assigned < n_shots and order2 and guard < 20000:
                guard += 1
                cands2 = [d for d in order2 if d != last_dir] or order2
                best2 = max(cands2, key=lambda d: (len(pools[d]) - curs2[d], -order.index(d)))
                f2 = pools[best2][curs2[best2] % len(pools[best2])][1]
                curs2[best2] += 1
                if str(f2) == prev_path and len(pools[best2]) > 1:
                    continue
                selected[best2].append(f2)
                quota[best2] += 1
                assigned += 1
                last_dir = best2
        buckets = {d: list(selected[d]) for d in order}
        remaining = {d: len(selected[d]) for d in order}
        picks, last_dir = [], None
        while len(picks) < assigned:
            cands = [d for d in order if remaining[d] > 0 and d != last_dir]
            if not cands:
                cands = [d for d in order if remaining[d] > 0]
                if not cands:
                    break
            best = max(cands, key=lambda d: (remaining[d], -order.index(d)))
            picks.append((best, buckets[best].pop(0)))
            remaining[best] -= 1
            last_dir = best
        if not picks:                                 # 极端兜底（全部被用过）
            picks.append((order[0], pools[order[0]][0][1]))
        if picks and prev_path:               # 跨章：章首避开上一章末镜素材
            for k2 in range(len(picks)):
                if str(picks[k2][1]) != prev_path:
                    if k2:
                        picks[0], picks[k2] = picks[k2], picks[0]
                    break
        # 镜头时长自适应：素材短于基准镜长时按素材实长切，余量分给仍有余量的镜头，
        # 避免 stream_loop 把素材尾接头 → 成片出现可见的短循环（验收项「无重复循环」）。
        durs = fit_shot_durations([f for _, f in picks], span, n_shots)
        t_cursor = c0
        for j, (d, f) in enumerate(picks):
            used_global.add(str(f))
            prev_path = str(f)
            sd = durs[j]
            seg = scene_selector.SceneSegment(
                theme=f"jp_daily/{d}", start=t_cursor, end=t_cursor + sd,
                chapter_title=label)
            t_cursor += sd
            setattr(seg, "chapter_idx", k)
            if j == 0:
                # 章节卡背景 = 本章首镜的定格帧（虚化压暗由 text_layers 处理）
                poster = poster_dir / f"ch{k+1}.jpg"
                subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(f),
                                "-frames:v", "1", "-vf", "scale=1080:-1",
                                "-q:v", "3", str(poster)], capture_output=True)
                if poster.exists():
                    seg.images = [str(poster)]
            segs.append(seg)
            items.append((str(f), sd, "video", d))
        print(f"  Ch{k+1} {label}: {n_shots} 镜 × {shot:.1f}s "
              f"| 目录 {len(pools)}/映射 {len(dirs)} | 池 {sum(len(v) for v in pools.values())}")
    return segs, items, titles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--scene-map", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--book", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--until-chapter", type=int, default=0, help="只出到第 N 章（样片）")
    ap.add_argument("--motion-cache", default="/tmp/audit005/jp_motion.json")
    ap.add_argument("--exclude", default=None, help="人工复核排除清单 JSON（元素为 目录/文件名）")
    ap.add_argument("--allow-static", default=None,
                    help="放行的干净静止镜头 JSON（元素为 目录/文件名，须人工复核无真人）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for a in ("script", "scene_map", "audio", "output", "motion_cache"):
        setattr(args, a, str(Path(getattr(args, a)).resolve()))

    lines = Path(args.script).read_text(encoding="utf-8").splitlines()
    sm = json.load(open(args.scene_map, encoding="utf-8"))
    scene_map = sm["scene_map"]
    root = Path(sm["scene_root"])
    motion = load_motion(args.motion_cache)

    full_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", args.audio], capture_output=True, text=True).stdout.strip())
    chapters = split_chapters(lines, scene_map)
    titles = [c[0] for c in chapters]
    print(f"📖 书名: {args.book} | 全片音频: {full_dur:.1f}s | 章节: {len(chapters)}")
    for k, (label, st, en) in enumerate(chapters):
        cjk = sum(len(re.findall(r"[\u4e00-\u9fff]", l)) for l in lines[st:en + 1]
                  if not MARKER_LINE.match(l))
        print(f"  Ch{k+1} {label}: 行 {st+1}-{en+1} 朗读CJK {cjk}")
    times = chapter_times(lines, chapters, full_dur)
    print("⏱️ 章节起点: " + " ".join(f"Ch{k+1}={t:.0f}s" for k, t in enumerate(times)))
    # 章节卡标题：由 scene_map 标签派生（"Ch2 重逢：医院走廊 / 小卖部" → "第二章 重逢"）
    card_titles = []
    for k, (label, _, _) in enumerate(chapters):
        name = re.sub(r"^Ch\d+\s*", "", label).split("：")[0].split(":")[0].strip()
        card_titles.append(f"第{k+1}章 {name}" if name else f"第{k+1}章")
    n_ch = len(chapters) if args.until_chapter <= 0 else min(args.until_chapter, len(chapters))
    # 样片只把前 n_ch 章文本交给 composer：否则 make_filter 会按全篇 10 章的字数比例
    # 把 10 张章节卡全压缩排进样片时长里（开场 1 分钟连弹数张卡，芒果街同类缺陷）。
    cut = chapters[n_ch - 1][2] + 1
    composer_text = build_text_with_chapters(lines[:cut], chapters[:n_ch], card_titles[:n_ch])
    total = times[n_ch] if n_ch < len(chapters) else full_dur
    print(f"🎯 本次输出时长: {total:.1f}s（{'全片' if n_ch == len(chapters) else f'前 {n_ch} 章样片'}）")
    quotes = VC.extract_quotes(composer_text)
    print(f"💬 金句字卡: {len(quotes)} 句" + (f" → {quotes}" if quotes else "（本稿无【金句】标记）"))
    poster_dir = Path(tempfile.mkdtemp(prefix="lb_posters_"))
    avail = sm.get("available") or {}
    exclude = set(json.load(open(args.exclude, encoding="utf-8"))) if args.exclude else set()
    allow_static = set(json.load(open(args.allow_static, encoding="utf-8"))) if args.allow_static else set()
    if exclude:
        print(f"🚫 人工复核排除 {len(exclude)} 段")
    segs, items, _ = pick_items(root, chapters, times, lines, scene_map, motion,
                                total, n_ch, poster_dir, avail, exclude, allow_static)
    n_vid = len(items)
    print(f"🎬 共 {n_vid} 镜 | 素材不重复: {len(set(i[0] for i in items))}/{n_vid}")
    if args.dry_run:
        for it in items:
            print(f"   {it[3]:42s} {Path(it[0]).name:10s} {it[1]:.1f}s")
        return
    plan = scene_selector.ScenePlan(segments=segs, duration=total)

    with tempfile.TemporaryDirectory(prefix="lb_scenemap_") as td:
        tmpdir = Path(td)
        audio_in = args.audio
        if total < full_dur - 0.05:      # 样片：裁音频+尾部淡出
            audio_in = str(tmpdir / "sample_audio.m4a")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", args.audio,
                            "-t", f"{total:.3f}", "-af",
                            f"afade=t=out:st={max(0.0, total-0.8):.2f}:d=0.8",
                            "-c:a", "aac", "-b:a", "128k", audio_in], check=True)
            print(f"✂️ 样片音频已裁至 {total:.1f}s（尾部 0.8s 淡出）")
        items3 = [(p, d, "video") for p, d, _, _ in items]
        flt, png_inputs, png_windows = VC.make_filter(
            plan, total, quotes, args.book, args.author, composer_text, audio_in,
            items=items3, pure_video=True, no_cta=True)
        vout = tmpdir / "video_noaudio.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for p, _d, _k in items3:
            cmd += ["-stream_loop", "-1", "-i", p]
        for png, win in zip(png_inputs, png_windows):
            if win is None:
                cmd += ["-loop", "1", "-t", str(total), "-i", str(png)]
            else:
                st, et = win
                cmd += ["-itsoffset", f"{st:.3f}", "-loop", "1",
                        "-t", f"{max(0.5, et - st):.3f}", "-i", str(png)]
        cmd += ["-filter_complex", flt, "-map", "[vout]",
                "-c:v", "libx264", "-preset", "faster", "-crf", "23",
                "-t", f"{total}", str(vout)]
        print(f"🎬 合成中（{n_vid} 镜 / {total:.0f}s，纯视频原样播放+黑场转场+章节卡）...")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10800)
        if r.returncode != 0:
            print("❌ 合成失败:", r.stderr[-800:])
            sys.exit(1)
        print("🎵 混入音频...")
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(vout), "-i", audio_in,
             "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "-1",
             "-c:v", "copy", "-c:a", "aac", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-b:a", "128k", "-movflags", "+faststart", "-shortest", args.output],
            capture_output=True, text=True, timeout=600)
        if r2.returncode != 0:
            print("❌ 混音失败:", r2.stderr[-400:])
            sys.exit(1)
    print(f"✅ 完成！输出: {args.output}")


if __name__ == "__main__":
    main()
