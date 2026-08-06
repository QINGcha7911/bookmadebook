#!/usr/bin/env python3
"""listen-book 配置加载器

让 config.yaml 被所有脚本真正读取（此前是"死配置"）。
提供统一的 load_config / get() 接口。

用法:
    from config_loader import load_config, get
    cfg = load_config()          # 全量配置
    voice = get("voice.default", "auto")   # 带默认值的取值
"""
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# config.yaml 位于仓库根目录（脚本在 scripts/ 下）
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"

# 也可被其他安装位置覆盖（技能目录/环境变量）
_ENV_OVERRIDE = os.environ.get("LISTEN_BOOK_CONFIG", "")

_cache = None


def _find_config() -> Path:
    """按优先级找 config.yaml：env覆盖 > 仓库根 > 技能目录。"""
    if _ENV_OVERRIDE and Path(_ENV_OVERRIDE).exists():
        return Path(_ENV_OVERRIDE)
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    # 技能目录兜底（Hermes skills 安装形态）
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "listen-book" / "config.yaml",
        Path.home() / ".hermes" / "skills" / "productivity" / "book-to-audio" / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return CONFIG_PATH


def load_config() -> dict:
    """加载 config.yaml，解析失败时返回空 dict（不崩溃）。"""
    global _cache
    if _cache is not None:
        return _cache
    path = _find_config()
    if yaml is None:
        print("⚠️ [config_loader] 缺少 PyYAML，配置未加载（请 pip install pyyaml）")
        _cache = {}
        return _cache
    try:
        with open(path, encoding="utf-8") as f:
            _cache = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"⚠️ [config_loader] 配置加载失败: {e}")
        _cache = {}
    return _cache


def get(key: str, default=None):
    """按点分路径取值，如 get('voice.default', 'auto')。"""
    cfg = load_config()
    cur = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


if __name__ == "__main__":
    cfg = load_config()
    print(f"✅ config.yaml 已加载: {_find_config()}")
    print(f"   配置节: {list(cfg.keys())}")
    print(f"   voice.default = {get('voice.default', 'auto')}")
    print(f"   age_group.default = {get('age_group.default', 'adult')}")
    print(f"   delivery.output_dir = {get('delivery.output_dir', '~/listen-book')}")
