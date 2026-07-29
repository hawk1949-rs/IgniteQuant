const TOKEN_KEY = 'iq_cockpit_token'
const USER_KEY = 'iq_cockpit_user'
const EXP_KEY = 'iq_cockpit_exp'

export type AuthStatus = {
  auth_required: boolean
}

export type LoginResult = {
  token: string
  expires_at: number
  username: string
  token_type: string
}

export function getStoredToken(): string | null {
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    const exp = Number(localStorage.getItem(EXP_KEY) || '0')
    if (!token) return null
    if (exp && exp * 1000 < Date.now()) {
      clearSession()
      return null
    }
    return token
  } catch {
    return null
  }
}

export function getStoredUsername(): string | null {
  try {
    return localStorage.getItem(USER_KEY)
  } catch {
    return null
  }
}

export function saveSession(result: LoginResult) {
  localStorage.setItem(TOKEN_KEY, result.token)
  localStorage.setItem(USER_KEY, result.username)
  localStorage.setItem(EXP_KEY, String(result.expires_at))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(EXP_KEY)
}

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const res = await fetch('/api/auth/status')
  if (!res.ok) throw new Error('无法读取登录配置')
  return res.json()
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    let detail = '登录失败'
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

export async function fetchMe(token: string): Promise<{ authenticated: boolean; username: string }> {
  const res = await fetch('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('会话无效')
  return res.json()
}
