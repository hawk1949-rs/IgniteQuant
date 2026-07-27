import { useState } from 'react'
import { cn } from '@/lib/utils'
import { WorkbenchPanel } from './strategy-lab/WorkbenchPanel'
import { FactorPanel } from './strategy-lab/FactorPanel'
import { SignalPanel } from './strategy-lab/SignalPanel'
import { ComingSoonPanel } from './strategy-lab/ComingSoonPanel'

type Props = {
  onBackHome?: () => void
}

export type LabSection =
  | 'workbench'
  | 'factor'
  | 'signal'
  | 'sizing'
  | 'admin'

const LAB_NAV: {
  id: LabSection
  label: string
  hint: string
  summary: string
}[] = [
  {
    id: 'workbench',
    label: '回测看板',
    hint: '档案 · 装配 · 绩效',
    summary: '策略档案、流水线装配、测试账号与绩效曲线。',
  },
  {
    id: 'factor',
    label: '因子与特征',
    hint: '编译 · 挖掘',
    summary: '自主因子模块 + 纯 OHLCV 管道；非预装指标陈列。',
  },
  {
    id: 'signal',
    label: '信号发生器',
    hint: '公式 · 门禁',
    summary: '选用已编译因子组成做多 / 做空 / 平仓公式，并附加门禁条件。',
  },
  {
    id: 'sizing',
    label: '仓位控制',
    hint: '手数 · 风险',
    summary: '固定手数、信号缩放、ATR 风险定仓与加仓规则。',
  },
  {
    id: 'admin',
    label: '管理后台',
    hint: '配置 · 运维',
    summary: '配置、归档、账号与系统运维入口。',
  },
]

function SectionBody({ id }: { id: LabSection }) {
  const meta = LAB_NAV.find((n) => n.id === id)!
  switch (id) {
    case 'workbench':
      return <WorkbenchPanel />
    case 'factor':
      return <FactorPanel />
    case 'signal':
      return <SignalPanel />
    case 'sizing':
    case 'admin':
      return (
        <ComingSoonPanel
          title={meta.label}
          english={meta.id}
          summary={meta.summary}
        />
      )
  }
}

export default function StrategyLabPage({ onBackHome }: Props) {
  const [section, setSection] = useState<LabSection>('workbench')
  const active = LAB_NAV.find((n) => n.id === section)

  return (
    <div className="mx-auto min-h-screen max-w-[92rem] px-3 pb-14 pt-4 sm:px-5 lg:px-6">
      <header className="mb-3 rounded-xl border border-line bg-panel/90 px-4 py-3.5 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {onBackHome ? (
              <button
                type="button"
                onClick={onBackHome}
                className="mb-1.5 text-[11px] font-medium text-blue hover:opacity-80"
              >
                ← 返回首页
              </button>
            ) : null}
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
                策略实验室
              </h1>
              <p className="text-xs text-faint">因子 → 信号 → 仓位 · 回测装配</p>
            </div>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted sm:text-sm">
              {active?.summary ||
                '一页切换回测看板、因子、信号、仓位与管理后台；布局与模拟盘座舱对齐。'}
            </p>
          </div>

          <nav
            className="flex shrink-0 flex-wrap rounded-lg border border-line bg-surface/50 p-0.5"
            aria-label="策略实验室分区"
          >
            {LAB_NAV.map((item) => {
              const isActive = item.id === section
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSection(item.id)}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-left transition',
                    isActive ? 'bg-blue text-white' : 'text-muted hover:text-ink',
                  )}
                >
                  <p className="text-sm font-medium leading-none">{item.label}</p>
                  <p
                    className={cn(
                      'mt-1 text-[10px] leading-none',
                      isActive ? 'text-white/75' : 'text-faint',
                    )}
                  >
                    {item.hint}
                  </p>
                </button>
              )
            })}
          </nav>
        </div>
      </header>

      <main className="min-w-0">
        <SectionBody id={section} />
      </main>
    </div>
  )
}
