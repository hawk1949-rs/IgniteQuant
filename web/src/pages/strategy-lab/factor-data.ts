/**
 * 因子挖掘（Factor Mining）配置层。
 * 原则：自主发现 / 组合 / 验证；不提供写死指标陈列室。
 * 主干只喂已闭合 OHLCV；逻辑写在 src 模块里，经 Feature Dict 交给下游。
 */

export type TimeframeId = '1m' | '5m' | '15m' | '60m' | '1d'

/** 管道只暴露原始字段，不预装 MA/KDJ 等耦合指标 */
export type RawField = 'open' | 'high' | 'low' | 'close' | 'volume' | 'open_oi' | 'close_oi'

export type FactorModuleStatus = 'draft' | 'ready'

/**
 * 用户自己的因子模块 = 一份可命名的 .py 代码块。
 */
export type FactorModule = {
  id: string
  /** 模块显示名（给人看） */
  name: string
  /** 归类，便于因子多时筛选 */
  category: string
  /** .py 文件名，例如 vol_filter.py；决定入库路径 */
  fileName: string
  /** 相对仓库根路径，由 fileName 推导 */
  modulePath: string
  /** 你在验证什么假设（自由文本） */
  hypothesis: string
  /** 本模块写入 Feature Dict 的键；由你定义 */
  outputKeys: string[]
  /** 本模块需要哪些周期的已闭合 OHLCV */
  requiredTimeframes: TimeframeId[]
  /** 在线编辑器中的 Python 源码 */
  source: string
  status: FactorModuleStatus
  enabled: boolean
}

export type DataPipelineConfig = {
  baseTimeframe: TimeframeId
  /** 额外周期：仅已闭合 bar + forward-fill，禁止读正在形成的高周期 */
  alignTimeframes: TimeframeId[]
  warmupBars: number
  /** 铁律锁定 */
  closedBarsOnly: true
  rawFields: RawField[]
}

export type FactorMiningConfig = {
  workspaceName: string
  pipeline: DataPipelineConfig
  modules: FactorModule[]
  /** 用户自定义归类列表（可为空分类，尚未挂因子） */
  categories: string[]
}

/** 已命名的因子组合：写入库后可在回测看板「因子与特征」节点选用 */
export type SavedFactorCombo = {
  id: string
  name: string
  /** 给人看的说明，会出现在回测看板下拉描述里 */
  note: string
  savedAt: string
  updatedAt: string
  config: FactorMiningConfig
}

export const TIMEFRAME_OPTIONS: { id: TimeframeId; label: string }[] = [
  { id: '1m', label: '1 分钟' },
  { id: '5m', label: '5 分钟' },
  { id: '15m', label: '15 分钟' },
  { id: '60m', label: '60 分钟' },
  { id: '1d', label: '日线' },
]

export const DEFAULT_CATEGORY = '未分类'

/** 预制归类；也可在「新建分类」中追加自定义 */
export const SUGGESTED_CATEGORIES = [
  '价格趋势',
  '波动率',
  '成交量',
  '基本面',
] as const

export function normalizeCategory(raw: string | undefined | null): string {
  const s = (raw ?? '').trim()
  return s || DEFAULT_CATEGORY
}

/** 合并预制、配置里登记的分类、以及因子上已用的分类 */
export function collectCategories(
  modules: FactorModule[],
  registered: string[] = [],
): string[] {
  const set = new Set<string>([...SUGGESTED_CATEGORIES, DEFAULT_CATEGORY])
  for (const c of registered) set.add(normalizeCategory(c))
  for (const m of modules) set.add(normalizeCategory(m.category))
  return Array.from(set).sort((a, b) => {
    const order = [...SUGGESTED_CATEGORIES, DEFAULT_CATEGORY]
    const ia = order.indexOf(a as (typeof order)[number])
    const ib = order.indexOf(b as (typeof order)[number])
    if (ia >= 0 || ib >= 0) {
      if (ia < 0) return 1
      if (ib < 0) return -1
      return ia - ib
    }
    return a.localeCompare(b, 'zh-CN')
  })
}

