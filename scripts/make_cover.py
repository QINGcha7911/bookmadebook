#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书封面生成器（bookmadebook 早晚班生产线用）

设计依据（2026-09-19 实测诊断：《莫斯科绅士》封面点击率 5.6% vs 同类中位 8.6%）：
  旧做法 = 从成片抽一帧当封面 → 无人、无钩子、书名仅占画面高 1.5%，缩略图里看不见。

本脚本规则：
  ① 尺寸：1080×1440（3:4，小红书信息流裁切后的安全区）同时出 1080×1920（9:16）兼容版
  ② 一句钩子 ≤14 字，字号 ≥ 画面高 8%（1440 下 ≥ 115px）
  ③ 单一视觉焦点（底图居中裁切，人物/主体居中）
  ④ 左下书名+作者小字（吃搜索与品牌），右下「AI 生成内容」角标（合规）
  ⑤ 底部渐变压暗保证文字可读

用法：
  python3 scripts/make_cover.py \
      --book 莫斯科绅士 --author 埃默·托尔斯 \
      --hook "被软禁32年，他活成了最优雅的人" \
      --base assets/scenes/book_莫斯科绅士/grand_hotel_lobby_marble/video/01.mp4 \
      --out /tmp/cover_v1.jpg
"""
import argparse, json, subprocess, sys, tempfile, os, warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

W, H = 1080, 1440          # 3:4 主版
W9, H9 = 1080, 1920        # 9:16 兼容版
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"
FONT_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FALLBACK_BOLD = "/mnt/c/Windows/Fonts/msyhbd.ttc"
FALLBACK_REG  = "/mnt/c/Windows/Fonts/msyh.ttc"


EXCLUDE = set()


def load_exclude(path: str = ""):
    """读 <书>_excluded.json，得到 {目录/文件名} 集合（自动纠正常见的 video/ 多一层写法）。"""
    global EXCLUDE
    if not path:
        return
    f = Path(path)
    if not f.exists():
        return
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return
    keys = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (list, dict)):            # 目录级 → 展开成具体文件
                for item in (v if isinstance(v, list) else v.keys()):
                    keys.add(f"{k}/{str(item).lstrip('/')}")
            else:
                keys.add(str(k))
    elif isinstance(data, list):
        keys = {str(x) for x in data}
    EXCLUDE = {k.replace("/video/", "/") for k in keys}
    return EXCLUDE


def is_excluded(dirname: str, filename: str, keys) -> bool:
    if not keys:
        return False
    cand = {f"{dirname}/{filename}", f"{dirname}/video/{filename}"}
    return bool(cand & set(keys))


def detail_score(img: Image.Image) -> float:
    """画面信息量评分：边缘方差大 = 有细节；过亮/过暗（雾、空天、死黑）重罚。"""
    g = img.convert("L").resize((240, 426))
    edges = g.filter(ImageFilter.FIND_EDGES)
    data = list(edges.getdata())
    mean = sum(data) / len(data)
    var = sum((v - mean) ** 2 for v in data) / len(data)
    lum = sum(g.getdata()) / len(g.getdata()) / 255.0
    if lum < 0.16 or lum > 0.90:          # 死黑 / 死白 / 大雾
        var *= 0.25
    return var


def _probe_dur(p) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip() or 0)


def best_frame_from_video(video: Path, n: int = 12) -> Image.Image:
    """抽 n 帧评分，取信息量最大的一帧（避免固定抽 40% 抽到空镜）。"""
    dur = _probe_dur(video)
    tmpd = Path(tempfile.mkdtemp())
    best, best_s = None, -1.0
    for i in range(n):
        ts = max(0.5, dur * (i + 0.5) / n)
        f = tmpd / f"f{i}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(video),
                        "-frames:v", "1", "-q:v", "2", str(f)], check=False)
        if not f.exists():
            continue
        img = Image.open(f).convert("RGB")
        sc = detail_score(img)
        if sc > best_s:
            best, best_s = img, sc
    if best is None:
        sys.exit(f"[ERR] 无法从视频抽帧：{video}")
    return best


def load_frame(base: str) -> Image.Image:
    """底图：视频取 40% 处一帧；图片直接读。"""
    p = Path(base)
    if not p.exists():
        sys.exit(f"[ERR] 底图不存在：{base}")
    if p.is_dir():                                   # 传场景目录 → 目录内挑最佳帧（跳过已排除素材！）
        raw = sorted([q for q in p.rglob("*") if q.suffix.lower() in (".mp4", ".mov", ".mkv")])
        vids = [v for v in raw if not is_excluded(p.name, v.name, EXCLUDE)]
        if not vids:
            sys.exit(f"[ERR] 目录内无可用视频（全部被排除或为空）：{base}\n"
                     f"      该目录共 {len(raw)} 个文件，其中 {len(raw) - len(vids)} 个在排除清单里")
        if len(vids) < len(raw):
            print(f"[INFO] 已跳过 {len(raw) - len(vids)} 个被排除素材，剩余可用 {len(vids)} 个")
        cands, best, best_s = vids[:3], None, -1.0
        for v in cands:
            img = best_frame_from_video(v)
            sc = detail_score(img)
            if sc > best_s:
                best, best_s = img, sc
        return best
    if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
        return best_frame_from_video(p)
    return Image.open(p).convert("RGB")


def crop_fill(img: Image.Image, w: int, h: int) -> Image.Image:
    """居中裁切填满目标比例（不拉伸、不变形）。"""
    sr, tr = img.width / img.height, w / h
    if sr > tr:                      # 太宽 → 裁两侧
        nw = int(img.height * tr)
        img = img.crop(((img.width - nw) // 2, 0, (img.width + nw) // 2, img.height))
    else:                            # 太高 → 裁上下（略偏上，保住主体）
        nh = int(img.width / tr)
        top = int((img.height - nh) * 0.38)
        img = img.crop((0, top, img.width, top + nh))
    return img.resize((w, h), RESAMPLE)


def gradient(w: int, h: int, start: float = 0.42, strength: int = 205) -> Image.Image:
    """自 start 比例处向下的黑色渐变，保证文字可读。"""
    g = Image.new("L", (1, h), 0)
    px = g.load()
    for y in range(h):
        t = (y / h - start) / max(1e-6, (1 - start))
        px[0, y] = int(max(0.0, min(1.0, t)) ** 0.85 * strength)
    return g.resize((w, h))


def wrap_balanced(text: str, font, max_w: int) -> list:
    """折行优先在标点断（读起来像人写的），且避免末行只剩 1-2 字。"""
    lines = wrap_cjk(text, font, max_w)
    if len(lines) <= 1:
        return lines
    # 候选断点 = 所有标点后；优先选"两行长度最接近"的那个
    cands = []
    for i, ch in enumerate(text):
        if ch in "，。！？、；：":
            a, b = text[:i + 1], text[i + 1:]
            if b and font.getlength(a) <= max_w and font.getlength(b) <= max_w:
                cands.append((abs(font.getlength(a) - font.getlength(b)), i))
    if cands:
        i = min(cands)[1]
        cand = [text[:i + 1], text[i + 1:]]
        # 至少比硬折行更匀（末行不短于 3 字）才采用
        if len(cand[1]) >= 3 or len(cand[1]) >= len(lines[-1]):
            return cand
    if len(lines) == 2 and len(lines[1]) <= 2:      # 兜底：末行太短 → 从倒数第二行借字
        m = len(lines[0])
        moved = lines[0][-2:]
        if len(moved.strip()):
            return [lines[0][:-2], moved + lines[1]]
    return lines


def wrap_cjk(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list:
    """中文按宽度折行；英文按空格折。"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if font.getlength(cur + ch) <= max_w:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_text_block(d, xy, lines, font, fill, line_gap=18, anchor_x="left", outline=3):
    x, y = xy
    asc, desc = font.getmetrics()
    lh = asc + desc + line_gap
    for i, ln in enumerate(lines):
        yy = y + i * lh
        if anchor_x == "center":
            wl = font.getlength(ln)
            d.text((x - wl / 2, yy), ln, font=font, fill=fill,
                   stroke_width=outline, stroke_fill=(0, 0, 0, 170))
        else:
            d.text((x, yy), ln, font=font, fill=fill,
                   stroke_width=outline, stroke_fill=(0, 0, 0, 170))
    return y + len(lines) * lh


