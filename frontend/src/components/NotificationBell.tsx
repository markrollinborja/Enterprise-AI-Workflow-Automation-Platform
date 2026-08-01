import { useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { fetchNotifications } from '../api/notifications'
import { useAuth } from '../context/AuthContext'

/** Header bell icon + unread badge — the standard top-nav pattern (Gmail,
 * Slack, Linear) for "something needs your attention" at a glance, separate
 * from the full Notifications list already on the Home page. Fetches its
 * own copy of the same GET /notifications response rather than sharing
 * state with NotificationsPanel: this app has no shared client-side cache
 * (React Query, etc. — deliberately not added, see ADR-0008's reasoning
 * about not adding dependencies the app doesn't need), so the badge count
 * can lag a few seconds behind marking something read in the panel below.
 * Acceptable for a portfolio demo; a real product would share one fetch. */
export function NotificationBell({ onClick }: { onClick: () => void }) {
  const { token } = useAuth()
  const [unreadCount, setUnreadCount] = useState(0)

  useEffect(() => {
    if (!token) return
    fetchNotifications(token)
      .then((notifications) => setUnreadCount(notifications.filter((n) => !n.read_at).length))
      .catch(() => {
        // Non-critical UI chrome — a failed background fetch shouldn't
        // surface an error state in the header.
      })
  }, [token])

  return (
    <button
      onClick={onClick}
      className="relative flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      aria-label={unreadCount > 0 ? `${unreadCount} unread notifications` : 'Notifications'}
    >
      <Bell className="h-5 w-5" />
      {unreadCount > 0 && (
        <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-destructive-foreground">
          {unreadCount > 9 ? '9+' : unreadCount}
        </span>
      )}
    </button>
  )
}
