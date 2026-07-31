import { useCallback, useEffect, useState } from 'react'
import {
  createEmployee,
  fetchEmployees,
  updateEmployee,
  type EmployeeCreate,
  type EmployeeResponse,
  type EmployeeUpdate,
} from '../api/employees'
import { createDepartment, fetchDepartments, type DepartmentResponse } from '../api/departments'
import { useAuth } from '../context/AuthContext'

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  pending: 'bg-blue-100 text-blue-800',
  on_leave: 'bg-amber-100 text-amber-800',
  terminated: 'bg-slate-200 text-slate-600',
}

const RISK_STYLES: Record<string, string> = {
  low: 'bg-slate-100 text-slate-700',
  medium: 'bg-amber-100 text-amber-800',
  high: 'bg-red-100 text-red-800',
}

const EMPLOYMENT_TYPES = ['full_time', 'part_time', 'contractor']
const RISK_LEVELS = ['low', 'medium', 'high']
const STATUSES = ['active', 'pending', 'on_leave', 'terminated']

const NEW_DEPARTMENT_VALUE = '__new_department__'

function Badge({ label, styles }: { label: string; styles: Record<string, string> }) {
  const className = styles[label] ?? 'bg-slate-100 text-slate-700'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {label.replace('_', ' ')}
    </span>
  )
}

const emptyCreateForm: EmployeeCreate = {
  first_name: '',
  last_name: '',
  work_email: '',
  job_title: '',
  department_id: '',
  manager_id: null,
  employment_type: 'full_time',
  start_date: '',
  location: '',
  risk_level: 'low',
}