export const RAW_FIELDS: { id: RawField; label: string }[] = [
  { id: 'open', label: 'Open' },
  { id: 'high', label: 'High' },
  { id: 'low', label: 'Low' },
  { id: 'close', label: 'Close' },
  { id: 'volume', label: 'Volume' },
  { id: 'open_oi', label: 'Open OI' },
  { id: 'close_oi', label: 'Close OI' },
]

export const BOUNDARY_RULES = [
  {
    title: '主干保持纯粹',
    body: '主循环只做两件事：接收行情流、执行交易指令。禁止在主干里写均线、ADX、评分或仓位公式。',
  },
  {
    title: '因子层独立封装',
    body: '自定义逻辑放在 src/… 模块：只吃已闭合 OHLCV，只吐 Feature Dict。不读账户、持仓、订单。',
  },
  {
    title: '绕过预设指标库',
    body: '需要 Granville / Wilder ADX 时，自己写计算函数，自己控平滑与权重；框架不提供写死的 MA+KDJ 组合绑架你。',
  },
] as const

const ALL_RAW: RawField[] = [
  'open',
  'high',
  'low',
  'close',
  'volume',
  'open_oi',
  'close_oi',
]

function newId() {
  return `fm-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}

export const FACTORS_DIR = 'src/ignitequant/factors'

export function sanitizePyFileName(raw: string): string {
  let s = raw.trim().replace(/\\/g, '/').split('/').pop() || 'untitled.py'
  s = s.replace(/[^a-zA-Z0-9_.-]/g, '_')
  if (!s.toLowerCase().endsWith('.py')) s += '.py'
  if (!/^[a-zA-Z_]/.test(s)) s = `f_${s}`
  return s
}

export function modulePathFromFileName(fileName: string): string {
  return `${FACTORS_DIR}/${sanitizePyFileName(fileName)}`
}

export function defaultFactorSource(fileName: string, outputKeys: string[]): string {
  const keys = outputKeys.length > 0 ? outputKeys : ['feature_a']
  const returnBody = keys.map((k) => `        "${k}": 0.0,`).join('\n')
  const stem = sanitizePyFileName(fileName).replace(/\.py$/i, '')
  return `"""${stem}: write your own factor logic over closed OHLCV only."""

from __future__ import annotations

from typing import Mapping

# bars_by_tf["5m"] 等为已闭合原始字段：open/high/low/close/volume/oi
ClosedBars = Mapping[str, object]


def compute(bars_by_tf: Mapping[str, ClosedBars]) -> Mapping[str, float]:
    """纯函数：无账户/持仓；禁止读取未闭合 K 线。"""
    bars = bars_by_tf.get("5m")
    _ = bars  # TODO: 用自己的公式计算
    return {
${returnBody}
    }
`
}

const VOL_FILTER_SOURCE = `"""波动率过滤示例壳 — 窗口与阈值由你标定。"""

from __future__ import annotations

from typing import Mapping

ClosedBars = Mapping[str, object]


def compute(bars_by_tf: Mapping[str, ClosedBars]) -> Mapping[str, float]:
    _ = bars_by_tf.get("5m")
    # TODO: 读 close/high/low/volume；写你的 vol_ratio / vol_regime
    return {
        "vol_ratio": 0.0,
        "vol_regime": 0.0,
    }
`

const XTF_TREND_SOURCE = `"""跨周期趋势差示例壳 — 只用已闭合 60m，禁止偷未来。"""

from __future__ import annotations

from typing import Mapping

ClosedBars = Mapping[str, object]


def compute(bars_by_tf: Mapping[str, ClosedBars]) -> Mapping[str, float]:
    _ = bars_by_tf.get("5m")
    _ = bars_by_tf.get("60m")
    # TODO: 自写 Granville / ADX / price-action
    return {
        "trend_bias_60m": 0.0,
        "price_behavior_5m": 0.0,
    }
`

export function normalizeModule(raw: Partial<FactorModule> & { id?: string }): FactorModule {
  const slug = Math.random().toString(36).slice(2, 6)
  const fileName = sanitizePyFileName(
    raw.fileName ||
      (typeof raw.modulePath === 'string'
        ? raw.modulePath.split(/[/\\]/).pop() || `my_factor_${slug}.py`
        : `my_factor_${slug}.py`),
  )
  const outputKeys =
    Array.isArray(raw.outputKeys) && raw.outputKeys.length > 0
      ? raw.outputKeys
      : [`f_${slug}`]
  const source =
    typeof raw.source === 'string' && raw.source.trim().length > 0
      ? raw.source
      : defaultFactorSource(fileName, outputKeys)
  return {
    id: raw.id || newId(),
    name: (raw.name || fileName.replace(/\.py$/i, '')).trim() || '未命名因子',
    category: normalizeCategory(raw.category),
    fileName,
    modulePath: modulePathFromFileName(fileName),
    hypothesis: raw.hypothesis ?? '',
    outputKeys,
    requiredTimeframes:
      Array.isArray(raw.requiredTimeframes) && raw.requiredTimeframes.length > 0
        ? raw.requiredTimeframes
        : ['5m'],
    source,
    status: raw.status === 'ready' ? 'ready' : 'draft',
    enabled: raw.enabled !== false,
  }
}

export function createEmptyModule(category?: string): FactorModule {
  const slug = Math.random().toString(36).slice(2, 6)
  const fileName = `my_factor_${slug}.py`
  const outputKeys = [`f_${slug}`]
  return normalizeModule({
    name: '未命名因子',
    category: category,
    fileName,
    hypothesis: '在此写清你要验证的市场假设。',
    outputKeys,
    requiredTimeframes: ['5m'],
    source: defaultFactorSource(fileName, outputKeys),
    status: 'draft',
    enabled: true,
  })
}

/** 示范：两份 .py 因子 */
export function createStarterModules(): FactorModule[] {
  return [
    normalizeModule({
      name: '波动率过滤',
      category: '波动率',
      fileName: 'vol_filter.py',
      hypothesis: '仅当短窗波动相对长窗偏低时，趋势类特征才可信。',
      outputKeys: ['vol_ratio', 'vol_regime'],
      requiredTimeframes: ['5m'],
      source: VOL_FILTER_SOURCE,
      status: 'draft',
      enabled: true,
    }),
    normalizeModule({
      name: '跨周期趋势差',
      category: '价格趋势',
      fileName: 'xtf_trend.py',
      hypothesis: '用已闭合 60m 方向过滤 5m 价格行为。',
      outputKeys: ['trend_bias_60m', 'price_behavior_5m'],
      requiredTimeframes: ['5m', '60m'],
      source: XTF_TREND_SOURCE,
      status: 'draft',
      enabled: true,
    }),
  ]
}

export function createDefaultMiningConfig(): FactorMiningConfig {
  return {
    workspaceName: '我的因子工作区',
    pipeline: {
      baseTimeframe: '5m',
      alignTimeframes: ['60m'],
      warmupBars: 5,
      closedBarsOnly: true,
      rawFields: [...ALL_RAW],
    },
    modules: createStarterModules(),
    categories: ['价格趋势', '波动率', '成交量', '基本面'],
  }
}

const LS_DRAFT = 'ignitequant.lab.factor_mining_v2'
const LS_COMBOS = 'ignitequant.lab.factor_combos_v1'

function normalizeConfig(partial: Partial<FactorMiningConfig> | undefined): FactorMiningConfig {
  const base = createDefaultMiningConfig()
  if (!partial) return base
  const registered = Array.isArray(partial.categories)
    ? partial.categories.map(normalizeCategory).filter(Boolean)
    : base.categories
  const modules =
    Array.isArray(partial.modules) && partial.modules.length > 0
      ? partial.modules.map((m) => normalizeModule(m))
      : base.modules
  return {
    workspaceName: partial.workspaceName || base.workspaceName,
    pipeline: {
      ...base.pipeline,
      ...(partial.pipeline ?? {}),
      closedBarsOnly: true,
      rawFields: ALL_RAW,
    },
    modules,
    categories: collectCategories(modules, registered),
  }
}

export function loadFactorMiningConfig(): FactorMiningConfig {
  try {
    const raw = localStorage.getItem(LS_DRAFT)
    if (!raw) return createDefaultMiningConfig()
    return normalizeConfig(JSON.parse(raw) as Partial<FactorMiningConfig>)
  } catch {
    return createDefaultMiningConfig()
  }
}

export function persistFactorMiningConfig(cfg: FactorMiningConfig) {
  localStorage.setItem(LS_DRAFT, JSON.stringify(cfg))
}

export function loadSavedFactorCombos(): SavedFactorCombo[] {
  try {
    const raw = localStorage.getItem(LS_COMBOS)
    if (!raw) return []
    const parsed = JSON.parse(raw) as SavedFactorCombo[]
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((c) => c && typeof c.id === 'string' && typeof c.name === 'string' && c.config)
      .map((c) => ({
        ...c,
        note: c.note ?? '',
        savedAt: c.savedAt || new Date().toISOString(),
        updatedAt: c.updatedAt || c.savedAt || new Date().toISOString(),
        config: normalizeConfig(c.config),
      }))
  } catch {
    return []
  }
}

export function persistSavedFactorCombos(list: SavedFactorCombo[]) {
  localStorage.setItem(LS_COMBOS, JSON.stringify(list))
}

export function summarizeFactorCombo(combo: SavedFactorCombo): string {
  const enabled = combo.config.modules.filter((m) => m.enabled)
  const keys = collectOutputKeys(combo.config.modules)
  const tf = [
    combo.config.pipeline.baseTimeframe,
    ...combo.config.pipeline.alignTimeframes,
  ].join('+')
  const base = `${enabled.length} 个 .py · ${keys.length} 键 · ${tf}`
  return combo.note.trim() ? `${combo.note.trim()}（${base}）` : base
}

/** 另存为新命名组合；返回写入后的完整列表与新项 */
export function saveFactorComboAsNew(
  name: string,
  note: string,
  config: FactorMiningConfig,
): { list: SavedFactorCombo[]; combo: SavedFactorCombo } {
  const now = new Date().toISOString()
  const combo: SavedFactorCombo = {
    id: `fc-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    name: name.trim(),
    note: note.trim(),
    savedAt: now,
    updatedAt: now,
    config: {
      ...config,
      workspaceName: name.trim(),
      pipeline: { ...config.pipeline, closedBarsOnly: true },
      modules: config.modules.map((m) => ({ ...m })),
    },
  }
  const list = [combo, ...loadSavedFactorCombos()]
  persistSavedFactorCombos(list)
  return { list, combo }
}

