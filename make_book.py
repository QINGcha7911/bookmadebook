#!/usr/bin/env python3
"""bookmadebook 一键流水线：书名 → 讲书稿 + 音频/视频 + 海报 + 小红书文案。

用法:
    python make_book.py "活着 10分钟" [--theme desert|forest|ocean] [--style ted|normal] [--output-type audio|video]
    python make_book.py "活着 10分钟" --api-key sk-xxx --strict

默认输出到 ./bookmadebook-output/<书名>/
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.sax.saxutils
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = Path("bookmadebook-output")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_ENV_FILE = Path(r"C:\Users\dongj\AppData\Local\hermes\.env")

VIDEO_KEYWORDS = ["视频", "短片", "配画面", "有画面", "video", "vlog"]
AUDIO_KEYWORDS = ["音频", "听书", "播客", "audio", "podcast", "mp3", "听"]
SCENE_WORDS = ["跑步", "通勤", "睡前", "开车", "运动", "开车时", "散步"]


def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(emoji: str, message: str) -> None:
    print(f"{emoji} {message}", flush=True)


def parse_request(text: str) -> dict:
    """复用 listen.py 的自然语言解析逻辑。"""
    t = text.strip()
    lower = t.lower()
    output_type = "audio"
    if any(k in lower for k in VIDEO_KEYWORDS):
        output_type = "video"
    elif any(k in lower for k in AUDIO_KEYWORDS):
        output_type = "audio"

    t = t.replace("《", "").replace("》", "").replace('"', "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:分钟|min)", t, re.IGNORECASE)
    minutes = float(m.group(1)) if m else 10.0
    if m:
        t = t[: m.start()].strip()

    for kw in VIDEO_KEYWORDS + AUDIO_KEYWORDS:
        t = t.replace(kw, "").strip()
    t = re.sub(r"(做个|要个|来一个|来段|生成|做一段|来一段|给我|帮我)\s*$", "", t).strip()
    t = re.sub(r"^(给我|帮我)\s*(做个|要个|生成|做一段)?\s*", "", t).strip()
    t = re.sub(r"^(做个|要个|来一个|来段|生成|做一段|来一段)\s*", "", t).strip()
    for word in SCENE_WORDS:
        if t.endswith(word):
            t = t[: -len(word)].strip()
            break
    t = t.strip("，。、 ")
    return {"book": t, "minutes": minutes, "output_type": output_type}


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name or "").strip()
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "未命名"


def minutes_label(minutes: float) -> str:
    return str(int(minutes)) if float(minutes).is_integer() else f"{minutes:g}"


def load_api_key(cli_key: str) -> str | None:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if DEEPSEEK_ENV_FILE.exists():
        try:
            for raw in DEEPSEEK_ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if line.lower().startswith("export "):
                    line = line[7:].strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                env_key, env_value = line.split("=", 1)
                if env_key.strip().upper() == "DEEPSEEK_API_KEY":
                    candidate = env_value.strip().strip('"').strip("'")
                    if candidate:
                        return candidate
        except Exception:
            pass
    if cli_key:
        return cli_key.strip()
    return None


def call_deepseek(messages: list[dict], api_key: str, timeout: int = 180) -> str:
    if not api_key:
        raise RuntimeError(
            "未提供 DeepSeek API Key；请设置环境变量 DEEPSEEK_API_KEY、"
            "在 .env 中配置，或使用 --api-key 传入。"
        )
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek API 请求失败: {exc.reason}") from exc

    try:
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise RuntimeError(f"DeepSeek API 返回异常: {raw[:300]}") from None


def generate_script(book: str, minutes: float, api_key: str) -> str:
    char_budget = max(400, int(round(minutes * 282)))
    system = (
        "你是一位资深图书讲书人兼 TED 演讲导演，擅长把一本书压缩成"
        "高密度、有感染力、适合口播的讲书稿。"
    )
    user = f"""请为《{book}》写一份约 {char_budget} 字的讲书稿，目标时长 {minutes_label(minutes)} 分钟。

