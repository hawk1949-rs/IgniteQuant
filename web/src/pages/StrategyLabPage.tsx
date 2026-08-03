import { useState } from 'react'
import { cn } from '@/lib/utils'
import { WorkbenchPanel } from './strategy-lab/WorkbenchPanel'
import { FactorPanel } from './strategy-lab/FactorPanel'
import { SignalPanel } from './strategy-lab/SignalPanel'

type Props = {
  onBackHome?: () => void
}

export type LabSection = 'workbench' | 'factor' | 'signal'

const LAB_NAV: {
  id: LabSection
  label: string
  summary: string
}[] = [
  {
    id: 'workbench',
    label: '回测工作台',
    summary: '设区间与参数，跑 Falcon 回测，看曲线与绩效。',
  },
  {
    id: 'factor',
    label: '因子',
    summary: '左边对话挖概念，右边命名分类并查看生成的代码。',
  },
  {
    id: 'signal',
    label: '信号',
    summary: '用已编译因子组合多空公式与门禁（本地草稿）。',
  },
]

function SectionBody({ id }: { id: LabSection }) {
  switch (id) {
    case 'workbench':
      return <WorkbenchPanel />
    case 'factor':
      return <FactorPanel />
    case 'signal':
      return <SignalPanel />
  }
}

export default function StrategyLabPage({ onBackHome }: Props) {
  const [section, setSection] = useState<LabSection>('workbench')
  const active = LAB_NAV.find((n) => n.id === section)

  return (
    <div className="mx-auto min-h-screen max-w-[92rem] px-3 pb-14 pt-4 sm:px-5 lg:px-6">
      <header className="mb-4 rounded-xl border border-line bg-panel/90 px-4 py-3.5 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {onBackHome ? (
              <button
                type="button"
                onClick={onBackHome}
                className="mb-1.5 text-xs font-medium text-blue hover:opacity-80"
              >
                ← 返回首页
              </button>
            ) : null}
            <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">
              策略实验室
            </h1>
            <p className="mt-1 max-w-xl text-sm leading-relaxed text-muted">
              {active?.summary}
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
                    'rounded-md px-3.5 py-2 text-sm font-medium transition',
                    isActive ? 'bg-blue text-white' : 'text-muted hover:text-ink',
                  )}
                >
                  {item.label}
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
