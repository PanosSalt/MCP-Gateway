// Mirrors every Pydantic schema in app/schemas/__init__.py

export type Role = 'admin' | 'analyst' | 'viewer'
export type DBType = 'postgres' | 'mysql' | 'sqlite' | 'mssql'
export type AuthProvider = 'local' | 'entra'
export type MinRole = 'viewer' | 'analyst' | 'admin'

// Auth
export interface Token {
  access_token: string
  token_type: string
}

// Tenants
export interface TenantCreate {
  name: string
  slug: string
  admin_email: string
  admin_password: string
}

export interface TenantOut {
  id: string
  name: string
  slug: string
  is_active: boolean
  created_at: string
}

// Users
export interface UserOut {
  id: string
  email: string
  role: Role
  is_active: boolean
  auth_provider: AuthProvider
}

export interface UserCreate {
  email: string
  password: string
  role: Role
}

export interface UserRoleUpdate {
  role: Role
}

// Connections
export interface ConnectionCreate {
  name: string
  db_type: DBType
  connection_string: string
  description?: string
  min_role?: MinRole
}

export interface ConnectionUpdate {
  name?: string
  db_type?: DBType
  connection_string?: string
  description?: string
  min_role?: MinRole
}

export interface ConnectionOut {
  id: string
  name: string
  db_type: DBType
  description: string | null
  is_active: boolean
  created_at: string
  min_role: MinRole
}

// Query
export interface QueryResponse {
  question: string
  sql_generated: string | null
  result: Record<string, unknown>[]
  summary: string
}

export interface AuditMetadata {
  question?: string
  sql_generated?: string
  sql_preview?: string
  error?: string
  reason?: string
  email?: string
  user_email?: string
  new_role?: string
  name?: string
  slug?: string
  connection_id?: string
  path?: string
  [key: string]: unknown
}

export interface AuditLogEntry {
  id: string
  user_id: string | null
  user_email: string | null
  event: string
  ip_address: string | null
  metadata: AuditMetadata | null
  created_at: string
}

// Entra SSO config
export interface EntraConfigCreate {
  entra_tenant_id: string
  client_id: string
  client_secret?: string  // omit or leave blank to keep the existing secret on update
  admin_group_id?: string
  analyst_group_id?: string
  viewer_group_id?: string
}

export interface EntraConfigOut {
  entra_tenant_id: string
  client_id: string
  admin_group_id: string | null
  analyst_group_id: string | null
  viewer_group_id: string | null
}

// API Keys
export interface APIKeyCreate {
  name: string
  expires_at?: string
}

export interface APIKeyCreatedResponse {
  id: string
  name: string
  prefix: string
  raw_key: string
  created_at: string
}

export interface APIKeyResponse {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
  expires_at: string | null
}

// Tools
export interface ToolInfo {
  tool_name: string
  tool_type: string
  description: string
  connection_id: string | null
  connection_name: string | null
  default_min_role: MinRole
  effective_min_role: MinRole
  accessible: boolean
}

// Auth context user state (decoded from /tenants/me)
export interface CurrentUser {
  tenant: TenantOut
  // role decoded from JWT stored in localStorage for UI decisions
  role: Role
  email: string
}
