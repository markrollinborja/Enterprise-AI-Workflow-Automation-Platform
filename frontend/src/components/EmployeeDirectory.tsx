import { useCallback, useEffect, useState } from 'react'
import { X } from 'lucide-react'
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
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { Select } from './ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'

const STATUS_BADGE_VARIANT: Record<string, 'success' | 'muted' | 'warning' | 'default'> = {
  active: 'success',
  pending: 'default',
  on_leave: 'warning',
  terminated: 'muted',
}

const RISK_BADGE_VARIANT: Record<string, 'muted' | 'warning' | 'destructive'> = {
  low: 'muted',
  medium: 'warning',
  high: 'destructive',
}

const EMPLOYMENT_TYPES = ['full_time', 'part_time', 'contractor']
const RISK_LEVELS = ['low', 'medium', 'high']
const STATUSES = ['active', 'pending', 'on_leave', 'terminated']

const NEW_DEPARTMENT_VALUE = '__new_department__'

function StatusBadge({ label }: { label: string }) {
  return (
    <Badge variant={STATUS_BADGE_VARIANT[label] ?? 'muted'}>{label.replace('_', ' ')}</Badge>
  )
}

function RiskBadge({ label }: { label: string }) {
  return <Badge variant={RISK_BADGE_VARIANT[label] ?? 'muted'}>{label}</Badge>
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
  onCreated: (created: EmployeeResponse) => void
}) {
  const [form, setForm] = useState<EmployeeCreate>(emptyCreateForm)
  const [newDepartmentName, setNewDepartmentName] = useState('')
  const [isAddingDepartment, setIsAddingDepartment] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
    setIsSubmitting(true)
    try {
      const created = await createEmployee(token, {
        ...form,
        manager_id: form.manager_id || null,
      })
      setForm(emptyCreateForm)
      onCreated(created)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create employee')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="mb-4">
      <CardContent className="pt-4">
        <form onSubmit={handleSubmit}>
          <p className="mb-3 text-sm font-semibold text-foreground">Create Employee</p>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="first_name">First name</Label>
              <Input
                id="first_name"
                required
                value={form.first_name}
                onChange={(e) => update('first_name', e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="last_name">Last name</Label>
              <Input
                id="last_name"
                required
                value={form.last_name}
                onChange={(e) => update('last_name', e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="work_email">Work email</Label>
              <Input
                id="work_email"
                required
                type="email"
                value={form.work_email}
                onChange={(e) => update('work_email', e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="job_title">Job title</Label>
              <Input
                id="job_title"
                required
                value={form.job_title}
                onChange={(e) => update('job_title', e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="department">Department</Label>
              {isAddingDepartment ? (
                <div className="flex gap-1.5">
                  <Input
                    autoFocus
                    placeholder="New department name"
                    value={newDepartmentName}
                    onChange={(e) => setNewDepartmentName(e.target.value)}
                  />
                  <Button type="button" size="sm" onClick={handleAddDepartment}>
                    Add
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsAddingDepartment(false)}
                  >
                    Cancel
                  </Button>
                </div>
              ) : (
                <Select
                  id="department"
                  required
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
                </Select>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="manager">Manager (optional)</Label>
              <Select
                id="manager"
                value={form.manager_id ?? ''}
                onChange={(e) => update('manager_id', e.target.value || null)}
              >
                <option value="">No manager</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {emp.first_name} {emp.last_name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="employment_type">Employment type</Label>
              <Select
                id="employment_type"
                value={form.employment_type}
                onChange={(e) => update('employment_type', e.target.value)}
              >
                {EMPLOYMENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace('_', ' ')}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="start_date">Start date</Label>
              <Input
                id="start_date"
                required
                type="date"
                value={form.start_date}
                onChange={(e) => update('start_date', e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="location">Location</Label>
              <Input
                id="location"
                required
                value={form.location}
                onChange={(e) => update('location', e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="risk_level">Risk level</Label>
              <Select
                id="risk_level"
                value={form.risk_level}
                onChange={(e) => update('risk_level', e.target.value)}
              >
                {RISK_LEVELS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

          <Button type="submit" disabled={isSubmitting} className="mt-4">
            {isSubmitting ? 'Creating…' : 'Create Employee'}
          </Button>
        </form>
      </CardContent>
    </Card>
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

  return (
    <TableRow className="bg-accent/40 hover:bg-accent/40">
      <TableCell colSpan={7}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Input
            placeholder="First name"
            value={form.first_name ?? ''}
            onChange={(e) => update('first_name', e.target.value)}
          />
          <Input
            placeholder="Last name"
            value={form.last_name ?? ''}
            onChange={(e) => update('last_name', e.target.value)}
          />
          <Input
            placeholder="Job title"
            value={form.job_title ?? ''}
            onChange={(e) => update('job_title', e.target.value)}
          />
          <Select
            value={form.department_id ?? ''}
            onChange={(e) => update('department_id', e.target.value)}
          >
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
          <Select value={form.status ?? ''} onChange={(e) => update('status', e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace('_', ' ')}
              </option>
            ))}
          </Select>
          <Select
            value={form.risk_level ?? ''}
            onChange={(e) => update('risk_level', e.target.value)}
          >
            {RISK_LEVELS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
          <Input
            placeholder="Location"
            value={form.location ?? ''}
            onChange={(e) => update('location', e.target.value)}
          />
          <Select
            value={form.employment_type ?? ''}
            onChange={(e) => update('employment_type', e.target.value)}
          >
            {EMPLOYMENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace('_', ' ')}
              </option>
            ))}
          </Select>
        </div>

        {error && <p className="mt-2 text-xs text-destructive">{error}</p>}

        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={handleSave} disabled={isSaving}>
            {isSaving ? 'Saving…' : 'Save'}
          </Button>
          <Button size="sm" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </TableCell>
    </TableRow>
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
  const [banner, setBanner] = useState<string | null>(null)

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
    return <p className="text-sm text-muted-foreground">Loading employee directory…</p>
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>
  }

  return (
    <div>
      {banner && (
        <div className="mb-3 flex items-start justify-between gap-3 rounded-md bg-success/10 px-4 py-3 text-sm text-success">
          <span>{banner}</span>
          <button
            onClick={() => setBanner(null)}
            className="shrink-0 text-success/70 hover:text-success"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {isHrOrAdmin && (
        <div className="mb-3">
          <Button variant="outline" onClick={() => setShowCreateForm((prev) => !prev)}>
            {showCreateForm ? 'Close' : '+ New Employee'}
          </Button>
        </div>
      )}

      {isHrOrAdmin && showCreateForm && token && (
        <CreateEmployeeForm
          token={token}
          departments={departments}
          employees={employees}
          onDepartmentCreated={(d) => setDepartments((prev) => [...prev, d])}
          onCreated={(created) => {
            load()
            setShowCreateForm(false)
            setBanner(
              `${created.first_name} ${created.last_name} created — onboarding workflow started. Check the Workflows tab (Administrator) or their Manager's Pending Approvals to track progress.`,
            )
          }}
        />
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Title</TableHead>
            <TableHead>Department</TableHead>
            <TableHead>Manager</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Risk</TableHead>
            {isHrOrAdmin && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
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
              <TableRow key={employee.id}>
                <TableCell>
                  <div className="font-medium text-foreground">
                    {employee.first_name} {employee.last_name}
                  </div>
                  <div className="text-xs text-muted-foreground">{employee.work_email}</div>
                </TableCell>
                <TableCell className="text-muted-foreground">{employee.job_title}</TableCell>
                <TableCell className="text-muted-foreground">
                  {employee.department_name ?? '—'}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {employee.manager_name ?? '—'}
                </TableCell>
                <TableCell>
                  <StatusBadge label={employee.status} />
                </TableCell>
                <TableCell>
                  <RiskBadge label={employee.risk_level} />
                </TableCell>
                {isHrOrAdmin && (
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={() => setEditingId(employee.id)}>
                      Edit
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ),
          )}
        </TableBody>
      </Table>
      {employees.length === 0 && (
        <p className="p-4 text-sm text-muted-foreground">No employees found.</p>
      )}
    </div>
  )
}
