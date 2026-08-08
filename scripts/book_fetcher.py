#!/usr/bin/env python3
"""bookmadebook 书籍获取（合规版）

仅支持合法来源：
1. Project Gutenberg（公版书，作者逝世超50年）
2. 用户提供的文件/URL（正版电子书/粘贴文本）

现代版权书请用 book_info.py（豆瓣公开信息/维基百科）。
已移除影子图书馆（安娜的档案）和微信读书抓取。

要求：
- 每个来源 15 秒超时，全局 60 秒
- 统一输出 Markdown 格式
- 最低 500 字符有效阈值
- 失败自动降级到下一个来源

用法：
    python book_fetcher.py "书名"                    # 公版书自动获取
    python book_fetcher.py --file xxx.pdf            # 本地文件
    python book_fetcher.py --url https://...         # 远程 URL
    python book_fetcher.py --source gutenberg "书名"  # 指定来源
"""
import argparse
import hashlib
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

MIN_CONTENT_LENGTH = 500
GLOBAL_TIMEOUT = 60
SOURCE_TIMEOUT = 15

CACHE_DIR = Path(os.path.expanduser("~/.hermes/cache/bookmadebook/books"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class BookFetchError(Exception):
    """书籍获取失败"""


class BookFetchResult:
    """统一获取结果"""
    def __init__(self, title: str, author: str = "", content: str = "",
                 source: str = "", url: str = ""):
        self.title = title
        self.author = author
        self.content = content
        self.source = source
        self.url = url

    def to_markdown(self) -> str:
        """统一输出 Markdown 格式"""
        lines = [
            f"# {self.title}",
            "",
            f"- **来源**: {self.source}",
        ]
        if self.author:
            lines.append(f"- **作者**: {self.author}")
        if self.url:
            lines.append(f"- **URL**: {self.url}")
        lines += ["", "---", "", self.content.strip()]
        return "\n".join(lines)

    @property
    def valid(self) -> bool:
        return len(self.content.strip()) >= MIN_CONTENT_LENGTH


def _http_get(url: str, timeout: int = SOURCE_TIMEOUT) -> str:
    """带 UA 的 HTTP GET，网络不稳定时自动重试 2 次"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 bookmadebook/1.0"
    })
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
            if "IncompleteRead" in type(e).__name__:
                time.sleep(1 * (attempt + 1))
                continue
            raise
    raise last_err


# ============================================================
# 来源 1：Project Gutenberg
# ============================================================
def fetch_gutenberg(title: str, timeout: int = SOURCE_TIMEOUT) -> BookFetchResult:
    """Project Gutenberg 公版书获取"""
    # 1. 搜索书
    search_url = (
        "https://gutendex.com/books?search="
        + urllib.parse.quote(title)
    )
    try:
        import json
        data = json.loads(_http_get(search_url, timeout))
    except Exception:
        # gutendex 不可用则用经典搜索页
        search_url = "https://www.gutenberg.org/ebooks/search/?query=" + urllib.parse.quote(title)
        html = _http_get(search_url, timeout)
        # 找第一条书的链接
        m = re.search(r'/ebooks/(\d+)', html)
        if not m:
            raise BookFetchError("Gutenberg 未找到匹配书籍")
        book_id = m.group(1)
        text_url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
        text = _http_get(text_url, timeout)
        if len(text) < MIN_CONTENT_LENGTH:
            raise BookFetchError("Gutenberg 文本过短")
        return BookFetchResult(title, "", text, "gutenberg", text_url)

    # gutendex JSON 方式
    books = data.get("results", [])
    if not books:
        raise BookFetchError("Gutenberg 未找到匹配书籍")

    book = books[0]
    book_id = book.get("id")
    title_out = book.get("title", title)
    author = ""
    authors = book.get("authors", [])
    if authors:
        author = authors[0].get("name", "")

    text_url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
    text = _http_get(text_url, timeout)

    # 去掉 Project Gutenberg 头尾
    text = re.sub(r"\*\*\*.*?\*\*\*", "", text, flags=re.DOTALL)
    text = text.strip()

    if len(text) < MIN_CONTENT_LENGTH:
        raise BookFetchError("Gutenberg 文本过短")

    return BookFetchResult(title_out, author, text, "gutenberg", text_url)


# ============================================================
# 来源 4：用户提供的文件/URL
# ============================================================
def fetch_user_file(path: str) -> BookFetchResult:
    """本地文件：支持 .txt/.md/.pdf(需 pdftotext)/.epub(需 ebook-convert)"""
    p = Path(path).expanduser()
    if not p.exists():
        raise BookFetchError(f"文件不存在: {path}")

    suffix = p.suffix.lower()
    if suffix in (".txt", ".md", ".markdown"):
        content = p.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        content = _convert_pdf(p)
    elif suffix in (".epub", ".mobi", ".azw3"):
        content = _convert_ebook(p)
    else:
        raise BookFetchError(f"不支持的格式: {suffix}")

    if len(content) < MIN_CONTENT_LENGTH:
        raise BookFetchError("文件内容过短")

    return BookFetchResult(p.stem, "", content, f"user_file:{suffix}", str(p))


def fetch_user_url(url: str, timeout: int = SOURCE_TIMEOUT) -> BookFetchResult:
    """远程 URL：尝试直接抓取网页文本"""
    content = _http_get(url, timeout)
    # 去掉 HTML 标签
    content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)
    content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"\s+", " ", content).strip()

    if len(content) < MIN_CONTENT_LENGTH:
        raise BookFetchError("URL 内容过短")

    title = urllib.parse.urlparse(url).path.split("/")[-1] or "web_page"
    return BookFetchResult(title, "", content, "url", url)


def _convert_pdf(p: Path) -> str:
    """用 pdftotext 转换 PDF"""
    import subprocess
    result = subprocess.run(
        ["pdftotext", str(p), "-"], capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise BookFetchError("PDF 转换失败，请安装 poppler-utils (pdftotext)")
    return result.stdout


def _convert_ebook(p: Path) -> str:
    """用 calibre ebook-convert 转换电子书"""
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as td:
        out_txt = Path(td) / "book.txt"
        result = subprocess.run(
            ["ebook-convert", str(p), str(out_txt)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0 or not out_txt.exists():
            raise BookFetchError("电子书转换失败，请安装 calibre")
        return out_txt.read_text(encoding="utf-8", errors="replace")


# ============================================================
# 统一入口
# ============================================================
def fetch_book(title: str, source: str = "auto") -> BookFetchResult:
    """按优先级获取书籍，失败自动降级（合规版）

    source: auto | gutenberg | user_file | url
    仅支持合法来源：古登堡计划（公版书）、用户提供文件/URL。
    现代版权书请用 book_info.py 获取公开信息（豆瓣/维基）。
    """
    if source == "user_file":
        return fetch_user_file(title)
    if source == "url":
        return fetch_user_url(title)
    if source == "gutenberg":
        order = ["gutenberg"]
    elif source == "auto":
        order = ["gutenberg"]
    else:
        raise BookFetchError(f"未知来源: {source}（合规版仅支持 gutenberg/user_file/url）")

    errors = []
    start = time.time()
    for src in order:
        if time.time() - start > GLOBAL_TIMEOUT:
            errors.append("全局 60 秒超时")
            break
        try:
            print(f"  🔍 尝试来源: {src}")
            result = {
                "gutenberg": fetch_gutenberg,
            }[src](title)
            if result.valid:
                print(f"  ✅ {src} 获取成功 ({len(result.content)} 字符)")
                return result
            errors.append(f"{src} 内容不足 {MIN_CONTENT_LENGTH} 字符")
        except BookFetchError as e:
            errors.append(str(e))
            print(f"  ❌ {src} 失败: {e}")
        except Exception as e:
            errors.append(f"{src} 异常: {e}")
            print(f"  ❌ {src} 异常: {e}")

    raise BookFetchError("所有来源均失败: " + "; ".join(errors))


def main():
    global MIN_CONTENT_LENGTH
    parser = argparse.ArgumentParser(description="bookmadebook 书籍获取降级链")
    parser.add_argument("query", nargs="?", help="书名或本地文件路径")
    parser.add_argument("--source", default="auto",
                        choices=["auto", "gutenberg", "user_file", "url"])
    parser.add_argument("--file", help="本地文件路径（等价 source=user_file）")
    parser.add_argument("--url", help="远程 URL（等价 source=url）")
    parser.add_argument("--output", "-o", help="输出 Markdown 路径（默认 stdout）")
    parser.add_argument("--min-chars", type=int, default=MIN_CONTENT_LENGTH)
    args = parser.parse_args()
    MIN_CONTENT_LENGTH = args.min_chars

    try:
        if args.file:
            result = fetch_user_file(args.file)
        elif args.url:
            result = fetch_user_url(args.url)
        else:
            if not args.query:
                parser.error("需要书名或 --file/--url")
            result = fetch_book(args.query, args.source)

        md = result.to_markdown()
        if args.output:
            out = Path(args.output).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
            print(f"✅ 已保存: {out}")
        else:
            print(md)

    except BookFetchError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

