# IgniteQuant Agent Instructions

> 本文件供 Cursor Agents、Codex Agents 和人工开发者共同使用。  
> 目标：在不改变现有 Falcon 交易行为的前提下，分阶段实现工业级的因子、信号、目标仓位和风控决策链。  
> 适用范围：`strategies/falcon/`、相关 runner、测试、配置和新建的 `src/ignitequant/`。  
> 默认环境：回测或快期模拟。未经用户明确授权，禁止连接真实账户或发送真实委托。

---

## 1. Agent 必须遵守的工作方式

### 1.1 开始修改前

Agent MUST：

1. 阅读本文件、项目架构说明、`Ruler.md` 和本次涉及的源码；
2. 执行 `git status`，不得覆盖、删除或回滚用户已有修改；
3. 查明仓库现有 Python 版本、依赖管理、测试、lint 和启动命令，不得凭空假设；
4. 输出本次任务的目标、非目标、涉及路径、行为不变量、实施步骤和验证方式；
5. 先为当前实现建立 characterization tests / golden master，再调整结构；
6. 如果源码行为与本文描述冲突，暂停相关修改并报告冲突、证据和建议解释。

### 1.2 修改过程中

- MUST 小步提交可验证的闭环，不得一次性重写整个项目；
- MUST 将架构迁移与策略参数优化分开；
- MUST 保留旧入口的兼容适配器，直到新旧结果通过 Golden Master；
- MUST 让回测、模拟和未来实盘调用同一个决策核；
- MUST 保持 `Factor → Signal → Target → Risk` 单向依赖；
- MUST 使用已完成K线，禁止未来函数；
- MUST 明确区分 `HOLD` 和 `FLAT`；
- MUST 以真实成交更新入场状态，不能以发单或目标仓位代替成交；
- MUST 保留每次决策的原因码和版本；
- MUST 默认 fail closed：异常时禁止新增风险，但保留撤单、减仓和平仓能力；
- MUST 不把 tqsdk 对象传入核心策略模块；
- MUST 不提交 `.env`、账号、密码、Token 或真实账户信息。

### 1.3 禁止事项

Agent MUST NOT：

- 同时迁移目录、改变指标公式、修改参数并重写执行逻辑；
- 直接删除旧 Falcon 实现后再尝试复现行为；
- 在因子、信号、仓位或风控模块中调用 tqsdk 下单接口；
- 在 `except Exception` 中静默吞掉交易异常；
- 用日志代替订单、成交、风险决策和策略状态的持久化；
- 把目标仓位归零视为实际仓位已经归零；
- 在订单状态未知时盲目重发；
- 为当前单人5分钟系统引入不必要的微服务、Kafka 或 Kubernetes；
- 未经明确授权修改 Golden Master 以迁就新结果。

---

## 2. 本轮重构目标

本轮只建设以下四个决策模块及其编排：

```text
FactorEngine
  → SignalEngine
  → PositionSizer
  → RiskEngine
  → approved target（交给既有执行层或后续 ExecutionEngine）
```

### 2.1 非目标

本轮不负责：

- 证明策略盈利；
- 自动搜索最佳参数；
- 改造完整数据库中台；
- 重写前端；
- 建设多账户或高频系统；
- 直接上线真实交易；
- 在没有样本外验证时启用新的退出逻辑或风险手数。

### 2.2 当前行为不变量

结构重构阶段必须保持：

1. 信号行情来自 `KQ.m@SHFE.au`；
2. 交易合约来自当时有效的 `underlying_symbol`；
3. 普通决策只在完整5分钟K线到达后运行；
4. 当前 MA7/14/52、ATR14、ADX14、KDJ 9/3/3 和量 MA20 公式不变；
5. 当前 `signal ∈ [-3,3]` 和 `LOT_BY_SIGNAL` 行为先通过兼容层保留；
6. 当前 `None` 等价于 `HOLD`，`0` 等价于明确 `FLAT`；
7. RANGE 当前不主动建立新仓；
8. 架构迁移阶段不得顺手启用本文件中的候选新参数。

---

## 3. 目标包结构

Agent 应分阶段创建以下结构，不要求一次完成全部文件：

