import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import {
  decideApproval,
  fetchApprovals,
  type ApprovalDecision,
  type ApprovalRequestResponse,
} from '../api/approvals'
import { useAuth } from '../context/AuthContext'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Input } from './ui/input'

export function ApprovalInbox() {
  const { token } = useAuth()
  const [approvals, setApprovals] = useState<ApprovalRequestResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notesByRequest, setNotesByRequest] = useState<Record<string, string>>({})
  const [decidingId, setDecidingId] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    fetchApprovals(token)
      .then(setApprovals)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load approvals'))
      .finally(() => setIsLoading(false))
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  async function handleDecision(approvalRequestId: string, decision: ApprovalDecision) {
    if (!token) return
    setDecidingId(approvalRequestId)
    setError(null)
    try {
      await decideApproval(token, approvalRequestId, decision, notesByRequest[approvalRequestId])
      // Decided items drop out of the inbox — refetch rather than splice
      // locally, since a decision can change what else is now pending
      // (e.g. approving manager_approval can immediately surface an
      // it_review_access request for a different approver, or none at all
      // if the AI didn't flag it).
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record decision')
    } finally {
      setDecidingId(null)
    }
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading approvals…</p>
  }

  if (error) {
    return <p className="text-sm text-destructive">{error}</p>
  }

  if (approvals.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2.5 pt-4 text-muted-foreground">
          <CheckCircle2 className="h-4 w-4 text-success" />
          <p className="text-sm">Nothing waiting on you right now.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      {approvals.map((approval) => (
        <Card key={approval.id}>
          <CardContent className="pt-4">
            <div>
              <p className="text-sm font-medium text-foreground">
                {approval.workflow_name} — {approval.step_name}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {approval.employee_name ? `For ${approval.employee_name} · ` : ''}
                Requires: {approval.approver_role} · step {approval.sequence_order}
              </p>
              <p className="mt-1 text-xs text-muted-foreground/70">
                Requested {new Date(approval.requested_at).toLocaleString()}
              </p>
            </div>

            <Input
              type="text"
              placeholder="Optional notes"
              value={notesByRequest[approval.id] ?? ''}
              onChange={(e) =>
                setNotesByRequest((prev) => ({ ...prev, [approval.id]: e.target.value }))
              }
              className="mt-3"
            />

            <div className="mt-3 flex gap-2">
              <Button
                onClick={() => handleDecision(approval.id, 'approved')}
                disabled={decidingId === approval.id}
                size="sm"
              >
                Approve
              </Button>
              <Button
                variant="outline"
                onClick={() => handleDecision(approval.id, 'rejected')}
                disabled={decidingId === approval.id}
                size="sm"
              >
                Reject
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
