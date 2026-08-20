import { useMemo, useState, type ReactNode } from 'react'
import {
  Select,
  Tag,
  Alert,
  Button,
  Table,
  Tabs,
  Segmented,
  message,
  Tooltip,
} from 'antd'
import { useIsBelowXl, useIsPhone } from '@/hooks/useMediaQuery'
import { useSimCockpit } from './SimCockpitContext'
import { MiniCandleChart } from './MiniCandleChart'
import {
  decisionReasonText,
  qualityLabel,
  regimeLabel,
  riskActionLabel,
  shortBiasLabel,
  statusLabel,
  tradeActionLabel,
  tradeActionTagColor,
  intentActionCode,
} from './labels'
import { catchUpSimBars, startSimStrategy } from '@/lib/api'
import { formatLocalDateTime } from './time'
import { useSimTablePagination } from './tablePagination'
import { HeartbeatBoard } from './HeartbeatBoard'
import {
  CHART_TIMEFRAMES,
  aggregateChartBundle,
  type ChartTimeframe,
} from './chartTimeframe'
import { focusedOpenPositions } from './simSessions'

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`
}

function money(n: number) {
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

const INTENT_STATUS: Record<string, string> = {
  PENDING: '待处理',
  SUBMITTED: '已提交',
  ACKNOWLEDGED: '已受理',
  FILLED: '已成交',
  PARTIAL: '部分成交',
  CANCELLED: '已撤销',
  REJECTED: '已拒绝',
  FAILED: '失败',
  UNKNOWN: '未知',
  CREATED: '已创建',
}

const SIDE_LABEL: Record<string, string> = {
  BUY: '买',
  SELL: '卖',
  LONG: '多',
  SHORT: '空',
}

function intentStatusLabel(s?: string) {
  if (!s) return '—'
  return INTENT_STATUS[s] || s
}

function sideLabel(s?: string) {
  if (!s) return '—'
  const u = s.toUpperCase()
  if (SIDE_LABEL[u]) return SIDE_LABEL[u]
  if (u.includes('BUY')) return '买'
  if (u.includes('SELL')) return '卖'
  return s
}

function Metric({
  label,
  value,
  tone,
  tip,
}: {
  label: string
  value: string | number
  tone?: 'good' | 'bad' | 'none'
  tip?: string
}) {
  const color =
    tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : 'text-ink'
  const labelNode = tip ? (
    <Tooltip title={tip}>
      <span className="cursor-help underline decoration-dotted decoration-faint/60">
        {label}
      </span>
    </Tooltip>
  ) : (
    label
  )
  return (
    <div className="min-w-0">
      <p className="text-xs leading-none text-faint">{labelNode}</p>
      <p className={`mt-1 truncate text-sm font-semibold tabular-nums ${color}`}>{value}</p>
    </div>
  )
}

function Section({
  title,
  extra,
  children,
  className = '',
}: {
  title: string
  extra?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-xl border border-line bg-panel/90 ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70 px-3.5 py-2">
        <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>
        {extra ? <div className="min-w-0 text-xs text-muted">{extra}</div> : null}
      </div>
      <div className="p-3.5">{children}</div>
    </section>
  )
}

export function OverviewPanel() {
  const {
    catalog,
    instanceId,
    setInstanceId,
    framework,
    strategyId,
    setStrategyId,
    symbolId,
    setSymbolId,
    symbolIds,
    setSymbolIds,
    fleet,
    summary,
    metrics,
    decisions,
    intents,
    fills,
    positionHistory,
    bars,
    overseas,
    error,
    warn,
    loading,
    refresh,
    loadMoreHistory,
    historyLoading,
    loadMoreOverseasHistory,
    overseasHistoryLoading,
    replayAt,
    replay,
    starting,
    setStarting,
  } = useSimCockpit()

  const latest = replay?.decision || decisions[0]
  const focusedSummary = summary?.instance_id === instanceId ? summary : null
  const status = focusedSummary?.status || 'IDLE'
  const statusText = focusedSummary?.status_label || statusLabel(status)
  const processRunning = Boolean(focusedSummary?.process_running)
  const selectedLaunchers = (catalog?.launchers || []).filter(
    (l) => l.strategy_id === strategyId && symbolIds.includes(l.symbol_id),
  )
  const selectedRunningCount = selectedLaunchers.filter((l) =>
    fleet.some((row) => row.instance_id === l.instance_id && row.process_running),
  ).length
  const allSelectedRunning =
    selectedLaunchers.length > 0 && selectedRunningCount === selectedLaunchers.length
  const runningFleet = fleet.filter((row) => row.process_running)
  const cloudReadOnly = Boolean(
    catalog?.read_only ||
      catalog?.data_source === 'cloud' ||
      summary?.read_only ||
      summary?.data_source === 'cloud',
  )
  const readOnlyHint =
    catalog?.read_only_hint ||
    summary?.read_only_hint ||
    '当前为云端只读座舱：决策/意图/成交来自 Supabase 投影；请在交易机运行模拟盘推送。'
  const isGmaStrategy = strategyId.startsWith('gma')
  const [catchingUp, setCatchingUp] = useState(false)
  const selectedSymbol = catalog?.symbols?.find((s) => s.id === symbolId)
  const launcherSymbolId =
    catalog?.launchers?.find((l) => l.instance_id === instanceId)?.symbol_id ?? null
  const symbolMismatch = Boolean(launcherSymbolId && launcherSymbolId !== symbolId)
  const focusedMetrics = metrics?.instance_id === instanceId ? metrics : null
  const lastPrice =
    focusedSummary?.last_price ??
    bars?.last_price ??
    (bars?.bars?.length ? bars.bars[bars.bars.length - 1].close : null)
  const pnl = focusedMetrics?.pnl ?? 0
  const realizedClosed =
    focusedMetrics?.realized_pnl_closed ??
    (pnl - Number(focusedMetrics?.unrealized_pnl || 0))
  const historyClosePnl = positionHistory
    .filter((r) => (r.action || 'CLOSE') === 'CLOSE')
    .reduce((s, r) => s + Number(r.realized_pnl || 0), 0)
  const historyRoundCount = new Set(
    positionHistory.map((r) => r.round_id).filter(Boolean),
  ).size || Math.ceil(positionHistory.length / 2)
  // Prefer live strategy_state.confirmed_net (heartbeat); position snapshot was historically boot-only.
  const confirmedNet = focusedSummary?.payload?.confirmed_net
  const net =
    confirmedNet != null && confirmedNet !== ''
      ? Number(confirmedNet)
      : (focusedSummary?.position?.net_position ?? 0)
  const target = Number(focusedSummary?.payload?.current_target ?? 0)
  const margin = Number(focusedSummary?.account?.margin ?? 0)
  const marginRatio = Number(focusedSummary?.account?.margin_ratio ?? 0)
  const pendingDesired =
    focusedSummary?.payload?.pending_desired != null &&
    focusedSummary.payload.pending_desired !== ''
      ? Number(focusedSummary.payload.pending_desired)
      : null
  const targetNetDesync = net !== target
  const chartCtx = bars?.chart_context
  const displayRegime = latest?.regime ?? chartCtx?.regime
  const shortBias = chartCtx?.short_bias
  const regimeConflict = Boolean(
    chartCtx?.conflict &&
      latest?.regime &&
      chartCtx?.regime &&
      latest.regime !== chartCtx.regime,
  )
  const session = focusedSummary?.market_session || bars?.market_session
  const positionNote = focusedSummary?.position_note
  const openPositions = focusedOpenPositions(focusedSummary)
  const otherLegs = (focusedSummary?.book?.legs || []).filter(
    (leg) =>
      leg.instance_id !== instanceId &&
      Number(leg.net_position || 0) !== 0,
  )
  const decisionsPagination = useSimTablePagination('decisions', 10, decisions.length)
  const intentsPagination = useSimTablePagination('intents', 10, intents.length)
  const fillsPagination = useSimTablePagination('fills', 10, fills.length)
  const historyPagination = useSimTablePagination('position-history', 10, positionHistory.length)
  const backfillFills = fills.filter(
    (f) => f.fill_source === 'intent_chain_backfill' || f.fill_id?.startsWith('fill-backfill-'),
  )
  const liveFills = fills.length - backfillFills.length
  const [chartTf, setChartTf] = useState<ChartTimeframe>('5m')
  const [positionTab, setPositionTab] = useState('current')
  const [chartPane, setChartPane] = useState<'domestic' | 'overseas'>('domestic')
  const isPhone = useIsPhone()
  const isBelowXl = useIsBelowXl()
  const chartHeight = isPhone ? 260 : 420
  const showChartTabs = Boolean(overseas?.supported) && isBelowXl

  const domesticChart = useMemo(
    () =>
      aggregateChartBundle({
        bars: bars?.bars,
        markers: bars?.markers,
        overlays: bars?.overlays,
        overlaySpecs: bars?.overlay_specs,
        barMeta: bars?.bar_meta,
        priceLines: bars?.price_lines,
        tf: chartTf,
      }),
    [
      bars?.bars,
      bars?.markers,
      bars?.overlays,
      bars?.overlay_specs,
      bars?.bar_meta,
      bars?.price_lines,
      chartTf,
    ],
  )

  const overseasChart = useMemo(
    () =>
      aggregateChartBundle({
        bars: overseas?.bars,
        overlays: overseas?.overlays,
        overlaySpecs: overseas?.overlay_specs,
        barMeta: overseas?.bar_meta,
        tf: chartTf,
      }),
    [overseas?.bars, overseas?.overlays, overseas?.overlay_specs, overseas?.bar_meta, chartTf],
  )

  const tfLabel = CHART_TIMEFRAMES.find((t) => t.value === chartTf)?.label || chartTf

  const onStart = async () => {
    setStarting(true)
    try {
      const res = await startSimStrategy(strategyId, symbolIds)
      message.success(res.message || '已发出启动指令')
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  const onCatchUp = async () => {
    setCatchingUp(true)
    try {
      const res = await catchUpSimBars(instanceId, { bootstrapToday: isGmaStrategy })
      const base = res.message || (isGmaStrategy ? '补信号完成' : '补跑完成')
      if (res.recorded === 0 && res.missed === 0) {
        message.info(base)
      } else if (res.hint) message.warning(`${base}；${res.hint}`)
      else message.success(base)
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setCatchingUp(false)
    }
  }

  const factorDetail = (() => {
    if (latest?.factor_summary) return latest.factor_summary
    if (chartCtx?.factor_summary) return chartCtx.factor_summary
    const parts = [
      `策略${regimeLabel(displayRegime)}`,
      shortBias ? shortBiasLabel(shortBias) : null,
      latest ? qualityLabel(latest.factor_quality) : null,
    ].filter(Boolean)
    if (regimeConflict) {
      parts.push('与近端走势不一致')
    }
    return parts.join(' · ') || '—'
  })()

  const pipeline = latest
    ? [
        {
          step: '因子',
          detail: factorDetail,
        },
        {
          step: '信号',
          detail: `分数 ${latest.legacy_signal}${
            latest.score_parts_label
              ? ` · ${latest.score_parts_label}`
              : latest.score_parts
                ? ` · ${JSON.stringify(latest.score_parts)}`
                : ''
          }`,
        },
        {
          step: '目标',
          detail: `${latest.target_before} → ${latest.target_after} · ${tradeActionLabel({
            action: latest.applied_action,
            from: latest.target_before,
            to: latest.target_after,
            signal: latest.legacy_signal,
          })}${targetNetDesync ? ` · 净仓仍为 ${net}` : ''}`,
        },
        {
          step: '风控',
          detail: [
            latest.risk
              ? `${riskActionLabel(latest.risk.action)} · 批准 ${latest.risk.approved_position}`
              : '未触发事前风控',
            latest.pipeline_risk_label,
          ]
            .filter(Boolean)
            .join(' · '),
        },
      ]
    : chartCtx
      ? [
          {
            step: '因子',
            detail: factorDetail,
          },
          {
            step: '信号',
            detail: '等待下一根已收盘 K 线决策',
          },
          {
            step: '目标',
            detail: `当前净仓 ${net} · 目标 ${target}`,
          },
          {
            step: '风控',
            detail: session?.open
              ? '交易时段'
              : '非交易时段（信号可记、MARKET_CLOSED 不成交）',
          },
        ]
      : []

  const symbolOptions = catalog?.symbols || []
  const strategyOptions = (catalog?.strategies || []).filter((s) =>
    (catalog?.launchers || []).some((l) => l.strategy_id === s.id),
  )

  return (
    <div className="flex flex-col gap-3">
      {runningFleet.length ? (
        <section className="rounded-xl border border-line bg-panel/90 px-3.5 py-2.5">
          <p className="text-xs font-medium tracking-wide text-faint">并行运行中</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {runningFleet.map((row) => {
              const active = row.instance_id === instanceId
              return (
                <button
                  key={row.instance_id}
                  type="button"
                  onClick={() => setInstanceId(row.instance_id)}
                  className={`rounded-md border px-2 py-1 text-left text-xs transition-colors ${
                    active
                      ? 'border-blue bg-blue-soft text-blue'
                      : 'border-line bg-surface/60 text-muted hover:border-blue/50 hover:text-ink'
                  }`}
                >
                  <span className="font-medium">{row.label || row.instance_id}</span>
                  {row.net_position ? (
                    <span className="ml-1 tabular-nums">
                      {row.net_position > 0 ? '+' : ''}
                      {row.net_position}手
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>
        </section>
      ) : null}

      {/* 品种主筛选 */}
      <section className="rounded-xl border border-line bg-panel/90 px-3.5 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium tracking-wide text-faint">
              交易品种（可多选，点击查看该品种持仓）
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {symbolOptions.map((s) => {
                const selected = symbolIds.includes(s.id)
                const focused = s.id === symbolId
                const running = fleet.some(
                  (row) =>
                    row.strategy_id === strategyId &&
                    row.symbol_id === s.id &&
                    row.process_running,
                )
                return (
                  <div key={s.id} className="relative">
                    <button
                      type="button"
                      onClick={() => setSymbolId(s.id)}
                      className={`rounded-lg border px-3.5 py-2 pr-7 text-left transition-colors ${
                        focused
                          ? 'border-blue bg-blue-soft text-blue shadow-sm'
                          : selected
                            ? 'border-blue/40 bg-blue-soft/40 text-ink'
                            : 'border-line bg-surface/60 text-muted hover:border-blue/50 hover:text-ink'
                      }`}
                    >
                      <span className="block text-sm font-semibold leading-none">
                        {s.name}
                        {running ? (
                          <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-good align-middle" />
                        ) : null}
                      </span>
                      <span className="mt-1 block text-xs tabular-nums text-faint">
                        {s.signal_symbol || s.id}
                        {selected ? ' · 已选' : ''}
                      </span>
                    </button>
                    {selected && symbolIds.length > 1 ? (
                      <button
                        type="button"
                        aria-label={`取消选择 ${s.name}`}
                        className="absolute right-1 top-1 rounded px-1 text-[10px] text-faint hover:text-ink"
                        onClick={(e) => {
                          e.stopPropagation()
                          const next = symbolIds.filter((id) => id !== s.id)
                          setSymbolIds(next)
                          if (focused && next[0]) setSymbolId(next[0])
                        }}
                      >
                        ×
                      </button>
                    ) : null}
                  </div>
                )
              })}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-xs text-faint">当前对照</p>
            <p className="mt-1 text-base font-semibold text-ink">
              {selectedSymbol?.name || symbolId}
            </p>
            <p className="mt-0.5 text-xs tabular-nums text-faint">
              {selectedSymbol?.signal_symbol || '—'}
              {selectedSymbol?.overseas_pair
                ? ` · 外盘 ${selectedSymbol.overseas_pair.display_symbol}`
                : ''}
            </p>
          </div>
        </div>
      </section>

      {/* 运行配置（次要） */}
      <section className="rounded-xl border border-line/80 bg-panel/70 px-3.5 py-2.5">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium tracking-wide text-faint">运行配置</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <Tag
              className="m-0"
              color={
                status === 'RUNNING' ? 'success' : status === 'STALE' ? 'warning' : 'default'
              }
            >
              {statusText}
            </Tag>
            <Tag className="m-0" color={processRunning ? 'processing' : 'default'}>
              {processRunning ? '进程在线' : '进程离线'}
            </Tag>
          </div>
        </div>
        <div className="flex flex-col gap-y-2 sm:flex-row sm:flex-wrap sm:items-end sm:gap-x-3 sm:gap-y-2">
          <Field label="框架">
            <Tooltip title="跟随运行会话配置，暂不可单独修改">
              <Select
                size="small"
                className="w-full sm:min-w-[9.5rem] sm:w-auto"
                value={framework}
                disabled
                options={(catalog?.frameworks || []).map((f) => ({
                  value: f.id,
                  label: f.enabled ? f.name : `${f.name}（即将支持）`,
                }))}
              />
            </Tooltip>
          </Field>
          <Field label="策略">
            <Select
              size="small"
              className="w-full sm:min-w-[8.5rem] sm:w-auto"
              value={strategyId}
              onChange={setStrategyId}
              options={strategyOptions.map((s) => ({
                value: s.id,
                label: s.ready ? s.name : `${s.name}（占位）`,
                disabled: !s.ready,
              }))}
            />
          </Field>
          <Field label="当前品种会话">
            <Select
              size="small"
              className="w-full sm:min-w-[11rem] sm:w-auto"
              value={instanceId}
              onChange={setInstanceId}
              options={(catalog?.launchers || [])
                .filter((l) => l.strategy_id === strategyId)
                .map((l) => ({
                  value: l.instance_id,
                  label: l.label,
                }))}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-2 pb-0.5">
            <Button
              type="primary"
              size="small"
              onClick={() => void onStart()}
              loading={starting}
              disabled={allSelectedRunning || cloudReadOnly || symbolIds.length === 0}
            >
              {allSelectedRunning
                ? '所选品种已在运行'
                : cloudReadOnly
                  ? '仅交易机可启动'
                  : `启动所选 ${symbolIds.length} 个品种`}
            </Button>
            <Tooltip
              title={
                cloudReadOnly
                  ? '云端只读：补跑会改交易机本地决策链，请在交易机执行'
                  : isGmaStrategy
                    ? '从当日 0 点（CST）补齐已完成 5 分钟 K 的 GMA 信号决策，使小时级因子连续；仅记决策不下单'
                    : '从 last_bar_id 补跑漏掉的已完成 5 分钟 K 线决策（中间 K 只记决策；对齐下单请重启/启动模拟盘）'
              }
            >
              <Button
                size="small"
                onClick={() => void onCatchUp()}
                loading={catchingUp}
                disabled={cloudReadOnly}
              >
                {isGmaStrategy ? '补信号' : '补跑漏 K'}
              </Button>
            </Tooltip>
            <Button size="small" onClick={() => void refresh()} loading={loading}>
              刷新
            </Button>
            {cloudReadOnly ? (
              <Tag color="blue" className="m-0">
                云端只读
              </Tag>
            ) : null}
            <Tooltip title="品种可多选：启动后每个品种独立心跳与持仓。点击品种卡片会载入该策略×品种的盈亏；切换策略则载入对应策略账本。座舱并行启动使用本地 TqSim 账户隔离，避免多策略抢同一合约。">
              <span className="cursor-help text-xs text-faint underline decoration-dotted">
                说明
              </span>
            </Tooltip>
          </div>
        </div>
        {cloudReadOnly ? (
          <Alert
            className="mt-2"
            type="info"
            showIcon
            banner
            message={readOnlyHint}
          />
        ) : null}
        {symbolMismatch ? (
          <Alert
            className="mt-2"
            type="info"
            showIcon
            banner
            message={`当前运行会话是「${launcherSymbolId}」，内盘实时成交/标记仍属该会话；下方图表按你选的「${selectedSymbol?.name || symbolId}」加载对照行情（若无对应模拟快照则显示为空）。`}
          />
        ) : null}
        {replayAt ? (
          <Alert
            className="mt-2"
            type="info"
            showIcon
            banner
            message="复盘模式：实时刷新已暂停，可在「复盘」页退出。"
          />
        ) : null}
        {error ? (
          <Alert
            className="mt-2"
            type="warning"
            showIcon
            banner
            message={error}
          />
        ) : null}
        {warn ? (
          <Alert className="mt-2" type="warning" showIcon banner message={warn} />
        ) : null}
        {positionNote ? (
          <Alert
            className="mt-2"
            type="info"
            showIcon
            banner
            message={positionNote}
          />
        ) : null}
        {session && !session.open ? (
          <Alert
            className="mt-2"
            type="info"
            showIcon
            banner
            message={`${session.label || '非交易时段'}：外盘信号仍可产生并落库；内盘成交门禁为 MARKET_CLOSED（不下单、持仓保留）。模拟进程继续心跳。`}
          />
        ) : null}
        {targetNetDesync ? (
          <Alert
            className="mt-2"
            type="warning"
            showIcon
            banner
            message={
              pendingDesired != null
                ? `净仓 ${net} 与策略目标 ${target} 不一致，待确认委托目标 ${pendingDesired}。思考链路里的「目标」是策略目标仓，不是券商净仓。`
                : `净仓 ${net} 与策略目标 ${target} 不一致。思考链路「目标 a→b」指策略目标仓变化，不是当前净仓。`
            }
          />
        ) : null}
      </section>

      <HeartbeatBoard />

      {/* 指标条：手机横滑卡片，≥sm 恢复网格（桌面 xl 仍 12 列） */}
      <section className="flex gap-px overflow-x-auto overscroll-x-contain rounded-xl border border-line bg-line/40 sm:grid sm:grid-cols-3 sm:overflow-visible lg:grid-cols-4 xl:grid-cols-12">
        {[
          <Metric key="sym" label="交易合约" value={summary?.symbol || '—'} />,
          <Metric
            key="px"
            label="主力价"
            value={lastPrice != null ? Number(lastPrice).toFixed(2) : '—'}
          />,
          <Metric
            key="net"
            label={session && !session.open && net !== 0 ? '净仓(留存)' : '净仓'}
            value={net}
            tip="券商账户确认净持仓（心跳刷新）"
          />,
          <Metric
            key="tgt"
            label="目标仓"
            value={target}
            tip="策略当前目标净仓；与净仓不同步时表示委托未确认或被抑制"
          />,
          <Metric
            key="eq"
            label="权益"
            value={`¥${money(focusedMetrics?.equity ?? focusedSummary?.account?.equity ?? 0)}`}
            tip="天勤模拟账户权益快照"
          />,
          <Metric
            key="mg"
            label="保证金"
            value={margin > 0 ? `¥${money(margin)}` : '—'}
            tip="按 Supabase/本地 ref_product_margin 品种保证金比例估算：价格×乘数×手数×比例（不采信天勤模拟保证金）"
          />,
          <Metric
            key="mr"
            label="风险度"
            value={marginRatio > 0 ? pct(marginRatio) : '—'}
            tip="占用保证金/权益；比例来自品种保证金表（如沪金 16%），不是天勤 risk_ratio"
          />,
          <Metric
            key="pnl"
            label="账户盈亏"
            value={money(pnl)}
            tone={pnl > 0 ? 'good' : pnl < 0 ? 'bad' : 'none'}
            tip="当前查看品种的独立模拟账户：权益−初始100万。当前无仓时，应与「已实现」一致。"
          />,
          <Metric
            key="book"
            label="浮动盈亏"
            value={money(
              Number(focusedMetrics?.unrealized_pnl ?? focusedSummary?.position?.unrealized_pnl ?? 0),
            )}
            tone={
              Number(focusedMetrics?.unrealized_pnl ?? 0) > 0
                ? 'good'
                : Number(focusedMetrics?.unrealized_pnl ?? 0) < 0
                  ? 'bad'
                  : 'none'
            }
            tip="当前查看品种的浮动盈亏，不含本策略其他品种"
          />,
          <Metric
            key="realized"
            label="已实现"
            value={money(realizedClosed)}
            tone={realizedClosed > 0 ? 'good' : realizedClosed < 0 ? 'bad' : 'none'}
            tip="账户口径：账户盈亏−浮动盈亏。不是历史表原始加总；补记成交已排除。"
          />,
          <Metric
            key="wr"
            label="胜率"
            value={pct(focusedMetrics?.win_rate ?? 0)}
            tip={`按完整开平回合统计（${focusedMetrics?.wins ?? 0}胜/${focusedMetrics?.trade_count ?? 0}回合）；依赖成交记录完整性`}
          />,
          <Metric
            key="dd"
            label="最大回撤"
            value={pct(focusedMetrics?.max_drawdown_pct ?? 0)}
            tip="基于账户权益快照曲线；快照过少时会低估"
          />,
        ].map((node, i) => (
          <div
            key={i}
            className="w-[7.75rem] shrink-0 bg-panel px-3 py-2.5 sm:w-auto sm:min-w-0"
          >
            {node}
          </div>
        ))}
      </section>

      {/* 持仓：当前 / 历史 */}
      <Section
        title="持仓"
        extra={
          <span className="text-faint">
            当前品种 {openPositions.length} · 历史 {historyRoundCount} 回合 / {positionHistory.length} 笔
          </span>
        }
      >
        <Alert
          className="mb-2"
          type="info"
          showIcon
          banner
          message="以下仅当前查看品种。切换沪银/螺纹不会继续显示沪金持仓与盈亏。"
        />
        {otherLegs.length ? (
          <Alert
            className="mb-2"
            type="success"
            showIcon
            banner
            message={`本策略其他品种仍持仓：${otherLegs
              .map((leg) => `${leg.label || leg.symbol_id || leg.instance_id} ${leg.net_position}手`)
              .join('、')}。点击顶部品种卡片可查看对应数据。`}
          />
        ) : null}
        <Tabs
          size="small"
          activeKey={positionTab}
          onChange={setPositionTab}
          items={[
            {
              key: 'current',
              label: `当前${openPositions.length ? ` ${openPositions.length}` : ''}`,
              children: openPositions.length ? (
                <div className="overflow-x-auto">
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(r) => `${r.symbol}-${r.side}`}
                  dataSource={openPositions}
                  scroll={{ x: 720 }}
                  columns={[
                    {
                      title: '合约',
                      dataIndex: 'symbol',
                      render: (v: string) => <span className="font-medium">{v}</span>,
                    },
                    {
                      title: '方向',
                      dataIndex: 'side_label',
                      width: 64,
                      render: (v: string, r) => (
                        <Tag color={r.side === 'LONG' ? 'success' : 'error'}>
                          {v || r.side}
                        </Tag>
                      ),
                    },
                    { title: '手数', dataIndex: 'lots', width: 64 },
                    {
                      title: '开仓均价',
                      dataIndex: 'average_entry_price',
                      render: (v: number | null | undefined) =>
                        v != null ? Number(v).toFixed(2) : '—',
                    },
                    {
                      title: '最新价',
                      dataIndex: 'last_price',
                      render: (v: number | null | undefined) =>
                        v != null ? Number(v).toFixed(2) : '—',
                    },
                    {
                      title: '浮动盈亏',
                      dataIndex: 'unrealized_pnl',
                      render: (v: number) => {
                        const n = Number(v || 0)
                        return (
                          <span
                            className={
                              n > 0 ? 'text-emerald-500' : n < 0 ? 'text-rose-500' : ''
                            }
                          >
                            ¥{money(n)}
                          </span>
                        )
                      },
                    },
                    {
                      title: '保证金',
                      dataIndex: 'margin',
                      render: (v: number, r) => {
                        const pctTxt =
                          r.margin_rate_pct != null
                            ? ` · ${Number(r.margin_rate_pct).toFixed(0)}%`
                            : ''
                        return v > 0 ? `¥${money(v)}${pctTxt}` : '—'
                      },
                    },
                    {
                      title: '止损/止盈',
                      key: 'stops',
                      render: (_: unknown, r) => {
                        const stop = r.stop_price
                        const take = r.take_price
                        if (stop == null && take == null) return '—'
                        const s = stop != null ? Number(stop).toFixed(2) : '—'
                        const t = take != null ? Number(take).toFixed(2) : '—'
                        return `${s} / ${t}`
                      },
                    },
                  ]}
                />
                </div>
              ) : (
                <p className="m-0 text-sm text-muted">
                  {net === 0 && pendingDesired != null && pendingDesired !== 0
                    ? `券商净仓为 0，开平仓委托待确认（目标 ${pendingDesired}）。成交前不算持仓，也不会进历史。`
                    : net === 0
                      ? '当前无持仓。'
                      : '等待持仓快照。'}
                </p>
              ),
            },
            {
              key: 'history',
              label: `历史 ${historyRoundCount} 回合`,
              children: positionHistory.length ? (
                <div className="overflow-x-auto">
                <Table
                  size="small"
                  pagination={historyPagination}
                  rowKey={(r, i) => r.leg_id || `${r.action}-${r.trade_time || ''}-${i}`}
                  dataSource={positionHistory}
                  scroll={{ x: 800 }}
                  summary={() => {
                    const fees = positionHistory.reduce(
                      (s, r) => s + Number(r.fees || 0),
                      0,
                    )
                    return (
                      <Table.Summary fixed>
                        <Table.Summary.Row>
                          <Table.Summary.Cell index={0} colSpan={6}>
                            <span className="text-faint">
                              平仓价差+结转 ¥{money(historyClosePnl)} = 账户已实现 ¥
                              {money(realizedClosed)}
                            </span>
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={6}>
                            <span
                              className={
                                realizedClosed > 0
                                  ? 'font-semibold text-emerald-500'
                                  : realizedClosed < 0
                                    ? 'font-semibold text-rose-500'
                                    : 'font-semibold'
                              }
                            >
                              ¥{money(realizedClosed)}
                            </span>
                          </Table.Summary.Cell>
                          <Table.Summary.Cell index={7}>
                            ¥{money(fees)}
                          </Table.Summary.Cell>
                        </Table.Summary.Row>
                      </Table.Summary>
                    )
                  }}
                  columns={[
                    {
                      title: '时间',
                      dataIndex: 'trade_time',
                      width: 148,
                      render: (v: string | null | undefined, r) => (
                        <span className="text-xs tabular-nums">
                          {formatLocalDateTime(v || r.closed_at || r.opened_at || '')}
                        </span>
                      ),
                    },
                    {
                      title: '开平',
                      dataIndex: 'action_label',
                      width: 64,
                      render: (v: string | undefined, r) => {
                        const label = v || (r.action === 'OPEN' ? '开仓' : '平仓')
                        const color =
                          r.source === 'account_residual' || label === '结转'
                            ? 'gold'
                            : r.action === 'OPEN'
                              ? 'blue'
                              : 'default'
                        return <Tag color={color}>{label}</Tag>
                      },
                    },
                    {
                      title: '方向',
                      dataIndex: 'side_label',
                      width: 56,
                      render: (v: string, r) => (
                        <Tag color={r.side === 'LONG' ? 'success' : 'error'}>
                          {v || r.side}
                        </Tag>
                      ),
                    },
                    {
                      title: '合约',
                      dataIndex: 'symbol',
                      ellipsis: true,
                      render: (v: string) => <span className="font-medium">{v}</span>,
                    },
                    { title: '手数', dataIndex: 'lots', width: 56 },
                    {
                      title: '价格',
                      dataIndex: 'price',
                      width: 80,
                      render: (v: number | undefined, r) =>
                        Number(v ?? r.entry_price ?? r.exit_price ?? 0).toFixed(2),
                    },
                    {
                      title: '盈亏',
                      dataIndex: 'realized_pnl',
                      width: 100,
                      render: (v: number, r) => {
                        const n = Number(v || 0)
                        if (r.action === 'OPEN' && r.source !== 'account_residual') {
                          return <span className="text-faint">¥0</span>
                        }
                        return (
                          <span
                            className={
                              n > 0 ? 'text-emerald-500' : n < 0 ? 'text-rose-500' : ''
                            }
                            title={r.note || undefined}
                          >
                            ¥{money(n)}
                          </span>
                        )
                      },
                    },
                    {
                      title: '手续费',
                      dataIndex: 'fees',
                      width: 72,
                      render: (v: number) => `¥${money(Number(v || 0))}`,
                    },
                  ]}
                />
                </div>
              ) : (
                <p className="m-0 text-sm text-muted">暂无已平仓记录。</p>
              ),
            },
          ]}
        />
      </Section>

      {/* 双图：<xl 用 Tab 切换内外盘；≥xl 并排（桌面不变） */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-ink">K 线对照</p>
        <div className="flex flex-wrap items-center gap-2">
          {showChartTabs ? (
            <Segmented
              size="small"
              value={chartPane}
              onChange={(v) => setChartPane(v as 'domestic' | 'overseas')}
              options={[
                { value: 'domestic', label: '内盘' },
                { value: 'overseas', label: '外盘' },
              ]}
            />
          ) : null}
          <Segmented
            size="small"
            value={chartTf}
            onChange={(v) => setChartTf(v as ChartTimeframe)}
            options={CHART_TIMEFRAMES.map((t) => ({
              value: t.value,
              label: t.label,
            }))}
          />
        </div>
      </div>
      <div
        className={`grid min-w-0 gap-3 ${overseas?.supported && !showChartTabs ? 'xl:grid-cols-2' : 'grid-cols-1'}`}
      >
        {!showChartTabs || chartPane === 'domestic' ? (
        <Section
          title={`内盘 · ${selectedSymbol?.name || '品种'}（天勤模拟）`}
          extra={
            <span className="tabular-nums text-faint">
              {bars?.trade_symbol || bars?.signal_symbol || '—'} ·{' '}
              {lastPrice != null ? Number(lastPrice).toFixed(2) : '—'}
            </span>
          }
        >
          {bars?.hint ? (
            <p className="mb-2 text-xs text-muted">{bars.hint}</p>
          ) : null}
          {domesticChart.bars.length ? (
            <MiniCandleChart
              key={`dom-${symbolId}-${chartTf}`}
              bars={domesticChart.bars}
              markers={domesticChart.markers}
              overlays={domesticChart.overlays}
              overlaySpecs={domesticChart.overlaySpecs}
              barMeta={domesticChart.barMeta}
              priceLines={domesticChart.priceLines}
              height={chartHeight}
              onLoadMore={() => {
                void loadMoreHistory()
              }}
            />
          ) : (
            <p className="py-16 text-center text-sm text-muted">暂无内盘 K 线</p>
          )}
          <p className="mt-1.5 text-xs text-faint">
            周期 {tfLabel}
            {chartTf !== '5m' ? '（由 5 分钟 K 线合成）' : ''} · {domesticChart.bars.length} 根
            {historyLoading ? ' · 加载更早历史…' : ''}
            {bars?.has_more ? ' · 向左拖动可加载更多' : ''}
          </p>
        </Section>
        ) : null}

        {overseas?.supported && (!showChartTabs || chartPane === 'overseas') ? (
          <Section
            title={`外盘对照 · ${overseas.pair?.name || '国际品种'}`}
            extra={
              <span className="tabular-nums text-faint">
                {overseas.pair?.display_symbol} ·{' '}
                {overseas.last_price != null
                  ? Number(overseas.last_price).toFixed(2)
                  : '—'}
                {overseas.source ? ` · ${overseas.source}` : ''}
                {overseas.lag_seconds != null && overseas.lag_seconds > 90
                  ? ` · 延迟≈${Math.round(overseas.lag_seconds / 60)}分钟`
                  : ''}
              </span>
            }
          >
            {overseas.hint ? (
              <p className="mb-2 text-xs text-amber-300/90">{overseas.hint}</p>
            ) : null}
            {overseas.lag_seconds != null && overseas.lag_seconds > 300 ? (
              <p className="mb-2 text-xs text-amber-300/90">
                外盘源延迟较大（约 {Math.round(overseas.lag_seconds / 60)}{' '}
                分钟）。已自动在东财/Yahoo 间选更新尖端；图表时间戳为 5 分钟
                K 线开盘时刻。
              </p>
            ) : null}
            {overseasChart.bars.length ? (
              <MiniCandleChart
                key={`os-${symbolId}-${chartTf}`}
                bars={overseasChart.bars}
                overlays={overseasChart.overlays}
                overlaySpecs={overseasChart.overlaySpecs}
                barMeta={overseasChart.barMeta}
                height={chartHeight}
                onLoadMore={() => {
                  void loadMoreOverseasHistory()
                }}
              />
            ) : (
              <p className="py-16 text-center text-sm text-muted">暂无外盘数据</p>
            )}
            <p className="mt-1.5 text-xs text-faint">
              周期 {tfLabel}
              {chartTf !== '5m' ? '（由 5 分钟 K 线合成）' : ''} · {overseasChart.bars.length}{' '}
              根
              {overseasHistoryLoading ? ' · 加载更早历史…' : ''}
              {overseas?.has_more ? ' · 向左拖动可加载更多' : ''}
            </p>
            {overseas.pair?.note ? (
              <p className="mt-1 text-xs leading-relaxed text-faint">{overseas.pair.note}</p>
            ) : null}
          </Section>
        ) : null}
      </div>

      {/* 思考链路 + 委托成交 */}
      <div className="grid min-w-0 gap-3 xl:grid-cols-2">
        <Section
          title="思考链路"
          extra={
            <span className="tabular-nums">
              {latest?.created_at
                ? `决策 ${formatLocalDateTime(latest.created_at)}`
                : null}
              {regimeConflict ? ' · 近端背离' : null}
            </span>
          }
        >
          {pipeline.length ? (
            <ol className="mb-3 grid gap-1.5 sm:grid-cols-2">
              {pipeline.map((p, i) => (
                <li
                  key={p.step}
                  className="rounded-lg border border-line/60 bg-surface/40 px-2.5 py-2"
                >
                  <p className="text-xs font-medium text-blue">
                    {i + 1}. {p.step}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-ink" title={p.detail}>
                    {p.detail}
                  </p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="mb-3 text-sm text-muted">暂无决策。启动后等待 5 分钟 K 收盘。</p>
          )}
          <Table
            size="small"
            rowKey="decision_id"
            pagination={decisionsPagination}
            dataSource={decisions}
            scroll={{ x: 640 }}
            locale={{ emptyText: '暂无决策记录' }}
            columns={[
              {
                title: '时间',
                dataIndex: 'created_at',
                width: 148,
                render: (v: string) => (
                  <span className="text-xs tabular-nums">{formatLocalDateTime(v)}</span>
                ),
              },
              {
                title: '策略状态',
                dataIndex: 'regime',
                width: 96,
                render: (v: string) => regimeLabel(v),
              },
              {
                title: (
                  <Tooltip title="legacy 信号分 ∈ [-3,3]：格兰维尔+量能+KDJ 等合成后截断">
                    <span className="cursor-help underline decoration-dotted">信号分</span>
                  </Tooltip>
                ),
                dataIndex: 'legacy_signal',
                width: 64,
              },
              {
                title: '动作',
                dataIndex: 'applied_action',
                width: 110,
                render: (v: string, r) =>
                  tradeActionLabel({
                    action: v,
                    from: r.target_before,
                    to: r.target_after,
                    signal: r.legacy_signal,
                  }),
              },
              {
                title: (
                  <Tooltip title="策略目标仓 before→after；不是券商净仓。维持目标且 1→1 表示策略仍想持有1手，本根不改目标；若净仓为0会提示脱节并在后台重试对齐">
                    <span className="cursor-help underline decoration-dotted">目标</span>
                  </Tooltip>
                ),
                key: 'tgt',
                width: 72,
                render: (_, r) => `${r.target_before}→${r.target_after}`,
              },
              {
                title: '风控',
                key: 'risk',
                width: 64,
                render: (_, r) => riskActionLabel(r.risk?.action),
              },
              {
                title: (
                  <Tooltip title="下单相关理由：风控拒绝/缩量/停机，或止损止盈等；不含指标来源标签">
                    <span className="cursor-help underline decoration-dotted">理由</span>
                  </Tooltip>
                ),
                key: 'reason',
                width: 120,
                ellipsis: true,
                render: (_, r) => {
                  const text = decisionReasonText(r)
                  return (
                    <span className="text-xs text-muted" title={text}>
                      {text}
                    </span>
                  )
                },
              },
            ]}
          />
        </Section>

        <Section title="委托与成交">
          <Alert
            className="mb-2"
            type="info"
            showIcon
            banner
            message={`成交 ${fills.length} 笔（真实约 ${liveFills}，补记 ${backfillFills.length}）。补记是系统事后写的流水，不进天勤权益；看账户盈亏请忽略「补记」行。历史回合 ≈ 真实成交开平配对，不是 1:1 对照成交条数。`}
          />
          <Tabs
            size="small"
            items={[
              {
                key: 'intents',
                label: `意图 ${intents.length}`,
                children: (
                  <Table
                    size="small"
                    rowKey="intent_id"
                    pagination={intentsPagination}
                    dataSource={intents}
                    scroll={{ x: 480 }}
                    columns={[
                      {
                        title: '时间',
                        dataIndex: 'created_at',
                        width: 148,
                        render: (v: string) => (
                          <span className="text-xs tabular-nums">
                            {formatLocalDateTime(v)}
                          </span>
                        ),
                      },
                      { title: '合约', dataIndex: 'symbol', width: 110, ellipsis: true },
                      { title: '当前', dataIndex: 'current_position', width: 52 },
                      { title: '目标', dataIndex: 'desired_position', width: 52 },
                      {
                        title: '动作',
                        key: 'intent_action',
                        width: 100,
                        ellipsis: true,
                        render: (_, r) => {
                          const action = intentActionCode(r)
                          const input = {
                            action,
                            from: r.current_position,
                            to: r.desired_position,
                          }
                          const label = tradeActionLabel(input)
                          const color = tradeActionTagColor(input)
                          return color ? (
                            <Tag color={color}>{label}</Tag>
                          ) : (
                            <Tag>{label}</Tag>
                          )
                        },
                      },
                      {
                        title: '状态',
                        dataIndex: 'status',
                        width: 72,
                        render: (v: string) => intentStatusLabel(v),
                      },
                    ]}
                  />
                ),
              },
              {
                key: 'fills',
                label: `成交 ${fills.length}`,
                children: (
                  <Table
                    size="small"
                    rowKey="fill_id"
                    pagination={fillsPagination}
                    dataSource={fills}
                    scroll={{ x: 1000 }}
                    columns={[
                      {
                        title: '时间',
                        dataIndex: 'trade_time',
                        width: 148,
                        render: (v: string) => (
                          <span className="text-xs tabular-nums">
                            {formatLocalDateTime(v)}
                          </span>
                        ),
                      },
                      {
                        title: '来源',
                        key: 'fill_source',
                        width: 64,
                        render: (_: unknown, r) => {
                          const src =
                            r.fill_source ||
                            (r.fill_id?.startsWith('fill-backfill-')
                              ? 'intent_chain_backfill'
                              : null)
                          if (src === 'intent_chain_backfill') {
                            return <Tag color="warning">补记</Tag>
                          }
                          return <Tag>真实</Tag>
                        },
                      },
                      { title: '合约', dataIndex: 'symbol', width: 110, ellipsis: true },
                      {
                        title: '方向',
                        dataIndex: 'side',
                        width: 48,
                        render: (v: string) => sideLabel(v),
                      },
                      {
                        title: '价格',
                        dataIndex: 'price',
                        width: 72,
                        render: (v: number) => Number(v).toFixed(2),
                      },
                      { title: '手', dataIndex: 'qty', width: 40 },
                      {
                        title: '费',
                        dataIndex: 'fee',
                        width: 52,
                        render: (v: number) => Number(v || 0).toFixed(1),
                      },
                      {
                        title: '信号',
                        dataIndex: 'legacy_signal',
                        width: 48,
                        render: (v: number | null | undefined) =>
                          v == null ? '—' : String(v),
                      },
                      {
                        title: '动作',
                        dataIndex: 'applied_action',
                        width: 120,
                        ellipsis: true,
                        render: (v: string | null | undefined, r) => {
                          const from =
                            r.current_position ?? r.target_before ?? null
                          const to =
                            r.desired_position ?? r.target_after ?? null
                          const input = {
                            action: v,
                            from,
                            to,
                            signal: r.legacy_signal,
                          }
                          const label = tradeActionLabel(input)
                          if (label === '—') return '—'
                          const color = tradeActionTagColor(input)
                          return color ? (
                            <Tag color={color}>{label}</Tag>
                          ) : (
                            <Tag>{label}</Tag>
                          )
                        },
                      },
                      {
                        title: (
                          <Tooltip title="外盘信号空间的入场/止损/止盈；成交价列为内盘真实成交">
                            入场(信号)
                          </Tooltip>
                        ),
                        dataIndex: 'entry_price',
                        width: 88,
                        render: (v: number | null | undefined, r) => {
                          if (
                            r.applied_action === 'STOP_LOSS' ||
                            r.applied_action === 'TAKE_PROFIT' ||
                            r.applied_action === 'BOOT_FLATTEN' ||
                            r.applied_action === 'FLAT_EXIT' ||
                            r.applied_action === 'EXIT' ||
                            r.applied_action === 'FLAT'
                          ) {
                            return '—'
                          }
                          return v != null ? Number(v).toFixed(2) : '—'
                        },
                      },
                      {
                        title: (
                          <Tooltip title="外盘信号空间止损价">止损(信号)</Tooltip>
                        ),
                        dataIndex: 'stop_price',
                        width: 88,
                        render: (v: number | null | undefined, r) => {
                          if (
                            r.applied_action === 'STOP_LOSS' ||
                            r.applied_action === 'TAKE_PROFIT' ||
                            r.applied_action === 'BOOT_FLATTEN' ||
                            r.applied_action === 'FLAT_EXIT' ||
                            r.applied_action === 'EXIT' ||
                            r.applied_action === 'FLAT'
                          ) {
                            return '—'
                          }
                          return v != null ? Number(v).toFixed(2) : '—'
                        },
                      },
                      {
                        title: (
                          <Tooltip title="外盘信号空间止盈价">止盈(信号)</Tooltip>
                        ),
                        dataIndex: 'take_price',
                        width: 88,
                        render: (v: number | null | undefined, r) => {
                          if (
                            r.applied_action === 'STOP_LOSS' ||
                            r.applied_action === 'TAKE_PROFIT' ||
                            r.applied_action === 'BOOT_FLATTEN' ||
                            r.applied_action === 'FLAT_EXIT' ||
                            r.applied_action === 'EXIT' ||
                            r.applied_action === 'FLAT'
                          ) {
                            return '—'
                          }
                          return v != null ? Number(v).toFixed(2) : '—'
                        },
                      },
                      {
                        title: '状态',
                        dataIndex: 'regime',
                        width: 88,
                        ellipsis: true,
                        render: (v: string | null | undefined) => regimeLabel(v),
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        </Section>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex w-full min-w-0 flex-col gap-1 sm:w-auto">
      <span className="text-xs text-faint">{label}</span>
      {children}
    </label>
  )
}
