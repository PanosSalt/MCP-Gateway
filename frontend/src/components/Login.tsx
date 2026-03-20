import { useState, useEffect, useRef } from 'react'
import { login as apiLogin, ApiError, setToken, decodeTokenPayload, exchangeSsoCode } from '../api'
import { SSO_POPUP_DIMENSIONS } from '../constants'
import { useAuth } from '../App'

interface Props {
  onSetup: () => void
}

export default function Login({ onSetup }: Props) {
  const { login } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const [showSso, setShowSso] = useState(false)
  const [tenantSlug, setTenantSlug] = useState('')
  const [ssoError, setSsoError] = useState('')
  const [ssoWaiting, setSsoWaiting] = useState(false)
  const [showManualPaste, setShowManualPaste] = useState(false)
  const [pastedCode, setPastedCode] = useState('')
  const popupRef = useRef<Window | null>(null)
  // Stable per-session nonce — validated against the postMessage payload to
  // reject forged messages even from same-origin compromised pages.
  const [ssoNonce] = useState(() =>
    typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
  )

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.data?.type !== 'sso-code' || typeof event.data.code !== 'string') return
      if (event.data?.nonce !== ssoNonce) return

      const code = event.data.code as string
      setSsoWaiting(false)
      exchangeSsoCode(code).then(resp => {
        const token = resp.access_token
        const payload = decodeTokenPayload(token)
        const exp = payload['exp'] as number | undefined
        if (exp && exp * 1000 < Date.now()) {
          setSsoError('Received token has expired')
          return
        }
        setToken(token)
        return login(token)
      }).catch((err: unknown) => {
        setSsoError(err instanceof ApiError ? err.detail : 'SSO login failed')
      })
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
    // `login` is wrapped in useCallback([]) in App.tsx, so this effect runs exactly
    // once — the stable reference prevents stale-closure issues with handleMessage.
  }, [login])

  async function handlePasswordLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const token = await apiLogin(email, password)
      await login(token.access_token)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  function handleOpenSsoLogin() {
    setSsoError('')
    if (!tenantSlug.trim()) { setSsoError('Enter a tenant slug'); return }
    const url = `/auth/entra/login?tenant_slug=${encodeURIComponent(tenantSlug.trim())}&nonce=${ssoNonce}`
    const popup = window.open(url, 'sso-popup', SSO_POPUP_DIMENSIONS)
    if (popup) {
      popupRef.current = popup
      setSsoWaiting(true)
      setShowManualPaste(false)
      const check = setInterval(() => {
        if (popup.closed) {
          clearInterval(check)
          setSsoWaiting(false)
        }
      }, 500)
    } else {
      setSsoError('Popup blocked — use the manual paste option below')
      setShowManualPaste(true)
    }
  }

  async function handlePasteCode() {
    setSsoError('')
    const c = pastedCode.trim()
    if (!c) { setSsoError('Paste the sign-in code from the SSO callback page'); return }
    try {
      const resp = await exchangeSsoCode(c)
      const token = resp.access_token
      const payload = decodeTokenPayload(token)
      const exp = payload['exp'] as number | undefined
      if (exp && exp * 1000 < Date.now()) { setSsoError('Token has expired'); return }
      setToken(token)
      await login(token)
    } catch (err) {
      setSsoError(err instanceof ApiError ? err.detail : 'Invalid or expired code')
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-box">
        <h1>MCP Gateway</h1>
        <p className="subtitle">Sign in to manage your tenant</p>

        {!showSso ? (
          <>
            {error && <div className="alert alert-error">{error}</div>}
            <form className="form" onSubmit={handlePasswordLogin}>
              <div className="field">
                <label htmlFor="login-email">Email</label>
                <input
                  id="login-email"
                  type="email" value={email} required autoFocus
                  onChange={e => setEmail(e.target.value)}
                  placeholder="admin@example.com"
                />
              </div>
              <div className="field">
                <label htmlFor="login-password">Password</label>
                <input
                  id="login-password"
                  type="password" value={password} required
                  onChange={e => setPassword(e.target.value)}
                />
              </div>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? <span className="spinner" aria-hidden="true" /> : 'Sign in'}
              </button>
            </form>

            <div className="auth-divider">or</div>

            <button
              className="btn-ghost"
              style={{ width: '100%' }}
              onClick={() => setShowSso(true)}
            >
              Sign in with SSO (Entra ID)
            </button>

            <div className="auth-divider">new here?</div>

            <button className="auth-link" onClick={onSetup}>
              Create a new tenant
            </button>
          </>
        ) : (
          <>
            {ssoError && <div className="alert alert-error">{ssoError}</div>}

            <div className="form">
              <div className="field">
                <label htmlFor="login-tenant-slug">Tenant slug</label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    id="login-tenant-slug"
                    value={tenantSlug} placeholder="local-test"
                    onChange={e => setTenantSlug(e.target.value)}
                    disabled={ssoWaiting}
                  />
                  <button
                    className="btn-primary"
                    onClick={handleOpenSsoLogin}
                    style={{ flexShrink: 0 }}
                    disabled={ssoWaiting}
                  >
                    {ssoWaiting
                      ? <><span className="spinner" aria-hidden="true" style={{ marginRight: 6 }} />Waiting...</>
                      : 'Sign in with SSO'}
                  </button>
                </div>
              </div>

              {ssoWaiting && (
                <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: -4 }}>
                  Complete authentication in the popup window. You will be signed in automatically.
                </p>
              )}

              {!ssoWaiting && !showManualPaste && (
                <button
                  className="auth-link"
                  style={{ fontSize: 11 }}
                  onClick={() => setShowManualPaste(true)}
                >
                  Popup not working? Paste token manually
                </button>
              )}

              {showManualPaste && !ssoWaiting && (
                <>
                  <div className="field">
                    <label htmlFor="login-paste-code">Paste the sign-in code from the callback page</label>
                    <textarea
                      id="login-paste-code"
                      value={pastedCode}
                      onChange={e => setPastedCode(e.target.value)}
                      placeholder="Paste the one-time code shown on the callback page"
                      style={{ minHeight: 72, fontFamily: 'monospace', fontSize: 11 }}
                    />
                  </div>
                  <button className="btn-primary" onClick={handlePasteCode}>
                    Continue with code
                  </button>
                </>
              )}

              <button
                className="auth-link"
                onClick={() => {
                  setShowSso(false)
                  setPastedCode('')
                  setSsoError('')
                  setSsoWaiting(false)
                  setShowManualPaste(false)
                }}
              >
                ← Back to password login
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
