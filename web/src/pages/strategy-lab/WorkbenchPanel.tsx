import { useMemo, useState, type MouseEvent } from 'react'
import {
  App,
  Button,
  Card,
  Col,
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
  CopyOutlined,
  FileAddOutlined,
  PlayCircleOutlined,
  RedoOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
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
  buildDemoSeries,
  buildDemoTrades,
  demoKpis,
  formatMetricValue,
  loadAssemblySnapshots,
  loadBacktestRuns,
  loadSavedStrategies,
  metricValue,
  newId,
  persistAssemblySnapshots,
  persistBacktestRuns,
  persistSavedStrategies,
  type AccountConfig,
  type AssemblySnapshot,
  type BacktestEngine,
  type BacktestRun,
  type ChartMetric,
  type ChartPeriod,
  type KpiSet,
  type PipelineNodeKey,
  type SavedStrategy,
  type SeriesPoint,
  type WorkbenchTrade,
} from './workbench-data'

const { Text } = Typography
const PAGE_SIZE = 10

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
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = Math.max(max - min, 1)
  const xAt = (i: number) => pad.l + (i / (series.length - 1)) * (w - pad.l - pad.r)
  const yAt = (v: number) => pad.t + (1 - (v - min) / span) * (h - pad.t - pad.b)
  const path = series
    .map(
      (p, i) =>
        `${i === 0 ? 'M' : 'L'} ${xAt(i).toFixed(1)} ${yAt(metricValue(p, metric)).toFixed(1)}`,
    )
    .join(' ')
  const area = `${path} L ${xAt(series.length - 1).toFixed(1)} ${h - pad.b} L ${pad.l} ${h - pad.b} Z`
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
          <g key={tv}>
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
        <path d={area} fill="rgba(10,132,255,0.12)" />
        <path d={path} fill="none" stroke="#0A84FF" strokeWidth="2.25" strokeLinecap="round" />
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
              stroke="#0A84FF"
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
            left: `min(${(hover.x / w) * 100}%, calc(100% - 170px))`,
            top: 8,
            pointerEvents: 'none',
            minWidth: 140,
            boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          }}
        >
          <Text strong>{series[hover.idx].t}</Text>
          <div>
            <Text type="secondary">{metricLabel} </Text>
            <Text style={{ color: '#0A84FF' }}>
              {formatMetricValue(metricValue(series[hover.idx], metric), metric)}
            </Text>
          </div>
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

  const [strategies, setStrategies] = useState<SavedStrategy[]>(() =>
    typeof window === 'undefined' ? [] : loadSavedStrategies(),
  )
  // 默认进入草稿，避免「一打开就选中第一条 → 每次保存都覆盖」
  const [activeStrategyId, setActiveStrategyId] = useState('')
  const [strategyName, setStrategyName] = useState('未命名策略')
  const [nodes, setNodes] = useState<Record<PipelineNodeKey, string>>({
    ...DEFAULT_PIPELINE,
  })
  const [assemblies, setAssemblies] = useState<AssemblySnapshot[]>(() =>
    typeof window === 'undefined' ? [] : loadAssemblySnapshots(),
  )
  const [selectedAssemblyId, setSelectedAssemblyId] = useState<string>()
  const [account, setAccount] = useState<AccountConfig>({ ...DEFAULT_ACCOUNT })
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

  const symbol =
    WORKBENCH_SYMBOLS.find((s) => s.id === account.symbolId) ?? WORKBENCH_SYMBOLS[0]
  const engineMeta =
    BACKTEST_ENGINE_OPTIONS.find((o) => o.id === account.engine) ??
    BACKTEST_ENGINE_OPTIONS[0]

  const chartSeries = useMemo(
    () => aggregateSeries(series, chartPeriod),
    [series, chartPeriod],
  )

  const patchAccount = (patch: Partial<AccountConfig>) =>
    setAccount((prev) => ({ ...prev, ...patch }))

  const onSelectStrategy = (id: string | undefined) => {
    if (!id) {
      setActiveStrategyId('')
      setStrategyName('未命名策略')
      setNodes({ ...DEFAULT_PIPELINE })
      setAccount({ ...DEFAULT_ACCOUNT })
      setSelectedAssemblyId(undefined)
      return
    }
    const s = strategies.find((x) => x.id === id)
    if (!s) return
    setActiveStrategyId(s.id)
    setStrategyName(s.name)
    setNodes({ ...s.nodes })
    setAccount({ ...s.account })
    setSelectedAssemblyId(undefined)
    message.success(`已加载策略「${s.name}」`)
  }

  const onNewDraft = () => {
    setActiveStrategyId('')
    setStrategyName('未命名策略')
    setNodes({ ...DEFAULT_PIPELINE })
    setAccount({ ...DEFAULT_ACCOUNT })
    setSelectedAssemblyId(undefined)
    message.info('已新建草稿，保存后会追加一条策略')
  }

  /** 始终追加一条新策略，不覆盖已有列表 */
  const createStrategy = (name: string) => {
    const now = new Date().toISOString()
    const created: SavedStrategy = {
      id: newId('strat'),
      name,
      updatedAt: now,
      nodes: { ...nodes },
      account: { ...account },
    }
    const next = [created, ...strategies]
    setStrategies(next)
    persistSavedStrategies(next)
    setActiveStrategyId(created.id)
    setStrategyName(name)
    return created
  }

  const onSaveStrategy = () => {
    const name = strategyName.trim() || '未命名策略'
    const now = new Date().toISOString()

    // 草稿：新增
    if (!activeStrategyId) {
      createStrategy(name)
      message.success(`已新增策略「${name}」`)
      return
    }

    // 已选中：只更新当前这一条（改名 + 装配/账号），其它策略保持不变
    const exists = strategies.some((s) => s.id === activeStrategyId)
    if (!exists) {
      createStrategy(name)
      message.success(`已新增策略「${name}」`)
      return
    }

    const next = strategies.map((s) =>
      s.id === activeStrategyId
        ? { ...s, name, updatedAt: now, nodes: { ...nodes }, account: { ...account } }
        : s,
    )
    setStrategies(next)
    persistSavedStrategies(next)
    setStrategyName(name)
    message.success(`已更新策略「${name}」`)
  }

  /** 在已有选中策略时，另存为新档案（保留原策略） */
  const onSaveAsStrategy = () => {
    const name = strategyName.trim() || '未命名策略'
    const created = createStrategy(name)
    message.success(`已另存为新策略「${created.name}」（原策略仍保留）`)
  }

  const onSaveAssembly = () => {
    let name = `${strategyName || '装配'} · ${dayjs().format('MM-DD HH:mm')}`
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
          strategyId: activeStrategyId || 'draft',
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
    // 只回放该次结果；退出策略选中，避免误点「更新」把历史装配写回档案
    setActiveStrategyId('')
    setStrategyName(run.strategyName || '历史回测')
    setSeries(run.series)
    setTrades(run.trades)
    setKpis(run.kpis)
    setNodes({ ...run.nodes })
    setAccount({ ...run.account })
    setSelectedAssemblyId(undefined)
    setPage(1)
    message.success(`已载入历史回测「${run.name}」`)
  }

  const onResetAccount = () => {
    setAccount({ ...DEFAULT_ACCOUNT })
    setSelectedRunId(undefined)
    setSeries([])
    setTrades([])
    setKpis(null)
    setPage(1)
    setProgress(0)
    setProgressMsg('')
    message.info('已重置测试账号配置与图表')
  }

  /** 按回测机制模拟分阶段进度（后续可换成真实 job 轮询） */
  const runWithProgress = async (engine: BacktestEngine) => {
    const steps =
      engine === 'cache'
        ? [
            { pct: 8, msg: '读取本地行情缓存…', wait: 180 },
            { pct: 28, msg: '校验 K 线完整性…', wait: 220 },
            { pct: 52, msg: '回放决策流水线…', wait: 320 },
            { pct: 78, msg: '汇总成交与权益…', wait: 260 },
            { pct: 94, msg: '写入结果…', wait: 160 },
          ]
        : [
            { pct: 6, msg: '连接天勤回测通道…', wait: 280 },
            { pct: 18, msg: '订阅合约与初始化 TqBacktest…', wait: 360 },
            { pct: 42, msg: '时光机推进中…', wait: 480 },
            { pct: 68, msg: '同步成交与持仓…', wait: 420 },
            { pct: 88, msg: '拉取绩效指标…', wait: 300 },
            { pct: 96, msg: '收尾归档…', wait: 200 },
          ]

    for (const step of steps) {
      setProgress(step.pct)
      setProgressMsg(step.msg)
      await new Promise((r) => setTimeout(r, step.wait))
    }
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
      account.engine === 'cache' ? '准备缓存回测…' : '准备天勤回测…',
    )
    try {
      await runWithProgress(account.engine)
      const curve = buildDemoSeries(account.initBalance, 90, account.enableCommission)
      const list = buildDemoTrades(symbol.name)
      const metrics = demoKpis(account.initBalance, account.enableCommission)
      setSeries(curve)
      setTrades(list)
      setKpis(metrics)

      const engineLabel = account.engine === 'tq' ? '天勤' : '缓存'
      const run: BacktestRun = {
        id: newId('run'),
        name: `${strategyName} · ${engineLabel} · ${account.start}~${account.end}`,
        savedAt: new Date().toISOString(),
        strategyId: activeStrategyId || 'draft',
        strategyName,
        account: { ...account },
        nodes: { ...nodes },
        series: curve,
        trades: list,
        kpis: metrics,
      }

      setProgress(100)
      setProgressMsg('回测完成')

      if (account.persistDb) {
        const nextRuns = [run, ...runs].slice(0, 50)
        setRuns(nextRuns)
        persistBacktestRuns(nextRuns)
        setSelectedRunId(run.id)
        message.success(`${engineLabel}回测完成，结果已写入历史归档`)
      } else {
        message.success(`${engineLabel}回测完成（未落库，不会出现在历史列表）`)
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
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title="策略档案"
        extra={
          <Space wrap>
            <Button icon={<FileAddOutlined />} onClick={onNewDraft}>
              新建草稿
            </Button>
            <Button icon={<CopyOutlined />} onClick={onSaveAsStrategy}>
              另存为
            </Button>
            <Button type="primary" icon={<SaveOutlined />} onClick={onSaveStrategy}>
              {activeStrategyId ? '更新策略' : '保存策略'}
            </Button>
          </Space>
        }
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
          默认是草稿：点「保存策略」会新增一条。从下拉选中已有策略后，「更新策略」只改当前条；要保留原策略请用「另存为」。
        </Text>
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              已保存策略（共 {strategies.length} 条）
            </Text>
            <Select
              style={{ width: '100%', marginTop: 8 }}
              allowClear
              placeholder="新建 / 未保存草稿"
              value={activeStrategyId || undefined}
              onChange={onSelectStrategy}
              options={strategies.map((s) => ({
                value: s.id,
                label: `${s.name} · ${dayjs(s.updatedAt).format('MM-DD HH:mm')}`,
              }))}
            />
          </Col>
          <Col xs={24} md={12}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              策略名称
            </Text>
            <Input
              style={{ marginTop: 8 }}
              value={strategyName}
              onChange={(e) => setStrategyName(e.target.value)}
              placeholder="输入策略名称"
            />
          </Col>
        </Row>
      </Card>

      <Card
        title="策略装配区"
        extra={
          <Space wrap>
            <Select
              style={{ minWidth: 180 }}
              placeholder="加载装配组合…"
              value={selectedAssemblyId}
              options={assemblies.map((s) => ({ value: s.id, label: s.name }))}
              onChange={onLoadAssembly}
              allowClear
            />
            <Button icon={<SaveOutlined />} onClick={onSaveAssembly}>
              保存当前装配
            </Button>
          </Space>
        }
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 12 }}>
          流水线：因子挖掘 → 信号生成 → 开仓策略 → 仓位控制。可单独保存装配，或随「保存策略」写入档案。
        </Text>
        <Row gutter={[12, 12]}>
          {PIPELINE_STEPS.map((step, i) => (
            <Col key={step.key} xs={24} sm={12} lg={6}>
              <Card size="small" styles={{ body: { padding: 14 } }}>
                <Flex justify="space-between" align="center">
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    节点 {i + 1}
                  </Text>
                  {i < PIPELINE_STEPS.length - 1 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      →
                    </Text>
                  )}
                </Flex>
                <Text strong style={{ display: 'block', marginTop: 4 }}>
                  {step.title}
                </Text>
                <Select
                  style={{ width: '100%', marginTop: 10 }}
                  value={nodes[step.key]}
                  onChange={(v) => setNodes((prev) => ({ ...prev, [step.key]: v }))}
                  options={PIPELINE_OPTIONS[step.key].map((o) => ({
                    value: o.id,
                    label: o.label,
                  }))}
                />
                <Text type="secondary" style={{ display: 'block', marginTop: 8, fontSize: 11 }}>
                  {PIPELINE_OPTIONS[step.key].find((o) => o.id === nodes[step.key])?.desc}
                </Text>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      <Card title="测试账号配置">
        <Row gutter={[16, 20]}>
          <Col span={24}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              历史回测结果
            </Text>
            <Select
              style={{ width: '100%' }}
              allowClear
              placeholder="不选择（使用当前配置新测）"
              value={selectedRunId}
              onChange={onSelectRun}
              options={runs.map((r) => ({
                value: r.id,
                label: `${r.name} · ${dayjs(r.savedAt).format('YYYY-MM-DD HH:mm')}`,
              }))}
            />
            <Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11 }}>
              选中后下方曲线与绩效直接渲染该次归档结果。
            </Text>
          </Col>

          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              回测机制
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
          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              测试品种
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
          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              初始资金
            </Text>
            <InputNumber
              style={{ width: '100%' }}
              value={account.initBalance}
              min={0}
              step={10000}
              disabled={busy}
              onChange={(v) => patchAccount({ initBalance: Math.max(0, Number(v) || 0) })}
            />
          </Col>

          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              回测区间
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
          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              手续费
            </Text>
            <Flex
              align="center"
              justify="space-between"
              style={{
                height: 40,
                padding: '0 12px',
                borderRadius: 12,
                border: '1px solid rgba(180, 200, 230, 0.42)',
                background: '#121C30',
              }}
            >
              <Text>{account.enableCommission ? '计入手续费' : '不计手续费'}</Text>
              <Switch
                checked={account.enableCommission}
                disabled={busy}
                onChange={(v) => patchAccount({ enableCommission: v })}
                checkedChildren="是"
                unCheckedChildren="否"
              />
            </Flex>
          </Col>
          <Col xs={24} md={8}>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              保存回测
            </Text>
            <Flex
              align="center"
              justify="space-between"
              style={{
                height: 40,
                padding: '0 12px',
                borderRadius: 12,
                border: '1px solid rgba(180, 200, 230, 0.42)',
                background: '#121C30',
              }}
            >
              <Text>{account.persistDb ? '写入数据库' : '仅本次展示'}</Text>
              <Switch
                checked={account.persistDb}
                disabled={busy}
                onChange={(v) => patchAccount({ persistDb: v })}
                checkedChildren="是"
                unCheckedChildren="否"
              />
            </Flex>
          </Col>

          <Col span={24}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              {engineMeta.desc}
            </Text>
          </Col>

          <Col span={24}>
            <Space>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={busy}
                disabled={busy}
                onClick={() => void onRun()}
              >
                {busy ? '回测进行中…' : '开始测试'}
              </Button>
              <Button icon={<RedoOutlined />} disabled={busy} onClick={onResetAccount}>
                重置
              </Button>
            </Space>
          </Col>

          {(busy || progress > 0) && (
            <Col span={24}>
              <Card size="small" styles={{ body: { padding: '14px 16px' } }}>
                <Flex justify="space-between" align="center" style={{ marginBottom: 8 }}>
                  <Text>{progressMsg || (busy ? '处理中…' : '就绪')}</Text>
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
              </Card>
            </Col>
          )}
        </Row>
      </Card>

      <Card
        title="可视化图表"
        extra={
          <Space wrap>
            <Segmented
              value={chartMetric}
              onChange={(v) => setChartMetric(v as ChartMetric)}
              options={CHART_METRIC_OPTIONS.map((o) => ({
                value: o.id,
                label: o.label,
              }))}
            />
            <Segmented
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

      <Card title="绩效指标">
        <KpiGrid kpis={kpis} />
      </Card>

      <Card title="交易明细">
        <Table
          size="middle"
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
          locale={{ emptyText: '尚无成交记录' }}
          scroll={{ x: 720 }}
        />
      </Card>
    </Space>
  )
}
