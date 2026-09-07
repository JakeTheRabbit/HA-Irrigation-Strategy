# Operator Dashboard Implementation Plan

> For agentic workers: use Superpowers subagent-driven-development with explicit ownership and independent review. User authorised sustained implementation without repeated design approvals.

**Goal:** Make daily room monitoring and irrigation configuration clear, reliable and usable on desktop and mobile.
**Architecture:** Typed React UI backed by an isolated HA adapter. Single HTML build preserves existing static deployment contracts. Retain specialist tools through explicit maintenance navigation.
**Tech Stack:** React, TypeScript, Vite, Tailwind CSS, shadcn/ui, Radix, Lucide, Vitest and Playwright.
**Spec:** docs/superpowers/specs/2026-09-07-operator-dashboard-design.md

## Global Constraints
- Missing data is unavailable, never fabricated live data or zero.
- UI components never construct entity IDs; frontend/src/lib/types.ts is the shared interface.
- F1 legacy aliases cannot fall through to F2; all writes target entities that actually exist.
- No direct valve/pump actions or cross-room recipe services.
- Demo never calls live endpoints. Tokens are never committed or stored persistently.
- Existing untracked aigrow-ops.html files are user-owned and must remain untouched.
- No live HA changes, remote deployment, push or publication in this task.

## Task 1: Baseline audit and adapter
Owner: data worker; audit findings supplied by independent reviewer.
Files: frontend/src/lib/{model,client,demo,use-controller}.ts and focused .test.ts files.
Interface: implement Controller from types.ts via useController(). Export pure model helpers for fixture tests.
- [x] Reproduce unsafe room resolution, unavailable values and failed writes in focused tests before implementation.
- [x] Resolve room and zone metadata from actual entity states; preserve legacy F1 mapping.
- [x] Implement bounded transport, session authentication, generation-safe polling and verified number/switch/select writes.
- [x] Implement explicit isolated demo fixture and history data.
- [x] Run Vitest adapter tests; record commands and output in audit report.

## Task 2: shadcn operator experience
Owner: UI worker. Files: frontend/src/{App.tsx,styles.css}, frontend/src/pages/*, feature components (excluding generated ui/*).
Interface: App calls useController() and consumes Controller; parent supplies shadcn ui primitives and dependencies.
- [x] Implement sidebar, mobile navigation, connection bar, room selector, theme and task routes.
- [x] Implement overview, zones and detail, strategy draft/review/apply, activity/filter/export, sensors, settings and help.
- [x] Preserve draft state until apply/discard; display partial write failures explicitly.
- [x] Explain empty, loading, disconnected and unavailable states with useful next actions.
- [x] Run TypeScript validation; parent runs browser checks on integrated result.

## Task 3: Build, packaging and end-to-end verification
Owner: primary agent. Files: frontend build config/scripts, primary/legacy HTML entry points, tests, documentation, workflows.
- [x] Generate shadcn primitives using official registry and pin npm lockfile.
- [x] Build one standalone HTML file and synchronize addon assets without changing deployment/runtime engine state.
- [x] Unify entry points and clear return links; preserve room/demo query parameters.
- [x] Browser verify desktop/mobile, all routes, forms, filters, accessibility, failure states and navigation history.
- [x] Run offline Python checks and frontend build/tests.
- [x] Request independent diff review, resolve material findings, document remaining limitations and show preview.

## Progress and decisions
- Baseline has two failing tests/test_dashboard_layout.py checks against stale CSS strings. Backend baselines: integration 85 pass, controller 14 pass, pure core 46 pass. Source audit will record details.
- The primary refactor preserves f2-classic.html to retain specialist workflows while replacing daily pages.

## Task 4: Proven controller safety defects
Owner: system_audit worker. Source scope: addons/f2_control/f2_control/controller.py and controller regression tests.
- [x] Account monotonic valve-open time including bounded HA read latency.
- [x] Apply daily budget to ordinary blind fallback/copy without removing real measured emergency exemption.
- [x] Persist hardware-close faults and inhibit shared hardware until explicit disarm plus verified OFF readback.
- [x] Prove regressions red then green and run existing state-migration/controller suites.
- [x] Preserve existing active-shot system/auto/zone disable semantics and document the distinction; no unrelated algorithm changes.

## Completed verification

All four workstreams are implemented and independently reviewed. See `docs/audits/2026-09-07-final-verification.md` for consolidated checks, scope, screenshots and remaining system limitations. Local preview: `http://127.0.0.1:5198/f2.html?demo`. No live deployment was performed.
