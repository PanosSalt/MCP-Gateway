import { memo } from 'react'
import { useAuth } from '../App'

export default memo(function Dashboard() {
  const { auth } = useAuth()
  if (!auth) return null
  return (
    <>
      <span>
        <span style={{ fontWeight: 600 }}>{auth.email || 'Unknown'}</span>
      </span>
      <span className={`badge badge-${auth.role}`}>{auth.role}</span>
      <span style={{ color: 'var(--text-muted)' }}>{auth.tenant.name}</span>
    </>
  )
})
