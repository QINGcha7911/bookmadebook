#!/usr/bin/env python3
"""第二轮主题: rain/ship/library/hongkong/tech_city/warm_home/gufeng/guyuan/temple"""
import sys, os
sys.path.insert(0, '/mnt/d/AI软件/GitHub/bookmadebook/scripts')
import scene_fetcher as sf
from pathlib import Path

THEME_QUERIES = {
    'rain':     ["raindrops window glass", "rain window blur", "umbrella rain night"],
    'ship':     ["cargo ship ocean", "container ship sea", "ship deck waves"],
    'library':  ["library books shelves", "old library hall", "books stack reading"],
    'hongkong': ["hong kong skyline night", "victoria harbour aerial", "hong kong street night"],
    'tech_city':["city skyline night aerial", "skyscraper night lights", "city traffic night"],
    'warm_home':["cozy home interior warm", "fireplace cozy room", "tea cup cozy blanket"],
    'gufeng':   ["chinese pavilion garden", "ancient chinese architecture", "chinese courtyard lantern"],
    'guyuan':   ["suzhou garden pond", "chinese garden bamboo", "ancient chinese garden"],
    'temple':   ["chinese temple mountain mist", "buddhist temple roof", "ancient temple china"],
    'ww2':      ["military tank silhouette", "soldier silhouette sunset", "war memorial"],
    'finance':  ["stock chart screen", "financial district night", "trading floor"],
}

def main():
    theme = sys.argv[1]
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    queries = THEME_QUERIES.get(theme)
    if not queries:
        print(f"无词表 {theme}"); return
    vdir = Path(f'/tmp/cand_{theme}/video')
    vdir.mkdir(parents=True, exist_ok=True)
    print(f"🎯 {theme}: 目标 {per} 段, {len(queries)} 组词")
    downloaded, seen = 0, set()
    for q in queries:
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
