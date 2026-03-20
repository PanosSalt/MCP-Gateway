import type { MinRole } from '../types'

const MIN_ROLES: MinRole[] = ['viewer', 'analyst', 'admin']

interface Props {
  defaultMinRole: MinRole
  effectiveMinRole: MinRole
  isOverridden: boolean
  pendingValue: string | undefined
  saving: boolean
  onChange: (value: string) => void
  onSave: () => void
}

export default function ToolRoleOverride({
  defaultMinRole,
  effectiveMinRole,
  isOverridden,
  pendingValue,
  saving,
  onChange,
  onSave,
}: Props) {
  const selectValue = pendingValue ?? (isOverridden ? effectiveMinRole : '')

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <select
        value={selectValue}
        onChange={e => onChange(e.target.value)}
        disabled={saving}
        style={{ fontSize: 12, padding: '2px 6px' }}
      >
        <option value="">Default ({defaultMinRole})</option>
        {MIN_ROLES.map(r => (
          <option key={r} value={r}>{r}</option>
        ))}
      </select>
      {pendingValue !== undefined && !saving && (
        <button
          className="btn btn-primary"
          onClick={onSave}
          style={{ fontSize: 11, padding: '2px 10px', lineHeight: '18px' }}
        >
          Update
        </button>
      )}
      {saving && <span className="spinner" aria-hidden="true" style={{ width: 14, height: 14 }} />}
    </div>
  )
}
