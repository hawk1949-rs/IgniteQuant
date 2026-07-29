import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '@/auth/AuthGate'
import WelcomePage from '@/pages/WelcomePage'
import StrategyLabPage from '@/pages/StrategyLabPage'
import LegacyStrategyLabPage from '@/pages/LegacyStrategyLabPage'
import SimCockpitPage from '@/pages/SimCockpitPage'

type Route = 'welcome' | 'lab' | 'lab-legacy' | 'sim'

function routeFromHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const path = raw.split('?')[0]
  if (path === 'lab-legacy' || path.startsWith('lab-legacy/')) return 'lab-legacy'
  if (path === 'lab' || path.startsWith('lab/')) return 'lab'
  if (path === 'sim' || path.startsWith('sim/')) return 'sim'
  return 'welcome'
}

const TITLES: Record<Route, string> = {
  welcome: '首页 — IgniteQuant',
  lab: '策略实验室 — IgniteQuant',
  'lab-legacy': '旧版策略实验室 — IgniteQuant',
  sim: '模拟盘座舱 — IgniteQuant',
}

export default function App() {
  const { username, logout } = useAuth()
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

  const go = useCallback((key: 'lab' | 'lab-legacy' | 'sim') => {
    window.location.hash = `#/${key}`
  }, [])

  if (route === 'lab') {
    return <StrategyLabPage onBackHome={goWelcome} />
  }

  if (route === 'lab-legacy') {
    return <LegacyStrategyLabPage onBackHome={goWelcome} />
  }

  if (route === 'sim') {
    return <SimCockpitPage onBackHome={goWelcome} />
  }

  return (
    <WelcomePage
      onNavigate={go}
      username={username}
      onLogout={logout}
    />
  )
}
