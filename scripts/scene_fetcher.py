#!/usr/bin/env python3
"""scene_fetcher.py —— 按主题搜索并下载素材（Pexels API）

用法：
    python scene_fetcher.py --theme palace --download 3
    python scene_fetcher.py --search "chinese temple" --orientation portrait --download 5

需要 PEXELS_API_KEY 环境变量（https://www.pexels.com/api/ 免费注册）。
API 返回真实图片 URL + alt 描述 → 人工目检 → 落盘 assets/scenes/<theme>/。

设计动机：manifest 盲猜 URL 内容错配（耳机/合影混入 palace）教训，
改用 API 关键词搜索拿真实匹配素材。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

API_BASE = "https://api.pexels.com/v1"
THEME_KEYWORDS = {
    "palace": "chinese palace forbidden city great wall",
    "desert": "desert sand dunes",
    "ocean": "ocean waves beach",
    "forest": "forest mist trees",
    "sunrise": "sunrise mountains clouds",
    "starry": "starry night milky way",
    "rain": "rainy night city street",
    "library": "library books bookshelf",
    "warm_home": "cozy home warm light interior",
    "snow": "snow mountain winter",
    "tech_city": "city night neon lights",
    "temple": "chinese temple ancient architecture",
}


def get_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        # 尝试从本地配置读取
        for p in [Path.home() / ".pexels_key",
                  Path("/root/.hermes/keys/pexels.txt")]:
            if p.exists():
                key = p.read_text().strip()
                break
    if not key:
        print("❌ 需要 PEXELS_API_KEY（https://www.pexels.com/api/ 免费注册）")
        sys.exit(1)
    return key


def search_photos(query: str, per_page: int = 10,
                  orientation: str = "portrait") -> list:
    """搜索照片，返回 [{id, url, alt, photographer}]"""
    key = get_key()
    url = f"{API_BASE}/search?query={urllib.parse.quote(query)}&per_page={per_page}"
    if orientation:
        url += f"&orientation={orientation}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": key,
                 "User-Agent": "Mozilla/5.0 (bookmadebook-scene-fetcher)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    results = []
    for p in data.get("photos", []):
        results.append({
            "id": p["id"],
            "url": p["src"]["large2x"],
            "alt": p.get("alt", ""),
            "photographer": p.get("photographer", ""),
            "w": p.get("width", 0),
            "h": p.get("height", 0),
        })
    return results


def search_videos(query: str, per_page: int = 5) -> list:
    """搜索视频（实景动态素材），返回 [{id, url, duration}]"""
    key = get_key()
    url = f"{API_BASE}/videos/search?query={urllib.parse.quote(query)}&per_page={per_page}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": key,
                 "User-Agent": "Mozilla/5.0 (bookmadebook-scene-fetcher)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    results = []
    for v in data.get("videos", []):
        # 选 HD 竖版文件（有的话）
        best = None
        for f in v.get("video_files", []):
            if f.get("height", 0) >= 1080 and f.get("width", 0) <= f.get("height", 0):
                best = f
                break
        if not best and v.get("video_files"):
            best = v["video_files"][0]
        results.append({
            "id": v["id"],
            "url": best["link"] if best else "",
            "duration": v.get("duration", 0),
            "w": best.get("width", 0) if best else 0,
            "h": best.get("height", 0) if best else 0,
        })
    return results


def download(url: str, dst: Path) -> bool:
    """下载图片到本地（curl + UA 头，Pexels CDN 要求 UA 否则 403）"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["curl", "-sL", "-f", "--max-time", "40",
         "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
         "-o", str(dst), url],
        capture_output=True, timeout=90)
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 30000


def main():
    ap = argparse.ArgumentParser(description="Pexels 素材搜索下载")
    ap.add_argument("--theme", help="主题名（用内置关键词）")
    ap.add_argument("--search", help="自定义搜索词")
    ap.add_argument("--orientation", default="portrait", help="portrait/landscape")
    ap.add_argument("--download", type=int, default=0, help="下载前 N 张到本地")
    ap.add_argument("--video", action="store_true", help="搜视频")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--size", default="w=2160", help="下载尺寸参数")
    ap.add_argument("--out", help="下载目录（默认 assets/scenes/<theme>）")
    args = ap.parse_args()

    query = args.search or THEME_KEYWORDS.get(args.theme, "")
    if not query:
        print("需要 --theme 或 --search")
        sys.exit(1)

    if args.video:
        results = search_videos(query, per_page=max(args.download, 5))
    else:
        results = search_photos(query, per_page=max(args.download, 10))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    for i, r in enumerate(results):
        info = f"#{i+1} [{r.get('w')}x{r.get('h')}] {r.get('alt','')[:50]}"
        if args.video:
            info = f"#{i+1} [{r.get('w')}x{r.get('h')} {r.get('duration')}s]"
        print(info)

    if args.download > 0:
        if args.out:
            tdir = Path(args.out)
        elif args.theme:
            tdir = Path("/root/.hermes/skills/productivity/bookmadebook/assets/scenes") / args.theme
        else:
            print("下载需要 --theme 或 --out")
            sys.exit(1)
        tdir.mkdir(parents=True, exist_ok=True)
        got = 0
        for i, r in enumerate(results[:args.download]):
            dst = tdir / f"{i+1:02d}.jpg"
            # 高清版：替换 URL 参数（缩略图 → 2160 宽）
            url = re.sub(r"[?&](w|h)=\d+", "", r["url"])
            url = url + (f"?{args.size}" if "?" not in url else f"&{args.size}")
            if download(url, dst):
                got += 1
                print(f"  ✅ {args.theme}/{i+1:02d}.jpg  {r.get('alt','')[:40]}")
            else:
                print(f"  ⚠️ {i+1} 下载失败")
        print(f"✅ 下载完成: {got}/{args.download} → {tdir}")


if __name__ == "__main__":
    import urllib.parse  # noqa: 延迟导入避免顶层依赖
    main()
