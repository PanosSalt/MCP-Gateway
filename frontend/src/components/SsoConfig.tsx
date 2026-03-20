import { useState, useEffect, useCallback } from 'react'
import { getEntraConfig, saveEntraConfig, deleteEntraConfig, ApiError } from '../api'
import type { EntraConfigOut } from '../types'
import { useAuth } from '../App'
import ConfirmModal from './ConfirmModal'
import { useForm } from '../hooks/useForm'

export default function SsoConfig() {
  const { auth } = useAuth()

  const { form, setForm, setField, busy, setBusy, error, setError, success, setSuccess } = useForm({
    entra_tenant_id: '',
    client_id: '',
    admin_group_id: '',
    analyst_group_id: '',
    viewer_group_id: '',
  })
  // client_secret is write-only — never pre-populated from the server response.
  // Keeping it separate from useForm ensures it cannot be accidentally serialised
  // or reflected back to any logging or state-inspection tool.
  const [clientSecret, setClientSecret] = useState('')

  const [existing, setExisting] = useState<EntraConfigOut | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [pendingConfirm, setPendingConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const cfg = await getEntraConfig()
      setExisting(cfg)
      setForm(f => ({
        ...f,
        entra_tenant_id: cfg.entra_tenant_id,
        client_id: cfg.client_id,
        admin_group_id: cfg.admin_group_id ?? '',
        analyst_group_id: cfg.analyst_group_id ?? '',
        viewer_group_id: cfg.viewer_group_id ?? '',
      }))
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setExisting(null)
        setEditing(true)
      } else {
        setError(err instanceof ApiError ? err.detail : 'Failed to load SSO config')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')
    setBusy(true)
    try {
      const cfg = await saveEntraConfig({
        entra_tenant_id: form.entra_tenant_id,
        client_id: form.client_id,
        ...(clientSecret ? { client_secret: clientSecret } : {}),
        ...(form.admin_group_id ? { admin_group_id: form.admin_group_id } : {}),
        ...(form.analyst_group_id ? { analyst_group_id: form.analyst_group_id } : {}),
        ...(form.viewer_group_id ? { viewer_group_id: form.viewer_group_id } : {}),
      })
      setExisting(cfg)
      setEditing(false)
      setClientSecret('')  // clear from memory immediately after transmission
      setSuccess('SSO configuration saved.')
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  function handleDelete() {
    setPendingConfirm({
      message: 'Remove SSO configuration?',
      onConfirm: async () => {
        setPendingConfirm(null)
        try {
          await deleteEntraConfig()
          setExisting(null)
          setEditing(true)
          setForm({ entra_tenant_id: '', client_id: '', admin_group_id: '', analyst_group_id: '', viewer_group_id: '' })
          setClientSecret('')
          setSuccess('')
        } catch (err) {
          setError(err instanceof ApiError ? err.detail : 'Delete failed')
        }
      },
    })
  }

  const ssoLoginUrl = existing
    ? `${window.location.origin}/auth/entra/login?tenant_slug=${auth?.tenant.slug ?? ''}`
    : null

  if (loading) return <div className="loading-row"><div className="spinner" /> Loading…</div>

  return (
    <div>
      <div className="section-header">
        <span className="section-title">SSO Configuration (Entra ID)</span>
        {existing && !editing && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn-ghost" onClick={() => setEditing(true)}>Edit</button>
            <button className="btn-danger" onClick={handleDelete}>Remove</button>
          </div>
        )}
      </div>

      {error   && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      {existing && !editing && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-title">Current configuration</div>
            <table>
              <tbody>
                <tr><td style={{ width: 180, color: 'var(--text-muted)', fontSize: 12 }}>Tenant ID</td><td><code>{existing.entra_tenant_id}</code></td></tr>
                <tr><td style={{ color: 'var(--text-muted)', fontSize: 12 }}>Client ID</td><td><code>{existing.client_id}</code></td></tr>
                <tr><td style={{ color: 'var(--text-muted)', fontSize: 12 }}>Admin group</td><td><code>{existing.admin_group_id ?? '—'}</code></td></tr>
                <tr><td style={{ color: 'var(--text-muted)', fontSize: 12 }}>Analyst group</td><td><code>{existing.analyst_group_id ?? '—'}</code></td></tr>
                <tr><td style={{ color: 'var(--text-muted)', fontSize: 12 }}>Viewer group</td><td><code>{existing.viewer_group_id ?? '—'}</code></td></tr>
              </tbody>
            </table>
          </div>

          {ssoLoginUrl && (
            <div className="card">
              <div className="card-title">SSO login URL</div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}>
                Share this link with users — it redirects directly to Entra ID login.
              </p>
              <div className="copy-row">
                <pre>{ssoLoginUrl}</pre>
                <button className="btn-ghost" onClick={() => void navigator.clipboard.writeText(ssoLoginUrl)}>Copy</button>
              </div>
            </div>
          )}
        </>
      )}

      {editing && (
        <div className="card">
          <div className="card-title">{existing ? 'Edit configuration' : 'Configure SSO'}</div>
          <form className="form" onSubmit={handleSave}>
            <div className="form-row">
              <div className="field">
                <label htmlFor="sso-tenant-id">Entra tenant ID</label>
                <input
                  id="sso-tenant-id"
                  value={form.entra_tenant_id} required
                  onChange={e => setField('entra_tenant_id', e.target.value)}
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                />
              </div>
              <div className="field">
                <label htmlFor="sso-client-id">Client ID</label>
                <input
                  id="sso-client-id"
                  value={form.client_id} required
                  onChange={e => setField('client_id', e.target.value)}
                  placeholder="mcp-gateway"
                />
              </div>
            </div>
            <div className="field">
              <label htmlFor="sso-client-secret">Client secret</label>
              <input
                id="sso-client-secret"
                type="password"
                value={clientSecret}
                required={!existing}
                onChange={e => setClientSecret(e.target.value)}
                placeholder={existing ? '(leave blank to keep existing)' : 'paste client secret'}
                autoComplete="new-password"
              />
            </div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Group UUIDs — paste from Azure AD group details.
            </p>
            <div className="form-row">
              <div className="field">
                <label htmlFor="sso-admin-group">Admin group UUID</label>
                <input id="sso-admin-group" value={form.admin_group_id} onChange={e => setField('admin_group_id', e.target.value)} placeholder="xxxxxxxx-xxxx-…" />
              </div>
              <div className="field">
                <label htmlFor="sso-analyst-group">Analyst group UUID</label>
                <input id="sso-analyst-group" value={form.analyst_group_id} onChange={e => setField('analyst_group_id', e.target.value)} placeholder="xxxxxxxx-xxxx-…" />
              </div>
              <div className="field">
                <label htmlFor="sso-viewer-group">Viewer group UUID</label>
                <input id="sso-viewer-group" value={form.viewer_group_id} onChange={e => setField('viewer_group_id', e.target.value)} placeholder="xxxxxxxx-xxxx-…" />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? <span className="spinner" aria-hidden="true" /> : 'Save configuration'}
              </button>
              {existing && (
                <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
              )}
            </div>
          </form>
        </div>
      )}
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
