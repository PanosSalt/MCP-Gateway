import { useState, useEffect, useCallback } from 'react'
import { listTools, updateToolRole, getErrorMessage, cachedFetch, invalidateCache } from '../api'
import { useAuth } from '../App'
import type { ToolInfo } from '../types'
import ToolGroup from './ToolGroup'

interface GroupedTools {
  connectionTools: Map<string, { connectionName: string; tools: ToolInfo[] }>
  generalTools: ToolInfo[]
}

function groupTools(tools: ToolInfo[]): GroupedTools {
  const connectionTools = new Map<string, { connectionName: string; tools: ToolInfo[] }>()
  const generalTools: ToolInfo[] = []

  for (const t of tools) {
    if (t.connection_id) {
      const existing = connectionTools.get(t.connection_id)
      if (existing) {
        existing.tools.push(t)
      } else {
        connectionTools.set(t.connection_id, {
          connectionName: t.connection_name ?? t.connection_id,
          tools: [t],
        })
      }
    } else {
      generalTools.push(t)
    }
  }
  return { connectionTools, generalTools }
}

export default function Tools() {
  const { auth } = useAuth()
  const isAdmin = auth?.role === 'admin'

  const [tools, setTools] = useState<ToolInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState<string | null>(null)
  const [pending, setPending] = useState<Record<string, string>>({})
  const [successMsg, setSuccessMsg] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTools(await cachedFetch('tools', listTools))
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to load tools'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  function handleDropdownChange(toolName: string, newValue: string) {
    setPending(prev => ({ ...prev, [toolName]: newValue }))
    setSuccessMsg('')
  }

  async function handleSave(toolName: string) {
    const newValue = pending[toolName]
    if (newValue === undefined) return
    setSaving(toolName)
    setError('')
    setSuccessMsg('')
    try {
      const minRole = newValue === '' ? null : newValue
      await updateToolRole(toolName, minRole)
      invalidateCache('tools')
      setPending(prev => {
        const next = { ...prev }
        delete next[toolName]
        return next
      })
      await load()
      setSuccessMsg(`Updated role for ${toolName}`)
      setTimeout(() => setSuccessMsg(''), 3000)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to update role'))
    } finally {
      setSaving(null)
    }
  }

  const { connectionTools, generalTools } = groupTools(tools)

  return (
    <div>
      <div className="section-header">
        <span className="section-title">MCP Tools</span>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {successMsg && <div className="alert alert-success">{successMsg}</div>}

      <div className="card">
        {loading ? (
          <table><tbody>{Array.from({ length: 5 }, (_, i) => (
            <tr key={i}>{Array.from({ length: 6 }, (_, j) => <td key={j}><div className="skeleton-line" /></td>)}</tr>
          ))}</tbody></table>
        ) : tools.length === 0 ? (
          <div className="empty">No tools available. Add a database connection to generate tools.</div>
        ) : (
          <>
            {Array.from(connectionTools.entries()).map(([connId, { connectionName, tools: connTools }]) => (
              <ToolGroup
                key={connId}
                title={`Connection: ${connectionName}`}
                tools={connTools}
                isAdmin={isAdmin}
                saving={saving}
                pending={pending}
                onDropdownChange={handleDropdownChange}
                onSave={handleSave}
              />
            ))}
            <ToolGroup
              title="General Tools"
              tools={generalTools}
              isAdmin={isAdmin}
              saving={saving}
              pending={pending}
              onDropdownChange={handleDropdownChange}
              onSave={handleSave}
            />
          </>
        )}
      </div>

      {!loading && tools.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: 0 }}>
            <strong>Default role</strong> is set by the tool provider.
            {isAdmin
              ? ' Use the Override role dropdown to customize access. Select "Default" to reset.'
              : ' Overridden roles are marked with *.'}
            {' '}<strong>Accessible</strong> indicates whether your current role grants access.
          </p>
        </div>
      )}
    </div>
  )
}