```text
src/ignitequant/
├── domain/
│   ├── enums.py
│   ├── models.py
│   └── events.py
├── config/
│   └── decision.py
├── strategies/
│   └── falcon/
│       ├── factor_engine.py
│       ├── regime.py
│       ├── signal_engine.py
│       └── legacy_adapter.py
├── portfolio/
│   ├── stop_planner.py
│   ├── sizing.py
│   └── aggregator.py
├── risk/
│   ├── rules.py
│   ├── pretrade.py
│   ├── operational.py
│   └── engine.py
└── engine/
    └── decision_pipeline.py

tests/
├── characterization/
├── unit/factors/
├── unit/signals/
├── unit/portfolio/
├── unit/risk/
└── integration/
```

若仓库尚未采用 `src` layout，Agent 必须先检查 `pyproject.toml` 或现有打包方式。迁移期间允许：

```text
旧 strategies/falcon/*.py
        ↓ thin adapter
新 src/ignitequant/*
```

旧入口只能变成薄适配器，不得保留第二套独立决策逻辑。

### 3.1 依赖方向

```text
decision_pipeline
  ├── factor_engine
  ├── signal_engine
  ├── position_sizer
  └── risk_engine

上述模块 → domain models / config
tqsdk adapter → domain models
```

禁止反向依赖：

- `domain` 不依赖 pandas、tqsdk、FastAPI；
- `factor_engine` 不依赖账户、持仓、订单；
- `signal_engine` 不依赖 tqsdk、执行器；
- `position_sizer` 不调用风控或下单；
- `risk_engine` 不调用下单；
- `decision_pipeline` 只编排，不重复实现公式。

---

## 4. 第一阶段：冻结当前行为

Agent 在创建新算法前，先建立 Golden Master。

### 4.1 固定测试数据

准备至少三段脱敏历史K线：

1. 明显上涨趋势；
2. 明显下跌趋势；
3. 横盘和趋势切换。

每段至少400根5分钟K线，并保存：

- K线输入哈希；
- 每根K线的指标；
- regime；
- 旧 `ScoreDetail`；
- 旧目标手数；
- 止损、止盈和冷却事件。

### 4.2 Characterization tests

必须覆盖：

- 指标在相同输入下确定性一致；
- 新旧 MA、ATR、ADX、KDJ 数值在允许误差内一致；
- 新旧 regime 一致；
- 新旧 `signal [-3,3]` 一致；
- 新旧 `None / 0 / int` 仓位语义一致；
- 回测、模拟 runner 对同一bar调用同一个新决策入口。

允许的浮点误差必须显式定义，禁止使用过宽的 `pytest.approx` 掩盖差异。

### 4.3 阶段退出条件

在 Golden Master 建立前，不得开始更改因子公式、评分权重、手数模型或风控参数。

---

## 5. 统一领域对象

优先使用冻结 `dataclass`。如果仓库已经统一使用 Pydantic，可采用严格 Pydantic model，但核心对象应避免运行中被原地修改。

### 5.1 枚举

在 `domain/enums.py` 中实现：

```python
from enum import Enum


class FactorQuality(str, Enum):
    READY = "READY"
    WARMING_UP = "WARMING_UP"
    STALE = "STALE"
    MISSING_DATA = "MISSING_DATA"
    INVALID_VALUE = "INVALID_VALUE"


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"


class SignalAction(str, Enum):
    HOLD = "HOLD"
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    REDUCE_LONG = "REDUCE_LONG"
    REDUCE_SHORT = "REDUCE_SHORT"
    EXIT = "EXIT"


class RiskAction(str, Enum):
    PASS = "PASS"
    RESIZE = "RESIZE"
    REJECT = "REJECT"
    HALT = "HALT"
```

### 5.2 核心对象

在 `domain/models.py` 或 `domain/events.py` 中实现等价对象。字段允许根据当前源码补充，但不得删除审计必需字段。

```python
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class BarSnapshot:
    bar_id: str
    symbol: str
    trading_day: date
    start_at: datetime
    end_at: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_oi: int
    close_oi: int
    is_final: bool


@dataclass(frozen=True)
class FactorSnapshot:
    factor_snapshot_id: str
    symbol: str
    bar_id: str
    data_as_of: datetime
    values: Mapping[str, float]
    regime: Regime
    quality: FactorQuality
    factor_version: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SignalEvent:
    signal_id: str
    factor_snapshot_id: str
    action: SignalAction
    direction: int
    alpha: float
    strength: float
    confidence: float
    generated_at: datetime
    effective_from: datetime
    expires_at: datetime
    confirmation_bars: int
    reason_codes: tuple[str, ...]
    model_version: str


@dataclass(frozen=True)
class TargetPosition:
    target_id: str
    signal_id: str
    symbol: str
    current_position: int
    desired_position: int
    delta: int
    planned_entry_price: float | None
    planned_stop_price: float | None
    stop_distance: float | None
    risk_per_lot: Decimal | None
    requested_risk: Decimal
    sizing_method: str
    reason_codes: tuple[str, ...]
    config_version: str


@dataclass(frozen=True)
class RiskDecision:
    risk_decision_id: str
    target_id: str
    action: RiskAction
    requested_position: int
    approved_position: int
    requested_risk: Decimal
    approved_risk: Decimal
    rule_hits: tuple[str, ...]
    warnings: tuple[str, ...]
    evaluated_at: datetime
    risk_config_version: str
    risk_snapshot_id: str
```

