import { useState, useEffect, useCallback } from 'react'
import { listConnections, runQuery, ApiError } from '../api'
import type { ConnectionOut, QueryResponse } from '../types'

export default function Query() {
  const [connections, setConnections] = useState<ConnectionOut[]>([])
  const [connId, setConnId] = useState('')
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [result, setResult] = useState<QueryResponse | null>(null)

  const load = useCallback(async () => {
    try {
      const conns = await listConnections()
      setConnections(conns)
      setLoadError('')
      if (conns.length > 0 && conns[0]) setConnId(conns[0].id)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.detail : 'Failed to load connections')
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!connId || !question.trim()) return
    setError('')
    setResult(null)
    setBusy(true)
    try {
      setResult(await runQuery(connId, question))
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Query failed')
    } finally {
      setBusy(false)
    }
  }

  const columns = result?.result.length
    ? Object.keys(result.result[0] ?? {} as Record<string, unknown>)
    : []

  return (
    <div>
      <div className="section-header">
        <span className="section-title">Natural Language Query</span>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <form className="form" onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="query-connection">Connection</label>
              <select id="query-connection" value={connId} onChange={e => setConnId(e.target.value)}>
                {connections.map(c => (
                  <option key={c.id} value={c.id}>{c.name} ({c.db_type})</option>
                ))}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="query-question">Question</label>
            <textarea
              id="query-question"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              placeholder="e.g. Show all products ordered by price descending"
              style={{ minHeight: 64 }}
              required
            />
          </div>
          <div>
            <button type="submit" className="btn-primary" disabled={busy || !connId}>
              {busy ? <><span className="spinner" aria-hidden="true" style={{ marginRight: 8 }} />Running…</> : 'Run query'}
            </button>
          </div>
        </form>
      </div>

      {loadError && <div className="alert alert-error">{loadError}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {result && (
        <>
          {result.summary && (
            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-title">Summary</div>
              <p style={{ lineHeight: 1.6 }}>{result.summary}</p>
            </div>
          )}

          {result.sql_generated && (
            <div className="card" style={{ marginBottom: 12 }}>
              <div className="card-title">Generated SQL</div>
              <pre>{result.sql_generated}</pre>
            </div>
          )}

          <div className="card">
            <div className="card-title">Results</div>
            <p className="results-count">{result.result.length} row{result.result.length !== 1 ? 's' : ''}</p>
            {result.result.length === 0 ? (
              <div className="empty">Query returned no rows.</div>
            ) : (
              <div className="results-scroll">
                <table>
                  <thead>
                    <tr>{columns.map(col => <th key={col}>{col}</th>)}</tr>
                  </thead>
                  <tbody>
                    {result.result.map((row, i) => (
                      <tr key={i}>
                        {columns.map(col => (
                          <td key={col} style={{ fontSize: 12 }}>
                            {row[col] === null || row[col] === undefined
                              ? <span style={{ color: 'var(--text-muted)' }}>NULL</span>
                              : typeof row[col] === 'object'
                                ? JSON.stringify(row[col])
                                : String(row[col])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
