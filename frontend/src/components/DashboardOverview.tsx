import { useEffect, useState } from 'react'
import { fetchDashboardSummary, type DashboardSummaryResponse } from '../api/dashboard'
import { useAuth } from '../context/AuthContext'
import { Card, CardContent } from './ui/card'

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-2xl font-semibold text-foreground">{value}</p>
      </CardContent>
    </Card>
  )
}

function BreakdownCard({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1])
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </p>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground/70">No data yet.</p>
        ) : (
          <ul className="space-y-1">
            {entries.map(([name, count]) => (
              <li key={name} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{name}</span>
                <span className="font-medium text-foreground">{count}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

export function DashboardOverview() {
  const { token } = useAuth()
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    fetchDashboardSummary(token)
      .then(setSummary)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load dashboard summary'),
      )
      .finally(() => setIsLoading(false))
  }, [token])

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading overview…</p>
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>
  }

  if (!summary) {
    return null
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
        <StatCard label="Active Workflows" value={summary.active_workflows} />
        <StatCard label="Pending Approvals" value={summary.pending_approvals} />
        <StatCard label="Failed Workflows" value={summary.failed_workflows} />
        <StatCard label="Completed Workflows" value={summary.completed_workflows} />
        <StatCard label="Avg Completion Time" value={formatDuration(summary.avg_completion_seconds)} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <BreakdownCard title="Requests by Type" data={summary.requests_by_type} />
        <BreakdownCard title="Requests by Department" data={summary.requests_by_department} />
      </div>
    </div>
  )
}
