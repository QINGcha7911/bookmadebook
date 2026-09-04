/**
 * bookmadebook · 阿里云函数计算 FC 3.0 入口（Node.js 20 HTTP 触发器）
 *
 * 平台适配层：FC event（结构化，非 Node req/res）→ 标准 Request →
 * 复用 worker.js 导出的 route（业务路由零改动）→ FC 响应对象。
 * 同时同源托管 public/ 静态页（非 /api/ 路径读 public/ 文件返回），
 * 前端 API_BASE='' 直接可用，无需跨域。
 *
 * 部署（Serverless Devs，见同目录 s.yaml）：
 *   handler: index.handler（ESM：.mjs 入口 + 具名导出 handler）
 *   codeUri: ./fc（含 package.json? 见 迁移方案.md：若运行时不识别 .mjs，
 *            加 {"type":"module"} 并把本文件改名 index.js，handler 不变）
 *
 * FC 3.0 HTTP event 关键字段（详见 迁移方案.md 坑清单）：
 *   event.requestContext.http.{method,path}   —— method + 已解码路径
 *   event.rawPath                              —— URL 编码原始路径（备用）
 *   event.queryParameters / event.headers / event.body / event.isBase64Encoded
 *
 * ⚠️ 默认域名 fcapp.run 强制 Content-Disposition: attachment（浏览器直接下载不渲染），
 *    生产必须绑自定义域名（见 迁移方案.md；建议 cn-hongkong 免备案）。
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { route } from '../worker/src/worker.js';
import { createOtsStoreFromEnv } from './store-ots.mjs';

// normalize 会保留结尾分隔符，去掉它以便 startsWith 前缀判界（防目录穿越）
const PUBLIC_DIR = path.normalize(fileURLToPath(new URL('../public/', import.meta.url))).replace(/[\\/]+$/, '');

/** 静态资源 Content-Type 表（当前 public/ 只有 html/js/css；扩展资源时补表） */
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.mp3': 'audio/mpeg',
  '.woff2': 'font/woff2',
};

/** FC 实例缓存 OTS client（实例复用，避免每请求重建）；只缓存创建成功的实例 */
let otsStoreCache = null;

/** 组装 env：平台配置 + 存储注入。
 *  - 未配 TABLESTORE_ENDPOINT → 视为本地开发/纯 node 测试，回退 worker 内存 store；
 *  - 配了 endpoint 却建不出 store（缺 AK 等）→ 抛错 fail-fast，避免订单静默写进易失内存。 */
function buildEnv() {
  if (!otsStoreCache) {
    const s = createOtsStoreFromEnv(process.env);
    if (s) otsStoreCache = s;
  }
  const env = {
    MOCK_PAY: process.env.MOCK_PAY || '0',
    DAEMON_TOKEN: process.env.DAEMON_TOKEN || '',
    CORS_ORIGIN: process.env.CORS_ORIGIN || '',
    TURNSTILE_SECRET: process.env.TURNSTILE_SECRET || '',
  };
  if (process.env.TABLESTORE_ENDPOINT && !otsStoreCache) {
    throw new Error('TABLESTORE_ENDPOINT 已配置但 store 创建失败：请检查 TABLESTORE_INSTANCE / TABLESTORE_AK_ID / TABLESTORE_AK_SECRET');
  }
  if (otsStoreCache) env.store = otsStoreCache; // 平台注入优先于 D1/内存
  return env;
}

/** FC event → 标准 Request（FC3 结构化 event，非 Node req/res） */
export function toRequest(event) {
  const http = (event.requestContext && event.requestContext.http) || {};
  const method = http.method || 'GET';
  // requestContext.http.path 已解码；event.rawPath 是原始编码路径，作后备
  let urlPath = http.path;
  if (!urlPath && event.rawPath) urlPath = decodeURIComponent(event.rawPath);
  if (!urlPath) urlPath = '/';

  const qp = event.queryParameters || {};
  const qs = Object.entries(qp)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&');

  const headers = {};
  for (const [k, v] of Object.entries(event.headers || {})) {
    headers[k.toLowerCase()] = String(v);
  }
  const host = headers.host || (http.domainName || 'fc.example.com');

  const hasBody = method !== 'GET' && method !== 'HEAD' &&
    event.body !== undefined && event.body !== null && event.body !== '';
  let body;
  if (hasBody) {
    body = event.isBase64Encoded ? Buffer.from(event.body, 'base64') : String(event.body);
  }

  return new Request(`http://${host}${urlPath}${qs ? '?' + qs : ''}`, {
    method, headers, body,
  });
}

/** 静态文件分支（仅非 /api/ 路径）；返回 FC 响应对象或 null（继续走 API 路由） */
export async function serveStatic(urlPath) {
  let rel = decodeURIComponent(urlPath);
  if (rel === '/' || rel === '') rel = '/index.html';
  const file = path.normalize(path.join(PUBLIC_DIR, rel));
  // 防目录穿越：必须落在 PUBLIC_DIR 内
  if (file !== PUBLIC_DIR && !file.startsWith(PUBLIC_DIR + path.sep)) return null;
  let buf;
  try {
    buf = await readFile(file);
  } catch {
    return null; // 不存在 → 交给 API 404（保持与 CF Pages 兜底一致的响应）
  }
  const ext = path.extname(file).toLowerCase();
  const type = MIME[ext] || 'application/octet-stream';
  const isText = type.startsWith('text/') || type.includes('json') || type.includes('javascript') ||
    type.includes('svg') || type.includes('xml') || type.includes('x-www-form-urlencoded');
  return {
    statusCode: 200,
    headers: { 'content-type': type, 'cache-control': 'no-cache' },
    body: isText ? buf.toString('utf8') : buf.toString('base64'),
    isBase64Encoded: !isText,
  };
}

/** 标准 Response → FC 响应对象 */
export async function toFcResponse(res) {
  const headers = {};
  res.headers.forEach((v, k) => { headers[k] = v; });
  const buf = Buffer.from(await res.arrayBuffer());
  const ct = (headers['content-type'] || '').toLowerCase();
  const isText = !ct || ct.startsWith('text/') || ct.includes('json') ||
    ct.includes('javascript') || ct.includes('svg') || ct.includes('xml') ||
    ct.includes('x-www-form-urlencoded');
  return {
    statusCode: res.status,
    headers,
    body: isText ? buf.toString('utf8') : buf.toString('base64'),
    isBase64Encoded: !isText,
  };
}

/** FC 3.0 入口（s.yaml handler: index.handler） */
export async function handler(event, context) {
  const req = toRequest(event);
  const url = new URL(req.url);

  // 非 API 路径 → 优先同源静态页（H5 由本函数直接托管）
  if (!url.pathname.startsWith('/api/')) {
    const staticRes = await serveStatic(url.pathname);
    if (staticRes) return staticRes;
  }

  const res = await route(req, buildEnv());
  return toFcResponse(res);
}
