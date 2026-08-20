import type { SimCatalog } from '@/lib/api'

export const READY_SIM_STRATEGIES = ['falcon_v2', 'gma_v1', 'gma_v2'] as const

export function instanceIdFor(
  catalog: SimCatalog | null | undefined,
  strategyId: string,
  symbolId: string,
): string {
  const hit = catalog?.launchers?.find(
    (l) => l.strategy_id === strategyId && l.symbol_id === symbolId,
  )
  if (hit) return hit.instance_id
  if (strategyId === 'falcon_v2' && symbolId === 'au') return 'falcon_au_sim'
  if (strategyId === 'gma_v1' && symbolId === 'au') return 'gma_au_sim'
  return `${strategyId}_${symbolId}_sim`
}

/** Current-session rows only. Never mix sibling symbols from the strategy book. */
export function focusedOpenPositions<T>(
  summary: { open_positions?: T[] | null } | null | undefined,
): T[] {
  return summary?.open_positions ?? []
}

export function readJsonLs<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

export function writeJsonLs(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* ignore */
  }
}

export function symbolIdsKey(strategyId: string) {
  return `ignitequant.sim.symbolIds.${strategyId}`
}
