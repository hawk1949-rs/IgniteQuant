/** 回测工作台：策略档案、装配快照、回测结果与图表聚合。 */

export type PipelineNodeKey = 'factor' | 'signal' | 'sizing'

export type PipelineOption = { id: string; label: string; desc: string }

export type ChartMetric = 'equity' | 'pnl' | 'ror' | 'drawdown' | 'lots'
export type ChartPeriod = 'day' | 'month' | 'quarter' | 'year'

export type SeriesPoint = {
  t: string
  equity: number
  pnl: number
  /** 相对初始资金的累计收益率，如 0.025 = +2.5% */
  ror: number
  /** 相对历史峰值的回撤（≤0），如 -0.05 = -5% */
  drawdown: number
  lots: number
}

export type WorkbenchTrade = {
  id: string
  time: string
  symbol: string
  direction: '买开' | '卖开' | '买平' | '卖平'
  price: number
  lots: number
  pnl: number | null
  signalStrength: number
}

export type KpiSet = {
  ror: number
  maxDrawdown: number
  sharpe: number
  tradeCount: number
  winRate: number
  profitLossRatio: number
  annualYield: number
  finalBalance: number
}

export type BacktestEngine = 'cache' | 'tq'

export type AccountConfig = {
  symbolId: string
  start: string
  end: string
  initBalance: number
  enableCommission: boolean
  persistDb: boolean
  /** 回测机制：缓存回测 | 天勤回测 */
  engine: BacktestEngine
}

/** 用户可命名/改名/切换的策略档案（含装配） */
export type SavedStrategy = {
  id: string
  name: string
  updatedAt: string
  nodes: Record<PipelineNodeKey, string>
  account: AccountConfig
}

/** 仅装配组合快照 */
export type AssemblySnapshot = {
  id: string
  name: string
  savedAt: string
  strategyId: string
  nodes: Record<PipelineNodeKey, string>
}

/** 一次回测结果，可被「测试账号配置」再次选中渲染 */
export type BacktestRun = {
  id: string
  name: string
  savedAt: string
  strategyId: string
  strategyName: string
  account: AccountConfig
  nodes: Record<PipelineNodeKey, string>
  series: SeriesPoint[]
  trades: WorkbenchTrade[]
  kpis: KpiSet
}

export const PIPELINE_OPTIONS: Record<Exclude<PipelineNodeKey, 'factor'>, PipelineOption[]> = {
  signal: [
    { id: 'signal_score', label: '信号发生器 · Score[-3,3]', desc: '格兰维尔+量能+KDJ' },
    { id: 'signal_alpha_055', label: '信号发生器 · Alpha 0.55/2根', desc: '加权 Alpha + 确认 2 根' },
    { id: 'signal_alpha_065', label: '信号发生器 · Alpha 0.65/1根', desc: '更高阈值、更短确认' },
  ],
  sizing: [
    { id: 'size_fixed_1', label: '仓位控制 · 固定 1 手', desc: '控制变量基线' },
    { id: 'size_by_signal', label: '仓位控制 · 按信号强度', desc: 'LOT_BY_SIGNAL 映射' },
    { id: 'size_atr_risk', label: '仓位控制 · ATR 风险定仓', desc: '按权益风险预算手数' },
  ],
}

/** 回测看板装配区只选信号与仓位；因子在「因子与特征」页独立挖掘 */
export const PIPELINE_STEPS: { key: Exclude<PipelineNodeKey, 'factor'>; title: string }[] = [
  { key: 'signal', title: '信号发生器' },
  { key: 'sizing', title: '仓位控制' },
]

export const DEFAULT_PIPELINE: Record<PipelineNodeKey, string> = {
  factor: '',
  signal: 'signal_score',
  sizing: 'size_fixed_1',
}

/** 兼容旧装配字段；factor 节点已从看板 UI 移除，统一置空 */
export function normalizePipelineNodes(
  nodes: Partial<Record<PipelineNodeKey | 'entry', string>> | undefined,
): Record<PipelineNodeKey, string> {
  return {
    factor: '',
    signal: nodes?.signal || DEFAULT_PIPELINE.signal,
    sizing: nodes?.sizing || DEFAULT_PIPELINE.sizing,
  }
}

export const DEFAULT_ACCOUNT: AccountConfig = {
  symbolId: 'au',
  start: '2025-01-01',
  end: '2025-05-31',
  initBalance: 1_000_000,
  enableCommission: true,
  persistDb: true,
  engine: 'cache',
}

