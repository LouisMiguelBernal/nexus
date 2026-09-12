# ADR 0005: Keep Next.js; ship a static export served from the asar

Status: accepted · 2026-09-11

## Context

The packaged app runs `next start` against the **source tree's** `.next` directory through a hard-coded absolute path. Editing a `.tsx` changes nothing in the app until someone runs `next build`; this bit the operator twice in one week. The asar bundles `.next` and `node_modules` (1.77 GB) it never reads. The app has zero server components and a single route. Alternatives considered: `output: 'standalone'` (still a Node server on a port, still bundles `node_modules`) and a Vite SPA (faster builds, but abandons the stated stack for ~4 days of churn).

## Decision

Keep Next.js 16 App Router with `output: 'export'`. Electron serves `frontend/out/` from inside the asar via `protocol.handle('nexus', …)`; `next dev` on :3000 remains the development path. Packaging ships `electron/**`, `out/**`, `package.json` (asar ≈ 10–30 MB); the backend ships as `extraResources` and is bootstrapped into a `uv`-managed venv on first run. A build stamp (`VERSION` + git SHA) is shown in the status bar and mismatches are flagged.

## Consequences

- The stale-build class of bug disappears for the packaged app: the app can only ever serve the build it was packaged with.
- Constraints of static export apply: no server components, `useSearchParams` under Suspense, unoptimised images. None of these affect the current app.
- Development keeps HMR; the two paths differ only in how the built assets are served.
