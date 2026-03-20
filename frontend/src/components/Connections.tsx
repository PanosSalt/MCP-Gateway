import { useState, useEffect } from 'react'
import { listConnections, deleteConnection, getErrorMessage, cachedFetch, invalidateCache } from '../api'
import type { ConnectionOut, MinRole } from '../types'
import { useAuth } from '../App'
import ConfirmModal from './ConfirmModal'
import ConnectionCreateForm from './ConnectionCreateForm'
import ConnectionEditRow from './ConnectionEditRow'

const ROLE_BADGE: Record<MinRole, string> = {
  viewer: 'badge-viewer',
  analyst: 'badge-analyst',
  admin: 'badge-admin',
}
const PAGE_SIZE = 50

export default function Connections() {
  const { auth } = useAuth()
  const isAdmin = auth?.role === 'admin'

  const [connections, setConnections] = useState<ConnectionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [pendingConfirm, setPendingConfirm] = useState<{ message: string; onConfirm: () => void } | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    cachedFetch('connections', () => listConnections(0, PAGE_SIZE))
      .then(data => { if (!cancelled) { setConnections(data); setHasMore(data.length === PAGE_SIZE) } })
      .catch(err => { if (!cancelled) setError(getErrorMessage(err, 'Failed to load connections')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const data = await listConnections(connections.length, PAGE_SIZE)
      setConnections(prev => [...prev, ...data])
      setHasMore(data.length === PAGE_SIZE)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load more'))
    } finally {
      setLoadingMore(false)
    }
  }

  function handleDelete(id: string) {
    setPendingConfirm({
      message: 'Remove this connection?',
      onConfirm: async () => {
        setPendingConfirm(null)
        try {
          await deleteConnection(id)
          setConnections(cs => cs.filter(c => c.id !== id))
          invalidateCache('connections')
        } catch (err) {
          setError(getErrorMessage(err, 'Delete failed'))
        }
      },
    })
  }

  return (
    <div>
      <div className="section-header">
        <span className="section-title">Database Connections</span>
        {isAdmin && (
          <button className="btn-primary" onClick={() => setShowForm(s => !s)}>
            {showForm ? 'Cancel' : '+ Add connection'}
          </button>
        )}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {showForm && isAdmin && (
        <ConnectionCreateForm
          onCreated={conn => {
            setConnections(cs => [...cs, conn])
            invalidateCache('connections')
            setShowForm(false)
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

      <div className="card">
        {loading ? (
          <table><tbody>{Array.from({ length: 5 }, (_, i) => (
            <tr key={i}>{Array.from({ length: 6 }, (_, j) => <td key={j}><div className="skeleton-line" /></td>)}</tr>
          ))}</tbody></table>
        ) : connections.length === 0 ? (
          <div className="empty">No connections yet.{isAdmin ? ' Click "+ Add connection" to register one.' : ''}</div>
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Description</th>
                  <th>Min role</th>
                  <th>Added</th>
                  {isAdmin && <th></th>}
                </tr>
              </thead>
              <tbody>
                {connections.map(c =>
                  editingId === c.id ? (
                    <ConnectionEditRow
                      key={c.id}
                      connection={c}
                      colSpan={isAdmin ? 6 : 5}
                      onUpdated={updated => {
                        setConnections(cs => cs.map(x => x.id === updated.id ? updated : x))
                        invalidateCache('connections')
                        setEditingId(null)
                      }}
                      onCancel={() => setEditingId(null)}
                    />
                  ) : (
                    <tr key={c.id}>
                      <td style={{ fontWeight: 500 }}>{c.name}</td>
                      <td><code>{c.db_type}</code></td>
                      <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{c.description || '—'}</td>
                      <td><span className={`badge ${ROLE_BADGE[c.min_role]}`}>{c.min_role}</span></td>
                      <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                        {new Date(c.created_at).toLocaleDateString()}
                      </td>
                      {isAdmin && (
                        <td style={{ display: 'flex', gap: 4 }}>
                          <button className="btn-ghost" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => setEditingId(c.id)}>
                            Edit
                          </button>
                          <button className="btn-danger" style={{ fontSize: 11, padding: '3px 10px' }} onClick={() => handleDelete(c.id)}>
                            Delete
                          </button>
                        </td>
                      )}
                    </tr>
                  )
                )}
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