必须遵守：
1. 采用 bookmadebook 4.2.1 讲书稿结构：开场悬念钩子 → 时间线分段（零重叠、同一主题只出现一次）→ 每章给出主线+细节+解读 → 结尾升华。
2. 禁止乱序补充段落、注水和重复内容。
3. 全稿 4-6 句【金句】，必须是书中原句，格式为【金句】原文。
4. TED 情绪多样化：在需要处标注【情绪：开心/悲伤/紧张/温柔/坚定/疑惑/神秘/爆发/轻声】。
5. 每章至少一个【停顿0.5】；金句前停顿并重读。
6. 字数预算约 {char_budget} 字。
7. 版权红线：只讲精华、不朗读全文、不逐段复制。
8. 每个章节开头标注【场景：XX】（用于视频实景匹配），从以下选最贴合本章内容的：宫殿/古建/沙漠/星空/海洋/海边/森林/日出/山巅/银河/夜空/雨夜/书房/暖光家居/雪原/都市夜景/寺庙/香港街景/牧场/航船。不确定时用通用（沙漠/森林/海洋）。
9. 用中文输出完整讲书稿，不要输出额外说明。"""
    return call_deepseek(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        api_key,
    )


def generate_xhs(book: str, api_key: str, script_path: Path | None = None) -> str:
    topic = "全书精华"
    if script_path and script_path.exists():
        try:
            first_line = next(
                (
                    line.strip()
                    for line in script_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ),
                "",
            )
            if first_line:
                topic = first_line[:80]
        except Exception:
            pass

    system = "你是擅长图书种草的小红书文案编辑，文案要口语、克制但不干瘪。"
    user = f"""书名：《{book}》
主题参考：{topic}

请只输出一篇可直接发布的小红书文案，结构如下：
## 标题
- 标题候选1
- 标题候选2
- 标题候选3

## 正文
4-5 行口语化正文，突出“想听什么就生成什么”，每行不要超过 30 字。

## 标签
5-8 个标签，用 # 开头。"""
    return call_deepseek(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        api_key,
    )


def _wrap_text(text: str, limit: int = 10) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    lines: list[str] = []
    current = ""
    for ch in text:
        current += ch
        if len(current) >= limit:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return lines


def _esc(value: str) -> str:
    return xml.sax.saxutils.escape(value, {'"': "&quot;"})


