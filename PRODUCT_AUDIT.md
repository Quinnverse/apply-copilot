# Product audit — 2026-09-30

Baseline: `main` at `1902c19`. Status describes the checked-out repository, not claims in README or old QA reports. Personal runtime files are intentionally absent.

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Resume import | PARTIAL | `server.py` `/api/resume`, `copilot.py register-resume` | Upload stores a file; no text extraction. Backend currently cannot import without external `apply.py`. |
| Resume parsing | PLANNED_ONLY | No PDF parsing path in source | Profile must be supplied separately. |
| Career/Profile data | PARTIAL | `copilot.py init-profile`, `profile.job.json` schema v1 | Requires external skill profile; no sample onboarding data. |
| Profile editing | PARTIAL | `/api/profile` GET/PUT and dashboard | Backend startup dependency blocks clean clone. |
| Application Package | PARTIAL | `copilot.py kit` outputs checklist, answers and fill artifacts | CLI path exists; not a canonical, editable application context shared with extension. |
| Browser Extension | PARTIAL | `extension/` MV3 popup/content/background | UI exists, but unconfirmed immediate fill and backend startup blocker. |
| Form detection | PARTIAL | `extension/content.js scanFields()` | Only light DOM input/select/textarea; omits radios and checkboxes; no prefill count. |
| Field mapping | PARTIAL | `filler.py build_fill_payload` | Broad keyword matching can confuse names; selector construction can fail or collide. |
| Form filling | PARTIAL | `content.js setVal` | Direct `.value` write, no selected option verification or controlled input support. |
| User confirmation | BROKEN | `doFill()` immediately calls `applyPayload()` | No per-field preview/approval. |
| Human submission | WORKING | No submit click in extension; test fixture has submit button | Human remains responsible for submit. |
| Application tracking | PARTIAL | queue endpoints and `/api/mark` | `apply.py` is external and absent; cannot run from clone. |
| JD capture | PARTIAL | Popup textarea + `/api/match` | Manual paste only; no page capture. |
| Custom questions | PARTIAL | `copilot.py` answer drafts | No in-page question drafting or safe mapping. |
| Data persistence | PARTIAL | JSON files and tenant paths | Runtime data excluded; local startup and multi-user behavior need independent live tests. |
| Privacy/security | PARTIAL | local host target, optional token, no auto submit | `<all_urls>` injection, excess manifest permissions, and unauthenticated local API with wildcard CORS. |
| Deployment | PARTIAL | `deploy/` systemd/package scripts | External skill dependencies and live deployment not verified. Packager has machine-specific paths; deployment script uses destructive data sync and stale token extraction. Do not run it without separate review. |

## Run evidence

- `python -m py_compile copilot.py filler.py server.py app_desktop.py app_desktop_qt.py` passed.
- `python -c "import fastapi"` failed: dependency not installed in the host Python.
- `apply.py` and `gen_submit_list.py` are absent from tracked files and this workspace. `server.py` imports `apply` at module import time.
- Prior `FIX_REPORT_2026-09-12.md` says its QA passed, but its `_qa*` test assets are absent from this repository. It primarily covers the desktop assistant, not the current extension.
- Desktop paths are present: `app_desktop_qt.py` (PyQt6 WebEngine), `app_desktop.py` (pywebview fallback), and `assistant.js`/`assistant_bridge.py`. They were read for architecture and compiled, but the host has neither PyQt6 nor pywebview, so desktop interaction is **UNVERIFIED** in this sprint.
- History inspected: initial sanitized commit `bd88dfc`, token UX `503b22f`, multi-tenant `1902c19`. No tracked automated test suite or CI workflow.

## Product shape

`profile.job.json` is the existing canonical career profile. `kit` is a generated per-job artifact. Reuse both: feed extension mapping from the profile and use kit/JD context only for complex answers. Simple identity and education fields should remain deterministic. No LLM is currently required for those fields.

## Post-sprint correction

The table above is the pre-change audit. The clean clone now starts with a bundled `local_apply.py` fallback, and the extension popup can edit six basic profile fields. Resume parsing remains absent; the Application Package CLI still uses the external autumn skill for its tracking command. The loaded extension and local API were exercised together on a local form and two public ATS forms. See `GOLDEN_PATH_REPORT.md` for the results. This does not validate the production cloud deployment or all tenant paths.