### 5.3 支撑快照

以下对象可以拆分到 `domain/models.py`，字段名允许适配项目惯例，但语义必须保持：

```python
@dataclass(frozen=True)
class ContractSnapshot:
    symbol: str
    exchange_id: str
    product_id: str
    multiplier: Decimal
    price_tick: Decimal
    margin_rate: Decimal
    open_fee: Decimal
    close_fee: Decimal
    close_today_fee: Decimal
    upper_limit: Decimal | None
    lower_limit: Decimal | None
    expire_at: datetime
    valid_at: datetime


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    net_position: int
    long_today: int
    long_yesterday: int
    short_today: int
    short_yesterday: int
    average_entry_price: Decimal | None
    unrealized_pnl: Decimal
    as_of: datetime


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    equity: Decimal
    available: Decimal
    margin: Decimal
    margin_ratio: Decimal
    realized_pnl_today: Decimal
    unrealized_pnl: Decimal
    strategy_drawdown_pct: Decimal
    as_of: datetime


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    last_price: Decimal
    bid_price_1: Decimal | None
    ask_price_1: Decimal | None
    bid_volume_1: int
    ask_volume_1: int
    spread_ticks: Decimal | None
    latest_bar_volume: int
    trade_status: str
    is_upper_limit_locked: bool
    is_lower_limit_locked: bool
    data_age_seconds: float
    as_of: datetime


@dataclass(frozen=True)
class PortfolioSnapshot:
    total_open_risk: Decimal
    symbol_open_risk: Decimal
    gross_exposure: Decimal
    margin_after_pending_orders: Decimal
    pending_order_count: int
    as_of: datetime


@dataclass(frozen=True)
class RuntimeSnapshot:
    runtime_state: str
    reconciliation_matched: bool
    unknown_order_count: int
    persistence_healthy: bool
    market_gateway_healthy: bool
    trade_gateway_healthy: bool
    kill_switch_active: bool
    as_of: datetime
```

`DecisionContext` 至少组合：bars、previous_regime、signal_state、market、contract、position、account、portfolio、runtime和now。Runner负责从tqsdk对象构建这些快照，核心Pipeline不得自行查询外部状态。

### 5.4 标识符

ID 必须在事件创建时生成并保持稳定。测试中使用确定性 ID factory；生产可采用 UUID/ULID。不得在序列化时重新生成ID。

---

## 6. SOP 2：FactorEngine

### 6.1 公开接口

在 `strategies/falcon/factor_engine.py` 中提供：

```python
class FactorEngine:
    def compute(
        self,
        bars: tuple[BarSnapshot, ...],
        previous_regime: Regime | None,
    ) -> FactorSnapshot:
        ...
```

核心逻辑不得读取账户、环境变量、数据库或 tqsdk 对象。

### 6.2 输入门禁

按顺序验证：

1. 所有bar均为 `is_final=True`；
2. 时间严格递增；
3. `bar_id` 和时间无重复；
4. OHLC关系合法；
5. volume、OI非负；
6. 最后一根bar没有超过允许延迟；
7. 至少满足配置的 `warmup_bars`。

建议：

```yaml
warmup_bars: 200
subscription_bars: 400
```

不满足预热时返回 `WARMING_UP`，数据错误返回相应质量状态。不得通过填0伪造有效因子。

### 6.3 基础指标

兼容阶段调用或迁移当前实现，保持：

- MA7、MA14、MA52；
- ATR14；
- ADX14、DI+、DI-；
- KDJ 9/3/3；
- Volume MA20。

候选增强版本增加：

- 三根K线动量；
- MA14三根K线斜率；
- ATR / Close；
- ATR过去120根分位数；
- 三根K线持仓量变化。

### 6.4 候选标准化因子

