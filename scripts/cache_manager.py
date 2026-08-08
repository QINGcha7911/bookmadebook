#!/usr/bin/env python3
"""bookmadebook 三级缓存管理器

L1 脚本缓存:  key = book_hash + age_group + scene + depth
L2 TTS片段缓存: key = text_md5 + voice + rate
L3 成品缓存:    key = script_hash + voice + speed

缓存目录: ~/.hermes/cache/bookmadebook/{l1,l2,l3}/

用法:
    from cache_manager import CacheManager
    cm = CacheManager()
    cm.get_l1(book_hash, age, scene, depth)
    cm.set_l1(book_hash, age, scene, depth, content)
"""
import hashlib
import json
import os
import time
from pathlib import Path

CACHE_ROOT = Path(os.path.expanduser("~/.hermes/cache/bookmadebook"))
# 缓存 schema 版本：键结构变更时+1，强制旧缓存失效（避免旧键复用错误音频）
CACHE_SCHEMA_VERSION = "v2"
DEFAULT_TTL = {
    "l1": 30 * 24 * 3600,      # 脚本缓存 30 天
    "l2": 7 * 24 * 3600,       # TTS 片段缓存 7 天
    "l3": 30 * 24 * 3600,      # 成品缓存 30 天
}


class CacheManager:
    """三级缓存统一管理器"""

    def __init__(self, root: Path | str = CACHE_ROOT, ttl: dict | None = None):
        self.root = Path(root).expanduser()
        self.ttl = ttl or DEFAULT_TTL
        for level in ("l1", "l2", "l3"):
            (self.root / level).mkdir(parents=True, exist_ok=True)

    # ---------- 通用工具 ----------
    @staticmethod
    def _md5(text: str) -> str:
        # 前缀带 schema 版本：键结构变更时旧缓存自动失效
        return hashlib.md5(f"{CACHE_SCHEMA_VERSION}|{text}".encode("utf-8", errors="replace")).hexdigest()

    def _path(self, level: str, key: str, suffix: str = ".json") -> Path:
        """按 key 生成缓存文件路径，支持子目录散列"""
        safe_key = key.replace("/", "_").replace("\\", "_")
        if len(safe_key) >= 2:
            subdir = self.root / level / safe_key[:2]
        else:
            subdir = self.root / level / "00"
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir / (safe_key + suffix)

    def _read(self, path: Path) -> dict | None:
        """读取缓存条目，检查 TTL"""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        level = path.parent.parent.name
        ttl = self.ttl.get(level, DEFAULT_TTL["l1"])
        if time.time() - entry.get("ts", 0) > ttl:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return entry

    def _write(self, path: Path, data: dict) -> None:
        data["ts"] = time.time()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---------- L1 脚本缓存 ----------
    def l1_key(self, book_hash: str, age_group: str, scene: str, depth: str) -> str:
        return self._md5(f"{book_hash}|{age_group}|{scene}|{depth}")

    def get_l1(self, book_hash: str, age_group: str, scene: str, depth: str) -> str | None:
        path = self._path("l1", self.l1_key(book_hash, age_group, scene, depth))
        entry = self._read(path)
        if entry and entry.get("content"):
            return entry["content"]
        return None

    def set_l1(self, book_hash: str, age_group: str, scene: str, depth: str, content: str) -> None:
        path = self._path("l1", self.l1_key(book_hash, age_group, scene, depth))
        self._write(path, {"content": content})

    # ---------- L2 TTS 片段缓存 ----------
    def l2_key(self, text: str, voice: str, rate: str,
               volume: str = "+0%", pitch: str = "+0Hz",
               style_fp: str = "") -> str:
        return self._md5(f"{self._md5(text)}|{voice}|{rate}|{volume}|{pitch}|{style_fp}")

    def get_l2(self, text: str, voice: str, rate: str,
               volume: str = "+0%", pitch: str = "+0Hz",
               style_fp: str = "") -> Path | None:
        """返回音频文件路径（存在且非空则命中）"""
        key = self.l2_key(text, voice, rate, volume, pitch, style_fp)
        path = self._path("l2", key, ".mp3")
        if path.exists() and path.stat().st_size > 0:
            entry = self._read(path.with_suffix(".meta.json"))
            if entry is None:
                # 无 meta 但文件存在仍可用；顺手补一个
                self.set_l2(text, voice, rate, volume, pitch, style_fp, path)
                return path
            return path
        return None

    def set_l2(self, text: str, voice: str, rate: str,
               audio_path: Path | str,
               volume: str = "+0%", pitch: str = "+0Hz",
               style_fp: str = "") -> None:
        """注册/保存 L2 音频文件"""
        src = Path(audio_path)
        key = self.l2_key(text, voice, rate, volume, pitch, style_fp)
        dest = self._path("l2", key, ".mp3")
        if src.exists() and src != dest:
            try:
                src.replace(dest)
            except OSError:
                return
        meta = self._path("l2", key, ".meta.json")
        self._write(meta, {"text_md5": self._md5(text), "voice": voice, "rate": rate,
                           "volume": volume, "pitch": pitch, "style_fp": style_fp})

    # ---------- L3 成品缓存 ----------
    def l3_key(self, script_hash: str, voice: str, speed: str,
               style_fp: str = "") -> str:
        return self._md5(f"{script_hash}|{voice}|{speed}|{style_fp}")

    def get_l3(self, script_hash: str, voice: str, speed: str,
               style_fp: str = "") -> Path | None:
        path = self._path("l3", self.l3_key(script_hash, voice, speed, style_fp), ".mp3")
        if path.exists() and path.stat().st_size > 0:
            return path
        return None

    def set_l3(self, script_hash: str, voice: str, speed: str,
               audio_path: Path | str,
               style_fp: str = "") -> None:
        src = Path(audio_path)
        key = self.l3_key(script_hash, voice, speed, style_fp)
        dest = self._path("l3", key, ".mp3")
        if src.exists() and src != dest:
            try:
                src.replace(dest)
            except OSError:
                return
        meta = self._path("l3", key, ".meta.json")
        self._write(meta, {"script_hash": script_hash, "voice": voice,
                           "speed": speed, "style_fp": style_fp})

    # ---------- 统计与清理 ----------
    def stats(self) -> dict:
        result = {}
        for level in ("l1", "l2", "l3"):
            files = list((self.root / level).rglob("*"))
            total = sum(f.stat().st_size for f in files if f.is_file())
            result[level] = {"files": len([f for f in files if f.is_file()]), "bytes": total}
        return result

    def clear(self, level: str | None = None) -> int:
        """清理缓存。level=None 清全部；否则只清指定级别"""
        removed = 0
        targets = [level] if level else ["l1", "l2", "l3"]
        for lv in targets:
            for f in (self.root / lv).rglob("*"):
                if f.is_file():
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
        return removed


