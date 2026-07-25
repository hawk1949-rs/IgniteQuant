# IgniteQuant 项目能力与数据说明

> **面向**：了解「现在能干什么、有哪些数据」的使用者 / 协作者。  
> **仓库**：https://github.com/hawk1949-rs/IgniteQuant  
> **定位**：家庭量化作坊 —— 以天勤 `tqsdk` 做期货策略实验，主策略 Falcon v2（沪金），配套回测看板、模拟盘、研究工具与 Agent Skills。  
> **日期**：2026-07-18（与当前代码对齐）。  
> **相关文档**：开发约定见根目录 `Ruler.md`；架构审阅见 `docs/ARCHITECTURE.md`；分阶段交付见 `docs/falcon_phase*_delivery.md`。

---

## 1. 一句话概括

本项目已经具备：**沪金 Falcon 策略的决策核 → 回测 / 快期模拟 → 异步看板打分 → 本地持久化与对账 → 参数研究档案**。  
生产默认参数仍是 `falcon_legacy_v1`；银河实盘与 VWAP 看板尚未产品化。

```text
研究层（Skills / MCP / 标定工具）
        ↓ 不进交易热路径
作坊层（React :5173 ↔ FastAPI :8787 / Streamlit :8501）
        ↓
执行层（tqsdk：TqSim 回测 / TqKq 模拟；**或** 本地缓存 + LocalSim 离线回放）
        ↓
决策核（FalconDecisionPipeline + RiskEngine + TargetPositionExecutor / LocalSim）
```

---

## 2. 功能能力清单

### 2.1 策略与交易（核心）

| 能力 | 说明 | 入口 |
| --- | --- | --- |
| Falcon v2 决策核 | 5 分钟 K 线：指标 → 行情状态 → 评分 → 手数 → ATR 止盈止损/冷却 | `strategies/falcon/*` + `src/ignitequant/engine/` |
| CLI 历史回测 | `TqSim` + `TqBacktest`，Web UI `:9876`，可选桌面 Excel 存档 | `python strategies/falcon_au_backtest.py` |
| **本地缓存回测** | 读 `data/market_cache`，换月 + LocalSim；默认看板引擎 | `run_falcon_local` / `tools/download_market_cache.py` |
| 快期模拟盘 | `TqKq` 实时行情 + 模拟撮合；换月/心跳/退出平仓 | `python strategies/falcon_au_sim.py` |
| 统一决策循环 | 回测 / 模拟 / 看板共用 `FalconDecisionPipeline` | Phase 2 |
| 事前风控链 | KillSwitch、对账、网关、数据过期、换月、仓位限制等（SOP5） | `src/ignitequant/risk/` |
| 目标仓位执行 | 包装 `TargetPosTask`，幂等意图、成交确认、换月状态机 | `src/ignitequant/execution/` |
| 参数档案切换 | 默认 legacy；候选 5m 档案需显式 `FALCON_PROFILE` | `configs/falcon/*.json` |

**策略语义（Falcon）**

- 信号合约：`KQ.m@SHFE.au`（主力连续）
- 交易合约：跟随 `quote.underlying_symbol`（真实合约）
- 行情状态：ADX≥25 + MA52 得 `TREND_UP` / `TREND_DOWN`，否则 `RANGE`（震荡不开新仓）
- 信号：`[-3, 3]`（格兰维尔 + 放量 + KDJ）
- 手数：默认扁平 `{1:1, 2:1, 3:1}`（候选档案可改为强度手数）
- 风控：ATR×1.3 止损、×2.3 止盈，触发后冷却 4 根 5m K（legacy）

### 2.2 看板与 API（作坊层）

| 能力 | 说明 | 地址 / 路径 |
| --- | --- | --- |
| React 回测控制台 | 深色科技风 UI；选策略/标的/区间；进度条；档案列表与详情 | http://127.0.0.1:5173 |
| FastAPI | 目录、异步回测 job、跑次 CRUD、Walk-forward 规划 | http://127.0.0.1:8787 |
| Streamlit 备用 | 同能力的浅色备用界面 | http://127.0.0.1:8501 |
| 异步回测 | `POST /api/backtest` 默认入队，不阻塞 HTTP；可轮询进度 | `dashboard/jobs.py` |
| 打分与复盘建议 | 收益/回撤/夏普/边缘/样本量 → 0–100 分 + tips | `dashboard/scoring.py` |
| 笔记 / 删除 | 本地改跑次备注或删除 JSON | API `PATCH` / `DELETE` |