这些公式属于 `falcon_v3_candidate`，必须由 feature flag 控制，不能在结构迁移时直接替换旧分数。

```python
trend = clip((close - ma52) / (2 * atr), -1, 1)
stack = clip((ma7 - ma52) / (2 * atr), -1, 1)
slope = clip((ma14 - ma14_3bars_ago) / atr, -1, 1)

dmi = clip(
    ((plus_di - minus_di) / (plus_di + minus_di + epsilon))
    * min(adx / 40.0, 1.0),
    -1,
    1,
)

momentum = clip((close - close_3bars_ago) / atr, -1, 1)

volume_ratio = volume / max(volume_ma20, epsilon)
volume_confirmation = sign(close - previous_close) * clip(
    log(max(volume_ratio, 1.0)) / log(3.0),
    0,
    1,
)
```

持仓量只作为确认：持仓增加时强化当前价格方向，持仓下降不直接产生反向信号。

所有除0、NaN、无穷和极端值必须显式处理。标准化方向因子必须在 `[-1,1]`。

### 6.5 Regime 状态机

候选状态机：

```python
enter_up = adx >= 25 and ma14 > ma52 and ma14_slope > 0 and close > ma52
keep_up = previous_regime == TREND_UP and adx >= 20 and close >= ma52 - 0.5 * atr

enter_down = adx >= 25 and ma14 < ma52 and ma14_slope < 0 and close < ma52
keep_down = previous_regime == TREND_DOWN and adx >= 20 and close <= ma52 + 0.5 * atr

enter_range = adx <= 18 and abs(close - ma52) <= atr
```

优先级：保持已有趋势 → 进入新趋势 → RANGE → TRANSITION。多空逻辑必须对称。

### 6.6 FactorEngine 测试

至少创建：

```text
tests/unit/factors/test_input_quality.py
tests/unit/factors/test_normalization.py
tests/unit/factors/test_regime_hysteresis.py
tests/unit/factors/test_determinism.py
tests/characterization/test_legacy_indicators.py
```

必须证明：

- 预热不足不产生可交易因子；
- 重复、倒序和未完成K线被识别；
- 因子范围和有限性正确；
- 多空状态机对称；
- 相同输入和版本产生相同输出；
- 未完成K线变化不影响已完成K线结果。

---

## 7. SOP 3：SignalEngine

### 7.1 公开接口

在 `strategies/falcon/signal_engine.py` 中提供：

```python
@dataclass(frozen=True)
class SignalState:
    previous_alpha: float | None
    consecutive_long_bars: int
    consecutive_short_bars: int
    previous_action: SignalAction


class SignalEngine:
    def generate(
        self,
        factors: FactorSnapshot,
        state: SignalState,
        now: datetime,
    ) -> tuple[SignalEvent, SignalState]:
        ...
```

### 7.2 兼容模式

先实现 `LegacySignalAdapter`：

```text
旧 IndicatorBundle / ScoreDetail
  → 标准 FactorSnapshot / SignalEvent
```

兼容模式下，bar-by-bar 的旧 `[-3,3]` 分数不得改变。

### 7.3 候选 Alpha

候选版本使用配置化权重：

```python
alpha = (
    0.25 * trend
    + 0.15 * stack
    + 0.15 * slope
    + 0.20 * dmi
    + 0.15 * momentum
    + 0.05 * volume_confirmation
    + 0.05 * oi_confirmation
)
```

所有权重来自配置，并在启动时校验绝对权重之和。输出 `alpha` 限制在 `[-1,1]`。

### 7.4 开仓信号

候选初始阈值：

```yaml
entry_threshold: 0.55
strong_threshold: 0.75
confirmation_bars: 2
signal_ttl_bars: 1
```

多头必须同时满足：

```python
factors.quality == READY
factors.regime == TREND_UP
alpha >= entry_threshold
consecutive_long_bars >= confirmation_bars
```

空头完全对称。RANGE和TRANSITION禁止发出新的ENTER。

### 7.5 退出信号

兼容配置默认：

```yaml
exit_on_signal_decay: false
exit_on_regime_loss: false
```

候选增强配置可在独立研究阶段启用：

```text
多头：alpha <= 0.10 连续2根，或 regime == TREND_DOWN
空头：alpha >= -0.10 连续2根，或 regime == TREND_UP
```

不得在架构重构阶段默认开启候选退出。

### 7.6 置信度

