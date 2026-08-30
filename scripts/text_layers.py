#!/usr/bin/env python3
"""text_layers.py —— PIL 预渲染文字 PNG 层（替代 drawtext）

设计依据：multi-agent 研讨《bookmadebook 竖版视频视觉设计方案 v2》
- 所有文字层渲染为透明底 PNG，由 ffmpeg overlay 叠加（解决 drawtext 中文转义/断行/描边三大坑）
- 三段式布局：① 顶部书名/章节条 ② 中部金句（居中 y≈980） ③ 底部进度条 + 署名
- 安全框：x 140-920 / y 220-1600（小红书 UI 遮挡约束）
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920

# 字体解析：系统 Noto CJK（OFL 许可）> Windows 系统字体 > fc-match 兜底
# 注意：不再随仓库分发专有字体（微软雅黑 msyh.ttc 再分发违反许可，已移除 2026-08-14）
_PROJ_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_CANDIDATES = {
    "bold": [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/mnt/c/Windows/Fonts/msyhbd.ttc"),  # Windows 系统字体（本地使用）
        Path("C:/Windows/Fonts/msyhbd.ttc"),
    ],
    "serif": [
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        Path("/mnt/c/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
    ],
}

_font_cache = {}
_KEEPALIVE = []  # 临时目录保活（防止 GC 删除已渲染的 PNG）


def resolve_font(role: str = "bold") -> str:
    """解析字体路径：项目 assets/fonts > 系统 Noto > fc-match 兜底"""
    if role in _font_cache:
        return _font_cache[role]
    for p in FONT_CANDIDATES.get(role, []):
        if p.exists():
            _font_cache[role] = str(p)
            return str(p)
    import subprocess
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", "sans-serif:lang=zh"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            _font_cache[role] = out
            return out
    except Exception:
        pass
    return ""


def get_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """获取指定字号字体"""
    key = f"{role}:{size}"
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(resolve_font(role), size)
    return _font_cache[key]


def wrap_by_px(text: str, font, max_width: int = 640) -> list:
    """按像素宽度断行（语义断行优先，不硬切词）"""
    # 先按标点切分语义单元
    units = []
    cur = ""
    for ch in text:
        cur += ch
        if ch in "，。！？；、——「」" or ch == " ":
            units.append(cur)
            cur = ""
    if cur:
        units.append(cur)
    lines, line = [], ""
    for unit in units:
        if font.getlength(line + unit) <= max_width:
            line += unit
        else:
            if line:
                lines.append(line)
            line = unit
    if line:
        lines.append(line)
    return lines or [text]


def _center_x(draw, text, font) -> int:
    """水平居中 x 坐标（相对画布）"""
    bb = draw.textbbox((0, 0), text, font=font)
    return (W - (bb[2] - bb[0])) // 2 - bb[0]


def render_book_title(title: str, font_size: int = 84) -> Image.Image:
    """① 顶部书名层：白字黑描边，居中，y≈250"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("bold", font_size)
    x = _center_x(d, title, font)
    y = 250 - font_size // 2
    # 阴影
    d.text((x + 4, y + 5), title, font=font, fill=(0, 0, 0, 110))
    # 主体 + 描边
    d.text((x, y), title, font=font, fill=(255, 255, 255, 255),
           stroke_width=5, stroke_fill=(0, 0, 0, 200))
    return img


def render_chapter_tag(title: str, font_size: int = 40) -> Image.Image:
    """② 章节标签层：顶部短线 + 白字描边，y≈400（章节切换闪现）"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("serif", font_size)
    x = _center_x(d, title, font)
    y = 400
    # 主题色短线（书签意象）
    d.rounded_rectangle([x - 20, y - 6, x + 20, y - 2], radius=2,
                        fill=(201, 160, 99, 230))
    d.text((x, y), title, font=font, fill=(255, 255, 255, 235),
           stroke_width=3, stroke_fill=(0, 0, 0, 160))
    return img


def render_quote(quote: str, quote_no: int = 0, total: int = 1,
                 font_size: int = 64) -> Image.Image:
    """③ 金句层：白字黑描边+阴影，语义断行 ≤3 行，块中心 y≈980"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("bold", font_size)
    lines = wrap_by_px(quote, font, max_width=640)
    lines = lines[:3]  # 最多 3 行
    line_h = int(font_size * 1.35)
    # 垂直居中公式：首行 y = 980 - (n-1)*L/2 - fontsize/2
    n = len(lines)
    y = 980 - (n - 1) * line_h // 2 - font_size // 2
    for line in lines:
        x = _center_x(d, line, font)
        # 阴影（右下偏移）
        d.text((x + 4, y + 5), line, font=font, fill=(0, 0, 0, 120))
        # 主体 + 描边
        d.text((x, y), line, font=font, fill=(255, 255, 255, 255),
               stroke_width=4, stroke_fill=(0, 0, 0, 190))
        y += line_h
    return img


