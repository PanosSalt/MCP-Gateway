import { useState, useEffect, useCallback } from 'react'
import { listApiKeys, createApiKey, revokeApiKey, getErrorMessage, cachedFetch, invalidateCache } from '../api'
import { useAuth } from '../App'
import type { APIKeyResponse, APIKeyCreatedResponse } from '../types'
import ConfirmModal from './ConfirmModal'

function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleDateString()
}

async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch { /* secure-context restriction — fall through */ }
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export default function ApiKeys() {
  const { auth } = useAuth()
  const tenantSlug = auth?.tenant.slug ?? ''

  const [keys, setKeys] = useState<APIKeyResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [formBusy, setFormBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [newKey, setNewKey] = useState<APIKeyCreatedResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [pendingConfirm, setPendingConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setKeys(await cachedFetch('apikeys', listApiKeys))
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load API keys'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError('')
    setFormBusy(true)
    try {
      const created = await createApiKey({ name, ...(expiresAt ? { expires_at: expiresAt } : {}) })
      setNewKey(created)
      setCopied(false)
      setName('')
      setExpiresAt('')
      setShowForm(false)
      invalidateCache('apikeys')
      void load()
    } catch (err) {
      setFormError(getErrorMessage(err, 'Failed to create key'))
    } finally {
      setFormBusy(false)
    }
  }

  function handleRevoke(id: string) {
    setPendingConfirm({
      message: 'Revoke this API key? This cannot be undone.',
      onConfirm: async () => {
        setPendingConfirm(null)
        try {
          await revokeApiKey(id)
          setKeys(ks => ks.map(k => k.id === id ? { ...k, revoked_at: new Date().toISOString() } : k))
          invalidateCache('apikeys')
        } catch (err) {
          setError(getErrorMessage(err, 'Revoke failed'))
        }
      },
    })
  }

  return (
    <div>
      <div className="section-header">
        <span className="section-title">API Keys</span>
        <button className="btn-primary" onClick={() => { setShowForm(s => !s); setNewKey(null) }}>
          {showForm ? 'Cancel' : '+ New key'}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {newKey && (
        <div className="card" style={{ marginBottom: 16, borderColor: '#bbf7d0' }}>
          <div className="card-title" style={{ color: 'var(--success)' }}>Key created — copy it now, it won't be shown again</div>
          <div className="copy-row">
            <pre style={{ flex: 1, background: '#f0fdf4' }}>{newKey.raw_key}</pre>
            <button
              className="btn-ghost"
              onClick={async () => {
                const ok = await copyToClipboard(newKey.raw_key)
                if (ok) {
                  setCopied(true)
                  setTimeout(() => setCopied(false), 2000)
                }
              }}
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>
            Use as <code>Authorization: Bearer &lt;key&gt;</code> on REST endpoints.
            For Claude Desktop, the recommended approach is browser-based OAuth login (see setup instructions below).
          </p>
        </div>
      )}

      {showForm && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-title">New API key</div>
          {formError && <div className="alert alert-error">{formError}</div>}
          <form className="form" onSubmit={handleCreate}>
            <div className="form-row">
              <div className="field">
                <label htmlFor="key-name">Name</label>
                <input
                  id="key-name"
                  value={name} required
                  onChange={e => setName(e.target.value)}
                  placeholder="Claude Desktop"
                  autoFocus
                />
              </div>
              <div className="field">
                <label htmlFor="key-expires">Expires (optional)</label>
                <input
                  id="key-expires"
                  type="date" value={expiresAt}
                  onChange={e => setExpiresAt(e.target.value)}
                  min={new Date().toISOString().split('T')[0]}
                />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn-primary" disabled={formBusy}>
                {formBusy ? <span className="spinner" aria-hidden="true" /> : 'Generate key'}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        {loading ? (
          <table><tbody>{Array.from({ length: 5 }, (_, i) => (
            <tr key={i}>{Array.from({ length: 7 }, (_, j) => <td key={j}><div className="skeleton-line" /></td>)}</tr>
          ))}</tbody></table>
        ) : keys.length === 0 ? (
          <div className="empty">No API keys yet. Create one to use with Claude Desktop.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Prefix</th>
                <th>Created</th>
                <th>Last used</th>
                <th>Expires</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map(k => (
                <tr key={k.id}>
                  <td style={{ fontWeight: 500 }}>{k.name}</td>
                  <td><code style={{ fontSize: 12 }}>{k.prefix}…</code></td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>{fmtDate(k.created_at)}</td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>{fmtDate(k.last_used_at)}</td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>{fmtDate(k.expires_at)}</td>
                  <td>
                    {k.revoked_at
                      ? <span className="badge badge-revoked">Revoked</span>
                      : <span style={{ fontSize: 12, color: 'var(--success)' }}>Active</span>}
                  </td>
                  <td>
                    {!k.revoked_at && (
                      <button
                        className="btn-danger"
                        style={{ fontSize: 11, padding: '3px 10px' }}
                        onClick={() => handleRevoke(k.id)}
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">Claude Desktop Setup</div>

        <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Recommended — Browser login (OAuth)</p>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          No API key needed. Claude Desktop opens a browser window for login, then caches the session automatically.
        </p>
        <pre>{`{
  "mcpServers": {
    "mcp-gateway": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "${window.location.origin}/t/${tenantSlug}/mcp/sse"]
    }
  }
}`}</pre>

        <hr style={{ margin: '16px 0', border: 'none', borderTop: '1px solid var(--border)' }} />

        <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Alternative — API key</p>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          Use an API key as a Bearer token on REST endpoints.
        </p>
        <pre>{`{
  "mcpServers": {
    "mcp-gateway": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "--header", "Authorization: Bearer YOUR_KEY_HERE",
        "${window.location.origin}/t/${tenantSlug}/mcp/sse"
      ]
    }
  }
}`}</pre>
      </div>
      {pendingConfirm && (
        <ConfirmModal
          message={pendingConfirm.message}
          onConfirm={pendingConfirm.onConfirm}
          onCancel={() => setPendingConfirm(null)}
        />
      )}
    </div>
  )
}