function CreateEmployeeForm({
  token,
  departments,
  employees,
  onDepartmentCreated,
  onCreated,
}: {
  token: string
  departments: DepartmentResponse[]
  employees: EmployeeResponse[]
  onDepartmentCreated: (department: DepartmentResponse) => void
  onCreated: () => void
}) {
  const [form, setForm] = useState<EmployeeCreate>(emptyCreateForm)
  const [newDepartmentName, setNewDepartmentName] = useState('')
  const [isAddingDepartment, setIsAddingDepartment] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  function update<K extends keyof EmployeeCreate>(key: K, value: EmployeeCreate[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function handleDepartmentSelect(value: string) {
    if (value === NEW_DEPARTMENT_VALUE) {
      setIsAddingDepartment(true)
      update('department_id', '')
      return
    }
    setIsAddingDepartment(false)
    update('department_id', value)
  }

  async function handleAddDepartment() {
    if (!newDepartmentName.trim()) return
    setError(null)
    try {
      const created = await createDepartment(token, newDepartmentName.trim())
      onDepartmentCreated(created)
      update('department_id', created.id)
      setIsAddingDepartment(false)
      setNewDepartmentName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create department')
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setIsSubmitting(true)
    try {
      const created = await createEmployee(token, {
        ...form,
        manager_id: form.manager_id || null,
      })
      setSuccessMessage(
        `${created.first_name} ${created.last_name} created — onboarding workflow started.`,
      )
      setForm(emptyCreateForm)
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create employee')
    } finally {
      setIsSubmitting(false)
    }
  }

  const inputClass = 'w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm'
  const labelClass = 'block text-xs font-medium text-slate-600'

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
    >
      <p className="mb-3 text-sm font-semibold text-slate-900">Create Employee</p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label className={labelClass}>First name</label>
          <input
            required
            className={inputClass}
            value={form.first_name}
            onChange={(e) => update('first_name', e.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Last name</label>
          <input
            required
            className={inputClass}
            value={form.last_name}
            onChange={(e) => update('last_name', e.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Work email</label>
          <input
            required
            type="email"
            className={inputClass}
            value={form.work_email}
            onChange={(e) => update('work_email', e.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Job title</label>
          <input
            required
            className={inputClass}
            value={form.job_title}
            onChange={(e) => update('job_title', e.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Department</label>
          {isAddingDepartment ? (
            <div className="flex gap-1">
              <input
                autoFocus
                className={inputClass}
                placeholder="New department name"
                value={newDepartmentName}
                onChange={(e) => setNewDepartmentName(e.target.value)}
              />
              <button
                type="button"
                onClick={handleAddDepartment}
                className="rounded-md bg-slate-900 px-2 text-xs font-medium text-white"
              >
                Add
              </button>
              <button
                type="button"
                onClick={() => setIsAddingDepartment(false)}
                className="rounded-md border border-slate-300 px-2 text-xs text-slate-600"
              >
                Cancel
              </button>
            </div>
          ) : (
            <select
              required
              className={inputClass}
              value={form.department_id}
              onChange={(e) => handleDepartmentSelect(e.target.value)}
            >
              <option value="" disabled>
                Select a department
              </option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
              <option value={NEW_DEPARTMENT_VALUE}>+ Add new department…</option>
            </select>
          )}
        </div>
        <div>
          <label className={labelClass}>Manager (optional)</label>
          <select
            className={inputClass}
            value={form.manager_id ?? ''}
            onChange={(e) => update('manager_id', e.target.value || null)}
          >
            <option value="">No manager</option>
            {employees.map((emp) => (
              <option key={emp.id} value={emp.id}>
                {emp.first_name} {emp.last_name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Employment type</label>
          <select
            className={inputClass}
            value={form.employment_type}
            onChange={(e) => update('employment_type', e.target.value)}
          >
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Start date</label>
          <input
            required
            type="date"
            className={inputClass}
            value={form.start_date}
            onChange={(e) => update('start_date', e.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Location</label>
          <input
            required
            className={inputClass}
            value={form.location}
            onChange={(e) => update('location', e.target.value)}
          />
        </div>
        <div>
          <label className={labelClass}>Risk level</label>
          <select
            className={inputClass}
            value={form.risk_level}
            onChange={(e) => update('risk_level', e.target.value)}
          >
            {RISK_LEVELS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {successMessage && <p className="mt-3 text-sm text-green-700">{successMessage}</p>}

      <button
        type="submit"
        disabled={isSubmitting}
        className="mt-4 rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        {isSubmitting ? 'Creating…' : 'Create Employee'}
      </button>
    </form>
  )
}

function EditEmployeeRow({
  employee,
  departments,
  token,
  onCancel,
  onSaved,
}: {
  employee: EmployeeResponse
  departments: DepartmentResponse[]
  token: string
  onCancel: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState<EmployeeUpdate>({
    first_name: employee.first_name,
    last_name: employee.last_name,
    job_title: employee.job_title,
    department_id: employee.department_id,
    employment_type: employee.employment_type,
    status: employee.status,
    location: employee.location,
    risk_level: employee.risk_level,
  })
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function update<K extends keyof EmployeeUpdate>(key: K, value: EmployeeUpdate[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    setIsSaving(true)
    setError(null)
    try {
      await updateEmployee(token, employee.id, form)
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update employee')
    } finally {
      setIsSaving(false)
    }
  }

  const inputClass = 'w-full rounded-md border border-slate-300 px-2 py-1 text-xs'

  return (
    <tr className="bg-slate-50">
      <td className="px-4 py-2" colSpan={7}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <input
            className={inputClass}
            placeholder="First name"
            value={form.first_name ?? ''}
            onChange={(e) => update('first_name', e.target.value)}
          />
          <input
            className={inputClass}
            placeholder="Last name"
            value={form.last_name ?? ''}
            onChange={(e) => update('last_name', e.target.value)}
          />
          <input
            className={inputClass}
            placeholder="Job title"
            value={form.job_title ?? ''}
            onChange={(e) => update('job_title', e.target.value)}
          />
          <select
            className={inputClass}
            value={form.department_id ?? ''}
            onChange={(e) => update('department_id', e.target.value)}
          >
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          <select
            className={inputClass}
            value={form.status ?? ''}
            onChange={(e) => update('status', e.target.value)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace('_', ' ')}
              </option>
            ))}
          </select>
          <select
            className={inputClass}
            value={form.risk_level ?? ''}
            onChange={(e) => update('risk_level', e.target.value)}
          >
            {RISK_LEVELS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input
            className={inputClass}
            placeholder="Location"
            value={form.location ?? ''}
            onChange={(e) => update('location', e.target.value)}
          />
          <select
            className={inputClass}
            value={form.employment_type ?? ''}
            onChange={(e) => update('employment_type', e.target.value)}
          >
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>

        {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

        <div className="mt-2 flex gap-2">
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            {isSaving ? 'Saving…' : 'Save'}
          </button>
          <button
            onClick={onCancel}
            className="rounded-md border border-slate-300 px-3 py-1 text-xs text-slate-600"
          >
            Cancel
          </button>
        </div>
      </td>
    </tr>
  )
}

export function EmployeeDirectory() {
  const { token, user } = useAuth()
  const [employees, setEmployees] = useState<EmployeeResponse[]>([])
  const [departments, setDepartments] = useState<DepartmentResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  const isHrOrAdmin = user?.role === 'hr' || user?.role === 'administrator'

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    Promise.all([fetchEmployees(token), fetchDepartments(token)])
      .then(([employeeList, departmentList]) => {
        setEmployees(employeeList)
        setDepartments(departmentList)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load employee directory'))
      .finally(() => setIsLoading(false))
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading employee directory…</p>
  }

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }

  return (
    <div>
      {isHrOrAdmin && (
        <div className="mb-3">
          <button
            onClick={() => setShowCreateForm((prev) => !prev)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700"
          >
            {showCreateForm ? 'Close' : '+ New Employee'}
          </button>
        </div>
      )}

      {isHrOrAdmin && showCreateForm && token && (
        <CreateEmployeeForm
          token={token}
          departments={departments}
          employees={employees}
          onDepartmentCreated={(d) => setDepartments((prev) => [...prev, d])}
          onCreated={() => {
            load()
            setShowCreateForm(false)
          }}
        />
      )}

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
              {isHrOrAdmin && <th className="px-4 py-2 text-left font-medium text-slate-600" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {employees.map((employee) =>
              editingId === employee.id && token ? (
                <EditEmployeeRow
                  key={employee.id}
                  employee={employee}
                  departments={departments}
                  token={token}
                  onCancel={() => setEditingId(null)}
                  onSaved={() => {
                    setEditingId(null)
                    load()
                  }}
                />
              ) : (
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
                  {isHrOrAdmin && (
                    <td className="px-4 py-2">
                      <button
                        onClick={() => setEditingId(employee.id)}
                        className="text-xs font-medium text-slate-600 underline"
                      >
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ),
            )}
          </tbody>
        </table>
        {employees.length === 0 && (
          <p className="p-4 text-sm text-slate-500">No employees found.</p>
        )}
      </div>
    </div>
  )
}
