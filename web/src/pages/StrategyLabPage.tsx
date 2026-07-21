import { useState } from 'react'
import { cn } from '@/lib/utils'
import { WorkbenchPanel } from './strategy-lab/WorkbenchPanel'
import { FactorPanel } from './strategy-lab/FactorPanel'
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
  title: string
  subtitle: string
  summary: string
}[] = [
  {
    id: 'workbench',
    title: 'Workbench',
    subtitle: '回测看板',
    summary: '策略档案、流水线装配、测试账号与绩效曲线。',
  },
  {
    id: 'factor',
    title: 'Factor',
    subtitle: '因子与特征',
    summary: '自主因子模块 + 纯 OHLCV 管道；非预装指标陈列。',
  },
  {
    id: 'signal',
    title: 'Signal',
    subtitle: '信号发生器',
    summary: 'Alpha / Score 映射、确认根数、TTL 与原因码。',
  },
  {
    id: 'sizing',
    title: 'Sizing',
    subtitle: '仓位控制',
    summary: '固定手数、信号缩放、ATR 风险定仓与加仓规则。',
  },
  {
    id: 'admin',
    title: 'Admin',
    subtitle: '管理后台',
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
    case 'sizing':
    case 'admin':
      return (
        <ComingSoonPanel
          title={meta.subtitle}
          english={meta.title}
          summary={meta.summary}
        />
      )
  }
}

export default function StrategyLabPage({ onBackHome }: Props) {
  const [section, setSection] = useState<LabSection>('workbench')

  return (
    <div className="mx-auto min-h-screen max-w-[88rem] px-4 pb-20 pt-6 sm:px-6 lg:px-8">
      <header className="mb-6 rounded-2xl border border-line bg-panel px-5 py-6 sm:px-7">
        {onBackHome && (
          <button
            type="button"
            onClick={onBackHome}
            className="mb-3 text-xs font-medium text-blue hover:opacity-80"
          >
            ← 返回首页
          </button>
        )}
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue">
          Strategy Lab
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">策略实验室</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          左侧切换回测看板、因子与特征 / 信号发生器 / 仓位控制与管理后台。
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
        <aside className="h-fit rounded-2xl border border-line bg-panel p-2 lg:sticky lg:top-4">
          <nav className="flex flex-col gap-0.5" aria-label="策略实验室导航">
            {LAB_NAV.map((item) => {
              const active = item.id === section
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSection(item.id)}
                  className={cn(
                    'rounded-xl px-3 py-2.5 text-left transition',
                    active
                      ? 'bg-blue text-white'
                      : 'text-muted hover:bg-surface hover:text-ink',
                  )}
                >
                  <p className="text-sm font-medium">{item.subtitle}</p>
                  <p
                    className={cn(
                      'mt-0.5 text-[11px]',
                      active ? 'text-white/85' : 'text-faint',
                    )}
                  >
                    {item.title}
                  </p>
                </button>
              )
            })}
          </nav>
        </aside>

        <main className="min-w-0">
          <SectionBody id={section} />
        </main>
      </div>
    </div>
  )
}
