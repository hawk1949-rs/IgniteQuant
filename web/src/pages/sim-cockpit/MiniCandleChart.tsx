import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  createChart,
  createSeriesMarkers,
  LineSeries,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type CandlestickData,
  type LineData,
  type Time,
} from 'lightweight-charts'
import type { SimBarMeta, SimChartOverlays, SimPriceLine } from '../../lib/api'

export type MiniBar = {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
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
  overlays?: SimChartOverlays | null
  barMeta?: SimBarMeta[] | null
  priceLines?: SimPriceLine[] | null
  height?: number
  showSignalPane?: boolean
  onLoadMore?: () => void
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

function toLine(
  points: { time: number; value: number }[] | undefined,
): LineData<Time>[] {
  if (!points?.length) return []
  return points.map((p) => ({
    time: timeToLocal(p.time) as Time,
    value: p.value,
  }))
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

function formatNum(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return '—'
  return Number(v).toFixed(digits)
}

function sourceLabel(source?: string | null): string {
  if (source === 'live') return '实盘决策'
  if (source === 'replay') return '图表重算'
  return source || '—'
}

export function MiniCandleChart({
  bars,
  markers = [],
  overlays = null,
  barMeta = null,
  priceLines = null,
  height = 280,
  showSignalPane = true,
  onLoadMore,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const ma7Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ma14Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ma52Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const signalRef = useRef<ISeriesApi<'Line'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const priceLineObjsRef = useRef<IPriceLine[]>([])
  const appliedRef = useRef<AppliedSnapshot | null>(null)
  const markersCacheRef = useRef<MiniMarker[]>([])
  const fittedRef = useRef(false)
  const loadMoreLockRef = useRef(false)
  const barByLocalTimeRef = useRef<Map<number, MiniBar>>(new Map())
  const metaByLocalTimeRef = useRef<Map<number, SimBarMeta>>(new Map())
  const onLoadMoreRef = useRef(onLoadMore)
  const [chartReady, setChartReady] = useState(0)

  useEffect(() => {
    onLoadMoreRef.current = onLoadMore
  }, [onLoadMore])

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
      crosshair: {
        mode: 0,
      },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#30d158',
      downColor: '#ff453a',
      borderVisible: false,
      wickUpColor: '#30d158',
      wickDownColor: '#ff453a',
    })
    series.priceScale().applyOptions({
      scaleMargins: { top: 0.05, bottom: showSignalPane ? 0.22 : 0.05 },
    })

    const ma7 = chart.addSeries(LineSeries, {
      color: '#64d2ff',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const ma14 = chart.addSeries(LineSeries, {
      color: '#bf5af2',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const ma52 = chart.addSeries(LineSeries, {
      color: '#ffd60a',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    let signal: ISeriesApi<'Line'> | null = null
    if (showSignalPane) {
      signal = chart.addSeries(LineSeries, {
        color: '#ff9f0a',
        lineWidth: 2,
        priceScaleId: 'signal',
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
      })
      chart.priceScale('signal').applyOptions({
        scaleMargins: { top: 0.82, bottom: 0.02 },
        borderVisible: false,
      })
    }

    chartRef.current = chart
    seriesRef.current = series
    ma7Ref.current = ma7
    ma14Ref.current = ma14
    ma52Ref.current = ma52
    signalRef.current = signal
    markersRef.current = createSeriesMarkers(series, [])
    appliedRef.current = null
    fittedRef.current = false
    setChartReady((n) => n + 1)

    chart.subscribeCrosshairMove((param) => {
      const tip = tooltipRef.current
      const el = containerRef.current
      if (!tip || !el) return
      if (
        !param.point ||
        !param.time ||
        param.point.x < 0 ||
        param.point.y < 0 ||
        param.point.x > el.clientWidth ||
        param.point.y > el.clientHeight
      ) {
        tip.style.display = 'none'
        return
      }
      const localTime = param.time as number
      const bar = barByLocalTimeRef.current.get(localTime)
      const meta = metaByLocalTimeRef.current.get(localTime)
      if (!bar) {
        tip.style.display = 'none'
        return
      }
      const parts = meta?.score_parts
      const partsText =
        parts && parts.length >= 4
          ? `gv=${parts[0]} vol=${parts[1]} kdj=${parts[2]} pen=${parts[3]}`
          : '—'
      tip.innerHTML = [
        `<div class="font-medium text-slate-100">${new Date(bar.time * 1000).toLocaleString('zh-CN')}</div>`,
        `<div>O ${formatNum(bar.open)}  H ${formatNum(bar.high)}  L ${formatNum(bar.low)}  C ${formatNum(bar.close)}</div>`,
        `<div>信号 <b>${meta?.signal ?? '—'}</b> · ${partsText}</div>`,
        `<div>regime ${meta?.regime ?? '—'} · ${sourceLabel(meta?.source)}</div>`,
        `<div>MA7 ${formatNum(meta?.ma7)} · MA14 ${formatNum(meta?.ma14)} · MA52 ${formatNum(meta?.ma52)}</div>`,
        `<div>ATR ${formatNum(meta?.atr)} · ADX ${formatNum(meta?.adx)}</div>`,
      ].join('')
      tip.style.display = 'block'
      const left = Math.min(param.point.x + 16, el.clientWidth - 240)
      const top = Math.min(Math.max(param.point.y - 20, 8), el.clientHeight - 140)
      tip.style.left = `${left}px`
      tip.style.top = `${top}px`
    })

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!range || !onLoadMoreRef.current) return
      if (range.from > 5) {
        loadMoreLockRef.current = false
        return
      }
      if (loadMoreLockRef.current) return
      loadMoreLockRef.current = true
      onLoadMoreRef.current()
    })

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
      ma7Ref.current = null
      ma14Ref.current = null
      ma52Ref.current = null
      signalRef.current = null
      markersRef.current = null
      priceLineObjsRef.current = []
      appliedRef.current = null
      fittedRef.current = false
    }
  }, [height, showSignalPane])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    const markersApi = markersRef.current
    if (!series || !chart || !markersApi || chartReady === 0) return

    if (!bars.length) {
      series.setData([])
      ma7Ref.current?.setData([])
      ma14Ref.current?.setData([])
      ma52Ref.current?.setData([])
      signalRef.current?.setData([])
      markersApi.setMarkers([])
      appliedRef.current = null
      fittedRef.current = false
      barByLocalTimeRef.current = new Map()
      metaByLocalTimeRef.current = new Map()
      return
    }

    const data = bars.map(toCandle)
    const barMap = new Map<number, MiniBar>()
    for (const b of bars) barMap.set(timeToLocal(b.time), b)
    barByLocalTimeRef.current = barMap

    const metaMap = new Map<number, SimBarMeta>()
    for (const m of barMeta || []) metaMap.set(timeToLocal(m.time), m)
    metaByLocalTimeRef.current = metaMap

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
    const prepended =
      prev != null &&
      bars.length > prev.len &&
      last.time === prev.lastTime &&
      first.time !== prev.firstTime
    const slidWindow =
      prev != null && prev.len === bars.length && prev.firstTime !== first.time

    if (sameTail && prev && sameLastBar(prev, last)) {
      // unchanged OHLC
    } else if (sameTail || appendedOne) {
      series.update(toCandle(last))
      appliedRef.current = remember()
    } else if (prepended || slidWindow) {
      series.setData(data)
      appliedRef.current = remember()
      loadMoreLockRef.current = false
    } else {
      series.setData(data)
      if (!fittedRef.current) {
        chart.timeScale().fitContent()
        fittedRef.current = true
      }
      appliedRef.current = remember()
    }

    ma7Ref.current?.setData(toLine(overlays?.ma7))
    ma14Ref.current?.setData(toLine(overlays?.ma14))
    ma52Ref.current?.setData(toLine(overlays?.ma52))
    signalRef.current?.setData(toLine(overlays?.signal))

    for (const line of priceLineObjsRef.current) {
      try {
        series.removePriceLine(line)
      } catch {
        /* ignore */
      }
    }
    priceLineObjsRef.current = (priceLines || []).map((pl) =>
      series.createPriceLine({
        price: pl.price,
        color: pl.color,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: pl.title,
      }),
    )

    if (!markersEqual(markersCacheRef.current, markers)) {
      applyMarkers(markersApi, data, markers)
      markersCacheRef.current = markers
    }
  }, [bars, markers, overlays, barMeta, priceLines, chartReady])

  return (
    <div className="relative w-full">
      <div ref={containerRef} className="w-full overflow-hidden rounded-xl" />
      <div
        ref={tooltipRef}
        className="pointer-events-none absolute z-10 hidden min-w-[220px] rounded-lg border border-white/10 bg-[#0f1a2c]/95 px-2.5 py-2 text-[11px] leading-5 text-slate-200 shadow-lg backdrop-blur"
      />
      <div className="mt-1 flex flex-wrap gap-3 px-1 text-[10px] text-faint">
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0.5 w-3 bg-[#64d2ff]" /> MA7
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0.5 w-3 bg-[#bf5af2]" /> MA14
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0.5 w-3 bg-[#ffd60a]" /> MA52
        </span>
        {showSignalPane ? (
          <span className="inline-flex items-center gap-1">
            <i className="inline-block h-0.5 w-3 bg-[#ff9f0a]" /> 信号
          </span>
        ) : null}
      </div>
    </div>
  )
}
