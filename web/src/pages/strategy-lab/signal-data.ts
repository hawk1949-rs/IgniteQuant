/**
 * 信号发生器配置层。
 * 从「因子与特征」已编译因子中选题，拼做多 / 做空 / 平仓公式，并可附加门禁条件。
 */

import {
  loadFactorMiningConfig,
  normalizeCategory,
  type FactorModule,
} from './factor-data'

export type SignalSide = 'long' | 'short' | 'flat'

export type CompareOp = 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq'

export type FormulaTerm = {
  id: string
  /** FactorModule.id */
  factorId: string
  /** Feature Dict 键；默认取该因子第一个 outputKey */
  outputKey: string
  op: CompareOp
  rhsType: 'number' | 'factor'
  rhsNumber: number
  rhsFactorId: string
  rhsOutputKey: string
}

export type SignalRule = {
  side: SignalSide
  enabled: boolean
  /** 条件之间如何组合 */
  join: 'and' | 'or'
  terms: FormulaTerm[]
}

export type ExtraConditions = {
  /** 连续满足公式的 K 线根数才触发 */
  confirmationBars: number
  /** 信号有效期（根） */
  signalTtlBars: number
  /** 同一根 K 线多空互斥（优先平仓） */
  longShortExclusive: boolean
  /** 平仓优先于开仓 */
  flatOverridesEntry: boolean
  /** 自定义附加说明（不参与计算） */
  note: string
}

export type SignalGeneratorConfig = {
  name: string
  updatedAt: string
  rules: Record<SignalSide, SignalRule>
  extras: ExtraConditions
}

/** 可供信号选题的已编译因子（启用中） */
export type CompiledFactorRef = {
  id: string
  name: string
  category: string
  fileName: string
  outputKeys: string[]
  enabled: boolean
}

export const SIGNAL_SIDE_META: {
  id: SignalSide
  label: string
  desc: string
  color: string
}[] = [
  {
    id: 'long',
    label: '做多',
    desc: '开多 / 加多条件满足时发出多头信号',
    color: '#32D74B',
  },
  {
    id: 'short',
    label: '做空',
    desc: '开空 / 加空条件满足时发出空头信号',
    color: '#FF453A',
  },
  {
    id: 'flat',
    label: '平仓',
    desc: '减仓或清仓条件满足时发出平仓信号',
    color: '#FFD60A',
  },
]

export const COMPARE_OP_OPTIONS: { id: CompareOp; label: string }[] = [
  { id: 'gt', label: '>' },
  { id: 'gte', label: '≥' },
  { id: 'lt', label: '<' },
  { id: 'lte', label: '≤' },
  { id: 'eq', label: '=' },
  { id: 'neq', label: '≠' },
]

const LS_SIGNAL = 'ignitequant.lab.signal_generator_v1'

function newId(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}

export function listCompiledFactors(): CompiledFactorRef[] {
  const cfg = loadFactorMiningConfig()
  return cfg.modules
    .filter((m) => m.enabled)
    .map((m: FactorModule) => ({
      id: m.id,
      name: m.name || m.fileName,
      category: normalizeCategory(m.category),
      fileName: m.fileName,
      outputKeys: m.outputKeys.length > 0 ? m.outputKeys : ['value'],
      enabled: m.enabled,
    }))
}

export function createEmptyTerm(factor?: CompiledFactorRef): FormulaTerm {
  const f = factor
  return {
    id: newId('term'),
    factorId: f?.id ?? '',
    outputKey: f?.outputKeys[0] ?? '',
    op: 'gt',
    rhsType: 'number',
    rhsNumber: 0,
    rhsFactorId: '',
    rhsOutputKey: '',
  }
}

function emptyRule(side: SignalSide): SignalRule {
  return {
    side,
    enabled: true,
    join: 'and',
    terms: [],
  }
}

export function createDefaultSignalConfig(): SignalGeneratorConfig {
  return {
    name: '我的信号发生器',
    updatedAt: new Date().toISOString(),
    rules: {
      long: emptyRule('long'),
      short: emptyRule('short'),
      flat: emptyRule('flat'),
    },
    extras: {
      confirmationBars: 2,
      signalTtlBars: 1,
      longShortExclusive: true,
      flatOverridesEntry: true,
      note: '',
    },
  }
}

