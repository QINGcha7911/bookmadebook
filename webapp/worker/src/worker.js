/**
 * bookmadebook 自助点书 · Workers 后端（任务 1+2 MVP）
 *
 * 路由：
 *   GET  /api/books            儿童白名单书单（前端儿童 tab 数据源）
 *   POST /api/order            下单（Turnstile + 邮箱每日 3 单限流）
 *   POST /api/pay-callback     支付回调（爱发电占位；MOCK_PAY=1 时接受模拟回调）
 *   GET  /api/order/:id        订单状态查询（前端轮询）
 *
 * 状态机：pending → paid → generating → done / failed（refunded 兜底）
 * daemon（本地电脑 30s 轮询拉单）在下一轮任务接入，本轮只预留状态位。
 *
 * 存储：生产 = D1（env.DB）；本地无 D1 绑定（纯 node 测试）时自动退回内存 Map，
 *       保证 test/api.test.mjs 能脱离 wrangler 直接跑通接口逻辑。
 */

// ── 常量 ──────────────────────────────────────────────────────────────
const STATUSES = ['pending', 'paid', 'generating', 'done', 'failed', 'refunded'];
const ADULT_DURATIONS = [10, 20, 30];
const ADULT_VOICES = ['hist_deep_male', 'husky_tender']; // 历史深男 / 散文温柔沙哑
const CHILD_VOICE = 'design_kid';                         // 儿童音（与流水线 VOICE_ALIASES 对齐）
const ADULT_PRICE_FEN = 990;                              // 成人单条 9.9 元（MVP；儿童次数卡下一轮接入）
const CHILD_PRICE_FEN = 990;                              // 儿童线演示价 9.9，真实为次数卡抵扣（下一轮）
const DAY_LIMIT = 3;                                      // 每邮箱每日最多 3 单
const ETA_BUFFER_MIN = 5;                                 // 生成估算缓冲（daemon 接入后按队列细化）

/** 儿童白名单书单（公版/经典；代码内数组先行，后续可挪到 D1/配置） */
const CHILD_BOOKS = [
  { id: 'xz',   title: '小王子',          author: '圣埃克苏佩里',  age: ['3-6', '7-12'], note: '温柔童话，讲爱与责任' },
  { id: 'ads',  title: '安徒生童话',      author: '安徒生',        age: ['3-6', '7-12'], note: '丑小鸭、海的女儿等经典篇' },
  { id: 'gl',   title: '格林童话',        author: '格林兄弟',      age: ['3-6', '7-12'], note: '白雪公主、小红帽等' },
  { id: 'yso',  title: '伊索寓言',        author: '伊索',          age: ['3-6', '7-12'], note: '龟兔赛跑等短寓言' },
  { id: 'yyy',  title: '一千零一夜',      author: '阿拉伯民间故事', age: ['7-12'],        note: '阿里巴巴、辛巴达历险' },
  { id: 'als',  title: '爱丽丝漫游奇境',  author: '刘易斯·卡罗尔', age: ['7-12'],        note: '奇幻冒险，想象力启蒙' },
  { id: 'mp',   title: '木偶奇遇记',      author: '科洛迪',        age: ['3-6', '7-12'], note: '小木偶成长历险' },
  { id: 'nes',  title: '尼尔斯骑鹅旅行记', author: '塞尔玛·拉格洛夫', age: ['7-12'],      note: '跟着大雁飞遍瑞典' },
  { id: 'oz',   title: '绿野仙踪',        author: '弗兰克·鲍姆',   age: ['3-6', '7-12'], note: '多萝茜的回家之路' },
  { id: 'xyj',  title: '西游记（儿童版）', author: '吴承恩',        age: ['7-12'],        note: '大闹天宫、三打白骨精' },
];

// ── 小工具 ────────────────────────────────────────────────────────────
const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  });

const corsHeaders = (env) => {
  const origin = (env && env.CORS_ORIGIN) || '*';
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, x-daemon-token',
    'Access-Control-Max-Age': '86400',
  };
};

