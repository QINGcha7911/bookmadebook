#!/usr/bin/env python3
"""bookmadebook 章节索引提取器（借鉴 book-to-skill 的"结构先行"模式）

把书籍源文件（PDF/TXT/MD）的章节结构提取为 chapters.json，供长稿扩充时
按章索引加载——008 做 5-6 轮长稿扩充时只读相关章节，省 token、提速、少幻觉。

用法:
    python scripts/extract_chapters.py "书名" [--file xxx.pdf] [--cache-dir ~/.hermes/cache/bookmadebook/books]
    python scripts/extract_chapters.py --file 活着.pdf --out-dir ./books/活着

输出:
    <out-dir>/chapters.json
    {
      "book": "活着",
      "source": "xxx.pdf",
      "total_chars": 123456,
      "chapter_pattern": "第X章",
      "chapters": [
        {"num": 1, "title": "第一章 引言", "start_char": 0, "end_char": 5000, "est_tokens": 2500, "preview": "…前120字…"},
        ...
      ],
      "generated_at": "2026-08-30T..."
    }

设计要点（来自 book-to-skill 借鉴）:
1. 确定性提取：pymupdf 解析 → 正则章节识别，不依赖 LLM（快、免费、可复现）
2. 优雅降级：无 PDF 库时用文本文件；识别不到章节时退化输出单一"全书"块
3. 按需加载：chapters.json 只存索引 + 预览，正文由调用方按 start/end_char 切片读取
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 中英文章节标题模式（按优先级尝试）
CHAPTER_PATTERNS = [
    re.compile(r"^\s*(第[一二三四五六七八九十百千0-9]+[章节回部卷篇]\s*.*)$"),  # 第一章 xxx
    re.compile(r"^\s*(Chapter\s+\d+.*)$", re.IGNORECASE),                      # Chapter 1
    re.compile(r"^\s*(Part\s+[IVX0-9]+.*)$", re.IGNORECASE),                   # Part I
    re.compile(r"^\s*([0-9]+\.\s+\S.*)$"),                                     # 1. xxx
    re.compile(r"^\s*(CHAPTER\s+[IVX0-9]+.*)$"),                               # CHAPTER I
]

# 排除噪声行（版权页、页码、空行等）
NOISE_RE = re.compile(
    r"^\s*($|[\d\s\W_]{1,12}$|第\s*\d+\s*页|Copyright|ISBN|©|—\s*\d+\s*—)",
    re.IGNORECASE,
)


def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg: str) -> None:
    print(f"📑 {msg}", flush=True)


def extract_text(path: Path) -> str:
    """提取纯文本：PDF 用 pymupdf，其他用 utf-8 读取。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz  # pymupdf

            doc = fitz.open(str(path))
            parts = [page.get_text("text") for page in doc]
            doc.close()
            return "\n".join(parts)
        except ImportError:
            log("⚠️ pymupdf 未安装，尝试文本模式")
        except Exception as exc:
            log(f"⚠️ PDF 解析失败: {exc}，尝试文本模式")
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return path.read_text(encoding=enc, errors="replace")
        except Exception:
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


