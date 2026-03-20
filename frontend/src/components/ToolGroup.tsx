import type { ToolInfo, MinRole } from '../types'
import ToolRoleOverride from './ToolRoleOverride'

const TYPE_LABEL: Record<string, string> = {
  schema: 'Schema',
  execute: 'Execute',
  custom: 'Custom',
  utility: 'Utility',
}

const ROLE_BADGE: Record<MinRole, string> = {
  viewer: 'badge-viewer',
  analyst: 'badge-analyst',
  admin: 'badge-admin',
}

interface Props {
  title: string
  tools: ToolInfo[]
  isAdmin: boolean
  saving: string | null
  pending: Record<string, string>
  onDropdownChange: (toolName: string, value: string) => void
  onSave: (toolName: string) => void
}

export default function ToolGroup({ title, tools, isAdmin, saving, pending, onDropdownChange, onSave }: Props) {
  if (tools.length === 0) return null

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: 'var(--text-muted)' }}>
        {title}
      </div>
      <table>
        <thead>
          <tr>
            <th>Tool</th>
            <th>Type</th>
            <th>Description</th>
            <th>Default role</th>
            <th>{isAdmin ? 'Override role' : 'Effective role'}</th>
            <th>Accessible</th>
          </tr>
        </thead>
        <tbody>
          {tools.map(t => {
            const isOverridden = t.effective_min_role !== t.default_min_role
            return (
              <tr key={t.tool_name}>
                <td><code style={{ fontSize: 12 }}>{t.tool_name}</code></td>
                <td>
                  <span className="badge" style={{ fontSize: 11 }}>
                    {TYPE_LABEL[t.tool_type] ?? t.tool_type}
                  </span>
                </td>
                <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {t.description.length > 80 ? t.description.slice(0, 80) + '…' : t.description}
                </td>
                <td>
                  <span className={`badge ${ROLE_BADGE[t.default_min_role]}`} style={{ fontSize: 11 }}>
                    {t.default_min_role}
                  </span>
                </td>
                <td>
                  {isAdmin ? (
                    <ToolRoleOverride
                      defaultMinRole={t.default_min_role}
                      effectiveMinRole={t.effective_min_role}
                      isOverridden={isOverridden}
                      pendingValue={pending[t.tool_name]}
                      saving={saving === t.tool_name}
                      onChange={v => onDropdownChange(t.tool_name, v)}
                      onSave={() => onSave(t.tool_name)}
                    />
                  ) : (
                    <span className={`badge ${ROLE_BADGE[t.effective_min_role]}`} style={{ fontSize: 11 }}>
                      {t.effective_min_role}
                      {isOverridden && ' *'}
                    </span>
                  )}
                </td>
                <td>
                  {t.accessible
                    ? <span style={{ fontSize: 12, color: 'var(--success)' }}>Yes</span>
                    : <span style={{ fontSize: 12, color: 'var(--danger, #ef4444)' }}>No</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
