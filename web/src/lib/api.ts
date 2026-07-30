import { clearSession, getStoredToken } from './auth'

const API_BASE = ''
const REQUEST_TIMEOUT_MS = 30_000
const BACKTEST_POLL_MAX_MS = 30 * 60_000

function notifyUnauthorized() {
  clearSession()
  window.dispatchEvent(new CustomEvent('iq:unauthorized'))
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController()
  const timer = window.setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS)
  try {
    const token = getStoredToken()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string> | undefined),
    }
    if (token) headers.Authorization = `Bearer ${token}`

    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal: ctrl.signal,
    })
    if (res.status === 401) {
      notifyUnauthorized()
      throw new Error('未登录或会话已过期')
    }
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail = body.detail || JSON.stringify(body)
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
    return res.json() as Promise<T>
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error('请求超时，请检查 API 是否已启动')
    }
    throw err
  } finally {
    window.clearTimeout(timer)
  }
}

export type Strategy = {
  id: string
  name: string
  description: string
  ready: boolean
}

export type SymbolItem = {
  id: string
  name: string
  signal_symbol: string
  exchange: string
}

export type EngineItem = {
  id: string
  name: string
  default?: boolean
}

export type Scorecard = {
  score?: number
  total?: number
  grade: string
  label: string
  tips?: string[]
  review_tips?: string[]
  parts?: Record<string, number>
}

export type RunRecord = {
  run_id: string
  saved_at?: string
  strategy_name?: string
  symbol_id?: string
  symbol_name?: string
  notes?: string
  metrics?: Record<string, number | string | null>
  scorecard?: Scorecard
  start?: string
  end?: string
  init_balance?: number
  equity_curve?: { t: string; equity: number }[]
  attribution?: Record<string, unknown>
  stress?: Record<string, unknown>
  reproducibility?: Record<string, unknown>
  config_hash?: string
}

