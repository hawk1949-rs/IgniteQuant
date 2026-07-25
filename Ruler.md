# IgniteQuant 开发指引

## 架构说明书（给 AI / 人工审阅）

- 核心逻辑与边界：`docs/ARCHITECTURE.md`
- **项目能力与数据清单（给人看）**：`docs/PROJECT_CAPABILITIES.md`
- **天勤→本地行情缓存规则（强制）**：`docs/market_cache_rules.md`
- 工业级重构大框架：`docs/falcon2大框架.md`
- 决策链 SOP 补充（因子/信号/仓位/风控）：`docs/falocn2小框架.md`
- Phase 0 行为冻结基线：`docs/falcon_phase0_baseline.md`
- Phase 1 包/领域/配置交付：`docs/falcon_phase1_delivery.md`
- Phase 2 统一决策循环：`docs/falcon_phase2_delivery.md`
- Phase 3 风控/执行/状态机：`docs/falcon_phase3_delivery.md`
- Phase 4 持久化/恢复/对账：`docs/falcon_phase4_delivery.md`
- Phase 5 回测真实性/归因/异步看板：`docs/falcon_phase5_delivery.md`
- Phase 6 5m 参数研究：`docs/falcon_phase6_delivery.md` / `docs/falcon_phase6_research.md`
- 用途：让 AI 审视架构、参数风险与重构优先级；不是逐步操作手册（操作约定仍以本文为准）
- 重构阶段顺序：Phase 0 Golden Master → 1 领域/配置 → 2 统一循环 → 3 风控执行 → 4 持久化对账 → 5 回测/看板 → 6 才重标定 5m 参数
- 当前进度：**Phase 6 研究闭环已完成**（候选档案 + 离线标定 + 上线门禁文档化；**生产默认仍为 `falcon_legacy_v1`**；Golden Master 保持）

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
- 2026-07-20：再次 `git pull --ff-only` 同步远程 `master`（落后 2 commits → 已对齐）
- 2026-07-21：直连 GitHub 失败（Connection reset）；经镜像 `ghfast.top` fetch 后 `merge --ff-only origin/master` 对齐
- 2026-07-21：修复因子页缺 `DeleteOutlined` 白屏；已 `git push origin master` 成功（本次直连可用）
- 当前 HEAD：`9ae1a9e`（Fix Factor panel crash from missing DeleteOutlined import.）

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
  - 5 分钟 K 线收盘才调仓；盘中每 60s 打心跳
  - Phase 4：`ENABLE_PERSISTENCE=True` → `data/runtime/falcon_au_sim.sqlite`（启动对账 + 决策/意图/成交追加写；重启恢复冷却与幂等键）
  - Phase 6：默认 `falcon_legacy_v1`；候选档案见 `configs/falcon/`；显式 `$env:FALCON_PROFILE='falcon_5m_sqrt_v1'` 才启用（研究报告 `docs/falcon_phase6_research.md`）
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

### Supabase PostgreSQL（可选云库，2026-07-20）

- 凭证只写本地 `.env` 的 `DATABASE_URL`（已在 `.gitignore`），**禁止提交 Git / 聊天明文密码**
- 连通性自检：`python tools/verify_supabase.py`（依赖 `psycopg2-binary`）
- **2026-07-20 本机实测**：直连 `db.<ref>.supabase.co:5432` 失败 —— 公司 DNS 搜索域污染主机名，且主机仅有 IPv6、本机 IPv6 不可达
- 推荐改用 Dashboard → Database → **Session pooler** 连接串（`*.pooler.supabase.com:6543`，通常有 IPv4），覆盖 `DATABASE_URL` 后再测
- 当前交易事实源仍是本地 SQLite（`data/runtime/*.sqlite`）；Supabase 仅作可选云端库，尚未替换决策持久化层

## 策略看板（家庭量化作坊）

### 本地行情缓存 + 离线回放（2026-07-18；意图纠偏 2026-07-22）