```python
regime_strength = clip(adx / 40.0, 0, 1)
factor_agreement = aligned_factor_weight / total_factor_weight
data_quality_score = 1.0 if quality == READY else 0.0

confidence = (
    0.50 * regime_strength
    + 0.30 * factor_agreement
    + 0.20 * data_quality_score
)
```

置信度和Alpha必须分开保存。

### 7.7 信号有效期

5分钟信号候选TTL为1根K线。信号必须包含：

- `generated_at`；
- `effective_from`；
- `expires_at`；
- `model_version`；
- `reason_codes`。

过期信号不得产生新仓位。

### 7.8 SignalEngine 测试

至少创建：

```text
tests/unit/signals/test_confirmation.py
tests/unit/signals/test_expiry.py
tests/unit/signals/test_regime_gate.py
tests/unit/signals/test_long_short_symmetry.py
tests/characterization/test_legacy_score.py
```

必须证明：

- 单根越过阈值不会提前开仓；
- RANGE和TRANSITION不能新开；
- 过期信号不能开仓；
- 多空逻辑对称；
- 每个动作都有原因码；
- 兼容模式与旧评分逐bar一致；
- 模块不导入账户、订单或tqsdk。

---

## 8. SOP 4：PositionSizer

### 8.1 公开接口

在 `portfolio/sizing.py` 中提供：

```python
class PositionSizer:
    def calculate(
        self,
        signal: SignalEvent,
        factors: FactorSnapshot,
        position: PositionSnapshot,
        account: AccountSnapshot,
        contract: ContractSnapshot,
        portfolio: PortfolioSnapshot,
    ) -> TargetPosition:
        ...
```

### 8.2 兼容模式

先实现：

```yaml
sizing_mode: legacy_fixed_lot
```

使用现有 `LOT_BY_SIGNAL` 和 `LOT_SCALE`，并把旧 `None / int` 转换为：

```text
None → SignalAction.HOLD
0    → desired_position=0
int  → 显式目标净仓
```

### 8.3 候选计划止损

在 `portfolio/stop_planner.py` 中实现纯计算函数。多头候选：

```python
atr_stop = reference_price - 1.3 * atr
structure_stop = min(low_of_last_6_bars) - price_tick
planned_stop = min(atr_stop, structure_stop)
stop_distance = reference_price - planned_stop
```

空头对称。

限制：

```yaml
minimum_stop_atr: 1.0
maximum_stop_atr: 2.5
```

超过最大止损距离时目标为0并记录 `STOP_DISTANCE_TOO_WIDE`。实际成交后，执行/持仓层必须用平均成交价重新锁定 EntryContext。

### 8.4 候选风险手数

```python
risk_per_lot = (
    stop_distance * contract.multiplier
    + estimated_round_trip_fee
    + estimated_round_trip_slippage
)

risk_budget = account.equity * config.risk_budget_per_trade_pct
raw_lots = floor(risk_budget / risk_per_lot)
```

候选配置：

```yaml
risk_budget_per_trade_pct: 0.003
max_lots_per_symbol: 3
max_add_lots_per_bar: 1
allow_minimum_one_lot: true
```

如果1手风险超过硬上限，即使 `allow_minimum_one_lot=true` 也必须返回0。

### 8.5 信号缩放

```python
if strength < 0.55:
    signal_scale = 0.00
elif strength < 0.70:
    signal_scale = 0.50
elif strength < 0.85:
    signal_scale = 0.75
else:
    signal_scale = 1.00
```

### 8.6 波动缩放

```python
if atr_percentile >= 0.90:
    volatility_scale = 0.50
elif atr_percentile >= 0.75:
    volatility_scale = 0.75
elif atr_percentile <= 0.05:
    volatility_scale = 0.75
else:
    volatility_scale = 1.00
```

最终候选手数：

```python
candidate_lots = min(
    floor(raw_lots * signal_scale * volatility_scale),
    config.max_lots_per_symbol,
)
```

### 8.7 加仓与反手

候选加仓必须满足：

- 信号方向与持仓一致；
- 信号强度比上次加仓至少提高0.15；
- 当前持仓浮盈；
- 距上次加仓至少2根K线；
- 每根K线最多增加1手。

反手必须：

```text
先生成 FLAT
→ 等待实际仓位归零
→ 至少冷却1根K线
→ 重新确认反向信号
→ 再生成反向目标
```

不得一次将目标从正数直接穿越到负数。

### 8.8 PositionSizer 测试

至少创建：

