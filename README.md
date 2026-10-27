# DealRadar (black-friday-rader)

实时比价、降价、库存与蹲点监控系统。设计文档见项目共享文件夹中的 Black Friday Deal Radar Development Document v1.0。

## 模块与分支

每个模块独立分支、独立测试、独立 PR：

| 模块 | 内容 |
|---|---|
| A | 数据模型与基础（用户、商品、Offer、历史价格、Watchlist） |
| B | 零售商适配框架、库存状态归一、价格标准化与校验 |
| C | JB Hi-Fi 连接器 |
| D | 扫描调度与任务队列 |
| E | 告警引擎与 Telegram 通知 |
| F | HTTP API、Celery 接线、扫描分发（可插拔零售商注册表） |
| G1–G4 | Officeworks / Good Guys / Harvey Norman / Amazon AU 连接器 |
| H / I | 商品匹配与人工复核；Deal Score 与假折扣识别 |
| J | WebSocket 实时推送 `/ws?token=…&topics=…`（price.updated / stock.updated / deal.created / alert.triggered / scanner.status）；worker 经 Redis pub/sub 推给各 API 进程 |
| K | 管理后台 `/admin/*`（管理员角色、零售商健康、队列/worker、失败任务、可疑价格、匹配复核确认/驳回）；用 `python -m dealradar.cli make-admin 邮箱` 授予管理员 |
| L | 监控 `/metrics`（Prometheus 文本格式，管理员 token 抓取：API 延迟/错误/WS 连接数，扫描成功率、解析失败、HTTP 错误、验证码，价格变动、告警）与 JSON 结构化日志（`DEALRADAR_LOG_LEVEL`） |
| M | 前端 `web/`（Next.js）：Dashboard、Watchlist、商品详情与价格图、Deals、War Room、Settings；`DEALRADAR_CORS_ORIGINS`、`/scanner/status`、`python -m dealradar.cli migrate` |
| N | 部署：`Dockerfile`、`web/Dockerfile`、`docker-compose.yml`（frontend / api / worker / scheduler / postgres / redis）、`.env.example` |

## 部署（Docker）

```bash
cp .env.example .env          # 填 POSTGRES_PASSWORD、DEALRADAR_SECRET_KEY，以及对外的 PUBLIC_API_URL / DEALRADAR_CORS_ORIGINS
docker compose up --build     # 前端 :3000，API :8000
# 在网页注册后，把自己设为管理员：
docker compose exec api python -m dealradar.cli make-admin 你的邮箱
```

`init` 服务每次启动会执行一次 `python -m dealradar.cli migrate`（Alembic 迁移到最新，已是最新则不做事；以前用 `init-db` 建的库会先自动识别并 stamp，再补齐缺的迁移）。`PUBLIC_API_URL` 在构建前端镜像时写入，浏览器直接访问它，所以要改地址需重新 `docker compose build frontend`。

### HTTPS（Caddy 反向代理）

需要两个指向本机的域名（前端一个、API 一个），开放 80/443。在 `.env` 里设 `APP_DOMAIN`、`API_DOMAIN`，并把 `PUBLIC_API_URL`、`DEALRADAR_CORS_ORIGINS` 改成 `https://` 地址，然后：

```bash
docker compose build frontend
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```

Caddy 自动申请和续期 Let's Encrypt 证书，WebSocket 无需额外配置；3000/8000 端口不再对外开放。

### Black Friday 模式

`DEALRADAR_EVENT_MODE=BLACK_FRIDAY`：扫描间隔减半，`deal.created` 推送阈值从 85 提到 90（全场打折时只推最强的）。阈值可用 `DEALRADAR_DEAL_MIN_SCORE`、`DEALRADAR_BLACK_FRIDAY_DEAL_MIN_SCORE` 调整。文档没给具体规则，这是假设值。

## 运行（不用 Docker）

```bash
python -m dealradar.cli migrate                  # 建表/升级到最新迁移（每次部署先跑）
uvicorn dealradar.main:app                       # API
celery -A dealradar.scanning.tasks worker -Q scan.high,scan.normal,scan.low,notification,maintenance
celery -A dealradar.scanning.tasks beat           # 每 15 秒分发到期扫描
```

环境变量均以 `DEALRADAR_` 为前缀（`DATABASE_URL`、`REDIS_URL`、`SECRET_KEY`、`TELEGRAM_BOT_TOKEN`、`EVENT_MODE`）。
Amazon AU 走官方 Product Advertising API（不抓网页），只有配置了 `DEALRADAR_AMAZON_PAAPI_ACCESS_KEY`、`DEALRADAR_AMAZON_PAAPI_SECRET_KEY`、`DEALRADAR_AMAZON_PAAPI_PARTNER_TAG`（Amazon Associates 账号）才会启用。
新增零售商：实现 `RetailerAdapter`，并在 `dealradar/retailers/builtin.py` 注册一行。

## 开发

```bash
pip install -e '.[dev]'
pytest
```

默认用 SQLite。要在真实 PostgreSQL / Redis 上跑同一套测试：

```bash
DEALRADAR_TEST_DATABASE_URL=postgresql+asyncpg://user@localhost:5432/dealradar_test \
DEALRADAR_TEST_REDIS_URL=redis://localhost:6379/15 pytest   # 每个测试前会重建表，Redis 库会被清空，请用专门的库
```

改了 `dealradar/models/` 之后要加迁移（`tests/test_migrations.py` 会检查迁移与模型是否一致）：

```bash
DEALRADAR_DATABASE_URL=postgresql+asyncpg://user@localhost:5432/dealradar_dev \
  alembic revision --autogenerate --rev-id 0003_short_name -m "说明"   # 生成到 dealradar/migrations/versions/，提交前检查一遍
```

## 注意

`retailers/jbhifi/fixtures/` 目前是按 schema.org Product JSON-LD 手写的合成样本，不是从 jbhifi.com.au 抓取的真实页面。上线前需用真实页面保存 fixture 校准解析器。
