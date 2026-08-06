#!/usr/bin/env python3
"""listen-book 书籍信息获取（合规版）

核心思路：精读音频是"引流种草"，不是盗版替代。
用户听了精读 → 被种草 → 去购买原书。

因此只需要获取**公开合法信息**，不需要完整书籍文本：
1. 书籍简介（豆瓣/出版社/维基）
2. 目录结构（公开页面）
3. 金句摘录（书评/媒体引用，合理使用）
4. 读者评价（豆瓣/Goodreads）
5. 作者背景（维基百科）

来源全部合法：豆瓣公开页、维基百科、出版社官网、Goodreads。

用法：
    python book_info.py "书名"                    # 自动获取书籍信息
    python book_info.py --file xxx.pdf            # 用户上传正版电子书
    python book_info.py --url https://...         # 用户提供文本URL
"""
import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

SOURCE_TIMEOUT = 15
GLOBAL_TIMEOUT = 60

CACHE_DIR = Path(os.path.expanduser("~/.hermes/cache/listen-book/info"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) listen-book/1.0"}


class BookInfoError(Exception):
    pass


class BookInfo:
    """书籍公开信息（用于生成精读，不含全文）"""
    def __init__(self, title="", author="", summary="", toc="",
                 quotes="", reviews="", source="", url="", buy_url=""):
        self.title = title
        self.author = author
        self.summary = summary      # 书籍简介
        self.toc = toc              # 目录（可选）
        self.quotes = quotes        # 金句摘录（合理引用）
        self.reviews = reviews      # 代表性评价
        self.source = source
        self.url = url
        self.buy_url = buy_url      # 购书链接（联盟佣金/书店）

    def to_markdown(self) -> str:
        """输出 Markdown（供 AI 生成精读脚本用）"""
        parts = [f"# 《{self.title}》书籍信息"]
        if self.author:
            parts.append(f"\n**作者**：{self.author}")
        if self.summary:
            parts.append(f"\n## 内容简介\n{self.summary}")
        if self.toc:
            parts.append(f"\n## 目录结构\n{self.toc}")
        if self.quotes:
            parts.append(f"\n## 金句摘录\n{self.quotes}")
        if self.reviews:
            parts.append(f"\n## 读者评价\n{self.reviews}")
        if self.buy_url:
            parts.append(f"\n## 购书链接\n{self.buy_url}")
        return "\n".join(parts)

    @property
    def valid(self) -> bool:
        return bool(self.summary and len(self.summary) > 200)


def _fetch(url: str, timeout: int = SOURCE_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ============================================================
# 豆瓣（简介+评价+金句线索）
# ============================================================
def fetch_douban(title: str, timeout: int = SOURCE_TIMEOUT) -> BookInfo:
    """豆瓣搜索+详情页（公开页面）"""
    search_url = "https://search.douban.com/book/subject_search?search_text=" + urllib.parse.quote(title)
    html = _fetch(search_url, timeout)
    # 从搜索页提取书籍ID
    ids = re.findall(r'subject/(\d+)/', html)
    if not ids:
        raise BookInfoError("豆瓣未找到该书籍")
    book_id = ids[0]

    detail_url = f"https://book.douban.com/subject/{book_id}/"
    detail = _fetch(detail_url, timeout)

    # 标题+作者
    title_m = re.search(r'<h1><span[^>]*>([^<]+)</span>', detail)
    author_m = re.search(r'<a[^>]*class="[^"]*"[^>]*>\s*([^<]{2,20})\s*</a>\s*</div>\s*<div class="pub"', detail)
    # 简介：匹配 intro 区域所有 <p> 段落
    summary_m = re.search(r'<div class="intro">(.*?)</div>\s*</div>', detail, re.DOTALL)
    if not summary_m:
        summary_m = re.search(r'<div class="intro">(.*?)</div>', detail, re.DOTALL)
    summary = ""
    if summary_m:
        paras = re.findall(r'<p>(.*?)</p>', summary_m.group(1), re.DOTALL)
        summary = " ".join(re.sub(r'<[^>]+>', '', p).strip() for p in paras)
    summary = re.sub(r'\s+', ' ', summary).strip()
    # 去掉 "(展开全部)" 标记及其后重复内容
    if "(展开全部)" in summary:
        summary = summary.split("(展开全部)")[0].strip()
    summary = re.sub(r'\s+', ' ', summary).strip()
    if len(summary) < 50:
        summary_m2 = re.search(r'<span class="all hidden">(.*?)</span>', detail, re.DOTALL)
        if summary_m2:
            summary = re.sub(r'<[^>]+>', '', summary_m2.group(1)).strip()
            summary = re.sub(r'\s+', ' ', summary).strip()

    # 评分
    rating_m = re.search(r'<strong class="ll rating_num"[^>]*>([\d.]+)</strong>', detail)
    rating = rating_m.group(1) if rating_m else ""

    author = author_m.group(1).strip() if author_m else ""
    summary_text = f"豆瓣评分：{rating}分\n\n{summary}" if rating else summary

    return BookInfo(
        title=title_m.group(1).strip() if title_m else title,
        author=author,
        summary=summary_text,
        source="douban",
        url=detail_url,
    )


# ============================================================
# 维基百科（作者背景+作品概述）
# ============================================================
def fetch_wikipedia(title: str, timeout: int = SOURCE_TIMEOUT) -> BookInfo:
    """维基百科中文版"""
    api_url = ("https://zh.wikipedia.org/w/api.php?action=query&prop=extracts"
               "&exintro&explaintext&format=json&titles=" + urllib.parse.quote(title))
    data = json.loads(_fetch(api_url, timeout))
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        extract = page.get("extract", "")
        if extract:
            return BookInfo(
                title=title, summary=extract,
                source="wikipedia",
                url=f"https://zh.wikipedia.org/wiki/{urllib.parse.quote(title)}",
            )
    raise BookInfoError("维基百科未找到该条目")


# ============================================================
# 用户提供内容（完全合法：用户购买的正版）
# ============================================================
def fetch_user_file(path: str) -> BookInfo:
    """用户上传的正版电子书/文本"""
    p = Path(path)
    if not p.exists():
        raise BookInfoError(f"文件不存在: {path}")
    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        content = p.read_text(encoding="utf-8", errors="replace")
    else:
        # 尝试用 calibre 转换或 pdftotext
        content = ""
        for cmd, out in [(["pdftotext", str(p), "-"], ".pdf")]:
            if suffix == out:
                try:
                    import subprocess
                    content = subprocess.run(cmd, capture_output=True, text=True).stdout
                except Exception:
                    pass
        if not content:
            raise BookInfoError("暂不支持该格式，请提供 .txt/.md 文件或粘贴文本")
    return BookInfo(
        title=p.stem, summary=content[:2000],
        source="user_file", url=str(p),
    )


def fetch_user_text(text: str) -> BookInfo:
    """用户粘贴的文本内容"""
    if len(text) < 100:
        raise BookInfoError("内容太短（<100字符）")
    return BookInfo(
        title="用户提供内容", summary=text[:2000],
        source="user_text",
    )


def fetch_user_url(url: str, timeout: int = SOURCE_TIMEOUT) -> BookInfo:
    """用户提供的文本URL（如自己博客/笔记）"""
    content = _fetch(url, timeout)
    return BookInfo(
        title=url.split("/")[-1], summary=content[:2000],
        source="user_url", url=url,
    )


# ============================================================
# 公版书检测（作者逝世>50年的经典）
# ============================================================
PUBLIC_DOMAIN_AUTHORS = {
    # 中文经典（春秋战国~清代）
    "孔子": "前479", "孟子": "前289", "老子": "前471", "庄子": "前286",
    "荀子": "前238", "韩非子": "前233", "司马迁": "前86", "诸葛亮": "234",
    "王羲之": "361", "李白": "762", "杜甫": "770", "韩愈": "824",
    "柳宗元": "819", "白居易": "846", "苏轼": "1101", "李清照": "1155",
    "辛弃疾": "1207", "文天祥": "1283", "罗贯中": "1400", "施耐庵": "1370",
    "吴承恩": "1582", "吴敬梓": "1754", "曹雪芹": "1763", "蒲松龄": "1715",
    "纪晓岚": "1805", "曾国藩": "1872", "左宗棠": "1885",
    # 外国经典
    "莎士比亚": "1616", "但丁": "1321", "歌德": "1832", "雨果": "1885",
    "托尔斯泰": "1910", "陀思妥耶夫斯基": "1881", "契诃夫": "1904",
    "马克·吐温": "1910", "安徒生": "1875", "王尔德": "1900",
    "简·奥斯汀": "1817", "狄更斯": "1870", "勃朗特": "1855",
    "福尔摩斯": "1930", "大仲马": "1870", "凡尔纳": "1905",
    "爱伦·坡": "1849", "司汤达": "1842", "巴尔扎克": "1850",
    "屠格涅夫": "1883", "高尔基": "1936", "杰克·伦敦": "1916",
    "海明威": "1961", "卡夫卡": "1924", "普鲁斯特": "1922",
}

PUBLIC_DOMAIN_BOOKS = [
    "论语", "孟子", "道德经", "庄子", "大学", "中庸", "诗经", "周易",
    "左传", "史记", "三国演义", "水浒传", "西游记", "红楼梦", "金瓶梅",
    "孙子兵法", "三十六计", "聊斋志异", "儒林外史", "古文观止", "唐诗三百首",
    "宋词三百首", "山海经", "搜神记", "世说新语", "资治通鉴", "战国策",
    "小王子", "老人与海", "傲慢与偏见", "简爱", "呼啸山庄", "双城记",
    "雾都孤儿", "基督山伯爵", "三个火枪手", "悲惨世界", "巴黎圣母院",
    "战争与和平", "安娜卡列尼娜", "罪与罚", "卡拉马佐夫兄弟", "套中人",
    "变色龙", "麦琪的礼物", "百万英镑", "汤姆索亚历险记", "哈克贝利费恩历险记",
    "格列佛游记", "鲁滨逊漂流记", "安徒生童话", "格林童话", "伊索寓言",
    "爱丽丝梦游仙境", "小妇人", "秘密花园", "彼得潘", "木偶奇遇记",
    "绿野仙踪", "柳林风声", "柳林风声", "金银岛", "八十天环游地球",
    "海底两万里", "神秘岛", "地心游记", "月亮与六便士",
]


def is_public_domain(title: str, author: str = "") -> bool:
    """判断是否为公版书（可合法获取全文）"""
    if author:
        for name in PUBLIC_DOMAIN_AUTHORS:
            if name in author:
                return True
    for book in PUBLIC_DOMAIN_BOOKS:
        if book in title:
            return True
    return False


# ============================================================
# 统一入口
# ============================================================
def get_book_info(title: str, source: str = "auto") -> BookInfo:
    """获取书籍公开信息（合法）

    source: auto | douban | wikipedia | gutenberg | user_file | user_text | url
    """
    if source == "user_file":
        return fetch_user_file(title)
    if source == "user_text":
        return fetch_user_text(title)
    if source == "url":
        return fetch_user_url(title)
    if source == "gutenberg":
        return fetch_gutenberg_summary(title)

    # auto：优先公开信息源，全部合法
    order = []
    if source == "douban":
        order = ["douban"]
    elif source == "wikipedia":
        order = ["wikipedia"]
    else:
        order = ["douban", "wikipedia"]

    errors = []
    start = time.time()
    for src in order:
        if time.time() - start > GLOBAL_TIMEOUT:
            errors.append("全局 60 秒超时")
            break
        try:
            print(f"  🔍 尝试来源: {src}")
            result = {
                "douban": fetch_douban,
                "wikipedia": fetch_wikipedia,
            }[src](title)
            if result.valid:
                print(f"  ✅ {src} 获取成功")
                return result
            errors.append(f"{src} 内容不足")
        except BookInfoError as e:
            errors.append(str(e))
        except Exception as e:
            errors.append(f"{src}: {e}")

    raise BookInfoError("；".join(errors) or "所有来源均失败")


def fetch_gutenberg_summary(title: str, timeout: int = SOURCE_TIMEOUT) -> BookInfo:
    """公版书：获取古登堡全文（合法）+ 自动摘要"""
    import subprocess
    sys_path = os.path.dirname(os.path.abspath(__file__))
    # 复用旧 book_fetcher 的 gutenberg 逻辑（如存在）
    try:
        sys_path_old = os.path.join(sys_path, "book_fetcher.py")  # 修复：同目录 scripts/
        if not os.path.exists(sys_path_old):
            # 兜底：仓库根目录
            sys_path_old = os.path.join(os.path.dirname(sys_path), "book_fetcher.py")
        if os.path.exists(sys_path_old):
            import importlib.util
            spec = importlib.util.spec_from_file_location("book_fetcher_old", sys_path_old)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.fetch_gutenberg(title, timeout)
            summary = result.content[:2000] if result.content else ""
            return BookInfo(
                title=result.title, author=result.author,
                summary=summary, source="gutenberg", url=result.url,
            )
    except Exception:
        pass
    raise BookInfoError("古登堡获取失败（公版书请稍后再试）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="listen-book 书籍信息获取（合规）")
    parser.add_argument("title", nargs="?", help="书名")
    parser.add_argument("--file", help="用户上传的文件")
    parser.add_argument("--text", help="用户粘贴的文本")
    parser.add_argument("--url", help="用户提供的URL")
    parser.add_argument("--source", default="auto",
                        choices=["auto", "douban", "wikipedia", "gutenberg",
                                 "user_file", "user_text", "url"])
    args = parser.parse_args()

    try:
        if args.file:
            info = fetch_user_file(args.file)
        elif args.text:
            info = fetch_user_text(args.text)
        elif args.url:
            info = fetch_user_url(args.url)
        elif args.title:
            info = get_book_info(args.title, args.source)
        else:
            parser.print_help()
            sys.exit(1)
        print(info.to_markdown())
        print(f"\n[来源: {info.source}] [合规: 公开信息/用户提供]")
    except BookInfoError as e:
        print(f"⚠️ {e}")
        print("提示：如为现代版权书，请上传您购买的正版电子书 (--file) 或粘贴内容 (--text)")
        sys.exit(1)
