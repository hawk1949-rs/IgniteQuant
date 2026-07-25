# 天勤行情 → 本地缓存规则

> 适用范围：`data/market_cache/`、`tools/download_market_cache.py`、`src/ignitequant/market/download.py`、本地回放 `local_replay.py`。  
> 目的：本地缓存加速回测时，**决策输入与 `TqBacktest` + `is_changing(datetime)` 语义一致**，避免再出现「缓存有数据但对不上天勤」的隐性分叉。

---

## 1. 产品定位

| 项 | 约定 |
| --- | --- |
| 缓存用途 | 加速本地回放；撮合语义对齐 `TqSim`（`align_mode=tq_kline`） |
| 权威结果 | 仍以 `engine=tq` / CLI `TqBacktest` 为准 |
| 禁止误解 | 天勤**不支持**把 CSV 直接喂给 `TqBacktest`；缓存不是「离线时光机」 |

---

## 2. 目录与文件约定

```text
data/market_cache/
  <signal_symbol>/          # 例：KQ.m@SHFE.au
    300.csv                 # duration_seconds=300 → 5 分钟
    300.meta.json           # rows / 起止 / source / updated_at
```

CSV 列（顺序固定，见 `ignitequant.market.cache.BAR_COLUMNS`）：

```text
datetime, open, high, low, close, volume, open_oi, close_oi, underlying_symbol
```

- `datetime`：纳秒时间戳（与 tqsdk kline 一致）
- `underlying_symbol`：该 bar 时刻主力合约（换月必需）；禁止空值冒充

新增品种时：先在 `ignitequant.market.symbols.INSTRUMENTS` 登记，再下载，禁止手搓无 `underlying` 的 CSV。

---

## 3. 下载写入规则（强制）

实现：`upsert_completed_and_stub`（`market/download.py`）。

天勤回测里，策略通常在：

```text
api.is_changing(klines.iloc[-1], "datetime") == True
```

时决策。此时：

| 行 | 含义 | 必须写入缓存的内容 |
| --- | --- | --- |
| `iloc[-2]` | **刚走完的 K 线** | **完整 OHLC + volume/OI**（最终态） |
| `iloc[-1]` | **刚开盘的新 K 线 stub** | 常为 `o=h=l=c`、`volume≈0`（允许暂时 stub） |

### 3.1 正确做法

1. 每次 `datetime` 变化：用 `iloc[-2]` **覆盖/upsert** 对应 `datetime` 的完整 bar。  
2. 同时 upsert `iloc[-1]` stub（同一 map，按 `datetime` 去重）。  
3. `BacktestFinished` 时再 flush 最后一根 `iloc[-1]`。  
4. 分段下载（默认约 6 个月一块）后 `merge_and_save`；合并冲突时 **保留更「丰满」的快照**（volume / high-low 区间更大者优先）。  
5. **缺区间自动补拉**时，下载起点会早于用户回测 `start`（约 45 天指标预热）。进度文案必须标明「补拉预热」，**不得让用户误以为回测从预热日开始**；真正交易窗口仍是用户选择的 `[start, end]`。

### 3.2 禁止做法（历史事故）

- 只 `append(iloc[-1])` 且从不回写上一根 → 全历史变成 stub → ATR 塌缩 → local 与 tq 决策分叉。  
- 用收盘价合成「假完整」bar 却声称与天勤一致。  
- 下载时丢掉 `underlying_symbol`。  
- 把未完成 bar 的盘中中间态当最终历史（除当前 stub 外）。

### 3.3 质量自检（下载后建议）

对任一品种抽样：

- 连续 bar 中，**非最后一根** 应大量满足：`high >= max(open, close)`、`low <= min(open, close)`，且 `volume > 0` 占比高。  
- 若几乎全部 `o=h=l=c` 且 `volume=0` → **缓存损坏，必须重下**。

对照门禁：

