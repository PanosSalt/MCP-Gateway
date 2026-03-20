import { updateConnection, getErrorMessage } from '../api'
import type { ConnectionOut, ConnectionUpdate, DBType, MinRole } from '../types'
import { useForm } from '../hooks/useForm'

const DB_TYPES: DBType[] = ['postgres', 'mysql', 'sqlite', 'mssql']
const MIN_ROLES: MinRole[] = ['viewer', 'analyst', 'admin']

interface Props {
  connection: ConnectionOut
  colSpan: number
  onUpdated: (conn: ConnectionOut) => void
  onCancel: () => void
}

export default function ConnectionEditRow({ connection: c, colSpan, onUpdated, onCancel }: Props) {
  const { form, setField, busy, setBusy, error, setError } = useForm({
    name: c.name,
    db_type: c.db_type,
    connection_string: '',
    description: c.description ?? '',
    min_role: c.min_role,
  })

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const payload: ConnectionUpdate = {
        name: form.name,
        db_type: form.db_type,
        description: form.description,
        min_role: form.min_role,
      }
      if (form.connection_string) payload.connection_string = form.connection_string
      const updated = await updateConnection(c.id, payload)
      onUpdated(updated)
    } catch (err) {
      setError(getErrorMessage(err, 'Update failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr>
      <td colSpan={colSpan}>
        {error && <div className="alert alert-error" style={{ marginBottom: 8 }}>{error}</div>}
        <form className="form" onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="edit-name">Name</label>
              <input id="edit-name" value={form.name} required onChange={e => setField('name', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="edit-type">Database type</label>
              <select id="edit-type" value={form.db_type} onChange={e => setField('db_type', e.target.value as DBType)}>
                {DB_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="edit-role">Min role</label>
              <select id="edit-role" value={form.min_role} onChange={e => setField('min_role', e.target.value as MinRole)}>
                {MIN_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="edit-string">Connection string (leave blank to keep current)</label>
            <input
              id="edit-string"
              value={form.connection_string}
              onChange={e => setField('connection_string', e.target.value)}
              placeholder="Only fill to change credentials"
            />
          </div>
          <div className="field">
            <label htmlFor="edit-desc">Description</label>
            <input id="edit-desc" value={form.description} onChange={e => setField('description', e.target.value)} />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? <span className="spinner" aria-hidden="true" /> : 'Save'}
            </button>
            <button type="button" className="btn-ghost" onClick={onCancel}>Cancel</button>
          </div>
        </form>
      </td>
    </tr>
  )
}