/** 覆盖更新已有命名组合 */
export function updateFactorCombo(
  id: string,
  name: string,
  note: string,
  config: FactorMiningConfig,
): { list: SavedFactorCombo[]; combo: SavedFactorCombo } | null {
  const list = loadSavedFactorCombos()
  const idx = list.findIndex((c) => c.id === id)
  if (idx < 0) return null
  const now = new Date().toISOString()
  const combo: SavedFactorCombo = {
    ...list[idx],
    name: name.trim(),
    note: note.trim(),
    updatedAt: now,
    config: {
      ...config,
      workspaceName: name.trim(),
      pipeline: { ...config.pipeline, closedBarsOnly: true },
      modules: config.modules.map((m) => ({ ...m })),
    },
  }
  const next = [...list]
  next[idx] = combo
  persistSavedFactorCombos(next)
  return { list: next, combo }
}

export function deleteFactorCombo(id: string): SavedFactorCombo[] {
  const next = loadSavedFactorCombos().filter((c) => c.id !== id)
  persistSavedFactorCombos(next)
  return next
}

export function getFactorComboById(id: string): SavedFactorCombo | undefined {
  return loadSavedFactorCombos().find((c) => c.id === id)
}

export function collectOutputKeys(modules: FactorModule[]): string[] {
  const keys: string[] = []
  const seen = new Set<string>()
  for (const m of modules.filter((x) => x.enabled)) {
    for (const k of m.outputKeys) {
      const key = k.trim()
      if (!key || seen.has(key)) continue
      seen.add(key)
      keys.push(key)
    }
  }
  return keys
}

