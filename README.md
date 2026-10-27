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

## 运行

```bash
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

## 注意

`retailers/jbhifi/fixtures/` 目前是按 schema.org Product JSON-LD 手写的合成样本，不是从 jbhifi.com.au 抓取的真实页面。上线前需用真实页面保存 fixture 校准解析器。
