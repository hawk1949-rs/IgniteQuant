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
import { useSimCockpit } from './SimCockpitContext'
import { MiniCandleChart } from './MiniCandleChart'
import {
  actionLabel,
  qualityLabel,
  regimeLabel,
  riskActionLabel,
  shortBiasLabel,
  statusLabel,
} from './labels'
import { startSimSession } from '@/lib/api'
import { formatLocalDateTime } from './time'
import { useSimTablePagination } from './tablePagination'
import { HeartbeatBoard } from './HeartbeatBoard'
import {
  CHART_TIMEFRAMES,
  aggregateBars,
  aggregateMarkers,
  type ChartTimeframe,
} from './chartTimeframe'

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`
}

function money(n: number) {
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

const INTENT_STATUS: Record<string, string> = {
  PENDING: '待处理',
  SUBMITTED: '已提交',
  FILLED: '已成交',
  PARTIAL: '部分成交',
  CANCELLED: '已撤销',
  REJECTED: '已拒绝',
  FAILED: '失败',
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
      <p className="text-[11px] leading-none text-faint">{labelNode}</p>
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
    setFramework,
    strategyId,
    setStrategyId,
    symbolId,
    setSymbolId,
    summary,
    metrics,
    decisions,
    intents,
    fills,
    bars,
    overseas,
    error,
    warn,
    loading,
    refresh,
    replayAt,
    replay,
    starting,
    setStarting,
  } = useSimCockpit()

  const latest = replay?.decision || decisions[0]
  const status = summary?.status || 'IDLE'
  const statusText = summary?.status_label || statusLabel(status)
  const processRunning = Boolean(summary?.process_running)
  const selectedSymbol = catalog?.symbols?.find((s) => s.id === symbolId)
  const launcherSymbolId =
    catalog?.launchers?.find((l) => l.instance_id === instanceId)?.symbol_id ?? null
  const symbolMismatch = Boolean(launcherSymbolId && launcherSymbolId !== symbolId)
  const lastPrice =
    summary?.last_price ??
    bars?.last_price ??
    (bars?.bars?.length ? bars.bars[bars.bars.length - 1].close : null)
  const pnl = metrics?.pnl ?? 0
  // Prefer live strategy_state.confirmed_net (heartbeat); position snapshot was historically boot-only.
  const confirmedNet = summary?.payload?.confirmed_net
  const net =
    confirmedNet != null && confirmedNet !== ''
      ? Number(confirmedNet)
      : (summary?.position?.net_position ?? 0)
  const target = Number(summary?.payload?.current_target ?? 0)
  const margin = Number(summary?.account?.margin ?? 0)
  const marginRatio = Number(summary?.account?.margin_ratio ?? 0)
  const pendingDesired =
    summary?.payload?.pending_desired != null && summary.payload.pending_desired !== ''
      ? Number(summary.payload.pending_desired)
      : null
  const targetNetDesync = net !== target
  const chartCtx = bars?.chart_context
  const displayRegime = chartCtx?.regime || latest?.regime
  const shortBias = chartCtx?.short_bias
  const regimeConflict = Boolean(chartCtx?.conflict)
  const session = summary?.market_session || bars?.market_session
  const positionNote = summary?.position_note
  const decisionsPagination = useSimTablePagination('decisions', 10, decisions.length)
  const intentsPagination = useSimTablePagination('intents', 10, intents.length)
  const fillsPagination = useSimTablePagination('fills', 10, fills.length)
  const [chartTf, setChartTf] = useState<ChartTimeframe>('5m')

  const domesticChart = useMemo(() => {
    const raw = bars?.bars || []
    const agg = aggregateBars(raw, chartTf)
    return {
      bars: agg,
      markers: aggregateMarkers(bars?.markers, agg),
    }
  }, [bars?.bars, bars?.markers, chartTf])

  const overseasChart = useMemo(() => {
    const raw = overseas?.bars || []
    return { bars: aggregateBars(raw, chartTf) }
  }, [overseas?.bars, chartTf])

  const tfLabel = CHART_TIMEFRAMES.find((t) => t.value === chartTf)?.label || chartTf

  const launcherOptions = useMemo(() => {
    const fromCatalog = catalog?.launchers || []
    if (fromCatalog.length) {
      return fromCatalog.map((l) => ({
        value: l.instance_id,
        label: l.label,
      }))
    }
    return [{ value: 'falcon_au_sim', label: 'Falcon 沪金天勤模拟' }]
  }, [catalog])

  const onStart = async () => {
    setStarting(true)
    try {
      const res = await startSimSession(instanceId)
      message.success(res.message || '已发出启动指令')
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setStarting(false)
    }
  }

  const factorDetail = (() => {
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
            latest.score_parts ? ` · ${JSON.stringify(latest.score_parts)}` : ''
          }`,
        },
        {
          step: '目标',
          detail: `${latest.target_before} → ${latest.target_after} · ${actionLabel(latest.applied_action)}${
            targetNetDesync ? ` · 净仓仍为 ${net}` : ''
          }`,
        },
        {
          step: '风控',
          detail: latest.risk
            ? `${riskActionLabel(latest.risk.action)} · 批准 ${latest.risk.approved_position}`
            : '未触发事前风控',
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
            detail: session?.open ? '交易时段' : '非交易时段（仅观察账户状态）',
          },
        ]
      : []

  const symbolOptions = catalog?.symbols || []

  return (
    <div className="flex flex-col gap-3">
      {/* 品种主筛选 */}
      <section className="rounded-xl border border-line bg-panel/90 px-3.5 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-medium tracking-wide text-faint">品种</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {symbolOptions.map((s) => {
                const active = s.id === symbolId
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setSymbolId(s.id)}
                    className={`rounded-lg border px-3.5 py-2 text-left transition-colors ${
                      active
                        ? 'border-blue bg-blue-soft text-blue shadow-sm'
                        : 'border-line bg-surface/60 text-muted hover:border-blue/50 hover:text-ink'
                    }`}
                  >
                    <span className="block text-sm font-semibold leading-none">{s.name}</span>
                    <span className="mt-1 block text-[11px] tabular-nums text-faint">
                      {s.signal_symbol || s.id}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-[11px] text-faint">当前对照</p>
            <p className="mt-1 text-base font-semibold text-ink">
              {selectedSymbol?.name || symbolId}
            </p>
            <p className="mt-0.5 text-[11px] tabular-nums text-faint">
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
          <p className="text-[11px] font-medium tracking-wide text-faint">运行配置</p>
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
        <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
          <Field label="框架">
            <Tooltip title="跟随运行会话配置，暂不可单独修改">
              <Select
                size="small"
                className="min-w-[9.5rem]"
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
            <Tooltip title="跟随运行会话配置，回测/启动均使用 launcher 绑定策略">
              <Select
                size="small"
                className="min-w-[8.5rem]"
                value={strategyId}
                disabled
                options={(catalog?.strategies || []).map((s) => ({
                  value: s.id,
                  label: s.ready ? s.name : `${s.name}（占位）`,
                }))}
              />
            </Tooltip>
          </Field>
          <Field label="运行会话">
            <Select
              size="small"
              className="min-w-[11rem]"
              value={instanceId}
              onChange={setInstanceId}
              options={launcherOptions}
            />
          </Field>
          <div className="flex items-center gap-2 pb-0.5">
            <Button
              type="primary"
              size="small"
              onClick={() => void onStart()}
              loading={starting}
              disabled={processRunning}
            >
              {processRunning ? '已在运行' : '启动'}
            </Button>
            <Button size="small" onClick={() => void refresh()} loading={loading}>
              刷新
            </Button>
            <Tooltip title="品种切换只改图表对照；内盘实时 K 线与成交标记来自当前「运行会话」对应品种的天勤快照。会话是沪金时，选螺纹钢不会继续画沪金图。">
              <span className="cursor-help text-[11px] text-faint underline decoration-dotted">
                说明
              </span>
            </Tooltip>
          </div>
        </div>
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
            message={`${session.label || '非交易时段'}：K 线可能停更；模拟进程仍在后台心跳，不会因关页面而停止。账户持仓/权益来自天勤快照。`}
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

      {/* 指标条 */}
      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line/40 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-10">
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
            value={`¥${money(metrics?.equity ?? summary?.account?.equity ?? 0)}`}
            tip="天勤模拟账户权益快照"
          />,
          <Metric
            key="mg"
            label="保证金"
            value={margin > 0 ? `¥${money(margin)}` : '—'}
            tip="天勤 account.margin；模拟盘保证金率可能低于交易所实盘"
          />,
          <Metric
            key="mr"
            label="风险度"
            value={marginRatio > 0 ? pct(marginRatio) : '—'}
            tip="天勤 account.risk_ratio（占用保证金/权益），不是交易所官方保证金率"
          />,
          <Metric
            key="pnl"
            label="盈亏"
            value={money(pnl)}
            tone={pnl > 0 ? 'good' : pnl < 0 ? 'bad' : 'none'}
            tip="相对初始资金 100 万的权益差"
          />,
          <Metric
            key="wr"
            label="胜率"
            value={pct(metrics?.win_rate ?? 0)}
            tip={`按完整开平回合统计（${metrics?.wins ?? 0}胜/${metrics?.trade_count ?? 0}回合）；依赖成交记录完整性`}
          />,
          <Metric
            key="dd"
            label="最大回撤"
            value={pct(metrics?.max_drawdown_pct ?? 0)}
            tip="基于账户权益快照曲线；快照过少时会低估"
          />,
        ].map((node, i) => (
          <div key={i} className="bg-panel px-3 py-2.5">
            {node}
          </div>
        ))}
      </section>

      {/* 双图 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-ink">K 线对照</p>
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
      <div
        className={`grid gap-3 ${overseas?.supported ? 'xl:grid-cols-2' : 'grid-cols-1'}`}
      >
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
              height={420}
            />
          ) : (
            <p className="py-16 text-center text-sm text-muted">暂无内盘 K 线</p>
          )}
          <p className="mt-1.5 text-[11px] text-faint">
            周期 {tfLabel}
            {chartTf !== '5m' ? '（由 5 分钟 K 线合成）' : ''} · {domesticChart.bars.length} 根
          </p>
        </Section>

        {overseas?.supported ? (
          <Section
            title={`外盘对照 · ${overseas.pair?.name || '国际品种'}`}
            extra={
              <span className="tabular-nums text-faint">
                {overseas.pair?.display_symbol} ·{' '}
                {overseas.last_price != null
                  ? Number(overseas.last_price).toFixed(2)
                  : '—'}
              </span>
            }
          >
            {overseas.hint ? (
              <p className="mb-2 text-xs text-amber-300/90">{overseas.hint}</p>
            ) : null}
            {overseasChart.bars.length ? (
              <MiniCandleChart
                key={`os-${symbolId}-${chartTf}`}
                bars={overseasChart.bars}
                height={420}
              />
            ) : (
              <p className="py-16 text-center text-sm text-muted">暂无外盘数据</p>
            )}
            <p className="mt-1.5 text-[11px] text-faint">
              周期 {tfLabel}
              {chartTf !== '5m' ? '（由 5 分钟 K 线合成）' : ''} · {overseasChart.bars.length}{' '}
              根
            </p>
            {overseas.pair?.note ? (
              <p className="mt-1 text-[11px] leading-relaxed text-faint">{overseas.pair.note}</p>
            ) : null}
          </Section>
        ) : null}
      </div>

      {/* 思考链路 + 委托成交 */}
      <div className="grid gap-3 xl:grid-cols-2">
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
                  <p className="text-[11px] font-medium text-blue">
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
            scroll={{ x: 520 }}
            locale={{ emptyText: '暂无决策记录' }}
            columns={[
              {
                title: '时间',
                dataIndex: 'created_at',
                width: 148,
                render: (v: string) => (
                  <span className="text-[11px] tabular-nums">{formatLocalDateTime(v)}</span>
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
                width: 80,
                render: (v: string) => actionLabel(v),
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
            ]}
          />
        </Section>

        <Section title="委托与成交">
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
                          <span className="text-[11px] tabular-nums">
                            {formatLocalDateTime(v)}
                          </span>
                        ),
                      },
                      { title: '合约', dataIndex: 'symbol', width: 110, ellipsis: true },
                      { title: '当前', dataIndex: 'current_position', width: 52 },
                      { title: '目标', dataIndex: 'desired_position', width: 52 },
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
                    scroll={{ x: 480 }}
                    columns={[
                      {
                        title: '时间',
                        dataIndex: 'trade_time',
                        width: 148,
                        render: (v: string) => (
                          <span className="text-[11px] tabular-nums">
                            {formatLocalDateTime(v)}
                          </span>
                        ),
                      },
                      { title: '合约', dataIndex: 'symbol', width: 110, ellipsis: true },
                      {
                        title: '方向',
                        dataIndex: 'side',
                        width: 48,
                        render: (v: string) => sideLabel(v),
                      },
                      { title: '价格', dataIndex: 'price', width: 80 },
                      { title: '手', dataIndex: 'qty', width: 44 },
                      { title: '费', dataIndex: 'fee', width: 56 },
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
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-faint">{label}</span>
      {children}
    </label>
  )
}
