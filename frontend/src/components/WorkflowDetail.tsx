import { useEffect, useState } from 'react'
import {
  fetchWorkflowInstanceDetail,
  type AIExecutionDetailResponse,
  type ApprovalDetailResponse,
  type AuditTimelineEntryResponse,
  type MCPToolExecutionDetailResponse,
  type NotificationDetailResponse,
  type WorkflowInstanceDetailResponse,
  type WorkflowStepDetailResponse,
} from '../api/dashboard'
import { useAuth } from '../context/AuthContext'
import { StatusBadge } from './WorkflowInstanceList'

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
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
    return <p className="text-xs text-slate-400">—</p>
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-slate-500">{key}</dt>
          <dd className="text-slate-700">
            {typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">{children}</div>
  )
}

function StepCard({ step }: { step: WorkflowStepDetailResponse }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-900">{step.step_key}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            {step.step_type} · attempt {step.attempt_count}
            {step.external_ref ? ` · ref ${step.external_ref}` : ''}
          </p>
        </div>
        <StatusBadge status={step.status} />
      </div>
      <p className="mt-2 text-xs text-slate-400">
        Started {formatDate(step.started_at)} · Completed {formatDate(step.completed_at)}
      </p>
      {step.error_message && (
        <p className="mt-2 text-xs text-red-600">{step.error_message}</p>
      )}
      {step.output_data && (
        <div className="mt-2">
          <KeyValueList data={step.output_data} />
        </div>
      )}
    </Card>
  )
}

function ApprovalCard({ approval }: { approval: ApprovalDetailResponse }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-900">{approval.step_key}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            Requires: {approval.approver_role}
            {approval.assigned_user_name ? ` · assigned to ${approval.assigned_user_name}` : ' · role pool'}
          </p>
        </div>
        <StatusBadge status={approval.status} />
      </div>
      {approval.decisions.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2">
          {approval.decisions.map((decision) => (
            <li key={decision.id} className="text-xs text-slate-600">
              <span className="font-medium text-slate-800">{decision.decided_by_name}</span>{' '}
              {decision.decision} on {formatDate(decision.decided_at)}
              {decision.notes ? ` — "${decision.notes}"` : ''}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function AIExecutionCard({ execution }: { execution: AIExecutionDetailResponse }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-900">{execution.task_type}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            {execution.step_key} · {execution.model_used}
            {execution.confidence_score !== null
              ? ` · confidence ${(execution.confidence_score * 100).toFixed(0)}%`
              : ''}
          </p>
        </div>
        <StatusBadge status={execution.status} />
      </div>
      {execution.requires_human_review !== null && (
        <p className="mt-2 text-xs text-slate-500">
          Human review required: {execution.requires_human_review ? 'yes' : 'no'}
        </p>
      )}
      {execution.error_message && (
        <p className="mt-2 text-xs text-red-600">{execution.error_message}</p>
      )}
      {execution.output_json && (
        <div className="mt-2">
          <KeyValueList data={execution.output_json} />
        </div>
      )}
    </Card>
  )
}

function MCPToolExecutionCard({ execution }: { execution: MCPToolExecutionDetailResponse }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-900">{execution.tool_name}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            Called by {execution.caller}
            {execution.mock_mode ? ' · mock mode' : ' · real'}
            {execution.duration_ms !== null ? ` · ${execution.duration_ms}ms` : ''}
          </p>
        </div>
        <StatusBadge status={execution.status} />
      </div>
      {execution.error_message && (
        <p className="mt-2 text-xs text-red-600">{execution.error_message}</p>
      )}
      {execution.output_result && (
        <div className="mt-2">
          <KeyValueList data={execution.output_result} />
        </div>
      )}
    </Card>
  )
}

function NotificationCard({ notification }: { notification: NotificationDetailResponse }) {
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-900">{notification.title}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            To {notification.recipient_name} via {notification.channel} · {notification.type}
          </p>
        </div>
        <StatusBadge status={notification.status} />
      </div>
      <p className="mt-2 text-xs text-slate-600">{notification.body}</p>
      <p className="mt-1 text-xs text-slate-400">
        Sent {formatDate(notification.created_at)}
        {notification.read_at ? ` · read ${formatDate(notification.read_at)}` : ''}
      </p>
    </Card>
  )
}

const ACTOR_TYPE_STYLES: Record<string, string> = {
  user: 'bg-blue-100 text-blue-800',
  ai: 'bg-purple-100 text-purple-800',
  system: 'bg-slate-100 text-slate-700',
}

function AuditTimelineRow({ entry }: { entry: AuditTimelineEntryResponse }) {
  const actorClass = ACTOR_TYPE_STYLES[entry.actor_type] ?? 'bg-slate-100 text-slate-700'
  const metadataEntries = Object.entries(entry.metadata).filter(([, v]) => v !== null && v !== '')
  return (
    <li className="border-l-2 border-slate-200 py-1 pl-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-400">{formatDate(entry.timestamp)}</span>
        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${actorClass}`}>
          {entry.actor}
        </span>
        <span className="text-sm text-slate-800">{entry.action.replace(/_/g, ' ')}</span>
        <StatusBadge status={entry.outcome} />
      </div>
      {metadataEntries.length > 0 && (
        <p className="mt-0.5 text-xs text-slate-500">
          {metadataEntries.map(([k, v]) => `${k}: ${String(v)}`).join(' · ')}
        </p>
      )}
    </li>
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

  return (
    <div className="space-y-6">
      <button onClick={onBack} className="text-xs text-slate-500 underline">
        ← Back
      </button>

      {isLoading && <p className="text-sm text-slate-500">Loading workflow instance…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {detail && (
        <>
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-lg font-semibold text-slate-900">{detail.workflow_name}</p>
                <p className="mt-1 text-sm text-slate-600">
                  {detail.employee_name ? `For ${detail.employee_name} · ` : ''}
                  Initiated by {detail.initiated_by_name ?? 'System'}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  Started {formatDate(detail.started_at)} · Updated {formatDate(detail.updated_at)}
                  {detail.completed_at ? ` · Completed ${formatDate(detail.completed_at)}` : ''}
                </p>
                {detail.current_step_key && (
                  <p className="mt-1 text-xs text-slate-400">
                    Current step: {detail.current_step_key}
                  </p>
                )}
              </div>
              <StatusBadge status={detail.status} />
            </div>
          </Card>

          <SectionCard title="Steps">
            {detail.steps.map((step) => (
              <StepCard key={step.id} step={step} />
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
            <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <ul className="space-y-1">
                {detail.audit_timeline.map((entry, index) => (
                  // No stable id on a synthesized timeline entry — index is
                  // fine, this list is never reordered or filtered in place.
                  <AuditTimelineRow key={index} entry={entry} />
                ))}
              </ul>
            </div>
          </SectionCard>
        </>
      )}
    </div>
  )
}
