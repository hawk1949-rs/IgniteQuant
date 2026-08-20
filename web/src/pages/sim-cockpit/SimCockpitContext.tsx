import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  fetchSimBars,
  fetchSimCatalog,
  fetchSimDecisions,
  fetchSimFills,
  fetchSimIntents,
  fetchSimMarketBars,
  fetchSimMetrics,
  fetchSimOverseasBars,
  fetchSimReplay,
  fetchSimSessions,
  fetchSimSummary,
  fetchSimPositionHistory,
  repairSimFills,
  type SimBarsResponse,
  type SimBookLeg,
  type SimCatalog,
  type SimDecision,
  type SimFill,
  type SimIntent,
  type SimMetrics,
  type SimOverseasBars,
  type SimPositionHistoryRow,
  type SimSession,
  type SimSummary,
  type SimReplay,
} from '@/lib/api'
import { mergeOverlayMaps, overlayKeys as collectOverlayKeys } from './strategyPresentation'
import { instanceIdFor, readJsonLs, symbolIdsKey, writeJsonLs } from './simSessions'

type Ctx = {
  catalog: SimCatalog | null
  sessions: SimSession[]
  fleet: SimBookLeg[]
  instanceId: string
  setInstanceId: (id: string) => void
  framework: string
  setFramework: (id: string) => void
  strategyId: string
  setStrategyId: (id: string) => void
  symbolId: string
  setSymbolId: (id: string) => void
  symbolIds: string[]
  setSymbolIds: (ids: string[]) => void
  summary: SimSummary | null
  metrics: SimMetrics | null
  decisions: SimDecision[]
  intents: SimIntent[]
  fills: SimFill[]
  positionHistory: SimPositionHistoryRow[]
  bars: SimBarsResponse | null
  overseas: SimOverseasBars | null
  error: string | null
  warn: string | null
  loading: boolean
  starting: boolean
  setStarting: (v: boolean) => void
  replayAt: string | null
  replay: SimReplay | null
  setReplayAt: (at: string | null) => void
  refresh: () => Promise<void>
  loadMoreHistory: () => Promise<void>
  loadMoreOverseasHistory: () => Promise<void>
  historyLoading: boolean
  overseasHistoryLoading: boolean
}

const CHART_BAR_LIMIT = 100
const OVERSEAS_CHART_BAR_LIMIT = 300
const CHART_BAR_CHUNK = 100
const OVERSEAS_CHART_BAR_CHUNK = 200
const CHART_BAR_MAX = 1500
const OVERSEAS_CHART_BAR_MAX = 1200

const SimCockpitContext = createContext<Ctx | null>(null)

/**
 * Split polling so quote/account stay snappy while heavy K-line / overseas HTTP
 * does not block the light path. Overseas upstream alone is often 1–3s.
 */
const LIGHT_POLL_MS = 2_000
const HEAVY_POLL_MS = 15_000
const LS_INSTANCE = 'ignitequant.sim.instanceId'
const LS_SYMBOL = 'ignitequant.sim.symbolId'
const LS_STRATEGY = 'ignitequant.sim.strategyId'

type BarLike = {
  time: number
  open: number
  high: number
  low: number
  close: number
}

function withLiveTip<T extends { bars: BarLike[]; last_price?: number | null }>(
  src: T,
  price: number | null,
): T {
  if (price == null || !src.bars.length) {
    return { ...src, last_price: price ?? src.last_price }
  }
  const bars = src.bars.slice()
  const tip = { ...bars[bars.length - 1] }
  tip.close = price
  tip.high = Math.max(tip.high, price)
  tip.low = Math.min(tip.low, price)
  bars[bars.length - 1] = tip
  return { ...src, bars, last_price: price }
}

function readLs(key: string, fallback: string) {
  try {
    const v = localStorage.getItem(key)
    return v && v.trim() ? v : fallback
  } catch {
    return fallback
  }
}

