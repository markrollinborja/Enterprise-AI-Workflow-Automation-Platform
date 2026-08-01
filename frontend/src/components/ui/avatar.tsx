import * as React from 'react'
import { cn } from '@/lib/utils'

/** Initials-only avatar — no AvatarImage, since no part of this app stores
 * or displays a profile photo (demo users are seeded with just a name and
 * email). Kept as its own primitive rather than inlined at each call site
 * so the initials-from-name logic lives in exactly one place. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  const first = parts[0]?.[0] ?? ''
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : ''
  return (first + last).toUpperCase()
}

interface AvatarProps extends React.HTMLAttributes<HTMLSpanElement> {
  name: string
}

const Avatar = React.forwardRef<HTMLSpanElement, AvatarProps>(
  ({ className, name, ...props }, ref) => (
    <span
      ref={ref}
      className={cn(
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground',
        className,
      )}
      {...props}
    >
      {initials(name)}
    </span>
  ),
)
Avatar.displayName = 'Avatar'

export { Avatar }
