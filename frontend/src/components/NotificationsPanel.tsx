import { useCallback, useEffect, useState } from 'react'
import { fetchNotifications, markNotificationRead, type NotificationResponse } from '../api/notifications'
import { useAuth } from '../context/AuthContext'

function timeAgo(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function NotificationsPanel() {
  const { token } = useAuth()
  const [notifications, setNotifications] = useState<NotificationResponse[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token) return
    setIsLoading(true)
    fetchNotifications(token)
      .then(setNotifications)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load notifications'))
      .finally(() => setIsLoading(false))
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  async function handleMarkRead(id: string) {
    if (!token) return
    try {
      const updated = await markNotificationRead(token, id)
      setNotifications((prev) => prev.map((n) => (n.id === id ? updated : n)))
    } catch {
      // Non-critical — leave the notification as unread in the UI on failure.
    }
  }

  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading notifications…</p>
  }

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }

  const unreadCount = notifications.filter((n) => !n.read_at).length

  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
        <span className="text-xs text-slate-500">
          {unreadCount} unread of {notifications.length}
        </span>
      </div>
      <ul className="divide-y divide-slate-100">
        {notifications.map((n) => (
          <li
            key={n.id}
            className={`flex items-start justify-between gap-3 px-4 py-3 ${
              n.read_at ? '' : 'bg-blue-50/50'
            }`}
          >
            <div>
              <p className="text-sm font-medium text-slate-900">{n.title}</p>
              <p className="mt-0.5 text-sm text-slate-600">{n.body}</p>
              <p className="mt-1 text-xs text-slate-400">{timeAgo(n.created_at)}</p>
            </div>
            {!n.read_at && (
              <button
                onClick={() => handleMarkRead(n.id)}
                className="shrink-0 rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-600"
              >
                Mark read
              </button>
            )}
          </li>
        ))}
      </ul>
      {notifications.length === 0 && (
        <p className="p-4 text-sm text-slate-500">No notifications yet.</p>
      )}
    </div>
  )
}