```text
tests/unit/portfolio/test_legacy_sizing.py
tests/unit/portfolio/test_risk_sizing.py
tests/unit/portfolio/test_stop_planner.py
tests/unit/portfolio/test_add_position.py
tests/unit/portfolio/test_reversal.py
```

必须证明：

- 信号增强时目标手数不应反向下降；
- ATR上升、其他条件不变时目标手数不增加；
- 权益下降时目标手数不增加；
- 单手风险超限时目标为0；
- RANGE不能新增仓位；
- HOLD不改变此前目标；
- 反手先归零；
- 所有目标不超过配置上限。

---

## 9. SOP 5：RiskEngine

### 9.1 公开接口

在 `risk/engine.py` 中提供：

```python
class RiskEngine:
    def evaluate(
        self,
        target: TargetPosition,
        signal: SignalEvent,
        market: MarketSnapshot,
        contract: ContractSnapshot,
        position: PositionSnapshot,
        account: AccountSnapshot,
        portfolio: PortfolioSnapshot,
        runtime: RuntimeSnapshot,
        now: datetime,
    ) -> RiskDecision:
        ...
```

风控规则实现统一协议：

```python
class RiskRule(Protocol):
    priority: int
    rule_code: str

    def evaluate(self, context: RiskContext) -> RuleResult:
        ...
```

规则按优先级排序执行。不得依赖文件导入顺序决定优先级。

### 9.2 风控优先级

必须按顺序检查：

1. Kill Switch；
2. 对账、未知订单和运行状态；
3. 数据新鲜度和信号有效期；
4. 合约合法性、换月和交易状态；
5. 涨跌停、价差和流动性；
6. 账户资金、保证金和单日亏损；
7. 单品种和组合风险；
8. 重复订单、开平和频率限制。

### 9.3 候选初始阈值

这些值必须配置化，并以研究/风控评审结果为准：

```yaml
max_bar_delay_seconds: 30
max_spread_ticks: 3
min_bar_volume: 10
max_order_volume_share: 0.01

max_margin_ratio_after_order: 0.30
minimum_available_cash_pct: 0.20
max_daily_loss_pct: 0.01
max_strategy_drawdown_pct: 0.05

max_trade_risk_pct: 0.003
max_symbol_open_risk_pct: 0.005
max_total_open_risk_pct: 0.010
max_symbol_lots: 3
```

### 9.4 审批语义

- `PASS`：原目标允许执行；
- `RESIZE`：允许执行，但必须缩小目标；
- `REJECT`：拒绝本次目标，不停止整个策略；
- `HALT`：停止新增风险并进入人工或自动恢复流程。

风控不能修改原 `TargetPosition`，只能创建新的 `RiskDecision`。

### 9.5 风险减少订单

定义：

```python
is_risk_reducing = abs(target.desired_position) < abs(position.net_position)
```

风险减少订单：

- 不因信号过期而拒绝；
- 不因保证金不足而拒绝合法平仓；
- 数据异常时仍应尽可能执行；
- 流动性不足时应调整数量或紧迫度并告警，而非假设风险已消失；
- 只有市场关闭、交易通道不可用或合约非法时才能暂缓；
- 暂缓必须返回原因码并触发告警。

### 9.6 必需原因码

在 `risk/rules.py` 或领域枚举中定义：

```text
DATA_STALE
FACTOR_NOT_READY
SIGNAL_EXPIRED
REGIME_NOT_ALLOWED
CONTRACT_INVALID
ROLL_IN_PROGRESS
SPREAD_TOO_WIDE
INSUFFICIENT_LIQUIDITY
PRICE_LIMIT_LOCKED
MARGIN_LIMIT
DAILY_LOSS_LIMIT
DRAWDOWN_LIMIT
SYMBOL_RISK_LIMIT
PORTFOLIO_RISK_LIMIT
POSITION_LIMIT
DUPLICATE_ORDER
UNKNOWN_ORDER_EXISTS
RECONCILIATION_MISMATCH
KILL_SWITCH_ACTIVE
RISK_REDUCING_ORDER
```

### 9.7 Kill Switch

满足任一条件时返回 `HALT`：

- 人工触发；
- 持仓与柜台持续不一致；
- 无法解释的重复订单；
- 单日亏损或回撤超过硬限制；
- 行情与交易通道同时失效；
- 交易事实无法持久化；
- 实际仓位超过硬上限；
- 多次恢复后订单仍为 UNKNOWN。

