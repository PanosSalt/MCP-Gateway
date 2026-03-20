import type { AuditLogEntry, AuditMetadata } from '../types'

interface Props {
  entry: AuditLogEntry
}

export default function AuditLogDetail({ entry: e }: Props) {
  const meta = (e.metadata ?? {}) as AuditMetadata
  const metaKeys = Object.keys(meta)

  return (
    <div style={{
      padding: '12px 16px',
      borderTop: '1px solid var(--border)',
      fontSize: 13,
      display: 'grid',
      gridTemplateColumns: '140px 1fr',
      gap: '6px 12px',
    }}>
      <span style={{ fontWeight: 600 }}>Event</span>
      <span>{e.event}</span>

      <span style={{ fontWeight: 600 }}>User</span>
      <span>
        {e.user_email ?? (typeof meta.user_email === 'string' ? meta.user_email : null) ?? '--'}
        {e.user_id ? <code style={{ fontSize: 11, marginLeft: 8, color: 'var(--text-muted)' }}>{e.user_id}</code> : null}
      </span>

      <span style={{ fontWeight: 600 }}>IP Address</span>
      <span>{e.ip_address ?? '--'}</span>

      <span style={{ fontWeight: 600 }}>Timestamp</span>
      <span>{new Date(e.created_at).toLocaleString()}</span>

      {metaKeys.map(key => (
        <span key={key} style={{ display: 'contents' }}>
          <span style={{ fontWeight: 600 }}>{key}</span>
          <code style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {typeof meta[key] === 'object' ? JSON.stringify(meta[key]) : String(meta[key])}
          </code>
        </span>
      ))}
    </div>
  )
}
