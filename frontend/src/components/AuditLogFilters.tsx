interface FilterOption {
  label: string
  prefix: string
}

export const AUDIT_FILTERS: FilterOption[] = [
  { label: 'All events',  prefix: '' },
  { label: 'Queries',     prefix: 'query' },
  { label: 'MCP Tools',   prefix: 'tool' },
  { label: 'Auth',        prefix: 'login,oauth' },
  { label: 'Connections', prefix: 'connection' },
  { label: 'Users',       prefix: 'user,tenant' },
  { label: 'API Keys',    prefix: 'key' },
]

interface Props {
  filter: string
  loading: boolean
  onChange: (prefix: string) => void
  onRefresh: () => void
}

export default function AuditLogFilters({ filter, loading, onChange, onRefresh }: Props) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <select
        value={filter}
        onChange={e => onChange(e.target.value)}
        style={{ fontSize: 13, padding: '4px 8px' }}
      >
        {AUDIT_FILTERS.map(f => (
          <option key={f.prefix} value={f.prefix}>{f.label}</option>
        ))}
      </select>
      <button className="btn-ghost" onClick={onRefresh} disabled={loading}>
        Refresh
      </button>
    </div>
  )
}
