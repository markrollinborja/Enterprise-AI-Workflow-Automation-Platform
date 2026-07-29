import { useCallback, useEffect, useState } from 'react'
import { fetchWorkflowInstances, type WorkflowInstanceSummaryResponse } from '../api/dashboard'
import { useAuth } from '../context/AuthContext'

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-700',
  running: 'bg-blue-100 text-blue-800',
  waiting_approval: 'bg-amber-100 text-amber-800',
  waiting_external: 'bg-amber-100 text-amber-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  rejected: 'bg-red-100 text-red-800',
  cancelled: 'bg-slate-200 text-slate-600',
}

function StatusBadge({ status }: { status: string }) {
  const className = STATUS_STYLES[status] ?? 'bg-slate-100 text-slate-700'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: '', label: 'All statuses' },
  { value: 'running', label: 'Running' },
  { value: 'waiting_approval', label: 'Waiting on approval' },
  { value: 'waiting_external', label: 'Waiting on external system' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'cancelled', label: 'Cancelled' },
]

interface WorkflowInstanceListProps {
  /** Fixes the filter to one status (e.g. "failed" for the Phase 12c Failed
   * Workflows page) and hides the dropdown — same component, same
   * GET /workflow-instances?status= endpoint, no second component needed.
   */
  fixedStatus?: string
  onSelectInstance?: (id: string) => void
}

export function WorkflowInstanceList({ fixedStatus, onSelectInstance }: WorkflowInstanceListProps) {
  const { token } = useAuth()
  const [status, setStatus] = useState(fixedStatus ?? '')
  const [instances, setInstances] = useState<WorkflowInstanceSummaryResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    fetchWorkflowInstances(token, status || undefined)
      .then(setInstances)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load workflow instances'),
      )
      .finally(() => setIsLoading(false))
  }, [token, status])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        {fixedStatus ? (
          <p className="text-sm text-slate-500">
            Showing <span className="font-medium text-slate-700">{fixedStatus}</span> workflows
          </p>
        ) : (
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        )}
        <button onClick={load} className="text-xs text-slate-500 underline">
          Refresh
        </button>
      </div>

      {isLoading && <p className="text-sm text-slate-500">Loading workflow instances…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!isLoading && !error && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Workflow</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Employee</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Initiated By</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Current Step</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Status</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Started</th>
                <th className="px-4 py-2 text-left font-medium text-slate-600">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {instances.map((instance) => (
                <tr
                  key={instance.id}
                  onClick={() => onSelectInstance?.(instance.id)}
                  className={onSelectInstance ? 'cursor-pointer hover:bg-slate-50' : undefined}
                >
                  <td className="px-4 py-2 font-medium text-slate-900">{instance.workflow_name}</td>
                  <td className="px-4 py-2 text-slate-700">{instance.employee_name ?? '—'}</td>
                  <td className="px-4 py-2 text-slate-700">{instance.initiated_by_name ?? '—'}</td>
                  <td className="px-4 py-2 text-slate-700">{instance.current_step_key ?? '—'}</td>
                  <td className="px-4 py-2">
                    <StatusBadge status={instance.status} />
                  </td>
                  <td className="px-4 py-2 text-slate-500">
                    {instance.started_at ? new Date(instance.started_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-2 text-slate-500">
                    {new Date(instance.updated_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {instances.length === 0 && (
            <p className="p-4 text-sm text-slate-500">No workflow instances found.</p>
          )}
        </div>
      )}
    </div>
  )
}
