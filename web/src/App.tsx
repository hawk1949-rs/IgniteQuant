import { useCallback, useEffect, useState } from 'react'
import WelcomePage from '@/pages/WelcomePage'
import StrategyLabPage from '@/pages/StrategyLabPage'
import LegacyStrategyLabPage from '@/pages/LegacyStrategyLabPage'

type Route = 'welcome' | 'lab' | 'lab-legacy'

function routeFromHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const path = raw.split('?')[0]
  if (path === 'lab-legacy' || path.startsWith('lab-legacy/')) return 'lab-legacy'
  if (path === 'lab' || path.startsWith('lab/')) return 'lab'
  return 'welcome'
}

const TITLES: Record<Route, string> = {
  welcome: '首页 — IgniteQuant',
  lab: '策略实验室 — IgniteQuant',
  'lab-legacy': '旧版策略实验室 — IgniteQuant',
}

export default function App() {
  const [route, setRoute] = useState<Route>(() =>
    typeof window === 'undefined' ? 'welcome' : routeFromHash(),
  )

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    document.body.dataset.theme = 'dark'
    document.title = TITLES[route]
  }, [route])

  const goWelcome = useCallback(() => {
    window.location.hash = '#/'
  }, [])

  const go = useCallback((key: 'lab' | 'lab-legacy') => {
    window.location.hash = `#/${key}`
  }, [])

  if (route === 'lab') {
    return <StrategyLabPage onBackHome={goWelcome} />
  }

  if (route === 'lab-legacy') {
    return <LegacyStrategyLabPage onBackHome={goWelcome} />
  }

  return <WelcomePage onNavigate={go} />
}
