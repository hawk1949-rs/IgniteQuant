import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
  type SimBarsResponse,
  type SimCatalog,
  type SimDecision,
  type SimFill,
  type SimIntent,
  type SimMetrics,
  type SimOverseasBars,
  type SimSession,
  type SimSummary,
  type SimReplay,
} from '@/lib/api'

type Ctx = {
  catalog: SimCatalog | null
  sessions: SimSession[]
  instanceId: string
  setInstanceId: (id: string) => void
  framework: string
  setFramework: (id: string) => void
  strategyId: string
  setStrategyId: (id: string) => void
  symbolId: string
  setSymbolId: (id: string) => void
  summary: SimSummary | null
  metrics: SimMetrics | null
  decisions: SimDecision[]
  intents: SimIntent[]
  fills: SimFill[]
  bars: SimBarsResponse | null
  overseas: SimOverseasBars | null
  error: string | null
  loading: boolean
  starting: boolean
  setStarting: (v: boolean) => void
  replayAt: string | null
  replay: SimReplay | null
  setReplayAt: (at: string | null) => void
  refresh: () => Promise<void>
}

const SimCockpitContext = createContext<Ctx | null>(null)

/** Align refresh to next 5-minute K-line boundary (plus small buffer). */
const BOOTSTRAP_POLL_MS = 15_000

function msUntilNextFiveMinuteBoundary(now = Date.now()): number {
  const period = 5 * 60 * 1000
  const next = Math.ceil((now + 1000) / period) * period
  return Math.max(5_000, next - now + 2_000)
}