export const BACKTEST_ENGINE_OPTIONS: {
  id: BacktestEngine
  label: string
  desc: string
}[] = [
  {
    id: 'cache',
    label: '缓存回测',
    desc: '读本地 market_cache；缺区间会先补拉（进度可能显示预热日，回测仍按所选起止日）。',
  },
  {
    id: 'tq',
    label: '天勤回测',
    desc: '天勤 TqBacktest 在线时光机，更慢，适合最终对照。',
  },
]

export const WORKBENCH_SYMBOLS = [
  { id: 'au', name: '沪金', signal: 'KQ.m@SHFE.au' },
  { id: 'ag', name: '沪银', signal: 'KQ.m@SHFE.ag' },
  { id: 'rb', name: '螺纹钢', signal: 'KQ.m@SHFE.rb' },
  { id: 'fg', name: '玻璃', signal: 'KQ.m@CZCE.FG' },
] as const

export const CHART_METRIC_OPTIONS: { id: ChartMetric; label: string }[] = [
  { id: 'equity', label: '总资产' },
  { id: 'ror', label: '收益率' },
  { id: 'drawdown', label: '回撤' },
  { id: 'pnl', label: '累计盈亏' },
  { id: 'lots', label: '成交手数' },
]

export const CHART_PERIOD_OPTIONS: { id: ChartPeriod; label: string }[] = [
  { id: 'day', label: '日' },
  { id: 'month', label: '月' },
  { id: 'quarter', label: '季度' },
  { id: 'year', label: '年' },
]

const LS_STRATEGIES = 'ignitequant.lab.saved_strategies'
const LS_ASSEMBLIES = 'ignitequant.lab.assembly_snapshots'
const LS_RUNS = 'ignitequant.lab.backtest_runs'

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as T
    return parsed ?? fallback
  } catch {
    return fallback
  }
}

function saveJson(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value))
}

export function loadSavedStrategies(): SavedStrategy[] {
  const raw = loadJson<SavedStrategy[]>(LS_STRATEGIES, [])
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (s) =>
      s &&
      typeof s.id === 'string' &&
      typeof s.name === 'string' &&
      s.nodes &&
      s.account,
  ).map((s) => ({
    ...s,
    nodes: normalizePipelineNodes(s.nodes),
    account: {
      ...DEFAULT_ACCOUNT,
      ...s.account,
      engine: s.account.engine === 'tq' ? 'tq' : 'cache',
    },
  }))
}

export function persistSavedStrategies(list: SavedStrategy[]) {
  saveJson(LS_STRATEGIES, list)
}

export function loadAssemblySnapshots(): AssemblySnapshot[] {
  const raw = loadJson<AssemblySnapshot[]>(LS_ASSEMBLIES, [])
  if (!Array.isArray(raw)) return []
  return raw
    .filter((s) => s && typeof s.id === 'string' && s.nodes)
    .map((s) => ({ ...s, nodes: normalizePipelineNodes(s.nodes) }))
}

export function persistAssemblySnapshots(list: AssemblySnapshot[]) {
  saveJson(LS_ASSEMBLIES, list)
}

export function loadBacktestRuns(): BacktestRun[] {
  const raw = loadJson<BacktestRun[]>(LS_RUNS, [])
  if (!Array.isArray(raw)) return []
  return raw
    .filter(
      (r) =>
        r &&
        typeof r.id === 'string' &&
        Array.isArray(r.series) &&
        Array.isArray(r.trades) &&
        r.kpis,
    )
    .map((r) => {
      const account = {
        ...DEFAULT_ACCOUNT,
        ...r.account,
        engine: r.account?.engine === 'tq' ? 'tq' : ('cache' as const),
      }
      const needsEnrich = r.series.some(
        (p) => typeof p.ror !== 'number' || typeof p.drawdown !== 'number',
      )
      return {
        ...r,
        nodes: normalizePipelineNodes(r.nodes),
        account,
        series: needsEnrich
          ? enrichEquitySeries(
              r.series.map((p) => ({ t: p.t, equity: p.equity, lots: p.lots ?? 0 })),
              account.initBalance,
            )
          : r.series,
      }
    })
}

export function persistBacktestRuns(list: BacktestRun[]) {
  saveJson(LS_RUNS, list)
}

export function newId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
}

/** 由权益序列补齐累计收益率与回撤（相对峰值）。 */
export function enrichEquitySeries(
  points: { t: string; equity: number; lots?: number }[],
  initBalance: number,
): SeriesPoint[] {
  const init = initBalance > 0 ? initBalance : 1
  let peak = init
  return points.map((p) => {
    const equity = Number(p.equity)
    peak = Math.max(peak, equity)
    const drawdown = peak > 0 ? (equity - peak) / peak : 0
    return {
      t: p.t,
      equity,
      pnl: equity - init,
      ror: (equity - init) / init,
      drawdown,
      lots: p.lots ?? 0,
    }
  })
}

