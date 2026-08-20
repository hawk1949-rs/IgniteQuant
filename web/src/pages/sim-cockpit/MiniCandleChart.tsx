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
import type {
  SimBarMeta,
  SimChartOverlays,
  SimEnergyProfile,
  SimOverlaySpec,
  SimPriceLine,
} from '../../lib/api'
import { computeEnergyProfile, type EnergyProfile } from './energyProfile'
import { DEFAULT_OVERLAY_SPECS, resolveOverlaySpecs } from './strategyPresentation'

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
  overlaySpecs?: SimOverlaySpec[] | null
  barMeta?: SimBarMeta[] | null
  priceLines?: SimPriceLine[] | null
  /** GMA 2.0 right-side volume profile; recomputed from visible bars when omitted. */
  energyProfile?: SimEnergyProfile | null
  showEnergyProfile?: boolean
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

const ENERGY_WIDTH = 128
/** 教程配色：VA 内绿、边缘灰、POC 紫、缺口亮绿 */
const ENERGY_COLORS = {
  va: 'rgba(34, 140, 70, 0.72)',
  edge: 'rgba(120, 120, 128, 0.55)',
  poc: 'rgba(191, 90, 242, 0.95)',
  vahVal: '#30d158',
  gap: '#00e676',
  volumeText: 'rgba(255,255,255,0.92)',
} as const

function formatVolLabel(v: number): string {
  if (v >= 1000) return String(Math.round(v))
  if (v >= 10) return v.toFixed(0)
  return v.toFixed(1)
}

