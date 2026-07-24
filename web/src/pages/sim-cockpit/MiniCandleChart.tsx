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

function applyChartData(
  series: ISeriesApi<'Candlestick'>,
  chart: IChartApi,
  markersApi: ISeriesMarkersPluginApi<Time>,
  bars: MiniBar[],
  markers: MiniMarker[],
) {
  if (!bars.length) {
    series.setData([])
    markersApi.setMarkers([])
    return
  }
  const data: CandlestickData<Time>[] = bars.map((b) => ({
    time: b.time as Time,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }))
  series.setData(data)
  const barTimes = new Set(data.map((d) => d.time))
  const snapped = markers
    .map((m) => {
      const raw = {
        time: m.time as Time,
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
  chart.timeScale().fitContent()
}

export function MiniCandleChart({ bars, markers = [], height = 280 }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
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
      timeScale: { borderColor: 'rgba(180,200,230,0.28)' },
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
    }
  }, [height])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    const markersApi = markersRef.current
    if (!series || !chart || !markersApi || chartReady === 0) return
    applyChartData(series, chart, markersApi, bars, markers)
  }, [bars, markers, chartReady])

  return <div ref={containerRef} className="w-full overflow-hidden rounded-xl" />
}
