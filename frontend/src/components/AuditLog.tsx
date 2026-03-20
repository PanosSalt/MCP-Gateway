import { useState, useEffect, useCallback, useRef } from 'react'
import { getAuditLogs, getErrorMessage } from '../api'
import type { AuditLogEntry, AuditMetadata } from '../types'
import AuditLogDetail from './AuditLogDetail'
import AuditLogFilters from './AuditLogFilters'

const PAGE_SIZE = 50

const COL_PCT = ['14%', '19%', '28%', '26%', '13%']

function fmtTime(s: string) {
  const d = new Date(s)
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function truncate(s: string, max: number) {
  return s.length > max ? s.slice(0, max) + '\u2026' : s
}

function eventBadge(event: string) {
  if (event.includes('success') || event === 'tool.execute_sql' || event === 'login.success')
    return <span className="badge badge-admin">{event}</span>
  if (event.includes('failure') || event.includes('error') || event.includes('rejected'))
    return <span className="badge badge-revoked">{event}</span>
  return <span className="badge badge-analyst">{event}</span>
}

function summarize(e: AuditLogEntry): string {
  const m = (e.metadata ?? {}) as AuditMetadata
  const parts: string[] = []

  if (m.question) parts.push(m.question)
  if (m.sql_preview) parts.push(m.sql_preview)
  if (m.sql_generated) parts.push(m.sql_generated)
  if (m.error) parts.push(`error: ${m.error}`)
  if (m.reason) parts.push(m.reason)
  if (m.email) parts.push(m.email)
  if (m.name) parts.push(m.name)
  if (m.slug) parts.push(`slug: ${m.slug}`)
  if (m.new_role) parts.push(`role: ${m.new_role}`)

  return parts.join(' | ') || '--'
}

function resolveEmail(e: AuditLogEntry): string {
  if (e.user_email) return e.user_email
  const meta = (e.metadata ?? {}) as AuditMetadata
  if (meta.user_email) return meta.user_email
  if (e.user_id) return truncate(e.user_id, 8)
  return '--'
}

function useColumnResize() {
  const [widths, setWidths] = useState<number[] | null>(null)
  const tableRef = useRef<HTMLTableElement>(null)
  const drag = useRef<{ col: number; startX: number; startW: number } | null>(null)

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const d = drag.current
      if (!d) return
      const w = Math.max(60, d.startW + (e.clientX - d.startX))
      setWidths((prev: number[] | null) => {
        if (!prev) return prev
        const next = [...prev]; next[d.col] = w; return next
      })
    }
    function onUp() {
      drag.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    return () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
  }, [])

  function onStart(col: number, e: React.MouseEvent<HTMLSpanElement>) {
    e.preventDefault()
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    if (!widths && tableRef.current) {
      const ths = tableRef.current.querySelectorAll('thead th')
      const px = Array.from(ths as NodeListOf<Element>).map(th => th.getBoundingClientRect().width)
      setWidths(px)
      drag.current = { col, startX: e.clientX, startW: px[col] ?? 0 }
    } else if (widths) {
      drag.current = { col, startX: e.clientX, startW: widths[col] ?? 0 }
    }
  }

  return { widths, tableRef, onStart }
}

const GRIP: { [key: string]: string | number } = {
  position: 'absolute', right: -2, top: 0, bottom: 0, width: 5,
  cursor: 'col-resize', zIndex: 1,
}

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  const headers = ['Time', 'Event', 'Details', 'User', 'IP']
  const { widths, tableRef, onStart } = useColumnResize()

  useEffect(() => {
    if (expandedId && !entries.find((x: AuditLogEntry) => x.id === expandedId)) {
      setExpandedId(null)
    }
  }, [entries, expandedId])

  const load = useCallback(async (prefix: string) => {
    setLoading(true)
    setError('')
    setExpandedId(null)
    try {
      const data = await getAuditLogs(0, PAGE_SIZE, prefix || undefined)
      setEntries(data)
      setHasMore(data.length === PAGE_SIZE)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load audit logs'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(filter) }, [load, filter])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const data = await getAuditLogs(entries.length, PAGE_SIZE, filter || undefined)
      setEntries((prev: AuditLogEntry[]) => [...prev, ...data])
      setHasMore(data.length === PAGE_SIZE)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load more'))
    } finally {
      setLoadingMore(false)
    }
  }

  const cellClip = { overflow: 'hidden' as const, textOverflow: 'ellipsis' as const, whiteSpace: 'nowrap' as const }

  return (
    <div>
      <div className="section-header">
        <span className="section-title">Audit Log</span>
        <AuditLogFilters
          filter={filter}
          loading={loading}
          onChange={setFilter}
          onRefresh={() => load(filter)}
        />
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card" style={{ overflowX: 'auto' }}>
        {loading ? (
          <table><tbody>{Array.from({ length: 5 }, (_, i) => (
            <tr key={i}>{Array.from({ length: 5 }, (_, j) => <td key={j}><div className="skeleton-line" /></td>)}</tr>
          ))}</tbody></table>
        ) : entries.length === 0 ? (
          <div className="empty">No audit log entries found.</div>
        ) : (
          <>
            <table
              ref={tableRef}
              style={{ width: '100%', tableLayout: 'fixed', borderCollapse: 'collapse' }}
            >
              <colgroup>
                {widths
                  ? widths.map((w: number, i: number) => <col key={i} style={{ width: w }} />)
                  : COL_PCT.map((p, i) => <col key={i} style={{ width: p }} />)
                }
              </colgroup>
              <thead>
                <tr>
                  {headers.map((h, i) => (
                    <th key={h} style={{ position: 'relative', ...cellClip }}>
                      {h}
                      {i < headers.length - 1 && (
                        <span style={GRIP} onMouseDown={e => onStart(i, e)} aria-hidden="true" />
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entries.map(e => {
                  const expanded = expandedId === e.id
                  return (
                    <tr
                      key={e.id}
                      onClick={() => setExpandedId((prev: string | null) => prev === e.id ? null : e.id)}
                      style={{ cursor: 'pointer', background: expanded ? 'var(--bg-hover, #f9fafb)' : undefined }}
                    >
                      <td style={{ fontSize: 12, color: 'var(--text-muted)', ...cellClip }}>
                        {fmtTime(e.created_at)}
                      </td>
                      <td style={cellClip}>
                        {eventBadge(e.event)}
                      </td>
                      <td style={{ fontSize: 12, ...cellClip }} title={summarize(e)}>
                        {summarize(e)}
                      </td>
                      <td style={{ fontSize: 12, color: 'var(--text-muted)', ...cellClip }} title={resolveEmail(e)}>
                        {resolveEmail(e)}
                      </td>
                      <td style={{ fontSize: 12, color: 'var(--text-muted)', ...cellClip }}>
                        {e.ip_address ?? '--'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>

            {expandedId && (() => {
              const e = entries.find((x: AuditLogEntry) => x.id === expandedId)
              if (!e) return null
              return <AuditLogDetail entry={e} />
            })()}

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
    </div>
  )
}
