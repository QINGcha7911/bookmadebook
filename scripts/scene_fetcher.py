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
    "arctic": "arctic aurora snow landscape",
    "ww2": "ww2 memorial tank silhouette battlefield",
    "ship": "container ship cargo port",
    "hongkong": "hong kong skyline victoria harbour",
    "pasture": "pasture sheep meadow",
    "finance": "stock market chart screen",
    "gufeng": "chinese garden ancient architecture",
    "guyuan": "ancient temple red wall trees",
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


def search_videos(query: str, per_page: int = 5, orientation: str = "portrait") -> list:
    """搜索视频（实景动态素材），返回 [{id, url, duration}]"""
    key = get_key()
    url = f"{API_BASE}/videos/search?query={urllib.parse.quote(query)}&per_page={per_page}"
    if orientation:
        url += f"&orientation={orientation}"
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
        ["curl", "-sL", "-f", "--max-time", "90",
         "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
         "-o", str(dst), url],
        capture_output=True, timeout=90)
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 30000


def verify_video(path: Path) -> tuple:
    """ffprobe 校验视频素材：竖版(宽<=高)、高度>=1080、时长>=3s。
    音频轨仅作 warning（合成时 -map 0:v 不 map 视频音轨，无影响）。
    返回 (ok, reasons, meta)。"""
    reasons, meta = [], {}
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return False, ["无法解析"], meta
    data = json.loads(r.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        return False, ["无视频流"], meta
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    dur = float(data.get("format", {}).get("duration", 0) or 0)
    meta = {"w": w, "h": h, "dur": dur}
    if h < 1080:
        reasons.append(f"高度不足1080({h})")
    if w > h:
        reasons.append(f"非竖版({w}x{h})")
    if dur < 3:
        reasons.append(f"时长过短({dur:.1f}s)")
    meta["audio"] = any(s.get("codec_type") == "audio" for s in streams)
    return (not reasons), reasons, meta


def make_contact_sheet(video: Path, out_png: Path, cols: int = 4, rows: int = 3) -> None:
    """ffmpeg 均匀抽 cols*rows 帧 + PIL 拼 4×3 缩略图，供 vision 目检真人/现代城市。"""
    from PIL import Image
    dur = 0.0
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, timeout=30)
    if r.stdout.strip():
        dur = float(r.stdout.strip())
    if dur <= 0:
        return
    out_png.parent.mkdir(parents=True, exist_ok=True)
    frames, n = [], cols * rows
    for k in range(n):
        t = (k + 0.5) / n * dur
        tmp = out_png.parent / f"_f{k}_{video.stem}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf",
             "scale=270:480:force_original_aspect_ratio=increase,crop=270:480",
             str(tmp)], capture_output=True, timeout=30)
        if tmp.exists():
            frames.append(tmp)
    if not frames:
        return
    imgs = [Image.open(p) for p in frames]
    w, h = imgs[0].size
    canvas = Image.new("RGB", (w * cols, h * rows), "black")
    for idx, im in enumerate(imgs):
        canvas.paste(im, ((idx % cols) * w, (idx // cols) * h))
    canvas.save(out_png)
    for p in frames:
        p.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Pexels 素材搜索下载")
    ap.add_argument("--theme", help="主题名（用内置关键词）")
    ap.add_argument("--search", help="自定义搜索词")
    ap.add_argument("--orientation", default="portrait", help="portrait/landscape")
    ap.add_argument("--download", type=int, default=0, help="下载前 N 张到本地")
    ap.add_argument("--video", action="store_true", help="搜视频")
    ap.add_argument("--verify", action="store_true", help="下载后 ffprobe 校验（竖版/≥1080/时长），不合格自动跳过补位；并抽帧拼 4×3 缩略图供 vision 目检")
    ap.add_argument("--min-dur", type=float, default=0, help="视频最短时长（秒），短于该值跳过（2026-09-02 15s+ 运动镜头规则）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--size", default="w=2160", help="下载尺寸参数")
    ap.add_argument("--out", help="下载目录（默认 assets/scenes/<theme>）")
    args = ap.parse_args()

    query = args.search or THEME_KEYWORDS.get(args.theme, "")
    if not query:
        print("需要 --theme 或 --search")
        sys.exit(1)

    # 仅复核已有素材（不联网）：--verify 且不下载
    if args.verify and not args.download:
        tdir = Path(args.out) if args.out else \
            Path(__file__).resolve().parent.parent / "assets" / "scenes" / (args.theme or "")
        vdir = tdir / "video"
        if not vdir.is_dir():
            print(f"❌ 无视频目录: {vdir}")
            sys.exit(1)
        print(f"🔎 复核已有素材: {vdir}")
        bad = 0
        for v in sorted(vdir.glob("*.mp4")):
            ok, reasons, meta = verify_video(v)
            status = "✅" if ok else f"❌ {'/'.join(reasons)}"
            if not ok:
                bad += 1
            print(f"  {status} {v.name} [{meta.get('w','?')}x{meta.get('h','?')} {meta.get('dur',0):.0f}s]")
        print(f"✅ 复核完成: 不合格 {bad} 个")
        return

    if args.video:
        results = search_videos(query, per_page=max(args.download, 5), orientation=args.orientation)
    else:
        results = search_photos(query, per_page=max(args.download, 10))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    for i, r in enumerate(results):
        info = f"#{i+1} [{r.get('w')}x{r.get('h')}] {r.get('alt','')[:50]}"
        if args.video:
            info = f"#{i+1} [{r.get('w')}x{r.get('h')} {r.get('duration')}s]"
            if args.min_dur and r.get("duration", 0) < args.min_dur:
                info += " (时长不足跳过)"
        print(info)

    if args.download > 0:
        if args.out:
            tdir = Path(args.out)
        elif args.theme:
            tdir = Path(__file__).resolve().parent.parent / "assets" / "scenes" / args.theme
        else:
            print("下载需要 --theme 或 --out")
            sys.exit(1)
        tdir.mkdir(parents=True, exist_ok=True)
        vdir = tdir / "video" if args.video else tdir
        vdir.mkdir(parents=True, exist_ok=True)
        got = 0
        idx = 0
        for i, r in enumerate(results):
            if got >= args.download:
                break
            if args.video:
                if args.min_dur and r.get("duration", 0) < args.min_dur:
                    print(f"  ⏭️ #{i+1} {r.get('duration')}s 短于 {args.min_dur:.0f}s，跳过")
                    continue
                dst = vdir / f"{idx+1:02d}.mp4"
                url = r["url"]
                desc = f"{r.get('duration')}s"
            else:
                dst = tdir / f"{idx+1:02d}.jpg"
                url = re.sub(r"[?&](w|h)=\d+", "", r["url"])
                url = url + (f"?{args.size}" if "?" not in url else f"&{args.size}")
                desc = r.get("alt", "")[:40]
            if not download(url, dst):
                print(f"  ⚠️ #{i+1} 下载失败，跳过")
                continue
            if args.video and args.verify:
                ok, reasons, meta = verify_video(dst)
                if not ok:
                    print(f"  ❌ #{i+1} {dst.name} 不合格（{'/'.join(reasons)}），自动补位")
                    dst.unlink(missing_ok=True)
                    continue
                audio_note = " 带音频轨(合成不map)" if meta.get("audio") else ""
                print(f"  ✅ #{i+1} {dst.name} [{meta['w']}x{meta['h']} {meta['dur']:.0f}s]{audio_note}")
            else:
                print(f"  ✅ #{i+1} {dst.name}  {desc}")
            idx += 1
            got += 1
        if args.video and args.verify:
            verify_dir = vdir / "verify"
            print(f"🔎 生成 4×3 缩略图（vision 目检真人/现代城市）→ {verify_dir}")
            for v in sorted(vdir.glob("*.mp4")):
                sheet = verify_dir / f"{v.stem}_contact.png"
                make_contact_sheet(v, sheet)
                print(f"  🖼️ {sheet.name}  {'✅' if sheet.exists() else '❌'}")
            print("⚠️ 目检要求：逐张确认无真人/无现代城市后再入库；不合格删除对应 mp4")
        print(f"✅ 下载完成: {got}/{args.download} → {vdir}")

if __name__ == "__main__":
    import urllib.parse  # noqa: 延迟导入避免顶层依赖
    main()
