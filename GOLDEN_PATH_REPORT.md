# Golden Path report — baseline

Date: 2026-09-30. Test data is synthetic. No application was submitted.

| Step | Baseline result | Evidence / failure |
|---|---|---|
| Resume/Profile | Partial | Synthetic `profile.job.json` shape mapped by `filler.py`; no resume parsing. |
| Open application | Working in fixture | `test_form.html` loaded in headless Edge. |
| Extension detect | Partial | Toolbar appears after script injection, but it does not show a field count. |
| Identify fields | Partial | `input/select/textarea` only; no radio/checkbox. |
| Match existing data | Partial | `filler.build_fill_payload` mapped six fixture fields. |
| Suggest | Broken | No review list; suggestions are not visible before fill. |
| User confirm | Broken | Single click immediately writes all values. |
| Fill | Partial | Baseline fixture: name/email/select populated; two unmatched fields. No after-write verification. |
| Review | Partial | User can inspect the webpage after fill; no extension review checklist. |
| STOP before submit | Working | Fixture submit listener remained false. |

Baseline command: `python tests/extension_golden.py`. The test uses the real content script, real `filler.py` mapping, synthetic profile, and a mocked backend transport. It cannot establish live ATS compatibility. Backend import is currently blocked by absent external `apply.py`; host Python also initially lacked FastAPI.

Live ATS filling was not run: no user credentials or test accounts were supplied, and no public form was confirmed safe to fill without creating an application. This remains an explicit first-user trial gate.

## Final rerun — loaded MV3 extension + local backend

Command: `.venv/Scripts/python tests/full_extension.py`. A disposable profile (`Test User`, `test@example.invalid`, synthetic phone) was served by the real FastAPI backend. Edge loaded the unpacked MV3 extension. All POST requests from the public ATS tabs were blocked in the test harness. No submit control was clicked.

After the per-site permission change, the same loaded-extension harness confirmed that the local form has no toolbar before permission is granted. Headless Chromium cannot approve the browser's optional-host permission prompt, so the post-grant injection path still requires a manual Chrome/Edge check. `tests/extension_golden.py` continues to verify the confirmed fill behavior with the real content script and synthetic data.

| Page | Detected | Suggested / written | Confirmation | Result |
|---|---:|---:|---|---|
| Local `test_form.html` | 8 | 6 | Name empty before confirmation; `Test User` after | Pass; synthetic PDF attached to native file input |
| [Greenhouse-hosted Boldly form](https://job-boards.greenhouse.io/boldly/jobs/4005594006) | 46 | 4 | Review shown before write | First/last name, email, phone filled; custom questions untouched |
| [Lever application form](https://jobs.lever.co/usasurveyjob/fe664ea7-bfc2-4e3d-913b-1de52c59fa41/apply) | 5 | 3 | Review shown before write | Full name, email, phone filled; location/company untouched |

The first Greenhouse run exposed a false positive: “Email Management for Executives...” was mapped to the email address. A guard for long/question-like labels removed that suggestion; rerun showed only the four basic fields. A loaded-extension run also revealed that Greenhouse removed the injected toolbar during page rendering. The content script now reinjects it when removed; rerun passed. These are observed bugs, not hypothetical compatibility claims.

The synthetic suite also exercised a two-step light-DOM form: it filled the name after confirmation, replaced the step content, then rescanned and filled email after a separate confirmation. Real ATS multi-step flows, genuine application submission, and resume upload widgets on these pages remain unverified. The extension only wrote synthetic data and stopped before submit.
