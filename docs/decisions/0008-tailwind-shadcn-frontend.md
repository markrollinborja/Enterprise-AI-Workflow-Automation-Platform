# ADR-0008: Tailwind CSS (+ shadcn/ui later) Over Material UI

**Status:** Accepted — 2026-07-25

**Context:** The spec asks for one lightweight, professional component approach for an internal enterprise dashboard look, comparing Material UI, shadcn/ui, and plain Tailwind CSS.

**Decision:** Tailwind CSS as the styling foundation from Phase 2 onward (Tailwind v4, via the `@tailwindcss/vite` plugin — no `tailwind.config.js`/`postcss.config.js` needed under v4's simplified setup). `shadcn/ui` components get layered in starting Phase 12 (dashboard) when there's an actual component inventory to build against, rather than installed now with nothing using it yet.

**Alternatives considered:** Material UI — rejected: its default look reads as "Google product," not "internal enterprise tool," and fighting Material Design defaults to get a Linear/Vercel-style dashboard aesthetic costs more time than it saves. Plain Tailwind with hand-rolled components for the whole project — viable, but shadcn/ui's copy-in (not npm-dependency) component model gives accessible, well-built primitives (dialogs, tables, dropdowns) for the approval-inbox and workflow-detail screens without adding a runtime UI-kit dependency.

**Consequences:** Phase 2's actual UI surface (one connectivity-check page) only needs Tailwind, so that's all that's installed now — keeps this phase's dependency footprint honest. Phase 12 revisits this ADR when shadcn/ui components are actually added.
