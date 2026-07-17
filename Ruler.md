# IgniteQuant 开发指引

## 外部资料

- Apple Design Skill（同步于 2026-07-17）：`apple-design-skill/` ← https://github.com/dickwu/apple-design-skill
  - Agent Skill：`.agents/skills/apple-design`（含 53 份 HIG 参考）
  - Cursor Rule：`.cursor/rules/apple-design.mdc`（UI 相关文件触发）
  - 用途：跨平台 UI/UX 审查（Flutter / RN / Electron / Tauri / Web）

- LLMQuant Skills（同步于 2026-07-17）：`LLMQuant-skills/` ← https://github.com/LLMQuant/skills
  - 18 个大类已安装到项目：`.agents/skills/llmquant-*`（`npx skills add ./LLMQuant-skills -a cursor`）
  - 商品相关：`llmquant-commodities`；系统化策略手册：`llmquant-strategies/workflows/quant.md`
- LLMQuant Data MCP（Skills 数据层）
  - **全局配置**（Cursor Settings 主要读这个）：`C:\Users\Administrator\.cursor\mcp.json`
  - 项目配置：`.cursor/mcp.json`（同样指向启动脚本）
  - 启动脚本：`.cursor/run-llmquant-mcp.cjs`（从项目 `.env` 读 `LLMQUANT_API_KEY`）
  - 申请 key：https://llmquantdata.com → Dashboard → API Keys
  - 包：`npx -y @llmquant/data-mcp`
  - 若 Settings → MCP 里看不到：确认打开的是全局 mcp.json；改完后 **Reload Window** 或重启 Cursor
  - 2026-07-17：已写入全局 mcp.json；此前仅项目级配置，Windows 上 Settings 页常不显示

- Magic UI MCP（2026-07-17）：`pnpm` 未安装，改用 `npx -y @magicuidesign/cli@latest install cursor`
  - 已写入全局 `C:\Users\Administrator\.cursor\mcp.json` → `@magicuidesign/mcp`
  - 需重启 Cursor 后在 Settings → MCP 中可见

## GitHub

- 个人仓库：https://github.com/hawk1949-rs/IgniteQuant
- 账号：`hawk1949-rs`
- 可见性：Public
- 本地目录：`D:\Cursor\IGNITE\AIQuant`，远程 `origin` → `https://github.com/hawk1949-rs/IgniteQuant.git`
- 默认分支：`master`
- 2026-07-17：已从远程同步到本地（直连 `git clone` 易超时/重置；可用镜像 `https://ghfast.top/https://github.com/hawk1949-rs/IgniteQuant.git`）
- 当前 HEAD：`792a995`（Upgrade Falcon to v2 with archive export and larger sizing.）

## Python / 依赖

