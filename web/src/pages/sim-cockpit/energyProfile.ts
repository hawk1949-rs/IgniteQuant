/**
 * GMA 能量分布（Volume Profile）— 严格对齐《GMA指标-能量分布详解》
 *
 * 教程要点：
 * - 模式：Visible Bars（界面当前可见 K 线窗口，与周期无关）
 * - VA：通常 70% 成交量价值区 → VAH / VAL
 * - POC：窗口内成交量最高的价格档
 * - 边缘：窗口高低价
 * - 分箱：教学截图 MT4 参数串含 50（Visible Bars … 50 …）
 * - 缺口（峡谷）：相对 POC 成交量显著塌陷的价位
 */

export const GMA_ENERGY_TEACHING = {
  /** 教学截图参数：Visible Bars */
  mode: 'Visible Bars' as const,
  /** 教学截图参数串中的行数≈50 */
  bins: 50,
  /** 教程原文：VA 通常设为 70% */
  valuePct: 0.7,
  /** 相对 POC 成交量低于此比例视为缺口候选（与后端 volume_profile 一致） */
  gapRelMax: 0.25,
} as const

export type EnergyBin = {
  price_low: number
  price_high: number
  volume: number
  in_va: boolean
  is_poc: boolean
}

export type EnergyProfile = {
  poc: number | null
  vah: number | null
  val: number | null
  edge_high: number | null
  edge_low: number | null
  gap_high: number | null
  gap_low: number | null
  bins: EnergyBin[]
}

type OhlcVol = {
  high: number
  low: number
  close: number
  volume?: number
}

export function computeEnergyProfile(
  bars: OhlcVol[],
  opts?: { bins?: number; valuePct?: number; gapRelMax?: number },
): EnergyProfile | null {
  if (bars.length < 8) return null
  const bins = opts?.bins ?? GMA_ENERGY_TEACHING.bins
  const valuePct = opts?.valuePct ?? GMA_ENERGY_TEACHING.valuePct
  const gapRelMax = opts?.gapRelMax ?? GMA_ENERGY_TEACHING.gapRelMax

  let lo = Infinity
  let hi = -Infinity
  for (const b of bars) {
    if (Number.isFinite(b.low)) lo = Math.min(lo, b.low)
    if (Number.isFinite(b.high)) hi = Math.max(hi, b.high)
  }
  if (!(hi > lo) || !Number.isFinite(lo) || !Number.isFinite(hi)) {
    const last = bars[bars.length - 1]?.close
    if (!Number.isFinite(last)) return null
    return {
      poc: last,
      vah: last,
      val: last,
      edge_high: last,
      edge_low: last,
      gap_high: null,
      gap_low: null,
      bins: [],
    }
  }

  const edges: number[] = []
  for (let i = 0; i <= bins; i++) edges.push(lo + ((hi - lo) * i) / bins)
  const hist = new Array(bins).fill(0)
  for (const b of bars) {
    if (!(Number.isFinite(b.high) && Number.isFinite(b.low)) || b.high < b.low) continue
    const vol = Number.isFinite(b.volume) && (b.volume as number) > 0 ? (b.volume as number) : 0
    const left = clamp(searchRight(edges, b.low) - 1, 0, bins - 1)
    const right = clamp(searchRight(edges, b.high) - 1, 0, bins - 1)
    const span = Math.max(right - left + 1, 1)
    const add = vol / span
    for (let i = left; i <= right; i++) hist[i] += add
  }

  const total = hist.reduce((a, v) => a + v, 0)
  if (total <= 0) {
    const last = bars[bars.length - 1]?.close
    return {
      poc: last ?? null,
      vah: last ?? null,
      val: last ?? null,
      edge_high: hi,
      edge_low: lo,
      gap_high: null,
      gap_low: null,
      bins: [],
    }
  }

  let pocI = 0
  for (let i = 1; i < bins; i++) if (hist[i] > hist[pocI]) pocI = i
  const centers = hist.map((_, i) => (edges[i] + edges[i + 1]) / 2)
  const poc = centers[pocI]

  // VA：从 POC 向两侧扩展，直至累计成交量达到 valuePct（教程 70%）
  const target = total * valuePct
  let acc = hist[pocI]
  let left = pocI
  let right = pocI
  while (acc < target && (left > 0 || right < bins - 1)) {
    const takeLeft = left > 0 ? hist[left - 1] : -1
    const takeRight = right < bins - 1 ? hist[right + 1] : -1
    if (takeRight > takeLeft) {
      right += 1
      acc += hist[right]
    } else {
      left -= 1
      acc += hist[left]
    }
  }
  const vah = edges[right + 1]
  const val = edges[left]

  // 成交量缺口（峡谷）：POC 上下相对塌陷
  let gap_high: number | null = null
  let gap_low: number | null = null
  const pocVol = Math.max(hist[pocI], 1e-9)
  if (pocI + 2 < bins) {
    const rel = hist.slice(pocI).map((v) => v / pocVol)
    let valley = 0
    for (let i = 1; i < rel.length; i++) if (rel[i] < rel[valley]) valley = i
    if (valley > 0 && valley < rel.length - 1 && rel[valley] < gapRelMax) {
      gap_high = centers[pocI + valley]
    }
  }
  if (pocI >= 2) {
    const rel = hist.slice(0, pocI + 1).map((v) => v / pocVol)
    let valley = 0
    for (let i = 1; i < rel.length; i++) if (rel[i] < rel[valley]) valley = i
    if (valley > 0 && valley < rel.length - 1 && rel[valley] < gapRelMax) {
      gap_low = centers[valley]
    }
  }

  const outBins: EnergyBin[] = []
  for (let i = 0; i < bins; i++) {
    // 保留极低量档以便视觉上露出「峡谷」；全 0 跳过
    if (hist[i] <= 0) continue
    const mid = centers[i]
    outBins.push({
      price_low: edges[i],
      price_high: edges[i + 1],
      volume: hist[i],
      in_va: mid >= val && mid <= vah,
      is_poc: i === pocI,
    })
  }

  return {
    poc,
    vah,
    val,
    edge_high: hi,
    edge_low: lo,
    gap_high,
    gap_low,
    bins: outBins,
  }
}

function searchRight(edges: number[], x: number): number {
  let lo = 0
  let hi = edges.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (edges[mid] <= x) lo = mid + 1
    else hi = mid
  }
  return lo
}

function clamp(n: number, a: number, b: number): number {
  return Math.max(a, Math.min(b, n))
}
