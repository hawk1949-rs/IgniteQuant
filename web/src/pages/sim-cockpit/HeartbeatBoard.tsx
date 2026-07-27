import { useEffect, useMemo, useState } from 'react'
import { Tag, Tooltip } from 'antd'
import { useSimCockpit } from './SimCockpitContext'
import { formatLocalDateTime } from './time'
import { cn } from '@/lib/utils'

/** Align with sim HEARTBEAT_SECONDS≈60 and API STALE_AFTER≈8min. */
const OK_SEC = 90
const WARN_SEC = 8 * 60

type Health = 'ok' | 'warn' | 'fail' | 'idle' | 'na'

function parseTs(value?: string | null): number | null {
  if (!value) return null
  const ms = Date.parse(value)
  return Number.isNaN(ms) ? null : ms
}

function ageSeconds(asOf: string | null | undefined, nowMs: number): number | null {
  const ms = parseTs(asOf)
  if (ms == null) return null
  return Math.max(0, (nowMs - ms) / 1000)
}

function formatAge(sec: number | null): string {
  if (sec == null) return '—'
  if (sec < 60) return `${Math.floor(sec)} 秒前`
  if (sec < 3600) {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${m} 分 ${s} 秒前`
  }
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return `${h} 小时 ${m} 分前`
}

function healthFromAge(
  sec: number | null,
  opts?: {
    okSec?: number
    warnSec?: number
    sessionOpen?: boolean
  },
): Health {
  const okSec = opts?.okSec ?? OK_SEC
  const warnSec = opts?.warnSec ?? WARN_SEC
  const sessionOpen = opts?.sessionOpen
  if (sec == null) return 'idle'
  // Outside session, quote/kline freeze is expected — soften to warn only when very old.
  if (sessionOpen === false) {
    if (sec <= warnSec) return 'ok'
    if (sec <= warnSec * 3) return 'warn'
    return 'fail'
  }
  if (sec <= okSec) return 'ok'
  if (sec <= warnSec) return 'warn'
  return 'fail'
}

function healthLabel(h: Health): string {
  switch (h) {
    case 'ok':
      return '正常'
    case 'warn':
      return '偏慢'
    case 'fail':
      return '中断'
    case 'na':
      return '不适用'
    default:
      return '未知'
  }
}

function healthColor(h: Health): string {
  switch (h) {
    case 'ok':
      return 'success'
    case 'warn':
      return 'warning'
    case 'fail':
      return 'error'
    default:
      return 'default'
  }
}

function Pulse({ health }: { health: Health }) {
  const tone =
    health === 'ok'
      ? 'bg-good shadow-[0_0_0_0_rgba(48,209,88,0.55)]'
      : health === 'warn'
        ? 'bg-amber-400 shadow-[0_0_0_0_rgba(251,191,36,0.45)]'
        : health === 'fail'
          ? 'bg-bad'
          : 'bg-faint'
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {health === 'ok' || health === 'warn' ? (
        <span
          className={cn(
            'absolute inline-flex h-full w-full animate-ping rounded-full opacity-60',
            health === 'ok' ? 'bg-good' : 'bg-amber-400',
          )}
        />
      ) : null}
      <span className={cn('relative inline-flex h-2.5 w-2.5 rounded-full', tone)} />
    </span>
  )
}

function Cell({
  title,
  tip,
  asOf,
  ageSec,
  health,
  detail,
}: {
  title: string
  tip: string
  asOf?: string | null
  ageSec: number | null
  health: Health
  detail?: string
}) {
  return (
    <div className="rounded-lg border border-line/70 bg-surface/40 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <Tooltip title={tip}>
          <p className="cursor-help text-[11px] text-faint underline decoration-dotted">
            {title}
          </p>
        </Tooltip>
        <div className="flex items-center gap-1.5">
          <Pulse health={health} />
          <Tag className="m-0" color={healthColor(health)}>
            {healthLabel(health)}
          </Tag>
        </div>
      </div>
      <p className="mt-1.5 text-sm font-semibold tabular-nums text-ink">{formatAge(ageSec)}</p>
      <p className="mt-0.5 truncate text-[11px] tabular-nums text-muted">
        {asOf ? formatLocalDateTime(asOf) : '尚无时间戳'}
      </p>
      {detail ? <p className="mt-1 truncate text-[11px] text-faint">{detail}</p> : null}
    </div>
  )
}

function worstHealth(items: Health[]): Health {
  if (items.includes('fail')) return 'fail'
  if (items.includes('warn')) return 'warn'
  if (items.includes('ok')) return 'ok'
  return 'idle'
}

export function HeartbeatBoard() {
  const { summary, bars, decisions, loading } = useSimCockpit()
  const [nowMs, setNowMs] = useState(() => Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const sessionOpen = summary?.market_session?.open
  const payload = summary?.payload || {}

  const stateAsOf = summary?.updated_at || null
  const quoteAsOf =
    (typeof payload.quote_as_of === 'string' ? payload.quote_as_of : null) ||
    summary?.last_price_as_of ||
    null
  const decisionAsOf = summary?.last_decision_at || decisions[0]?.created_at || null
  const accountAsOf = summary?.account?.as_of || summary?.account?.created_at || null
  const positionAsOf = summary?.position?.as_of || null
  const klinesAsOf = bars?.updated_at || null

  const stateAge = ageSeconds(stateAsOf, nowMs)
  const quoteAge = ageSeconds(quoteAsOf, nowMs)
  const decisionAge = ageSeconds(decisionAsOf, nowMs)
  const accountAge = ageSeconds(accountAsOf, nowMs)
  const positionAge = ageSeconds(positionAsOf, nowMs)
  const klinesAge = ageSeconds(klinesAsOf, nowMs)

  const processHealth: Health = summary?.process_running
    ? 'ok'
    : summary
      ? 'fail'
      : 'idle'
  const stateHealth = summary?.process_running
    ? healthFromAge(stateAge, { okSec: OK_SEC, warnSec: WARN_SEC })
    : processHealth === 'fail'
      ? 'fail'
      : healthFromAge(stateAge)
  // Decisions only expected on 5m closes while session open.
  const decisionHealth = healthFromAge(decisionAge, {
    okSec: 6 * 60,
    warnSec: 12 * 60,
    sessionOpen,
  })
  const quoteHealth = healthFromAge(quoteAge, { sessionOpen })
  const klinesHealth = healthFromAge(klinesAge, {
    okSec: 30,
    warnSec: WARN_SEC,
    sessionOpen,
  })
  const accountHealth = healthFromAge(accountAge, { okSec: OK_SEC, warnSec: WARN_SEC })
  const positionHealth = healthFromAge(positionAge, { okSec: OK_SEC, warnSec: WARN_SEC })

  const overall = useMemo(
    () =>
      worstHealth([
        processHealth,
        stateHealth,
        quoteHealth,
        klinesHealth,
        accountHealth,
        positionHealth,
        // decision lag alone shouldn't paint overall red outside session
        sessionOpen ? decisionHealth : decisionHealth === 'fail' ? 'warn' : decisionHealth,
      ]),
    [
      processHealth,
      stateHealth,
      quoteHealth,
      klinesHealth,
      accountHealth,
      positionHealth,
      decisionHealth,
      sessionOpen,
    ],
  )

  const pending = payload.pending_desired
  const target = payload.current_target
  const net = payload.confirmed_net

  return (
    <section className="rounded-xl border border-line bg-panel/90">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70 px-3.5 py-2">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold tracking-wide text-ink">心跳检测</h2>
          <Pulse health={overall} />
          <Tag className="m-0" color={healthColor(overall)}>
            总览 {healthLabel(overall)}
          </Tag>
          {loading ? <span className="text-[11px] text-faint">刷新中…</span> : null}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
          <span>
            会话{' '}
            <span className="text-ink">
              {summary?.market_session?.label || (sessionOpen ? '交易时段' : '非交易时段')}
            </span>
          </span>
          <span>
            运行时{' '}
            <span className="tabular-nums text-ink">{summary?.runtime_state || '—'}</span>
          </span>
          <span>
            PID{' '}
            <span className="tabular-nums text-ink">
              {summary?.process_running ? summary.pid ?? '—' : '—'}
            </span>
          </span>
          <Tooltip title="策略心跳约 60s 写库；座舱约 5s 拉一次；状态超过约 8 分钟视为滞后">
            <span className="cursor-help underline decoration-dotted">阈值说明</span>
          </Tooltip>
        </div>
      </div>

      <div className="grid gap-2 p-3.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <Cell
          title="模拟进程"
          tip="操作系统里 falcon_au_sim 是否仍在运行"
          asOf={stateAsOf}
          ageSec={summary?.process_running ? stateAge : null}
          health={processHealth}
          detail={
            summary?.process_running
              ? `在线 · ${summary.symbol || '—'}`
              : '离线 — 可点上方「启动」'
          }
        />
        <Cell
          title="策略心跳"
          tip="strategy_state.updated_at；心跳/收盘决策时刷新"
          asOf={stateAsOf}
          ageSec={stateAge}
          health={stateHealth}
          detail={`目标 ${String(target ?? '—')} · 净仓 ${String(net ?? '—')}${
            pending != null && pending !== '' ? ` · 待确认 ${String(pending)}` : ''
          }`}
        />
        <Cell
          title="行情报价"
          tip="payload.quote_as_of / last_price_as_of；休市时可能停更"
          asOf={quoteAsOf}
          ageSec={quoteAge}
          health={quoteHealth}
          detail={
            summary?.last_price != null
              ? `最新价 ${Number(summary.last_price).toFixed(2)} · ${summary.last_price_source || ''}`
              : summary?.last_price_source || undefined
          }
        />
        <Cell
          title="K 线快照"
          tip="天勤模拟写入的 *.klines.json；含进行中 K 线与最新价"
          asOf={klinesAsOf}
          ageSec={klinesAge}
          health={klinesHealth}
          detail={
            bars?.bars?.length
              ? `${bars.bars.length} 根 · ${bars.trade_symbol || bars.signal_symbol || ''}`
              : '暂无快照'
          }
        />
        <Cell
          title="最近决策"
          tip="思考链路最新一条；交易时段约每 5 分钟一条，休市无新 K 线属正常"
          asOf={decisionAsOf}
          ageSec={decisionAge}
          health={decisionHealth}
          detail={
            decisions[0]
              ? `${decisions[0].applied_action} ${decisions[0].target_before}→${decisions[0].target_after}`
              : '尚无决策'
          }
        />
        <Cell
          title="账户快照"
          tip="account_snapshot_event；启动与心跳时写入"
          asOf={accountAsOf}
          ageSec={accountAge}
          health={accountHealth}
          detail={
            summary?.account
              ? `权益 ${Number(summary.account.equity).toLocaleString('zh-CN', { maximumFractionDigits: 0 })} · 风险度 ${(
                  Number(summary.account.margin_ratio || 0) * 100
                ).toFixed(1)}%`
              : undefined
          }
        />
        <Cell
          title="持仓快照"
          tip="position_snapshot_event；成交/心跳时写入"
          asOf={positionAsOf}
          ageSec={positionAge}
          health={positionHealth}
          detail={
            summary?.position
              ? `${summary.position.symbol || ''} net=${summary.position.net_position} · ${summary.position.source || ''}`
              : undefined
          }
        />
        <div className="rounded-lg border border-line/70 bg-surface/40 px-3 py-2.5">
          <p className="text-[11px] text-faint">判定规则</p>
          <ul className="mt-1.5 space-y-1 text-[11px] leading-relaxed text-muted">
            <li>
              <span className="text-good">正常</span>：心跳 / 报价 ≤ {OK_SEC}s（进程在线）
            </li>
            <li>
              <span className="text-amber-300">偏慢</span>：超过 {OK_SEC}s，未满{' '}
              {Math.round(WARN_SEC / 60)} 分钟
            </li>
            <li>
              <span className="text-bad">中断</span>：进程离线，或状态超过约{' '}
              {Math.round(WARN_SEC / 60)} 分钟未刷新
            </li>
            <li>休市时报价/K 线停更会降级判定，避免误报红灯</li>
          </ul>
        </div>
      </div>
    </section>
  )
}