function mergePreserveHistory(
  prev: SimBarsResponse | null,
  next: SimBarsResponse,
  maxBars = 1500,
): SimBarsResponse {
  if (!prev?.bars?.length) return next
  if (!next.bars?.length) return next
  const nextFirst = next.bars[0]?.time
  const older = prev.bars.filter((b) => b.time < nextFirst)
  if (!older.length) return next

  const bars = [...older, ...next.bars].slice(-maxBars)
  const metaMap = new Map((next.bar_meta || []).map((m) => [m.time, m]))
  for (const m of prev.bar_meta || []) {
    if (!metaMap.has(m.time)) metaMap.set(m.time, m)
  }
  const keys = collectOverlayKeys(next.overlay_specs, next.overlays)
  const overlays = mergeOverlayMaps(prev.overlays, next.overlays, keys)
  return {
    ...next,
    bars,
    bar_meta: bars.map((b) => metaMap.get(b.time) || { time: b.time, source: 'replay' }),
    overlays,
    has_more: prev.has_more ?? next.has_more,
    markers: next.markers?.length ? next.markers : prev.markers,
    price_lines: next.price_lines?.length ? next.price_lines : prev.price_lines,
    overlay_specs: next.overlay_specs?.length ? next.overlay_specs : prev.overlay_specs,
  }
}

function mergePreserveOverseas(
  prev: SimOverseasBars | null,
  next: SimOverseasBars,
  maxBars = OVERSEAS_CHART_BAR_MAX,
): SimOverseasBars {
  if (!prev?.bars?.length || prev.symbol_id !== next.symbol_id) return next
  if (!next.bars?.length) return next
  const nextFirst = next.bars[0]?.time
  const older = prev.bars.filter((b) => b.time < nextFirst)
  if (!older.length) {
    return {
      ...next,
      has_more: prev.has_more ?? next.has_more,
    }
  }

  const bars = [...older, ...next.bars].slice(-maxBars)
  const metaMap = new Map((next.bar_meta || []).map((m) => [m.time, m]))
  for (const m of prev.bar_meta || []) {
    if (!metaMap.has(m.time)) metaMap.set(m.time, m)
  }
  const keys = collectOverlayKeys(next.overlay_specs, next.overlays)
  const overlays = mergeOverlayMaps(prev.overlays, next.overlays, keys)
  return {
    ...next,
    bars,
    bar_meta: bars.map((b) => metaMap.get(b.time) || { time: b.time, source: 'replay' }),
    overlays,
    has_more: Boolean(prev.has_more) || Boolean(next.has_more),
    overlay_specs: next.overlay_specs?.length ? next.overlay_specs : prev.overlay_specs,
  }
}

function mergeOlderOverseas(
  prev: SimOverseasBars,
  older: SimOverseasBars,
): SimOverseasBars {
  const seen = new Set(prev.bars.map((b) => b.time))
  const prependBars = (older.bars || []).filter((b) => !seen.has(b.time))
  if (!prependBars.length) {
    return { ...prev, has_more: Boolean(older.has_more) }
  }
  const mergedBars = [...prependBars, ...prev.bars].slice(-OVERSEAS_CHART_BAR_MAX)
  const metaMap = new Map((prev.bar_meta || []).map((m) => [m.time, m]))
  for (const m of older.bar_meta || []) metaMap.set(m.time, m)
  const keys = collectOverlayKeys(prev.overlay_specs ?? older.overlay_specs, {
    ...older.overlays,
    ...prev.overlays,
  })
  const overlays = mergeOverlayMaps(older.overlays, prev.overlays, keys)
  return {
    ...prev,
    bars: mergedBars,
    bar_meta: mergedBars.map(
      (b) => metaMap.get(b.time) || { time: b.time, source: 'replay' },
    ),
    overlays,
    has_more: Boolean(older.has_more) && mergedBars.length < OVERSEAS_CHART_BAR_MAX,
    hint: older.hint || prev.hint,
    overlay_specs: prev.overlay_specs?.length ? prev.overlay_specs : older.overlay_specs,
  }
}

