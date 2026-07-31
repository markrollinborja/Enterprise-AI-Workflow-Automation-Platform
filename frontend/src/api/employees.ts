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
 * readable).
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

export interface EmployeeCreate {
  first_name: string
  last_name: string
  work_email: string
  job_title: string
  department_id: string
  manager_id?: string | null
  employment_type: string
  start_date: string
  location: string
  risk_level: string
}

/**
 * POST /employees is HR/Administrator-only server-side (require_role) — this
 * client call doesn't re-check the role, it just calls the endpoint; the
 * form that calls this (EmployeeDirectory.tsx) hides itself for other roles,
 * and the backend is the actual enforcement point either way. Creating an
 * employee here is what fires the `employee.created` event and starts the
 * onboarding workflow instance — this is the only trigger for that flow.
 */
export async function createEmployee(
  token: string,
  payload: EmployeeCreate,
): Promise<EmployeeResponse> {
  const response = await fetch(`${API_BASE_URL}/employees`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to create employee')
  }
  return response.json() as Promise<EmployeeResponse>
}

export interface EmployeeUpdate {
  first_name?: string
  last_name?: string
  job_title?: string
  department_id?: string
  manager_id?: string | null
  employment_type?: string
  status?: string
  location?: string
  risk_level?: string
}

/**
 * PATCH /employees/{id} is HR/Administrator-only server-side, same
 * enforcement note as createEmployee above. All fields optional — only send
 * what actually changed (see EmployeeDirectory.tsx's edit form, which
 * starts from the existing row's values and only includes fields the user
 * touched).
 */
export async function updateEmployee(
  token: string,
  employeeId: string,
  payload: EmployeeUpdate,
): Promise<EmployeeResponse> {
  const response = await fetch(`${API_BASE_URL}/employees/${employeeId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to update employee')
  }
  return response.json() as Promise<EmployeeResponse>
}
