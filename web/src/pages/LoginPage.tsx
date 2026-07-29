import { useState } from 'react'
import type { FormEvent } from 'react'
import { login, saveSession } from '@/lib/auth'

type Props = {
  onSuccess: (username: string) => void
}

export default function LoginPage({ onSuccess }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const result = await login(username.trim(), password)
      saveSession(result)
      onSuccess(result.username)
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-panel">
        <p className="login-eyebrow">IgniteQuant</p>
        <h1>登录座舱</h1>
        <p className="login-lead">输入账号密码后继续使用策略实验室与模拟盘。</p>

        <form className="login-form" onSubmit={onSubmit}>
          <label className="login-field">
            <span>账号</span>
            <input
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="用户名"
              required
            />
          </label>
          <label className="login-field">
            <span>密码</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="密码"
              required
            />
          </label>
          {error ? <p className="login-error" role="alert">{error}</p> : null}
          <button type="submit" className="login-submit" disabled={busy}>
            {busy ? '登录中…' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
