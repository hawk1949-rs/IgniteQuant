/** Chart timeframe helpers for Sim Cockpit candle panels. */

export type ChartTimeframe = '5m' | '15m' | '1h' | '1d'

export const CHART_TIMEFRAMES: { value: ChartTimeframe; label: string }[] = [
  { value: '5m', label: '5分钟' },
  { value: '15m', label: '15分钟' },
  { value: '1h', label: '1小时' },
  { value: '1d', label: '日线' },
]

export type OhlcBar = {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export type ChartMarker = {
  time: number
  position?: string
  color: string
  shape?: string
  text: string
}

const PERIOD_SEC: Record<Exclude<ChartTimeframe, '1d'>, number> = {
  '5m': 300,
  '15m': 900,
  '1h': 3600,
}

/** Bucket start in unix seconds, aligned to local wall clock (CN futures sessions). */
export function bucketStart(unixSec: number, tf: ChartTimeframe): number {
  const d = new Date(unixSec * 1000)
  if (tf === '1d') {
    d.setHours(0, 0, 0, 0)
    return Math.floor(d.getTime() / 1000)
  }
  const periodMin = PERIOD_SEC[tf] / 60
  const totalMin = d.getHours() * 60 + d.getMinutes()
  const bucketMin = Math.floor(totalMin / periodMin) * periodMin
  d.setHours(Math.floor(bucketMin / 60), bucketMin % 60, 0, 0)
  return Math.floor(d.getTime() / 1000)
}

/** Aggregate lower-TF OHLC (typically 5m) into a higher timeframe. */
export function aggregateBars(bars: OhlcBar[], tf: ChartTimeframe): OhlcBar[] {
  if (!bars.length) return []
  if (tf === '5m') return bars.map((b) => ({ ...b }))

  const out: OhlcBar[] = []
  let cur: OhlcBar | null = null
  let curBucket = -1

  for (const b of bars) {
    const bucket = bucketStart(b.time, tf)
    if (bucket !== curBucket || cur == null) {
      if (cur) out.push(cur)
      curBucket = bucket
      cur = {
        time: bucket,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
        volume: b.volume ?? 0,
      }
      continue
    }
    cur.high = Math.max(cur.high, b.high)
    cur.low = Math.min(cur.low, b.low)
    cur.close = b.close
    cur.volume = (cur.volume ?? 0) + (b.volume ?? 0)
  }
  if (cur) out.push(cur)
  return out
}

/** Snap markers onto aggregated bar times (last bar ≤ marker time). */
export function aggregateMarkers(
  markers: ChartMarker[] | undefined,
  bars: OhlcBar[],
): ChartMarker[] {
  if (!markers?.length || !bars.length) return []
  const times = bars.map((b) => b.time)
  return markers
    .map((m) => {
      let best: number | null = null
      for (const t of times) {
        if (t <= m.time) best = t
        else break
      }
      return best == null ? null : { ...m, time: best }
    })
    .filter(Boolean) as ChartMarker[]
}
