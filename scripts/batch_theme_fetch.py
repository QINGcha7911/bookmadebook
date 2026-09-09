#!/usr/bin/env python3
"""逐主题批量下载高清候选 — 后台跑，输出到 /tmp/cand_<theme>"""
import sys, os
sys.path.insert(0, '/mnt/d/AI软件/GitHub/bookmadebook/scripts')
import scene_fetcher as sf
from pathlib import Path
import subprocess

THEME_QUERIES = {
    # 自然景观类(先攻): 词已验证/易命中
    'ocean':   ["ocean waves aerial", "sea waves coast", "beach waves water"],
    'forest':  ["misty forest trees", "forest sunlight green", "pine forest fog"],
    'snow':    ["snowy mountain winter", "snowfall winter landscape", "snow forest"],
    'arctic':  ["aurora borealis night", "arctic ice glacier", "northern lights snow"],
    'desert':  ["desert sand dunes", "desert sunset", "sahara dunes"],
    'sunrise': ["sunrise mountains", "morning sun clouds", "sunrise sea"],
    'starry':  ["milky way stars", "night sky stars", "starry sky timelapse"],
    'pasture': ["sheep meadow pasture", "green grassland hills", "cows pasture"],
    # 人文古建类(后攻, 特写词避开游客)
    'palace':  ["chinese temple roof", "forbidden city roof", "ancient pagoda", "chinese roof tile"],
    'temple':  ["chinese temple mountain", "buddhist temple china", "temple roof china"],
    'gufeng':  ["chinese garden pavilion", "ancient chinese architecture", "chinese courtyard"],
    'guyuan':  ["chinese garden pond", "ancient chinese park", "suzhou garden"],
    'hongkong':["hong kong skyline night", "victoria harbour", "hong kong city"],
    'rain':    ["raindrops window", "rain window blur", "rainy night lights"],
    'library': ["library books shelves", "old library interior", "books reading"],
    'ww2':     ["soldier silhouette sunset", "tank silhouette", "war memorial flame"],
    'tech_city':["city skyline night", "skyscraper night", "city lights aerial night"],
}

def main():
    theme = sys.argv[1]
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    queries = THEME_QUERIES.get(theme)
    if not queries:
        print(f"无主题词表: {theme}"); return
    vdir = Path(f'/tmp/cand_{theme}/video')
    vdir.mkdir(parents=True, exist_ok=True)
    print(f"🎯 {theme}: 目标 {per} 段高清, 词表 {len(queries)} 组")
    downloaded = 0
    seen = set()
    for q in queries:
        if downloaded >= per:
            break
        print(f"\n--- 词: {q} ---")
        try:
            results = sf.search_videos(q, per_page=15, orientation='portrait')
        except Exception as e:
            print(f"  搜索失败 {e}"); continue
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
    print(f"\n✅ {theme} 完成: {downloaded}/{per} 段 -> {vdir}")

if __name__ == '__main__':
    main()
