# Privacy and tenant isolation — 2026-09-30

## Verified code paths

- `profile.job.json`, `resumes.json`, `applications.json`, `tokens.json`, and `tenants/` are Git ignored. They are absent from tracked project files. Previous public-form screenshots contain synthetic applicant data only.
- The browser extension (`extension/background.js`) sends profile and form descriptors to `http://127.0.0.1:8787`; it has no cloud backend setting. `extension/content.js` runs on `<all_urls>`, but sends field descriptors only after the user presses Fill. Selected values are written after explicit confirmation.
- In token mode, `server.py` validates `X-AC-Token`, binds each request to a token-derived tenant directory, and routes profile, resume, field memory and application record operations through `TENANT`. `tests/tenant_isolation.py` confirmed two tokens could not read each other's data through these endpoints.
- Invalid/empty/removed token configuration now fails closed when token auth was configured or `AC_REQUIRE_AUTH=1`. The systemd template sets `AC_REQUIRE_AUTH=1`; CLI startup refuses a non-loopback bind without authentication. Query-string tokens are no longer accepted.
- The legacy userscript no longer contains a path that clicks the final Submit button. New installs default auto fill and auto attach to off.
- The generated bookmarklet previously embedded profile values in a public static asset. Its URL now returns 404; the generated file is ignored by Git and excluded from deployment packages. The committed copy contained synthetic sample values and was removed from Git tracking.
- Deployment packaging now excludes profiles, PDFs, tokens and application state. The deployment script rejects packages containing data, preserves the server data directory, checks token file permissions and authentication readiness, and keeps port 8787 on loopback behind HTTPS. These script changes have not been run on the live server.

## Limits: no absolute secrecy guarantee

1. **Local mode is single-user.** When no token is configured, all local API requests use one data directory. This is suitable only for one trusted computer/user account. Another local process, a privileged extension, or anyone with filesystem access could read local files. CORS limits ordinary webpages reading responses, but is not authentication.
2. **Cloud configuration is unverified here.** The code and disposable two-token tests passed; the live `apply.quinnverse.tech` deployment, its TLS, environment variables, token file permissions, reverse proxy and data directory were not validated in this run. An HTTPS probe failed during TLS handshake from this workspace. Changes in this branch do not protect a server until deployed.
3. **Storage is plaintext.** Profiles, PDFs and token mappings are files on disk; server operators and anyone with filesystem or backup access can read them. The dashboard stores its token in browser `localStorage`, and the userscript stores its token in userscript storage. A compromised browser profile can expose it.
4. **Broad extension scope.** The manifest still injects the toolbar on `<all_urls>`. The extension does not send fields merely on page load, but that permission should be narrowed before broad distribution.
5. **Other application paths.** The desktop assistant and legacy userscript can store field memory and scan diagnostics locally. These may contain user-entered values or page context; treat their data directories and backups as sensitive. Anyone who previously generated or distributed a bookmarklet containing real data should treat that copy as exposed until deleted; this sprint cannot verify historic distribution.

## Verification

Run `.venv/Scripts/python tests/tenant_isolation.py` and `.venv/Scripts/python tests/backend_smoke.py`. The first checks profile/resume/field-memory/application isolation, unauthorized and query-token rejection, malformed-token fail-closed behavior. The second checks local API/CORS behavior and refuses unauthenticated `0.0.0.0` CLI startup. These are code-level checks, not a security certification or production penetration test.
