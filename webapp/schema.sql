-- bookmadebook 自助点书 D1 表结构
-- 本地初始化：npm run db:init  （= wrangler d1 execute bookmadebook_orders --local --file=./schema.sql）
-- 线上初始化：wrangler d1 execute bookmadebook_orders --remote --file=./schema.sql

CREATE TABLE IF NOT EXISTS orders (
  id             TEXT PRIMARY KEY,                -- 订单号，如 BM-MXYZ12
  email          TEXT NOT NULL,                   -- 下单邮箱（防滥用限流键）
  product_type   TEXT NOT NULL DEFAULT 'adult',   -- adult=成人点书 / child=儿童白名单点播
  book_title     TEXT NOT NULL,                   -- 书名（成人=用户输入；儿童=白名单书名）
  book_id        TEXT,                            -- 儿童白名单书单 id（成人 NULL）
  duration_min   INTEGER,                         -- 目标时长（10/20/30，成人线；儿童线默认 10）
  voice          TEXT NOT NULL,                   -- 音色：hist_deep_male / husky_tender / design_kid
  age_band       TEXT,                            -- 儿童年龄档：3-6 / 7-12
  parent_declared INTEGER DEFAULT 0,              -- 家长声明（儿童线必选 1）
  amount_fen     INTEGER NOT NULL,                -- 金额（分）。MVP 定价 990；儿童次数卡下一轮接入
  status         TEXT NOT NULL DEFAULT 'pending', -- 状态机：pending→paid→generating→done/failed；refunded
  provider       TEXT,                            -- 支付渠道（mock=aifadian_mock / 正式=aifadian）
  voucher        TEXT,                            -- 支付凭证号（爱发电回调）
  eta_min        INTEGER,                         -- 预计完成所需分钟（占位估算，daemon 轮次细化）
  created_day    TEXT NOT NULL,                   -- 下单日（Asia/Shanghai YYYY-MM-DD，限流用）
  created_at     TEXT NOT NULL,                   -- 创建时间 ISO8601
  updated_at     TEXT                             -- 最后更新时间 ISO8601
);

CREATE INDEX IF NOT EXISTS idx_orders_email_day ON orders(email, created_day);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
