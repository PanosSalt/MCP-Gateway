import { createConnection, getErrorMessage } from '../api'
import type { ConnectionOut, DBType, MinRole } from '../types'
import { useForm } from '../hooks/useForm'

const DB_TYPES: DBType[] = ['postgres', 'mysql', 'sqlite', 'mssql']
const MIN_ROLES: MinRole[] = ['viewer', 'analyst', 'admin']

interface Props {
  onCreated: (conn: ConnectionOut) => void
  onCancel: () => void
}

export default function ConnectionCreateForm({ onCreated, onCancel }: Props) {
  const { form, setField, busy, setBusy, error, setError, reset } = useForm({
    name: '',
    db_type: 'postgres' as DBType,
    connection_string: '',
    description: '',
    min_role: 'viewer' as MinRole,
  })

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const conn = await createConnection(form)
      reset()
      onCreated(conn)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to create connection'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-title">New connection</div>
      {error && <div className="alert alert-error">{error}</div>}
      <form className="form" onSubmit={handleSubmit}>
        <div className="form-row">
          <div className="field">
            <label htmlFor="conn-name">Name</label>
            <input id="conn-name" value={form.name} required onChange={e => setField('name', e.target.value)} placeholder="Products DB" />
          </div>
          <div className="field">
            <label htmlFor="conn-type">Database type</label>
            <select id="conn-type" value={form.db_type} onChange={e => setField('db_type', e.target.value as DBType)}>
              {DB_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="conn-role">Min role to see this DB</label>
            <select id="conn-role" value={form.min_role} onChange={e => setField('min_role', e.target.value as MinRole)}>
              {MIN_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="conn-string">Connection string</label>
          <input
            id="conn-string"
            value={form.connection_string} required
            onChange={e => setField('connection_string', e.target.value)}
            placeholder="postgresql://user:pass@host:5432/db"
          />
        </div>
        <div className="field">
          <label htmlFor="conn-desc">Description (optional)</label>
          <input id="conn-desc" value={form.description} onChange={e => setField('description', e.target.value)} placeholder="Product catalog and orders" />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? <span className="spinner" aria-hidden="true" /> : 'Save connection'}
          </button>
          <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </div>
  )
}