export function buildDemoSeries(
  initBalance: number,
  points = 90,
  enableCommission = true,
): SeriesPoint[] {
  const raw: { t: string; equity: number; lots: number }[] = []
  let eq = initBalance
  const feeDrag = enableCommission ? 0.00012 : 0
  const start = new Date('2025-01-02T09:00:00')
  for (let i = 0; i < points; i++) {
    const d = new Date(start.getTime() + i * 86400000)
    const drift = Math.sin(i / 5) * 0.004 + (i % 7 === 0 ? -0.006 : 0.002) - feeDrag
    eq = Math.max(initBalance * 0.85, eq * (1 + drift))
    const lots = i % 3 === 0 ? 1 + (i % 3) : i % 5 === 0 ? 2 : 0
    raw.push({
      t: d.toISOString().slice(0, 10),
      equity: Math.round(eq),
      lots,
    })
  }
  return enrichEquitySeries(raw, initBalance)
}

export function buildDemoTrades(symbolName: string): WorkbenchTrade[] {
  const rows: WorkbenchTrade[] = []
  const dirs: WorkbenchTrade['direction'][] = ['买开', '卖平', '卖开', '买平']
  for (let i = 0; i < 94; i++) {
    const dir = dirs[i % 4]
    const isClose = dir.includes('平')
    const month = String((i % 5) + 1).padStart(2, '0')
    const day = String((i % 27) + 1).padStart(2, '0')
    rows.push({
      id: `T-${String(i + 1).padStart(3, '0')}`,
      time: `2025-${month}-${day} ${String(9 + (i % 6)).padStart(2, '0')}:${String((i * 7) % 60).padStart(2, '0')}:00`,
      symbol: symbolName,
      direction: dir,
      price: 580 + (i % 40) * 0.8,
      lots: 1 + (i % 3),
      pnl: isClose ? Math.round((Math.sin(i / 3) * 1800 + (i % 5) * 80) * 100) / 100 : null,
      signalStrength: 1 + (i % 5),
    })
  }
  return rows
}

export function demoKpis(initBalance: number, enableCommission = true): KpiSet {
  const feeHaircut = enableCommission ? 0.008 : 0
  const finalBalance = Math.round(initBalance * (1.086 - feeHaircut))
  return {
    ror: (finalBalance - initBalance) / initBalance,
    maxDrawdown: enableCommission ? -0.062 : -0.055,
    sharpe: enableCommission ? 1.24 : 1.31,
    tradeCount: 94,
    winRate: 0.47,
    profitLossRatio: 1.68,
    annualYield: enableCommission ? 0.21 : 0.23,
    finalBalance,
  }
}

function periodKey(isoDate: string, period: ChartPeriod): string {
  const [y, m] = isoDate.split('-').map(Number)
  if (period === 'day') return isoDate
  if (period === 'month') return `${y}-${String(m).padStart(2, '0')}`
  if (period === 'year') return String(y)
  const q = Math.ceil(m / 3)
  return `${y}-Q${q}`
}

/** 按日/月/季/年聚合；权益/收益/回撤取期末，手数求和 */
export function aggregateSeries(
  series: SeriesPoint[],
  period: ChartPeriod,
): SeriesPoint[] {
  if (period === 'day') return series
  const map = new Map<string, SeriesPoint>()
  const order: string[] = []
  for (const p of series) {
    const key = periodKey(p.t, period)
    const prev = map.get(key)
    if (!prev) {
      map.set(key, { ...p, t: key })
      order.push(key)
    } else {
      map.set(key, {
        t: key,
        equity: p.equity,
        pnl: p.pnl,
        ror: p.ror,
        drawdown: p.drawdown,
        lots: prev.lots + p.lots,
      })
    }
  }
  return order.map((k) => map.get(k)!)
}

export function metricValue(p: SeriesPoint, metric: ChartMetric): number {
  return p[metric]
}

export function formatMetricValue(v: number, metric: ChartMetric): string {
  if (metric === 'lots') return String(Math.round(v))
  if (metric === 'ror' || metric === 'drawdown') {
    return `${(v * 100).toFixed(2)}%`
  }
  return Math.round(v).toLocaleString('zh-CN')
}

export function chartStrokeColor(metric: ChartMetric): string {
  if (metric === 'drawdown') return '#FF453A'
  if (metric === 'ror') return '#30D158'
  if (metric === 'lots') return '#BF5AF2'
  return '#0A84FF'
}
