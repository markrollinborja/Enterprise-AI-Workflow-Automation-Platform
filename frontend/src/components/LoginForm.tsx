import { useState, type FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import { Button } from './ui/button'
import { Card, CardContent } from './ui/card'
import { Input } from './ui/input'
import { Label } from './ui/label'

export function LoginForm() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(email, password)
    } catch {
      setError('Incorrect email or password')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-sidebar-background p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary text-lg font-bold text-primary-foreground shadow-lg shadow-primary/30">
            M
          </div>
          <p className="mt-4 text-lg font-semibold text-sidebar-foreground">Meridian Flow</p>
          <p className="text-sm text-sidebar-muted-foreground">
            Enterprise Employee Workflow Automation
          </p>
        </div>

        <Card className="border-sidebar-border/50 shadow-xl">
          <CardContent className="pt-6">
            <p className="mb-4 text-sm font-medium text-foreground">Sign in to your account</p>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              {error && <p className="text-sm text-destructive">{error}</p>}

              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSubmitting ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="mt-4 text-center text-xs text-sidebar-muted-foreground">
          Demo users: see backend/app/db/seed.py (e.g. ava.thompson@cordant.io, password from
          your local .env / seed script).
        </p>
      </div>
    </div>
  )
}