const ok = (env, data, status = 200) => {
  const r = json(data, status);
  Object.entries(corsHeaders(env)).forEach(([k, v]) => r.headers.set(k, v));
  return r;
};

/** 上海时区（UTC+8）的 YYYY-MM-DD，用于"每邮箱每日 3 单"限流 */
function shanghaiDay(ts = Date.now()) {
  return new Date(ts + 8 * 3600 * 1000).toISOString().slice(0, 10);
}

/** 生成可读订单号：BM + 时间戳36进制大写 + 随机4位 */
function newOrderId() {
  const t = Date.now().toString(36).toUpperCase().slice(-6);
  const r = Math.random().toString(36).toUpperCase().slice(2, 6);
  return `BM-${t}${r}`;
}

/** 基础邮箱校验（够用即可，无需过度严格） */
function validEmail(email) {
  return typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim());
}

/** 预估分钟数：成人=时长+缓冲；儿童默认 10 分钟稿 */
function estimateEta(durationMin) {
  const base = Math.min(Math.max(durationMin || 10, 10), 30);
  return base + ETA_BUFFER_MIN;
}

// ── Turnstile 人机验证（未配置 secret 时放行，便于本地开发）────────────
async function verifyTurnstile(env, token) {
  if (!env.TURNSTILE_SECRET) {
    return { ok: true, mock: true }; // 本地开发无 secret → 跳过（前端也未加载组件）
  }
  if (!token) return { ok: false, error: '缺少人机验证令牌' };
  try {
    const fd = new FormData();
    fd.append('secret', env.TURNSTILE_SECRET);
    fd.append('response', token);
    const r = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST', body: fd,
    });
    const data = await r.json();
    return data.success ? { ok: true } : { ok: false, error: '人机验证未通过' };
  } catch (e) {
    return { ok: false, error: '人机验证服务异常' };
  }
}

// ── 存储层：D1（生产） / 内存 Map（无 D1 的纯 node 测试）───────────────
/** 内存实现：接口对齐 D1 需要用到的三个方法 */
function createMemoryStore() {
  const rows = new Map();
  const todayCount = async (email, day) =>
    [...rows.values()].filter((r) => r.email === email && r.created_day === day).length;
  const getPendingPaid = async () =>
    [...rows.values()].filter((r) => r.status === 'paid')
      .sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
  const insert = async (row) => { rows.set(row.id, { ...row }); };
  const get = async (id) => rows.get(id) || null;
  const patch = async (id, fields) => {
    const row = rows.get(id);
    if (!row) return null;
    Object.assign(row, fields);
    return row;
  };
  return { kind: 'memory', todayCount, getPendingPaid, insert, get, patch };
}

