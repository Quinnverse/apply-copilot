# Form compatibility matrix — baseline

`TESTED` means an offline fixture was exercised. No ATS platform is claimed supported.

| Form type | Detection | Mapping | Fill | Evidence / issue |
|---|---|---|---|---|
| Ordinary HTML | TESTED | TESTED | PARTIAL | `test_form.html` / `tests/extension_golden.py`: six fields filled, two missed. |
| React controlled | CODE RISK | CODE RISK | UNVERIFIED | Direct `.value` write may not update framework state. |
| Native select | TESTED | TESTED | PARTIAL | Fixture selects exact value; missing option silently fails. |
| Custom dropdown | UNVERIFIED | UNVERIFIED | UNSUPPORTED | Not an input/select/textarea. |
| Radio | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | Excluded in scanner. |
| Checkbox | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | Excluded in scanner. |
| Native date | DETECTABLE | PARTIAL | UNVERIFIED | No ISO value conversion or validation. |
| Date picker | UNVERIFIED | UNVERIFIED | UNSUPPORTED | Custom picker is site-specific. |
| Textarea | TESTED | PARTIAL | PARTIAL | Fixture's custom answer is correctly left unfilled. |
| Dynamically rendered | TESTED | TESTED | TESTED | Synthetic step replacement then manual Fill rescans the current DOM; no automatic readiness cue. |
| Multi-step | TESTED | TESTED | TESTED | Synthetic two-step form fills name, replaces step DOM, then fills email after a new user action. Real ATS multi-step flows remain unverified. |
| iframe | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | `all_frames` absent. |
| Shadow DOM | UNSUPPORTED | UNSUPPORTED | UNSUPPORTED | `querySelectorAll` does not enter shadow roots. |

ATS systems (Workday, Greenhouse, Lever and others): **UNVERIFIED**. A platform should enter this matrix only after a specific test page, date and observed detection/mapping/fill result are recorded.

## Verified after changes (2026-09-30)

| System / form | Detection | Mapping | Filling | Issues |
|---|---:|---:|---:|---|
| [Greenhouse-hosted Boldly](https://job-boards.greenhouse.io/boldly/jobs/4005594006) | 46 native elements | 4 basic fields | 4 written, 0 write errors | Many custom controls and questions remain manual. Toolbar initially vanished during site rendering; reinjection fixed it. False email mapping in custom question was removed. |
| [Lever application](https://jobs.lever.co/usasurveyjob/fe664ea7-bfc2-4e3d-913b-1de52c59fa41/apply) | 5 | 3 basic fields | 3 written, 0 write errors | Location autocomplete and current company remain manual. |
| Synthetic controlled input / select / radio / month / textarea | 6 | 4 suggestions | 3 written, 1 select rejected, custom answer untouched | `tests/extension_golden.py`; controlled state updated through native setter. |
| Synthetic dynamically rendered two-step form | Step 1: 1; Step 2: 1 | 1 per step | Name then email written after separate confirmations | `tests/extension_golden.py`; no submit; represents only light-DOM step replacement. |

Screenshots with synthetic data: [Greenhouse](evidence/greenhouse-after-fill.png), [Lever](evidence/lever-after-fill.png). The platform observations apply to these specific pages on this date, not every job on each ATS.

## Permission-gated extension check (2026-09-30)

The unpacked MV3 extension was loaded in a disposable Edge profile. Before a site permission was granted, the local synthetic form had no toolbar and the popup correctly stated that `127.0.0.1` was not allowed. Headless Chromium cannot approve the optional-host browser prompt, so post-grant toolbar injection remains a manual-browser check.