- Python：`3.10.11`
- 天勤量化框架：`tqsdk`（清华镜像安装）
  - 安装命令：`pip install tqsdk -U -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host=pypi.tuna.tsinghua.edu.cn`
  - 或：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host=pypi.tuna.tsinghua.edu.cn`
- 依赖清单：`requirements.txt`
- 安装连通性校验脚本：`verify_install.py`
  - 凭证放在本地 `.env`（已在 `.gitignore`，仓库为 Public，禁止把密码写进代码）
  - 可参考 `.env.example`
  - 运行：`python verify_install.py`
  - 默认订阅 `SHFE.ni2607`，最多打印 5 次行情；可用 `TQ_SYMBOL`、`TQ_VERIFY_UPDATES`、`TQ_VERIFY_TIMEOUT` 调整
  - 本地 `.env` 已放账户信息；提交前确认未被 `git add`（依赖 `.gitignore`）

## 期货公司对接

### 模拟盘 vs 实盘（天勤账户类型）

| 类型 | 类 | 用途 | 当前状态 |
| --- | --- | --- | --- |
| 本地模拟 | `TqSim(init_balance=...)` | 回测 / 本地试跑，不落快期客户端 | Falcon 回测在用，`INIT_BALANCE=100万` |
| 快期模拟盘 | `TqKq()` | 实时行情 + 模拟撮合，账户在快期侧 | **2026-07-17 已验证可用**：`hawk1949` 登录成功，权益 100 万；沪金主力 `KQ.m@SHFE.au` → `SHFE.au2608` |
| 期货公司实盘 | `TqAccount("Y银河期货", ...)` | 真实下单 | `.env` 里 `TQ_FUTURE_ACCOUNT` / `TQ_FUTURE_PASSWORD` **尚未填写**；且需穿透式白名单 |

- Falcon 回测：`strategies/falcon_au_backtest.py`（`TqSim` + `TqBacktest`）
- Falcon 快期模拟盘：`strategies/falcon_au_sim.py`（`TqKq`，实时；`python strategies/falcon_au_sim.py`）
  - Web UI：http://127.0.0.1:9876；Ctrl+C 退出（默认退出前目标仓位归零）
  - 1H K 线收盘才调仓；盘中每 60s 打心跳
  - 策略说明文档（桌面）：`Falcon_v2_沪金策略说明.md`（信号/下单/持仓/风控）
- 推荐路径：先用 **`TqKq` 快期模拟盘**；银河实盘等账号写入 `.env` + 销售开通白名单后再切 `TqAccount`

### 银河期货（当前主推实盘渠道）

- 状态：资金账号已开好；席位 **CTP主席**；凭证只写本地 `.env`（`TQ_BROKER` / `TQ_FUTURE_ACCOUNT` / `TQ_FUTURE_PASSWORD`），**禁止提交 Git**
- 天勤公司名（中继）：`Y银河期货`（主席）；若登录异常再问销售是否要换七席/三席名
- 2026-07-15 登录自检：连上 `kqzj.yhqh.com.cn` 后提示需期货公司做**穿透式认证/白名单**，否则 TqSdk 无法完成实盘登录（非密码错误）
- 待销售处理：把资金账号加入天勤中继白名单，并绑定 AppID `SHINNY_TQ_1.0`
- 走天勤中继填表常用值：外接系统天勤量化（TqSdk），对接 CTP，终端类型中继（多对多），归属信易科技
- 登录自检（只查资金、不下单）：`python verify_live_login.py`
- 代码形态：

```python
api = TqApi(
    TqAccount("Y银河期货", os.environ["TQ_FUTURE_ACCOUNT"], os.environ["TQ_FUTURE_PASSWORD"]),
    auth=TqAuth(os.environ["TQ_USER"], os.environ["TQ_PASS"]),
)
```

### 安粮期货（早期资料，非当前主渠道）

- 本地「安粮期货」协议文件已移除（含实名填表信息，不再入库）
- 中继写法：`TqAccount("A安粮期货", ...)`；AppID：`SHINNY_TQ_1.0`
- 安粮在天勤「专业版可用」列表

## 策略看板（家庭量化作坊）

### 新前端（Magic UI + React，2026-07-17）

- 目录：`web/`（Vite + React + TS + Tailwind v4 + Magic UI 组件）
- 启动后端 API：`uvicorn dashboard.api:app --reload --port 8787` → http://127.0.0.1:8787
- 启动前端：`cd web && npm run dev` → http://127.0.0.1:5173（`/api` 代理到 8787）
- 主色：`#0071e3`（浅色；避免 Magic 默认紫粉）；字体 Fraunces + DM Sans
- 组件：`blur-fade` / `number-ticker` / `magic-card` / `border-beam`（源码在 `web/src/components/ui/`）
- API：`dashboard/api.py`（`/api/catalog` `/api/runs` `/api/backtest` 笔记/删除）
- 依赖：`fastapi` / `uvicorn` 已写入 `requirements.txt`

### Streamlit 备用入口

- `streamlit run dashboard/app.py --server.port 8501` → http://127.0.0.1:8501
- UI：浅色 HIG 取向（`.streamlit/config.toml` + `dashboard/app.py`）；主色 `#0071e3`；隐藏 Deploy 壳
- 能力：选策略（Falcon v2）/ 多选标的（沪金·银·铜）→ 无 GUI 批量回测 → 自动打分与复盘建议 → 本地 JSON 对比
- 结果目录：`data/backtest_runs/*.json`
- 引擎：`dashboard/runners.py`（`web_gui=False`）
- 打分：`dashboard/scoring.py`（收益/回撤/夏普/边缘/样本量 → 0–100）

