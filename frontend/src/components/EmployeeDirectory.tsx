import { useEffect, useState } from 'react'
import { fetchEmployees, type EmployeeResponse } from '../api/employees'
import { useAuth } from '../context/AuthContext'

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  on_leave: 'bg-amber-100 text-amber-800',
  terminated: 'bg-slate-200 text-slate-600',
}

const RISK_STYLES: Record<string, string> = {
  low: 'bg-slate-100 text-slate-700',
  medium: 'bg-amber-100 text-amber-800',
  high: 'bg-red-100 text-red-800',
}

function Badge({ label, styles }: { label: string; styles: Record<string, string> }) {
  const className = styles[label] ?? 'bg-slate-100 text-slate-700'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {label.replace('_', ' ')}
    </span>
  )
}

export function EmployeeDirectory() {
  const { token } = useAuth()
  const [employees, setEmployees] = useState<EmployeeResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    fetchEmployees(token)
      .then(setEmployees)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load employees'))
      .finally(() => setIsLoading(false))
  }, [token])

  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading employee directory…</p>
  }

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="px-4 py-2 text-left font-medium text-slate-600">Name</th>
            <th className="px-4 py-2 text-left font-medium text-slate-600">Title</th>
            <th className="px-4 py-2 text-left font-medium text-slate-600">Department</th>
            <th className="px-4 py-2 text-left font-medium text-slate-600">Manager</th>
            <th className="px-4 py-2 text-left font-medium text-slate-600">Status</th>
            <th className="px-4 py-2 text-left font-medium text-slate-600">Risk</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {employees.map((employee) => (
            <tr key={employee.id}>
              <td className="px-4 py-2">
                <div className="font-medium text-slate-900">
                  {employee.first_name} {employee.last_name}
                </div>
                <div className="text-xs text-slate-400">{employee.work_email}</div>
              </td>
              <td className="px-4 py-2 text-slate-700">{employee.job_title}</td>
              <td className="px-4 py-2 text-slate-700">{employee.department_name ?? '—'}</td>
              <td className="px-4 py-2 text-slate-700">{employee.manager_name ?? '—'}</td>
              <td className="px-4 py-2">
                <Badge label={employee.status} styles={STATUS_STYLES} />
              </td>
              <td className="px-4 py-2">
                <Badge label={employee.risk_level} styles={RISK_STYLES} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {employees.length === 0 && (
        <p className="p-4 text-sm text-slate-500">No employees found.</p>
      )}
    </div>
  )
}
