/* ============================================================
 * 前端真实 payload 回归测试（补 007 验收教训）
 * 背景：儿童线曾因前端 onSubmitChild 漏传 parent_declared，
 *       后端校验必拒 → 儿童线真实页面永远无法下单。
 *       该 bug 只能从前端链路暴露，API 直调测试覆盖不到。
 * 方案：app.js 的 payload 构建抽为纯函数并暴露（window/globalThis），
 *       本测试直接调用「前端同款构建器」，再把产物喂给后端接口，
 *       验证真实页面提交的 payload 能 201 落单。
 * 运行：npm test
 * ============================================================ */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

// 副作用导入 app.js：无 DOM 环境自动跳过 DOM 绑定，仅挂 globalThis.bookmadebook
import '../public/app.js';
import worker from '../worker/src/worker.js';

const env = { MOCK_PAY: '1' };
const BASE = 'http://127.0.0.1:8787';
const builders = globalThis.bookmadebook;

function postOrder(payload) {
  return worker.fetch(new Request(BASE + '/api/order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }), env);
}

describe('前端真实 payload → 后端接口（回归）', () => {
  test('app.js 暴露了与页面同款的 payload 构建器', () => {
    assert.ok(builders, 'globalThis.bookmadebook 未挂载（app.js 顶部 location 防护失效？）');
    assert.equal(typeof builders.buildChildPayload, 'function');
    assert.equal(typeof builders.buildAdultPayload, 'function');
  });

  test('儿童线真实 payload 必须携带 parent_declared: true', () => {
    const payload = builders.buildChildPayload('xz', '3-6', 'parent@example.com', true);
    assert.equal(payload.product_type, 'child');
    assert.equal(payload.book_id, 'xz');
    assert.equal(payload.age_band, '3-6');
    assert.equal(payload.parent_declared, true);   // ← 回归点：漏传即后端 400
    assert.equal(payload.email, 'parent@example.com');
    // 儿童线音色由后端强制 design_kid，前端 payload 不应携带 voice 覆盖
    assert.equal(payload.voice, undefined);
  });

  test('儿童线真实 payload 喂后端 → 201 落单（端到端）', async () => {
    const payload = builders.buildChildPayload('gl', '7-12', 'parent2@example.com', true);
    const res = await postOrder(payload);
    assert.equal(res.status, 201);
    const data = await res.json();
    assert.equal(data.order.product_type, 'child');
    assert.equal(data.order.book_title, '格林童话');
    assert.equal(data.order.voice, 'design_kid');
    assert.equal(data.order.status, 'pending');
  });

  test('成人线真实 payload 喂后端 → 201 落单', async () => {
    const payload = builders.buildAdultPayload('活着', 20, 'husky_tender', 'adult@example.com');
    const res = await postOrder(payload);
    assert.equal(res.status, 201);
    const data = await res.json();
    assert.equal(data.order.duration_min, 20);
    assert.equal(data.order.voice, 'husky_tender');
    assert.equal(data.order.amount_yuan, '9.90');
  });

  test('儿童线 payload 若被改回漏传 parent_declared → 后端仍拒绝（防回归双保险）', async () => {
    const bad = builders.buildChildPayload('xz', '3-6', 'parent3@example.com', true);
    delete bad.parent_declared; // 模拟旧版前端 bug
    const res = await postOrder(bad);
    assert.equal(res.status, 400);
    assert.match((await res.json()).error, /未成年|家长声明/);
  });
});