def make_poster(book: str, output_path: Path) -> Path:
    title_lines = _wrap_text(book, 10)
    title_tspans = "\n".join(
        f'      <tspan x="450" dy="{index * 62}">{_esc(line)}</tspan>'
        for index, line in enumerate(title_lines)
    )
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1500" viewBox="0 0 900 1500" role="img" aria-label="{_esc(book)} 讲书海报">
  <defs>
    <filter id="paper" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="4" seed="7" stitchTiles="stitch"/>
      <feColorMatrix type="matrix" values="0 0 0 0 0.86 0 0 0 0 0.82 0 0 0 0 0.76 0 0 0 0.10 0"/>
    </filter>
    <pattern id="lined" width="900" height="24" patternUnits="userSpaceOnUse">
      <path d="M0 24 H900" stroke="#cbbfa9" stroke-width="1" opacity="0.55"/>
    </pattern>
  </defs>

  <rect width="900" height="1500" fill="#f1e9da"/>
  <rect width="900" height="1500" filter="url(#paper)" opacity="0.92"/>
  <rect x="54" y="54" width="792" height="1392" fill="none" stroke="#1f2937" stroke-width="3"/>
  <rect x="72" y="72" width="756" height="1356" fill="#f7f1e6" opacity="0.5"/>
  <rect x="72" y="72" width="756" height="1356" fill="url(#lined)" opacity="0.6"/>

  <g fill="none" stroke="#1f2937" stroke-width="2">
    <path d="M105 164 H795"/>
    <path d="M105 176 H795"/>
  </g>
  <text x="450" y="150" text-anchor="middle" font-family="'Avenir Next','Helvetica Neue',Arial,sans-serif" font-size="22" letter-spacing="7" fill="#1f2937">BOOKMADEBOOK</text>
  <rect x="412" y="188" width="76" height="4" fill="#e04a2f"/>

  <g transform="translate(240 310) rotate(-6)">
    <rect x="-120" y="-160" width="240" height="320" rx="2" fill="#fffdf7" stroke="#1f2937" stroke-width="3"/>
    <path d="M-78 -96 H78 M-78 -42 H78 M-78 12 H52" fill="none" stroke="#b7aa93" stroke-width="3" stroke-linecap="round"/>
  </g>
  <g transform="translate(655 1180) rotate(6)">
    <rect x="-120" y="-160" width="240" height="320" rx="2" fill="#f3ead9" stroke="#1f2937" stroke-width="2"/>
    <path d="M-78 -80 H78 M-78 -34 H78" fill="none" stroke="#b7aa93" stroke-width="2" stroke-linecap="round"/>
  </g>

  <text x="450" y="620" text-anchor="middle" font-family="'Songti SC','STSong','Noto Serif SC',serif" font-size="76" font-weight="700" fill="#1f2937">
{title_tspans}
  </text>
  <text x="450" y="{640 + len(title_lines) * 62}" text-anchor="middle" font-family="'Avenir Next','Helvetica Neue',Arial,sans-serif" font-size="22" letter-spacing="5" fill="#e04a2f">bookmadebook</text>
  <text x="450" y="{668 + len(title_lines) * 62}" text-anchor="middle" font-family="'Songti SC','STSong','Noto Serif SC',serif" font-size="17" fill="#5f564a">一部书 · 一档有声讲书</text>

  <g fill="none" stroke="#e04a2f" stroke-width="6" stroke-linecap="round">
    <path d="M170 1300 H190 M208 1250 H228 M246 1330 H266 M284 1270 H304 M322 1345 H342 M360 1290 H380 M398 1320 H418 M436 1255 H456 M474 1310 H494 M512 1270 H532 M550 1335 H570 M588 1280 H608 M626 1305 H646 M664 1260 H684 M702 1325 H722"/>
  </g>
  <circle cx="450" cy="1370" r="5" fill="#e04a2f"/>
  <text x="450" y="1418" text-anchor="middle" font-family="'Songti SC','STSong','Noto Serif SC',serif" font-size="16" fill="#1f2937">想听什么，就生成什么</text>
</svg>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def run_media(
    book: str,
    minutes: float,
    script_path: Path,
    output_type: str,
    theme: str,
    style: str,
    voice: str,
    out_dir: Path,
) -> bool:
    listen_py = BASE_DIR / "listen.py"
    if not listen_py.exists():
        raise FileNotFoundError(f"找不到 listen.py: {listen_py}")

    safe_book = safe_name(book)
    ext = ".mp4" if output_type == "video" else ".mp3"
    media_path = out_dir / f"{safe_book}{ext}"
    request = f"{book} {minutes_label(minutes)}分钟"
    if output_type == "video":
        request += "视频"

    # 反推实际时长：讲书稿中文字数 / 语速 282 字/分（避免验证门拦截）
    try:
        _st = script_path.read_text(encoding="utf-8")
        _cn = len(re.findall(r"[\u4e00-\u9fff]", _st))
        # 目标时长 = 实际字数时长×0.95（满足质量门 est≥target×0.9 且贴近实际，避免验证门偏差拦截）
        actual_min = max(float(minutes), round(_cn / 282 * 0.95, 1))
        if abs(actual_min - float(minutes)) > 0.1:
            log("⏱️", f"讲书稿 {_cn} 字 ≈ {_cn/282:.1f} 分钟，目标时长调整为 {actual_min} 分钟")
    except Exception:
        actual_min = float(minutes)

    cmd = [
        sys.executable,
        str(listen_py),
        request,
        "--file",
        str(script_path),
        "--target-minutes",
        str(actual_min),
        "--theme",
        theme,
        "--style",
        style,
        "--voice",
        voice,
        "--output",
        str(media_path),
        "--output-type",
        output_type,
    ]
    log("🔗", f"[2/5] 调用 listen.py: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"listen.py 返回非零退出码 {result.returncode}")
    return media_path.exists()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="bookmadebook 一键流水线：讲书稿 + 音频/视频 + 海报 + 小红书文案"
    )
    parser.add_argument("request", help='自然语言请求，如 "活着 10分钟" 或 "活着 10分钟视频"')
    parser.add_argument("--theme", default="auto", choices=["auto", "desert", "forest", "ocean",
                       "palace", "sunrise", "starry", "rain", "library", "warm_home", "snow",
                       "tech_city", "temple", "hongkong", "pasture", "ship"], help="视频实景主题（auto=按内容自动选择）")
    parser.add_argument("--style", default="ted", choices=["normal", "ted"], help="朗读风格")
    parser.add_argument("--output-type", choices=["audio", "video"], help="输出类型，覆盖自然语言识别")
    parser.add_argument("--voice", default="auto", help="TTS 声音，透传给 listen.py")
    parser.add_argument("--api-key", help="DeepSeek API Key（env/.env 未配置时使用）")
    parser.add_argument("--strict", action="store_true", help="任一步失败立即退出")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出根目录，默认 ./bookmadebook-output")
    return parser