def badge(d, xy, text, font):
    """右下角「AI 生成内容」角标。"""
    x, y = xy
    pad_x, pad_y = 16, 10
    wl = font.getlength(text)
    asc, desc = font.getmetrics()
    bw, bh = wl + pad_x * 2, asc + desc + pad_y * 2
    d.rounded_rectangle([x - bw, y - bh, x, y], radius=12, fill=(0, 0, 0, 145))
    d.text((x - bw + pad_x, y - bh + pad_y), text, font=font, fill=(255, 255, 255, 235))


def build(base_img, book, author, hook, w, h, out_path, hook_ratio=0.085):
    img = crop_fill(base_img, w, h).convert("RGBA")

    # 渐变遮罩
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ov.putalpha(gradient(w, h))
    img = Image.alpha_composite(img, ov)

    d = ImageDraw.Draw(img)
    # 字号：钩子 ≥ 画面高 8%
    hook_size = max(110, int(h * hook_ratio))
    try:
        f_hook = ImageFont.truetype(FONT_BOLD, hook_size)
        f_book = ImageFont.truetype(FONT_BOLD, int(h * 0.032))
        f_auth = ImageFont.truetype(FONT_REG, int(h * 0.023))
        f_badge = ImageFont.truetype(FONT_REG, int(h * 0.017))
    except Exception:
        f_hook = ImageFont.truetype(FALLBACK_BOLD, hook_size)
        f_book = ImageFont.truetype(FALLBACK_BOLD, int(h * 0.032))
        f_auth = ImageFont.truetype(FALLBACK_REG, int(h * 0.023))
        f_badge = ImageFont.truetype(FALLBACK_REG, int(h * 0.017))

    # 钩子（大字，靠下 1/4）
    lines = wrap_balanced(hook, f_hook, int(w * 0.86))
    asc, desc = f_hook.getmetrics()
    block_h = len(lines) * (asc + desc + int(hook_size * 0.16))
    y0 = int(h * 0.70) - block_h // 2
    draw_text_block(d, (w * 0.07, y0), lines, f_hook, (255, 255, 255, 255),
                    line_gap=int(hook_size * 0.16), outline=max(3, hook_size // 34))

    # 左下：书名 + 作者
    yb = h - int(h * 0.105)
    draw_text_block(d, (w * 0.07, yb), [f"《{book}》"], f_book, (255, 255, 255, 240), outline=2)
    if author:
        d.text((w * 0.07, yb + int(h * 0.040)), author, font=f_auth,
               fill=(255, 255, 255, 205), stroke_width=2, stroke_fill=(0, 0, 0, 150))
    # 右下角标
    badge(d, (w * 0.95, h - int(h * 0.022)), "AI 生成内容", f_badge)

    img.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--author", default="")
    ap.add_argument("--hook", required=True, help="≤14 字最好；超了会自动折行")
    ap.add_argument("--base", required=True, help="底图或视频路径")
    ap.add_argument("--out", required=True, help="主版输出路径（3:4）")
    ap.add_argument("--also-916", action="store_true", help="同时输出 9:16 兼容版")
    ap.add_argument("--exclude", default="auto",
                    help="排除清单 json；默认 auto = assets/scenes/book_<书名>_excluded.json")
    a = ap.parse_args()

    if a.exclude == "auto":
        for c in (Path("assets/scenes") / f"book_{a.book}_excluded.json",
                  Path(__file__).resolve().parent.parent / "assets/scenes" / f"book_{a.book}_excluded.json"):
            if c.exists():
                a.exclude = str(c); break
    if a.exclude and a.exclude != "auto":
        load_exclude(a.exclude)
        print(f"[INFO] 排除清单 {len(EXCLUDE)} 条 ← {a.exclude}")

    if len(a.hook) > 16:
        print(f"[WARN] 钩子 {len(a.hook)} 字，超过建议的 14 字，缩略图可读性下降")

    base_img = load_frame(a.base)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build(base_img, a.book, a.author, a.hook, W, H, out)
    print(f"[OK] 3:4 主版 → {out}  ({W}×{H})")
    if a.also_916:
        o9 = out.with_name(out.stem + "_916.jpg")
        build(base_img, a.book, a.author, a.hook, W9, H9, o9)
        print(f"[OK] 9:16 兼容版 → {o9}  ({W9}×{H9})")


if __name__ == "__main__":
    main()