def render_attribution(text: str, font_size: int = 40) -> Image.Image:
    """④ 出处层（—— 书名）：仅最后一句金句显示"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("serif", font_size)
    t = f"—— {text}"
    x = _center_x(d, t, font)
    y = 1180
    d.text((x, y), t, font=font, fill=(255, 255, 255, 210),
           stroke_width=2, stroke_fill=(0, 0, 0, 140))
    return img


def render_progress_track() -> Image.Image:
    """⑤ 进度条轨道层：y=1530 全宽细线，白色 22%"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([120, 1530, 900, 1536], radius=3, fill=(255, 255, 255, 56))
    return img


def render_cta(lines: list, font_size: int = 56) -> Image.Image:
    """⑨ 结尾 CTA 引导帧（2026-08-30 引入，蔡格尼克+互动权重×4）
    lines: 如 ["完整版精读在主页", "评论区报书名，帮你点单"]
    竖向排列居中，白字黑描边，y 中心 ≈980"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("bold", font_size)
    total_h = len(lines) * (font_size + 24)
    y = 980 - total_h // 2
    for ln in lines:
        x = _center_x(d, ln, font)
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=4, stroke_fill=(0, 0, 0, 200))
        y += font_size + 24
    return img


def render_progress_fill(accent: tuple = (216, 176, 74)) -> Image.Image:
    """⑥ 进度条填充层：金色，ffmpeg 端用 crop 表达式按时间增长"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([120, 1530, 900, 1536], radius=3,
                        fill=(accent[0], accent[1], accent[2], 217))
    # 前端圆点锚
    d.ellipse([893, 1523, 907, 1537], fill=(accent[0], accent[1], accent[2], 255))
    return img


def render_watermark(text: str, font_size: int = 28) -> Image.Image:
    """⑦ 水印层：左下角常驻小字"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("serif", font_size)
    d.text((140, 1420), text, font=font, fill=(255, 255, 255, 140))
    return img


def render_ai_badge(font_size: int = 26) -> Image.Image:
    """⑧ AI 生成角标层：右下角常驻（《人工智能生成合成内容标识办法》2025-09-01 合规）"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = get_font("serif", font_size)
    text = "AI 生成内容"
    # 半透明黑底圆角标签 + 白字，右下角
    tw = d.textlength(text, font=font)
    pad_x, pad_y = 20, 10
    x0, y0 = W - 60 - tw - pad_x * 2, H - 120
    x1, y1 = x0 + tw + pad_x * 2, y0 + font_size + pad_y * 2
    d.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=(0, 0, 0, 120))
    d.text((x0 + pad_x, y0 + pad_y), text, font=font, fill=(255, 255, 255, 200))
    return img


def render_all(book_title: str, quotes: list, chapters: list,
               author: str = "", watermark: str = "") -> dict:
    """一次渲染所有层，返回 {名称: PNG路径}
    临时目录引用保存在模块级 _KEEPALIVE 中，防止被 GC 删除"""
    import tempfile
    td = tempfile.TemporaryDirectory(prefix="lb_layers_")
    _KEEPALIVE.append(td)  # 模块级保活
    tmpdir = Path(td.name)
    layers = {}

    # ① 书名（首帧封面）
    layers["book"] = tmpdir / "book.png"
    render_book_title(book_title).save(layers["book"])

    # ② 章节标签（每章一个）
    for i, ch in enumerate(chapters):
        if ch:
            p = tmpdir / f"chapter_{i}.png"
            render_chapter_tag(ch).save(p)
            layers[f"chapter_{i}"] = p

    # ③ 金句层（每句一个）
    for i, q in enumerate(quotes):
        p = tmpdir / f"quote_{i}.png"
        fs = 64 if len(q) <= 24 else 56
        render_quote(q, i, len(quotes), font_size=fs).save(p)
        layers[f"quote_{i}"] = p

    # ④ 出处（—— 书名）
    if book_title:
        layers["attribution"] = tmpdir / "attribution.png"
        render_attribution(book_title).save(layers["attribution"])

    # ⑤⑥ 进度条
    layers["progress_track"] = tmpdir / "progress_track.png"
    render_progress_track().save(layers["progress_track"])
    layers["progress_fill"] = tmpdir / "progress_fill.png"
    render_progress_fill().save(layers["progress_fill"])

    # ⑦ 水印
    if watermark:
        layers["watermark"] = tmpdir / "watermark.png"
        render_watermark(watermark).save(layers["watermark"])

    # ⑧ AI 生成角标（合规标识）
    layers["ai_badge"] = tmpdir / "ai_badge.png"
    render_ai_badge().save(layers["ai_badge"])

    # ⑨ 结尾 CTA 引导帧（2026-08-30：完整版预告 + 评论点单）
    layers["cta"] = tmpdir / "cta.png"
    render_cta(["完整版精读在主页", "评论区报书名，帮你点单"]).save(layers["cta"])

    return layers


if __name__ == "__main__":
    import sys
    layers = render_all("张居正传", ["天下之事，不难于立法，而难于法之必行"],
                        ["第一章 少年时代"], author="朱东润")
    for k, v in layers.items():
        if k != "_tmpdir":
            print(f"{k}: {v} ({Path(v).stat().st_size}B)")
