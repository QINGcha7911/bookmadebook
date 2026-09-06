/* ============================================================
 * FC 3.0 适配层测试（阿里云迁移）
 * 验证：FC event → 标准 Request → worker route → FC 响应对象 的
 * 平台转换正确性（业务逻辑已由 api.test.mjs 覆盖，这里只测适配层）。
 * 不真实部署、不连 Tablestore：缺 OTS 环境变量时 route 自动回退内存 store。
 * 运行：npm test（已并入 package.json test 脚本）
 * ============================================================ */
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import { handler, toRequest, toFcResponse, serveStatic } from '../fc/index.mjs';

// 模拟 FC 3.0 HTTP 触发器 event（结构见 fc/index.mjs 头注释）
function makeEvent(method, path, { query, headers = {}, body, isBase64Encoded = false } = {}) {
  return {
    requestContext: { http: { method, path } },
    rawPath: path,
    headers: Object.assign({ Host: 'book.test.fcapp.run' }, headers),
    ...(query ? { queryParameters: query } : {}),
    ...(body !== undefined ? { body, isBase64Encoded } : {}),
  };
}

describe('FC 3.0 适配层', () => {
  before(() => {
    // 测试环境变量：允许模拟支付 + 无 Turnstile（与 api.test.mjs 一致）
    process.env.MOCK_PAY = '1';
    process.env.DAEMON_TOKEN = 'fc-test-token';
    delete process.env.TABLESTORE_ENDPOINT; // 确保走内存 store，不连真库
    delete process.env.TABLESTORE_INSTANCE;
    // OSS 签名（任务 4）：配齐 → buildEnv 注入 signDownloadUrl，done 订单返回真实链接
    process.env.OSS_BUCKET = 'bookmadebook-audio';
    process.env.OSS_REGION = 'cn-hongkong';
    process.env.OSS_AK_ID = 'FCTESTAK';
    process.env.OSS_AK_SECRET = 'FCTESTSECRET';
  });

  test('toRequest：GET + query + headers 转换正确', () => {
    const req = toRequest(makeEvent('GET', '/api/books', { query: { a: '1', b: '中文' } }));
    assert.equal(req.method, 'GET');
    const url = new URL(req.url);
    assert.equal(url.pathname, '/api/books');
    assert.equal(url.searchParams.get('a'), '1');
    assert.equal(url.searchParams.get('b'), '中文');
    assert.equal(req.headers.get('host'), 'book.test.fcapp.run');
  });

  test('toRequest：POST 文本 body（isBase64Encoded=false）原样透传', async () => {
    const payload = { email: 'fc@example.com', product_type: 'adult', book_title: '活着', duration_min: 10, voice: 'husky_tender' };
    const req = toRequest(makeEvent('POST', '/api/order', { body: JSON.stringify(payload) }));
    assert.equal(req.method, 'POST');
    assert.deepEqual(await req.json(), payload);
  });

  test('toRequest：POST base64 body 正确解码', async () => {
    const payload = { email: 'fc2@example.com', product_type: 'child', book_id: 'xz', age_band: '7-12', parent_declared: true };
    const body = Buffer.from(JSON.stringify(payload)).toString('base64');
    const req = toRequest(makeEvent('POST', '/api/order', { body, isBase64Encoded: true }));
    assert.deepEqual(await req.json(), payload);
  });

  test('serveStatic：/ 返回 index.html，目录穿越被拦截', async () => {
    const home = await serveStatic('/');
    assert.equal(home.statusCode, 200);
    assert.match(home.headers['content-type'], /text\/html/);
    assert.match(home.body, /<!doctype html/i);

    const css = await serveStatic('/style.css');
    assert.equal(css.statusCode, 200);
    assert.match(css.headers['content-type'], /text\/css/);

    assert.equal(await serveStatic('/../schema.sql'), null); // 防穿越
    assert.equal(await serveStatic('/not-exist.js'), null);
  });

  test('handler：GET /api/books → FC 响应对象（200 + CORS + JSON）', async () => {
    const res = await handler(makeEvent('GET', '/api/books'), {});
    assert.equal(res.statusCode, 200);
    assert.equal(res.isBase64Encoded, false);
    assert.equal(res.headers['access-control-allow-origin'], '*');
    const data = JSON.parse(res.body);
    assert.equal(data.ok, true);
    assert.equal(data.list.length, 10);
  });

  test('handler：FC3 nodejs 真实形态——event 为 Buffer 时先 JSON.parse 再路由', async () => {
    // 2026-09-06 实测：FC 3.0 nodejs20 HTTP 触发器以 Buffer 传入 event（本地直调传对象不暴露）
    const raw = Buffer.from(JSON.stringify(makeEvent('GET', '/api/books')));
    const res = await handler(raw, {});
    assert.equal(res.statusCode, 200);
    assert.equal(JSON.parse(res.body).ok, true);
  });

  test('handler：event 为字符串（JSON）时兼容解析', async () => {
    const raw = JSON.stringify(makeEvent('GET', '/api/books'));
    const res = await handler(raw, {});
    assert.equal(res.statusCode, 200);
    assert.equal(JSON.parse(res.body).ok, true);
  });

  test('handler：Buffer event + POST 下单全链路（真实平台形态）', async () => {
    const payload = { email: 'fc-buf@example.com', product_type: 'adult', book_title: '活着', duration_min: 10, voice: 'husky_tender' };
    const raw = Buffer.from(JSON.stringify(makeEvent('POST', '/api/order', { body: JSON.stringify(payload) })));
    const res = await handler(raw, {});
    assert.equal(res.statusCode, 201);
    const data = JSON.parse(res.body);
    assert.equal(data.ok, true);
    assert.match(data.order.order_id, /^BM-/);
  });

  test('handler：POST /api/order 成人线 → 201（适配层 + 业务路由打通）', async () => {
    const payload = { email: 'fc-adult@example.com', product_type: 'adult', book_title: '沉思录', duration_min: 10, voice: 'hist_deep_male' };
    const res = await handler(makeEvent('POST', '/api/order', { body: JSON.stringify(payload) }), {});
    assert.equal(res.statusCode, 201);
    const data = JSON.parse(res.body);
    assert.equal(data.ok, true);
    assert.match(data.order.order_id, /^BM-/);
    assert.equal(data.order.status, 'pending');
  });

  test('handler：GET /（静态 HTML）与 /api 404 分支正确', async () => {
    const page = await handler(makeEvent('GET', '/'), {});
    assert.equal(page.statusCode, 200);
    assert.match(page.headers['content-type'], /text\/html/);

    const nf = await handler(makeEvent('GET', '/api/not-exist'), {});
    assert.equal(nf.statusCode, 404);
    assert.equal(JSON.parse(nf.body).ok, false);
  });

  test('handler：admin 接口无 token → 401（FC 环境变量 DAEMON_TOKEN 注入）', async () => {
    const res = await handler(makeEvent('GET', '/api/admin/pending-orders'), {});
    assert.equal(res.statusCode, 401);
  });

  test('handler：done 订单带 oss_key → GET /api/order/:id 返回 OSS 签名下载 URL', async () => {
    // 下单 → 模拟支付 → daemon 认领 → daemon 上传后 PATCH done（带 oss_key）
    const order = JSON.parse((await handler(makeEvent('POST', '/api/order', {
      body: JSON.stringify({ email: 'oss@example.com', product_type: 'adult', book_title: '活着', duration_min: 10, voice: 'husky_tender' }),
    }), {})).body).order;
    const id = order.order_id;
    const pay = await handler(makeEvent('POST', '/api/pay-callback', {
      body: JSON.stringify({ order_id: id, voucher: 'v-oss' }),
    }), {});
    assert.equal(pay.statusCode, 200);
    const auth = (method, path, body) => makeEvent(method, path, {
      headers: { 'x-daemon-token': 'fc-test-token' }, body: JSON.stringify(body),
    });
    assert.equal((await handler(auth('PATCH', '/api/admin/order/' + id, { status: 'generating' }), {})).statusCode, 200);
    const done = await handler(auth('PATCH', '/api/admin/order/' + id, { status: 'done', oss_key: `orders/${id}.mp3` }), {});
    assert.equal(done.statusCode, 200);

    // 用户查询：download_url 是 24h OSS 签名 URL（不再是 /api/download/ 占位）
    const view = JSON.parse((await handler(makeEvent('GET', '/api/order/' + id), {})).body).order;
    assert.equal(view.status, 'done');
    assert.match(view.download_url, new RegExp(`^https://bookmadebook-audio\.cn-hongkong\.aliyuncs\.com/orders/${id}\.mp3\?`));
    const u = new URL(view.download_url);
    assert.equal(u.searchParams.get('OSSAccessKeyId'), 'FCTESTAK');
    assert.ok(u.searchParams.get('Signature'));
    const expires = Number(u.searchParams.get('Expires'));
    assert.ok(expires > Math.floor(Date.now() / 1000));          // 未过期
    assert.ok(expires <= Math.floor(Date.now() / 1000) + 24 * 3600 + 5); // 24h 内
    assert.ok(!view.download_url.includes('/api/download/'));
  });

  test('handler：done 但无 oss_key（历史/未上传）→ download_url 为 null', async () => {
    const order = JSON.parse((await handler(makeEvent('POST', '/api/order', {
      body: JSON.stringify({ email: 'oss2@example.com', product_type: 'adult', book_title: '沉思录', duration_min: 10, voice: 'hist_deep_male' }),
    }), {})).body).order;
    const id = order.order_id;
    await handler(makeEvent('POST', '/api/pay-callback', { body: JSON.stringify({ order_id: id }) }), {});
    const auth = (method, path, body) => makeEvent(method, path, {
      headers: { 'x-daemon-token': 'fc-test-token' }, body: JSON.stringify(body),
    });
    await handler(auth('PATCH', '/api/admin/order/' + id, { status: 'generating' }), {});
    await handler(auth('PATCH', '/api/admin/order/' + id, { status: 'done' }), {}); // 无 oss_key
    const view = JSON.parse((await handler(makeEvent('GET', '/api/order/' + id), {})).body).order;
    assert.equal(view.status, 'done');
    assert.equal(view.download_url, null);
  });

  test('toFcResponse：二进制 body 走 base64（isBase64Encoded=true）', async () => {
    const bin = new Response(new Uint8Array([0x89, 0x50, 0x4e, 0x47]), {
      status: 200,
      headers: { 'content-type': 'image/png' },
    });
    const fc = await toFcResponse(bin);
    assert.equal(fc.statusCode, 200);
    assert.equal(fc.isBase64Encoded, true);
    assert.equal(Buffer.from(fc.body, 'base64')[0], 0x89);
  });
});