function drawEnergyHistogram(
  canvas: HTMLCanvasElement,
  series: ISeriesApi<'Candlestick'>,
  profile: EnergyProfile,
  chartHeight: number,
) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const dpr = window.devicePixelRatio || 1
  const cssW = ENERGY_WIDTH
  const cssH = chartHeight
  canvas.width = Math.floor(cssW * dpr)
  canvas.height = Math.floor(cssH * dpr)
  canvas.style.width = `${cssW}px`
  canvas.style.height = `${cssH}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, cssW, cssH)

  const bins = profile.bins || []
  if (!bins.length) return
  const maxVol = Math.max(...bins.map((b) => b.volume), 1e-9)
  const padRight = 2
  const labelReserve = 34
  const maxBarW = cssW - padRight - labelReserve - 4

  for (const bin of bins) {
    const yHigh = series.priceToCoordinate(bin.price_high)
    const yLow = series.priceToCoordinate(bin.price_low)
    if (yHigh == null || yLow == null) continue
    const top = Math.min(yHigh, yLow)
    const h = Math.max(Math.abs(yLow - yHigh) - 0.5, 1.2)
    const w = Math.max(2, (bin.volume / maxVol) * maxBarW)
    const x = cssW - padRight - w
    if (bin.is_poc) {
      ctx.fillStyle = ENERGY_COLORS.poc
    } else if (bin.in_va) {
      ctx.fillStyle = ENERGY_COLORS.va
    } else {
      ctx.fillStyle = ENERGY_COLORS.edge
    }
    ctx.fillRect(x, top, w, h)

    // 教程：每档左侧标注成交量数字
    if (h >= 7) {
      ctx.fillStyle = ENERGY_COLORS.volumeText
      ctx.font = `${bin.is_poc ? 'bold ' : ''}9px ui-sans-serif, system-ui, sans-serif`
      ctx.textAlign = 'right'
      ctx.textBaseline = 'middle'
      ctx.fillText(formatVolLabel(bin.volume), x - 3, top + h / 2)
    }
  }

  const drawLevel = (
    price: number | null | undefined,
    color: string,
    label: string,
    dashed = false,
  ) => {
    if (price == null || !Number.isFinite(price)) return
    const y = series.priceToCoordinate(price)
    if (y == null) return
    ctx.strokeStyle = color
    ctx.lineWidth = label === 'POC' ? 1.5 : 1
    ctx.setLineDash(dashed ? [4, 3] : [])
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(cssW, y)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = color
    ctx.font = '10px ui-sans-serif, system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'bottom'
    ctx.fillText(label, 2, Math.max(11, y - 1))
  }
  drawLevel(profile.vah, ENERGY_COLORS.vahVal, 'VAH')
  drawLevel(profile.val, ENERGY_COLORS.vahVal, 'VAL')
  drawLevel(profile.poc, ENERGY_COLORS.poc, 'POC')
  drawLevel(profile.gap_high, ENERGY_COLORS.gap, '缺口', true)
  drawLevel(profile.gap_low, ENERGY_COLORS.gap, '缺口', true)
}

function barsInVisibleRange(
  bars: MiniBar[],
  range: { from: number; to: number } | null,
): MiniBar[] {
  if (!bars.length) return []
  if (!range) return bars
  const from = Math.max(0, Math.floor(range.from))
  const to = Math.min(bars.length - 1, Math.ceil(range.to))
  if (to < from) return bars
  return bars.slice(from, to + 1)
}

export function MiniCandleChart({
  bars,
  markers = [],
  overlays = null,
  overlaySpecs = null,
  barMeta = null,
  priceLines = null,
  energyProfile: _energyProfileUnused = null,
  showEnergyProfile = false,
  height = 280,
  showSignalPane = true,
  onLoadMore,
}: Props) {
  // energyProfile API 载荷仅作调试参考；教程要求 Visible Bars，图上始终按视窗重算。
  void _energyProfileUnused
  const specs = resolveOverlaySpecs(overlaySpecs)
  const hasSignalPane = showSignalPane && specs.some((s) => s.pane === 'signal')
  const containerRef = useRef<HTMLDivElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const energyCanvasRef = useRef<HTMLCanvasElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const priceLineObjsRef = useRef<IPriceLine[]>([])
  const energyLevelLinesRef = useRef<IPriceLine[]>([])
  const appliedRef = useRef<AppliedSnapshot | null>(null)
  const markersCacheRef = useRef<MiniMarker[]>([])
  const fittedRef = useRef(false)
  const loadMoreLockRef = useRef(false)
  const barByLocalTimeRef = useRef<Map<number, MiniBar>>(new Map())
  const metaByLocalTimeRef = useRef<Map<number, SimBarMeta>>(new Map())
  const barsRef = useRef(bars)
  const onLoadMoreRef = useRef(onLoadMore)
  const [chartReady, setChartReady] = useState(0)

  useEffect(() => {
    barsRef.current = bars
  }, [bars])

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
        rightOffset: showEnergyProfile ? 12 : 0,
      },
      rightPriceScale: { borderColor: 'rgba(180,200,230,0.28)' },
      crosshair: {
        mode: 0,
      },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#30d158',
      downColor: '#ff453a',
      borderVisible: true,
      borderUpColor: '#1faa45',
      borderDownColor: '#d70015',
      wickUpColor: '#30d158',
      wickDownColor: '#ff453a',
    })
    series.priceScale().applyOptions({
      scaleMargins: { top: 0.05, bottom: hasSignalPane ? 0.22 : 0.05 },
    })

    const lineMap = new Map<string, ISeriesApi<'Line'>>()
    for (const spec of specs) {
      const isSignal = spec.pane === 'signal'
      if (isSignal && !hasSignalPane) continue
      const line = chart.addSeries(LineSeries, {
        color: spec.color,
        lineWidth: isSignal ? 2 : spec.key.includes('mid') || spec.key.includes('52') ? 2 : 1,
        priceScaleId: isSignal ? 'signal' : 'right',
        priceLineVisible: false,
        lastValueVisible: isSignal,
        crosshairMarkerVisible: isSignal,
      })
      lineMap.set(spec.key, line)
    }
    if (hasSignalPane) {
      chart.priceScale('signal').applyOptions({
        scaleMargins: { top: 0.82, bottom: 0.02 },
        borderVisible: false,
      })
    }

    chartRef.current = chart
    seriesRef.current = series
    overlaySeriesRef.current = lineMap
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
      const partsText =
        typeof meta?.score_parts_label === 'string' && meta.score_parts_label
          ? meta.score_parts_label
          : meta?.score_parts && Array.isArray(meta.score_parts)
            ? meta.score_parts.join('/')
            : '—'
      const overlayHints = specs
        .filter((s) => s.pane !== 'signal')
        .slice(0, 4)
        .map((s) => `${s.label} ${formatNum(meta?.[s.key] as number | null | undefined)}`)
        .join(' · ')
      tip.innerHTML = [
        `<div class="font-medium text-slate-100">${new Date(bar.time * 1000).toLocaleString('zh-CN')}</div>`,
        `<div>O ${formatNum(bar.open)}  H ${formatNum(bar.high)}  L ${formatNum(bar.low)}  C ${formatNum(bar.close)}</div>`,
        `<div>信号 <b>${meta?.signal ?? '—'}</b> · ${partsText}</div>`,
        `<div>regime ${meta?.regime ?? '—'} · ${sourceLabel(meta?.source)}</div>`,
        overlayHints ? `<div>${overlayHints}</div>` : '',
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
      overlaySeriesRef.current = new Map()
      markersRef.current = null
      priceLineObjsRef.current = []
      energyLevelLinesRef.current = []
      appliedRef.current = null
      fittedRef.current = false
    }
  }, [height, hasSignalPane, specs.map((s) => s.key).join('|'), showEnergyProfile])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    const markersApi = markersRef.current
    if (!series || !chart || !markersApi || chartReady === 0) return

    if (!bars.length) {
      series.setData([])
      for (const line of overlaySeriesRef.current.values()) line.setData([])
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

    for (const spec of specs) {
      overlaySeriesRef.current
        .get(spec.key)
        ?.setData(toLine(overlays?.[spec.key]))
    }

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
  }, [bars, markers, overlays, overlaySpecs, barMeta, priceLines, chartReady, specs])

  useEffect(() => {
    const canvas = energyCanvasRef.current
    const series = seriesRef.current
    const chart = chartRef.current
    if (!canvas || !series || !chart || chartReady === 0 || !showEnergyProfile) return

    const clearEnergyLevels = () => {
      for (const line of energyLevelLinesRef.current) {
        try {
          series.removePriceLine(line)
        } catch {
          /* ignore */
        }
      }
      energyLevelLinesRef.current = []
    }

    const syncEnergyLevels = (profile: EnergyProfile | null) => {
      clearEnergyLevels()
      if (!profile) return
      const levels: { price: number | null | undefined; title: string; color: string; style: number }[] =
        [
          { price: profile.vah, title: 'VAH', color: ENERGY_COLORS.vahVal, style: 0 },
          { price: profile.val, title: 'VAL', color: ENERGY_COLORS.vahVal, style: 0 },
          { price: profile.poc, title: 'POC', color: ENERGY_COLORS.poc, style: 0 },
          { price: profile.gap_high, title: '缺口', color: ENERGY_COLORS.gap, style: 2 },
          { price: profile.gap_low, title: '缺口', color: ENERGY_COLORS.gap, style: 2 },
        ]
      for (const lv of levels) {
        if (lv.price == null || !Number.isFinite(lv.price)) continue
        energyLevelLinesRef.current.push(
          series.createPriceLine({
            price: lv.price,
            color: lv.color,
            lineWidth: 1,
            lineStyle: lv.style,
            axisLabelVisible: true,
            title: lv.title,
          }),
        )
      }
    }

    const paint = () => {
      const range = chart.timeScale().getVisibleLogicalRange()
      const visibleBars = barsInVisibleRange(barsRef.current, range)
      // 教程：Visible Bars — 仅用当前视窗内 K 线重算能量分布
      const profile = computeEnergyProfile(visibleBars)
      if (!profile?.bins?.length) {
        const ctx = canvas.getContext('2d')
        ctx?.clearRect(0, 0, canvas.width, canvas.height)
        syncEnergyLevels(null)
        return
      }
      drawEnergyHistogram(canvas, series, profile, height)
      syncEnergyLevels(profile)
    }

    paint()
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => paint())
    const raf = requestAnimationFrame(paint)
    return () => {
      cancelAnimationFrame(raf)
      clearEnergyLevels()
    }
  }, [bars, chartReady, height, showEnergyProfile, overlays, priceLines])

  return (
    <div className="relative w-full">
      <div ref={containerRef} className="w-full overflow-hidden rounded-xl" />
      {showEnergyProfile ? (
        <canvas
          ref={energyCanvasRef}
          className="pointer-events-none absolute top-0 z-[5]"
          style={{ right: 48 }}
          aria-hidden
        />
      ) : null}
      <div
        ref={tooltipRef}
        className="pointer-events-none absolute z-10 hidden max-w-[min(220px,calc(100vw-2rem))] min-w-0 rounded-lg border border-white/10 bg-[#0f1a2c]/95 px-2.5 py-2 text-xs leading-5 text-slate-200 shadow-lg backdrop-blur sm:min-w-[220px]"
      />
      <div className="mt-1 flex flex-wrap gap-3 px-1 text-xs text-faint">
        {(specs.length ? specs : DEFAULT_OVERLAY_SPECS).map((spec) => (
          <span key={spec.key} className="inline-flex items-center gap-1">
            <i className="inline-block h-0.5 w-3" style={{ backgroundColor: spec.color }} />{' '}
            {spec.label}
          </span>
        ))}
        {showEnergyProfile ? (
          <>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: ENERGY_COLORS.va }} />{' '}
              VA(70%)
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: ENERGY_COLORS.edge }} />{' '}
              边缘
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: ENERGY_COLORS.poc }} />{' '}
              POC
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block h-2 w-2 rounded-sm" style={{ background: ENERGY_COLORS.gap }} />{' '}
              缺口
            </span>
            <span className="text-faint/80">Visible Bars · 50档</span>
          </>
        ) : null}
      </div>
    </div>
  )
}
