import { useState, useEffect, useCallback } from 'react'
import { listUsers, createUser, updateUserRole, deleteUser, getErrorMessage, cachedFetch, invalidateCache } from '../api'
import type { UserOut, Role } from '../types'
import { useAuth } from '../App'
import ConfirmModal from './ConfirmModal'
import { useForm } from '../hooks/useForm'

const ROLES: Role[] = ['viewer', 'analyst', 'admin']
const PAGE_SIZE = 50

export default function Users() {
  const { auth } = useAuth()
  const [users, setUsers] = useState<UserOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [pending, setPending] = useState<Record<string, Role>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState('')

  const [pendingConfirm, setPendingConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null)

  const [showForm, setShowForm] = useState(false)
  const {
    form, setForm, busy: formBusy, setBusy: setFormBusy,
    error: formError, setError: setFormError, reset: resetCreateForm,
  } = useForm({ email: '', password: '', role: 'viewer' as Role })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await cachedFetch('users', () => listUsers(0, PAGE_SIZE))
      setUsers(data)
      setHasMore(data.length === PAGE_SIZE)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load users'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const data = await listUsers(users.length, PAGE_SIZE)
      setUsers(prev => [...prev, ...data])
      setHasMore(data.length === PAGE_SIZE)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load more'))
    } finally {
      setLoadingMore(false)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setFormError('')
    setFormBusy(true)
    try {
      const user = await createUser(form)
      setUsers(us => [...us, user])
      invalidateCache('users')
      resetCreateForm()
      setShowForm(false)
    } catch (err) {
      setFormError(getErrorMessage(err, 'Failed to create user'))
    } finally {
      setFormBusy(false)
    }
  }

  function handleDropdownChange(userId: string, role: Role) {
    setPending(prev => ({ ...prev, [userId]: role }))
    setSuccessMsg('')
  }

  async function handleSave(userId: string) {
    const role = pending[userId]
    if (role === undefined) return
    setSaving(userId)
    setError('')
    setSuccessMsg('')
    try {
      const updated = await updateUserRole(userId, { role })
      setUsers(us => us.map(u => u.id === userId ? updated : u))
      invalidateCache('users')
      setPending(prev => {
        const next = { ...prev }
        delete next[userId]
        return next
      })
      setSuccessMsg(`Role updated for ${updated.email}`)
      setTimeout(() => setSuccessMsg(''), 3000)
    } catch (err) {
      setError(getErrorMessage(err, 'Role update failed'))
    } finally {
      setSaving(null)
    }
  }

  function handleDelete(userId: string, email: string) {
    setPendingConfirm({
      message: `Remove user ${email}? This cannot be undone.`,
      onConfirm: async () => {
        setPendingConfirm(null)
        try {
          await deleteUser(userId)
          setUsers(us => us.filter((u: UserOut) => u.id !== userId))
          invalidateCache('users')
        } catch (err) {
          setError(getErrorMessage(err, 'Failed to remove user'))
        }
      },
    })
  }

  return (
    <div>
      <div className="section-header">
        <span className="section-title">Users</span>
        <button className="btn-primary" onClick={() => setShowForm(s => !s)}>
          {showForm ? 'Cancel' : '+ Add user'}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {successMsg && <div className="alert alert-success">{successMsg}</div>}

      {showForm && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-title">New local user</div>
          {formError && <div className="alert alert-error">{formError}</div>}
          <form className="form" onSubmit={handleCreate}>
            <div className="form-row">
              <div className="field">
                <label htmlFor="user-email">Email</label>
                <input id="user-email" type="email" value={form.email} required onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
              </div>
              <div className="field">
                <label htmlFor="user-password">Password</label>
                <input id="user-password" type="password" value={form.password} required minLength={12} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} />
              </div>
              <div className="field">
                <label htmlFor="user-role">Role</label>
                <select id="user-role" value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value as Role }))}>
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn-primary" disabled={formBusy}>
                {formBusy ? <span className="spinner" aria-hidden="true" /> : 'Create user'}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="card">
        {loading ? (
          <table><tbody>{Array.from({ length: 5 }, (_, i) => (
            <tr key={i}>{Array.from({ length: 5 }, (_, j) => <td key={j}><div className="skeleton-line" /></td>)}</tr>
          ))}</tbody></table>
        ) : users.length === 0 ? (
          <div className="empty">No users found.</div>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Provider</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id}>
                    <td style={{ fontWeight: u.email === auth?.email ? 600 : undefined }}>
                      {u.email}
                      {u.email === auth?.email && (
                        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>(you)</span>
                      )}
                    </td>
                    <td><span className={`badge badge-${u.auth_provider}`}>{u.auth_provider}</span></td>
                    <td>
                      {u.auth_provider === 'local' ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <select
                            value={pending[u.id] ?? u.role}
                            onChange={e => handleDropdownChange(u.id, e.target.value as Role)}
                            disabled={saving === u.id}
                            style={{ padding: '3px 6px', fontSize: 12 }}
                          >
                            {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                          </select>
                          {pending[u.id] !== undefined && pending[u.id] !== u.role && saving !== u.id && (
                            <button
                              className="btn btn-primary"
                              onClick={() => handleSave(u.id)}
                              style={{ fontSize: 11, padding: '2px 10px', lineHeight: '18px' }}
                            >
                              Update
                            </button>
                          )}
                          {saving === u.id && <span className="spinner" aria-hidden="true" style={{ width: 14, height: 14 }} />}
                        </div>
                      ) : (
                        <span className={`badge badge-${u.role}`}>{u.role}</span>
                      )}
                    </td>
                    <td>
                      <span style={{ fontSize: 12, color: u.is_active ? 'var(--success)' : 'var(--danger)' }}>
                        {u.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td>
                      {u.email !== auth?.email && (
                        <button
                          className="btn-ghost"
                          style={{ color: 'var(--danger)', padding: '2px 8px', fontSize: 12 }}
                          onClick={() => handleDelete(u.id, u.email)}
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMore && (
              <div style={{ padding: 12, textAlign: 'center' }}>
                <button className="btn-ghost" onClick={loadMore} disabled={loadingMore}>
                  {loadingMore ? <><span className="spinner" aria-hidden="true" /> Loading...</> : 'Load more'}
                </button>
              </div>
            )}
          </>
        )}
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
