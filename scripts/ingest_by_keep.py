#!/usr/bin/env python3
"""按合格清单入库: 从 cand 目录选合格品复制到主题库 + 隔离低清存量
合格映射: {theme: [候选索引(1-based)]}
"""
import sys, os, shutil, re, subprocess
from pathlib import Path

REPO = Path('/mnt/d/AI软件/GitHub/bookmadebook')
KEEP = {
    'palace':  list(range(1, 10)),   # cand_01~08(palace2) + 1(前批,已复制在palace_hd)
    'ocean':   [1, 2, 3, 4, 5, 6],
    'forest':  [1, 3, 4, 5],
    'snow':    [1, 3],
    'arctic':  [2],
    'desert':  [1, 2, 5],
    'sunrise': [1, 5],
    'starry':  [1, 3, 5],
    'pasture': [3, 5],
}

def verify(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'stream=codec_type,width,height:format=duration',
                        '-of', 'json', str(path)], capture_output=True, text=True, timeout=30)
    import json as _json
    d = _json.loads(r.stdout or '{}')
    v = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not v:
        return None
    w, h = int(v['width']), int(v['height'])
    dur = float(d.get('format', {}).get('duration', 0) or 0)
    return {'w': w, 'h': h, 'dur': dur, 'hd': min(w, h) >= 1080}

for theme, keep_idx in KEEP.items():
    # 候选源: palace 用 palace_hd(前批cand_01复制来的)+palace2; 其他用 cand_<theme>
    if theme == 'palace':
        # 先把 palace_hd(1个) + cand_palace2(8个) 合并到 /tmp/cand_palace_final
        final = Path('/tmp/cand_palace_final/video')
        final.mkdir(parents=True, exist_ok=True)
        for f in list(Path('/tmp/palace_hd').glob('*.mp4')) + list(Path('/tmp/cand_palace2/video').glob('*.mp4')):
            dst = final / f.name
            if not dst.exists():
                shutil.copy2(str(f), str(dst))
        src_dir = final
    else:
        src_dir = Path(f'/tmp/cand_{theme}/video')
    tdir = REPO / 'assets' / 'scenes' / theme / 'video'
    tdir.mkdir(parents=True, exist_ok=True)
    print(f"\n🎯 {theme}: 候选目录 {src_dir}")

    # 1. 隔离低清存量
    excl = tdir / '_excluded_lowres'
    excl.mkdir(exist_ok=True)
    for e in list(tdir.glob('*.mp4')):
        if e.name.startswith('_'):
            continue
        meta = verify(e)
        if meta and not meta['hd']:
            dst = excl / e.name
            if not dst.exists():
                shutil.move(str(e), str(dst))
                print(f"  📦 隔离低清: {e.name}")

    # 2. 入库合格候选 (接续编号)
    existing = sorted([f for f in tdir.glob('*.mp4') if not f.name.startswith('_')])
    used = set()
    for e in existing:
        m = re.match(r'(\d+)', e.name)
        if m:
            used.add(int(m.group(1)))
    next_num = max(used, default=0) + 1

    all_cands = sorted(src_dir.glob('*.mp4'))
    for idx in keep_idx:
        if idx - 1 >= len(all_cands):
            print(f"  ⚠️ {theme} 无候选 #{idx}")
            continue
        c = all_cands[idx - 1]
        meta = verify(c)
        if not meta or not meta['hd']:
            print(f"  ⏭️ {c.name} 非高清")
            continue
        while next_num in used:
            next_num += 1
        desc = c.stem.replace('cand_', '')
        dst = tdir / f"{next_num:02d}_{desc}.mp4"
        shutil.copy2(str(c), str(dst))
        print(f"  ✅ {dst.name} [{meta['w']}x{meta['h']} {meta['dur']:.0f}s]")
        used.add(next_num)
        next_num += 1

    final_count = len([f for f in tdir.glob('*.mp4') if not f.name.startswith('_')])
    print(f"  → 主题现有 {final_count} 段可用")
print("\n✅ 全部入库完成")
