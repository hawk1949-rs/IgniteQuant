/** Strategy-aware chart / pipeline presentation helpers for sim cockpit. */

import type { SimChartOverlays, SimOverlaySpec } from '@/lib/api'

export const DEFAULT_OVERLAY_SPECS: SimOverlaySpec[] = [
  { key: 'ma7', label: 'MA7', color: '#64d2ff', pane: 'main' },
  { key: 'ma14', label: 'MA14', color: '#ffd60a', pane: 'main' },
  { key: 'ma52', label: 'MA52', color: '#bf5af2', pane: 'main' },
  { key: 'signal', label: '信号', color: '#30d158', pane: 'signal' },
]

export function overlayKeys(
  specs?: SimOverlaySpec[] | null,
  overlays?: SimChartOverlays | null,
): string[] {
  const keys = new Set<string>()
  for (const spec of specs || []) keys.add(spec.key)
  if (overlays) {
    for (const key of Object.keys(overlays)) keys.add(key)
  }
  if (!keys.size) {
    for (const spec of DEFAULT_OVERLAY_SPECS) keys.add(spec.key)
  }
  return [...keys]
}

export function mergeOverlayMaps(
  prev: SimChartOverlays | null | undefined,
  next: SimChartOverlays | null | undefined,
  keys: string[],
): SimChartOverlays {
  const out: SimChartOverlays = {}
  for (const key of keys) {
    const map = new Map((next?.[key] || []).map((p) => [p.time, p]))
    for (const p of prev?.[key] || []) {
      if (!map.has(p.time)) map.set(p.time, p)
    }
    out[key] = [...map.values()].sort((a, b) => a.time - b.time)
  }
  return out
}

export function resolveOverlaySpecs(
  specs?: SimOverlaySpec[] | null,
  presentation?: Record<string, unknown> | null,
): SimOverlaySpec[] {
  if (specs?.length) return specs
  const fromPresentation = presentation?.overlay_specs
  if (Array.isArray(fromPresentation) && fromPresentation.length) {
    return fromPresentation as SimOverlaySpec[]
  }
  return DEFAULT_OVERLAY_SPECS
}

export function formatScorePartsLabel(
  parts: number[] | null | undefined,
  labels?: string[] | null,
): string {
  if (!parts?.length) return '—'
  return parts
    .map((value, index) => {
      const label = labels?.[index] ?? `p${index}`
      return `${label}=${value}`
    })
    .join(' · ')
}
