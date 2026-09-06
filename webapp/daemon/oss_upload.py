#!/usr/bin/env python3
"""bookmadebook · daemon → OSS 直传（mp3 交付，任务 4）

为什么 daemon 直传而不经 FC 中转：
  mp3 约 9-11MB，超过 FC HTTP 触发器请求体限制；本地直传 OSS 最简可靠。

对象 key：orders/{order_id}.mp3（与 fc/oss.mjs 的签名下载约定一致）。
订单 done 时 daemon 把 oss_key PATCH 给后端；用户查询订单时 FC 现场签发
24h 临时签名 URL（见 fc/oss.mjs），本模块只负责上传、不碰下载。

环境变量（本机 .env 或 shell export；密钥禁硬编码）：
  OSS_ENDPOINT   如 https://oss-cn-hongkong.aliyuncs.com（008 按实际 region 给）
  OSS_BUCKET     建议 bookmadebook-audio
  OSS_AK_ID / OSS_AK_SECRET   （兼容 ALIBABA_CLOUD_ACCESS_KEY_ID / _SECRET）
  BOOKMADE_OSS_MOCK=1   本地联调：不连真实 OSS，模拟上传成功
  OSS_RETRIES          上传重试次数（默认 3）

依赖：pip install oss2（lazy import：未配置 OSS 时不强制安装）
失败策略：指数退避重试（2s/4s/8s），仍失败抛 RuntimeError →
          daemon 标记订单 failed（不静默丢单，用户可见失败）。
"""
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("bookmadebook-daemon")

RETRY_DEFAULT = 3
BACKOFF_BASE_S = 2.0

# 配置键 → 环境变量候选（多候选按序取第一个非空）
_OSS_ENV = {
    "endpoint": ("OSS_ENDPOINT",),
    "bucket": ("OSS_BUCKET",),
    "access_key_id": ("OSS_AK_ID", "ALIBABA_CLOUD_ACCESS_KEY_ID"),
    "access_key_secret": ("OSS_AK_SECRET", "ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
}


def load_dotenv(dotenv_path=None) -> bool:
    """极简 .env 加载（KEY=VALUE / # 注释；真实环境变量优先，幂等）。"""
    path = Path(dotenv_path) if dotenv_path else Path(__file__).resolve().parent / ".env"
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:   # 已存在的环境变量优先（shell export > .env）
            os.environ[k] = v
    return True


# 模块导入即加载 .env（本机免 export；仓库不提交 .env，见 .gitignore）
load_dotenv()


def config_from_env(env=None) -> dict:
    env = env or os.environ
    cfg = {key: next((env[n] for n in names if env.get(n)), None)
           for key, names in _OSS_ENV.items()}
    cfg["mock"] = str(env.get("BOOKMADE_OSS_MOCK", "0")) == "1"
    cfg["retries"] = int(env.get("OSS_RETRIES", RETRY_DEFAULT))
    return cfg


def is_configured(cfg: dict) -> bool:
    """mock 模式无需真实凭据；真实模式需 endpoint/bucket/AK 全齐。"""
    if cfg["mock"]:
        return True
    return bool(cfg["endpoint"] and cfg["bucket"]
                and cfg["access_key_id"] and cfg["access_key_secret"])


def object_key(order_id: str) -> str:
    """规范 key：orders/{order_id}.mp3（与 fc/oss.mjs ossKeyOf 一致）"""
    return f"orders/{order_id}.mp3"


def get_uploader(env=None):
    """返回 upload(order_id, mp3_path) -> oss_key；OSS 未配置返回 None（daemon 跳过上传）。

    None 语义：本地开发/联调未配 OSS → 订单仍 PATCH done（本地产物可查），
    但无真实下载链接；生产 008 必须配置 OSS（配齐后自动启用，无需改代码）。
    """
    cfg = config_from_env(env)
    if not is_configured(cfg):
        log.info("OSS 未配置（需 OSS_ENDPOINT/OSS_BUCKET/OSS_AK_ID/OSS_AK_SECRET 或 BOOKMADE_OSS_MOCK=1），"
                 "跳过上传：订单仅标记 done + 本地路径")
        return None

    def upload(order_id: str, mp3_path) -> str:
        key = object_key(order_id)
        if cfg["mock"]:
            p = Path(mp3_path)
            if not p.exists() or p.stat().st_size <= 0:
                raise FileNotFoundError(f"mock 上传：产物不存在或为空 {mp3_path}")
            log.info("☁️ [mock] 模拟上传 %s（%.1f MB）", key, p.stat().st_size / 1024 / 1024)
            return key
        return _upload_real(cfg, key, mp3_path)

    return upload


def _upload_real(cfg: dict, key: str, mp3_path) -> str:
    """真实上传（oss2 lazy import + 指数退避重试）；仍失败抛 RuntimeError。"""
    try:
        import oss2  # noqa: PLC0415 —— lazy：未配 OSS 的环境无需安装
    except ImportError as exc:
        raise RuntimeError("未安装 oss2：请 pip install oss2（OSS 交付必需）") from exc

    auth = oss2.Auth(cfg["access_key_id"], cfg["access_key_secret"])
    bucket = oss2.Bucket(auth, cfg["endpoint"], cfg["bucket"])
    last_exc = None
    for attempt in range(1, cfg["retries"] + 1):
        try:
            bucket.put_object_from_file(key, mp3_path)
            return key
        except Exception as exc:  # noqa: BLE001 —— 网络/签名/限流都重试
            last_exc = exc
            if attempt < cfg["retries"]:
                wait = BACKOFF_BASE_S * (2 ** (attempt - 1))
                log.warning("OSS 上传第 %d/%d 次失败：%s；%.0fs 后重试",
                            attempt, cfg["retries"], exc, wait)
                time.sleep(wait)
    raise RuntimeError(f"OSS 上传失败（已重试 {cfg['retries']} 次）：{last_exc}") from last_exc


# ── CLI 自测：python3 daemon/oss_upload.py <order_id> <mp3_path> ───────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 3:
        print("用法: python3 daemon/oss_upload.py <order_id> <mp3_path>")
        sys.exit(1)
    uploader = get_uploader()
    if uploader is None:
        print("OSS 未配置，退出（mock 联调请设 BOOKMADE_OSS_MOCK=1）")
        sys.exit(2)
    print("上传成功:", uploader(sys.argv[1], sys.argv[2]))
