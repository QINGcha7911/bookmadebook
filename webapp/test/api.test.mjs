/* ============================================================
 * bookmadebook 自助点书 · API 自测（node:test，无需真实部署）
 * 运行：npm test   （= node test/api.test.mjs）
 * 说明：worker.js 无 D1 绑定（未传 env.DB）时自动使用内存存储，
 *       因此本测试可脱离 wrangler 直接 import worker 跑通接口逻辑。
 * ============================================================ */
import { test, before, describe } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../worker/src/worker.js';

// 测试环境：MOCK_PAY=1（允许模拟支付回调）；不设 TURNSTILE_SECRET（跳过人机验证）
const env = { MOCK_PAY: '1' };

const BASE = 'http://127.0.0.1:8787';
function call(path, { method = 'GET', body } = {}) {
  const init = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) init.body = JSON.stringify(body);
  return worker.fetch(new Request(BASE + path, init), env);
}

describe('bookmadebook API 自测', () => {
  let adultId = null;
  let childId = null;
  const email = 'test-user@example.com';

  test('GET /api/books 返回 10 本白名单书单', async () => {
    const res = await call('/api/books');
    assert.equal(res.status, 200);
    const data = await res.json();
    assert.equal(data.ok, true);
    assert.ok(Array.isArray(data.list));
    assert.equal(data.list.length, 10);
    // 每本都有 id/title/author/age，且封面字段完整
    for (const b of data.list) {
      assert.ok(b.id && b.title && b.author && Array.isArray(b.age) && b.note);
    }
  });

  test('POST /api/order 成人线：合法下单 → 201 pending', async () => {
    const res = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'adult', book_title: '活着', duration_min: 20, voice: 'husky_tender', email },
    });
    assert.equal(res.status, 201);
    const data = await res.json();
    assert.equal(data.ok, true);
    adultId = data.order.order_id;
    assert.match(adultId, /^BM-/);
    assert.equal(data.order.status, 'pending');
    assert.equal(data.order.book_title, '活着');
    assert.equal(data.order.duration_min, 20);
    assert.equal(data.order.voice, 'husky_tender');
    assert.equal(data.order.amount_yuan, '9.90');
    assert.equal(data.order.eta_min, 25); // 20 + 缓冲 5
    assert.equal(data.order.next_step, 'pay');
  });

  test('POST /api/order 成人线：非法时长 → 400', async () => {
    const res = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'adult', book_title: '活着', duration_min: 15, voice: 'husky_tender', email },
    });
    assert.equal(res.status, 400);
    const data = await res.json();
    assert.equal(data.ok, false);
    assert.ok(data.error.includes('10/20/30'));
  });

  test('POST /api/order 儿童线：合法点播 → 201（默认儿童音/10分钟）', async () => {
    const res = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'child', book_id: 'xz', age_band: '3-6', email, parent_declared: true },
    });
    assert.equal(res.status, 201);
    const data = await res.json();
    assert.equal(data.ok, true);
    childId = data.order.order_id;
    assert.equal(data.order.product_type, 'child');
    assert.equal(data.order.book_title, '小王子');
    assert.equal(data.order.voice, 'design_kid');
    assert.equal(data.order.age_band, '3-6');
    assert.equal(data.order.duration_min, 10);
  });

  test('POST /api/order 儿童线：未勾选家长声明 → 400', async () => {
    const res = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'child', book_id: 'xz', age_band: '3-6', email: 'other@example.com' },
    });
    assert.equal(res.status, 400);
    const data = await res.json();
    assert.ok(data.error.includes('家长声明') || data.error.includes('未成年'));
  });

  test('POST /api/order 儿童线：白名单外书目 → 400', async () => {
    const res = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'child', book_id: 'not-exist', age_band: '3-6', email: 'other@example.com', parent_declared: true },
    });
    assert.equal(res.status, 400);
    assert.match((await res.json()).error, /白名单/);
  });

  test('每邮箱每日限 3 单：第 4 单 → 429', async () => {
    // 上面同一邮箱已下 2 单（成人+儿童），再下 2 单：第 3 单成功、第 4 单被限
    const third = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'adult', book_title: '人类简史', duration_min: 10, voice: 'hist_deep_male', email },
    });
    assert.equal(third.status, 201);
    const fourth = await call('/api/order', {
      method: 'POST',
      body: { product_type: 'adult', book_title: '沉思录', duration_min: 10, voice: 'hist_deep_male', email },
    });
    assert.equal(fourth.status, 429);
    assert.match((await fourth.json()).error, /上限/);
  });

  test('POST /api/pay-callback 模拟支付：pending → paid，且幂等', async () => {
    const res = await call('/api/pay-callback', {
      method: 'POST',
      body: { order_id: adultId, voucher: 'mock-voucher-001' },
    });
    assert.equal(res.status, 200);
    const data = await res.json();
    assert.equal(data.ok, true);
    assert.equal(data.order.status, 'paid');
    // provider/voucher 属内部字段，publicOrder 故意隐藏（此处只校验对外视图）
    assert.equal(data.order.download_url, null);

    // 幂等：重复回调仍成功且不报错
    const again = await call('/api/pay-callback', {
      method: 'POST',
      body: { order_id: adultId, voucher: 'mock-voucher-001' },
    });
    assert.equal(again.status, 200);
    assert.equal((await again.json()).order.status, 'paid');
  });

  test('POST /api/pay-callback 订单不存在 → 404', async () => {
    const res = await call('/api/pay-callback', {
      method: 'POST',
      body: { order_id: 'BM-NOPE000' },
    });
    assert.equal(res.status, 404);
  });

  test('GET /api/order/:id 查询状态正确', async () => {
    const res = await call('/api/order/' + childId);
    assert.equal(res.status, 200);
    const data = await res.json();
    assert.equal(data.order.order_id, childId);
    assert.equal(data.order.status, 'pending');
    assert.equal(data.order.amount_yuan, '9.90');
  });

  test('GET /api/order/:id 不存在 → 404', async () => {
    const res = await call('/api/order/BM-NOPE000');
    assert.equal(res.status, 404);
  });
});
