# MVP readiness — 2026-09-30

**Decision: ready for a small, guided technical pilot; not yet ready for unassisted first-user distribution.** Quinnverse Apply Copilot Season 01 content production should wait until the remaining gates below are met. `CONTENT_EVIDENCE.md` contains factual development material, not a launch claim.

## What works now

- A clean checkout can start the FastAPI backend after installing `deploy/requirements.txt`. The extension popup can save a basic profile to `profile.job.json`.
- The actual unpacked MV3 extension, connected to that backend, scans the page, shows suggestions and counts, waits for user confirmation, writes selected native fields, and stops before submit.
- Local form: 8 fields detected, 6 filled after confirmation, 2 manual. A synthetic PDF was attached to its file input.
- Public ATS checks with synthetic data: [Greenhouse-hosted Boldly](https://job-boards.greenhouse.io/boldly/jobs/4005594006), 46 detected / 4 filled; [Lever](https://jobs.lever.co/usasurveyjob/fe664ea7-bfc2-4e3d-913b-1de52c59fa41/apply), 5 detected / 3 filled. No submission; public-page POST requests blocked.
- Backend smoke: health, profile save/read, deterministic mapping, application record, duplicate rejection and CORS origin restriction passed in a disposable data directory.

## Remaining blocking issues for unassisted users

1. **Setup and onboarding:** users must run a Python backend and load an unpacked extension in developer mode. The popup covers only six profile fields; PDF import still does not parse a profile.
2. **Coverage:** only two specific public ATS pages have been tested. Custom dropdowns, cross-origin iframes, shadow DOM and multi-step applications remain unsupported or unverified. Greenhouse's 46 detected elements produced only 4 safe suggestions.
3. **Name semantics:** first/last split works for whitespace-separated test names; Chinese names without separators are deliberately left manual until the user can set given/family names explicitly.
4. **Resume upload on real ATS:** synthetic PDF attachment to a local file input passed, but upload widgets on the tested ATS pages were not verified.
5. **Distribution privacy:** `<all_urls>` content-script scope remains broad. Narrow installation/activation permission flow before broad release.
6. **Shared deployment:** the security branch is live. A second disposable two-token test passed for profile, resume and field-memory isolation; the backend now binds loopback, the generated bookmarklet is gone, and tenant files have private permissions. The domain has no matching HTTPS certificate or working DNS resolution, so its HTTP application entry intentionally returns 503. See `PRIVACY_SECURITY_AUDIT.md`; DNS and HTTPS remain blocking before any shared pilot.

## Quality gates before changing this decision

Run the loaded extension on several more live ATS forms and at least one multi-step form with consenting pilot users, without submitting test applications. Record field-level correctness and failures in `FORM_COMPATIBILITY_MATRIX.md`. Verify real resume upload widgets, refine profile onboarding and permissions, then rerun `tests/backend_smoke.py`, `tests/extension_golden.py` and `tests/full_extension.py`.