/** D1 实现 */
function createD1Store(db) {
  const todayCount = async (email, day) => {
    const r = await db
      .prepare('SELECT COUNT(*) AS c FROM orders WHERE email = ? AND created_day = ?')
      .bind(email, day).first();
    return r ? Number(r.c || 0) : 0;
  };
  const insert = async (row) => {
    await db
      .prepare(`INSERT INTO orders
        (id,email,product_type,book_title,book_id,duration_min,voice,age_band,
         parent_declared,amount_fen,status,provider,voucher,eta_min,created_day,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
      .bind(
        row.id, row.email, row.product_type, row.book_title, row.book_id ?? null,
        row.duration_min ?? null, row.voice, row.age_band ?? null,
        row.parent_declared ? 1 : 0, row.amount_fen, row.status,
        row.provider ?? null, row.voucher ?? null, row.eta_min,
        row.created_day, row.created_at, row.updated_at
      ).run();
  };
  const getPendingPaid = async () => {
    const { results } = await db
      .prepare("SELECT * FROM orders WHERE status = 'paid' ORDER BY created_at ASC")
      .all();
    return results || [];
  };
  const get = async (id) => {
    const r = await db.prepare('SELECT * FROM orders WHERE id = ?').bind(id).first();
    return r || null;
  };
  const patch = async (id, fields) => {
    const row = await get(id);
    if (!row) return null;
    const sets = [], binds = [];
    for (const [k, v] of Object.entries(fields)) {
      sets.push(`${k} = ?`);
      binds.push(v);
    }
    binds.push(id);
    await db.prepare(`UPDATE orders SET ${sets.join(', ')} WHERE id = ?`).bind(...binds).run();
    return get(id);
  };
  return { kind: 'd1', todayCount, getPendingPaid, insert, get, patch };
}

/** 取存储：env.DB 存在用 D1，否则内存（供 node 测试/无绑定时容错） */
function storeFor(env) {
  if (env && env.DB) return createD1Store(env.DB);
  if (!storeFor._mem) storeFor._mem = createMemoryStore();
  return storeFor._mem;
}

// ── 下单参数校验 ──────────────────────────────────────────────────────
function validateOrder(body) {
  const err = (msg) => ({ ok: false, error: msg });
  if (!body) return err('请求体不能为空');
  const email = String(body.email || '').trim().toLowerCase();
  if (!validEmail(email)) return err('邮箱格式不正确');
  const productType = body.product_type === 'child' ? 'child' : 'adult';
  const voice = String(body.voice || '');

  if (productType === 'child') {
    // 儿童线：白名单书单 + 年龄档 + 家长声明（必选）
    const book = CHILD_BOOKS.find((b) => b.id === body.book_id);
    if (!book) return err('请从白名单书单中选择一本（儿童区只支持白名单点播）');
    const ageBand = String(body.age_band || '');
    if (!['3-6', '7-12'].includes(ageBand)) return err('请选择孩子年龄档');
    if (!book.age.includes(ageBand)) return err(`该书暂不支持 ${ageBand} 岁档`);
    if (body.parent_declared !== true && body.parent_declared !== 'true')
      return err('请勾选「本人为未成年子女点播」声明');
    if (voice && voice !== CHILD_VOICE) return err('儿童线使用默认儿童音色，无需指定');
    return {
      ok: true,
      order: {
        email, product_type: 'child', book, age_band: ageBand,
        voice: CHILD_VOICE, duration_min: 10, parent_declared: true,
        amount_fen: CHILD_PRICE_FEN,
      },
    };
  }

  // 成人线：书名 + 时长 + 音色
  const title = String(body.book_title || '').trim();
  if (title.length < 2 || title.length > 60) return err('书名需在 2-60 字之间');
  const duration = Number(body.duration_min);
  if (!ADULT_DURATIONS.includes(duration)) return err('时长请选择 10/20/30 分钟');
  if (!ADULT_VOICES.includes(voice)) return err('音色仅支持 历史深男 / 散文温柔沙哑');
  return {
    ok: true,
    order: {
      email, product_type: 'adult', book_title: title, duration_min: duration,
      voice, parent_declared: false, amount_fen: ADULT_PRICE_FEN,
    },
  };
}

// ── 路由处理 ──────────────────────────────────────────────────────────
async function handleBooks() {
  return { ok: true, list: CHILD_BOOKS };
}

async function handleCreateOrder(env, body) {
  // 1) 人机验证（Turnstile）
  const tv = await verifyTurnstile(env, body && body.turnstile_token);
  if (!tv.ok) return json({ ok: false, error: tv.error }, 400);

  // 2) 参数校验
  const v = validateOrder(body);
  if (!v.ok) return json({ ok: false, error: v.error }, 400);
  const o = v.order;
  const store = storeFor(env);

  // 3) 每邮箱每日限 3 单
  const day = shanghaiDay();
  const todayCount = await store.todayCount(o.email, day);
  if (todayCount >= DAY_LIMIT) {
    return json({ ok: false, error: `今日下单次数已达上限（${DAY_LIMIT} 单），请明天再来` }, 429);
  }

  // 4) 落单
  const now = new Date().toISOString();
  const id = newOrderId();
  const etaMin = estimateEta(o.duration_min);
  const row = {
    id,
    email: o.email,
    product_type: o.product_type,
    book_title: o.product_type === 'child' ? o.book.title : o.book_title,
    book_id: o.product_type === 'child' ? o.book.id : null,
    duration_min: o.duration_min,
    voice: o.voice,
    age_band: o.age_band || null,
    parent_declared: o.parent_declared ? 1 : 0,
    amount_fen: o.amount_fen,
    status: 'pending',
    provider: null,
    voucher: null,
    eta_min: etaMin,
    created_day: day,
    created_at: now,
    updated_at: now,
  };
  await store.insert(row);

  return json({
    ok: true,
    order: {
      order_id: id,
      status: 'pending',
      product_type: row.product_type,
      book_title: row.book_title,
      duration_min: row.duration_min,
      voice: row.voice,
      age_band: row.age_band,
      amount_fen: row.amount_fen,
      amount_yuan: (row.amount_fen / 100).toFixed(2),
      eta_min: etaMin,
      created_at: row.created_at,
      // 支付为异步：pending 需先完成支付（爱发电/模拟）才进入队列
      next_step: 'pay',
    },
  }, 201);
}

async function handlePayCallback(env, body) {
  // ⚠️ MVP 占位实现：
  //  - MOCK_PAY=1（本地开发）接受任意 { order_id, voucher }，直接标记 paid
  //  - 生产：MOCK_PAY=0，这里必须替换为爱发电回调验签逻辑（下一轮交付接入）
  if (!body || !body.order_id) return json({ ok: false, error: '缺少 order_id' }, 400);
  const store = storeFor(env);
  const row = await store.get(String(body.order_id));
  if (!row) return json({ ok: false, error: '订单不存在' }, 404);

  const mockAllowed = String(env.MOCK_PAY || '0') === '1';
  if (!mockAllowed) {
    return json({ ok: false, error: '生产环境：请接入爱发电真实回调验签后再调用' }, 403);
  }

  if (row.status === 'paid' || row.status === 'generating' || row.status === 'done') {
    // 幂等：已支付的回调直接成功返回，避免前端重试报错
    return json({ ok: true, order: publicOrder(row) });
  }
  if (row.status === 'failed' || row.status === 'refunded') {
    return json({ ok: false, error: `订单当前状态 ${row.status}，无法支付` }, 409);
  }

  const voucher = String(body.voucher || `mock-${Date.now()}`).slice(0, 64);
  const updated = await store.patch(row.id, {
    status: 'paid', provider: 'aifadian_mock', voucher,
    updated_at: new Date().toISOString(),
  });
  return json({ ok: true, order: publicOrder(updated) });
}

async function handleGetOrder(env, id) {
  const store = storeFor(env);
  const row = await store.get(id);
  if (!row) return json({ ok: false, error: '订单不存在' }, 404);
  return json({ ok: true, order: publicOrder(row) });
}

// ── daemon 管理接口（任务 3：本地生成工人轮询拉单）────────────────────
/** DAEMON_TOKEN 校验：header x-daemon-token。env 未配置 token 时一律拒绝（fail-closed）。 */
function authDaemon(env, request) {
  const expect = env && env.DAEMON_TOKEN;
  if (!expect) return false;
  const got = request.headers.get('x-daemon-token');
  return !!got && got === expect;
}

/** 状态机白名单：只允许 paid→generating→done/failed（终态不可逆） */
const ALLOWED_TRANSITIONS = {
  paid: ['generating'],
  generating: ['done', 'failed'],
};

/** GET /api/admin/pending-orders：拉取 status=paid 待生成订单（按创建时间先到先出） */
async function handleAdminPending(env) {
  const rows = await storeFor(env).getPendingPaid();
  return { ok: true, count: rows.length, list: rows.map(publicOrder) };
}

/** PATCH /api/admin/order/:id：推进状态（daemon 认领/完成/失败） */
async function handleAdminPatch(env, id, body) {
  const target = body && body.status;
  if (!target || !['generating', 'done', 'failed'].includes(target)) {
    return { code: 400, body: { ok: false, error: '非法目标状态（仅 generating/done/failed）' } };
  }
  const store = storeFor(env);
  const row = await store.get(id);
  if (!row) return { code: 404, body: { ok: false, error: '订单不存在' } };
  const allowed = ALLOWED_TRANSITIONS[row.status] || [];
  if (!allowed.includes(target)) {
    return {
      code: 409,
      body: { ok: false, error: `订单状态 ${row.status} 不允许转为 ${target}（应为 ${allowed.join('/') || '终态不可变'}）` },
    };
  }
  const updated = await store.patch(id, {
    status: target,
    updated_at: new Date().toISOString(),
  });
  return { code: 200, body: { ok: true, order: publicOrder(updated) } };
}

/** 对外返回的订单视图（隐藏内部字段，预留下载位） */
function publicOrder(row) {
  return {
    order_id: row.id,
    status: row.status,
    product_type: row.product_type,
    book_title: row.book_title,
    book_id: row.book_id,
    duration_min: row.duration_min,
    voice: row.voice,
    age_band: row.age_band,
    amount_fen: row.amount_fen,
    amount_yuan: (row.amount_fen / 100).toFixed(2),
    eta_min: row.eta_min,
    created_at: row.created_at,
    updated_at: row.updated_at,
    // 下载地址：daemon + R2（下一轮任务）就绪后，done 状态返回真实签名链接
    download_url: row.status === 'done' ? `/api/download/${row.id}` : null,
  };
}

// ── 入口 ──────────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS 预检
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }

    // GET /api/books
    if (request.method === 'GET' && path === '/api/books') {
      return ok(env, await handleBooks());
    }

    // POST /api/order
    if (request.method === 'POST' && path === '/api/order') {
      let body = null;
      try { body = await request.json(); } catch (e) { /* 非 JSON → 校验会报错 */ }
      const r = await handleCreateOrder(env, body);
      Object.entries(corsHeaders(env)).forEach(([k, v]) => r.headers.set(k, v));
      return r;
    }

    // POST /api/pay-callback
    if (request.method === 'POST' && path === '/api/pay-callback') {
      let body = null;
      try { body = await request.json(); } catch (e) { /* ignore */ }
      const r = await handlePayCallback(env, body);
      Object.entries(corsHeaders(env)).forEach(([k, v]) => r.headers.set(k, v));
      return r;
    }

    // GET /api/order/:id
    const mOrder = path.match(/^\/api\/order\/([A-Za-z0-9-]+)$/);
    if (request.method === 'GET' && mOrder) {
      const r = await handleGetOrder(env, mOrder[1]);
      Object.entries(corsHeaders(env)).forEach(([k, v]) => r.headers.set(k, v));
      return r;
    }

    // GET /api/admin/pending-orders（daemon 30s 轮询拉单）
    if (request.method === 'GET' && path === '/api/admin/pending-orders') {
      if (!authDaemon(env, request)) {
        return ok(env, { ok: false, error: 'unauthorized: 缺少/错误 x-daemon-token' }, 401);
      }
      return ok(env, await handleAdminPending(env));
    }

    // PATCH /api/admin/order/:id（daemon 推进状态机）
    const mAdmin = path.match(/^\/api\/admin\/order\/([A-Za-z0-9-]+)$/);
    if (request.method === 'PATCH' && mAdmin) {
      if (!authDaemon(env, request)) {
        return ok(env, { ok: false, error: 'unauthorized: 缺少/错误 x-daemon-token' }, 401);
      }
      let body = null;
      try { body = await request.json(); } catch (e) { /* 非 JSON → 400 */ }
      const r = await handleAdminPatch(env, mAdmin[1], body);
      return ok(env, r.body, r.code);
    }

    // 兜底：API 404（静态页面由 Cloudflare Pages / 本地 python http.server 提供）
    return json({ ok: false, error: 'Not Found', path }, 404);
  },
};
