/** Shared Chinese labels for sim cockpit. */

export const STATUS_LABEL: Record<string, string> = {
  RUNNING: '运行中',
  STALE: '数据滞后',
  IDLE: '未运行',
}

export const REGIME_LABEL: Record<string, string> = {
  TREND_UP: '上升趋势',
  TREND_DOWN: '下降趋势',
  RANGE: '震荡',
  TRANSITION: '切换中',
}

export const SHORT_BIAS_LABEL: Record<string, string> = {
  UP: '近端偏多',
  DOWN: '近端偏空',
  FLAT: '近端走平',
}

export const ACTION_LABEL: Record<string, string> = {
  HOLD: '维持目标',
  TARGET: '调仓',
  STOP_LOSS: '止损',
  TAKE_PROFIT: '止盈',
  BOOT_FLATTEN: '启动补平',
  FLAT_EXIT: '平仓',
  EXIT: '平仓',
  FLAT: '平仓',
  COOLDOWN_HOLD: '冷却观望',
  RESYNC: '仓位补齐',
  NONE: '无动作',
}

/** Net-position change verbs for TARGET / flatten intents. */
export function positionChangeVerb(
  from: number,
  to: number,
): string | null {
  if (!Number.isFinite(from) || !Number.isFinite(to)) return null
  if (from === to) return null
  if (from === 0 && to > 0) return '开多'
  if (from === 0 && to < 0) return '开空'
  if (to === 0 && from > 0) return '平多'
  if (to === 0 && from < 0) return '平空'
  if (from > 0 && to > 0) return to > from ? '加多' : '减多'
  if (from < 0 && to < 0) return to < from ? '加空' : '减空'
  if (from > 0 && to < 0) return '反手空'
  if (from < 0 && to > 0) return '反手多'
  return null
}

function formatSignalPart(signal?: number | null): string {
  if (signal == null || !Number.isFinite(Number(signal))) return ''
  const n = Number(signal)
  if (n > 0) return `+${n}`
  return String(n)
}

export type TradeActionLabelInput = {
  action?: string | null
  /** Net position before this intent/decision. */
  from?: number | null
  /** Net position target after. */
  to?: number | null
  /** Legacy signal ∈ [-3, 3]. */
  signal?: number | null
}

/**
 * Human action for cockpit: TARGET becomes 开多/开空/加多/加空… plus signal.
 * Exit actions get 平多/平空 when from/to known.
 */
export function tradeActionLabel(input: TradeActionLabelInput): string {
  const action = String(input.action || '').toUpperCase() || null
  const from =
    input.from == null || !Number.isFinite(Number(input.from))
      ? null
      : Number(input.from)
  const to =
    input.to == null || !Number.isFinite(Number(input.to))
      ? null
      : Number(input.to)
  const sig = formatSignalPart(input.signal)
  const verb =
    from != null && to != null ? positionChangeVerb(from, to) : null

  const withSig = (base: string) => (sig ? `${base}(${sig})` : base)

  if (action === 'TARGET' || action === 'RESYNC') {
    if (verb) return withSig(verb)
    return withSig(ACTION_LABEL[action] || '调仓')
  }

  if (action === 'STOP_LOSS') {
    if (verb === '平多' || verb === '平空') return withSig(`止损${verb}`)
    if (from != null && from > 0 && (to === 0 || to == null))
      return withSig('止损平多')
    if (from != null && from < 0 && (to === 0 || to == null))
      return withSig('止损平空')
    return withSig('止损')
  }

  if (action === 'TAKE_PROFIT') {
    if (verb === '平多' || verb === '平空') return withSig(`止盈${verb}`)
    if (from != null && from > 0 && (to === 0 || to == null))
      return withSig('止盈平多')
    if (from != null && from < 0 && (to === 0 || to == null))
      return withSig('止盈平空')
    return withSig('止盈')
  }

  if (
    action === 'BOOT_FLATTEN' ||
    action === 'FLAT_EXIT' ||
    action === 'EXIT' ||
    action === 'FLAT'
  ) {
    if (verb === '平多' || verb === '平空') {
      const prefix = action === 'BOOT_FLATTEN' ? '启动补平·' : ''
      return withSig(`${prefix}${verb}`)
    }
    return ACTION_LABEL[action] || actionLabel(action)
  }

  if (action === 'HOLD' || action === 'COOLDOWN_HOLD') {
    return ACTION_LABEL[action] || actionLabel(action)
  }

  // Decision rows sometimes omit action but still have before→after.
  if (!action && verb) return withSig(verb)

  if (action && ACTION_LABEL[action]) {
    return verb ? withSig(verb) : ACTION_LABEL[action]
  }
  return actionLabel(action)
}

/** Infer cockpit action code from an order intent row. */
export function intentActionCode(input: {
  current_position?: number | null
  desired_position?: number | null
  reason_codes?: string[] | null
  idempotency_key?: string | null
}): string {
  const codes = (input.reason_codes || []).map((c) => String(c).toUpperCase())
  const key = String(input.idempotency_key || '').toUpperCase()
  if (
    codes.some((c) => c.includes('BOOT_FLATTEN')) ||
    key.includes('BOOT_FLAT')
  ) {
    return 'BOOT_FLATTEN'
  }
  if (key.includes('STOP_LOSS') || codes.includes('LEGACY_EXIT_STOP')) {
    return 'STOP_LOSS'
  }
  if (key.includes('TAKE_PROFIT') || codes.includes('LEGACY_EXIT_TAKE')) {
    return 'TAKE_PROFIT'
  }
  if (
    codes.some(
      (c) =>
        c.includes('RESYNC') ||
        c.includes('CATCH_UP') ||
        c.includes('HEARTBEAT'),
    ) ||
    key.includes('HB-RESYNC') ||
    key.includes('CATCHUP')
  ) {
    return 'RESYNC'
  }
  const from = Number(input.current_position)
  const to = Number(input.desired_position)
  if (Number.isFinite(from) && Number.isFinite(to) && from === to) return 'HOLD'
  return 'TARGET'
}

