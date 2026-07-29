import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import {
  clearSession,
  fetchAuthStatus,
  fetchMe,
  getStoredToken,
  getStoredUsername,
} from '@/lib/auth'
import LoginPage from '@/pages/LoginPage'

type AuthContextValue = {
  username: string | null
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>({
  username: null,
  logout: () => undefined,
})

export function useAuth() {
  return useContext(AuthContext)
}

type Props = {
  children: ReactNode
}

export function AuthGate({ children }: Props) {
  const [ready, setReady] = useState(false)
  const [required, setRequired] = useState(true)
  const [username, setUsername] = useState<string | null>(null)

  const logout = useCallback(() => {
    clearSession()
    setUsername(null)
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const status = await fetchAuthStatus()
        if (cancelled) return
        setRequired(status.auth_required)
        if (!status.auth_required) {
          setUsername(getStoredUsername() || 'dev')
          setReady(true)
          return
        }
        const token = getStoredToken()
        if (!token) {
          setReady(true)
          return
        }
        try {
          const me = await fetchMe(token)
          if (cancelled) return
          setUsername(me.username)
        } catch {
          clearSession()
          if (!cancelled) setUsername(null)
        }
      } catch {
        // API 不可达时仍要求登录态；无 token 则显示登录页
        if (!cancelled) {
          setRequired(true)
          setUsername(getStoredToken() ? getStoredUsername() : null)
        }
      } finally {
        if (!cancelled) setReady(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const onUnauthorized = () => {
      setUsername(null)
    }
    window.addEventListener('iq:unauthorized', onUnauthorized)
    return () => window.removeEventListener('iq:unauthorized', onUnauthorized)
  }, [])

  const value = useMemo(
    () => ({
      username,
      logout,
    }),
    [username, logout],
  )

  if (!ready) {
    return (
      <div className="login-shell">
        <p className="login-loading">正在检查登录状态…</p>
      </div>
    )
  }

  if (required && !username) {
    return (
      <AuthContext.Provider value={value}>
        <LoginPage onSuccess={(name) => setUsername(name)} />
      </AuthContext.Provider>
    )
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