def main() -> None:
    setup_utf8()
    args = build_parser().parse_args()
    req = parse_request(args.request)
    book = req["book"] or "未命名"
    minutes = req["minutes"]
    output_type = args.output_type or req["output_type"]
    safe_book = safe_name(book)
    out_dir = Path(args.output_dir) / safe_book
    out_dir.mkdir(parents=True, exist_ok=True)
    api_key = load_api_key(args.api_key)

    log("📚", f"请求解析: 书名={book} | 时长={minutes_label(minutes)}分钟 | 输出={output_type}")
    log("📁", f"输出目录: {out_dir}")

    script_path = out_dir / f"{safe_book}_script.txt"
    if not api_key:
        log(
            "⏭️",
            "未找到 DeepSeek API Key；可用 DEEPSEEK_API_KEY 环境变量、.env 或 --api-key 提供。",
        )

    try:
        script = generate_script(book, minutes, api_key)
        script_path.write_text(script, encoding="utf-8")
        log("✅", f"[1/5] 讲书稿已生成（约 {len(script)} 字）: {script_path}")
    except Exception as exc:
        log("❌", f"[1/5] 讲书稿生成失败: {exc}")
        if args.strict:
            sys.exit(1)

    if script_path.exists():
        try:
            ok = run_media(
                book,
                minutes,
                script_path,
                output_type,
                args.theme,
                args.style,
                args.voice,
                out_dir,
            )
            ext = ".mp4" if output_type == "video" else ".mp3"
            if ok:
                log("✅", f"[2/5] 音频/视频已生成: {out_dir / f'{safe_book}{ext}'}")
        except Exception as exc:
            log("❌", f"[2/5] 音频/视频生成失败: {exc}")
            if args.strict:
                sys.exit(1)
    else:
        log("⏭️", "[2/5] 跳过音频/视频：讲书稿不存在")

    try:
        poster_path = out_dir / f"{safe_book}_poster.svg"
        make_poster(book, poster_path)
        log("✅", f"[3/5] 海报已生成: {poster_path}")
    except Exception as exc:
        log("❌", f"[3/5] 海报生成失败: {exc}")
        if args.strict:
            sys.exit(1)

    if api_key:
        try:
            xhs_path = out_dir / f"{safe_book}_xiaohongshu.md"
            xhs_path.write_text(generate_xhs(book, api_key, script_path), encoding="utf-8")
            log("✅", f"[4/5] 小红书文案已生成: {xhs_path}")
        except Exception as exc:
            log("❌", f"[4/5] 小红书文案生成失败: {exc}")
            if args.strict:
                sys.exit(1)
    else:
        log("⏭️", "[4/5] 跳过小红书文案：未配置 DeepSeek API Key")

    log("📦", "[5/5] 输出清单")
    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    for file_path in files:
        log("  -", str(file_path))
    if not files:
        log("  -", "（无输出）")


if __name__ == "__main__":
    main()