export function validateModules(
  modules: FactorModule[],
  opts: { lintSource?: boolean } = {},
): string[] {
  const errs: string[] = []
  const keyOwner = new Map<string, string>()
  const fileOwner = new Map<string, string>()
  for (const m of modules) {
    if (!m.name.trim()) errs.push('存在未命名模块')
    const fileName = sanitizePyFileName(m.fileName || m.modulePath)
    if (!fileName.endsWith('.py')) {
      errs.push(`「${m.name}」文件名应以 .py 结尾`)
    }
    const prevFile = fileOwner.get(fileName.toLowerCase())
    if (prevFile && prevFile !== m.id) {
      errs.push(`文件名「${fileName}」在同一组合内重复`)
    }
    fileOwner.set(fileName.toLowerCase(), m.id)

    if (m.outputKeys.length === 0 || m.outputKeys.every((k) => !k.trim())) {
      errs.push(`「${m.name}」至少声明一个 Feature Dict 输出键`)
    }
    for (const k of m.outputKeys) {
      const key = k.trim()
      if (!key) continue
      if (!/^[a-z][a-z0-9_]*$/.test(key)) {
        errs.push(`键「${key}」须为 snake_case`)
      }
      const prev = keyOwner.get(key)
      if (prev && prev !== m.id) {
        errs.push(`输出键「${key}」被多个模块占用`)
      }
      keyOwner.set(key, m.id)
    }
    if (opts.lintSource) {
      errs.push(...lintFactorSource(m.source || '', m.outputKeys).map((e) => `「${m.name}」${e}`))
    }
  }
  return errs
}