**API 一览**

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/catalog` | 策略、标的、参数档案列表 |
| POST | `/api/backtest` | 提交回测（默认 async；`sync=true` 同步冒烟） |
| GET | `/api/jobs`、`/api/jobs/{id}` | 任务列表 / 进度与结果 |
| POST | `/api/jobs/{id}/cancel` | 取消任务 |
| GET | `/api/runs`、`/api/runs/{id}` | 历史跑次 |
| PATCH | `/api/runs/{id}/notes` | 笔记 |
| DELETE | `/api/runs/{id}` | 删除 |
| POST | `/api/research/walk-forward` | 规划训练/测试窗口（不自动批量回测） |

**看板可选标的**（本地引擎四品种）

- 螺纹 `rb`、沪金 `au`、沪银 `ag`、玻璃 `fg`（见 `dashboard/catalog.py` / `ignitequant.market.symbols`）
- 回测引擎：`local`（默认）/ `tq`（天勤在线对照）

### 2.3 研究与分析

| 能力 | 说明 | 位置 |
| --- | --- | --- |
| 成本模型 | 手续费 / 滑点 / 换月假设（版本化） | `analytics/cost_model.py` |
| PnL 归因 | FIFO 毛利、费用、滑点、多空/行情状态拆分 | `analytics/attribution.py` |
| 成本压力 | fee/slip ×1～×3 情景 | `analytics/stress.py` |
| Walk-forward 窗口 | 训练/测试日期切分 | `analytics/walk_forward.py` |
| 离线参数标定 | 在 Phase 0 fixture 上对比档案，输出门禁结果 | `tools/calibrate_falcon_phase6.py` |
| 上线门禁 | `GoLiveGate`（永不 auto-promote） | `research/calibration.py` |
| Golden Master | 固定 CSV + bar-by-bar 行为冻结测试 | `tests/characterization/` |

### 2.4 运行时安全（模拟盘侧重）

| 能力 | 说明 |
| --- | --- |
| SQLite 持久化 | 决策/风控/意图/成交/状态追加写 + 审计哈希链 |
| 启动对账 | 柜台持仓 vs 本地投影；不一致 → `DEGRADED`，禁止新开 |
| 周期对账 | 模拟盘运行中定期核对 |
| 幂等下单 | `idempotency_key` 防重启重复意图 |
| 状态恢复 | 冷却、入场价、SL/TP 可从库恢复 |

默认库路径：`data/runtime/falcon_au_sim.sqlite`（模拟盘 `ENABLE_PERSISTENCE=True`）。

### 2.5 辅助与周边

| 能力 | 说明 |
| --- | --- |
| 桌面 Excel 存档 | 回测结束后可选导出对账单风格明细 | `common/backtest_archive.py` |
| 天勤连通自检 | `verify_install.py` / `verify_live_login.py` |
| VWAP 示例 | `strategies/vwap_au_backtest.py`（未接看板，stub） |
| Agent Skills | LLMQuant 研究技能、Apple HIG 设计技能、Data MCP | `.agents/skills/` |

---

## 3. 数据资产清单

### 3.1 行情与交易事实（外部 / 运行时）

| 数据 | 来源 | 用途 | 是否落盘到本仓库 |
| --- | --- | --- | --- |
| 5 分钟 K 线（在线） | 天勤行情 / TqBacktest | 决策输入、缓存下载 | 否（在线） |
| 5 分钟 K 线（本地缓存） | `tools/download_market_cache.py` | 离线回放；含 `underlying_symbol`；**写入规则见 `docs/market_cache_rules.md`** | `data/market_cache/**/*.csv`（gitignore） |
| Tick / 盘口 | 天勤（模拟盘） | 成交与心跳展示 | 否 |
| 账户权益 / 持仓 | `TqSim` / `TqKq` / `LocalSimAccount` | 回测指标、对账 | 部分写入 runtime SQLite |
| 成交明细 | `TqSim.trade_log` / LocalSim fills | 笔数、归因、夏普估算 | 回测结果摘要进 JSON；完整 log 不长期存库 |

凭证：本地 `.env`（`TQ_USER` / `TQ_PASS` 等），**禁止提交 Git**。

### 3.2 本地持久化数据

| 路径 | 内容 | 格式 |
| --- | --- | --- |
| `data/backtest_runs/*.json` | 看板每次回测档案：指标、打分、归因、压力、配置哈希、笔记 | JSON |
| `data/market_cache/` | 四品种 5m 连续 K + underlying（本地引擎）；规则：`docs/market_cache_rules.md` | CSV + meta.json |
| `data/runtime/*.sqlite` | 模拟盘策略状态、决策/订单/成交事件、对账与审计链；异步 job 表 | SQLite WAL |
| `data/research/*.json` | Phase 6 离线标定报告 | JSON |
| 桌面 Excel（可选） | 回测对账单（成交 + 信号强度） | `.xlsx` |

**单条回测 JSON 通常包含**

- 区间、初始资金、耗时、交易合约  
- `metrics`：收益率、年化、最大回撤、夏普、胜率、盈亏比、成交笔数、期末权益等  
- `scorecard`：总分 / 等级 / 分项 / 复盘建议  
- `attribution` / `stress` / `cost_model` / `reproducibility`  
- `config_version` / `config_hash` / `entry_mode`

### 3.3 配置与参数数据

| 路径 | 内容 |
| --- | --- |
| `configs/falcon/falcon_legacy_v1.json` | **生产默认**（Golden Master 锚定） |
| `configs/falcon/falcon_5m_sqrt_v1.json` | 候选：周期 √12 缩放 |
| `configs/falcon/falcon_5m_half_v1.json` | 候选：周期约 6× |
| `configs/falcon/falcon_5m_lots_v1.json` | 候选：仅启用强度手数 |
| `src/ignitequant/config/decision.py` | 代码内默认 `DecisionConfig`（与 legacy 档案对齐） |

启用候选：`$env:FALCON_PROFILE='falcon_5m_sqrt_v1'`（仅 CLI 模拟/回测默认读取；看板 runner 默认仍用代码配置）。

### 3.4 测试与基线数据

| 路径 | 内容 |
| --- | --- |
| `tests/fixtures/falcon_phase0/*.csv` | 三段固定 400-bar 5m 行情（趋势上/下、震荡过渡） |
| `tests/golden/falcon_phase0/*.json` | bar-by-bar Golden Master |
| `tests/unit/test_phase*.py` | Phase 1–6 单元测试 |
| `tests/characterization/` | 行为冻结表征测试 |

### 3.5 研究层外部数据（可选）

通过 LLMQuant Data MCP（需 `LLMQUANT_API_KEY`）可查询宏观、股票、加密等**研究数据**，**不进入** Falcon 下单热路径。

---

## 4. 指标与输出能力（回测结果）

看板 / runner 当前可展示或落库的主要指标：

| 指标 | 含义 | 备注 |
| --- | --- | --- |
| 收益率 `ror` | 区间权益变化 | 来自天勤统计或期末推算 |
| 年化 `annual_yield` | 年化收益 | 天勤统计 |
| 最大回撤 `max_drawdown` | 峰值回撤 | 天勤统计 |
| 夏普 `sharpe` | 年化夏普 | 优先用每日权益自算；天勤 `sharpe_ratio` 常为 NaN |
| 胜率 / 盈亏比 | 交易统计 | 天勤统计 |
| 成交笔数 | 调仓/成交次数 | `trade_log` 或事件计数 |
| 期末权益 | 账户余额 | |
| 综合评分 | 0–100 + A–E | `scoring.py` |
| 归因 / 压力 | 费用滑点拆分与情景 | Phase 5 |

---

## 5. 怎么启动（最小集）

```powershell
# 后端 API
uvicorn dashboard.api:app --reload --port 8787

# 前端（另开终端）
cd web
npx vite --host 127.0.0.1 --port 5173
# 浏览器：http://127.0.0.1:5173

# 快期模拟盘（可选）
python strategies/falcon_au_sim.py
# Web UI：http://127.0.0.1:9876

# 测试
python -m pytest tests/characterization tests/unit -q
```

依赖：Python 3.10+、`requirements.txt`、项目根目录 `.env` 中的天勤账号。

---

## 6. 能力边界（当前做不到 / 未完成）

| 项 | 状态 |
| --- | --- |
| 银河期货实盘自动交易 | 未产品化（穿透式白名单等外部条件） |
| VWAP 看板接入 | stub |
| 5m 候选参数生产默认 | **未批准**（研究门禁未过） |
| 多品种组合优化 | 无 |
| 机构级 OMS / 云端调度 | 非目标 |
| 真实部分成交 / 涨跌停撮合引擎 | 仅有研究级成本模型 |
| PostgreSQL 交易库 | 规划在实盘前；现用 SQLite |

---

## 7. 目录速查

| 路径 | 职责 |
| --- | --- |
| `src/ignitequant/` | 领域模型、配置、决策管线、风控、执行、持久化、分析、研究 |
| `strategies/falcon/` | 遗留公式实现（指标/评分/手数/风控） |
| `strategies/falcon_au_*.py` | CLI 回测 / 模拟入口 |
| `dashboard/` | API、runner、打分、job、Streamlit |
| `web/` | React 回测控制台 |
| `configs/falcon/` | 版本化参数档案 |
| `data/` | 跑次 JSON、runtime SQLite、研究报告 |
| `tests/` | Golden Master + 单元测试 |
| `docs/` | 架构与 Phase 交付说明 |
| `Ruler.md` | 日常开发与运维备忘 |

---

## 8. 重构完成度（Phase 0–6）

| Phase | 主题 | 状态 |
| --- | --- | --- |
| 0 | Golden Master 行为冻结 | ✅ |
| 1 | 包 / 领域 / 配置 | ✅ |
| 2 | 统一决策循环 | ✅ |
| 3 | 风控 / 执行 / 状态机 | ✅ |
| 4 | 持久化 / 对账 / 恢复 | ✅ |
| 5 | 归因 / 压力 / 异步看板 | ✅ |
| 6 | 5m 参数研究闭环 | ✅（候选未上线） |

---

*本文描述「当前仓库已具备」的能力与数据；若与代码不一致，以代码与 `Ruler.md` 为准。*
