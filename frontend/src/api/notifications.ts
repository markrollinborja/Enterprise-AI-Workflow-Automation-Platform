import { API_BASE_URL } from './client'

export interface NotificationResponse {
  id: string
  workflow_instance_id: string | null
  type: string
  title: string
  body: string
  created_at: string
  read_at: string | null
}

interface ApiErrorBody {
  error?: { type: string; message: string }
}

/**
 * GET /notifications — no role gate, every authenticated user has their own
 * list (same pattern as GET /approvals: the filtering to "yours" happens
 * server-side, see app/api/routes/notifications.py).
 */
export async function fetchNotifications(token: string): Promise<NotificationResponse[]> {
  const response = await fetch(`${API_BASE_URL}/notifications`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to load notifications')
  }
  return response.json() as Promise<NotificationResponse[]>
}

export async function markNotificationRead(
  token: string,
  notificationId: string,
): Promise<NotificationResponse> {
  const response = await fetch(`${API_BASE_URL}/notifications/${notificationId}/read`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null
    throw new Error(body?.error?.message ?? 'Failed to mark notification read')
  }
  return response.json() as Promise<NotificationResponse>
}