if __name__ == "__main__":
    # 自测
    print("=== cache_manager 自测 ===")
    cm = CacheManager()
    test_book = "test_book_hash_abc123"
    test_age, test_scene, test_depth = "adult", "running", "standard"
    test_text = "测试 TTS 片段内容"

    # L1
    cm.set_l1(test_book, test_age, test_scene, test_depth, "脚本内容...")
    got = cm.get_l1(test_book, test_age, test_scene, test_depth)
    print(f"L1 命中: {'✅' if got == '脚本内容...' else '❌'}")

    # L2 用临时文件模拟音频
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(b"\x00\x01\x02fake-mp3")
        tmp_path = tmp.name
    cm.set_l2(test_text, "zh-CN-XiaoxiaoNeural", "+0%", tmp_path)
    l2_hit = cm.get_l2(test_text, "zh-CN-XiaoxiaoNeural", "+0%")
    print(f"L2 命中: {'✅' if l2_hit and l2_hit.exists() else '❌'}")

    # L3
    script_hash = cm._md5("完整脚本")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp2:
        tmp2.write(b"\x00\x01\x02final-mp3")
        tmp3_path = tmp2.name
    cm.set_l3(script_hash, "zh-CN-XiaoxiaoNeural", "1.0", tmp3_path)
    l3_hit = cm.get_l3(script_hash, "zh-CN-XiaoxiaoNeural", "1.0")
    print(f"L3 命中: {'✅' if l3_hit and l3_hit.exists() else '❌'}")

    # 统计
    print(f"缓存统计: {cm.stats()}")

    # 清理测试文件
    import os as _os
    for p in [tmp_path, tmp3_path]:
        try: _os.unlink(p)
        except OSError: pass
    cm.clear("l2")
    print("清理 L2: ✅")
