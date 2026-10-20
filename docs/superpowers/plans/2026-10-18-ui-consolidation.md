# UI Consolidation and All Zones Implementation Plan

> **For agentic workers:** Use the assigned parallel workstreams and verification-before-completion. Work in codex/ui-consolidation; preserve unrelated untracked files.

**Goal:** Implement the approved dashboard ownership map, add a facility-wide All zones landing page and a configurable browser default, then push the reviewed branch.

**Architecture:** Keep existing HA-derived state and backend commands. Consolidate presentations around canonical editors, shared charts and context-preserving navigation. All zones builds each room from the same controller snapshot; landing preferences never write equipment state.

**Tech Stack:** React, TypeScript, Vite, existing shadcn components and HA native theme variables.

**Spec:** docs/superpowers/specs/2026-10-18-ui-consolidation.md (approved mockup design and audit)

## Global Constraints
- Preserve F1/F2 separation, permission checks, revision guards, missing-data semantics and backend safety behavior.
- Feed EC is distinct from pore EC; estimated delivery is distinct from measured uptake.
- Explicit hash/view links override the browser landing preference; unavailable storage falls back safely to All zones.
- No product controls may disappear when converting Features into a directory. Registry-only controls must have canonical destinations.
- Push is authorized. Do not deploy to HA or promote a production release implicitly.

## Review Focus
- A stale or disabled room remains visible without implying live readings.
- Duplicate zone numbers in different rooms must navigate to the intended room.
- Invalid preferences or blocked storage cannot prevent startup.
- Active schedules retain exclusive target ownership and separate save/arm operations.
- Canonical configuration editors must not overwrite more recent values from another persistence path.

## Tasks
- [x] Root: landing preference validation/routing tests (RED), implementation (GREEN); all-room zone view and room-aware zone navigation.
- [x] Configuration worker: feature-owner inventory, canonical controls and remove duplicate editors without losing capabilities; targeted tests.
- [x] Monitoring worker: one Zone chart/explanation, canonical History explorer, one water table, concise Today.
- [x] Irrigation worker: unified Current day/Calendar workspace, preserving actual target/schedule ownership and drafts.
- [x] Root: integrate, run frontend tests/typecheck/build and browser desktop/mobile checks, independent final review, update documentation/screenshots, commit and push branch with PR.

## Progress
Initial source baseline 4853f853; remote main/testing at 7800759e. Earlier setup-save fix remains included. User explicitly approved layout A/ownership map and added All zones plus default-view preference.

Review fixes: propagated Zone canonical draft dirty state; retained Timeline room-only filter; synchronized focused zone after discard confirmation. Browser regressions passed. Packaging now leaves unaddressed landing aliases to preference resolution and preserves explicit legacy views.
