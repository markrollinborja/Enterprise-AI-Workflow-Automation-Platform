# Authentication

## Approach: local JWT

FastAPI issues a signed JWT on login (`passlib`/`bcrypt` for password hashing, `python-jose` for signing/verification). The token carries `user_id`, `role`, and `employee_id` (nullable) as claims. Every protected route depends on a `get_current_user` dependency that decodes the token and a `require_role(...)` dependency that checks the claim against the route's allowed roles.

## Why not Auth0/Clerk/a full OAuth provider

Evaluated and rejected for V1: they solve problems this project doesn't have (external user federation, social login, SSO) and add an external dependency + account setup for something a 40-line local implementation demonstrates just as well for portfolio purposes. Local JWT is also easier to explain end-to-end in an interview — there's no "and then a third-party service does the rest" gap in the explanation. Section 9 of the project spec explicitly says to prefer this.

## Token lifetime

8-hour access token, no refresh-token flow. This is a documented simplification, not an oversight: a real production system would need short-lived access tokens plus refresh tokens plus revocation; for a local demo environment where the person testing it re-logs-in rarely, the operational cost of refresh-token infrastructure isn't worth it. Documented in `docs/architecture/` (here) and called out again in the security notes (Phase 15) as "what would need to change for production."

## Roles enforced server-side

Six roles: `employee, manager, hr, it, security, administrator`. Enforcement happens in the FastAPI dependency layer, not just hidden/disabled in the frontend — a request from an `employee` token to an HR-only route is rejected with 403 regardless of what the UI shows, which is what makes the RBAC claim testable (Phase 14 includes permission tests that hit routes directly with the wrong role's token).

## Demo users

Seeded at startup (Phase 4), one per role, fictional company (name TBD in Phase 16 demo-data pass): an HR coordinator, a hiring manager, an IT admin, a security approver, a regular employee, and a platform administrator. Passwords are dev-only, documented in `.env.example`/seed script — never real credentials, never committed as secrets (there's nothing secret about a local demo password, but it still won't live in version control as a hardcoded production-looking value).
