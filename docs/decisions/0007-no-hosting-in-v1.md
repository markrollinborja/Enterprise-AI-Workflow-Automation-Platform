# ADR-0007: No Hosting/Deployment in V1

**Status:** Accepted — 2026-07-23

**Context:** The original phase plan included Phase 17 (deployment to Render/Railway/Fly/Neon) as part of V1. Mark decided to defer this to a later version.

**Decision:** V1 success criteria is `docker compose up` running the full stack locally, plus a demo video/GIF/screenshots — no live hosted URL. Deployment moves out of V1 scope entirely.

**Alternatives considered:** Hosting on Render's free tier (verified still available, no card required, as of 2026-07-23) — viable, but adds cold-start unpredictability to a live demo and a maintenance surface (env config drift between local and hosted, keeping a free-tier DB alive) that isn't worth taking on before the local experience is solid.

**Also resolved as part of this decision:** confirmed none of this project's integrations require an inbound webhook receiver (Jira/Slack/Calendar are all called *outbound* via MCP tools; unlike Project #1, nothing here receives incoming webhooks) — so **ngrok is not needed** to run this locally, contrary to the initial assumption when scoping this out.

**Consequences:** No shareable live link until a later version — mitigated with a strong local demo video. Every environment-config decision (Phase 2 onward) should assume "runs via Docker Compose on a laptop" as the only supported environment for now; hosting-specific config (e.g. managed Postgres connection strings, CORS for a hosted frontend origin) is out of scope until revisited.
