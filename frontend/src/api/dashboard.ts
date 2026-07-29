import { API_BASE_URL } from './client'

export interface DashboardSummaryResponse {
  active_workflows: number
  pending_approvals: number
  failed_workflows: number
  completed_workflows: number
  avg_completion_seconds: number | null
  requests_by_type: Record<string, number>
  requests_by_department: Record<string, number>
}

/**
 * Mirrors backend/app/schemas/dashboard.py's WorkflowInstanceSummaryResponse.
 * The three failed_* fields are only ever populated when status === "failed"
 * — see that schema's docstring for why the Failed Workflows page (Phase
 * 12c) reuses this same shape via ?status=failed instead of a second type.
 */
export interface WorkflowInstanceSummaryResponse {
  id: string
  workflow_key: string
  workflow_name: string
  employee_name: string | null
  initiated_by_name: string | null
  status: string
  current_step_key: string | null
  started_at: string | null
  updated_at: string
  completed_at: string | null
  failed_step_key: string | null
  failure_reason: string | null
  failed_attempt_count: number | null
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * Every /dashboard/*, /workflow-instances*, and /audit-log route is a plain
 * authenticated GET with the same error-unwrapping — one helper here rather
 * than repeating the same six lines in every fetch function in this file.
 */
async function getJson<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? `Request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchDashboardSummary(token: string): Promise<DashboardSummaryResponse> {
  return getJson<DashboardSummaryResponse>('/dashboard/summary', token)
}

export function fetchWorkflowInstances(
  token: string,
  status?: string,
): Promise<WorkflowInstanceSummaryResponse[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return getJson<WorkflowInstanceSummaryResponse[]>(`/workflow-instances${query}`, token)
}
