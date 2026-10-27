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

## 开发

```bash
pip install -e '.[dev]'
pytest
```

## 注意

`retailers/jbhifi/fixtures/` 目前是按 schema.org Product JSON-LD 手写的合成样本，不是从 jbhifi.com.au 抓取的真实页面。上线前需用真实页面保存 fixture 校准解析器。
