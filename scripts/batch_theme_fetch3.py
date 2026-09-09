#!/usr/bin/env python3
"""第三轮: 补 arctic/desert/snow/sunrise/rain 到 5 段"""
import sys, os
sys.path.insert(0, '/mnt/d/AI软件/GitHub/bookmadebook/scripts')
import scene_fetcher as sf
from pathlib import Path

THEME_QUERIES = {
    'arctic':  ["aurora lake reflection", "aurora sky stars", "iceberg ocean polar", "snowstorm arctic wind"],
    'desert':  ["sand dune texture", "desert dunes aerial", "desert golden sand", "dune ridge shadow"],
    'snow':    ["snowfall trees", "winter forest snow falling", "snowy pine landscape", "blizzard snow wind"],
    'sunrise': ["sunrise ocean horizon", "golden sunrise clouds", "sunrise mountain peak", "morning light valley"],
    'rain':    ["rain drops leaf", "rain window city bokeh", "rain puddle reflection", "umbrella rain drops"],
    'gufeng':  ["chinese ancient architecture detail", "chinese traditional house courtyard", "chinese old town roof"],
    'guyuan':  ["chinese garden water reflection", "ancient chinese courtyard tree", "chinese stone bridge garden"],
    'temple':  ["chinese temple roof upturned", "buddhist temple china mountain", "chinese incense temple"],
    'ww2':     ["battlefield fog silhouette", "war monument flame", "dark clouds dramatic sky"],
    'finance': ["city financial buildings night", "stock exchange building", "glass skyscrapers low angle"],
}

def main():
    theme = sys.argv[1]
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    queries = THEME_QUERIES.get(theme)
    if not queries:
        print(f"无词表 {theme}"); return
    vdir = Path(f'/tmp/cand_{theme}/video')
    vdir.mkdir(parents=True, exist_ok=True)
    print(f"🎯 {theme}: 目标 {per}, {len(queries)} 组词")
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
