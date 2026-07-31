import { API_BASE_URL } from './client'

export interface ApplicationResponse {
  id: string
  name: string
  description: string
  risk_level: string
  created_at: string
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * GET /applications is visible to any authenticated user — you need to see
 * what's requestable before you can request it. No create/update endpoint
 * exists (the catalog is seed-managed, see app/schemas/application.py's
 * docstring), so there's no corresponding write call here.
 */
export async function fetchApplications(token: string): Promise<ApplicationResponse[]> {
  const response = await fetch(`${API_BASE_URL}/applications`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to load applications')
  }
  return response.json() as Promise<ApplicationResponse[]>
}