- **产品意图（用户确认）**：缓存是为了**加速贴近实盘的天勤回测**（`TqSim`+`TqBacktest`），不是另起一套结果可偏离的自研撮合当「正式回测」。
- **现状（对齐中，2026-07-22）**：
  - LocalSim / CostModel 默认 `align_mode=tq_kline`：成交价 = 决策价 ± 1 tick（镜像 TqSim 无 tick 时的合成盘口）；换月不再额外加 2 tick。
  - `engine=tq` 对交易合约调用 `TqSim.set_commission`，手续费与 LocalSim 的 `CostModel` 对齐。
  - **缓存修复**：旧下载器在 `is_changing(datetime)` 时只写入新 K 线开盘 stub（o=h=l=c, vol=0），历史 ATR 塌缩 → 决策与天勤分叉。现改为回写 `iloc[-2]` 完整 OHLC，并在本地回放时对**当前决策 bar** 做开盘 stub（与天勤 datetime-change 语义一致）。
  - **必须重下缓存**：`python tools/download_market_cache.py --symbol KQ.m@SHFE.au --start ...`（其它品种同样）；旧 CSV 不可用。
  - 对照脚本：`python tools/compare_local_tq.py --symbol KQ.m@SHFE.au --start YYYY-MM-DD --end YYYY-MM-DD`
  - 门禁：`within_tolerances`（ror±2%、回撤±2%、期末权益相对差≤3%、成交笔数相对差≤15%）。
  - **2026-07-22 短窗实测**（au `2025-01-02..01-10`，重下缓存后）：**门禁通过** — trades 20=20，期末权益差 100，ror/回撤过关。
  - **仍可能有残差**：权益曲线日内盯市、平今单字段、保证金占用、更长区间 bar 边界；权威对照仍以 `engine=tq` 为准。
- **硬约束**：天勤官方 `TqBacktest` **不支持**用本地 CSV 离线驱动回测（运行时从行情服务器取数）；缓存加速的是「本地对齐撮合预览」，不是「离线天勤时光机」。
- **后续方向**：用对照脚本收敛残差；UI 标注 local 为「TqSim 语义对齐 / 非官方时光机」。
- **默认引擎**：看板 / API 现仍默认 `engine=local`（可选 `tq`）。
- **品种（4）**：螺纹 `rb` / 沪金 `au` / 沪银 `ag` / 玻璃 `fg`
  - 信号：`KQ.m@SHFE.rb` / `KQ.m@SHFE.au` / `KQ.m@SHFE.ag` / `KQ.m@CZCE.FG`
- **缓存目录**：`data/market_cache/<signal>/300.csv`（含 `underlying_symbol` 供换月）
- **下载 / 写入 / 回放规则（强制）**：见 **`docs/market_cache_rules.md`**（回写上一根完整 OHLC + 当前 stub；回放时决策 bar 开盘 stub）
- **下载 CLI**：`python tools/download_market_cache.py --all --start 2023-01-01 --end 2026-07-01`
  - 或 `--status` 查看覆盖；看板 local 缺缓存时可 `auto_download=true` 自动补拉
  - **2026-07-23**：按新规则重下。覆盖（`--status`）：
    - `au`：5818 根（约 2024-10-31 → 2025-01-15，短窗验证区间）
    - `ag`：92101 根；`rb`/`fg`：各 57661 根（约 2022-12-30 → 2026-07-01）
    - flat-stub 占比 ≈ 0（旧全 stub CSV 已作废）
  - **2026-07-23 UI**：工作台「开始测试」已接真实 `/api/backtest`；进度若出现早于所选 start 的日期，是**补拉预热**，回测窗口仍以所选区间为准。
- **回放**：`src/ignitequant/engine/local_replay.py` —— `FalconDecisionPipeline` + `RollStateMachine` + `LocalSimAccount`
- **代码**：`src/ignitequant/market/`；入口 `dashboard/runners.run_falcon_local`；撮合镜像 `src/ignitequant/analytics/tq_match.py`

### 新前端（Magic UI + React，2026-07-17）

