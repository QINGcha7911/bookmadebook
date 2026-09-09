#!/usr/bin/env python3
"""arctic/ww2 攻坚: 换词再试一轮"""
import sys, os
sys.path.insert(0, '/mnt/d/AI软件/GitHub/bookmadebook/scripts')
import scene_fetcher as sf
from pathlib import Path

QUERIES = {
    'arctic': ["glacier ice blue", "iceberg polar ocean", "ice cave glacier", "snow mountain peak arctic",
               "frozen lake ice", "polar landscape ice snow", "glacier aerial"],
    'ww2':    ["soldier walking silhouette", "military convoy silhouette sunset", "horse silhouette battle",
               "smoke battlefield dramatic", "warplane silhouette sky", "soldiers marching column"],
}

def main():
    theme = sys.argv[1]
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    vdir = Path(f'/tmp/cand5_{theme}/video')
    vdir.mkdir(parents=True, exist_ok=True)
    print(f"🎯 {theme}: 目标 {per}")
    downloaded, seen = 0, set()
    for q in QUERIES.get(theme, []):
        if downloaded >= per:
            break
        print(f"\n--- {q} ---")
        try:
            results = sf.search_videos(q, per_page=15, orientation='portrait')
        except Exception as e:
            print(f"  失败 {e}"); continue
        for r in results:
            if downloaded >= per:
                break
            if r['id'] in seen or r['w'] < 1080 or r['w'] > r['h']:
                continue
            seen.add(r['id'])
            dst = vdir / f"cand_{downloaded+1:02d}.mp4"
            print(f"  下载 #{downloaded+1} ID={r['id']} [{r['w']}x{r['h']} {r['duration']}s]")
            if sf.download(r['url'], dst):
                ok, reasons, meta = sf.verify_video(dst)
                if ok:
                    print(f"    ✅ {meta['w']}x{meta['h']} {meta['dur']:.0f}s")
                    downloaded += 1
                else:
                    print(f"    ❌ {'/'.join(reasons)}")
                    dst.unlink(missing_ok=True)
            else:
                print("    ❌ 下载失败")
                dst.unlink(missing_ok=True)
    print(f"\n✅ {theme}: {downloaded}/{per}")

if __name__ == '__main__':
    main()
