import { ArrowLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  fetchWorkflowInstanceDetail,
  retryFailedStep,
  type AIExecutionDetailResponse,
  type ApprovalDetailResponse,
  type MCPToolExecutionDetailResponse,
  type NotificationDetailResponse,
  type WorkflowInstanceDetailResponse,
  type WorkflowStepDetailResponse,
} from '../api/dashboard'
import { useAuth } from '../context/AuthContext'
import { AuditTimelineList } from './AuditTimeline'
import { StatusBadge } from './WorkflowInstanceList'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

/** Compact key: value rendering for a step/tool call's input or output blob
 * — this data is arbitrary JSON from workflows/*.json input_schema or
 * whatever an MCP tool/AI call actually returned, not a fixed shape the
 * frontend can build a bespoke form around. */
function KeyValueList({ data }: { data: Record<string, unknown> | null }) {
  if (!data || Object.keys(data).length === 0) {
    return <p className="text-xs text-muted-foreground/70">—</p>
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-muted-foreground">{key}</dt>
          <dd className="text-foreground">
            {typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

interface StepCardProps {
  step: WorkflowStepDetailResponse
  onRetry: (stepKey: string) => void
  isRetrying: boolean
}

function StepCard({ step, onRetry, isRetrying }: StepCardProps) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">{step.step_key}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {step.step_type} · attempt {step.attempt_count}
              {step.external_ref ? ` · ref ${step.external_ref}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={step.status} />
            {step.status === 'failed' && (
              <Button variant="outline" size="sm" onClick={() => onRetry(step.step_key)} disabled={isRetrying}>
                {isRetrying ? 'Retrying…' : 'Retry'}
              </Button>
            )}
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground/70">
          Started {formatDate(step.started_at)} · Completed {formatDate(step.completed_at)}
        </p>
        {step.retried_at && (
          <p className="mt-1 text-xs text-muted-foreground/70">
            Manually retried by {step.retried_by_name} on {formatDate(step.retried_at)}
          </p>
        )}
        {step.error_message && <p className="mt-2 text-xs text-destructive">{step.error_message}</p>}
        {step.output_data && (
          <div className="mt-2">
            <KeyValueList data={step.output_data} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ApprovalCard({ approval }: { approval: ApprovalDetailResponse }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">{approval.step_key}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Requires: {approval.approver_role}
              {approval.assigned_user_name ? ` · assigned to ${approval.assigned_user_name}` : ' · role pool'}
            </p>
          </div>
          <StatusBadge status={approval.status} />
        </div>
        {approval.decisions.length > 0 && (
          <ul className="mt-2 space-y-1 border-t border-border pt-2">
            {approval.decisions.map((decision) => (
              <li key={decision.id} className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{decision.decided_by_name}</span>{' '}
                {decision.decision} on {formatDate(decision.decided_at)}
                {decision.notes ? ` — "${decision.notes}"` : ''}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function AIExecutionCard({ execution }: { execution: AIExecutionDetailResponse }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">{execution.task_type}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {execution.step_key} · {execution.model_used}
              {execution.confidence_score !== null
                ? ` · confidence ${(execution.confidence_score * 100).toFixed(0)}%`
                : ''}
            </p>
          </div>
          <StatusBadge status={execution.status} />
        </div>
        {execution.requires_human_review !== null && (
          <p className="mt-2 text-xs text-muted-foreground">
            Human review required: {execution.requires_human_review ? 'yes' : 'no'}
          </p>
        )}
        {execution.error_message && (
          <p className="mt-2 text-xs text-destructive">{execution.error_message}</p>
        )}
        {execution.output_json && (
          <div className="mt-2">
            <KeyValueList data={execution.output_json} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function MCPToolExecutionCard({ execution }: { execution: MCPToolExecutionDetailResponse }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">{execution.tool_name}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Called by {execution.caller}
              {execution.mock_mode ? ' · mock mode' : ' · real'}
              {execution.duration_ms !== null ? ` · ${execution.duration_ms}ms` : ''}
            </p>
          </div>
          <StatusBadge status={execution.status} />
        </div>
        {execution.error_message && (
          <p className="mt-2 text-xs text-destructive">{execution.error_message}</p>
        )}
        {execution.output_result && (
          <div className="mt-2">
            <KeyValueList data={execution.output_result} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function NotificationCard({ notification }: { notification: NotificationDetailResponse }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-foreground">{notification.title}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              To {notification.recipient_name} via {notification.channel} · {notification.type}
            </p>
          </div>
          <StatusBadge status={notification.status} />
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{notification.body}</p>
        <p className="mt-1 text-xs text-muted-foreground/70">
          Sent {formatDate(notification.created_at)}
          {notification.read_at ? ` · read ${formatDate(notification.read_at)}` : ''}
        </p>
      </CardContent>
    </Card>
  )
}

interface WorkflowDetailProps {
  instanceId: string
  onBack: () => void
}

export function WorkflowDetail({ instanceId, onBack }: WorkflowDetailProps) {
  const { token } = useAuth()
  const [detail, setDetail] = useState<WorkflowInstanceDetailResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryingStepKey, setRetryingStepKey] = useState<string | null>(null)
  const [retryError, setRetryError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    setIsLoading(true)
    setDetail(null)
    fetchWorkflowInstanceDetail(token, instanceId)
      .then(setDetail)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Failed to load workflow instance'),
      )
      .finally(() => setIsLoading(false))
  }, [token, instanceId])

  async function handleRetry(stepKey: string) {
    if (!token) return
    setRetryingStepKey(stepKey)
    setRetryError(null)
    try {
      // The retry endpoint returns the full updated instance detail
      // directly — advance_workflow already ran inline server-side, so
      // this one response reflects wherever the retry actually landed
      // (re-failed, paused for approval, completed, ...) with no second
      // fetch needed.
      const updated = await retryFailedStep(token, instanceId, stepKey)
      setDetail(updated)
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : 'Failed to retry step')
    } finally {
      setRetryingStepKey(null)
    }
  }

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" onClick={onBack} className="gap-1.5 text-muted-foreground">
        <ArrowLeft className="h-4 w-4" />
        Back
      </Button>

      {isLoading && <p className="text-sm text-muted-foreground">Loading workflow instance…</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {retryError && <p className="text-sm text-destructive">{retryError}</p>}

      {detail && (
        <>
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-lg font-semibold text-foreground">{detail.workflow_name}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {detail.employee_name ? `For ${detail.employee_name} · ` : ''}
                    Initiated by {detail.initiated_by_name ?? 'System'}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground/70">
                    Started {formatDate(detail.started_at)} · Updated {formatDate(detail.updated_at)}
                    {detail.completed_at ? ` · Completed ${formatDate(detail.completed_at)}` : ''}
                  </p>
                  {detail.current_step_key && (
                    <p className="mt-1 text-xs text-muted-foreground/70">
                      Current step: {detail.current_step_key}
                    </p>
                  )}
                </div>
                <StatusBadge status={detail.status} />
              </div>
            </CardContent>
          </Card>

          <SectionCard title="Steps">
            {detail.steps.map((step) => (
              <StepCard
                key={step.id}
                step={step}
                onRetry={handleRetry}
                isRetrying={retryingStepKey === step.step_key}
              />
            ))}
          </SectionCard>

          {detail.approvals.length > 0 && (
            <SectionCard title="Approvals">
              {detail.approvals.map((approval) => (
                <ApprovalCard key={approval.id} approval={approval} />
              ))}
            </SectionCard>
          )}

          {detail.ai_executions.length > 0 && (
            <SectionCard title="AI Output">
              {detail.ai_executions.map((execution) => (
                <AIExecutionCard key={execution.id} execution={execution} />
              ))}
            </SectionCard>
          )}

          {detail.mcp_tool_executions.length > 0 && (
            <SectionCard title="MCP Tool Executions">
              {detail.mcp_tool_executions.map((execution) => (
                <MCPToolExecutionCard key={execution.id} execution={execution} />
              ))}
            </SectionCard>
          )}

          {detail.notifications.length > 0 && (
            <SectionCard title="Notifications">
              {detail.notifications.map((notification) => (
                <NotificationCard key={notification.id} notification={notification} />
              ))}
            </SectionCard>
          )}

          <SectionCard title="Audit Timeline">
            <Card>
              <CardContent className="pt-4">
                <AuditTimelineList entries={detail.audit_timeline} />
              </CardContent>
            </Card>
          </SectionCard>
        </>
      )}
    </div>
  )
}
