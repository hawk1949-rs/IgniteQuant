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