export function SimCockpitProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<SimCatalog | null>(null)
  const [sessions, setSessions] = useState<SimSession[]>([])
  const [instanceId, setInstanceId] = useState('falcon_au_sim')
  const [framework, setFramework] = useState('tq')
  const [strategyId, setStrategyId] = useState('falcon_v2')
  const [symbolId, setSymbolId] = useState('au')
  const [summary, setSummary] = useState<SimSummary | null>(null)
  const [metrics, setMetrics] = useState<SimMetrics | null>(null)
  const [decisions, setDecisions] = useState<SimDecision[]>([])
  const [intents, setIntents] = useState<SimIntent[]>([])
  const [fills, setFills] = useState<SimFill[]>([])
  const [bars, setBars] = useState<SimBarsResponse | null>(null)
  const [overseas, setOverseas] = useState<SimOverseasBars | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [replayAt, setReplayAt] = useState<string | null>(null)
  const [replay, setReplay] = useState<SimReplay | null>(null)

  const selectInstance = useCallback(
    (id: string) => {
      setInstanceId(id)
      const launcher = catalog?.launchers?.find((l) => l.instance_id === id)
      if (launcher) {
        setSymbolId(launcher.symbol_id)
        setStrategyId(launcher.strategy_id)
        setFramework(launcher.framework)
      }
    },
    [catalog],
  )

  const refresh = useCallback(async () => {
    try {
      const [cat, sess] = await Promise.all([fetchSimCatalog(), fetchSimSessions()])
      setCatalog(cat)
      setSessions(sess.sessions || [])

      const id = instanceId
      if (!id) {
        setLoading(false)
        return
      }

      if (replayAt) {
        try {
          const rp = await fetchSimReplay(id, replayAt)
          setReplay(rp)
          const barEnd = rp.at
          const [dec, intentRes, fillRes, barRes] = await Promise.all([
            fetchSimDecisions(id, { limit: 40 }),
            fetchSimIntents(id, 80),
            fetchSimFills(id, 80),
            fetchSimBars(id, { end: barEnd, limit: 400 }),
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
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e))
        }
        setLoading(false)
        return
      }

      const marketBarsPromise = fetchSimMarketBars(symbolId, 400).catch(() => null)
      // Clear previous overseas immediately so remount gets fresh fetch (no stale rb→au blank).
      setOverseas(null)
      const overseasPromise = fetchSimOverseasBars(symbolId, 400).catch(() => null)

      const settled = await Promise.allSettled([
        fetchSimSummary(id),
        fetchSimMetrics(id),
        fetchSimDecisions(id, { limit: 40 }),
        fetchSimIntents(id, 80),
        fetchSimFills(id, 80),
        fetchSimBars(id, { limit: 400 }),
        marketBarsPromise,
        overseasPromise,
      ])

      const [sumR, metR, decR, intentR, fillR, barR, marketR, overseasR] = settled

      if (sumR.status === 'fulfilled') {
        setSummary(sumR.value)
        setError(null)
      } else {
        setSummary(null)
        const msg = sumR.reason instanceof Error ? sumR.reason.message : String(sumR.reason)
        setError(
          msg.includes('404') || msg.includes('not found')
            ? '尚未启动或暂无会话数据，可点击「启动模拟盘」。'
            : msg,
        )
      }

      if (metR.status === 'fulfilled') setMetrics(metR.value)
      else setMetrics(null)

      if (decR.status === 'fulfilled') setDecisions(decR.value.decisions || [])
      else setDecisions([])

      if (intentR.status === 'fulfilled') setIntents(intentR.value.intents || [])
      else setIntents([])

      if (fillR.status === 'fulfilled') setFills(fillR.value.fills || [])
      else setFills([])

      if (overseasR.status === 'fulfilled' && overseasR.value) {
        setOverseas(overseasR.value)
      } else {
        setOverseas({
          symbol_id: symbolId,
          supported: false,
          bars: [],
          last_price: null,
          hint: '外盘对照暂不可用',
        })
      }

      const market =
        marketR.status === 'fulfilled' && marketR.value ? marketR.value : null
      const sessionBars = barR.status === 'fulfilled' ? barR.value : null
      const livePrice =
        sumR.status === 'fulfilled' ? sumR.value.last_price ?? null : null

      // Prefer Tq live session snapshot (with markers); never fall back to stale cache.
      if (sessionBars?.bars?.length) {
        setBars({
          ...sessionBars,
          last_price: livePrice ?? sessionBars.last_price,
        })
      } else if (market?.bars?.length) {
        setBars({
          instance_id: id,
          signal_symbol: market.signal_symbol,
          trade_symbol: market.trade_symbol,
          bars: market.bars,
          markers: [],
          last_price: livePrice ?? market.last_price,
          hint: market.hint,
        })
      } else if (sessionBars) {
        setBars({
          ...sessionBars,
          last_price: livePrice ?? sessionBars.last_price,
        })
      } else if (market) {
        setBars({
          instance_id: id,
          signal_symbol: market.signal_symbol,
          trade_symbol: market.trade_symbol,
          bars: [],
          markers: [],
          last_price: livePrice ?? market.last_price,
          hint: market.hint,
        })
      } else {
        setBars(null)
      }

      setReplay(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [instanceId, replayAt, symbolId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (replayAt) return
    let cancelled = false
    let timeoutId = 0

    const schedule = (delay: number) => {
      timeoutId = window.setTimeout(() => {
        if (cancelled) return
        void refresh().finally(() => {
          if (!cancelled) schedule(msUntilNextFiveMinuteBoundary())
        })
      }, delay)
    }

    // First auto refresh after bootstrap window, then on 5m boundaries.
    schedule(BOOTSTRAP_POLL_MS)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [refresh, replayAt])

  const value = useMemo<Ctx>(
    () => ({
      catalog,
      sessions,
      instanceId,
      setInstanceId: selectInstance,
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
      starting,
      setStarting,
      replayAt,
      replay,
      setReplayAt,
      refresh,
    }),
    [
      catalog,
      sessions,
      instanceId,
      selectInstance,
      framework,
      strategyId,
      symbolId,
      summary,
      metrics,
      decisions,
      intents,
      fills,
      bars,
      overseas,
      error,
      loading,
      starting,
      replayAt,
      replay,
      refresh,
    ],
  )

  return <SimCockpitContext.Provider value={value}>{children}</SimCockpitContext.Provider>
}

export function useSimCockpit() {
  const ctx = useContext(SimCockpitContext)
  if (!ctx) throw new Error('useSimCockpit must be used within SimCockpitProvider')
  return ctx
}
