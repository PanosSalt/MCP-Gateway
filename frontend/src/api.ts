import type {
  Token,
  TenantCreate,
  TenantOut,
  UserOut,
  UserCreate,
  UserRoleUpdate,
  ConnectionCreate,
  ConnectionUpdate,
  ConnectionOut,
  QueryResponse,
  AuditLogEntry,
  EntraConfigCreate,
  EntraConfigOut,
  APIKeyCreate,
  APIKeyCreatedResponse,
  APIKeyResponse,
  ToolInfo,
} from './types'

import { REQUEST_TIMEOUT_MS, MAX_RETRIES, RETRY_BASE_MS } from './constants'

const TOKEN_KEY = 'mgw_token'

// sessionStorage is scoped to the tab and cleared on close, limiting the
// window of exposure compared to localStorage which persists indefinitely.
export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}

// Decode JWT payload without verification (UI-only, server always re-validates)
export function decodeTokenPayload(token: string): Record<string, unknown> {
  try {
    const base64 = token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64)) as Record<string, unknown>
  } catch {
    return {}
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
  }
}

export class TimeoutError extends ApiError {
  constructor() { super(0, 'Request timed out. Check your connection and try again.') }
}

export class NetworkError extends ApiError {
  constructor() { super(0, 'Network error. Check your connection and try again.') }
}

export function getErrorMessage(err: unknown, fallback = 'An error occurred'): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return fallback
}

// ── Stale-while-revalidate cache ──────────────────────────────────────────────
// Used by list endpoints whose data changes infrequently (connections, users,
// tools, API keys).  A tab switch (unmount → remount) returns the cached value
// immediately and revalidates in the background after the stale window expires.

const _cache = new Map<string, { data: unknown; ts: number }>()
const _STALE_MS = 30_000

export async function cachedFetch<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const hit = _cache.get(key)
  if (hit) {
    if (Date.now() - hit.ts < _STALE_MS) return hit.data as T
    // Stale: serve immediately and refresh in the background.
    fetcher().then(data => _cache.set(key, { data, ts: Date.now() })).catch(() => {})
    return hit.data as T
  }
  const data = await fetcher()
  _cache.set(key, { data, ts: Date.now() })
  return data
}

export function invalidateCache(key: string): void {
  _cache.delete(key)
}


async function requestWithRetry<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const isIdempotent = method === 'GET' || method === 'HEAD' || method === 'OPTIONS'
  let lastError: unknown
  const attempts = isIdempotent ? MAX_RETRIES : 1
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await request<T>(path, options, authenticated)
    } catch (err) {
      lastError = err
      if (err instanceof ApiError && err.status > 0 && err.status < 500) throw err
      if (attempt < attempts - 1) {
        await new Promise(r => setTimeout(r, RETRY_BASE_MS * 2 ** attempt))
      }
    }
  }
  throw lastError
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (authenticated) {
    const token = getToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  let res: Response
  try {
    res = await fetch(path, { ...options, headers, signal: controller.signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new TimeoutError()
    }
    if (err instanceof TypeError) {
      throw new NetworkError()
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch { /* ignore */ }
    if (res.status === 401) clearToken()
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(email: string, password: string): Promise<Token> {
  return request<Token>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }, false)
}


export async function getEntraConfig(): Promise<EntraConfigOut> {
  return requestWithRetry<EntraConfigOut>('/auth/entra/config')
}

export async function saveEntraConfig(payload: EntraConfigCreate): Promise<EntraConfigOut> {
  return request<EntraConfigOut>('/auth/entra/config', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteEntraConfig(): Promise<void> {
  return request<void>('/auth/entra/config', { method: 'DELETE' })
}

// ── Tenants ───────────────────────────────────────────────────────────────────

export async function createTenant(payload: TenantCreate): Promise<TenantOut> {
  return request<TenantOut>('/tenants/', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, false)
}

export async function getMyTenant(): Promise<TenantOut> {
  return requestWithRetry<TenantOut>('/tenants/me')
}

// ── Users ─────────────────────────────────────────────────────────────────────

export async function listUsers(skip = 0, limit = 50): Promise<UserOut[]> {
  return requestWithRetry<UserOut[]>(`/tenants/users?skip=${skip}&limit=${limit}`)
}

export async function createUser(payload: UserCreate): Promise<UserOut> {
  return request<UserOut>('/tenants/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateUserRole(userId: string, payload: UserRoleUpdate): Promise<UserOut> {
  return request<UserOut>(`/tenants/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteUser(userId: string): Promise<void> {
  return request<void>(`/tenants/users/${userId}`, { method: 'DELETE' })
}

// ── Connections ───────────────────────────────────────────────────────────────

export async function listConnections(skip = 0, limit = 50): Promise<ConnectionOut[]> {
  return requestWithRetry<ConnectionOut[]>(`/connections/?skip=${skip}&limit=${limit}`)
}

export async function createConnection(payload: ConnectionCreate): Promise<ConnectionOut> {
  return request<ConnectionOut>('/connections/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateConnection(connectionId: string, payload: ConnectionUpdate): Promise<ConnectionOut> {
  return request<ConnectionOut>(`/connections/${connectionId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteConnection(connectionId: string): Promise<void> {
  return request<void>(`/connections/${connectionId}`, { method: 'DELETE' })
}

// ── Query ─────────────────────────────────────────────────────────────────────

export async function runQuery(connectionId: string, question: string): Promise<QueryResponse> {
  return request<QueryResponse>('/query/', {
    method: 'POST',
    body: JSON.stringify({ connection_id: connectionId, question }),
  })
}

export async function getAuditLogs(skip = 0, limit = 50, eventPrefix?: string): Promise<AuditLogEntry[]> {
  let url = `/audit-logs/?skip=${skip}&limit=${limit}`
  if (eventPrefix) url += `&event_prefix=${encodeURIComponent(eventPrefix)}`
  return requestWithRetry<AuditLogEntry[]>(url)
}

export async function getQueryHistory(skip = 0, limit = 50): Promise<AuditLogEntry[]> {
  return requestWithRetry<AuditLogEntry[]>(`/query/history?skip=${skip}&limit=${limit}`)
}

// ── API Keys ──────────────────────────────────────────────────────────────────

export async function listApiKeys(): Promise<APIKeyResponse[]> {
  return requestWithRetry<APIKeyResponse[]>('/api-keys')
}

export async function createApiKey(payload: APIKeyCreate): Promise<APIKeyCreatedResponse> {
  return request<APIKeyCreatedResponse>('/api-keys', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function revokeApiKey(keyId: string): Promise<void> {
  return request<void>(`/api-keys/${keyId}`, { method: 'DELETE' })
}

// ── Tools ────────────────────────────────────────────────────────────────────

export async function listTools(): Promise<ToolInfo[]> {
  return requestWithRetry<ToolInfo[]>('/tools/')
}

export async function exchangeSsoCode(code: string): Promise<Token> {
  return request<Token>(`/auth/entra/exchange?code=${encodeURIComponent(code)}`)
}

export async function updateToolRole(toolName: string, minRole: string | null): Promise<void> {
  return request<void>(`/tools/${encodeURIComponent(toolName)}`, {
    method: 'PATCH',
    body: JSON.stringify({ min_role: minRole }),
  })
}
