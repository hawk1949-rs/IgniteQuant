const API_BASE = ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
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
  for (;;) {
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
