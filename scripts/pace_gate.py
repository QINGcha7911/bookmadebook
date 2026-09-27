#!/usr/bin/env python3
"""交付前语速门禁（A 项 · 2026-09-25）

用途：拿到成片或独立音频后，自动体检三项语速指标，超标即 FAIL（退出码 1）。
依据：5 本实测 + 停顿调度器设计（target 停顿占比 13%）

判据（可用 --relax 放宽为记录级）：
  综合语速   4.00 – 4.70 字/秒   ← 听众感受到的节奏
  发音速率   5.00 – 5.80 字/秒   ← 朗读本身快慢
  停顿占比   0.11 – 0.16        ← 静音占比（超标 = 空洞/赶）

用法:
  python3 scripts/pace_gate.py 成片.mp4
  python3 scripts/pace_gate.py 音频.mp3 --json /tmp/pace_report.json
  python3 scripts/pace_gate.py x.mp4 --relax      # 只报警不算失败
"""
import argparse, json, sys, statistics as st

TH = {"综合语速": (4.00, 4.70), "发音速率": (4.80, 5.80), "停顿占比": (0.11, 0.16)}
GAP_TH = 0.25


def measure(path):
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(path, language="zh", word_timestamps=True,
                                   vad_filter=True, beam_size=1)
    words = []
    for s in segments:
        for w in (s.words or []):
            ww = (w.word or "").strip()
            if ww:
                words.append((w.start, w.end, len(ww)))
    if not words:
        return None
    T0, T1 = words[0][0], words[-1][1]
    dur = T1 - T0
    speech = sum(e - s for s, e, _ in words)
    chars = sum(n for _, _, n in words)
    gaps = [words[i + 1][0] - words[i][1] for i in range(len(words) - 1)]
    real = [g for g in gaps if g > GAP_TH]
    W = 20.0
    curve = []
    t = T0
    while t < T1:
        ws = [x for x in words if t <= x[0] < t + W]
        if ws:
            c = sum(n for _, _, n in ws)
            sp = sum(e - s for s, e, _ in ws)
            span = min(t + W, T1) - ws[0][0]
            curve.append({"t": round(t, 1), "cps_total": round(c / max(span, .1), 2),
                          "cps_speech": round(c / max(sp, .1), 2)})
        t += W
    return {"时长s": round(dur, 1), "字数": chars,
            "综合语速": round(chars / dur, 2),
            "发音速率": round(chars / speech, 2),
            "停顿占比": round(sum(real) / dur, 3),
            "真停顿条数": len(real),
            "最长停顿s": round(max(real), 2) if real else 0,
            "曲线CV": round(st.pstdev([c["cps_total"] for c in curve]) / st.mean([c["cps_total"] for c in curve]), 3) if len(curve) > 1 else 0,
            "曲线": curve}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json")
    ap.add_argument("--relax", action="store_true")
    a = ap.parse_args()
    m = measure(a.path)
    if not m:
        print("❌ 无法测量（无词/音频不可读）—— 判定数 0 ⇒ 视为未跑，不得放行")
        return 2
    print(f"📊 {a.path}")
    print(f"   时长 {m['时长s']}s ｜ 字数 {m['字数']} ｜ 真停顿 {m['真停顿条数']} 条（最长 {m['最长停顿s']}s）")
    bad = []
    for k, (lo, hi) in TH.items():
        v = m[k]
        ok = lo <= v <= hi
        print(f"   {'✓' if ok else '✗'} {k}: {v}" + ("" if ok else f"  （要求 {lo}–{hi}）"))
        if not ok:
            bad.append(k)
    print(f"   · 节奏曲线 CV: {m['曲线CV']}（越小越稳）")
    if a.json:
        json.dump(m, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"   → {a.json}")
    if bad:
        print(("⚠️ 记录级（--relax）" if a.relax else "❌ FAIL") + "：超标项 " + "、".join(bad))
        return 0 if a.relax else 1
    print("✅ PASS：三项语速指标全部达标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
