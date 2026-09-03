# bookmadebook · 自助点书生成 Web MVP

「私人听书工厂」自助点书产品：用户输入书名 → 付费 → 本机 AI 流水线生成 mp3 → 下载。
本目录为 **任务 1+2**：Cloudflare Pages H5 前端 + Workers 后端 + D1 表结构。

> 本轮范围：前端下单全流程 + 后端 API + D1 schema（本地可跑，mock 支付）。
> 下一轮：daemon（本地电脑 30s 轮询拉单）、R2 存储下载、爱发电真实回调、Turnstile 前端组件、真实部署。

## 目录结构

```
webapp/
├── public/                 # Cloudflare Pages 静态站（H5，移动端优先）
│   ├── index.html          # 成人点书 / 儿童专区 双 Tab + 订单页
│   ├── style.css           # 简洁温暖样式
│   └── app.js              # 下单、状态轮询、模拟支付（开发）
├── worker/
│   └── src/worker.js       # Workers 后端（单文件，无 D1 时可内存存储）
├── test/
│   ├── api.test.mjs        # API 自测（node:test，15 用例，含 admin 接口）
│   └── frontend-payload.test.mjs  # 前端真实 payload 回归（5 用例）
├── daemon/
│   └── daemon.py           # 本地生成工人：30s 轮询 paid 单 → 写稿+harness 生成 mp3
├── schema.sql              # D1 orders 表 + 索引
├── wrangler.toml           # Worker 配置（MOCK_PAY=1，D1 绑定占位 ID）
├── .dev.vars.example       # 本地环境变量示例
└── package.json
```

## 本地运行（无需真实部署）

需要 Node 18+（本仓库开发机为 Node 22）。

```bash
cd webapp
npm install
npm run db:init      # 初始化本地 D1（wrangler d1 execute --local）

# 终端 A：起 Worker API（http://127.0.0.1:8787）
npm run dev

# 终端 B：起前端静态站（http://127.0.0.1:8788）
npm run static
```

浏览器打开 `http://127.0.0.1:8788`：
前端自动把 API 请求指向 `http://127.0.0.1:8787`（同机开发无需配 CORS）。
成人线提交后点「模拟支付成功（本地开发）」即可看到订单进入 `paid`。

也可直接访问 Worker 页面验证 API：`http://127.0.0.1:8787/api/books`。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/books` | 儿童白名单书单（10 本公版经典） |
| POST | `/api/order` | 下单（Turnstile + 每邮箱每日 3 单限流） |
| POST | `/api/pay-callback` | 支付回调（开发 MOCK_PAY=1 模拟；生产需接爱发电验签） |
| GET | `/api/order/:id` | 订单状态查询（前端轮询） |

状态机：`pending → paid → generating → done / failed`（`refunded` 兜底）。
`generating` 之后由本地 daemon（下一轮任务 3）消费推进。

## daemon 管理接口（任务 3）

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/admin/pending-orders` | `x-daemon-token` | 拉取 `status=paid` 待生成订单 |
| PATCH | `/api/admin/order/:id` | `x-daemon-token` | 推进 `paid→generating→done/failed` |

token 校验规则：header `x-daemon-token` 必须等于 `[vars] DAEMON_TOKEN`
（本地默认 `dev-daemon-token-001`；生产用 `wrangler secret put DAEMON_TOKEN`）。
状态机白名单：`paid→generating`、`generating→done/failed`，终态不可逆，
非法跳转返回 409；未配置 token 时全部 401（fail-closed）。

### 本地 daemon（任务 3）

仓库根新增写稿器 `scripts/write_script.py`（DeepSeek 写稿，key 读
`~/.hermes/config.yaml model.providers.deepseek`，不硬编码）。daemon 位于
`webapp/daemon/daemon.py`：

```bash
cd webapp
# 终端 A：Worker（含本地 D1）
npm run dev

# 终端 B：单次拉单处理（测试）——每笔 paid 订单执行：
#   write_script（写稿）→ harness（质量门+TTS+输出验证）→ PATCH done/failed
python3 daemon/daemon.py --once
# 常驻 30s 轮询：
python3 daemon/daemon.py
# 链路测试不烧 DeepSeek（写稿用占位稿，TTS 仍真实）：
python3 daemon/daemon.py --once --mock-script
```

