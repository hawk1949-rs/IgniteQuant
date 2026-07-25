import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { OverviewPanel } from './sim-cockpit/OverviewPanel'
import { ReplayPanel } from './sim-cockpit/ReplayPanel'
import { SimCockpitProvider, useSimCockpit } from './sim-cockpit/SimCockpitContext'
import { statusLabel } from './sim-cockpit/labels'
import { formatLocalDateTime } from './sim-cockpit/time'

type Props = {
  onBackHome?: () => void
}

export type SimSection = 'overview' | 'replay'

const SIM_NAV: {
  id: SimSection
  label: string
  hint: string
}[] = [
  {
    id: 'overview',
    label: '座舱总览',
    hint: '行情 · 决策 · 委托',
  },
  {
    id: 'replay',
    label: '复盘',
    hint: '历史时刻截面',
  },
]

function formatClock(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function StatusBadge() {
  const { summary, replayAt } = useSimCockpit()
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])
  const status = summary?.status || 'IDLE'
  const text = summary?.status_label || statusLabel(status)
  const color =
    status === 'RUNNING'
      ? 'text-good'
      : status === 'STALE'
        ? 'text-amber-300'
        : 'text-muted'
  const dataAsOf = summary?.updated_at || summary?.last_price_as_of
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <span>
        系统时间 <span className="font-medium tabular-nums text-ink">{formatClock(now)}</span>
      </span>
      {dataAsOf ? (
        <span>
          数据更新 <span className="tabular-nums">{formatLocalDateTime(dataAsOf)}</span>
        </span>
      ) : null}
      <span>
        状态 <span className={cn('font-medium', color)}>{text}</span>
      </span>
      <span>{summary?.process_running ? '进程在线' : '进程离线'}</span>
      {summary?.symbol ? <span className="tabular-nums">{summary.symbol}</span> : null}
      {replayAt ? (
        <span className="rounded-md bg-blue/20 px-2 py-0.5 text-blue">复盘中</span>
      ) : null}
    </div>
  )
}

function SimCockpitInner({ onBackHome }: Props) {
  const [section, setSection] = useState<SimSection>('overview')

  return (
    <div className="mx-auto min-h-screen max-w-[92rem] px-3 pb-14 pt-4 sm:px-5 lg:px-6">
      <header className="mb-3 rounded-xl border border-line bg-panel/90 px-4 py-3.5 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {onBackHome ? (
              <button
                type="button"
                onClick={onBackHome}
                className="mb-1.5 text-[11px] font-medium text-blue hover:opacity-80"
              >
                ← 返回首页
              </button>
            ) : null}
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
                模拟盘座舱
              </h1>
              <p className="text-xs text-faint">天勤模拟 · 5 分钟节奏</p>
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted sm:text-sm">
              一页看完行情、账户、思考链路与委托成交；可一键启动，按 K 线自动刷新。
            </p>
            <div className="mt-2">
              <StatusBadge />
            </div>
          </div>

          <nav
            className="flex shrink-0 rounded-lg border border-line bg-surface/50 p-0.5"
            aria-label="座舱分区"
          >
            {SIM_NAV.map((item) => {
              const active = item.id === section
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSection(item.id)}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-left transition',
                    active ? 'bg-blue text-white' : 'text-muted hover:text-ink',
                  )}
                >
                  <p className="text-sm font-medium leading-none">{item.label}</p>
                  <p
                    className={cn(
                      'mt-1 text-[10px] leading-none',
                      active ? 'text-white/75' : 'text-faint',
                    )}
                  >
                    {item.hint}
                  </p>
                </button>
              )
            })}
          </nav>
        </div>
      </header>

      <main>{section === 'overview' ? <OverviewPanel /> : <ReplayPanel />}</main>
    </div>
  )
}

export default function SimCockpitPage({ onBackHome }: Props) {
  return (
    <SimCockpitProvider>
      <SimCockpitInner onBackHome={onBackHome} />
    </SimCockpitProvider>
  )
}
