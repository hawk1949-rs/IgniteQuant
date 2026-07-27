import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type CandlestickData,
  type Time,
} from 'lightweight-charts'

export type MiniBar = {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export type MiniMarker = {
  time: number
  position?: string
  color: string
  shape?: string
  text: string
}

type Props = {
  bars: MiniBar[]
  markers?: MiniMarker[]
  height?: number
}

/** Lightweight Charts 按 UTC 画轴；把 unix 秒转成「本地墙钟」伪 UTC，轴上即看本地时间。 */
function timeToLocal(unixSec: number): number {
  const d = new Date(unixSec * 1000)
  return (
    Date.UTC(
      d.getFullYear(),
      d.getMonth(),
      d.getDate(),
      d.getHours(),
      d.getMinutes(),
      d.getSeconds(),
      d.getMilliseconds(),
    ) / 1000
  )
}

function toCandle(b: MiniBar): CandlestickData<Time> {
  return {
    time: timeToLocal(b.time) as Time,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }
}

function markersEqual(a: MiniMarker[], b: MiniMarker[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    const x = a[i]
    const y = b[i]
    if (
      x.time !== y.time ||
      x.color !== y.color ||
      x.text !== y.text ||
      x.position !== y.position ||
      x.shape !== y.shape
    ) {
      return false
    }
  }
  return true
}

function applyMarkers(
  markersApi: ISeriesMarkersPluginApi<Time>,
  data: CandlestickData<Time>[],
  markers: MiniMarker[],
) {
  const barTimes = new Set(data.map((d) => d.time))
  const snapped = markers
    .map((m) => {
      const raw = {
        time: timeToLocal(m.time) as Time,
        position: (m.position === 'belowBar' ? 'belowBar' : 'aboveBar') as
          | 'belowBar'
          | 'aboveBar',
        color: m.color,
        shape: (m.shape === 'arrowUp'
          ? 'arrowUp'
          : m.shape === 'arrowDown'
            ? 'arrowDown'
            : 'circle') as 'arrowUp' | 'arrowDown' | 'circle',
        text: m.text,
      }
      if (barTimes.has(raw.time)) return raw
      let best: Time | null = null
      for (const t of data) {
        if ((t.time as number) <= (raw.time as number)) best = t.time
      }
      return best ? { ...raw, time: best } : null
    })
    .filter(Boolean) as {
    time: Time
    position: 'belowBar' | 'aboveBar'
    color: string
    shape: 'arrowUp' | 'arrowDown' | 'circle'
    text: string
  }[]
  markersApi.setMarkers(snapped)
}

type AppliedSnapshot = {
  len: number
  firstTime: number
  lastTime: number
  lastClose: number
  lastHigh: number
  lastLow: number
  lastOpen: number
}

function sameLastBar(prev: AppliedSnapshot, last: MiniBar): boolean {
  return (
    prev.lastTime === last.time &&
    prev.lastClose === last.close &&
    prev.lastHigh === last.high &&
    prev.lastLow === last.low &&
    prev.lastOpen === last.open
  )
}

export function MiniCandleChart({ bars, markers = [], height = 280 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const appliedRef = useRef<AppliedSnapshot | null>(null)
  const markersCacheRef = useRef<MiniMarker[]>([])
  const fittedRef = useRef(false)
  const [chartReady, setChartReady] = useState(0)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#1a2740' },
        textColor: '#9db0c9',
      },
      grid: {
        vertLines: { color: 'rgba(180,200,230,0.12)' },
        horzLines: { color: 'rgba(180,200,230,0.12)' },
      },
      width: containerRef.current.clientWidth,
      height,
      localization: {
        locale: 'zh-CN',
        dateFormat: 'yyyy-MM-dd',
      },
      timeScale: {
        borderColor: 'rgba(180,200,230,0.28)',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: { borderColor: 'rgba(180,200,230,0.28)' },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#30d158',
      downColor: '#ff453a',
      borderVisible: false,
      wickUpColor: '#30d158',
      wickDownColor: '#ff453a',
    })
    chartRef.current = chart
    seriesRef.current = series
    markersRef.current = createSeriesMarkers(series, [])
    appliedRef.current = null
    fittedRef.current = false
    setChartReady((n) => n + 1)
    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      markersRef.current = null
      appliedRef.current = null
      fittedRef.current = false
    }
  }, [height])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    const markersApi = markersRef.current
    if (!series || !chart || !markersApi || chartReady === 0) return

    if (!bars.length) {
      series.setData([])
      markersApi.setMarkers([])
      appliedRef.current = null
      fittedRef.current = false
      return
    }

    const data = bars.map(toCandle)
    const first = bars[0]
    const last = bars[bars.length - 1]
    const prev = appliedRef.current
    const remember = (): AppliedSnapshot => ({
      len: bars.length,
      firstTime: first.time,
      lastTime: last.time,
      lastClose: last.close,
      lastHigh: last.high,
      lastLow: last.low,
      lastOpen: last.open,
    })

    const sameTail =
      prev != null && prev.len === bars.length && prev.lastTime === last.time
    const appendedOne =
      prev != null &&
      bars.length === prev.len + 1 &&
      bars[bars.length - 2]?.time === prev.lastTime
    // Rolling window: length unchanged, first bar slid, last bar advanced or refreshed.
    const slidWindow =
      prev != null &&
      prev.len === bars.length &&
      prev.firstTime !== first.time

    if (sameTail && prev && sameLastBar(prev, last)) {
      // unchanged OHLC
    } else if (sameTail || appendedOne) {
      series.update(toCandle(last))
      appliedRef.current = remember()
    } else if (slidWindow) {
      // Replace data quietly — do NOT fitContent (avoids overseas flicker).
      series.setData(data)
      appliedRef.current = remember()
    } else {
      series.setData(data)
      if (!fittedRef.current) {
        chart.timeScale().fitContent()
        fittedRef.current = true
      }
      appliedRef.current = remember()
    }

    if (!markersEqual(markersCacheRef.current, markers)) {
      applyMarkers(markersApi, data, markers)
      markersCacheRef.current = markers
    }
  }, [bars, markers, chartReady])

  return <div ref={containerRef} className="w-full overflow-hidden rounded-xl" />
}
