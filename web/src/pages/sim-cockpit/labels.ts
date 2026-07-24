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

export const ACTION_LABEL: Record<string, string> = {
  HOLD: '持有观望',
  TARGET: '调仓',
  STOP_LOSS: '止损',
  TAKE_PROFIT: '止盈',
  COOLDOWN_HOLD: '冷却观望',
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

export function statusLabel(status?: string | null) {
  if (!status) return '未运行'
  return STATUS_LABEL[status] || status
}

export function regimeLabel(regime?: string | null) {
  if (!regime) return '—'
  return REGIME_LABEL[regime] || regime
}

export function actionLabel(action?: string | null) {
  if (!action) return '—'
  return ACTION_LABEL[action] || action
}

export function riskActionLabel(action?: string | null) {
  if (!action) return '—'
  return RISK_ACTION_LABEL[action] || action
}

export function qualityLabel(q?: string | null) {
  if (!q) return '—'
  return QUALITY_LABEL[q] || q
}
