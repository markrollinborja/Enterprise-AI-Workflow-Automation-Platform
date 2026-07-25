import { API_BASE_URL } from './client'

export interface EmployeeResponse {
  id: string
  first_name: string
  last_name: string
  work_email: string
  job_title: string
  department_id: string
  department_name: string | null
  manager_id: string | null
  manager_name: string | null
  employment_type: string
  start_date: string
  status: string
  location: string
  risk_level: string
  created_at: string
  updated_at: string
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * GET /employees is visible to any authenticated user (see the reasoning in
 * app/api/routes/employees.py — org directories are typically company-wide
 * readable). This is the only employees call the Phase 4 UI needs; create
 * and update stay HR/Administrator-only and get a UI in a later phase once
 * there's a workflow that actually triggers them.
 */
export async function fetchEmployees(token: string): Promise<EmployeeResponse[]> {
  const response = await fetch(`${API_BASE_URL}/employees`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to load employees')
  }
  return response.json() as Promise<EmployeeResponse[]>
}
