/**
 * bookmadebook · Tablestore 建表脚本（阿里云 FC 版）
 *
 * 用途：在 008 创建好表格存储实例后，一次性初始化两张表。
 * 运行（本机需能访问 OTS 公网 endpoint）：
 *   export TABLESTORE_ENDPOINT=https://<instance>.<region>.ots.aliyuncs.com
 *   export TABLESTORE_INSTANCE=<instance>
 *   export TABLESTORE_AK_ID=xxx   TABLESTORE_AK_SECRET=xxx
 *   node fc/schema.ots.mjs
 *
 * 幂等：表已存在时跳过（不报错）。也可在控制台手动按下方表结构建表。
 */
import TableStore from 'tablestore';

export const ORDERS_TABLE_META = {
  tableName: 'orders',
  primaryKey: [{ name: 'id', type: 'STRING' }], // 订单号 BM-XXX
  // 属性列可变（D1 orders 全字段），无 NULL：null 列不写、读回补 null
};

export const RATE_TABLE_META = {
  tableName: 'rate_limits',
  primaryKey: [{ name: 'key', type: 'STRING' }], // `${email}#${created_day}`
  // 属性列：count(INTEGER) 原子自增计数
};

function buildParams(meta) {
  return {
    tableMeta: {
      tableName: meta.tableName,
      primaryKey: meta.primaryKey,
    },
    // capacityUnit 0/0 = 按量计费（不预留吞吐）；个人产品按量最省
    reservedThroughput: { capacityUnit: { read: 0, write: 0 } },
    tableOptions: { timeToLive: -1, maxVersions: 1 },
  };
}

async function ensureTable(client, meta) {
  try {
    await client.createTable(buildParams(meta));
    console.log(`[ok] 表已创建：${meta.tableName}（PK=${meta.primaryKey.map((k) => k.name).join(',')}）`);
  } catch (err) {
    if (String(err && err.code || '').includes('exist') || String(err && err.message || '').includes('exist')) {
      console.log(`[skip] 表已存在：${meta.tableName}`);
      return;
    }
    console.error(`[fail] 创建 ${meta.tableName} 失败：`, err.code || err.message || err);
    process.exitCode = 1;
  }
}

async function main() {
  const env = process.env;
  if (!env.TABLESTORE_ENDPOINT || !env.TABLESTORE_INSTANCE || !(env.TABLESTORE_AK_ID || env.ALIBABA_CLOUD_ACCESS_KEY_ID)) {
    console.error('缺环境变量：TABLESTORE_ENDPOINT / TABLESTORE_INSTANCE / TABLESTORE_AK_ID(+SECRET)。见文件头注释。');
    process.exit(1);
  }
  const client = new TableStore.Client({
    accessKeyId: env.TABLESTORE_AK_ID || env.ALIBABA_CLOUD_ACCESS_KEY_ID,
    secretAccessKey: env.TABLESTORE_AK_SECRET || env.ALIBABA_CLOUD_ACCESS_KEY_SECRET,
    endpoint: env.TABLESTORE_ENDPOINT,
    instancename: env.TABLESTORE_INSTANCE,
  });
  await ensureTable(client, ORDERS_TABLE_META);
  await ensureTable(client, RATE_TABLE_META);
  console.log('完成。表结构对照见 webapp/迁移方案.md 的「Tablestore 表设计」。');
}

// CLI 直跑
if (process.argv[1] && process.argv[1].endsWith('schema.ots.mjs')) {
  main().catch((err) => { console.error('异常：', err); process.exit(1); });
}

