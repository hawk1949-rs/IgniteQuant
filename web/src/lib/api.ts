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

export type Scorecard = {
  total: number
  grade: string
  label: string
  tips?: string[]
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
}

export function fetchCatalog() {
  return request<{ strategies: Strategy[]; symbols: SymbolItem[] }>('/api/catalog')
}

export function fetchRuns() {
  return request<RunRecord[]>('/api/runs')
}

export function runBacktest(body: {
  strategy_id: string
  symbol_ids: string[]
  start: string
  end: string
  init_balance: number
}) {
  return request<{ count: number; runs: RunRecord[] }>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
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