/** 静态检查（非真机 Python 解释器）；真跑通需后续接 runner */
export function lintFactorSource(source: string, _outputKeys: string[] = []): string[] {
  const errs: string[] = []
  const text = source || ''
  if (!text.trim()) {
    errs.push('源码为空')
    return errs
  }
  if (!/\bdef\s+compute\s*\(/.test(text)) {
    errs.push('缺少 def compute(...)')
  }
  if (!/\breturn\b/.test(text)) {
    errs.push('compute 中未见 return')
  }
  const opens = (text.match(/"""/g) || []).length
  if (opens % 2 !== 0) errs.push('三引号字符串可能未闭合')
  return errs
}

/** 契约预览：键由用户模块声明；数值占位 */
export function buildFeatureDictPreview(cfg: FactorMiningConfig): Record<string, number | null> {
  const out: Record<string, number | null> = {}
  collectOutputKeys(cfg.modules).forEach((key, i) => {
    out[key] = Math.round(((key.length * 13 + i * 7) % 50) / 10 - 2) * 100 / 100
  })
  return out
}

export const FACTOR_MODULE_CONTRACT = `from __future__ import annotations

from typing import Mapping, Protocol

# 管道只给你已闭合的原始 K 线；自己算一切。
ClosedBars = Mapping[str, object]  # open/high/low/close/volume/oi 序列


class FactorModule(Protocol):
    """因子层契约：纯函数，无账户/持仓，无未闭合 bar。"""

    def compute(
        self,
        bars_by_tf: Mapping[str, ClosedBars],
    ) -> Mapping[str, float]:
        """返回 Feature Dict，键由你定义。"""
        ...
`
