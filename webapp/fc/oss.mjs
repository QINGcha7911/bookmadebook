/**
 * bookmadebook · OSS 签名下载模块（FC 侧，Node 20 零第三方依赖）
 *
 * 交付链路：daemon 直传 mp3（key=orders/{order_id}.mp3，见 daemon/oss_upload.py）
 * → PATCH done 时把 oss_key 存进订单行 → 用户查询订单时本模块用 OSS V1
 * 预签名算法现场生成临时下载 URL（默认 24h 过期，防扩散盗链）。
 *
 * 为什么选「FC 现场签名」而不是「daemon 存死链接」：
 *   - OSS 临时签名 URL 会过期（24h），daemon 存 URL 无法续期；
 *   - 上传后只存 oss_key（不可变事实），查询时按当前时间重新签名 → URL 永远新鲜；
 *   - V1 预签名是纯本地 HMAC-SHA1 计算（node:crypto），不产生 OSS API 调用，
 *     因此 FC 侧甚至不需要 OSS API 权限即可签发（仍建议给最小只读策略）。
 *
 * 环境变量（FC 控制台 / s.yaml 注入，密钥勿硬编码）：
 *   OSS_BUCKET / OSS_REGION / OSS_AK_ID / OSS_AK_SECRET
 * 签名 URL 形如：
 *   https://bookmadebook-audio.oss-cn-hongkong.aliyuncs.com/orders/BM-XXX.mp3
 *     ?OSSAccessKeyId=...&Expires=...&Signature=...
 */
import { createHmac } from 'node:crypto';

export const OSS_KEY_PREFIX = 'orders/';

/** 对象 key 规范化：orders/{order_id}.mp3（与 daemon 上传约定一致） */
export function ossKeyOf(orderId) {
  return `${OSS_KEY_PREFIX}${String(orderId)}.mp3`;
}

/** OSS V1 预签名 GET URL（确定性可测：expiresInSec/now 可注入） */
export function signUrl({ bucket, region, accessKeyId, secretAccessKey, key,
                          expiresInSec = 24 * 3600, now = Date.now() }) {
  const expires = Math.floor(now / 1000) + expiresInSec;
  // OSS V1 签名串：GET\n\n\n{expires}\n/{bucket}/{key}（无 x-oss-* 头、无 sub-resource）
  const stringToSign = `GET\n\n\n${expires}\n/${bucket}/${key}`;
  const signature = createHmac('sha1', String(secretAccessKey))
    .update(stringToSign, 'utf8')
    .digest('base64');
  const query = new URLSearchParams({
    OSSAccessKeyId: String(accessKeyId),
    Expires: String(expires),
    Signature: signature,
  });
  return `https://${bucket}.${region}.aliyuncs.com/${key}?${query.toString()}`;
}

/** 从环境变量构建「订单 → 签名 URL」注入函数；配置不全返回 null */
export function buildSignDownloadUrl(env = process.env) {
  const bucket = env.OSS_BUCKET;
  const region = env.OSS_REGION;
  const accessKeyId = env.OSS_AK_ID || env.ALIBABA_CLOUD_ACCESS_KEY_ID;
  const secretAccessKey = env.OSS_AK_SECRET || env.ALIBABA_CLOUD_ACCESS_KEY_SECRET;
  if (!bucket || !region || !accessKeyId || !secretAccessKey) return null;
  return async (row) => {
    // 只对显式带 oss_key 的 done 订单签发（daemon 上传成功才写该字段）；
    // 历史订单/未上传 → 返回 null（download_url=null，前端提示稍后/联系客服）。
    const key = row && row.oss_key;
    if (!key) return null;
    return signUrl({ bucket, region, accessKeyId, secretAccessKey, key });
  };
}
