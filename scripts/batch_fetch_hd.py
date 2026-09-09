#!/usr/bin/env python3
"""批量高清素材补库工具 v1 — 对指定主题批量搜索+下载高清候选到临时目录

用法:
  python3 batch_fetch_hd.py <theme> "<search1>" "<search2>" ... [--per N] [--out DIR]

特性:
  - 多组搜索词依次查询(词不命中就换词)
  - 自动选窄边>=1080 的竖版高清档(复用 scene_fetcher.search_videos 修复)
  - 下载到临时目录(不直接入库,等目检)
  - 输出每个文件的 ffprobe 信息清单
"""
import sys, os, subprocess, json, time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
import scene_fetcher as sf

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    theme = args[0] if args else 'palace'
    queries = args[1:] or [sf.THEME_KEYWORDS.get(theme, '')]
    per = 5
    if '--per' in sys.argv:
        per = int(sys.argv[sys.argv.index('--per') + 1])
    out = Path('/tmp/cand_' + theme)
    if '--out' in sys.argv:
        out = Path(sys.argv[sys.argv.index('--out') + 1])
    vdir = out / 'video'
    vdir.mkdir(parents=True, exist_ok=True)

    print(f"🎯 主题 {theme}: {len(queries)} 组搜索词 -> {vdir}")
    downloaded = 0
    seen_ids = set()
    for qi, q in enumerate(queries):
        if downloaded >= per:
            break
        print(f"\n--- 搜索词 {qi+1}: {q} ---")
        try:
            results = sf.search_videos(q, per_page=12, orientation='portrait')
        except Exception as e:
            print(f"  搜索失败: {e}")
            continue
        for r in results:
            if downloaded >= per:
                break
            vid = r['id']
            if vid in seen_ids or r['w'] < 1080 or r['w'] > r['h']:
                continue
            seen_ids.add(vid)
            dst = vdir / f"cand_{downloaded+1:02d}.mp4"
            print(f"  下载 #{downloaded+1} ID={vid} [{r['w']}x{r['h']} {r['duration']}s]...")
            ok = sf.download(r['url'], dst)
            if ok:
                ok2, reasons, meta = sf.verify_video(dst)
                if ok2:
                    print(f"    ✅ {dst.name} [{meta['w']}x{meta['h']} {meta['dur']:.0f}s]")
                    downloaded += 1
                else:
                    print(f"    ❌ 校验失败: {'/'.join(reasons)}")
                    dst.unlink(missing_ok=True)
            else:
                print(f"    ❌ 下载失败")
                dst.unlink(missing_ok=True)

    print(f"\n✅ 完成: 下载 {downloaded} 段到 {vdir}")
    # 输出清单
    for v in sorted(vdir.glob('*.mp4')):
        ok, reasons, meta = sf.verify_video(v)
        print(f"  {'✅' if ok else '❌'} {v.name} [{meta.get('w','?')}x{meta.get('h','?')} {meta.get('dur',0):.0f}s]")

if __name__ == '__main__':
    main()