本轮只生成 `HALT` 决策和事件，不得在 RiskEngine 中直接撤单或平仓。后续执行层负责按照 shutdown policy 执行。

### 9.8 RiskEngine 测试

至少创建：

```text
tests/unit/risk/test_rule_priority.py
tests/unit/risk/test_risk_reducing.py
tests/unit/risk/test_resize.py
tests/unit/risk/test_operational_halt.py
tests/unit/risk/test_reason_codes.py
tests/integration/test_risk_pipeline.py
```

必须证明：

- 数据过期时新开仓被拒绝；
- 风险减少订单不被普通开仓规则阻断；
- 请求3手、上限2手时返回RESIZE到2手；
- UNKNOWN订单和对账不一致禁止新增风险；
- 保证金不足不阻止合法平仓；
- 每次REJECT、RESIZE、HALT都有原因码；
- 同一输入得到同一决策；
- 风控模块不调用任何下单接口。

---

## 10. 决策编排

在 `engine/decision_pipeline.py` 中实现唯一编排入口：

```python
@dataclass(frozen=True)
class PipelineResult:
    factors: FactorSnapshot
    signal: SignalEvent
    target: TargetPosition
    risk_decision: RiskDecision


class FalconDecisionPipeline:
    def on_bar_close(self, context: DecisionContext) -> PipelineResult:
        factors = self.factor_engine.compute(
            bars=context.bars,
            previous_regime=context.previous_regime,
        )

        if factors.quality is not FactorQuality.READY:
            signal = self.signal_factory.hold(
                factor_snapshot_id=factors.factor_snapshot_id,
                reason_code="FACTOR_NOT_READY",
                now=context.now,
            )
        else:
            signal, next_signal_state = self.signal_engine.generate(
                factors=factors,
                state=context.signal_state,
                now=context.now,
            )

        target = self.position_sizer.calculate(
            signal=signal,
            factors=factors,
            position=context.position,
            account=context.account,
            contract=context.contract,
            portfolio=context.portfolio,
        )

        risk_decision = self.risk_engine.evaluate(
            target=target,
            signal=signal,
            market=context.market,
            contract=context.contract,
            position=context.position,
            account=context.account,
            portfolio=context.portfolio,
            runtime=context.runtime,
            now=context.now,
        )

        return PipelineResult(
            factors=factors,
            signal=signal,
            target=target,
            risk_decision=risk_decision,
        )
```

实际实现应处理 `next_signal_state` 的显式返回或事件化持久化，不能依赖模块内部不可见的全局可变状态。

### 10.1 编排不变量

- 每根完整K线最多产生一次相同 `decision_id`；
- 重复处理相同 `bar_id` 必须幂等；
- 四阶段输出必须在执行前持久化或写入可靠决策日志；
- 执行层只消费 `RiskDecision.approved_position`；
- RiskEngine不得回头修改Factor、Signal或Target；
- Runner不得绕过Pipeline直接调用旧 `score_signal` 或 `lots_from_signal`。

---

## 11. 配置要求

在 `config/decision.py` 中实现类型化配置，或适配项目已有配置体系。

```yaml
decision_mode: legacy_compatible

factor:
  warmup_bars: 200
  subscription_bars: 400
  regime_enter_adx: 25
  regime_keep_adx: 20
  regime_range_adx: 18

signal:
  entry_threshold: 0.55
  strong_threshold: 0.75
  confirmation_bars: 2
  signal_ttl_bars: 1
  exit_on_signal_decay: false
  exit_on_regime_loss: false

sizing:
  mode: legacy_fixed_lot
  risk_budget_per_trade_pct: 0.003
  max_lots_per_symbol: 3
  max_add_lots_per_bar: 1
  allow_minimum_one_lot: true
  minimum_stop_atr: 1.0
  maximum_stop_atr: 2.5

risk:
  max_bar_delay_seconds: 30
  max_spread_ticks: 3
  max_order_volume_share: 0.01
  max_margin_ratio_after_order: 0.30
  minimum_available_cash_pct: 0.20
  max_daily_loss_pct: 0.01
  max_strategy_drawdown_pct: 0.05
  max_trade_risk_pct: 0.003
  max_symbol_open_risk_pct: 0.005
  max_total_open_risk_pct: 0.010
  max_symbol_lots: 3
```

要求：

- 参数只能有一个事实来源；
- 配置启动时完成范围校验；
- 生产日志输出脱敏配置和配置哈希；
- 兼容模式与候选模式必须显式命名；
- 候选配置默认不得用于真实交易。

