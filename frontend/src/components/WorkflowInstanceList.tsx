import { useCallback, useEffect, useState } from 'react'
import { fetchWorkflowInstances, type WorkflowInstanceSummaryResponse } from '../api/dashboard'
import { useAuth } from '../context/AuthContext'
import { Badge } from './ui/badge'
import { Select } from './ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'
import { Button } from './ui/button'

// Shared across every status vocabulary in this app (instance, step,
// approval) — a status this map doesn't recognize just falls back to plain
// muted rather than needing its own map per vocabulary.
const STATUS_BADGE_VARIANT: Record<
  string,
  'muted' | 'default' | 'warning' | 'success' | 'destructive'
> = {
  pending: 'muted',
  running: 'default',
  waiting_approval: 'warning',
  waiting_external: 'warning',
  approved: 'success',
  completed: 'success',
  skipped: 'muted',
  failed: 'destructive',
  rejected: 'destructive',
  cancelled: 'muted',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={STATUS_BADGE_VARIANT[status] ?? 'muted'}>{status.replace('_', ' ')}</Badge>
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
          <p className="text-sm text-muted-foreground">
            Showing <span className="font-medium text-foreground">{fixedStatus}</span> workflows
          </p>
        ) : (
          <div className="w-56">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </Select>
          </div>
        )}
        <Button variant="ghost" size="sm" onClick={load} className="text-muted-foreground">
          Refresh
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading workflow instances…</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {!isLoading && !error && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workflow</TableHead>
                <TableHead>Employee</TableHead>
                <TableHead>Initiated By</TableHead>
                <TableHead>Current Step</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {instances.map((instance) => (
                <TableRow
                  key={instance.id}
                  onClick={() => onSelectInstance?.(instance.id)}
                  className={onSelectInstance ? 'cursor-pointer' : undefined}
                >
                  <TableCell className="font-medium text-foreground">
                    {instance.workflow_name}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {instance.employee_name ?? '—'}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {instance.initiated_by_name ?? '—'}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {instance.current_step_key ?? '—'}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={instance.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {instance.started_at ? new Date(instance.started_at).toLocaleString() : '—'}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {new Date(instance.updated_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {instances.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">No workflow instances found.</p>
          )}
        </>
      )}
    </div>
  )
}
