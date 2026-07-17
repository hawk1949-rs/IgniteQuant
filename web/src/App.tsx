import { useCallback, useEffect, useMemo, useState } from 'react'
import { BlurFade } from '@/components/ui/blur-fade'
import { BorderBeam } from '@/components/ui/border-beam'
import { MagicCard } from '@/components/ui/magic-card'
import { NumberTicker } from '@/components/ui/number-ticker'
import {
  deleteRun,
  fetchCatalog,
  fetchRuns,
  patchNotes,
  runBacktest,
  type RunRecord,
  type Strategy,
  type SymbolItem,
} from '@/lib/api'
import { cn } from '@/lib/utils'

function pct(v: number | string | null | undefined, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

function num(v: number | string | null | undefined, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function gradeTone(grade?: string) {
  if (grade === 'A' || grade === 'B') return 'text-good'
  if (grade === 'D' || grade === 'E') return 'text-bad'
  return 'text-blue'
}

export default function App() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [symbols, setSymbols] = useState<SymbolItem[]>([])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [strategyId, setStrategyId] = useState('falcon_v2')
  const [symbolIds, setSymbolIds] = useState<string[]>(['au'])
  const [start, setStart] = useState('2025-01-01')
  const [end, setEnd] = useState('2025-02-28')
  const [balance, setBalance] = useState(1_000_000)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [notesDraft, setNotesDraft] = useState('')
  const [apiOk, setApiOk] = useState<boolean | null>(null)

  const selected = useMemo(
    () => runs.find((r) => r.run_id === selectedId) || null,
    [runs, selectedId],
  )

  const reload = useCallback(async () => {
    const [catalog, list] = await Promise.all([fetchCatalog(), fetchRuns()])
    setStrategies(catalog.strategies)
    setSymbols(catalog.symbols)
    setRuns(list)
    setApiOk(true)
    if (!selectedId && list[0]) {
      setSelectedId(list[0].run_id)
      setNotesDraft(list[0].notes || '')
    }
  }, [selectedId])

  useEffect(() => {
    reload().catch((e: Error) => {
      setApiOk(false)
      setError(e.message || '无法连接 API（请先启动 uvicorn :8787）')
    })
  }, [reload])

  useEffect(() => {
    if (selected) setNotesDraft(selected.notes || '')
  }, [selected])

  const toggleSymbol = (id: string) => {
    setSymbolIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  const onRun = async () => {
    setBusy(true)
    setError(null)
    try {
      const out = await runBacktest({
        strategy_id: strategyId,
        symbol_ids: symbolIds,
        start,
        end,
        init_balance: balance,
      })
      await reload()
      if (out.runs[0]) setSelectedId(out.runs[0].run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const onSaveNotes = async () => {
    if (!selected) return
    await patchNotes(selected.run_id, notesDraft)
    await reload()
  }

  const onDelete = async () => {
    if (!selected) return
    if (!window.confirm(`确认删除回测 ${selected.run_id}？`)) return
    await deleteRun(selected.run_id)
    setSelectedId(null)
    await reload()
  }

  const bestScore = runs.reduce((m, r) => Math.max(m, Number(r.scorecard?.total || 0)), 0)
  const avgRor =
    runs.length === 0
      ? 0
      : runs.reduce((s, r) => s + Number(r.metrics?.ror || 0), 0) / runs.length

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 pb-16 pt-10 sm:px-8">
      <BlurFade delay={0.05}>
        <header className="relative mb-10 overflow-hidden rounded-[28px] border border-white/70 bg-white/55 px-7 py-9 shadow-[0_20px_50px_rgba(29,29,31,0.06)] backdrop-blur-xl">
          <BorderBeam size={80} duration={9} colorFrom="#0071e3" colorTo="#64d2ff" />
          <p className="font-display text-3xl tracking-tight text-ink sm:text-4xl">
            IgniteQuant
          </p>
          <h1 className="mt-2 max-w-xl text-lg font-medium text-muted sm:text-xl">
            家庭量化作坊 · 策略回测与对照
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted">
            选策略、跑标的、看打分。结果落在本地 JSON，方便你和家人一起复盘。
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3 text-xs text-muted">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1',
                apiOk ? 'bg-blue-soft text-blue' : 'bg-surface text-muted',
              )}
            >
              <span
                className={cn(
                  'size-1.5 rounded-full',
                  apiOk ? 'bg-blue' : apiOk === false ? 'bg-bad' : 'bg-line',
                )}
              />
              API {apiOk ? '已连接' : apiOk === false ? '未连接' : '检测中'}
            </span>
            <span>前端 :5173 · 后端 :8787</span>
          </div>
        </header>
      </BlurFade>

      <div className="mb-8 grid gap-4 sm:grid-cols-3">
        {[
          { label: '历史回测', value: runs.length, digits: 0 },
          { label: '最高总分', value: bestScore, digits: 1 },
          { label: '平均收益 %', value: avgRor * 100, digits: 2 },
        ].map((stat, i) => (
          <BlurFade key={stat.label} delay={0.1 + i * 0.05}>
            <div className="rounded-2xl border border-line/70 bg-white/70 px-5 py-4 backdrop-blur">
              <p className="text-xs uppercase tracking-[0.14em] text-muted">{stat.label}</p>
              <p className="mt-2 font-display text-3xl text-ink">
                <NumberTicker value={stat.value} decimalPlaces={stat.digits} />
              </p>
            </div>
          </BlurFade>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <BlurFade delay={0.2}>
          <MagicCard className="h-full">
            <div className="space-y-5 p-5">
              <div>
                <label className="text-xs font-medium text-muted">策略</label>
                <select
                  className="mt-1.5 w-full rounded-xl border border-line bg-white px-3 py-2.5 outline-none focus:border-blue"
                  value={strategyId}
                  onChange={(e) => setStrategyId(e.target.value)}
                >
                  {strategies.map((s) => (
                    <option key={s.id} value={s.id} disabled={!s.ready}>
                      {s.name}
                      {!s.ready ? '（占位）' : ''}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs leading-relaxed text-muted">
                  {strategies.find((s) => s.id === strategyId)?.description}
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-muted">标的</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {symbols.map((s) => {
                    const on = symbolIds.includes(s.id)
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => toggleSymbol(s.id)}
                        className={cn(
                          'rounded-xl border px-3 py-1.5 text-sm transition',
                          on
                            ? 'border-blue bg-blue-soft text-blue'
                            : 'border-line bg-white text-muted hover:border-blue/40',
                        )}
                      >
                        {s.name}
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-muted">开始</label>
                  <input
                    type="date"
                    className="mt-1.5 w-full rounded-xl border border-line bg-white px-3 py-2 outline-none focus:border-blue"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted">结束</label>
                  <input
                    type="date"
                    className="mt-1.5 w-full rounded-xl border border-line bg-white px-3 py-2 outline-none focus:border-blue"
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted">初始资金</label>
                <input
                  type="number"
                  step={10000}
                  className="mt-1.5 w-full rounded-xl border border-line bg-white px-3 py-2 outline-none focus:border-blue"
                  value={balance}
                  onChange={(e) => setBalance(Number(e.target.value) || 0)}
                />
              </div>

              <button
                type="button"
                disabled={busy || symbolIds.length === 0 || !apiOk}
                onClick={onRun}
                className="relative w-full overflow-hidden rounded-xl bg-blue px-4 py-3 text-sm font-semibold text-white transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? '回测进行中…' : '开始回测'}
              </button>

              {error && (
                <p className="rounded-xl bg-[#fff2f2] px-3 py-2 text-xs leading-relaxed text-bad">
                  {error}
                </p>
              )}
            </div>
          </MagicCard>
        </BlurFade>

        <div className="space-y-6">
          <BlurFade delay={0.25}>
            <section className="rounded-2xl border border-line/70 bg-white/70 p-5 backdrop-blur">
              <div className="mb-4 flex items-end justify-between gap-3">
                <div>
                  <h2 className="font-display text-xl text-ink">回测档案</h2>
                  <p className="mt-1 text-sm text-muted">点击一条查看打分与指标</p>
                </div>
                <button
                  type="button"
                  onClick={() => reload().catch((e: Error) => setError(e.message))}
                  className="text-sm text-blue hover:underline"
                >
                  刷新
                </button>
              </div>

              {runs.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted">还没有记录，先跑一次回测。</p>
              ) : (
                <ul className="max-h-[280px] space-y-2 overflow-auto pr-1">
                  {runs.map((r) => {
                    const active = r.run_id === selectedId
                    return (
                      <li key={r.run_id}>
                        <button
                          type="button"
                          onClick={() => setSelectedId(r.run_id)}
                          className={cn(
                            'flex w-full items-center justify-between gap-3 rounded-xl border px-3.5 py-3 text-left transition',
                            active
                              ? 'border-blue bg-blue-soft'
                              : 'border-transparent bg-surface/80 hover:border-line',
                          )}
                        >
                          <div>
                            <p className="text-sm font-medium text-ink">
                              {r.strategy_name || '—'} · {r.symbol_name || r.symbol_id}
                            </p>
                            <p className="mt-0.5 text-xs text-muted">
                              {r.saved_at || r.run_id}
                            </p>
                          </div>
                          <div className="text-right">
                            <p className={cn('font-display text-lg', gradeTone(r.scorecard?.grade))}>
                              {r.scorecard?.total?.toFixed?.(1) ?? '—'}
                            </p>
                            <p className="text-xs text-muted">
                              {r.scorecard?.grade} · {pct(r.metrics?.ror)}
                            </p>
                          </div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          </BlurFade>

          <BlurFade delay={0.3}>
            <section className="relative overflow-hidden rounded-2xl border border-line/70 bg-white/80 p-5 backdrop-blur">
              {!selected ? (
                <p className="py-12 text-center text-sm text-muted">选择一条回测查看详情</p>
              ) : (
                <>
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.14em] text-muted">综合评分</p>
                      <p className={cn('font-display text-5xl', gradeTone(selected.scorecard?.grade))}>
                        <NumberTicker
                          key={selected.run_id}
                          value={Number(selected.scorecard?.total || 0)}
                          decimalPlaces={1}
                        />
                      </p>
                      <p className="mt-1 text-sm text-muted">
                        {selected.scorecard?.grade} · {selected.scorecard?.label}
                      </p>
                    </div>
                    <div className="text-right text-sm text-muted">
                      <p>
                        {selected.strategy_name} / {selected.symbol_name}
                      </p>
                      <p className="mt-1 font-mono text-xs">{selected.run_id}</p>
                    </div>
                  </div>

                  <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {[
                      { k: '收益率', v: pct(selected.metrics?.ror) },
                      { k: '最大回撤', v: pct(selected.metrics?.max_drawdown) },
                      { k: '夏普', v: num(selected.metrics?.sharpe) },
                      { k: '成交笔数', v: String(selected.metrics?.trade_count ?? '—') },
                      { k: '胜率', v: pct(selected.metrics?.winning_rate) },
                      { k: '盈亏比', v: num(selected.metrics?.profit_loss_ratio) },
                      { k: '年化', v: pct(selected.metrics?.annual_yield) },
                      {
                        k: '期末权益',
                        v: selected.metrics?.final_balance
                          ? Number(selected.metrics.final_balance).toLocaleString('zh-CN')
                          : '—',
                      },
                    ].map((m) => (
                      <div key={m.k} className="rounded-xl bg-surface/90 px-3 py-2.5">
                        <p className="text-[11px] text-muted">{m.k}</p>
                        <p className="mt-1 text-sm font-semibold tabular-nums text-ink">{m.v}</p>
                      </div>
                    ))}
                  </div>

                  {selected.scorecard?.tips && selected.scorecard.tips.length > 0 && (
                    <div className="mt-5">
                      <p className="text-xs font-medium text-muted">复盘建议</p>
                      <ul className="mt-2 space-y-1.5">
                        {selected.scorecard.tips.map((t) => (
                          <li
                            key={t}
                            className="rounded-lg bg-blue-soft/60 px-3 py-2 text-xs leading-relaxed text-ink"
                          >
                            {t}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="mt-5">
                    <label className="text-xs font-medium text-muted">笔记</label>
                    <textarea
                      className="mt-1.5 min-h-[88px] w-full rounded-xl border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue"
                      value={notesDraft}
                      onChange={(e) => setNotesDraft(e.target.value)}
                      placeholder="写下这次回测的观察…"
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => onSaveNotes().catch((e: Error) => setError(e.message))}
                        className="rounded-xl bg-ink px-4 py-2 text-sm font-medium text-white"
                      >
                        保存笔记
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete().catch((e: Error) => setError(e.message))}
                        className="rounded-xl border border-line px-4 py-2 text-sm text-bad"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                </>
              )}
            </section>
          </BlurFade>
        </div>
      </div>
    </div>
  )
}
