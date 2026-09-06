/**
 * bookmadebook · Tablestore（阿里云表格存储）存储适配层（FC 版）
 *
 * 职责：实现与 worker.js 内存/D1 完全一致的 5 方法存储接口：
 *   todayCount(email, day) / getPendingPaid() / insert(row) / get(id) / patch(id, fields)
 * 这样 worker.js 的业务路由（下单/限流/状态机/支付回调）一行不用改，
 * 只需要把 env.store 指向本适配层返回的 store 对象。
 *
 * 表设计（两表，主键均为单列 STRING；MVP 量级够用，见 迁移方案.md）：
 *   orders      主键 id      —— 一行一单，属性列 = D1 orders 全字段
 *                               （OTS 无 NULL：null/undefined 列不写，读回时补 null）
 *   rate_limits 主键 key     —— `${email}#${created_day}` 计数行，count 列原子自增，
 *                               解决「每邮箱每日 3 单」限流（避免全表扫 email）
 *
 * 读接口说明：Tablestore SDK v5 不传 callback 时返回 Promise（client.getRow(params) 直接 await）。
 * 环境变量（FC 控制台 / s.yaml 注入，密钥勿硬编码）：
 *   TABLESTORE_ENDPOINT   公网 endpoint，形如 https://<instance>.<region>.ots.aliyuncs.com
 *   TABLESTORE_INSTANCE   实例名
 *   TABLESTORE_AK_ID      AccessKeyId
 *   TABLESTORE_AK_SECRET  AccessKeySecret（也兼容 ALIBABA_CLOUD_ACCESS_KEY_ID / _SECRET）
 *
 * 已知取舍（MVP 接受，量大再优化，均写入 迁移方案.md）：
 *   - getPendingPaid() 走全表 getRange 后内存过滤 status='paid'（MVP 单量小，30s 轮询无压力）；
 *     量大后可加「paid 队列表/索引」，daemon 改为按队列表范围读。
 *   - todayCount() 用 rate_limits 计数行，先查后增存在极小并发窗口（限流是防滥用非精确账本，
 *     MVP 可接受；如需严格可改条件更新 +1 时校验 count < 3，失败即 429）。
 */

import TableStore from 'tablestore';

export const ORDERS_TABLE = 'orders';
export const RATE_TABLE = 'rate_limits';

/** D1 orders 全字段（写入/读出的行对象字段顺序） */
const ORDER_FIELDS = [
  'id', 'email', 'product_type', 'book_title', 'book_id',
  'duration_min', 'voice', 'age_band', 'parent_declared',
  'amount_fen', 'status', 'provider', 'voucher', 'eta_min',
  'oss_key', 'created_day', 'created_at', 'updated_at',
];

/** 整数属性列：写入须用 Long 包装，读回是 Long 对象 */
const INT_FIELDS = new Set(['duration_min', 'amount_fen', 'eta_min', 'parent_declared']);

// ── 工具 ──────────────────────────────────────────────────────────────
/** OTS 数值列读回统一转 number（Long 对象 → toNumber） */
function toNum(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'object' && typeof v.toNumber === 'function') return v.toNumber();
  return Number(v);
}

/** 行对象 → OTS 属性列数组 [{列名: 值}]；null/undefined 跳过（OTS 无 NULL） */
function rowToAttrs(row) {
  const attrs = [];
  for (const field of ORDER_FIELDS) {
    if (field === 'id') continue; // 主键单独传
    const v = row[field];
    if (v === null || v === undefined) continue;
    attrs.push({ [field]: INT_FIELDS.has(field) ? TableStore.Long.fromNumber(Number(v)) : String(v) });
  }
  return attrs;
}

/** OTS 行（primaryKey + attributes 数组）→ 业务行对象（缺列补 null） */
function otsRowToRow(row) {
  if (!row || !row.primaryKey || row.primaryKey.length === 0) return null;
  const out = { id: row.primaryKey[0].value };
  const map = new Map((row.attributes || []).map((a) => [a.columnName, a.columnValue]));
  for (const field of ORDER_FIELDS) {
    if (field === 'id') continue;
    const v = map.get(field);
    out[field] = v === undefined || v === null ? null : (INT_FIELDS.has(field) ? toNum(v) : String(v));
  }
  return out;
}

// ── 单列 STRING 主键的辅助参数 ─────────────────────────────────────────
const pkOf = (id) => [{ id: String(id) }];
const pkOfKey = (key) => [{ key: String(key) }]; // rate_limits 表主键列名是 key
const rangeAll = () => ({
  inclusiveStartPrimaryKey: [{ id: TableStore.INF_MIN }],
  exclusiveEndPrimaryKey: [{ id: TableStore.INF_MAX }],
});