## 策略回测

### 回测存档（可插拔）

- 模块：`common/backtest_archive.py`（`BacktestArchive`）
- 用途：回测结束后在**桌面**生成 Excel（对账单风格成交明细 + 信号强度）
- **非强制**：策略按需 `import`；未接入则不影响回测
- 概要页：策略名称、品种/合约、回测启动时间、区间、成交笔数、初始/期末资金、累计平仓盈亏与手续费等
- 说明：`get_account()` 的平仓盈亏/手续费是**当日截面**；累计值从 `TqSim.trade_log` / `tqsdk_stat` 汇总（接入时传 `sim_account=` + `init_balance=`）
- 明细「平仓盈亏」：天勤 `Trade` 无该字段，存档模块按开平 **FIFO + 合约乘数** 回算
- 概要保证金：同时写 **期末 / 峰值 / 占用日均**（期末空仓时峰值为准）
- 明细页：成交时间/合约/买卖/开平/手数/成交价/手续费/平仓盈亏/**信号强度**/行情状态/备注
- 接入要点：下单前 `tag_next(signal_strength=...)`；每轮 `poll(api)`；结束 `save(api)`
- Falcon 示例开关：`strategies/falcon_au_backtest.py` 中 `ENABLE_ARCHIVE = True`
- 依赖：`openpyxl`（已写入 `requirements.txt`）
- 默认文件名：`回测_{策略}_{品种}_{启动时间}.xlsx`；可用 `save_dir=` / `save(path=...)` 改路径

### 回测 Web UI 固定地址（全局约定）

- 所有带界面的回测统一固定：`web_gui=":9876"`
- 浏览器访问域名/地址固定为：**http://127.0.0.1:9876**
- 不要用 `web_gui=True`（会随机端口，地址不稳定）
- 若 9876 被占用：先结束旧回测进程，再启动新回测
- web_gui 常停在「最后一笔成交」：无新信号时图表不再跳动，属正常
- 回测结束后必须继续 `api.wait_update()` 保活 UI，**禁止**只用 `time.sleep`（会阻塞事件循环，导致页面 Listen 但 HTTP 超时僵死）

### 现有策略

- 沪金 VWAP：`strategies/vwap_au_backtest.py`
  - 合约默认 `SHFE.au2606`，区间 `2026-01-01` ~ `2026-05-31`
  - Web UI：http://127.0.0.1:9876
  - 凭证读 `.env`；运行：`python strategies/vwap_au_backtest.py`
- Falcon v2：`strategies/falcon_au_backtest.py` + 包 `strategies/falcon/`
  - 模块：`indicators` / `regime` / `score` / `sizing` / `risk`
  - 行情状态：ADX(14)≥25 为趋势，结合 MA52 得 `TREND_UP`/`TREND_DOWN`，否则 `RANGE`（震荡不开新仓）
  - 信号：`[-3,3]`，分项=格兰维尔 + 放量 + KDJ（冲突降权）
  - 回测账户：`INIT_BALANCE = 1_000_000`（100 万；见 `falcon_au_backtest.py`）
  - 手数映射：`{1:1, 2:1, 3:1}`（可用 `LOT_SCALE` 再缩放；约 100 万账户峰值风险度 ~4%；仅趋势同向开仓）
  - 风控：ATR(14)×1.3 止损、×2.3 止盈，触发后冷却 4 根 K
  - 信号合约：`KQ.m@SHFE.au`（主力连续）；区间：`2025-01-01` ~ `2025-02-28`（按需改 `START_DT`/`END_DT`）
  - 交易合约：跟随 `quote.underlying_symbol`（TqSim **不能**对 `KQ.m@` 下单；换月时先平旧仓再切 TargetPosTask）
  - Web UI：http://127.0.0.1:9876
  - 期末强制平仓：自 `FLAT_DATE`（结束日前最后一个交易日）起，按 `position.pos` 持续 `set_target_volume(0)` 直至净仓为 0
  - 回测结束后继续 `wait_update()` 保活 UI
  - 运行：`python strategies/falcon_au_backtest.py`
  - 约 18 个月 1H K 线，跑完可能需数分钟到十几分钟；日志出现「推进」即在正常推进
