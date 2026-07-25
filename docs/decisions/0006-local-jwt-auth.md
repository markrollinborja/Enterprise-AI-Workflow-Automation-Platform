# ADR-0006: Local JWT Auth, No Third-Party Provider

**Status:** Accepted — 2026-07-23

**Context:** Need role-based auth for 6 roles across a handful of demo users. Options: build local JWT auth, or integrate Auth0/Clerk/similar.

**Decision:** Local JWT (FastAPI + passlib/bcrypt + python-jose), 8-hour access tokens, no refresh-token flow, role enforced server-side via route dependencies.

**Alternatives considered:** Auth0/Clerk free tier — rejected: solves problems (external federation, social login, SSO) this project doesn't have, and adds an external account/service dependency for something a small local implementation demonstrates equally well. Refresh tokens — rejected for V1: real-production hygiene, not needed for a locally-run demo environment; documented as a known simplification rather than left unexplained.

**Consequences:** Fully self-contained, no external auth dependency, easy to explain end-to-end. Not production-grade session hygiene (no revocation, no refresh) — explicitly called out in security docs (Phase 15) as "what changes in a real production environment."
