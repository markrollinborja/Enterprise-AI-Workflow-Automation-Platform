import { API_BASE_URL } from './client'

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface CurrentUser {
  id: string
  email: string
  full_name: string
  role: string
  is_active: boolean
}

export interface AuthModeResponse {
  mode: 'local' | 'oidc'
}

/**
 * Called by LoginForm before rendering anything — it needs to know
 * whether to show a password form or a "Continue with Keycloak" redirect
 * before the person has any credentials to offer. Public and
 * unauthenticated on the backend for exactly that reason.
 */
export async function fetchAuthMode(): Promise<AuthModeResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/mode`)
  if (!response.ok) {
    throw new Error('Failed to determine authentication mode')
  }
  return response.json() as Promise<AuthModeResponse>
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

export async function login(payload: LoginRequest): Promise<TokenResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Login failed')
  }
  return response.json() as Promise<TokenResponse>
}

export async function fetchCurrentUser(token: string): Promise<CurrentUser> {
  const response = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new Error('Failed to fetch current user')
  }
  return response.json() as Promise<CurrentUser>
}