// ── 适配层主体：5 方法与 worker.js 存储接口一一对应 ─────────────────────
/**
 * 创建 Tablestore store。
 * 缺必要环境变量时返回 null（调用方回退内存 store，便于本地测试/联调）。
 */
export function createOtsStoreFromEnv(env = process.env) {
  const endpoint = env.TABLESTORE_ENDPOINT;
  const instancename = env.TABLESTORE_INSTANCE;
  const accessKeyId = env.TABLESTORE_AK_ID || env.ALIBABA_CLOUD_ACCESS_KEY_ID;
  const secretAccessKey = env.TABLESTORE_AK_SECRET || env.ALIBABA_CLOUD_ACCESS_KEY_SECRET;
  if (!endpoint || !instancename || !accessKeyId || !secretAccessKey) return null;

  const client = new TableStore.Client({
    accessKeyId, secretAccessKey, endpoint, instancename,
    maxRetries: 3,
    httpOptions: { timeout: 10000 },
  });

  return {
    kind: 'ots',

    /** 每邮箱每日已下单数：读 rate_limits 计数行 */
    async todayCount(email, day) {
      const data = await client.getRow({
        tableName: RATE_TABLE,
        primaryKey: pkOfKey(`${email}#${day}`),
        maxVersions: 1,
      });
      const row = data && data.row && data.row.attributes ? data.row.attributes : [];
      const count = row.find((a) => a.columnName === 'count');
      return count ? toNum(count.columnValue) : 0;
    },

    /** 拉取 status=paid 订单（全表扫 + 内存过滤；MVP 量级可接受） */
    async getPendingPaid() {
      const rows = [];
      let start = rangeAll().inclusiveStartPrimaryKey;
      for (;;) {
        const data = await client.getRange({
          tableName: ORDERS_TABLE,
          direction: TableStore.Direction.FORWARD,
          inclusiveStartPrimaryKey: start,
          exclusiveEndPrimaryKey: [{ id: TableStore.INF_MAX }],
          limit: 200,
          maxVersions: 1,
        });
        for (const r of data.rows || []) {
          const row = otsRowToRow(r);
          if (row && row.status === 'paid') rows.push(row);
        }
        if (!data.nextStartPrimaryKey || data.nextStartPrimaryKey.length === 0) break;
        start = data.nextStartPrimaryKey.map((k) => ({ id: k.value }));
      }
      return rows.sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
    },

    /** 落单：写 orders 行 + rate_limits 原子 +1 */
    async insert(row) {
      await client.putRow({
        tableName: ORDERS_TABLE,
        condition: new TableStore.Condition(TableStore.RowExistenceExpectation.IGNORE, null),
        primaryKey: pkOf(row.id),
        attributeColumns: rowToAttrs(row),
      });
      await this.incrRate(row.email, row.created_day);
    },

    /** 限流计数：首单条件建行 count=1（期望行不存在）；已存在 → 原子 INCREMENT +1。
     *  条件建行失败不依赖服务端错误码判断：统一落到 INCREMENT（幂等收敛），
     *  若建行失败是真实故障（表缺失/鉴权），updateRow 会以同一底层错误上抛。 */
    async incrRate(email, day) {
      const key = `${email}#${day}`;
      try {
        await client.putRow({
          tableName: RATE_TABLE,
          condition: new TableStore.Condition(TableStore.RowExistenceExpectation.EXPECT_NOT_EXIST, null),
          primaryKey: pkOfKey(key),
          attributeColumns: [{ count: TableStore.Long.fromNumber(1) }],
        });
      } catch (putErr) {
        // 行已存在（条件不满足）属预期；真实故障由下面的 updateRow 暴露
        await client.updateRow({
          tableName: RATE_TABLE,
          condition: new TableStore.Condition(TableStore.RowExistenceExpectation.IGNORE, null),
          primaryKey: pkOfKey(key),
          updateOfAttributeColumns: [{ INCREMENT: [{ count: TableStore.Long.fromNumber(1) }] }],
        });
      }
    },

    /** 查单：不存在返回 null（与 D1 .first() 语义一致） */
    async get(id) {
      const data = await client.getRow({
        tableName: ORDERS_TABLE,
        primaryKey: pkOf(id),
        maxVersions: 1,
      });
      return otsRowToRow(data && data.row);
    },

    /** 改单：读-改-写（PUT 全列，行必须存在） */
    async patch(id, fields) {
      const row = await this.get(id);
      if (!row) return null;
      const merged = { ...row, ...fields };
      await client.updateRow({
        tableName: ORDERS_TABLE,
        condition: new TableStore.Condition(TableStore.RowExistenceExpectation.EXPECT_EXIST, null),
        primaryKey: pkOf(id),
        updateOfAttributeColumns: [{ PUT: rowToAttrs(merged) }],
      });
      return merged;
    },
  };
}
