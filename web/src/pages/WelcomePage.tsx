type ModuleKey = 'lab' | 'lab-legacy'

type Props = {
  onNavigate: (key: ModuleKey) => void
}

const MODULES: {
  key: ModuleKey
  title: string
  desc: string
  arrow: string
}[] = [
  {
    key: 'lab',
    title: '策略实验室',
    desc: '回测工作台：策略档案、流水线装配、测试账号与绩效曲线。',
    arrow: '进入 →',
  },
  {
    key: 'lab-legacy',
    title: '旧版策略实验室',
    desc: '原 Falcon 回测控制台：本地/天勤回测、评分对照与跑次档案。',
    arrow: '进入 →',
  },
]

export default function WelcomePage({ onNavigate }: Props) {
  return (
    <div className="welcome-shell">
      <header className="site-header" role="navigation">
        <nav className="site-header__nav" aria-label="页面切换">
          <span className="site-header__brand">IgniteQuant</span>
          <a href="#/" className="is-active" onClick={(e) => e.preventDefault()}>
            首页
          </a>
          <button
            type="button"
            className="site-header__link-btn"
            onClick={() => onNavigate('lab')}
          >
            策略实验室
          </button>
          <button
            type="button"
            className="site-header__link-btn"
            onClick={() => onNavigate('lab-legacy')}
          >
            旧版策略实验室
          </button>
        </nav>
      </header>

      <div className="welcome">
        <header className="welcome-hero">
          <p className="welcome-hero__eyebrow">Quantitative Platform</p>
          <h1>IgniteQuant</h1>
          <p className="welcome-hero__lead">
            面向策略研究与回测实验的统一门户。从下方进入模块，保持简洁，专注决策。
          </p>
        </header>

        <nav className="welcome-grid" aria-label="功能模块">
          {MODULES.map((m) => (
            <button
              key={m.key}
              type="button"
              className="welcome-card"
              onClick={() => onNavigate(m.key)}
            >
              <span className="welcome-card__title">{m.title}</span>
              <span className="welcome-card__desc">{m.desc}</span>
              <span className="welcome-card__arrow">{m.arrow}</span>
            </button>
          ))}
        </nav>

        <footer className="welcome-foot">
          页面展示仅供参考，不构成投资建议。
        </footer>
      </div>
    </div>
  )
}
