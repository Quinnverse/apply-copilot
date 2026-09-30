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
2. **Live cloud is blocked for a shared pilot by DNS/HTTPS.** Before the 2026-09-30 deployment, the service bound `0.0.0.0:8787`, served the generated bookmarklet with HTTP 200, and stored 18 tenant files with mode 644. The bookmarklet had no email/phone regex matches and no string matches against current profile values in a targeted check; that does not prove it contained no personal information. These server issues were repaired below. `apply.quinnverse.tech` still lacks a matching HTTPS certificate and did not resolve to the server during checks; its HTTP Nginx entry now returns 503 instead of proxying private API requests.
3. **Storage is plaintext.** Profiles, PDFs and token mappings are files on disk; server operators and anyone with filesystem or backup access can read them. The dashboard stores its token in browser `localStorage`, and the userscript stores its token in userscript storage. A compromised browser profile can expose it.
4. **Broad extension scope.** The manifest still injects the toolbar on `<all_urls>`. The extension does not send fields merely on page load, but that permission should be narrowed before broad distribution.
5. **Other application paths.** The desktop assistant and legacy userscript can store field memory and scan diagnostics locally. These may contain user-entered values or page context; treat their data directories and backups as sensitive. Anyone who previously generated or distributed a bookmarklet containing real data should treat that copy as exposed until deleted; this sprint cannot verify historic distribution.

## Verification

Run `.venv/Scripts/python tests/tenant_isolation.py` and `.venv/Scripts/python tests/backend_smoke.py`. The first checks profile/resume/field-memory/application isolation, unauthorized and query-token rejection, malformed-token fail-closed behavior. The second checks local API/CORS behavior and refuses unauthenticated `0.0.0.0` CLI startup. These are code-level checks, not a security certification or production penetration test.

### Live read-only and synthetic checks (2026-09-30)

- Server files: `.env` and `data/tokens.json` both mode 600; service active; anonymous `/api/profile` returns 401. Two existing token identities returned different tenant IDs and their own profile/resume endpoints returned 200. No existing resume was available for a cross-tenant file request.
- With two temporary random test tokens, A wrote a synthetic profile, uploaded a synthetic PDF and saved a field-memory value. B's profile and resume list did not show A's data, B's request for A's resume ID returned 404, and B's field memory did not contain A's value. All assertions passed via the running HTTP service on server loopback.
- The two test tokens and their data directories were removed in a `finally` cleanup. Follow-up checks found two original token entries and two original tenant directories, with no test token or temporary token file remaining.
- Before deployment, production had HTTP only for this hostname, invalid HTTPS hostname, a `0.0.0.0:8787` listener, a public generated bookmarklet, and old server code. Those findings motivated the security deployment below.

### Security deployment and regression (2026-09-30)

- Saved a root-only rollback archive of application code and service configuration on the server. The deployment package contained code and static shell only; it did not contain profiles, PDFs, tokens or application state. No tenant data was overwritten.
- Deployed the security branch to the running service. `GET /api/health` returned `build: 2026-09-30-security`, `auth: true`, `auth_ready: true`; anonymous profile requests returned 401. The generated bookmarklet file was removed and its URL returned 404 from the backend. The service bound only `127.0.0.1:8787`.
- Set existing data directories to mode 700 and tenant files to mode 600; systemd `UMask=0077` now governs newly created files. Two original token entries and two original tenant directories remained after deployment.
- Re-ran `tests/live_tenant_probe.py` on the live server with disposable tokens: cross-tenant profile, resume file, resume list and field memory isolation passed; cleanup restored the original token and tenant counts.
- Replaced the HTTP Nginx proxy for `apply.quinnverse.tech` with a temporary 503 response, retaining the ACME challenge path. This prevents cleartext access to the application while DNS and HTTPS are unresolved. Other Nginx sites remained active. The HTTPS configuration and certificate flow are prepared in `deploy/apply_https.conf` and `deploy/enable_apply_https.sh`, but certificate issuance was not attempted because the domain did not resolve to the server. Browser access to the DNS console was blocked by its security check, so no DNS change was made.
