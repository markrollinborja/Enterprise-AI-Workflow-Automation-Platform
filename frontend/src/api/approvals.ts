import { API_BASE_URL } from './client'

export interface ApprovalRequestResponse {
  id: string
  workflow_instance_id: string
  workflow_name: string
  step_key: string
  step_name: string
  employee_name: string | null
  approver_role: string
  sequence_order: number
  status: string
  assigned_user_id: string | null
  requested_at: string
  due_at: string | null
}

export type ApprovalDecision = 'approved' | 'rejected'

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * GET /approvals always returns exactly what's relevant to the caller —
 * assigned-to-them, their role's pool, or everything for Administrators.
 * There's no "view all" mode here; that filtering happens server-side (see
 * approval_request_repo.list_pending_for_user), so the frontend never has
 * to reason about who's allowed to see what.
 */
export async function fetchApprovals(token: string): Promise<ApprovalRequestResponse[]> {
  const response = await fetch(`${API_BASE_URL}/approvals`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to load approvals')
  }
  return response.json() as Promise<ApprovalRequestResponse[]>
}

export async function decideApproval(
  token: string,
  approvalRequestId: string,
  decision: ApprovalDecision,
  notes?: string,
): Promise<ApprovalRequestResponse> {
  const response = await fetch(`${API_BASE_URL}/approvals/${approvalRequestId}/decide`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ decision, notes: notes || null }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to record decision')
  }
  return response.json() as Promise<ApprovalRequestResponse>
}