def find_chapters(text: str) -> tuple[list[dict], str]:
    """按章节模式识别章节边界。返回 (chapters, 命中的模式名)。"""
    lines = text.splitlines()
    candidates: list[dict] = []  # {"title", "line_no", "start_char"}
    for line_no, line in enumerate(lines):
        if NOISE_RE.match(line):
            continue
        for pattern in CHAPTER_PATTERNS:
            m = pattern.match(line)
            if m:
                title = m.group(1).strip()
                # 真章节标题特征：
                # 1. 长度 ≤ 30 字
                # 2. 不以句号/逗号结尾（正文句子的行首误匹配排除）
                # 3. 不含正文过渡词（内容/继续/展开/讲述/描写等）
                if len(title) > 30:
                    continue
                if title.endswith(("。", "，", "；", "！", "？", "：", "……")):
                    continue
                if re.search(r"(内容|继续|展开|讲述|描写|关于|以下|如下)", title):
                    continue
                start_char = sum(len(l) + 1 for l in lines[:line_no])
                candidates.append(
                    {"title": title, "line_no": line_no, "start_char": start_char}
                )
                break

    if not candidates:
        return [], "none"

    # 记录用到的模式（取第一个候选的）
    used_pattern = "第X章" if "第" in candidates[0]["title"] else (
        "Chapter N" if "Chapter" in candidates[0]["title"] else (
            "Part N" if "Part" in candidates[0]["title"] else (
                "N. title" if re.match(r"^\d+\.", candidates[0]["title"]) else "other"
            )
        )
    )

    # 转成区间
    chapters = []
    for i, cand in enumerate(candidates):
        end_char = (
            candidates[i + 1]["start_char"]
            if i + 1 < len(candidates)
            else len(text)
        )
        body = text[cand["start_char"] : end_char]
        est_tokens = max(1, int(len(body) / 1.7))  # 中文约 1.7 字符/token
        preview = re.sub(r"\s+", " ", body[:120]).strip()
        chapters.append(
            {
                "num": i + 1,
                "title": cand["title"],
                "start_char": cand["start_char"],
                "end_char": end_char,
                "est_tokens": est_tokens,
                "preview": preview[:120],
            }
        )
    return chapters, used_pattern


def resolve_source(book: str, file_arg: str | None, cache_dir: Path) -> Path | None:
    """找书籍源文件：优先 --file，其次缓存目录里匹配书名的文件。"""
    if file_arg:
        p = Path(file_arg)
        if p.exists():
            return p
        log(f"⚠️ --file 不存在: {file_arg}")
        return None
    if cache_dir.exists():
        matches = [
            p
            for p in cache_dir.iterdir()
            if p.is_file() and book.replace("《", "").replace("》", "") in p.name
        ]
        if matches:
            return sorted(matches, key=lambda p: p.stat().st_mtime)[-1]
    return None


def main() -> None:
    setup_utf8()
    parser = argparse.ArgumentParser(description="bookmadebook 章节索引提取器")
    parser.add_argument("book", nargs="?", help="书名（用于匹配缓存文件）")
    parser.add_argument("--file", help="书籍源文件（PDF/TXT/MD）")
    parser.add_argument("--cache-dir", default="~/.hermes/cache/bookmadebook/books",
                        help="书籍缓存目录")
    parser.add_argument("--out-dir", help="输出目录（默认: ./books/<书名>）")
    args = parser.parse_args()

    if not args.book and not args.file:
        parser.error("必须提供书名或 --file")

    book = (args.book or Path(args.file).stem).strip()
    cache_dir = Path(args.cache_dir).expanduser()
    source = resolve_source(book, args.file, cache_dir)
    if not source:
        log(f"❌ 未找到《{book}》的源文件（缓存目录 {cache_dir} 为空或未匹配）")
        log("   提示: 先用 book_fetcher.py 获取书籍，或 --file 指定本地文件")
        sys.exit(1)

    log(f"解析: {source.name}（{source.stat().st_size/1024:.0f} KB）")
    text = extract_text(source)
    if len(text.strip()) < 200:
        log(f"❌ 文本过短（{len(text)} 字符），可能不是有效书籍")
        sys.exit(1)

    chapters, pattern = find_chapters(text)
    result = {
        "book": book,
        "source": str(source),
        "total_chars": len(text),
        "chapter_pattern": pattern,
        "chapters": chapters,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    out_dir = Path(args.out_dir) if args.out_dir else Path("books") / book
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "chapters.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not chapters:
        log(f"⚠️ 未识别到章节标题（模式: none），全书作为单一块输出")
    else:
        log(f"✅ 识别到 {len(chapters)} 章（模式: {pattern}）")
        for ch in chapters[:8]:
            log(f"   [{ch['num']:>2}] {ch['title'][:40]}  ~{ch['est_tokens']/1000:.1f}K tokens")
        if len(chapters) > 8:
            log(f"   … 其余 {len(chapters)-8} 章省略")
    log(f"💾 已写入: {out_path}")
    print(json.dumps({"ok": True, "chapters": len(chapters),
                      "out": str(out_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