function normalizeRule(raw: Partial<SignalRule> | undefined, side: SignalSide): SignalRule {
  const base = emptyRule(side)
  if (!raw) return base
  return {
    side,
    enabled: raw.enabled !== false,
    join: raw.join === 'or' ? 'or' : 'and',
    terms: Array.isArray(raw.terms)
      ? raw.terms.map((t) => ({
          id: t.id || newId('term'),
          factorId: t.factorId || '',
          outputKey: t.outputKey || '',
          op: (COMPARE_OP_OPTIONS.some((o) => o.id === t.op) ? t.op : 'gt') as CompareOp,
          rhsType: t.rhsType === 'factor' ? 'factor' : 'number',
          rhsNumber: Number.isFinite(t.rhsNumber) ? Number(t.rhsNumber) : 0,
          rhsFactorId: t.rhsFactorId || '',
          rhsOutputKey: t.rhsOutputKey || '',
        }))
      : [],
  }
}

export function normalizeSignalConfig(
  partial: Partial<SignalGeneratorConfig> | undefined,
): SignalGeneratorConfig {
  const base = createDefaultSignalConfig()
  if (!partial) return base
  return {
    name: partial.name?.trim() || base.name,
    updatedAt: partial.updatedAt || new Date().toISOString(),
    rules: {
      long: normalizeRule(partial.rules?.long, 'long'),
      short: normalizeRule(partial.rules?.short, 'short'),
      flat: normalizeRule(partial.rules?.flat, 'flat'),
    },
    extras: {
      confirmationBars: Math.max(1, Number(partial.extras?.confirmationBars ?? 2)),
      signalTtlBars: Math.max(1, Number(partial.extras?.signalTtlBars ?? 1)),
      longShortExclusive: partial.extras?.longShortExclusive !== false,
      flatOverridesEntry: partial.extras?.flatOverridesEntry !== false,
      note: partial.extras?.note ?? '',
    },
  }
}

export function loadSignalConfig(): SignalGeneratorConfig {
  try {
    const raw = localStorage.getItem(LS_SIGNAL)
    if (!raw) return createDefaultSignalConfig()
    return normalizeSignalConfig(JSON.parse(raw) as Partial<SignalGeneratorConfig>)
  } catch {
    return createDefaultSignalConfig()
  }
}

export function persistSignalConfig(cfg: SignalGeneratorConfig) {
  const next = {
    ...cfg,
    updatedAt: new Date().toISOString(),
  }
  localStorage.setItem(LS_SIGNAL, JSON.stringify(next))
}

export function describeTerm(
  term: FormulaTerm,
  factors: CompiledFactorRef[],
): string {
  const left = factors.find((f) => f.id === term.factorId)
  const leftName = left ? `${left.name}.${term.outputKey || left.outputKeys[0]}` : '（未选因子）'
  const op = COMPARE_OP_OPTIONS.find((o) => o.id === term.op)?.label ?? term.op
  if (term.rhsType === 'factor') {
    const right = factors.find((f) => f.id === term.rhsFactorId)
    const rightName = right
      ? `${right.name}.${term.rhsOutputKey || right.outputKeys[0]}`
      : '（未选因子）'
    return `${leftName} ${op} ${rightName}`
  }
  return `${leftName} ${op} ${term.rhsNumber}`
}

export function describeRule(
  rule: SignalRule,
  factors: CompiledFactorRef[],
): string {
  if (!rule.enabled) return '已关闭'
  if (rule.terms.length === 0) return '尚未添加条件'
  const join = rule.join === 'and' ? ' 且 ' : ' 或 '
  return rule.terms.map((t) => describeTerm(t, factors)).join(join)
}

export function validateSignalConfig(
  cfg: SignalGeneratorConfig,
  factors: CompiledFactorRef[],
): string[] {
  const errs: string[] = []
  const factorIds = new Set(factors.map((f) => f.id))
  if (factors.length === 0) {
    errs.push('暂无可用因子：请先在「因子与特征」启用并编译至少一个因子')
  }
  for (const meta of SIGNAL_SIDE_META) {
    const rule = cfg.rules[meta.id]
    if (!rule.enabled) continue
    if (rule.terms.length === 0) {
      errs.push(`「${meta.label}」已启用但尚未添加公式条件`)
      continue
    }
    for (const t of rule.terms) {
      if (!t.factorId || !factorIds.has(t.factorId)) {
        errs.push(`「${meta.label}」存在未选择或已失效的因子`)
      }
      if (t.rhsType === 'factor' && (!t.rhsFactorId || !factorIds.has(t.rhsFactorId))) {
        errs.push(`「${meta.label}」右侧比较因子无效`)
      }
    }
  }
  return [...new Set(errs)]
}
