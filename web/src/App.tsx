import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  deleteRun,
  fetchCatalog,
  fetchRuns,
  patchNotes,
  runBacktest,
  type JobRecord,
  type RunRecord,
  type Strategy,
  type SymbolItem,
} from '@/lib/api'
import { cn } from '@/lib/utils'

function pct(v: number | string | null | undefined, digits = 2) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

function num(v: number | string | null | undefined, digits = 2) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function gradeTone(grade?: string) {
  if (grade === 'A' || grade === 'B') return 'text-good'
  if (grade === 'D' || grade === 'E') return 'text-bad'
  return 'text-blue'
}

function scoreOf(r: RunRecord) {
  return Number(r.scorecard?.score ?? r.scorecard?.total ?? 0)
}

function tipsOf(r: RunRecord) {
  return r.scorecard?.review_tips || r.scorecard?.tips || []
}

export default function App() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [symbols, setSymbols] = useState<SymbolItem[]>([])
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [strategyId, setStrategyId] = useState('falcon_v2')
  const [symbolIds, setSymbolIds] = useState<string[]>(['au'])
  const [engine, setEngine] = useState<'local' | 'tq'>('local')
  const [engines, setEngines] = useState<{ id: string; name: string }[]>([])
  const [start, setStart] = useState('2025-01-01')
  const [end, setEnd] = useState('2025-02-28')
  const [balance, setBalance] = useState(1_000_000)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [progressMsg, setProgressMsg] = useState('')
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
    setEngines(catalog.engines || [
      { id: 'local', name: '本地缓存回放' },
      { id: 'tq', name: '天勤在线回测' },
    ])
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

  const onProgress = (job: JobRecord) => {
    const pctVal = Math.max(0, Math.min(100, Math.round(Number(job.progress || 0) * 100)))
    setProgress(pctVal)
    setProgressMsg(
      job.progress_msg ||
        (job.status === 'QUEUED'
          ? '排队中…'
          : job.status === 'RUNNING'
            ? '回测运行中…'
            : job.status),
    )
  }

  const onRun = async () => {
    setBusy(true)
    setError(null)
    setProgress(2)
    setProgressMsg('提交任务…')
    try {
      const out = await runBacktest({
        strategy_id: strategyId,
        symbol_ids: symbolIds,
        start,
        end,
        init_balance: balance,
        engine,
        onProgress,
      })
      setProgress(100)
      setProgressMsg('完成')
      await reload()
      if (out.runs[0]) setSelectedId(out.runs[0].run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setProgressMsg('失败')
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

  const bestScore = runs.reduce((m, r) => Math.max(m, scoreOf(r)), 0)
  const avgRor =
    runs.length === 0
      ? 0
      : runs.reduce((s, r) => s + Number(r.metrics?.ror || 0), 0) / runs.length

  const fieldCls =
    'mt-1.5 w-full rounded-lg border border-line bg-[#0a1018] px-3 py-2.5 text-sm text-ink outline-none focus:border-blue'

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 pb-16 pt-8 sm:px-8">
      <header className="mb-8 border border-line bg-panel/90 px-6 py-7 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-2xl font-semibold tracking-wide text-ink sm:text-3xl">
              IgniteQuant
            </p>
            <h1 className="mt-1 text-base text-muted sm:text-lg">策略回测控制台</h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
              选择策略与标的，提交回测任务。结果保存在本地，可对照评分与指标。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 border px-2.5 py-1',
                apiOk ? 'border-blue/40 bg-blue-soft text-blue' : 'border-line bg-surface text-muted',
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
        </div>
      </header>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        {[
          { label: '历史回测', value: String(runs.length) },
          { label: '最高总分', value: bestScore.toFixed(1) },
          { label: '平均收益 %', value: (avgRor * 100).toFixed(2) },
        ].map((stat) => (
          <div key={stat.label} className="border border-line bg-panel/80 px-5 py-4">
            <p className="text-xs tracking-wide text-muted">{stat.label}</p>
            <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">{stat.value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <aside className="border border-line bg-panel/90">
          <div className="space-y-5 p-5">
            <div>
              <label className="text-xs font-medium text-muted">策略</label>
              <select
                className={fieldCls}
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
                        'border px-3 py-1.5 text-sm',
                        on
                          ? 'border-blue bg-blue-soft text-blue'
                          : 'border-line bg-surface text-muted hover:border-blue/50',
                      )}
                    >
                      {s.name}
                    </button>
                  )
                })}
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-muted">回测引擎</label>
              <select
                className={fieldCls}
                value={engine}
                onChange={(e) => setEngine(e.target.value as 'local' | 'tq')}
              >
                {engines.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </select>
              <p className="mt-2 text-xs leading-relaxed text-muted">
                {engine === 'local'
                  ? '默认：读 data/market_cache，含换月与 LocalSim；缺缓存可自动下载。'
                  : '天勤 TqBacktest 在线时光机，更慢，适合最终对照。'}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted">开始</label>
                <input
                  type="date"
                  className={fieldCls}
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted">结束</label>
                <input
                  type="date"
                  className={fieldCls}
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
                className={fieldCls}
                value={balance}
                onChange={(e) => setBalance(Number(e.target.value) || 0)}
              />
            </div>

            <button
              type="button"
              disabled={busy || symbolIds.length === 0 || !apiOk}
              onClick={onRun}
              className="w-full border border-blue/50 bg-blue/15 px-4 py-3 text-sm font-semibold text-blue enabled:hover:bg-blue/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? '回测进行中…' : '开始回测'}
            </button>

            {(busy || progress > 0) && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-muted">
                  <span>{progressMsg || (busy ? '处理中…' : '就绪')}</span>
                  <span className="tabular-nums text-blue">{progress}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden border border-line bg-[#0a1018]">
                  <div
                    className="h-full bg-gradient-to-r from-[#1a6cff] to-[#3dd6ff] transition-[width] duration-300 ease-out"
                    style={{ width: `${Math.max(busy ? 2 : 0, progress)}%` }}
                  />
                </div>
              </div>
            )}

            {error && (
              <p className="border border-bad/40 bg-bad/10 px-3 py-2 text-xs leading-relaxed text-bad">
                {error}
              </p>
            )}
          </div>
        </aside>

        <div className="space-y-6">
          <section className="border border-line bg-panel/90 p-5">
            <div className="mb-4 flex items-end justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold text-ink">回测档案</h2>
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
                          'flex w-full items-center justify-between gap-3 border px-3.5 py-3 text-left',
                          active
                            ? 'border-blue/50 bg-blue-soft'
                            : 'border-line/80 bg-surface/60 hover:border-blue/30',
                        )}
                      >
                        <div>
                          <p className="text-sm font-medium text-ink">
                            {r.strategy_name || '—'} · {r.symbol_name || r.symbol_id}
                          </p>
                          <p className="mt-0.5 text-xs text-muted">{r.saved_at || r.run_id}</p>
                        </div>
                        <div className="text-right">
                          <p className={cn('text-lg font-semibold tabular-nums', gradeTone(r.scorecard?.grade))}>
                            {scoreOf(r) ? scoreOf(r).toFixed(1) : '—'}
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

          <section className="border border-line bg-panel/90 p-5">
            {!selected ? (
              <p className="py-12 text-center text-sm text-muted">选择一条回测查看详情</p>
            ) : (
              <>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs tracking-wide text-muted">综合评分</p>
                    <p
                      className={cn(
                        'mt-1 text-5xl font-semibold tabular-nums',
                        gradeTone(selected.scorecard?.grade),
                      )}
                    >
                      {scoreOf(selected).toFixed(1)}
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
                    <div key={m.k} className="border border-line bg-surface/80 px-3 py-2.5">
                      <p className="text-[11px] text-muted">{m.k}</p>
                      <p className="mt-1 text-sm font-semibold tabular-nums text-ink">{m.v}</p>
                    </div>
                  ))}
                </div>

                {tipsOf(selected).length > 0 && (
                  <div className="mt-5">
                    <p className="text-xs font-medium text-muted">复盘建议</p>
                    <ul className="mt-2 space-y-1.5">
                      {tipsOf(selected).map((t) => (
                        <li
                          key={t}
                          className="border border-line bg-blue-soft/40 px-3 py-2 text-xs leading-relaxed text-ink"
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
                    className={cn(fieldCls, 'min-h-[88px]')}
                    value={notesDraft}
                    onChange={(e) => setNotesDraft(e.target.value)}
                    placeholder="写下这次回测的观察…"
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => onSaveNotes().catch((e: Error) => setError(e.message))}
                      className="border border-blue/40 bg-blue/15 px-4 py-2 text-sm font-medium text-blue"
                    >
                      保存笔记
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete().catch((e: Error) => setError(e.message))}
                      className="border border-bad/40 px-4 py-2 text-sm text-bad"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
