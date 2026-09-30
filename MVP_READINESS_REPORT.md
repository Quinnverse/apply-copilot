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
3. **Name semantics:** first/last split works for whitespace-separated test names. Users can now set explicit family/given names in the popup for Chinese or other non-whitespace names; the real popup flow still needs manual-browser verification.
4. **Resume upload on real ATS:** synthetic PDF attachment to a local file input passed, but upload widgets on the tested ATS pages were not verified.
5. **Distribution privacy:** resolved for the extension: the user explicitly enables each site before injection. Validate this flow in a real browser before broad release.
6. **Shared deployment:** the security branch is live over HTTPS. A second disposable two-token test passed for profile, resume and field-memory isolation; the backend binds loopback, the generated bookmarklet is gone, tenant files have private permissions, the public health endpoint reports `auth_ready: true`, and anonymous profile access returns 401. HTTP redirects to HTTPS. See `PRIVACY_SECURITY_AUDIT.md`. This clears the deployment privacy gate for a small guided technical pilot, while the setup, form-coverage and broad-permission gates above still prevent unassisted distribution.

## Quality gates before changing this decision

Run the loaded extension on several more live ATS forms and at least one multi-step form with consenting pilot users, without submitting test applications. Record field-level correctness and failures in `FORM_COMPATIBILITY_MATRIX.md`. Verify real resume upload widgets, refine profile onboarding and permissions, then rerun `tests/backend_smoke.py`, `tests/extension_golden.py` and `tests/full_extension.py`.
