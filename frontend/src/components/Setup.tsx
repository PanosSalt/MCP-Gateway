import { useForm } from '../hooks/useForm'
import { createTenant, ApiError } from '../api'

interface Props {
  onDone: () => void
}

const SETUP_INITIAL = { name: '', slug: '', admin_email: '', admin_password: '' }

export default function Setup({ onDone }: Props) {
  const { form, setForm, busy, setBusy, error, setError, success, setSuccess } = useForm(SETUP_INITIAL)

  function set(field: keyof typeof form, value: string) {
    setForm(f => ({ ...f, [field]: value }))
    // Auto-generate slug from name
    if (field === 'name') {
      setForm(f => ({
        ...f,
        name: value,
        slug: value.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, ''),
      }))
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')
    setBusy(true)
    try {
      const tenant = await createTenant(form)
      setSuccess(`Tenant "${tenant.name}" created. You can now sign in.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Failed to create tenant')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-box">
        <h1>Create Tenant</h1>
        <p className="subtitle">One-time setup — creates your organisation and admin account</p>

        {error   && <div className="alert alert-error">{error}</div>}
        {success && (
          <div className="alert alert-success">
            {success}{' '}
            <button className="auth-link" onClick={onDone}>Sign in →</button>
          </div>
        )}

        {!success && (
          <form className="form" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="setup-name">Organisation name</label>
              <input
                id="setup-name"
                value={form.name} required autoFocus
                onChange={e => set('name', e.target.value)}
                placeholder="Acme Corp"
              />
            </div>
            <div className="field">
              <label htmlFor="setup-slug">Slug (URL-safe identifier)</label>
              <input
                id="setup-slug"
                value={form.slug} required
                onChange={e => set('slug', e.target.value)}
                placeholder="acme-corp"
                pattern="[a-z0-9\-]+"
                title="Lowercase letters, numbers, and hyphens only"
              />
            </div>
            <div className="field">
              <label htmlFor="setup-admin-email">Admin email</label>
              <input
                id="setup-admin-email"
                type="email" value={form.admin_email} required
                onChange={e => set('admin_email', e.target.value)}
                placeholder="admin@acme.com"
              />
            </div>
            <div className="field">
              <label htmlFor="setup-admin-password">Admin password</label>
              <input
                id="setup-admin-password"
                type="password" value={form.admin_password} required
                onChange={e => set('admin_password', e.target.value)}
                minLength={12}
              />
            </div>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? <span className="spinner" aria-hidden="true" /> : 'Create tenant'}
            </button>
          </form>
        )}

        <div className="auth-divider">already have a tenant?</div>
        <button className="auth-link" onClick={onDone}>← Sign in</button>
      </div>
    </div>
  )
}
