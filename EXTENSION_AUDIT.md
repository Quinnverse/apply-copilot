# Browser extension audit — baseline `1902c19`

| Question | Finding |
|---|---|
| Exists / stack / manifest | Yes. Plain JavaScript/CSS/HTML Chrome/Edge extension, Manifest V3 (`extension/manifest.json`). |
| Content script | Injects floating toolbar on all URLs; scans fields, asks local backend for mapping, writes values, tries resume file upload, offers manual record action, watches text for success keywords. |
| Background | MV3 service worker proxies popup/content requests to `http://127.0.0.1:8787`; returns PDF as base64 data URL. |
| Popup / side panel | Popup exists for queue target, pasted JD matching, resumes. No side panel. |
| Detectable elements | `input` except hidden/submit/reset/button/image/radio/checkbox, plus `select` and `textarea`. No visibility/disabled filtering, custom controls, shadow roots, or iframe traversal. |
| Profile source | `/api/fill` reads `profile.job.json` via `current_profile()`; content receives mapped values. Empty fresh clone has no profile. |
| Field mapping | `filler.FIELD_RULES` then `FIELD_SYN`, using label/name/id/placeholder. Can return selectors for ID/name only; no reliable handle for anonymous fields. |
| Actual write | `document.querySelector(selector)`, then `.value = value` and input/change events. This can write plain fields; no after-write verification. |
| React/Vue | Unverified; direct property write does not use native setter, so controlled state can revert. |
| Select/radio/checkbox/date | Select value is assigned without checking option; radio/checkbox omitted; date gets raw profile string, format not normalized. |
| Dynamic forms | A new scan happens only when user clicks Fill again. MutationObserver only checks success text. |
| iframe / shadow DOM | Top-frame light DOM only (`all_frames` not set). Both unsupported. |
| ATS support | No platform-specific test evidence in repository; do not claim any supported ATS. |
| Submission | No automatic submit. “Record” is a separate user click. |
| Permissions/privacy | The MV3 manifest has no always-on content script and no `<all_urls>` host permission. The user must grant the current HTTP(S) site in the popup before `content.js` is injected; later pages on that granted site reinject through the service worker. Local no-token mode remains single-user. |

Main product gap: user sees no “found N / reliable M / confirm K / manual R” review before writes. The present Fill button changes every matched field immediately.

## Post-sprint state

- Toolbar now shows detected, fillable, confirm and manual counts with a checkbox per suggestion. No field changes until “填充勾选字段” is clicked.
- Suggestions are bound to scanned DOM elements, avoiding duplicate CSS selector collisions. Writes use native input/textarea setters and verify native select options. Radio groups and ISO month/date inputs have narrow support. Unsupported/custom controls remain manual.
- Popup can edit the existing `profile.job.json` basic and education fields. The background still bridges the same local API.
- 2026-09-30: replaced the `<all_urls>` content script with per-site optional host access. `scripting` is now used for injection after the popup's explicit permission request.
- Live loaded-extension checks: Greenhouse Boldly form 46 detected / 4 filled, Lever form 5 detected / 3 filled; no submit. See `FORM_COMPATIBILITY_MATRIX.md`.