- 目录：`web/`（Vite + React + TS + Tailwind v4 + Magic UI 组件）
- 启动后端 API：`uvicorn dashboard.api:app --reload --port 8787` → http://127.0.0.1:8787
- 启动前端：`cd web && npm run dev` → http://127.0.0.1:5173（`/api` 代理到 8787）
- **欢迎首页**（2026-07-20）：深色科技简约门户（Apple Dark Mode 语义色）
  - `#/` → `WelcomePage`；`#/lab` → 策略实验室侧栏：回测看板 / 因子与特征 / 信号发生器 / 仓位控制 / 管理后台
  - 主题：`web/src/theme/AppleAntdProvider.tsx`（高对比：正文 `#F5F5F7`、次要 `#C8D0DC`、实色卡片 `#1A2740`）
  - 扩展方式：在 `StrategyLabPage.tsx` 的 `LabSection` / `LAB_NAV` 追加项；未实现页用 `ComingSoonPanel`
  - **策略装配区**（2026-07-21）：三节点流水线 —— ①因子与特征 → ②信号发生器 → ③仓位控制；已移除独立「开仓策略」节点与侧栏项；旧 localStorage 四节点装配经 `normalizePipelineNodes` 兼容加载
  - **因子与特征页**（2026-07-22）：专注因子编译与挖掘
    - 已移除：因子组合库、纯净数据管道 UI、回测看板因子下拉
    - 因子支持 **归类**（`category`）+ 顶部筛选标签；预设建议：未分类/趋势/波动/动量/量价/跨周期，也可自定义
    - UI：边界说明 + 因子编译（启用/命名/归类/触发周期/编辑器）+ Feature Dict 预览
  - **信号发生器页**（2026-07-22）：`SignalPanel.tsx` + `signal-data.ts`
    - 从因子页已启用模块选题，组成 **做多 / 做空 / 平仓** 三套公式（条件 AND/OR；右侧可为数值或另一因子）
    - 附加条件：confirmation_bars、TTL、多空互斥、平仓优先、备注
    - 持久化：`localStorage` `ignitequant.lab.signal_generator_v1`；本轮仅 UI 契约，未接 Python SignalEngine
  - `#/lab-legacy` → 旧版策略实验室
  - 工作台注意：`persistDb=否` 不写入历史列表；选历史回测会退出当前策略选中防误更新
  - 测试账号：`回测机制`（缓存 / 天勤）+ 开始测试时显示分阶段进度条（当前为演示进度，后续可接 `/api/jobs`）
- 回测进度：异步 job 轮询时显示进度条（`progress` / `progress_msg`）
- 组件：已去掉 BlurFade / NumberTicker / BorderBeam 等动效依赖（源码仍可在 `web/src/components/ui/`）
- API：`dashboard/api.py` v0.6（`/api/catalog` 含 engines/market_cache；`/api/backtest` 支持 `engine=local|tq`）
- 依赖：`fastapi` / `uvicorn` 已写入 `requirements.txt`
- **本地↔天勤指标口径（2026-07-23）**：必须与 `tqsdk.report.TqReport` / `get_sharp` 一致
  - 年化：`(1+ror)^(250/n_settle_days)-1`（禁止用日历日 365.25）
  - 夏普：日收益序列 + 总体标准差 + rf=2.5% + √250（`ignitequant.analytics.tq_metrics`）
  - 权益曲线按**交易日结算**取样（`trading_day_from_timestamp_ns`，夜盘≥18:00 滚次日、周末滚周一）；决策/强制平仓门控仍用**日历日**（与 `dashboard/runners` 天勤路径一致）
  - 实现：`src/ignitequant/analytics/tq_metrics.py`、`src/ignitequant/market/trading_day.py`
  - **缓存覆盖**（2026-07-23）：`coverage_ok` 允许春节等休市缺口——区间内有 bar 且缓存已有 `end` 之后的数据即视为覆盖完整（勿因 1/28–2/4 无 K 线而报 missing coverage）
  - **缓存空洞误判**（2026-07-23）：au 缓存曾缺 2025-03～10，但 11 月仍有数据，旧 `coverage_ok` 把「end 之后任意有 bar」当成完整 → 本地回测静默停在 2/28，与天勤 3 月续跑分叉（例：`baf46e44943c` local vs `7e5a3929cb06` tq）。现要求：窗口内无超长空洞；节假日续跑须在 `end` 后约 20 天内恢复
  - **成交对齐**（2026-07-23）：天勤 `TargetPosTask` 用决策 K 线 open±tick 钉住限价（禁止追 1 分钟隐式行情）；本地日终盯市用 bar close；`settle_day > end` 的夜盘不计入。短窗验证：期末权益/收益率/回撤/夏普/年化与天勤一致
  - **GFD 日终错单**（2026-07-23）：硬钉限价若始终无法穿越盘口，TqSim 日终撤 GFD，`TargetPosTask` 抛「遇到错单…交易日结束…」。修复：`align_limit_price` 在 pin 不可成交时抬到 ask/bid；runner / `falcon_au_backtest` 捕获该类异常后 `recover_after_gfd_cancel` 重建任务