export type JobRecord = {
  job_id: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELED'
  progress: number
  progress_msg?: string
  result_run_ids?: string[]
  error_summary?: string
  runs?: RunRecord[]
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

export function fetchCatalog() {
  return request<{
    strategies: Strategy[]
    symbols: SymbolItem[]
    engines?: EngineItem[]
    market_cache?: Array<Record<string, unknown>>
  }>('/api/catalog')
}

export function fetchRuns() {
  return request<RunRecord[]>('/api/runs')
}

export function fetchJob(jobId: string) {
  return request<JobRecord>(`/api/jobs/${jobId}`)
}

/** 异步提交并轮询至完成（Phase 5：不阻塞 API 进程内同步等待 HTTP 线程）。 */
export async function runBacktest(body: {
  strategy_id: string
  symbol_ids: string[]
  start: string
  end: string
  init_balance: number
  engine?: 'local' | 'tq'
  auto_download?: boolean
  /** 用户点击「开始回测」时应为 true，避免命中历史 SUCCEEDED 任务秒回 done */
  force?: boolean
  onProgress?: (job: JobRecord) => void
}) {
  const { onProgress, ...payload } = body
  const submitted = await request<{
    mode: string
    count: number
    runs: RunRecord[]
    job: JobRecord | null
  }>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

  if (submitted.mode === 'sync' || !submitted.job) {
    return { count: submitted.count, runs: submitted.runs, job: submitted.job }
  }

  let job = submitted.job
  onProgress?.(job)

  // Idempotent hit: previous SUCCEEDED job returned immediately.
  if (job.status === 'SUCCEEDED') {
    job = await fetchJob(job.job_id)
    onProgress?.(job)
    return {
      count: (job.runs || []).length,
      runs: job.runs || [],
      job,
    }
  }

  const started = Date.now()
  for (;;) {
    if (Date.now() - started > BACKTEST_POLL_MAX_MS) {
      throw new Error('回测轮询超时（30 分钟），请稍后在任务列表查看结果')
    }
    await sleep(1500)
    job = await fetchJob(job.job_id)
    onProgress?.(job)
    if (job.status === 'SUCCEEDED') {
      return {
        count: (job.runs || []).length,
        runs: job.runs || [],
        job,
      }
    }
    if (job.status === 'FAILED' || job.status === 'CANCELED') {
      throw new Error(job.error_summary || `回测任务 ${job.status}`)
    }
  }
}

export function patchNotes(runId: string, notes: string) {
  return request<RunRecord>(`/api/runs/${runId}/notes`, {
    method: 'PATCH',
    body: JSON.stringify({ notes }),
  })
}

export function deleteRun(runId: string) {
  return request<{ ok: boolean }>(`/api/runs/${runId}`, { method: 'DELETE' })
}

// ---- Sim Cockpit ----

export type SimFramework = {
  id: string
  name: string
  enabled: boolean
  cli?: string
  note?: string
}

export type SimCatalog = {
  frameworks: SimFramework[]
  strategies: Strategy[]
  symbols: Array<
    SymbolItem & {
      source?: string
      source_note?: string
      overseas_pair?: {
        id: string
        name: string
        display_symbol: string
        yahoo_symbol: string
        note: string
      } | null
    }
  >
  launchers?: Array<{
    instance_id: string
    label: string
    symbol_id: string
    strategy_id: string
    framework: string
  }>
  cli_hint?: string
  runtime_dir?: string
  refresh_hint?: string
  symbol_catalog_note?: string
  data_source?: 'cloud' | 'local' | string
  read_only?: boolean
  read_only_hint?: string | null
}

export type SimSession = {
  instance_id: string
  db_path?: string
  strategy_id?: string
  account_id?: string
  symbol?: string
  runtime_state?: string
  status: 'RUNNING' | 'STALE' | 'IDLE' | string
  updated_at?: string | null
  framework?: string
  last_decision_at?: string | null
  payload?: Record<string, unknown>
  error?: string
}

export type SimSummary = {
  instance_id: string
  framework: string
  framework_label?: string
  strategy_id: string
  account_id: string
  symbol: string
  runtime_state: string
  status: string
  status_label?: string
  label?: string
  updated_at?: string
  payload?: Record<string, unknown>
  account?: {
    equity: number
    available: number
    margin: number
    margin_ratio: number
    realized_pnl_today?: number
    unrealized_pnl?: number
    margin_rate?: number | null
    margin_rate_pct?: number | null
    margin_source?: string
    as_of?: string
    created_at?: string
  } | null
  position?: {
    symbol: string
    net_position: number
    source?: string
    as_of?: string
    average_entry_price?: number | null
    unrealized_pnl?: number
    margin?: number
    long_today?: number
    long_yesterday?: number
    short_today?: number
    short_yesterday?: number
  } | null
  open_positions?: Array<{
    symbol: string
    side: 'LONG' | 'SHORT' | string
    side_label?: string
    lots: number
    net_position: number
    average_entry_price?: number | null
    last_price?: number | null
    unrealized_pnl: number
    margin: number
    margin_rate?: number | null
    margin_rate_pct?: number | null
    margin_source?: string
    source?: string
    as_of?: string
    stop_price?: number | null
    take_price?: number | null
  }>
  position_note?: string | null
  market_session?: {
    open: boolean
    local_time?: string
    label?: string
    note?: string | null
  } | null
  last_decision_at?: string | null
  last_price?: number | null
  last_price_source?: string | null
  last_price_as_of?: string | null
  cli_hint?: string
  process_running?: boolean
  pid?: number | null
  can_start?: boolean
  data_source?: 'cloud' | 'local' | string
  read_only?: boolean
  read_only_hint?: string | null
}

export type SimMetrics = {
  instance_id: string
  equity: number
  init_balance: number
  pnl: number
  pnl_pct: number
  trade_count: number
  fill_count: number
  wins: number
  losses: number
  win_rate: number
  max_drawdown_pct: number
  open_position: number
  equity_curve: { t: string; equity: number }[]
}

export type SimDecision = {
  decision_id: string
  bar_id: string
  symbol: string
  applied_action: string
  target_before: number
  target_after: number
  legacy_signal: number
  created_at: string
  regime?: string
  factor_values?: Record<string, number>
  factor_quality?: string
  reason_codes?: string[]
  score_parts?: number[] | null
  signal?: Record<string, unknown>
  target?: Record<string, unknown>
  risk?: {
    action: string
    requested_position: number
    approved_position: number
    rule_hits: string[]
    created_at?: string
  } | null
}

export type SimIntent = {
  intent_id: string
  decision_id: string
  symbol: string
  current_position: number
  desired_position: number
  urgency: string
  status: string
  reason_codes: string[]
  created_at: string
}

export type SimFill = {
  fill_id: string
  intent_id: string
  symbol: string
  price: number
  qty: number
  fee: number
  side: string
  trade_time: string
  created_at: string
}

export type SimPositionHistoryRow = {
  symbol: string
  side: 'LONG' | 'SHORT' | string
  side_label?: string
  lots: number
  entry_price: number
  exit_price: number
  opened_at?: string | null
  closed_at?: string | null
  realized_pnl: number
  fees: number
}

export type SimChartContext = {
  regime?: string
  short_bias?: string
  close?: number
  ma52?: number | null
  adx?: number | null
  bar_time?: number
  conflict?: boolean
}

export type SimBarsResponse = {
  instance_id?: string
  symbol_id?: string
  name?: string
  signal_symbol: string
  trade_symbol: string
  bars: {
    time: number
    open: number
    high: number
    low: number
    close: number
    volume: number
  }[]
  markers: {
    time: number
    position: string
    color: string
    shape: string
    text: string
    side: string
    price?: number | null
    qty?: number
  }[]
  last_price?: number | null
  last_price_source?: string | null
  last_price_as_of?: string | null
  updated_at?: string | null
  hint?: string | null
  chart_context?: SimChartContext | null
  market_session?: {
    open: boolean
    local_time?: string
    label?: string
    note?: string | null
  } | null
}

export type SimOverseasBars = {
  symbol_id: string
  supported: boolean
  pair?: {
    id: string
    name: string
    display_symbol: string
    yahoo_symbol: string
    note: string
  }
  bars: {
    time: number
    open: number
    high: number
    low: number
    close: number
    volume: number
  }[]
  last_price?: number | null
  last_bar_open?: number | null
  lag_seconds?: number | null
  source?: string | null
  pricing_role?: string | null
  note?: string | null
  hint?: string | null
}

export type SimReplay = {
  instance_id: string
  at: string
  mode: string
  account?: {
    equity: number
    available: number
    margin: number
    margin_ratio: number
    as_of?: string
    created_at?: string
  } | null
  position?: {
    symbol: string
    net_position: number
    as_of?: string
  } | null
  decision?: SimDecision | null
  fills: SimFill[]
  metrics_snapshot: {
    equity: number
    pnl: number
    fill_count: number
  }
}

export function fetchSimCatalog() {
  return request<SimCatalog>('/api/sim/catalog')
}

export function fetchSimSessions() {
  return request<{ sessions: SimSession[]; count: number }>('/api/sim/sessions')
}

export function fetchSimSummary(instanceId: string) {
  return request<SimSummary>(`/api/sim/sessions/${encodeURIComponent(instanceId)}/summary`)
}

export function fetchSimMetrics(instanceId: string) {
  return request<SimMetrics>(`/api/sim/sessions/${encodeURIComponent(instanceId)}/metrics`)
}

export function fetchSimDecisions(
  instanceId: string,
  opts?: { limit?: number; before?: string },
) {
  const q = new URLSearchParams()
  if (opts?.limit) q.set('limit', String(opts.limit))
  if (opts?.before) q.set('before', opts.before)
  const suffix = q.toString() ? `?${q}` : ''
  return request<{ decisions: SimDecision[]; count: number }>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/decisions${suffix}`,
  )
}

export function fetchSimIntents(instanceId: string, limit = 100) {
  return request<{ intents: SimIntent[]; count: number }>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/intents?limit=${limit}`,
  )
}

