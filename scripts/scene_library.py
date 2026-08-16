#!/usr/bin/env python3
"""scene_library.py —— 本地视频素材库管理

素材组织（设计文档 §4）：
    assets/scenes/<theme>/NN_分组_变体.jpg   ← 本地素材（随仓库分发）
    ~/.cache/bookmadebook/scenes/<theme>/    ← 运行时联网补图缓存
    assets/scenes/fallback/                  ← 兜底渐变图（断网保底）

降级链：本地素材 → 缓存 → 联网下载 → fallback 兜底图 → 报错退出
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
SCENES_DIR = SKILL_DIR / "assets" / "scenes"
MANIFEST_PATH = SCENES_DIR / "manifest.json"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bookmadebook" / "scenes"

MIN_IMAGES = 2  # 一个主题至少 2 张才能做 xfade
W, H = 1080, 1920

# 主题中文名（用于日志/提示）
THEME_CN = {
    "palace": "古建宫殿", "desert": "沙漠星空", "ocean": "海洋",
    "forest": "森林", "sunrise": "日出山川", "starry": "星空银河",
    "rain": "雨夜城市", "library": "书房书香", "warm_home": "暖光家居",
    "snow": "雪境", "tech_city": "都市夜景", "temple": "禅意寺庙",
    "ww2": "战争史诗", "ship": "远洋巨轮", "hongkong": "香港天际线",
    "pasture": "雪原牧场", "arctic": "北极极夜",
}


def load_manifest() -> dict:
    """读取素材清单 manifest.json（主题 → URL 列表）"""
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def all_themes() -> list:
    """全部可用主题 ID（manifest 键 + 本地已有目录）"""
    themes = set(load_manifest().keys())
    if SCENES_DIR.is_dir():
        for d in SCENES_DIR.iterdir():
            if d.is_dir() and d.name != "fallback":
                themes.add(d.name)
    return sorted(themes)


def _download_crop(url: str, dst: Path) -> bool:
    """下载图片并竖版裁剪到 1080×1920。wget 下载（对慢速网络更稳）。"""
    try:
        raw = dst.with_suffix(".raw")
        # wget 下载：--tries 2 --timeout 30，失败即退出
        r = subprocess.run(
            ["wget", "-q", "--tries=2", "--timeout=30", "-O", str(raw), url],
            timeout=50, capture_output=True)
        if r.returncode != 0 or not raw.exists() or raw.stat().st_size < 50000:
            raw.unlink(missing_ok=True)
            return False
        try:
            from PIL import Image
            im = Image.open(raw)
            im.load()  # 强制完整加载，检测截断
            im = im.convert("RGB")
            w, h = im.size
            target_ratio = H / W
            cur_ratio = h / w
            if cur_ratio > target_ratio:
                new_h = int(w * target_ratio)
                top = (h - new_h) // 2
                im = im.crop((0, top, w, top + new_h))
            else:
                new_w = int(h / target_ratio)
                left = (w - new_w) // 2
                im = im.crop((left, 0, left + new_w, h))
            im = im.resize((W, H), Image.LANCZOS)
            im.save(dst, quality=92)
            raw.unlink(missing_ok=True)
            return dst.exists() and dst.stat().st_size > 50000
        except Exception:
            raw.unlink(missing_ok=True)
            return False
    except Exception:
        return False


def ensure_theme(theme: str, force: bool = False) -> list:
    """确保主题素材就绪，返回图片路径列表。命中本地→直接返回（离线可用）。"""
    theme_dir = SCENES_DIR / theme
    # ① 本地素材（随仓库分发，最高优先）
    if theme_dir.is_dir():
        images = sorted(theme_dir.glob("*.jpg"))
        if len(images) >= MIN_IMAGES and not force:
            return images
    # ② 缓存目录
    cache_theme = CACHE_DIR / theme
    if cache_theme.is_dir():
        images = sorted(cache_theme.glob("*.jpg"))
        if len(images) >= MIN_IMAGES and not force:
            return images
    # ③ 联网下载（manifest 里的 URL）
    urls = load_manifest().get(theme, [])
    if urls:
        cache_theme.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for i, url in enumerate(urls, start=1):
            dst = cache_theme / f"{i:02d}.jpg"
            if dst.exists() and dst.stat().st_size > 10000:
                downloaded.append(dst)
                continue
            if _download_crop(url, dst):
                downloaded.append(dst)
            if len(downloaded) >= MIN_IMAGES and i >= 3:
                break
        if len(downloaded) >= MIN_IMAGES:
            print(f"  ⬇️ 主题 [{theme}] 素材已下载到缓存: {cache_theme}")
            return downloaded
    # ④ 兜底：desert 本地素材
    return fallback_images(theme)


def fallback_images(theme: str) -> list:
    """降级：theme 缺失 → desert（内置兜底）→ 报错退出"""
    if theme != "desert":
        imgs = ensure_theme("desert")
        if len(imgs) >= MIN_IMAGES:
            print(f"  ⚠️ 主题 [{theme}] 素材缺失，已回退到 desert")
            return imgs
    # 生成纯色渐变兜底图
    fallback_dir = SCENES_DIR / "fallback"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    from PIL import Image, ImageDraw
    imgs = []
    for i, color in enumerate([(30, 35, 50), (60, 50, 35), (25, 60, 50)]):
        p = fallback_dir / f"fb_{i}.jpg"
        if not p.exists():
            im = Image.new("RGB", (W, H), color)
            d = ImageDraw.Draw(im)
            # 简单渐变
            for y in range(H):
                d.line([(0, y), (W, y)],
                       fill=(color[0] + int(20 * y / H),
                             color[1] + int(15 * y / H),
                             color[2] + int(10 * y / H)))
            im.save(p, quality=90)
        imgs.append(p)
    print(f"  ⚠️ 主题 [{theme}] 无素材，使用内置渐变兜底图")
    return imgs


def load_plan_images(plan) -> list:
    """为 plan 中每个 segment 填充图片路径；缺失主题走降级链"""
    for seg in plan.segments:
        seg.images = ensure_theme(seg.theme)
        if len(seg.images) < MIN_IMAGES:
            print(f"  ❌ 主题 [{seg.theme}] 素材完全不可用")
            sys.exit(1)
    return plan


def fetch_all() -> None:
    """预下载全部主题素材（离线部署用）"""
    themes = load_manifest().keys()
    print(f"📥 预下载 {len(themes)} 个主题素材...")
    for t in themes:
        imgs = ensure_theme(t, force=True)
        print(f"  ✅ {t} ({THEME_CN.get(t, '')}): {len(imgs)} 张")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="素材库管理")
    ap.add_argument("--all", action="store_true", help="预下载全部主题素材")
    ap.add_argument("--theme", help="指定主题")
    ap.add_argument("--list", action="store_true", help="列出可用主题")
    args = ap.parse_args()
    if args.list:
        for t in all_themes():
            n = len(ensure_theme(t))
            print(f"  {t} ({THEME_CN.get(t, '')}): {n} 张")
    elif args.all:
        fetch_all()
    elif args.theme:
        imgs = ensure_theme(args.theme, force=True)
        print(f"  ✅ {args.theme}: {len(imgs)} 张")
    else:
        print("用法: scene_library.py --list | --all | --theme <name>")