### Streamlit 备用入口

- `streamlit run dashboard/app.py --server.port 8501` → http://127.0.0.1:8501
- UI：浅色 HIG 取向（`.streamlit/config.toml` + `dashboard/app.py`）；主色 `#0071e3`；隐藏 Deploy 壳
- 能力：选策略（Falcon v2）/ 多选标的（沪金·银·铜）→ 无 GUI 批量回测 → 自动打分与复盘建议 → 本地 JSON 对比
- 结果目录：`data/backtest_runs/*.json`
- 引擎：`dashboard/runners.py`（`web_gui=False`；Phase 5 附带 attribution / stress / reproducibility）
- 打分：`dashboard/scoring.py`（收益/回撤/夏普/边缘/样本量 → 0–100）
- Phase 5 异步：`POST /api/backtest` 默认入队（`dashboard/jobs.py` → `data/runtime/backtest_jobs.sqlite`）；前端轮询 `/api/jobs/{id}`；短冒烟可 `sync=true`

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
  - K 线周期：`KLINE_SECONDS = 60 * 5`（5 分钟；回测 / 模拟盘 / 看板 runner 一致）
  - 回测账户：`INIT_BALANCE = 1_000_000`（100 万；见 `falcon_au_backtest.py`）
  - 手数映射：`{1:1, 2:1, 3:1}`（可用 `LOT_SCALE` 再缩放；约 100 万账户峰值风险度 ~4%；仅趋势同向开仓）
  - 风控：ATR(14)×1.3 止损、×2.3 止盈，触发后冷却 4 根 K
  - 信号合约：`KQ.m@SHFE.au`（主力连续）；区间：`2025-01-01` ~ `2025-02-28`（按需改 `START_DT`/`END_DT`）
  - 交易合约：跟随 `quote.underlying_symbol`（TqSim **不能**对 `KQ.m@` 下单；换月时先平旧仓再切 TargetPosTask）
  - Web UI：http://127.0.0.1:9876
  - 期末强制平仓：自 `FLAT_DATE`（结束日前最后一个交易日）起，按 `position.pos` 持续 `set_target_volume(0)` 直至净仓为 0
  - 回测结束后继续 `wait_update()` 保活 UI
  - 运行：`python strategies/falcon_au_backtest.py`
  - 5 分钟 K 线回测比 1H 更密，同区间耗时更长；日志出现「推进」即在正常推进

## MetaTrader 5 手工下单看板（2026-07-18）

- 源码：`tools/mt5/实盘下单工具看板.mq5`
- 已编译：`tools/mt5/实盘下单工具看板.ex5`（同步到本机 MT5 Experts）
- 安装路径：`%APPDATA%\MetaQuotes\Terminal\E6E3D0917DD641581E4779524EB3B1AA\MQL5\Experts\`
- 功能：一键平仓/减仓50%·80%/平多空/平盈亏/一键保本(+偏移点)/删挂单/挂多挂空(+止损止盈点数)/点差与浮盈刷新
- 使用：图表拖入 EA → 开启算法交易 → 允许自动交易；先在模拟盘验证
- 重编译：`MetaEditor64.exe /compile:"...Experts\实盘下单工具看板.mq5" /include:"...MQL5" /log`