export function fetchSimFills(instanceId: string, limit = 100) {
  return request<{ fills: SimFill[]; count: number }>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/fills?limit=${limit}`,
  )
}

export function fetchSimPositionHistory(instanceId: string, limit = 100) {
  return request<{ positions: SimPositionHistoryRow[]; count: number }>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/position-history?limit=${limit}`,
  )
}

export function repairSimFills(instanceId: string) {
  return request<{ instance_id: string; repaired: number }>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/repair-fills`,
    { method: 'POST' },
  )
}

export function catchUpSimBars(instanceId: string) {
  return request<{
    instance_id: string
    missed: number
    recorded: number
    skipped_existing: number
    last_bar_id_before?: string | null
    last_bar_id_after?: string | null
    final_target: number
    confirmed_net: number
    message: string
    source?: string
    process_running?: boolean
    hint?: string | null
    bar_ids?: string[]
  }>(`/api/sim/sessions/${encodeURIComponent(instanceId)}/catch-up-bars`, { method: 'POST' })
}

export function fetchSimBars(
  instanceId: string,
  opts?: { symbol?: string; end?: string; limit?: number },
) {
  const q = new URLSearchParams()
  if (opts?.symbol) q.set('symbol', opts.symbol)
  if (opts?.end) q.set('end', opts.end)
  if (opts?.limit) q.set('limit', String(opts.limit))
  const suffix = q.toString() ? `?${q}` : ''
  return request<SimBarsResponse>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/bars${suffix}`,
  )
}

export function fetchSimReplay(instanceId: string, at: string) {
  return request<SimReplay>(
    `/api/sim/sessions/${encodeURIComponent(instanceId)}/replay?at=${encodeURIComponent(at)}`,
  )
}

export function startSimSession(instanceId: string) {
  return request<{
    ok: boolean
    already_running?: boolean
    message: string
    pid?: number
    process_running?: boolean
    label?: string
  }>(`/api/sim/sessions/${encodeURIComponent(instanceId)}/start`, { method: 'POST' })
}

export function fetchSimOverseasBars(symbolId: string, limit = 400) {
  return request<SimOverseasBars>(
    `/api/sim/overseas/bars?symbol_id=${encodeURIComponent(symbolId)}&limit=${limit}`,
  )
}

export function fetchSimMarketBars(symbolId: string, limit = 400) {
  return request<SimBarsResponse & { symbol_id?: string; name?: string }>(
    `/api/sim/market/bars?symbol_id=${encodeURIComponent(symbolId)}&limit=${limit}`,
  )
}
