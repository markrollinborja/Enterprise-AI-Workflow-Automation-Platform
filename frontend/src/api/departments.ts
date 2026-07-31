import { API_BASE_URL } from './client'

export interface DepartmentResponse {
  id: string
  name: string
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * GET /departments is visible to any authenticated user — same reasoning as
 * the employee directory. Only pulled in for its own sake here to populate
 * the Create Employee form's department picker (see EmployeeDirectory.tsx);
 * there's no standalone "Departments" page in V1.
 */
export async function fetchDepartments(token: string): Promise<DepartmentResponse[]> {
  const response = await fetch(`${API_BASE_URL}/departments`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to load departments')
  }
  return response.json() as Promise<DepartmentResponse[]>
}

/**
 * POST /departments is HR/Administrator-only server-side. Exposed here as a
 * quick "add new department" path inline in the Create Employee form
 * (EmployeeDirectory.tsx) rather than a standalone Departments management
 * page — departments are simple enough (just a name) that a whole page for
 * CRUD on them would be more surface area than the actual demo needs.
 */
export async function createDepartment(
  token: string,
  name: string,
): Promise<DepartmentResponse> {
  const response = await fetch(`${API_BASE_URL}/departments`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ name }),
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to create department')
  }
  return response.json() as Promise<DepartmentResponse>
}
