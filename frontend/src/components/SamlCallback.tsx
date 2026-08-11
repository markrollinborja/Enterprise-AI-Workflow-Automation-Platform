import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { Card, CardContent } from './ui/card'

// Rendered when the browser lands on /auth/saml/callback — where the
// backend's POST /auth/saml/acs redirects to once it has already verified
// the signed assertion and resolved a local user (see
// backend/app/api/routes/saml.py). Unlike OidcCallback, there is no token
// exchange to perform here: the backend did the security-critical work
// server-side and this component's only job is to hand the token it
// carries to AuthContext, the same way any other login does, then scrub it
// from the URL so a page refresh or browser-history entry doesn't leave a
// live token sitting in the address bar.
export function SamlCallback() {
  const { loginWithToken } = useAuth()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const token = new URLSearchParams(window.location.search).get('token')

    if (!token) {
      setError('Sign-in did not return a token. Please try again.')
      return
    }

    loginWithToken(token)
      .then(() => {
        if (!cancelled) {
          window.history.replaceState({}, '', '/')
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError('Sign-in failed. Please try again.')
        }
      })

    return () => {
      cancelled = true
    }
    // Intentionally runs once: the token in the URL should be consumed and
    // scrubbed exactly once, not re-processed on a loginWithToken identity
    // change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-sidebar-background p-4">
        <div className="w-full max-w-sm">
          <Card className="border-destructive/30 shadow-xl">
            <CardContent className="space-y-3 pt-6 text-center">
              <p className="text-sm font-medium text-destructive">{error}</p>
              <a href="/" className="inline-block text-sm text-primary underline">
                Back to sign in
              </a>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return <div className="min-h-screen bg-sidebar-background" />
}
