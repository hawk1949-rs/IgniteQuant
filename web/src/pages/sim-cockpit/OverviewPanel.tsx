import { useMemo, type ReactNode } from 'react'
import {
  Select,
  Tag,
  Alert,
  Button,
  Table,
  Tabs,
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
}: {
  label: string
  value: string | number
  tone?: 'good' | 'bad' | 'none'
}) {
  const color =
    tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : 'text-ink'
  return (
    <div className="min-w-0">
      <p className="text-[11px] leading-none text-faint">{label}</p>
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
      <div className="flex items-center justify-between gap-3 border-b border-line/70 px-3.5 py-2">
        <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>
        {extra ? <div className="shrink-0 text-xs text-muted">{extra}</div> : null}
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
  const lastPrice =
    summary?.last_price ??
    bars?.last_price ??
    (bars?.bars?.length ? bars.bars[bars.bars.length - 1].close : null)
  const pnl = metrics?.pnl ?? 0
  const net =
    summary?.position?.net_position ?? Number(summary?.payload?.confirmed_net ?? 0)
  const target = Number(summary?.payload?.current_target ?? 0)
  const chartCtx = bars?.chart_context
  const displayRegime = chartCtx?.regime || latest?.regime
  const shortBias = chartCtx?.short_bias
  const regimeConflict = Boolean(chartCtx?.conflict)
  const session = summary?.market_session || bars?.market_session
  const positionNote = summary?.position_note

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
          detail: `${latest.target_before} → ${latest.target_after} · ${actionLabel(latest.applied_action)}`,
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

  return (
    <div className="flex flex-col gap-3">
      {/* 控制条 */}
      <section className="rounded-xl border border-line bg-panel/90 px-3.5 py-3">
        <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
          <Field label="框架">
            <Select
              size="small"
              className="min-w-[9.5rem]"
              value={framework}
              onChange={setFramework}
              options={(catalog?.frameworks || []).map((f) => ({
                value: f.id,
                label: f.enabled ? f.name : `${f.name}（即将支持）`,
                disabled: !f.enabled,
              }))}
            />
          </Field>
          <Field label="品种">
            <Select
              size="small"
              className="min-w-[10rem]"
              value={symbolId}
              onChange={setSymbolId}
              options={(catalog?.symbols || []).map((s) => ({
                value: s.id,
                label: `${s.name}`,
              }))}
            />
          </Field>
          <Field label="策略">
            <Select
              size="small"
              className="min-w-[8.5rem]"
              value={strategyId}
              onChange={setStrategyId}
              options={(catalog?.strategies || []).map((s) => ({
                value: s.id,
                label: s.ready ? s.name : `${s.name}（占位）`,
                disabled: !s.ready,
              }))}
            />
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
            <Tooltip title="品种来自项目目录；K 线优先读本地 market_cache；页面按 5 分钟自动刷新。">
              <span className="cursor-help text-[11px] text-faint underline decoration-dotted">
                说明
              </span>
            </Tooltip>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-1.5 pb-0.5">
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
            message={`${session.label || '非交易时段'}：K 线可能停更；账户持仓/权益仍来自天勤模拟账户快照。`}
          />
        ) : null}
      </section>

      {/* 指标条 */}
      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line/40 sm:grid-cols-4 lg:grid-cols-8">
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
          />,
          <Metric key="tgt" label="目标仓" value={target} />,
          <Metric key="eq" label="权益" value={`¥${money(metrics?.equity ?? 0)}`} />,
          <Metric
            key="pnl"
            label="盈亏"
            value={money(pnl)}
            tone={pnl > 0 ? 'good' : pnl < 0 ? 'bad' : 'none'}
          />,
          <Metric key="wr" label="胜率" value={pct(metrics?.win_rate ?? 0)} />,
          <Metric key="dd" label="最大回撤" value={pct(metrics?.max_drawdown_pct ?? 0)} />,
        ].map((node, i) => (
          <div key={i} className="bg-panel px-3 py-2.5">
            {node}
          </div>
        ))}
      </section>

      {/* 双图 */}
      <div
        className={`grid gap-3 ${overseas?.supported ? 'xl:grid-cols-2' : 'grid-cols-1'}`}
      >
        <Section
          title={`内盘 5 分钟 · ${selectedSymbol?.name || '品种'}（天勤模拟）`}
          extra={
            <span>
              {bars?.trade_symbol || bars?.signal_symbol || '—'} ·{' '}
              {lastPrice != null ? Number(lastPrice).toFixed(2) : '—'}
            </span>
          }
        >
          {bars?.hint ? (
            <p className="mb-2 text-xs text-muted">{bars.hint}</p>
          ) : null}
            {bars?.bars?.length ? (
              <MiniCandleChart
                key={`dom-${symbolId}-${bars.bars.length}`}
                bars={bars.bars}
                markers={bars.markers}
                height={240}
              />
            ) : (
              <p className="py-10 text-center text-sm text-muted">暂无内盘 K 线</p>
            )}
          </Section>

        {overseas?.supported ? (
          <Section
            title={`外盘对照 · ${overseas.pair?.name || '国际品种'}`}
            extra={
              <span>
                {overseas.pair?.display_symbol} ·{' '}
                {overseas.last_price != null ? Number(overseas.last_price).toFixed(2) : '—'}
              </span>
            }
          >
            {overseas.hint ? (
              <p className="mb-2 text-xs text-amber-300/90">{overseas.hint}</p>
            ) : null}
            {overseas.bars?.length ? (
              <MiniCandleChart
                key={`os-${symbolId}-${overseas.bars.length}-${overseas.last_price ?? 0}`}
                bars={overseas.bars}
                height={240}
              />
            ) : (
              <p className="py-10 text-center text-sm text-muted">暂无外盘数据</p>
            )}
            {overseas.pair?.note ? (
              <p className="mt-2 text-[11px] leading-relaxed text-faint">{overseas.pair.note}</p>
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
            pagination={{ pageSize: 6, size: 'small' }}
            dataSource={decisions}
            scroll={{ x: 520 }}
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
              { title: '分', dataIndex: 'legacy_signal', width: 44 },
              {
                title: '动作',
                dataIndex: 'applied_action',
                width: 80,
                render: (v: string) => actionLabel(v),
              },
              {
                title: '目标',
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
                    pagination={{ pageSize: 6, size: 'small' }}
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
                    pagination={{ pageSize: 6, size: 'small' }}
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
