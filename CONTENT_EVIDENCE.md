# Content evidence — observed during this sprint

Date: 2026-09-30. Use only these recorded observations in Quinnverse material; do not turn untested cases into claimed success stories.

| Observation | Evidence | Before → After |
|---|---|---|
| The extension wrote immediately after one click | Baseline `tests/extension_golden.py`; original `content.js` `doFill → applyPayload` | New review shows 8 detected / 6 fillable / 2 manual, with name still empty until confirmation. |
| Clean clone backend failed to import | `server.py` imported absent `apply.py`; FastAPI also absent in host Python | Installed declared backend requirements in isolated `.venv`; `local_apply.py` fallback now passes isolated HTTP smoke test. |
| Greenhouse custom question was misidentified as email | First public form run suggested `Email Management for Executives... → test@example.invalid` | Conservative long/question label guard removed that suggestion; final Greenhouse run suggests only first name, last name, email and phone. |
| Greenhouse removed the extension toolbar while rendering | First loaded-extension public page run found no `#ac-toggle` | Mutation observer now reinjects toolbar when removed; next loaded-extension run detected 46 fields and filled 4. |
| Native select could report success despite no matching option | Synthetic complex fixture | Missing school option now yields one write failure and stays blank. |
| Controlled input needed native setter | Synthetic controlled-state fixture | State updates to `Test User` after confirmed fill. |
| Resume file transport | Loaded MV3 extension + local backend + synthetic PDF | File attached to local fixture; actual ATS upload remains unverified. |
| Live public ATS pages | `tests/full_extension.py` | Greenhouse-hosted Boldly: 46 detected / 4 filled; Lever: 5 detected / 3 filled. No submit click; POST requests blocked in test. |
| Damaged token table could disable authentication | `server.py` previously guarded APIs only when `load_tokens()` returned entries | Auth now stays required after a configured token table is malformed, empty, or removed; `tests/tenant_isolation.py` verifies 401 responses. |
| Generated bookmarklet embedded profile values in a public static path | `gen_bookmarklet.py` and the previous `/static` mount | `/static/assistant.bookmarklet.js` now returns 404; the generated file is excluded from Git and deployment packages. Historic distribution of generated copies was not verified. |
| Separate users needed an actual isolation check | `tests/tenant_isolation.py` with disposable token A and B | Profile, resume, field memory, and application records stay in separate tenant directories in the local test. Live cloud isolation remains unverified. |
| Old deployment could overwrite user data and expose a token | Previous `deploy/package.py` copied local profile/PDF/state; `deploy_server.sh` replaced server data, printed a token, and opened port 8787 | Packaging now rejects old data directories and copies code only; deployment preserves server data, checks auth, and binds loopback. The new script has not been run on the server. |

Screenshots after synthetic fill: [Greenhouse](evidence/greenhouse-after-fill.png), [Lever](evidence/lever-after-fill.png). The pages and counts can change over time. Both images contain only synthetic applicant data.

Design cut: no LLM call for name/email/phone/education, no auto submit, no bot workflow, no new Application Package schema. Custom questions remain for the applicant.
