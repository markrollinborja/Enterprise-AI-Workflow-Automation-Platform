import { API_BASE_URL } from './client'

export interface DashboardSummaryResponse {
  active_workflows: number
  pending_approvals: number
  failed_workflows: number
  completed_workflows: number
  avg_completion_seconds: number | null
  requests_by_type: Record<string, number>
  requests_by_department: Record<string, number>
}

/**
 * Mirrors backend/app/schemas/dashboard.py's WorkflowInstanceSummaryResponse.
 * The three failed_* fields are only ever populated when status === "failed"
 * — see that schema's docstring for why the Failed Workflows page (Phase
 * 12c) reuses this same shape via ?status=failed instead of a second type.
 */
export interface WorkflowInstanceSummaryResponse {
  id: string
  workflow_key: string
  workflow_name: string
  employee_name: string | null
  initiated_by_name: string | null
  status: string
  current_step_key: string | null
  started_at: string | null
  updated_at: string
  completed_at: string | null
  failed_step_key: string | null
  failure_reason: string | null
  failed_attempt_count: number | null
}

export interface WorkflowStepDetailResponse {
  id: string
  step_key: string
  step_type: string
  status: string
  input_data: Record<string, unknown> | null
  output_data: Record<string, unknown> | null
  attempt_count: number
  scheduled_at: string | null
  external_ref: string | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
}

export interface ApprovalDecisionDetailResponse {
  id: string
  decided_by_name: string
  decision: string
  notes: string | null
  decided_at: string
}

export interface ApprovalDetailResponse {
  id: string
  step_key: string
  approver_role: string
  assigned_user_name: string | null
  status: string
  sequence_order: number
  due_at: string | null
  created_at: string
  decisions: ApprovalDecisionDetailResponse[]
}

export interface AIExecutionDetailResponse {
  id: string
  step_key: string
  task_type: string
  input_summary: string
  output_json: Record<string, unknown> | null
  confidence_score: number | null
  requires_human_review: boolean | null
  model_used: string
  tokens_used: number | null
  status: string
  error_message: string | null
  created_at: string
}

export interface MCPToolExecutionDetailResponse {
  id: string
  step_key: string | null
  tool_name: string
  caller: string
  input_params: Record<string, unknown>
  output_result: Record<string, unknown> | null
  status: string
  mock_mode: boolean
  duration_ms: number | null
  error_message: string | null
  created_at: string
}

export interface NotificationDetailResponse {
  id: string
  recipient_name: string
  type: string
  channel: string
  status: string
  title: string
  body: string
  created_at: string
  read_at: string | null
}

export interface AuditTimelineEntryResponse {
  timestamp: string
  actor: string
  actor_type: string
  action: string
  resource_type: string
  resource_id: string | null
  workflow_instance_id: string | null
  workflow_name: string | null
  outcome: string
  metadata: Record<string, unknown>
}

export interface WorkflowInstanceDetailResponse {
  id: string
  workflow_key: string
  workflow_name: string
  status: string
  input_data: Record<string, unknown>
  employee_name: string | null
  initiated_by_name: string | null
  current_step_key: string | null
  started_at: string | null
  updated_at: string
  completed_at: string | null
  steps: WorkflowStepDetailResponse[]
  approvals: ApprovalDetailResponse[]
  ai_executions: AIExecutionDetailResponse[]
  mcp_tool_executions: MCPToolExecutionDetailResponse[]
  notifications: NotificationDetailResponse[]
  audit_timeline: AuditTimelineEntryResponse[]
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * Every /dashboard/*, /workflow-instances*, and /audit-log route is a plain
 * authenticated GET with the same error-unwrapping — one helper here rather
 * than repeating the same six lines in every fetch function in this file.
 */
async function getJson<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? `Request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchDashboardSummary(token: string): Promise<DashboardSummaryResponse> {
  return getJson<DashboardSummaryResponse>('/dashboard/summary', token)
}

export function fetchWorkflowInstances(
  token: string,
  status?: string,
): Promise<WorkflowInstanceSummaryResponse[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return getJson<WorkflowInstanceSummaryResponse[]>(`/workflow-instances${query}`, token)
}

export function fetchWorkflowInstanceDetail(
  token: string,
  instanceId: string,
): Promise<WorkflowInstanceDetailResponse> {
  return getJson<WorkflowInstanceDetailResponse>(`/workflow-instances/${instanceId}`, token)
}
