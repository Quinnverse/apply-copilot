# MVP backlog and minimal change plan

## P0 — Blocking

1. Fresh clone backend cannot start because `apply.py` is an undeclared external import. Provide a narrow local store fallback while keeping the external integration when available.
2. Fill has no preview or user confirmation. Show detected/mapped counts and explicit checkboxes; write only chosen fields.
3. Unsafe write reporting: selectors can collide and select values can silently fail. Bind suggestions to scanned elements and verify writes before reporting success.

## P1 — Major friction

1. Make controlled text inputs work with native setters and bubbling events.
2. Cover safe native radio/checkbox/date cases; leave uncertain options for manual review.
3. Reduce extension permissions and avoid injecting UI until user opens it on a page.
4. Clearly distinguish unsupported fields and make rescanning dynamic/multi-step forms simple.

## P2 — Enhancement

Shadow DOM, cross-origin frames, custom dropdown/date picker adapters, better JD capture, profile onboarding and per-site mapping memory.

## P3 — Future / Pro

Semantic mapping and JD-aware answer drafting only for ambiguous/open questions; no automatic submission or mass apply.

## Execution order

Keep `profile.job.json` and existing kit. Fix backend startup, then extension preview/verified fill. Run offline browser regression after P0, add narrow P1 coverage, rerun Golden Path. Do not claim ATS compatibility before live trials.

## Sprint outcome

- P0 1 closed: `local_apply.py` fallback starts a clean checkout and records user-confirmed applications; external skill path remains supported.
- P0 2 closed: preview, counts, checkboxes and explicit fill action. No write before confirmation.
- P0 3 closed for native controls: scanned element binding, option verification and failure count. A real Greenhouse false positive led to a conservative long-question guard.
- P1 1 closed for tested controlled inputs through native setter plus events.
- P1 2 partial: native radio/month/date supported in narrow cases; custom widgets remain manual.
- P1 3 closed in code: the manifest now has no always-on content script or `<all_urls>` host permission. The popup asks the user to enable the current HTTP(S) site, then injects with `scripting`; the background reinjects only after a user-granted site reload. `tests/extension_permissions.py` verifies the manifest gate. A manual Chrome/Edge permission-flow check remains before broad distribution.
- P1 4 closed for light DOM: manual rescan works and toolbar reinjects after site DOM replacement. A synthetic two-step form fills each step only after a separate confirmation. Real ATS multi-step flows are still unverified.

Next blocking work for unassisted distribution: test more ATS and multi-step pages with real user data under consent, package the local backend/extension setup, and verify actual PDF upload on supported ATS pages. These were deliberately not represented as complete by local/synthetic tests.

2026-09-30 setup increment: `start_backend.bat` no longer relies on a machine-specific Python path. It creates a project-local `.venv`, installs the declared backend requirements on first run, starts the loopback backend and opens the dashboard. Its Windows double-click flow is not yet UI-verified in this sprint.

2026-09-30 name increment: profile editing now offers optional explicit `family_name` and `given_name`. These map to split First/Last name fields; a Chinese full name remains manual unless the user supplies those values. `tests/extension_golden.py` covers both the conservative and explicit cases.
