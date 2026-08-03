import { useEffect, useMemo, useState, type MouseEvent } from 'react'
import {
  App,
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Flex,
  Input,
  InputNumber,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  PlayCircleOutlined,
  RedoOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { fetchCatalog, runBacktest, type RunRecord, type Strategy } from '@/lib/api'
import {
  BACKTEST_ENGINE_OPTIONS,
  CHART_METRIC_OPTIONS,
  CHART_PERIOD_OPTIONS,
  DEFAULT_ACCOUNT,
  DEFAULT_PIPELINE,
  PIPELINE_OPTIONS,
  PIPELINE_STEPS,
  WORKBENCH_SYMBOLS,
  aggregateSeries,
  chartStrokeColor,
  enrichEquitySeries,
  formatMetricValue,
  loadAssemblySnapshots,
  loadBacktestRuns,
  metricValue,
  newId,
  persistAssemblySnapshots,
  persistBacktestRuns,
  type AccountConfig,
  type AssemblySnapshot,
  type BacktestEngine,
  type BacktestRun,
  type ChartMetric,
  type ChartPeriod,
  type KpiSet,
  type PipelineNodeKey,
  type SeriesPoint,
  type WorkbenchTrade,
} from './workbench-data'

const { Text } = Typography
const PAGE_SIZE = 10
const DEFAULT_STRATEGY_ID = 'falcon_v2'

const FALLBACK_STRATEGIES: Strategy[] = [
  {
    id: 'falcon_v2',
    name: 'Falcon v2',
    description: 'ADX 行情状态 + 格兰维尔/量能/KDJ 评分 + ATR 止盈止损（5 分钟）',
    ready: true,
  },
  {
    id: 'vwap_au',
    name: 'VWAP（沪金）',
    description: 'VWAP 偏离回归（看板内暂作占位）',
    ready: false,
  },
]

function MetricChart({
  series,
  metric,
}: {
  series: SeriesPoint[]
  metric: ChartMetric
}) {
  const [hover, setHover] = useState<{ idx: number; x: number; y: number } | null>(
    null,
  )

  if (series.length < 2) {
    return (
      <Flex align="center" justify="center" style={{ height: 240 }}>
        <Text type="secondary">暂无曲线。开始测试或选择历史回测结果后显示。</Text>
      </Flex>
    )
  }

  const w = 720
  const h = 260
  const pad = { t: 20, r: 16, b: 36, l: 58 }
  const vals = series.map((p) => metricValue(p, metric))
  let min = Math.min(...vals)
  let max = Math.max(...vals)
  // Keep zero in view for return / drawdown charts
  if (metric === 'ror' || metric === 'drawdown' || metric === 'pnl') {
    min = Math.min(min, 0)
    max = Math.max(max, 0)
  }
  const span = Math.max(max - min, metric === 'ror' || metric === 'drawdown' ? 1e-6 : 1)
  const xAt = (i: number) => pad.l + (i / (series.length - 1)) * (w - pad.l - pad.r)
  const yAt = (v: number) => pad.t + (1 - (v - min) / span) * (h - pad.t - pad.b)
  const stroke = chartStrokeColor(metric)
  const path = series
    .map(
      (p, i) =>
        `${i === 0 ? 'M' : 'L'} ${xAt(i).toFixed(1)} ${yAt(metricValue(p, metric)).toFixed(1)}`,
    )
    .join(' ')
  const baselineY = yAt(0)
  const area =
    metric === 'drawdown' || metric === 'ror' || metric === 'pnl'
      ? `${path} L ${xAt(series.length - 1).toFixed(1)} ${baselineY.toFixed(1)} L ${pad.l} ${baselineY.toFixed(1)} Z`
      : `${path} L ${xAt(series.length - 1).toFixed(1)} ${h - pad.b} L ${pad.l} ${h - pad.b} Z`
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((r) => min + span * (1 - r))
  const metricLabel =
    CHART_METRIC_OPTIONS.find((o) => o.id === metric)?.label ?? metric

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * w
    let best = 0
    let bestDist = Infinity
    for (let i = 0; i < series.length; i++) {
      const d = Math.abs(xAt(i) - px)
      if (d < bestDist) {
        bestDist = d
        best = i
      }
    }
    setHover({
      idx: best,
      x: xAt(best),
      y: yAt(metricValue(series[best], metric)),
    })
  }

  return (
    <div style={{ position: 'relative', width: '100%', overflowX: 'auto' }}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        style={{ height: 256, width: '100%', minWidth: 520 }}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((tv) => (
          <g key={String(tv)}>
            <line
              x1={pad.l}
              x2={w - pad.r}
              y1={yAt(tv)}
              y2={yAt(tv)}
              stroke="rgba(180,200,230,0.35)"
              strokeDasharray="4 4"
            />
            <text
              x={pad.l - 8}
              y={yAt(tv) + 4}
              textAnchor="end"
              fill="#C8D0DC"
              fontSize="11"
            >
              {formatMetricValue(tv, metric)}
            </text>
          </g>
        ))}
        {(metric === 'ror' || metric === 'drawdown' || metric === 'pnl') && min < 0 && max > 0 && (
          <line
            x1={pad.l}
            x2={w - pad.r}
            y1={baselineY}
            y2={baselineY}
            stroke="rgba(245,245,247,0.45)"
            strokeWidth={1}
          />
        )}
        <path d={area} fill={stroke} fillOpacity={0.12} />
        <path d={path} fill="none" stroke={stroke} strokeWidth="2.25" strokeLinecap="round" />
        {hover && (
          <g>
            <line
              x1={hover.x}
              x2={hover.x}
              y1={pad.t}
              y2={h - pad.b}
              stroke="rgba(245,245,247,0.35)"
              strokeDasharray="3 3"
            />
            <circle
              cx={hover.x}
              cy={hover.y}
              r={5}
              fill="#F5F5F7"
              stroke={stroke}
              strokeWidth={2}
            />
          </g>
        )}
        <text x={pad.l} y={h - 12} fill="#C8D0DC" fontSize="11">
          {series[0].t}
        </text>
        <text x={w - pad.r} y={h - 12} textAnchor="end" fill="#C8D0DC" fontSize="11">
          {series[series.length - 1].t}
        </text>
      </svg>
      {hover && series[hover.idx] && (
        <Card
          size="small"
          style={{
            position: 'absolute',
            left: `min(${(hover.x / w) * 100}%, calc(100% - 190px))`,
            top: 8,
            pointerEvents: 'none',
            minWidth: 160,
            boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          }}
        >
          <Text strong>{series[hover.idx].t}</Text>
          <div>
            <Text type="secondary">{metricLabel} </Text>
            <Text style={{ color: stroke }}>
              {formatMetricValue(metricValue(series[hover.idx], metric), metric)}
            </Text>
          </div>
          {metric !== 'equity' && (
            <div>
              <Text type="secondary">总资产 </Text>
              <Text>{Math.round(series[hover.idx].equity).toLocaleString('zh-CN')}</Text>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}

function pct(n: number, digits = 2) {
  return `${(n * 100).toFixed(digits)}%`
}

function KpiGrid({ kpis }: { kpis: KpiSet | null }) {
  const items = [
    { k: '收益率', v: kpis ? pct(kpis.ror) : '—', tone: (kpis?.ror ?? 0) >= 0 ? '#30D158' : '#FF453A' },
    { k: '最大回撤', v: kpis ? pct(kpis.maxDrawdown) : '—', tone: '#FF453A' },
    { k: '夏普', v: kpis ? kpis.sharpe.toFixed(2) : '—', tone: '#F5F5F7' },
    { k: '成交笔数', v: kpis ? String(kpis.tradeCount) : '—', tone: '#F5F5F7' },
    { k: '胜率', v: kpis ? pct(kpis.winRate) : '—', tone: '#F5F5F7' },
    { k: '盈亏比', v: kpis ? kpis.profitLossRatio.toFixed(2) : '—', tone: '#F5F5F7' },
    {
      k: '年化',
      v: kpis ? pct(kpis.annualYield) : '—',
      tone: (kpis?.annualYield ?? 0) >= 0 ? '#F5F5F7' : '#FF453A',
    },
    {
      k: '期末权益',
      v: kpis ? kpis.finalBalance.toLocaleString('zh-CN') : '—',
      tone: '#F5F5F7',
    },
  ]

  return (
    <Row gutter={[12, 12]}>
      {items.map((c) => (
        <Col key={c.k} xs={12} sm={12} md={6}>
          <Card size="small" styles={{ body: { padding: '14px 16px' } }}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {c.k}
            </Text>
            <div
              style={{
                marginTop: 6,
                fontSize: 22,
                fontWeight: 600,
                letterSpacing: '-0.03em',
                color: kpis ? c.tone : '#A8B2C2',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {c.v}
            </div>
          </Card>
        </Col>
      ))}
    </Row>
  )
}

export function WorkbenchPanel() {
  const { message, modal } = App.useApp()

  const [nodes, setNodes] = useState<Record<PipelineNodeKey, string>>({
    ...DEFAULT_PIPELINE,
  })
  const [assemblies, setAssemblies] = useState<AssemblySnapshot[]>(() =>
    typeof window === 'undefined' ? [] : loadAssemblySnapshots(),
  )
  const [selectedAssemblyId, setSelectedAssemblyId] = useState<string>()
  const [account, setAccount] = useState<AccountConfig>({ ...DEFAULT_ACCOUNT })
  const [catalogStrategies, setCatalogStrategies] =
    useState<Strategy[]>(FALLBACK_STRATEGIES)
  const [strategyId, setStrategyId] = useState(DEFAULT_STRATEGY_ID)
  const [runs, setRuns] = useState<BacktestRun[]>(() =>
    typeof window === 'undefined' ? [] : loadBacktestRuns(),
  )
  const [selectedRunId, setSelectedRunId] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
  const [series, setSeries] = useState<SeriesPoint[]>([])
  const [trades, setTrades] = useState<WorkbenchTrade[]>([])
  const [kpis, setKpis] = useState<KpiSet | null>(null)
  const [page, setPage] = useState(1)
  const [chartMetric, setChartMetric] = useState<ChartMetric>('equity')
  const [chartPeriod, setChartPeriod] = useState<ChartPeriod>('day')

  useEffect(() => {
    let cancelled = false
    void fetchCatalog()
      .then((catalog) => {
        if (cancelled || !catalog.strategies?.length) return
        setCatalogStrategies(catalog.strategies)
        setStrategyId((prev) =>
          catalog.strategies.some((s) => s.id === prev)
            ? prev
            : catalog.strategies[0]?.id || DEFAULT_STRATEGY_ID,
        )
      })
      .catch(() => {
        /* 保持本地兜底目录 */
      })
    return () => {
      cancelled = true
    }
  }, [])

  const engineMeta =
    BACKTEST_ENGINE_OPTIONS.find((o) => o.id === account.engine) ??
    BACKTEST_ENGINE_OPTIONS[0]

  const strategyMeta =
    catalogStrategies.find((s) => s.id === strategyId) ?? catalogStrategies[0]

  const chartSeries = useMemo(
    () => aggregateSeries(series, chartPeriod),
    [series, chartPeriod],
  )

  const patchAccount = (patch: Partial<AccountConfig>) =>
    setAccount((prev) => ({ ...prev, ...patch }))

  const onSaveAssembly = () => {
    let name = `装配 · ${dayjs().format('MM-DD HH:mm')}`
    modal.confirm({
      title: '保存当前装配组合',
      content: (
        <Input
          defaultValue={name}
          onChange={(e) => {
            name = e.target.value
          }}
        />
      ),
      okText: '保存',
      onOk: () => {
        const trimmed = name.trim()
        if (!trimmed) return Promise.reject()
        const snap: AssemblySnapshot = {
          id: newId('asm'),
          name: trimmed,
          savedAt: new Date().toISOString(),
          strategyId,
          nodes: { ...nodes },
        }
        const next = [snap, ...assemblies].slice(0, 40)
        setAssemblies(next)
        persistAssemblySnapshots(next)
        message.success(`已保存装配「${trimmed}」`)
      },
    })
  }

  const onLoadAssembly = (id: string | undefined) => {
    setSelectedAssemblyId(id)
    if (!id) return
    const snap = assemblies.find((s) => s.id === id)
    if (!snap) return
    setNodes({ ...snap.nodes })
    message.success(`已加载装配「${snap.name}」`)
  }

  const onSelectRun = (id: string | undefined) => {
    setSelectedRunId(id)
    if (!id) return
    const run = runs.find((r) => r.id === id)
    if (!run) {
      message.error('找不到该回测归档，可能已被清理')
      setSelectedRunId(undefined)
      return
    }
    setSeries(
      enrichEquitySeries(
        run.series.map((p) => ({ t: p.t, equity: p.equity, lots: p.lots ?? 0 })),
        run.account.initBalance,
      ),
    )
    setTrades(run.trades)
    setKpis(run.kpis)
    setNodes({ ...run.nodes })
    setAccount({ ...run.account })
    setStrategyId(run.strategyId || DEFAULT_STRATEGY_ID)
    setSelectedAssemblyId(undefined)
    setPage(1)
    message.success(`已载入历史回测「${run.name}」`)
  }

  const onResetAccount = () => {
    setAccount({ ...DEFAULT_ACCOUNT })
    setStrategyId(DEFAULT_STRATEGY_ID)
    setSelectedRunId(undefined)
    setSeries([])
    setTrades([])
    setKpis(null)
    setPage(1)
    setProgress(0)
    setProgressMsg('')
    message.info('已重置测试账号配置与图表')
  }

  const kpisFromRun = (rec: RunRecord, initBalance: number): KpiSet => {
    const m = rec.metrics || {}
    const num = (key: string, fallback = 0) => {
      const v = m[key]
      return typeof v === 'number' && Number.isFinite(v) ? v : fallback
    }
    return {
      ror: num('ror'),
      maxDrawdown: num('max_drawdown'),
      sharpe: num('sharpe'),
      tradeCount: Math.round(num('trade_count')),
      winRate: num('winning_rate'),
      profitLossRatio: num('profit_loss_ratio'),
      annualYield: num('annual_yield'),
      finalBalance: num('final_balance', initBalance),
    }
  }

  const seriesFromRun = (rec: RunRecord, initBalance: number): SeriesPoint[] => {
    const curve = rec.equity_curve || []
    if (curve.length === 0) {
      const final =
        typeof rec.metrics?.final_balance === 'number'
          ? rec.metrics.final_balance
          : initBalance
      const start = rec.start || account.start
      const end = rec.end || account.end
      return enrichEquitySeries(
        [
          { t: start, equity: initBalance, lots: 0 },
          { t: end, equity: final, lots: 0 },
        ],
        initBalance,
      )
    }
    return enrichEquitySeries(
      curve.map((p) => ({ t: p.t, equity: p.equity, lots: 0 })),
      initBalance,
    )
  }

  const onRun = async () => {
    if (!Number.isFinite(account.initBalance) || account.initBalance <= 0) {
      message.warning('初始资金必须大于 0')
      return
    }
    if (!account.start || !account.end) {
      message.warning('请选择完整回测区间')
      return
    }
    if (dayjs(account.start).isAfter(dayjs(account.end), 'day')) {
      message.warning('回测开始日期不能晚于结束日期')
      return
    }

    setBusy(true)
    setSelectedRunId(undefined)
    setPage(1)
    setProgress(2)
    setProgressMsg(
      `提交回测 ${account.start} → ${account.end}（${account.engine === 'tq' ? '天勤' : '本地缓存'}）…`,
    )
    try {
      const engineApi = account.engine === 'tq' ? 'tq' : 'local'
      const strategyLabel = strategyMeta?.name || strategyId
      const out = await runBacktest({
        strategy_id: strategyId,
        symbol_ids: [account.symbolId],
        start: account.start,
        end: account.end,
        init_balance: account.initBalance,
        engine: engineApi,
        auto_download: true,
        force: true,
        onProgress: (job) => {
          const pct = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0) * 100)))
          setProgress(pct)
          setProgressMsg(
            job.progress_msg ||
              (job.status === 'QUEUED'
                ? '排队中…'
                : job.status === 'RUNNING'
                  ? `回测运行中（${account.start}→${account.end}）…`
                  : job.status),
          )
        },
      })

      const rec = out.runs[0]
      if (!rec) {
        throw new Error('回测完成但未返回结果记录')
      }

      const curve = seriesFromRun(rec, account.initBalance)
      const metrics = kpisFromRun(rec, account.initBalance)
      setSeries(curve)
      setTrades([])
      setKpis(metrics)

      const engineLabel = account.engine === 'tq' ? '天勤' : '缓存'
      const run: BacktestRun = {
        id: rec.run_id || newId('run'),
        name: `${strategyLabel} · ${engineLabel} · ${rec.start || account.start}~${rec.end || account.end}`,
        savedAt: rec.saved_at || new Date().toISOString(),
        strategyId,
        strategyName: strategyLabel,
        account: { ...account },
        nodes: { ...nodes },
        series: curve,
        trades: [],
        kpis: metrics,
      }

      setProgress(100)
      setProgressMsg(`回测完成 ${run.name}`)

      if (account.persistDb) {
        const nextRuns = [run, ...runs].slice(0, 50)
        setRuns(nextRuns)
        try {
          persistBacktestRuns(nextRuns)
        } catch (saveErr) {
          message.error(saveErr instanceof Error ? saveErr.message : String(saveErr))
        }
        setSelectedRunId(run.id)
        message.success(`${engineLabel}回测完成（区间 ${account.start}～${account.end}）`)
      } else {
        message.success(
          `${engineLabel}回测完成（区间 ${account.start}～${account.end}；未写入本地历史列表）`,
        )
      }
    } catch (e) {
      setProgressMsg('回测失败')
      message.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const rangeValue: [Dayjs, Dayjs] | null =
    account.start && account.end ? [dayjs(account.start), dayjs(account.end)] : null

  const tradeColumns = [
    { title: '时间', dataIndex: 'time', key: 'time', width: 160 },
    { title: '标的', dataIndex: 'symbol', key: 'symbol', width: 80 },
    { title: '方向', dataIndex: 'direction', key: 'direction', width: 80 },
    {
      title: '价格',
      dataIndex: 'price',
      key: 'price',
      width: 90,
      render: (v: number) => v.toFixed(2),
    },
    { title: '手数', dataIndex: 'lots', key: 'lots', width: 70 },
    {
      title: '盈亏',
      dataIndex: 'pnl',
      key: 'pnl',
      width: 100,
      render: (v: number | null) =>
        v === null ? (
          <Text type="secondary">—</Text>
        ) : (
          <Text style={{ color: v >= 0 ? '#30D158' : '#FF453A' }}>{v.toFixed(2)}</Text>
        ),
    },
    {
      title: '信号强度',
      dataIndex: 'signalStrength',
      key: 'signalStrength',
      width: 100,
      render: (v: number) => <Tag color="processing">{v}</Tag>,
    },
  ]

  return (
    <Row gutter={[16, 16]} align="stretch">
      <Col xs={24} xl={9} xxl={8}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="下方「信号/仓位预览」尚未接入回测 API；实际回测以所选策略目录为准。"
          />

          <Card size="small" title="回测参数">
            <Row gutter={[12, 14]}>
              <Col span={24}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  策略
                </Text>
                <Select
                  style={{ width: '100%' }}
                  value={strategyId}
                  disabled={busy}
                  onChange={setStrategyId}
                  options={catalogStrategies.map((s) => ({
                    value: s.id,
                    label: s.ready === false ? `${s.name}（占位）` : s.name,
                  }))}
                />
                {strategyMeta?.description ? (
                  <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>
                    {strategyMeta.description}
                  </Text>
                ) : null}
              </Col>
              <Col span={24}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  历史结果
                </Text>
                <Select
                  style={{ width: '100%' }}
                  allowClear
                  placeholder="不选则按当前参数新测"
                  value={selectedRunId}
                  onChange={onSelectRun}
                  options={runs.map((r) => ({
                    value: r.id,
                    label: `${r.name} · ${dayjs(r.savedAt).format('MM-DD HH:mm')}`,
                  }))}
                />
              </Col>
              <Col xs={24} sm={12}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  引擎
                </Text>
                <Select
                  style={{ width: '100%' }}
                  value={account.engine}
                  disabled={busy}
                  onChange={(v) => patchAccount({ engine: v as BacktestEngine })}
                  options={BACKTEST_ENGINE_OPTIONS.map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                />
              </Col>
              <Col xs={24} sm={12}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  品种
                </Text>
                <Select
                  style={{ width: '100%' }}
                  value={account.symbolId}
                  disabled={busy}
                  onChange={(v) => patchAccount({ symbolId: v })}
                  options={WORKBENCH_SYMBOLS.map((s) => ({
                    value: s.id,
                    label: `${s.name}（${s.signal}）`,
                  }))}
                />
              </Col>
              <Col span={24}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  区间
                </Text>
                <DatePicker.RangePicker
                  style={{ width: '100%' }}
                  value={rangeValue}
                  allowClear={false}
                  disabled={busy}
                  onChange={(vals) => {
                    if (!vals?.[0] || !vals?.[1]) return
                    const start = vals[0]
                    const end = vals[1]
                    if (start.isAfter(end, 'day')) {
                      message.warning('开始日期不能晚于结束日期')
                      return
                    }
                    patchAccount({
                      start: start.format('YYYY-MM-DD'),
                      end: end.format('YYYY-MM-DD'),
                    })
                  }}
                />
              </Col>
              <Col xs={24} sm={12}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  初始资金
                </Text>
                <InputNumber
                  style={{ width: '100%' }}
                  value={account.initBalance}
                  min={0}
                  step={10000}
                  disabled={busy}
                  onChange={(v) =>
                    patchAccount({ initBalance: Math.max(0, Number(v) || 0) })
                  }
                />
              </Col>
              <Col xs={12} sm={6}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  手续费
                </Text>
                <Switch
                  checked={account.enableCommission}
                  disabled={busy}
                  onChange={(v) => patchAccount({ enableCommission: v })}
                  checkedChildren="计"
                  unCheckedChildren="否"
                />
              </Col>
              <Col xs={12} sm={6}>
                <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
                  存历史
                </Text>
                <Switch
                  checked={account.persistDb}
                  disabled={busy}
                  onChange={(v) => patchAccount({ persistDb: v })}
                  checkedChildren="是"
                  unCheckedChildren="否"
                />
              </Col>
              <Col span={24}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {engineMeta.desc}
                </Text>
              </Col>
              <Col span={24}>
                <Space wrap>
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={busy}
                    disabled={busy}
                    onClick={() => void onRun()}
                  >
                    {busy ? '回测中…' : '开始回测'}
                  </Button>
                  <Button icon={<RedoOutlined />} disabled={busy} onClick={onResetAccount}>
                    重置
                  </Button>
                </Space>
              </Col>
              {(busy || progress > 0) && (
                <Col span={24}>
                  <Flex justify="space-between" style={{ marginBottom: 6 }}>
                    <Text style={{ fontSize: 13 }}>{progressMsg || (busy ? '处理中…' : '就绪')}</Text>
                    <Text style={{ color: '#0A84FF', fontVariantNumeric: 'tabular-nums' }}>
                      {progress}%
                    </Text>
                  </Flex>
                  <Progress
                    percent={progress}
                    status={busy ? 'active' : progress >= 100 ? 'success' : 'normal'}
                    strokeColor={{ from: '#1a6cff', to: '#0A84FF' }}
                    showInfo={false}
                  />
                </Col>
              )}
            </Row>
          </Card>

          <Collapse
            size="small"
            items={[
              {
                key: 'pipeline-preview',
                label: '信号 / 仓位预览（未接入回测）',
                children: (
                  <Space direction="vertical" size={10} style={{ width: '100%' }}>
                    <Flex wrap="wrap" gap={8} justify="space-between">
                      <Select
                        size="small"
                        style={{ minWidth: 160, flex: 1 }}
                        placeholder="加载装配…"
                        value={selectedAssemblyId}
                        options={assemblies.map((s) => ({ value: s.id, label: s.name }))}
                        onChange={onLoadAssembly}
                        allowClear
                      />
                      <Button size="small" icon={<SaveOutlined />} onClick={onSaveAssembly}>
                        保存装配
                      </Button>
                    </Flex>
                    <Row gutter={[8, 8]}>
                      {PIPELINE_STEPS.map((step) => {
                        const options = PIPELINE_OPTIONS[step.key].map((o) => ({
                          value: o.id,
                          label: o.label,
                        }))
                        return (
                          <Col key={step.key} span={24}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {step.title}
                            </Text>
                            <Select
                              style={{ width: '100%', marginTop: 4 }}
                              value={nodes[step.key]}
                              options={options}
                              onChange={(v) =>
                                setNodes((prev) => ({ ...prev, [step.key]: v }))
                              }
                            />
                          </Col>
                        )
                      })}
                    </Row>
                  </Space>
                ),
              },
            ]}
          />
        </Space>
      </Col>

      <Col xs={24} xl={15} xxl={16}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Card
            size="small"
            title="收益曲线"
            extra={
              <Space wrap size={8}>
                <Select
                  size="small"
                  value={chartMetric}
                  onChange={(v) => setChartMetric(v as ChartMetric)}
                  style={{ width: 140 }}
                  options={CHART_METRIC_OPTIONS.map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                  popupMatchSelectWidth={false}
                />
                <Segmented
                  size="small"
                  value={chartPeriod}
                  onChange={(v) => setChartPeriod(v as ChartPeriod)}
                  options={CHART_PERIOD_OPTIONS.map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                />
              </Space>
            }
          >
            <MetricChart series={chartSeries} metric={chartMetric} />
          </Card>

          <Card size="small" title="绩效">
            <KpiGrid kpis={kpis} />
          </Card>

          <Card size="small" title="成交明细">
            <Table
              size="small"
              rowKey="id"
              columns={tradeColumns}
              dataSource={trades}
              pagination={{
                current: page,
                pageSize: PAGE_SIZE,
                total: trades.length,
                showSizeChanger: false,
                showTotal: (t) => `共 ${t} 笔`,
                onChange: setPage,
              }}
              locale={{ emptyText: '尚无成交记录（当前 Falcon 回测未返回逐笔）' }}
              scroll={{ x: 720 }}
            />
          </Card>
        </Space>
      </Col>
    </Row>
  )
}
