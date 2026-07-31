import { API_BASE_URL } from './client'

export interface AccessRequestResponse {
  workflow_instance_id: string
  application_id: string
  application_name: string
  justification: string
  computed_risk_level: string
  auto_approved: boolean
  status: string
  current_step_key: string | null
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * POST /access-requests — any authenticated user with a linked employee
 * record can call this (not role-restricted to `employee`, since a manager
 * or HR coordinator is also a person who might need their own software
 * access — see app/api/routes/access_requests.py). `employee_id` is
 * deliberately not a parameter here: the backend derives it from the
 * caller's own token, so there's no way to submit a request "as" someone
 * else even if this client tried to.
 *
 * This is the only trigger for the software_access_request workflow —
 * before this file existed, that entire second flagship workflow had no
 * frontend path at all.
 */
export async function submitAccessRequest(
  token: string,
  applicationId: string,
  justification: string,
): Promise<AccessRequestResponse> {
  const response = await fetch(`${API_BASE_URL}/access-requests`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ application_id: applicationId, justification }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to submit access request')
  }
  return response.json() as Promise<AccessRequestResponse>
}