约束与保障：
- 并发=1：写稿与生成全程串行（参考 09-01 教训：并行 TTS/渲染会资源竞争中断）。
- 产物落 `<仓库>/webapp-output/<order_id>/`（script.txt + mp3）；
  订单 `done` 的 `download_url` 目前为 `/api/download/:id` 占位（R2 下一轮接真实链接）。
- 单订单超时默认 60 分钟自动 `failed`；daemon 崩溃重启后，
  `daemon/state.json` 中滞留 `generating` 超过超时的订单会被自动补 `failed`。
- 日志：`webapp/daemon/daemon.log`（运行态产物已 gitignore）。

## 定价（MVP）

### curl 自测示例

```bash
# 1) 白名单书单
curl -s http://127.0.0.1:8787/api/books

# 2) 成人下单（书名/时长/音色/邮箱）
curl -s -X POST http://127.0.0.1:8787/api/order \
  -H 'Content-Type: application/json' \
  -d '{"product_type":"adult","book_title":"活着","duration_min":20,"voice":"husky_tender","email":"me@example.com"}'

# 3) 儿童点播（白名单书 id + 年龄档 + 家长声明）
curl -s -X POST http://127.0.0.1:8787/api/order \
  -H 'Content-Type: application/json' \
  -d '{"product_type":"child","book_id":"xz","age_band":"3-6","parent_declared":true,"email":"me@example.com"}'

# 4) 模拟支付成功（MOCK_PAY=1 时可用；<ORDER_ID> 替换为上面返回的订单号）
curl -s -X POST http://127.0.0.1:8787/api/pay-callback \
  -H 'Content-Type: application/json' \
  -d '{"order_id":"<ORDER_ID>","voucher":"test-001"}'

# 5) 查订单状态
curl -s http://127.0.0.1:8787/api/order/<ORDER_ID>
```

## 自动化自测

```bash
npm test   # node --test，20 用例全绿（API 15 + 前端 payload 回归 5）
```

测试原理：`worker.js` 在无 `env.DB` 时自动退回内存 Map 存储，
因此可脱离 wrangler 直接 `import` worker 跑接口逻辑。

## 防滥用设计（已内置）

- Turnstile 人机验证：后端已接 `siteverify`；未配置 `TURNSTILE_SECRET` 时放行（本地开发）。
- 每邮箱每日限 3 单：按上海时区 `created_day` 计数，超限返回 429。
- 儿童线仅白名单书单（代码内 `CHILD_BOOKS` 数组，后续可挪 D1/配置）。
- 儿童线强制家长声明 + 年龄档（按书目适龄过滤）。

## 定价（MVP）

- 成人单条 ¥9.9。
- 儿童线当前演示价 ¥9.9/条；次数卡（10 次 ¥39 / 30 次 ¥99）下一轮接入抵扣。

## 部署步骤（下一轮由 008 浏览器执行，先留档）

```bash
# 1) 创建 D1 数据库，拿真实 database_id
wrangler d1 create bookmadebook_orders

# 2) 把返回的 database_id 填入 wrangler.toml 的 [[d1_databases]]

# 3) 线上初始化表
wrangler d1 execute bookmadebook_orders --remote --file=./schema.sql

# 4) 部署 Worker
wrangler deploy

# 5) 部署 Pages（public/ 目录）到 Cloudflare Pages，路由 /api/* 指向 Worker

# 6) 生产配置
wrangler secret put TURNSTILE_SECRET   # 开启人机验证
wrangler secret put CORS_ORIGIN        # 生产站源
# 前端集成 Turnstile 组件；wrangler.toml [vars] 中 MOCK_PAY 置 0
# 爱发电真实回调验签：替换 worker.js handlePayCallback 的占位实现
```

## 下一轮 TODO（任务 4+）

- R2 存储：产物上传 + `/api/download/:id` 签名链接下发（替换占位）。
- 爱发电真实回调验签 + 订单号打通。
- Turnstile 前端组件、邮箱验证码、儿童次数卡余额扣减。
- 儿童线时长模型：儿童模板语速（120-170 字/分）与质量门引擎语速（~240）对齐。