export function SimCockpitProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<SimCatalog | null>(null)
  const [sessions, setSessions] = useState<SimSession[]>([])
  const [fleet, setFleet] = useState<SimBookLeg[]>([])
  const [instanceId, setInstanceId] = useState(() => readLs(LS_INSTANCE, 'falcon_au_sim'))
  const [framework, setFramework] = useState('tq')
  const [strategyId, setStrategyIdState] = useState(() => readLs(LS_STRATEGY, 'falcon_v2'))
  const [symbolId, setSymbolId] = useState(() => readLs(LS_SYMBOL, 'au'))
  const [symbolIds, setSymbolIdsState] = useState<string[]>(() => {
    const strat = readLs(LS_STRATEGY, 'falcon_v2')
    const saved = readJsonLs<string[]>(symbolIdsKey(strat), [])
    const current = readLs(LS_SYMBOL, 'au')
    const ids = saved.length ? saved : [current]
    return ids.includes(current) ? ids : [...ids, current]
  })
  const [summary, setSummary] = useState<SimSummary | null>(null)
  const [metrics, setMetrics] = useState<SimMetrics | null>(null)
  const [decisions, setDecisions] = useState<SimDecision[]>([])
  const [intents, setIntents] = useState<SimIntent[]>([])
  const [fills, setFills] = useState<SimFill[]>([])
  const [positionHistory, setPositionHistory] = useState<SimPositionHistoryRow[]>([])
  const [bars, setBars] = useState<SimBarsResponse | null>(null)
  const [overseas, setOverseas] = useState<SimOverseasBars | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [warn, setWarn] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const refreshGenRef = useRef(0)
  const lightInFlightRef = useRef(false)
  const heavyInFlightRef = useRef(false)
  const catalogRef = useRef<SimCatalog | null>(null)
  const catalogLoadedRef = useRef(false)
  const repairedRef = useRef(false)
  const [starting, setStarting] = useState(false)
  const [replayAt, setReplayAt] = useState<string | null>(null)
  const [replay, setReplay] = useState<SimReplay | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const historyInFlightRef = useRef(false)
  const [overseasHistoryLoading, setOverseasHistoryLoading] = useState(false)
  const overseasHistoryInFlightRef = useRef(false)

  const selectInstance = useCallback(
    (id: string) => {
      setInstanceId(id)
      repairedRef.current = false
      try {
        localStorage.setItem(LS_INSTANCE, id)
      } catch {
        /* ignore */
      }
      const launcher = catalog?.launchers?.find((l) => l.instance_id === id)
      if (launcher) {
        setSymbolId(launcher.symbol_id)
        try {
          localStorage.setItem(LS_SYMBOL, launcher.symbol_id)
        } catch {
          /* ignore */
        }
        setStrategyIdState(launcher.strategy_id)
        try {
          localStorage.setItem(LS_STRATEGY, launcher.strategy_id)
        } catch {
          /* ignore */
        }
        setFramework(launcher.framework)
        const saved = readJsonLs<string[]>(
          symbolIdsKey(launcher.strategy_id),
          [launcher.symbol_id],
        )
        const next = saved.includes(launcher.symbol_id)
          ? saved
          : [...saved, launcher.symbol_id]
        setSymbolIdsState(next)
        writeJsonLs(symbolIdsKey(launcher.strategy_id), next)
      }
    },
    [catalog],
  )

  const persistSymbolIds = useCallback(
    (ids: string[], strat = strategyId) => {
      const next = ids.length ? ids : ['au']
      setSymbolIdsState(next)
      writeJsonLs(symbolIdsKey(strat), next)
    },
    [strategyId],
  )

  const selectSymbol = useCallback(
    (id: string) => {
      setSymbolId(id)
      try {
        localStorage.setItem(LS_SYMBOL, id)
      } catch {
        /* ignore */
      }
      persistSymbolIds(
        symbolIds.includes(id) ? symbolIds : [...symbolIds, id],
      )
      const iid = instanceIdFor(catalog, strategyId, id)
      if (iid !== instanceId) {
        setInstanceId(iid)
        repairedRef.current = false
        try {
          localStorage.setItem(LS_INSTANCE, iid)
        } catch {
          /* ignore */
        }
      }
    },
    [catalog, instanceId, persistSymbolIds, strategyId, symbolIds],
  )

  const selectStrategy = useCallback(
    (id: string) => {
      setStrategyIdState(id)
      try {
        localStorage.setItem(LS_STRATEGY, id)
      } catch {
        /* ignore */
      }
      const saved = readJsonLs<string[]>(symbolIdsKey(id), ['au'])
      const nextIds = saved.length ? saved : ['au']
      persistSymbolIds(nextIds, id)
      const focus = nextIds.includes(symbolId) ? symbolId : nextIds[0]
      const iid = instanceIdFor(catalog, id, focus)
      setSymbolId(focus)
      try {
        localStorage.setItem(LS_SYMBOL, focus)
      } catch {
        /* ignore */
      }
      if (iid !== instanceId) {
        setInstanceId(iid)
        repairedRef.current = false
        try {
          localStorage.setItem(LS_INSTANCE, iid)
        } catch {
          /* ignore */
        }
      }
    },
    [catalog, instanceId, persistSymbolIds, symbolId],
  )

  const resolvedInstanceId = instanceIdFor(catalog, strategyId, symbolId)

  useEffect(() => {
    if (!resolvedInstanceId || resolvedInstanceId === instanceId) return
    setInstanceId(resolvedInstanceId)
    repairedRef.current = false
    try {
      localStorage.setItem(LS_INSTANCE, resolvedInstanceId)
    } catch {
      /* ignore */
    }
  }, [instanceId, resolvedInstanceId])

  useEffect(() => {
    setSummary(null)
    setMetrics(null)
    setDecisions([])
    setIntents([])
    setFills([])
    setPositionHistory([])
    setError(null)
    setWarn(null)
  }, [instanceId])

  const ensureCatalog = useCallback(async (force = false) => {
    if (catalogLoadedRef.current && !force && catalogRef.current) {
      return catalogRef.current
    }
    const [cat, sess] = await Promise.all([fetchSimCatalog(), fetchSimSessions()])
    catalogLoadedRef.current = true
    catalogRef.current = cat
    setCatalog(cat)
    setSessions(sess.sessions || [])
    setFleet(sess.fleet || [])
    return cat
  }, [])

  const refreshLight = useCallback(async () => {
    if (lightInFlightRef.current || replayAt) return
    lightInFlightRef.current = true
    const gen = refreshGenRef.current
    const stale = () => gen !== refreshGenRef.current
    try {
      const id = instanceId
      if (!id) {
        setLoading(false)
        return
      }
      const [sum, sess] = await Promise.all([fetchSimSummary(id), fetchSimSessions()])
      if (stale()) return
      if (sum.instance_id && sum.instance_id !== id) return
      setSummary(sum)
      setSessions(sess.sessions || [])
      setFleet(sess.fleet || [])
      setError(null)
      const livePrice = sum.last_price ?? null
      if (livePrice != null) {
        setBars((prev) => (prev?.bars?.length ? withLiveTip(prev, livePrice) : prev))
      }
    } catch (e) {
      if (!stale()) {
        const msg = e instanceof Error ? e.message : String(e)
        setSummary(null)
        setError(
          msg.includes('404') || msg.includes('not found')
            ? '尚未启动或暂无会话数据。当前为云端只读时请确认交易机已同步；本机可启动模拟盘。'
            : msg,
        )
      }
    } finally {
      if (gen === refreshGenRef.current) {
        lightInFlightRef.current = false
        setLoading(false)
      }
    }
  }, [instanceId, replayAt])

  const refreshHeavy = useCallback(async () => {
    if (heavyInFlightRef.current) return
    heavyInFlightRef.current = true
    const gen = refreshGenRef.current
    const stale = () => gen !== refreshGenRef.current
    try {
      const cat = await ensureCatalog(false)
      if (stale()) return

      const id = instanceId
      if (!id) {
        setLoading(false)
        return
      }

      const cloudMode = cat.read_only || cat.data_source === 'cloud'
      if (!cloudMode && !repairedRef.current) {
        repairedRef.current = true
        void repairSimFills(id).catch(() => undefined)
      }

      if (replayAt) {
        try {
          const rp = await fetchSimReplay(id, replayAt)
          if (stale()) return
          setReplay(rp)
          const barEnd = rp.at
          const [dec, intentRes, fillRes, barRes] = await Promise.all([
            fetchSimDecisions(id, { limit: 40 }),
            fetchSimIntents(id, 80),
            fetchSimFills(id, 200),
            fetchSimBars(id, { end: barEnd, limit: CHART_BAR_LIMIT }),
          ])
          const cut = replayAt
          setDecisions((dec.decisions || []).filter((d) => !cut || (d.created_at || '') <= cut))
          setIntents((intentRes.intents || []).filter((d) => !cut || (d.created_at || '') <= cut))
          setFills(rp.fills || fillRes.fills || [])
          setBars(barRes)
          setSummary((prev) =>
            prev
              ? {
                  ...prev,
                  account: rp.account
                    ? {
                        equity: rp.account.equity,
                        available: rp.account.available,
                        margin: rp.account.margin,
                        margin_ratio: rp.account.margin_ratio,
                        as_of: rp.account.as_of,
                        created_at: rp.account.created_at,
                      }
                    : prev.account,
                  position: rp.position
                    ? {
                        symbol: rp.position.symbol,
                        net_position: rp.position.net_position,
                        source: 'replay',
                        as_of: rp.position.as_of,
                      }
                    : prev.position,
                }
              : prev,
          )
          if (rp.metrics_snapshot) {
            setMetrics((prev) => ({
              instance_id: id,
              equity: rp.metrics_snapshot.equity,
              init_balance: prev?.init_balance ?? 1_000_000,
              pnl: rp.metrics_snapshot.pnl,
              pnl_pct: rp.metrics_snapshot.pnl / (prev?.init_balance ?? 1_000_000),
              trade_count: prev?.trade_count ?? 0,
              fill_count: rp.metrics_snapshot.fill_count,
              wins: prev?.wins ?? 0,
              losses: prev?.losses ?? 0,
              win_rate: prev?.win_rate ?? 0,
              max_drawdown_pct: prev?.max_drawdown_pct ?? 0,
              open_position: rp.position?.net_position ?? prev?.open_position ?? 0,
              equity_curve: prev?.equity_curve ?? [],
            }))
          }
          setError(null)
          setWarn(null)
        } catch (e) {
          if (!stale()) setError(e instanceof Error ? e.message : String(e))
        }
        if (!stale()) setLoading(false)
        return
      }

      // Heavy path: K-lines + overseas HTTP. Do not await on the light quote path.
      const marketBarsPromise = fetchSimMarketBars(symbolId, {
        limit: CHART_BAR_LIMIT,
        strategyId,
      }).catch(() => null)
      const overseasPromise = fetchSimOverseasBars(symbolId, {
        limit: OVERSEAS_CHART_BAR_LIMIT,
        instanceId: id,
      }).catch(() => null)

      const settled = await Promise.allSettled([
        fetchSimSummary(id),
        fetchSimMetrics(id),
        fetchSimDecisions(id, { limit: 40 }),
        fetchSimIntents(id, 80),
        fetchSimFills(id, 200),
        fetchSimBars(id, { limit: CHART_BAR_LIMIT }),
        marketBarsPromise,
        overseasPromise,
        fetchSimSessions(),
        fetchSimPositionHistory(id, 100),
      ])

      const [sumR, metR, decR, intentR, fillR, barR, marketR, overseasR, sessR, histR] =
        settled
      if (stale()) return

      const partial: string[] = []

      if (sumR.status === 'fulfilled' && sumR.value.instance_id === id) {
        setSummary(sumR.value)
        setError(null)
      } else if (sumR.status === 'fulfilled') {
        setSummary(null)
      } else {
        const msg = sumR.reason instanceof Error ? sumR.reason.message : String(sumR.reason)
        setSummary(null)
        setError(
          msg.includes('404') || msg.includes('not found')
            ? '尚未启动或暂无会话数据。当前为云端只读时请确认交易机已同步；本机可启动模拟盘。'
            : msg,
        )
      }

      if (metR.status === 'fulfilled' && metR.value.instance_id === id) {
        setMetrics(metR.value)
      } else {
        setMetrics(null)
        if (metR.status === 'rejected') partial.push('绩效指标')
      }

      if (decR.status === 'fulfilled') setDecisions(decR.value.decisions || [])
      else {
        setDecisions([])
        partial.push('决策链')
      }

      if (intentR.status === 'fulfilled') setIntents(intentR.value.intents || [])
      else {
        setIntents([])
        partial.push('订单意图')
      }

      if (fillR.status === 'fulfilled') setFills(fillR.value.fills || [])
      else {
        setFills([])
        partial.push('成交记录')
      }

      if (histR.status === 'fulfilled') setPositionHistory(histR.value.positions || [])
      else {
        setPositionHistory([])
        partial.push('历史持仓')
      }

      if (sessR.status === 'fulfilled') {
        setSessions(sessR.value.sessions || [])
        setFleet(sessR.value.fleet || [])
      }

      setWarn(partial.length ? `部分数据加载失败：${partial.join('、')}` : null)

      if (overseasR.status === 'fulfilled' && overseasR.value) {
        const next = overseasR.value
        setOverseas((prev) => {
          const merged = mergePreserveOverseas(prev, next)
          if (
            prev &&
            prev.symbol_id === merged.symbol_id &&
            prev.bars.length === merged.bars.length &&
            prev.last_price === merged.last_price &&
            prev.has_more === merged.has_more &&
            prev.bars[prev.bars.length - 1]?.time ===
              merged.bars[merged.bars.length - 1]?.time &&
            prev.bars[prev.bars.length - 1]?.close ===
              merged.bars[merged.bars.length - 1]?.close
          ) {
            return prev
          }
          return merged
        })
      } else {
        setOverseas((prev) =>
          prev?.symbol_id === symbolId
            ? prev
            : {
                symbol_id: symbolId,
                supported: false,
                bars: [],
                last_price: null,
                has_more: false,
                hint: '外盘对照暂不可用',
              },
        )
      }

      const market =
        marketR.status === 'fulfilled' && marketR.value ? marketR.value : null
      const sessionBars = barR.status === 'fulfilled' ? barR.value : null
      const livePrice =
        sumR.status === 'fulfilled' ? sumR.value.last_price ?? null : null
      const launcherSymbolId =
        cat?.launchers?.find((l) => l.instance_id === id)?.symbol_id ?? null
      const sessionMatchesSymbol = launcherSymbolId != null && launcherSymbolId === symbolId

      if (sessionMatchesSymbol && sessionBars?.bars?.length) {
        setBars((prev) => mergePreserveHistory(prev, withLiveTip(sessionBars, livePrice)))
      } else if (market?.bars?.length && market.symbol_id === symbolId) {
        setBars((prev) =>
          mergePreserveHistory(prev, {
            instance_id: id,
            signal_symbol: market.signal_symbol,
            trade_symbol: market.trade_symbol,
            bars: market.bars,
            markers: [],
            overlays: market.overlays,
            overlay_specs: market.overlay_specs,
            bar_meta: market.bar_meta,
            price_lines: market.price_lines,
            has_more: market.has_more,
            last_price: market.last_price,
            updated_at: market.updated_at,
            hint:
              market.hint ||
              (sessionMatchesSymbol
                ? undefined
                : `当前运行会话是 ${launcherSymbolId ?? '其他品种'}；以下为 ${symbolId} 的行情快照（非本会话成交标记）。`),
            chart_context: market.chart_context,
            market_session: market.market_session,
          }),
        )
      } else if (market && market.symbol_id === symbolId) {
        setBars({
          instance_id: id,
          signal_symbol: market.signal_symbol,
          trade_symbol: market.trade_symbol,
          bars: [],
          markers: [],
          overlays: market.overlays,
          overlay_specs: market.overlay_specs,
          bar_meta: market.bar_meta,
          price_lines: market.price_lines,
          has_more: false,
          last_price: market.last_price,
          updated_at: market.updated_at,
          hint:
            market.hint ||
            `暂无 ${symbolId} 的天勤模拟 K 线。当前可启动会话仅覆盖 ${launcherSymbolId ?? '已配置品种'}。`,
          chart_context: market.chart_context,
          market_session: market.market_session,
        })
      } else if (sessionMatchesSymbol && sessionBars) {
        setBars({
          ...sessionBars,
          last_price: livePrice ?? sessionBars.last_price,
        })
      } else {
        setBars({
          instance_id: id,
          signal_symbol: '',
          trade_symbol: '',
          bars: [],
          markers: [],
          last_price: null,
          hint: `暂无 ${symbolId} 内盘 K 线。模拟盘会话「${id}」对应品种为 ${launcherSymbolId ?? '未知'}，切换品种不会自动换成该会话行情。`,
        })
      }

      setReplay(null)
    } catch (e) {
      if (!stale()) setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (gen === refreshGenRef.current) {
        heavyInFlightRef.current = false
        setLoading(false)
      }
    }
  }, [ensureCatalog, instanceId, replayAt, symbolId])

  const refresh = useCallback(async () => {
    catalogLoadedRef.current = false
    await refreshHeavy()
  }, [refreshHeavy])

  const mergeOlderBars = useCallback((prev: SimBarsResponse, older: SimBarsResponse): SimBarsResponse => {
    const seen = new Set(prev.bars.map((b) => b.time))
    const prependBars = (older.bars || []).filter((b) => !seen.has(b.time))
    if (!prependBars.length) {
      return { ...prev, has_more: Boolean(older.has_more) }
    }
    const mergedBars = [...prependBars, ...prev.bars].slice(-CHART_BAR_MAX)
    const metaMap = new Map((prev.bar_meta || []).map((m) => [m.time, m]))
    for (const m of older.bar_meta || []) metaMap.set(m.time, m)
    const keys = collectOverlayKeys(prev.overlay_specs ?? older.overlay_specs, {
      ...older.overlays,
      ...prev.overlays,
    })
    const overlays = mergeOverlayMaps(older.overlays, prev.overlays, keys)
    return {
      ...prev,
      bars: mergedBars,
      bar_meta: mergedBars.map(
        (b) => metaMap.get(b.time) || { time: b.time, source: 'replay' },
      ),
      overlays,
      has_more: Boolean(older.has_more) && mergedBars.length < CHART_BAR_MAX,
      hint: older.hint || prev.hint,
      overlay_specs: prev.overlay_specs?.length ? prev.overlay_specs : older.overlay_specs,
    }
  }, [])

  const loadMoreHistory = useCallback(async () => {
    if (historyInFlightRef.current || replayAt) return
    const current = bars
    if (!current?.bars?.length || current.has_more === false) return
    const before = current.bars[0]?.time
    if (before == null) return
    historyInFlightRef.current = true
    setHistoryLoading(true)
    const gen = refreshGenRef.current
    try {
      const cat = catalogRef.current
      const launcherSymbolId =
        cat?.launchers?.find((l) => l.instance_id === instanceId)?.symbol_id ?? null
      const sessionMatchesSymbol = launcherSymbolId != null && launcherSymbolId === symbolId
      const older = sessionMatchesSymbol
        ? await fetchSimBars(instanceId, { limit: CHART_BAR_CHUNK, before })
        : await fetchSimMarketBars(symbolId, {
            limit: CHART_BAR_CHUNK,
            before,
            strategyId,
          })
      if (gen !== refreshGenRef.current) return
      setBars((prev) => (prev ? mergeOlderBars(prev, older) : older))
    } catch {
      /* keep current window */
    } finally {
      historyInFlightRef.current = false
      setHistoryLoading(false)
    }
  }, [bars, instanceId, mergeOlderBars, replayAt, symbolId, strategyId])

  const loadMoreOverseasHistory = useCallback(async () => {
    if (overseasHistoryInFlightRef.current || replayAt) return
    const current = overseas
    if (!current?.supported || !current.bars?.length || current.has_more === false) return
    const before = current.bars[0]?.time
    if (before == null) return
    overseasHistoryInFlightRef.current = true
    setOverseasHistoryLoading(true)
    const gen = refreshGenRef.current
    try {
      const older = await fetchSimOverseasBars(symbolId, {
        limit: OVERSEAS_CHART_BAR_CHUNK,
        before,
        instanceId,
      })
      if (gen !== refreshGenRef.current) return
      setOverseas((prev) => (prev ? mergeOlderOverseas(prev, older) : older))
    } catch {
      /* keep current window */
    } finally {
      overseasHistoryInFlightRef.current = false
      setOverseasHistoryLoading(false)
    }
  }, [instanceId, overseas, replayAt, symbolId])

  useEffect(() => {
    // Invalidate in-flight responses when session/symbol/replay changes.
    refreshGenRef.current += 1
    lightInFlightRef.current = false
    heavyInFlightRef.current = false
  }, [instanceId, symbolId, replayAt])

  useEffect(() => {
    setOverseas(null)
    setBars(null)
  }, [instanceId, symbolId])

  useEffect(() => {
    void refreshHeavy()
  }, [refreshHeavy])

  useEffect(() => {
    if (replayAt) return
    let cancelled = false
    let lightTimer = 0
    let heavyTimer = 0

    const scheduleLight = (delay: number) => {
      lightTimer = window.setTimeout(() => {
        if (cancelled) return
        void refreshLight().finally(() => {
          if (!cancelled) scheduleLight(LIGHT_POLL_MS)
        })
      }, delay)
    }

    const scheduleHeavy = (delay: number) => {
      heavyTimer = window.setTimeout(() => {
        if (cancelled) return
        void refreshHeavy().finally(() => {
          if (!cancelled) scheduleHeavy(HEAVY_POLL_MS)
        })
      }, delay)
    }

    scheduleLight(LIGHT_POLL_MS)
    scheduleHeavy(HEAVY_POLL_MS)

    return () => {
      cancelled = true
      window.clearTimeout(lightTimer)
      window.clearTimeout(heavyTimer)
    }
  }, [refreshLight, refreshHeavy, replayAt])

  const value = useMemo<Ctx>(
    () => ({
      catalog,
      sessions,
      fleet,
      instanceId,
      setInstanceId: selectInstance,
      framework,
      setFramework,
      strategyId,
      setStrategyId: selectStrategy,
      symbolId,
      setSymbolId: selectSymbol,
      symbolIds,
      setSymbolIds: persistSymbolIds,
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
      starting,
      setStarting,
      replayAt,
      replay,
      setReplayAt,
      refresh,
      loadMoreHistory,
      loadMoreOverseasHistory,
      historyLoading,
      overseasHistoryLoading,
    }),
    [
      catalog,
      sessions,
      fleet,
      instanceId,
      selectInstance,
      framework,
      strategyId,
      selectStrategy,
      symbolId,
      selectSymbol,
      symbolIds,
      persistSymbolIds,
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
      starting,
      replayAt,
      replay,
      refresh,
      loadMoreHistory,
      loadMoreOverseasHistory,
      historyLoading,
      overseasHistoryLoading,
    ],
  )

  return <SimCockpitContext.Provider value={value}>{children}</SimCockpitContext.Provider>
}

export function useSimCockpit() {
  const ctx = useContext(SimCockpitContext)
  if (!ctx) throw new Error('useSimCockpit must be used within SimCockpitProvider')
  return ctx
}