---

## 12. 分阶段实施任务

### Task A：行为冻结

只添加测试和基线数据，不改策略逻辑。

完成条件：旧指标、评分、目标和风险事件可以逐bar复现。

### Task B：领域对象和适配器

创建 enums、models、legacy adapters，把旧输出转换为新对象。

完成条件：旧 runner 仍能运行，新对象可序列化，Golden Master不变。

### Task C：FactorEngine

先封装旧指标，再在 feature flag 下增加候选标准化因子和regime状态机。

完成条件：兼容模式完全一致；候选模式单元测试通过但默认关闭。

### Task D：SignalEngine

先封装旧score，再增加候选Alpha、确认、TTL和原因码。

完成条件：兼容模式逐bar一致；候选模式不会在RANGE开仓。

### Task E：PositionSizer

先迁移旧 `LOT_BY_SIGNAL`，再增加候选风险定仓、计划止损、加仓和反手约束。

完成条件：兼容模式一致；候选模式满足所有仓位属性测试。

### Task F：RiskEngine

将风险规则改为确定性、可排序、带原因码的规则链。

完成条件：风险减少订单、RESIZE、HALT和优先级测试通过。

### Task G：统一Pipeline

让 backtest、sim 和 dashboard runner 调用统一 `on_bar_close`。

完成条件：仓库不存在第二套活动决策循环；三入口相同输入得到相同决策。

### Task H：删除旧重复逻辑

只有在全部兼容测试通过、调用点迁移完成后，才能删除旧实现或保留明确弃用的薄适配器。

完成条件：无未使用旧入口、无 `sys.path` 新增注入、文档同步。

---

## 13. Agent 每次任务的输出格式

修改前：

```markdown
## 任务理解
- 本次阶段：
- 目标：
- 非目标：
- 行为不变量：
- 涉及路径：

## 当前证据
- 现有实现：
- 现有测试：
- 文档与源码冲突：

## 实施计划
1. ...
2. ...

## 验证计划
- Golden Master：
- 单元测试：
- 集成测试：
- 回滚方式：
```

修改后：

```markdown
## 完成内容
- ...

## 行为变化
- 无；或逐条说明变化、依据和影响。

## 验证结果
- 运行命令：
- 通过项：
- 未运行项及原因：

## 配置或迁移
- ...

## 风险与下一步
- ...
```

---

## 14. Definition of Done

单个阶段只有满足以下条件才算完成：

- [ ] 修改前已建立或更新相关测试；
- [ ] 兼容模式未发生未授权行为变化；
- [ ] 因子、信号、目标和风控对象可序列化；
- [ ] HOLD与FLAT语义明确；
- [ ] 所有拒绝、缩量和停止都有原因码；
- [ ] 核心模块没有导入tqsdk交易接口；
- [ ] 相同输入和版本得到相同结果；
- [ ] 多空逻辑的对称性已测试；
- [ ] 异常默认不扩大风险；
- [ ] 测试、lint和类型检查已运行；
- [ ] 未运行项和剩余风险已报告；
- [ ] 文档与代码同步。

整个决策链重构只有满足以下条件才算完成：

- [ ] 回测、模拟和dashboard runner共用一个Pipeline；
- [ ] 旧逻辑通过Golden Master或差异已获明确批准；
- [ ] 候选新策略默认关闭；
- [ ] 每笔批准目标可回溯到Factor、Signal、Target和RiskDecision；
- [ ] 重复bar处理幂等；
- [ ] 未来执行层只能消费批准后的目标；
- [ ] 不存在活动的第二套评分、手数或风控主循环。

---

## 15. 推荐给 Cursor Agent 的首个任务

```text
阅读根目录 AGENTS.md、架构说明、Ruler.md，以及 strategies/falcon 下的全部核心文件。

本次只执行 Task A“行为冻结”，不要改策略公式、参数、目录或执行逻辑。

请：
1. 列出 indicators、regime、score、sizing、risk 的真实调用关系；
2. 找出 backtest、sim、dashboard runner 的行为差异；
3. 建立固定输入数据和 characterization tests；
4. 保存逐bar指标、regime、score、目标仓位和风险事件作为 Golden Master；
5. 运行现有测试和新增测试；
6. 输出下一阶段建议，但不要开始 Task B。

如果源码与 AGENTS.md 描述冲突，以可重复测试和源码为证据，报告冲突，不要静默修改预期结果。
```
