import { useState, useEffect, createContext, useContext, useCallback } from 'react'
import { getToken, setToken, clearToken, decodeTokenPayload, getMyTenant, ApiError } from './api'
import type { TenantOut, Role } from './types'

import Login from './components/Login'
import Setup from './components/Setup'
import Dashboard from './components/Dashboard'
import Connections from './components/Connections'
import SsoConfig from './components/SsoConfig'
import Users from './components/Users'
import Query from './components/Query'
import ApiKeys from './components/ApiKeys'
import Tools from './components/Tools'
import AuditLog from './components/AuditLog'
import ErrorBoundary from './components/ErrorBoundary'

// ── Auth context ───────────────────────────────────────────────────────────────

interface AuthState {
  token: string
  role: Role
  email: string
  tenant: TenantOut
}

interface AuthCtx {
  auth: AuthState | null
  login: (token: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthCtx>({
  auth: null,
  login: async () => {},
  logout: () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

// ── Tabs ───────────────────────────────────────────────────────────────────────

type Tab = 'connections' | 'tools' | 'sso' | 'users' | 'query' | 'apikeys' | 'audit'

interface TabDef {
  id: Tab
  label: string
  minRole: Role
}

const TABS: TabDef[] = [
  { id: 'connections', label: 'Connections', minRole: 'viewer' },
  { id: 'tools',       label: 'Tools',       minRole: 'viewer' },
  { id: 'query',       label: 'Query',       minRole: 'analyst' },
  { id: 'apikeys',     label: 'API Keys',    minRole: 'viewer' },
  { id: 'users',       label: 'Users',       minRole: 'admin' },
  { id: 'audit',       label: 'Audit Log',     minRole: 'admin' },
  { id: 'sso',         label: 'SSO Config',  minRole: 'admin' },
]

const ROLE_RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2 }

function hasRole(userRole: Role, minRole: Role): boolean {
  return ROLE_RANK[userRole] >= ROLE_RANK[minRole]
}

// ── App ────────────────────────────────────────────────────────────────────────

type Page = 'login' | 'setup' | 'app'

const _TAB_FALLBACK = (
  <div className="alert alert-error" style={{ margin: 24 }}>
    This panel crashed. Switch to another tab or reload the page.
  </div>
)

export default function App() {
  const [auth, setAuth] = useState<AuthState | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState<Page>('login')
  const [activeTab, setActiveTab] = useState<Tab>('connections')
  const [online, setOnline] = useState(navigator.onLine)

  useEffect(() => {
    const on = () => setOnline(true)
    const off = () => setOnline(false)
    window.addEventListener('online', on)
    window.addEventListener('offline', off)
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off) }
  }, [])

  const doLogin = useCallback(async (token: string) => {
    setToken(token)
    const payload = decodeTokenPayload(token)
    const tenant = await getMyTenant()
    setAuth({
      token,
      role: payload['role'] as Role,
      email: (payload['email'] as string | undefined) ?? '',
      tenant,
    })
  }, [])

  const doLogout = useCallback(() => {
    clearToken()
    setAuth(null)
  }, [])

  // Restore session on mount
  useEffect(() => {
    const token = getToken()
    if (!token) { setLoading(false); return }
    const payload = decodeTokenPayload(token)
    const exp = payload['exp'] as number | undefined
    if (exp && exp * 1000 < Date.now()) { clearToken(); setLoading(false); return }
    getMyTenant()
      .then(tenant => {
        setAuth({ token, role: payload['role'] as Role, email: payload['email'] as string ?? '', tenant })
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) clearToken()
      })
      .finally(() => setLoading(false))
  }, [])

  // Keep first visible tab active when role changes
  useEffect(() => {
    if (!auth) return
    const visible = TABS.filter(t => hasRole(auth.role, t.minRole))
    if (!visible.find(t => t.id === activeTab) && visible[0]) {
      setActiveTab(visible[0].id)
    }
  }, [auth])

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div className="spinner" />
      </div>
    )
  }

  // Not logged in → show login or setup
  if (!auth) {
    return (
      <AuthContext.Provider value={{ auth, login: doLogin, logout: doLogout }}>
        {page === 'setup'
          ? <Setup onDone={() => setPage('login')} />
          : <Login onSetup={() => setPage('setup')} />}
      </AuthContext.Provider>
    )
  }

  const visibleTabs = TABS.filter(t => hasRole(auth.role, t.minRole))

  return (
    <AuthContext.Provider value={{ auth, login: doLogin, logout: doLogout }}>
      <div className="layout">
        <header className="topbar">
          <span className="topbar-brand">MCP Gateway</span>
          <nav className="topbar-nav">
            {visibleTabs.map(t => (
              <button
                key={t.id}
                className={`tab-btn${activeTab === t.id ? ' active' : ''}`}
                onClick={() => setActiveTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="topbar-user">
            {!online && <span className="badge badge-error">Offline</span>}
            <Dashboard />
            <button className="btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }} onClick={doLogout}>
              Sign out
            </button>
          </div>
        </header>

        <main className="main">
          {activeTab === 'connections' && <ErrorBoundary fallback={_TAB_FALLBACK}><Connections /></ErrorBoundary>}
          {activeTab === 'tools'       && <ErrorBoundary fallback={_TAB_FALLBACK}><Tools /></ErrorBoundary>}
          {activeTab === 'query'       && <ErrorBoundary fallback={_TAB_FALLBACK}><Query /></ErrorBoundary>}
          {activeTab === 'apikeys'     && <ErrorBoundary fallback={_TAB_FALLBACK}><ApiKeys /></ErrorBoundary>}
          {activeTab === 'users'       && <ErrorBoundary fallback={_TAB_FALLBACK}><Users /></ErrorBoundary>}
          {activeTab === 'audit'       && <ErrorBoundary fallback={_TAB_FALLBACK}><AuditLog /></ErrorBoundary>}
          {activeTab === 'sso'         && <ErrorBoundary fallback={_TAB_FALLBACK}><SsoConfig /></ErrorBoundary>}
        </main>
      </div>
    </AuthContext.Provider>
  )
}