- `coverage_ok`：窗口内不得有超过约 20 天的空洞；期末若因节假日提前结束，续跑须在 `end` 后约 20 天内恢复。**禁止**把数月后的缓存段当成当前窗口已覆盖（历史事故：au 缺 2025-03～10，却因 11 月仍有数据误判完整）。

```powershell
python tools/compare_local_tq.py --symbol KQ.m@SHFE.au --start 2025-01-02 --end 2025-01-10
```

---

## 4. 本地回放消费规则（强制）

实现：`_tq_datetime_change_window`（`engine/local_replay.py`）。

即使 CSV 里历史 bar 已是完整 OHLC，回放决策时仍须模拟天勤「新 bar 刚出现」：

1. 窗口内 **历史 bar**：用缓存中的完整 OHLC。  
2. **当前决策 bar**：塌缩为开盘 stub —— `high=low=close=open`，`volume=0`。  
3. 成交/盯市信号价：用该 bar 的 **open**（再 ±1 tick 对齐 `TqSim` kline 盘口），不是完整 close。

这样 local 与 `engine=tq` 在同一 `datetime-change` 时刻看到的输入一致。

---

## 5. 操作命令

```powershell
# 状态
python tools/download_market_cache.py --status

# 四品种全量（示例区间；可按研究需要加长）
python tools/download_market_cache.py --all --start 2023-01-01 --end 2026-07-01

# 单品种 / 多 id
python tools/download_market_cache.py --ids ag,rb,fg --start 2023-01-01 --end 2026-07-01
python tools/download_market_cache.py --symbol KQ.m@SHFE.au --start 2024-11-01 --end 2025-01-15
```

**更换下载算法或发现 stub 污染后**：删除对应 `data/market_cache/<signal>/300.csv`（及 `.meta.json`）再下，不要假设增量 merge 能修好全是 stub 的旧文件。

---

## 6. 新增数据源 / 新周期检查清单

在合入前必须回答：

- [ ] 是否仍按「`datetime` 变化 → 回写上一根完整 + 写入当前 stub」？  
- [ ] CSV 是否含 `underlying_symbol`？  
- [ ] 本地回放是否对当前 bar 做 stub？  
- [ ] 手续费是否经 `CostModel` / `TqSim.set_commission` 对齐？  
- [ ] 是否跑过 `compare_local_tq`（或等价）短窗门禁？

任一为否，不得把该缓存标为「与天勤对齐」。

---

## 7. 指标口径（与 TqReport 对齐）

本地回测展示的年化 / 夏普 / 最大回撤必须走 `ignitequant.analytics.tq_metrics`，与天勤 `TqReport` 同公式：

| 指标 | 公式 |
| --- | --- |
| 年化 | `(1+ror) ** (250 / n_settle_days) - 1` |
| 夏普 | `√250 * (mean(daily_yield) - rf_daily) / pstdev`，`rf=2.5%` |
| 结算日 | `trading_day_from_timestamp_ns`（≥18:00 CST 滚次日；周末滚周一） |
| 决策日 | 日历日 `fromtimestamp`（与 `dashboard/runners` 强制平仓门控一致） |

禁止再用「日历跨度 / 365.25」年化，也禁止把周六夜盘日历日当作独立权益采样点。

---

## 8. 相关代码

| 模块 | 职责 |
| --- | --- |
| `src/ignitequant/market/download.py` | TqBacktest 拉取 + `upsert_completed_and_stub` |
| `src/ignitequant/market/cache.py` | CSV 读写 / merge（丰满快照优先） |
| `src/ignitequant/market/symbols.py` | 品种登记与 CostModel |
| `src/ignitequant/market/trading_day.py` | 交易日映射（对齐 tqsdk.datetime） |
| `src/ignitequant/analytics/tq_metrics.py` | 年化/夏普/回撤（对齐 TqReport） |
| `src/ignitequant/engine/local_replay.py` | stub 窗口 + LocalSim 回放 |
| `src/ignitequant/analytics/tq_match.py` | 1-tick 盘口与对照门禁 |
| `tools/download_market_cache.py` | CLI |
| `tools/compare_local_tq.py` | local↔tq 对照 |
