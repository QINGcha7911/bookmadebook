#!/usr/bin/env python3
"""候选素材入库: 高清入库 + 低清隔离

用法:
  python3 ingest_candidates.py <theme> [--keep-all] [--list]

- 从 /tmp/cand_<theme>/video/ 扫描候选
- 自动检查目录已用编号, 新候选接续命名  <n>_<描述>.mp4
- 把候选复制到 assets/scenes/<theme>/video/
- 把该主题 720p 存量移到 _excluded_lowres/ (窄边<1080)
"""
import sys, os, shutil, subprocess
from pathlib import Path

REPO = Path('/mnt/d/AI软件/GitHub/bookmadebook')
THEME = sys.argv[1] if len(sys.argv) > 1 else 'ocean'
KEEP_ALL = '--keep-all' in sys.argv
LIST_ONLY = '--list' in sys.argv

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
    short = min(w, h)
    return {'w': w, 'h': h, 'dur': dur, 'short': short, 'hd': short >= 1080}

# 1. 列出候选
cand_dir = Path(f'/tmp/cand_{THEME}/video')
if not cand_dir.is_dir():
    print(f"❌ 无候选目录 {cand_dir}"); sys.exit(1)
cands = sorted(cand_dir.glob('cand_*.mp4'))
print(f"📋 候选 {len(cands)} 段:")
for c in cands:
    meta = verify(c)
    print(f"  {'✅' if meta and meta['hd'] else '❌'} {c.name} [{meta['w']}x{meta['h']} {meta['dur']:.0f}s]" if meta else f"  ❌ {c.name} [无法解析]")
if LIST_ONLY:
    sys.exit(0)

# 2. 检查目标目录
tdir = REPO / 'assets' / 'scenes' / THEME / 'video'
tdir.mkdir(parents=True, exist_ok=True)
existing = sorted([f for f in tdir.glob('*.mp4') if not f.name.startswith('_')])
print(f"\n📁 现有 {len(existing)} 段")
for e in existing:
    meta = verify(e)
    if meta:
        print(f"  {e.name} [{meta['w']}x{meta['h']} {meta['dur']:.0f}s] {'HD' if meta['hd'] else 'SD!'}")

# 3. 隔离低清存量
if not KEEP_ALL:
    excl = tdir / '_excluded_lowres'
    excl.mkdir(exist_ok=True)
    moved = 0
    for e in existing:
        meta = verify(e)
        if meta and not meta['hd']:
            dst = excl / e.name
            if not dst.exists():
                shutil.move(str(e), str(dst))
                print(f"  📦 隔离低清: {e.name} -> _excluded_lowres/")
                moved += 1
    if moved == 0:
        print("  (无低清存量需隔离)")
    # 重扫现有
    existing = sorted([f for f in tdir.glob('*.mp4') if not f.name.startswith('_')])

# 4. 入库候选 (接续编号, 跳过已存在同名)
used_nums = set()
for e in existing:
    import re
    m = re.match(r'(\d+)', e.name)
    if m:
        used_nums.add(int(m.group(1)))
next_num = max(used_nums, default=0) + 1
import re
ingested = 0
for c in cands:
    meta = verify(c)
    if not meta or not meta['hd']:
        print(f"  ⏭️ 跳过 {c.name} (非高清)")
        continue
    # 找下一个空号
    while next_num in used_nums:
        next_num += 1
    # 简短描述 = 原文件名去掉cand_和.mp4
    desc = c.stem.replace('cand_', '')
    dst = tdir / f"{next_num:02d}_{desc}.mp4"
    shutil.copy2(str(c), str(dst))
    print(f"  ✅ 入库: {dst.name} [{meta['w']}x{meta['h']} {meta['dur']:.0f}s]")
    used_nums.add(next_num)
    next_num += 1
    ingested += 1

print(f"\n✅ {THEME} 入库完成: +{ingested} 段高清")
print(f"   目录现有 {len([f for f in tdir.glob('*.mp4') if not f.name.startswith('_')])} 段可用")
