#!/usr/bin/env python3
"""bookmadebook · 本地生成工人 daemon（任务 3）

轮询 Workers 接口里的已支付订单（status=paid），串行执行：
  A 段 写稿  scripts/write_script.py（DeepSeek 讲书稿，可选 --mock 占位稿）
  B 段 生成  scripts/harness.py --file 稿 --target-minutes N --voice V
       （内部含 质量门 → streaming_pipeline TTS → 输出验证，fail-closed）
  完成 → 直传 OSS → PATCH done（带 oss_key）；失败/超时 → PATCH failed。

约束（09-01 教训固化）：
  - 并发 = 1：写稿与生成全程串行，禁止并行（并行 TTS/渲染会资源竞争中断）
  - 产物落本地 webapp-output/<order_id>/；mp3 由本进程直传 OSS（orders/{id}.mp3，
    不经 FC 中转，见 daemon/oss_upload.py；上传失败重试后仍失败 → 订单 failed）
  - daemon 崩溃后重启：state.json 中滞留 generating 超过超时的订单自动补 failed

OSS 配置（可选，生产必需）：见 daemon/oss_upload.py 文件头（.env 或环境变量）。
本地联调无真实 OSS：设 BOOKMADE_OSS_MOCK=1 模拟上传；不配则跳过上传（仅 done+本地路径）。

用法:
    python daemon.py --once                 # 拉一次并处理完退出（测试用）
    python daemon.py                        # 30s 轮询常驻
    python daemon.py --once --mock-script   # 写稿用占位稿（链路测试，不烧 LLM）
    python daemon.py --base-url http://127.0.0.1:8787 --token dev-daemon-token-001

退出码: 0 = 正常（--once 全部处理完）；1 = 参数/配置错误
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 同目录模块：OSS 直传（含 .env 加载，见 oss_upload.py 文件头）
try:
    import oss_upload
except ImportError:  # 以模块方式被 import（测试等）时把 daemon/ 加入搜索路径
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import oss_upload

# ── 路径与配置 ──────────────────────────────────────────────────────────
DAEMON_DIR = Path(__file__).resolve().parent
REPO_ROOT = DAEMON_DIR.parents[1]          # webapp/daemon → 仓库根
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "webapp-output"
STATE_FILE = DAEMON_DIR / "state.json"
LOG_FILE = DAEMON_DIR / "daemon.log"

DEFAULT_BASE_URL = os.environ.get("BOOKMADE_BASE_URL", "http://127.0.0.1:8787")
DEFAULT_TOKEN = os.environ.get("DAEMON_TOKEN", "dev-daemon-token-001")
DEFAULT_INTERVAL = 30          # 轮询间隔（秒）
DEFAULT_TIMEOUT_MIN = 60       # 单订单超时（分钟）：写稿+TTS 合计

log = logging.getLogger("bookmadebook-daemon")


def setup_logging(verbose: bool) -> None:
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


def safe_name(name: str) -> str:
    """文件名安全化（Windows/WSL 通用）。"""
    name = re.sub(r'[<>:"/\\|?*]', "_", name or "").strip()
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "未命名"


# ── HTTP（urllib，无第三方依赖）───────────────────────────────────────
def http_json(base_url: str, method: str, path: str, token: str,
              body: dict | None = None, timeout: int = 60) -> tuple[int, dict]:
    url = base_url.rstrip("/") + path
    headers = {"Content-Type": "application/json", "x-daemon-token": token}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {"ok": False, "error": f"HTTP {exc.code}"}
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 Worker {base_url}: {exc.reason}") from exc


# ── 本地状态（state.json：订单 → 认领时间/产物/错误）────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("state.json 解析失败，重置为空状态")
    return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)   # 原子替换，防写一半


# ── 订单处理（串行，并发=1）────────────────────────────────────────────
def order_dir(order: dict, output_dir: Path) -> Path:
    d = output_dir / safe_name(order["order_id"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cmd(cmd: list, task_timeout_s: int) -> subprocess.CompletedProcess:
    """同步跑子进程（继承 stdout/stderr 便于实时观察），超时杀掉。"""
    log.info("$ %s", " ".join(str(c) for c in cmd))
    proc = subprocess.Popen(cmd)
    try:
        proc.wait(timeout=task_timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise TimeoutError(f"任务超时（>{task_timeout_s}s），已终止: {cmd[0]}")
    return proc


def process_order(order: dict, args, state: dict) -> None:
    order_id = order["order_id"]
    book_title = order.get("book_title") or "未命名"
    product_type = order.get("product_type") or "adult"
    duration = float(order.get("duration_min") or 10)
    voice = order.get("voice") or "auto"
    age_band = order.get("age_band")
    o = order_dir(order, Path(args.output_dir))
    book_file = safe_name(book_title)
    script_path = o / "script.txt"
    audio_path = o / f"{book_file}_{duration:g}min_{order_id}.mp3"
    task_timeout_s = int(args.task_timeout_s or args.timeout_min * 60)

    state[order_id] = {"status": "generating", "claimed_at": time.time(),
                       "book_title": book_title, "duration_min": duration}
    save_state(state)

    # ── A 段：写稿（写稿失败不烧 TTS 钱）──
    try:
        ws_cmd = [sys.executable, str(SCRIPTS_DIR / "write_script.py"),
                  "--book-title", book_title,
                  "--target-minutes", str(duration),
                  "--voice", voice,
                  "--product-type", product_type,
                  "--out", str(script_path)]
        if product_type == "child" and age_band:
            ws_cmd += ["--age-band", age_band]
        if args.mock_script:
            ws_cmd += ["--mock"]
        rc = run_cmd(ws_cmd, task_timeout_s).returncode
        if rc != 0 or not script_path.exists():
            raise RuntimeError(f"写稿失败（write_script exit {rc}）")
        log.info("✅ A 段写稿完成: %s", script_path)
    except Exception as exc:   # noqa: BLE001 —— 任一失败都走 failed，不让 daemon 崩
        mark_failed(order_id, state, f"写稿失败: {exc}", args)
        return

    # ── B 段：harness 生成（内部含质量门/输出验证，fail-closed）──
    try:
        h_cmd = [sys.executable, str(SCRIPTS_DIR / "harness.py"),
                 "--file", str(script_path),
                 "--target-minutes", str(duration),
                 "--voice", voice,
                 "--style", "ted",
                 "--output", str(audio_path)]
        rc = run_cmd(h_cmd, task_timeout_s).returncode
        if rc != 0 or not audio_path.exists():
            raise RuntimeError(f"生成失败（harness exit {rc}）")
        size_mb = audio_path.stat().st_size / 1024 / 1024
        log.info("✅ B 段生成完成: %s（%.1f MB）", audio_path, size_mb)
    except Exception as exc:   # noqa: BLE001
        mark_failed(order_id, state, f"生成失败: {exc}", args)
        return

    # ── 完成：直传 OSS → PATCH done（带 oss_key，后端查询时签发 24h 签名下载链接）──
    try:
        uploader = oss_upload.get_uploader()   # None = OSS 未配置（本地联调降级）
        patch_body = {"status": "done"}
        if uploader is not None:
            patch_body["oss_key"] = uploader(order_id, str(audio_path))
        code, resp = http_json(args.base_url, "PATCH", f"/api/admin/order/{order_id}",
                               args.token, patch_body)
        if code != 200:
            raise RuntimeError(f"HTTP {code}: {resp.get('error')}")
    except Exception as exc:   # noqa: BLE001 —— 上传/回执失败都不静默丢单
        mark_failed(order_id, state, f"OSS 上传/PATCH done 失败: {exc}", args)
        return
    state[order_id].update({"status": "done", "audio": str(audio_path),
                            "script": str(script_path), "done_at": time.time()})
    save_state(state)
    log.info("🎉 订单 %s 完成: %s → done（本地产物 %s%s）",
             order_id, book_title, audio_path,
             f"，OSS key={patch_body.get('oss_key')}" if patch_body.get("oss_key") else "，未配 OSS 跳过上传")


def mark_failed(order_id: str, state: dict, reason: str, args) -> None:
    log.error("❌ 订单 %s failed：%s", order_id, reason)
    try:
        code, resp = http_json(args.base_url, "PATCH",
                               f"/api/admin/order/{order_id}", args.token,
                               {"status": "failed"})
    except Exception:
        code, resp = 0, {}
    state[order_id].update({"status": "failed", "error": reason[:300],
                            "failed_at": time.time()})
    save_state(state)


# ── 超时清理：daemon 崩溃/中断后，滞留 generating 的订单补 failed ──────
def sweep_stale(args, state: dict) -> None:
    limit = time.time() - args.timeout_min * 60
    for order_id, rec in list(state.items()):
        if rec.get("status") != "generating":
            continue
        if rec.get("claimed_at", 0) < limit:
            log.warning("⏰ 订单 %s 认领超时（>%s 分钟），标记 failed", order_id, args.timeout_min)
            mark_failed(order_id, state, f"认领超时（>{args.timeout_min} 分钟无完成）", args)


# ── 主循环 ─────────────────────────────────────────────────────────────
def run_once(args) -> None:
    state = load_state()
    sweep_stale(args, state)

    code, resp = http_json(args.base_url, "GET", "/api/admin/pending-orders",
                           args.token, timeout=30)
    if code != 200:
        log.error("拉单失败 HTTP %s：%s", code, resp.get("error", resp))
        return
    orders = resp.get("list") or []
    if not orders:
        log.info("暂无待生成订单（status=paid）")
        return
    log.info("拉取到 %s 个待生成订单，开始串行处理", len(orders))

    for order in orders:
        # 认领：paid → generating（409=已被其他方认领/状态已变 → 跳过）
        code, resp = http_json(args.base_url, "PATCH",
                               f"/api/admin/order/{order['order_id']}",
                               args.token, {"status": "generating"})
        if code != 200:
            log.warning("订单 %s 认领失败 HTTP %s：%s（跳过）",
                        order["order_id"], code, resp.get("error"))
            continue
        log.info("🔨 开始处理订单 %s《%s》 %s分钟 voice=%s",
                 order["order_id"], order.get("book_title"),
                 order.get("duration_min"), order.get("voice"))
        process_order(order, args, state)


def main():
    global REPO_ROOT, SCRIPTS_DIR
    ap = argparse.ArgumentParser(description="bookmadebook 本地生成工人 daemon")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Worker API 地址")
    ap.add_argument("--token", default=DEFAULT_TOKEN, help="daemon 鉴权 token")
    ap.add_argument("--repo", default=str(REPO_ROOT), help="bookmadebook 仓库根")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="本地产物根目录")
    ap.add_argument("--once", action="store_true", help="只拉取处理一轮后退出")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="轮询间隔秒数")
    ap.add_argument("--timeout-min", type=int, default=DEFAULT_TIMEOUT_MIN,
                    help="单订单超时分钟（认领后无结果视为失败）")
    ap.add_argument("--task-timeout-s", type=int, default=None,
                    help="子进程硬超时秒数（默认 timeout-min×60）")
    ap.add_argument("--mock-script", action="store_true",
                    help="写稿用占位稿（不调 DeepSeek，链路测试用）")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)
    REPO_ROOT = Path(args.repo).resolve()
    SCRIPTS_DIR = REPO_ROOT / "scripts"
    log.info("daemon 启动 base=%s 仓库=%s 输出=%s", args.base_url, REPO_ROOT, args.output_dir)

    if args.once:
        run_once(args)
        log.info("--once 完成，退出")
        return

    # 常驻轮询
    while True:
        try:
            run_once(args)
        except Exception as exc:   # noqa: BLE001 —— 网络抖动等不让 daemon 退出
            log.error("轮询异常: %s", exc)
        log.info("休眠 %s 秒后继续轮询", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
