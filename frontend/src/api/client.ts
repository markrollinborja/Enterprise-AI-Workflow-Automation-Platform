export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface HealthResponse {
  status: string
}

/**
 * Smoke-test call used by the Phase 2 landing page to prove the frontend can
 * actually reach the backend through Docker Compose / local dev. Real API
 * calls (employees, workflows, approvals...) get their own modules here from
 * Phase 4 onward.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`)
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json() as Promise<HealthResponse>
}