/** Ant Design Tag color hint for trade action chips. */
export function tradeActionTagColor(
  input: TradeActionLabelInput,
): string | undefined {
  const label = tradeActionLabel(input)
  if (label.includes('开多') || label.includes('加多') || label.includes('反手多'))
    return 'red'
  if (label.includes('开空') || label.includes('加空') || label.includes('反手空'))
    return 'green'
  if (label.includes('止损')) return 'error'
  if (label.includes('止盈')) return 'success'
  if (label.includes('平多') || label.includes('平空') || label.includes('减'))
    return 'warning'
  if (label.includes('调仓')) return 'processing'
  return undefined
}

export const RISK_ACTION_LABEL: Record<string, string> = {
  PASS: '通过',
  RESIZE: '缩量',
  REJECT: '拒绝',
  HALT: '停机',
}

export const QUALITY_LABEL: Record<string, string> = {
  READY: '就绪',
  WARMING_UP: '预热中',
  STALE: '过期',
  MISSING_DATA: '缺数据',
  INVALID_VALUE: '无效值',
}

/** Risk / signal reason codes → cockpit Chinese (keep short for table cells). */
export const REASON_CODE_LABEL: Record<string, string> = {
  MARKET_CLOSED: '非交易时段',
  DATA_STALE: '行情过期',
  FACTOR_NOT_READY: '因子未就绪',
  SIGNAL_EXPIRED: '信号已过期',
  REGIME_NOT_ALLOWED: '状态不允许开仓',
  CONTRACT_INVALID: '合约无效',
  ROLL_IN_PROGRESS: '换月进行中',
  SPREAD_TOO_WIDE: '价差过大',
  INSUFFICIENT_LIQUIDITY: '流动性不足',
  PRICE_LIMIT_LOCKED: '涨跌停锁定',
  MARGIN_LIMIT: '保证金不足',
  DAILY_LOSS_LIMIT: '单日亏损限额',
  DRAWDOWN_LIMIT: '回撤限额',
  SYMBOL_RISK_LIMIT: '品种风险限额',
  PORTFOLIO_RISK_LIMIT: '组合风险限额',
  POSITION_LIMIT: '持仓上限',
  DUPLICATE_ORDER: '重复委托',
  UNKNOWN_ORDER_EXISTS: '存在未知订单',
  RECONCILIATION_MISMATCH: '对账不一致',
  KILL_SWITCH_ACTIVE: '熔断开关',
  RISK_REDUCING_ORDER: '风险减少单',
  GATEWAY_UNHEALTHY: '通道异常',
  COOLDOWN: '冷却中',
  LEGACY_EXIT_STOP: '止损退出',
  LEGACY_EXIT_TAKE: '止盈退出',
  TARGET_NET_RESYNC: '仓位对齐重试',
}

export function statusLabel(status?: string | null) {
  if (!status) return '未运行'
  return STATUS_LABEL[status] || status
}

export function regimeLabel(regime?: string | null) {
  if (!regime) return '—'
  return REGIME_LABEL[regime] || regime
}

export function shortBiasLabel(bias?: string | null) {
  if (!bias) return '—'
  return SHORT_BIAS_LABEL[bias] || bias
}

export function actionLabel(action?: string | null) {
  if (!action) return '—'
  if (ACTION_LABEL[action]) return ACTION_LABEL[action]
  // Never leak raw English enums (e.g. TARGET) into the cockpit.
  const pretty = action
    .replace(/_/g, '')
    .replace(/([A-Z])/g, ' $1')
    .trim()
  const fallback: Record<string, string> = {
    TARGET: '调仓',
    HOLD: '维持目标',
    STOPLOSS: '止损',
    TAKEPROFIT: '止盈',
  }
  const key = action.replace(/_/g, '').toUpperCase()
  return fallback[key] || pretty || action
}

export function riskActionLabel(action?: string | null) {
  if (!action) return '—'
  return RISK_ACTION_LABEL[action] || action
}

export function qualityLabel(q?: string | null) {
  if (!q) return '—'
  return QUALITY_LABEL[q] || q
}

export function reasonCodeLabel(code?: string | null) {
  if (!code) return '—'
  return REASON_CODE_LABEL[code] || code
}

type DecisionReasonInput = {
  risk?: {
    action?: string | null
    rule_hits?: string[] | null
  } | null
  reason_codes?: string[] | null
  applied_action?: string | null
}

/** Provenance / score crumbs — not order reasons. */
function isOrderReasonCode(code: string): boolean {
  const c = code.trim()
  if (!c) return false
  if (c.startsWith('LEGACY_')) return false
  if (/^(gv|vol|kdj|pen)=/i.test(c)) return false
  if (c === 'RISK_REDUCING_ORDER') return false
  return true
}

/**
 * Order/trade reasons only: risk rule_hits (reject / resize / halt / stop / take).
 * Ignores factor provenance tags like LEGACY_INDICATORS.
 */
export function decisionReasonText(row: DecisionReasonInput): string {
  const hits = (row.risk?.rule_hits || []).filter(
    (c): c is string => typeof c === 'string' && isOrderReasonCode(c),
  )
  if (!hits.length) return '—'

  const seen = new Set<string>()
  const labels: string[] = []
  for (const code of hits) {
    if (seen.has(code)) continue
    seen.add(code)
    labels.push(reasonCodeLabel(code))
    if (labels.length >= 2) break
  }
  return labels.join(' · ') || '—'
}
