#!/usr/bin/env python3
"""bookmadebook 写稿器（Web 自助点书 daemon 专用）

输入 书名+时长+音色类型（成人/儿童），调 DeepSeek API 生成可直接进
streaming_pipeline/harness 的讲书稿 txt（纯文本 + 【】表演注解）。

与 make_book.py 内置 generate_script 的区别：
  - key/model/base_url 从 ~/.hermes/config.yaml model.providers.deepseek 读取
    （不硬编码落盘，与仓库其他脚本的凭据规范一致）
  - 成人线读 prompts/standard_mode.txt 写作原则（精读：90% 书内容）
  - 儿童线读 prompts/children/<age>.txt（白名单公版书，可完整讲故事）
  - 目标字数按"质量门可过"的引擎语速估算（10min≈2600-2800 字）
  - 字数不足自动补批续写（动态分批，避免单次输出截断）

用法:
    python write_script.py --book-title 活着 --target-minutes 10 \\
        --voice husky_tender --product-type adult --out /tmp/script.txt
    python write_script.py --book-title 小王子 --target-minutes 10 \\
        --product-type child --age-band 3-6 --out /tmp/kid.txt
    python write_script.py --book-title X --target-minutes 2 --mock --out /tmp/mock.txt

退出码:
    0 = 成功（--out 文件已写）
    2 = 写稿失败（配置缺失/API 错误/字数多次补批仍不达标）
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS = REPO_ROOT / "prompts"

# 引擎语速（质量门口径：style=ted 乘 0.85 后约 240 字/分）——
# 儿童模板里的"每分钟 120/170 字"是句式节奏设计，不是 TTS 实际读速，
# 音频时长达标以引擎语速计（否则儿童稿会被质量门以字数不足拦截）。
ENGINE_SPEED = 240.0

# 年龄档 → 儿童模板（prompts/children/）
CHILD_TEMPLATES = {
    "3-6": "preschool_mode.txt",
    "7-12": "primary_upper_mode.txt",
}


def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def log(msg: str) -> None:
    print(f"✍️  {msg}", flush=True)


# ── DeepSeek 凭据（不硬编码：env > ~/.hermes/config.yaml > ~/.hermes/.env）──
def find_deepseek_config() -> dict:
    """返回 {api_key, base_url, model}；找不到 key 时 api_key 为空。"""
    cfg = {"api_key": "", "base_url": "https://api.deepseek.com/v1",
           "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")}
    cfg["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "").strip()

    # ~/.hermes/config.yaml（agent 主配置：model.providers.deepseek）
    hermes_cfg = Path.home() / ".hermes" / "config.yaml"
    # 仓库 config.yaml（若未来加入 model 段也兼容）
    for path in (hermes_cfg, REPO_ROOT / "config.yaml"):
        if not path.exists():
            continue
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        prov = (data.get("model") or {}).get("providers") or {}
        ds = prov.get("deepseek") or {}
        if isinstance(ds, dict):
            cfg["api_key"] = cfg["api_key"] or str(ds.get("api_key", "") or "").strip()
            if ds.get("base_url"):
                cfg["base_url"] = str(ds["base_url"]).rstrip("/")
            if ds.get("model"):
                cfg["model"] = str(ds["model"])

    # ~/.hermes/.env / Windows hermes .env（历史形态兜底）
    for env_file in (Path.home() / ".hermes" / ".env",
                     Path(r"C:\Users\dongj\AppData\Local\hermes\.env")):
        if cfg["api_key"] or not env_file.exists():
            continue
        try:
            for raw in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if raw.strip().startswith("DEEPSEEK_API_KEY="):
                    cfg["api_key"] = raw.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return cfg


def call_deepseek(cfg: dict, messages: list, timeout: int = 240) -> str:
    """调 chat/completions，返回纯文本内容。
    含重试：网络抖动/RemoteDisconnected 时指数退避重试（最多 3 次）。"""
    if not cfg.get("api_key"):
        raise RuntimeError(
            "未找到 DeepSeek API Key：请设置 DEEPSEEK_API_KEY 环境变量，"
            "或在 ~/.hermes/config.yaml 的 model.providers.deepseek.api_key 配置"
        )
    url = f"{cfg['base_url']}/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
        "max_tokens": 8192,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        })
    # 重试：URLError（含 RemoteDisconnected）/5xx 指数退避最多 3 次
    import time as _t
    last_exc = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(exc)
            if exc.code < 500 or attempt == 2:
                raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {detail[:300]}") from exc
            last_exc = exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == 2:
                raise RuntimeError(f"DeepSeek API 请求失败（重试 3 次后）: {exc}") from exc
        _t.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"DeepSeek API 请求失败（重试 3 次后）: {last_exc}") from last_exc
    try:
        data = json.loads(raw)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise RuntimeError(f"DeepSeek API 返回异常: {raw[:300]}") from None


# ── 模板与字数 ──────────────────────────────────────────────────────────
def char_count(text: str) -> int:
    """有效字数：去掉【】注解与空白后的汉字+字母数字。"""
    t = re.sub(r"【[^】]*】", "", text)
    return len(re.sub(r"\s", "", t))


def load_template(product_type: str, age_band: str) -> str:
    """读 prompts/ 模板原文（写稿原则），不存在则返回内置兜底。"""
    if product_type == "child":
        name = CHILD_TEMPLATES.get(age_band or "", "preschool_mode.txt")
        path = PROMPTS / "children" / name
    else:
        path = PROMPTS / "standard_mode.txt"
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ("内容以书籍真实内容为准：90% 篇幅讲书里的情节/人物/细节，"
                "解读不超过 10%；口语化；不编造书中不存在的内容。")


def plan_targets(target_minutes: float, product_type: str) -> tuple[int, int]:
    """返回 (下限字数 floor, 目标字数 target)。
    下限按质量门口径：floor = 分钟 × 240 × 0.9（不足会被质量门拦截）。
    成人目标按"讲书稿框架"惯例取 2600-2800 字/10min 等比扩。"""
    floor = int(target_minutes * ENGINE_SPEED * 0.9)
    if product_type == "child":
        return floor, int(target_minutes * 250)
    per_10 = 2700  # 10 分钟约 2600-2800 字的中间值
    return floor, max(floor + 200, int(round(target_minutes / 10.0)) * per_10)


# ── Prompt 组装 ─────────────────────────────────────────────────────────
def make_user_prompt(book_title: str, target_minutes: float, product_type: str,
                     age_band: str, template: str, need_chars: int,
                     is_continuation: bool, prev_tail: str = "") -> str:
    if product_type == "child":
        age_label = {"3-6": "3-6 岁学龄前", "7-12": "7-12 岁学龄"}.get(age_band, "")
        lines = [
            f"本次任务：为 {age_label}孩子讲解公版经典《{book_title}》。",
            "《{book_title}》是公版书，可完整讲述其故事，但仍请用自己的语言讲故事，"
            "不要整段照搬原文。".format(book_title=book_title),
            f"目标时长约 {target_minutes:g} 分钟（音频约 {need_chars} 字）。",
            "",
            "写作原则（严格遵循）：",
            template,
            "",
            "输出要求：",
            "1. 只输出故事正文纯文本（不要 JSON、不要 Markdown 标题、不要输出书名行）。",
            "2. 句子短、口语化；适当穿插【停顿0.5】；关键打动处用【情绪：温暖/开心/温柔】。",
            "3. 结尾温柔收尾，不喊口号。",
        ]
    else:
        lines = [
            f"本次任务：为《{book_title}》写一份 {target_minutes:g} 分钟精读讲书稿"
            f"（约 {need_chars} 字，10 分钟对应 2600-2800 字，按比例扩展）。",
            "《{book_title}》为普通出版书，只做精华解读——禁止朗读或大段复制原文。"
            .format(book_title=book_title),
            "",
            "写作原则（严格遵循）：",
            template,
            "注：模板中的 JSON 结构仅作章节思路参考，最终请输出正文纯文本，不要输出 JSON。",
            "",
            "输出要求：",
            "1. 只输出正文纯文本（不要 JSON、不要 Markdown 标题、不要输出书名标题行）。",
            "2. 结构：悬念开场 → 时间线/章节顺序推进（【章节N：标题】标记开头）→ 金句 → 结尾升华。",
            "3. 金句 4-6 句，格式【金句】书中原句，必须真实出自该书。",
            "4. 情绪起伏：在合适处标注【情绪：激动/低沉/温暖/紧张/坚定】；"
            "段落转折用【停顿0.5】。",
            "5. 严禁编造书中不存在的人名/情节/细节；内容不足宁可写短。",
        ]
    if is_continuation:
        lines += [
            "",
            f"这是续写批。上一批结尾为：「{prev_tail[-120:]}」。",
            "请按全书脉络自然衔接继续，写全新内容：严禁重复上一批已出现的段落、"
            "句子与【金句】（金句全稿只出现一次）；每段必须有新信息。",
        ]
    return "\n".join(lines)


SYSTEM_ADULT = ("你是一位资深图书讲书人兼 TED 演讲导演，擅长把一本书压缩成"
                "高密度、有感染力、适合口播的讲书稿。你的稿件会直接交给 TTS 朗读。")
SYSTEM_CHILD = ("你是一位儿童故事讲解员，声音亲切温暖，擅长给不同年龄段孩子"
                "讲公版经典故事。你的稿件会直接交给 TTS 朗读。")


# ── 写稿主流程 ─────────────────────────────────────────────────────────
def generate_real(cfg: dict, book_title: str, target_minutes: float,
                  product_type: str, age_band: str) -> str:
    floor, target = plan_targets(target_minutes, product_type)
    template = load_template(product_type, age_band)
    system = SYSTEM_CHILD if product_type == "child" else SYSTEM_ADULT

    parts: list[str] = []
    tries = 0
    while char_count("".join(parts)) < floor and tries < 4:
        tries += 1
        need = max(600, target - char_count("".join(parts)))
        user = make_user_prompt(
            book_title, target_minutes, product_type, age_band, template,
            need_chars=need,
            is_continuation=bool(parts),
            prev_tail=parts[-1] if parts else "")
        piece = call_deepseek(cfg, [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        # 去掉可能的"第X批"等行首噪音
        cleaned = re.sub(r"^(第[一二三四五六七八九十0-9]+批[：: ]*|\(续?上?一?批?\)[：:]?\s*)", "", piece.strip())
        if char_count(cleaned) < 120 and not parts:
            # 空/废话响应：视为失败，再试一次
            if tries >= 3:
                raise RuntimeError("DeepSeek 连续返回空内容，写稿失败")
            continue
        parts.append(cleaned)
        log(f"第 {tries} 批完成（{char_count(cleaned)} 字，累计 {char_count(''.join(parts))} 字）")

    text = "\n\n".join(parts)
    if char_count(text) < floor:
        raise RuntimeError(
            f"多次补批后字数仍不足：{char_count(text)} < 下限 {floor}，写稿失败")
    return text


def generate_mock(book_title: str, target_minutes: float,
                  product_type: str) -> str:
    """占位稿（链路测试用，不烧 LLM）：内容为公版常识性段落，段落各异。"""
    floor, target = plan_targets(target_minutes, product_type)
    scenes = [
        "这本书讲述了一位主人公踏上旅程、在途中遇见形形色色的人和事的故事。",
        "开篇，主人公的处境并不如意，生活的压力让他不得不做出一个重要的决定。",
        "在路上，他遇到了一位智者。智者没有直接给出答案，而是讲了一个意味深长的故事。",
        "旅途中的一次意外，让主人公开始重新审视自己过去的选择与坚持。",
        "他逐渐明白，真正重要的不是抵达终点，而是途中学会的勇敢与温柔。",
        "故事的后半段，主人公鼓起勇气面对了曾经逃避的真相，也原谅了不够完美的自己。",
        "结尾处，主人公把这段经历讲给后来的人听，就像这本书此刻讲给你听一样。",
        "如果这本书的某句话曾打动过你，不妨把它记在心里，在需要的时候拿出来读一读。",
    ]
    # 目标字数按质量门下限拼凑（每段展开为 2-3 个变体句，段落互不相同）
    texts = []
    idx = 0
    while char_count("\n".join(texts)) < floor + 600 and idx < 120:
        base = scenes[idx % len(scenes)]
        variant = f"这是第 {idx+1} 段。{base} 具体到情节里，主人公的每一次选择都藏着作者的深意。"
        if idx % 3 == 0:
            variant += "【情绪：温暖】读到这里不妨放慢脚步想一想，如果是你会怎么做。"
        elif idx % 3 == 1:
            variant += "【停顿0.5】故事在这里留下了一个小小的悬念。"
        else:
            variant += "这段经历后来成为主人公生命里最珍贵的一课。"
        texts.append(f"【章节{idx+1}：旅途见闻】{variant}")
        idx += 1
    log(f"mock 稿已生成 {idx} 段，{char_count(chr(10).join(texts))} 字（测试占位，非真实内容）")
    return "\n\n".join(texts)


def main():
    ap = argparse.ArgumentParser(description="bookmadebook 写稿器（Web 自助点书 daemon 用）")
    ap.add_argument("--book-title", required=True, help="书名（儿童线=白名单公版书）")
    ap.add_argument("--target-minutes", type=float, default=10.0)
    ap.add_argument("--voice", default="auto",
                    help="音色短名（husky_tender/hist_deep_male/design_kid，仅影响风格提示）")
    ap.add_argument("--product-type", choices=["adult", "child"], default="adult")
    ap.add_argument("--age-band", choices=["3-6", "7-12"], default=None,
                    help="儿童线年龄档（决定儿童模板）")
    ap.add_argument("--out", required=True, help="输出 txt 路径")
    ap.add_argument("--mock", action="store_true",
                    help="生成占位稿（不调 DeepSeek，链路测试用）")
    ap.add_argument("--model", default=None, help="覆盖 DeepSeek 模型名")
    args = ap.parse_args()

    setup_utf8()
    if args.product_type == "child" and not args.age_band:
        ap.error("儿童线必须提供 --age-band（3-6 / 7-12）")

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        if args.mock:
            text = generate_mock(args.book_title, args.target_minutes,
                                 args.product_type)
        else:
            cfg = find_deepseek_config()
            if args.model:
                cfg["model"] = args.model
            log(f"DeepSeek: model={cfg['model']} "
                f"base={cfg['base_url']} key={'已配置' if cfg['api_key'] else '缺失'}")
            if not cfg["api_key"]:
                sys.exit(2)
            text = generate_real(cfg, args.book_title, args.target_minutes,
                                 args.product_type, args.age_band)
    except RuntimeError as exc:
        print(f"✍️  写稿失败: {exc}", file=sys.stderr)
        sys.exit(2)

    out.write_text(text + "\n", encoding="utf-8")
    n = char_count(text)
    est = n / ENGINE_SPEED
    print(f"✅ 讲书稿已写入: {out}")
    print(f"   字数 {n}，预估 {est:.1f} 分钟（目标 {args.target_minutes:g} 分钟）")


if __name__ == "__main__":
    main()
