# Apply Copilot production status — 2026-09-30

## Current state

The security build `2026-09-30-security` is running on the server. Its API is bound to `127.0.0.1:8787`; anonymous profile access returns 401; authentication is ready; generated bookmarklet access returns 404. Existing tenant directories and files are restricted to modes 700 and 600. A disposable two-user live isolation test passed after deployment and cleaned up its test data.

`apply.quinnverse.tech` now has a valid Let's Encrypt certificate (expires 2026-12-29). HTTP returns a 308 redirect to HTTPS. Public HTTPS checks returned the expected `auth: true`, `auth_ready: true`, anonymous `/api/profile` 401, and generated bookmarklet 404.

## Completed DNS and HTTPS validation

- Public Google and Cloudflare resolvers returned `apply.quinnverse.tech → 124.223.15.11` with a 600-second TTL.
- Let's Encrypt issued a certificate for the domain. The server-local TLS request verified the certificate hostname and returned health 200.
- Public HTTPS returned the same security status as the server-local check. HTTP now redirects to HTTPS.

The remaining product gates are setup, form coverage, real ATS upload verification, and the extension's broad `<all_urls>` scope. A root-only rollback archive of the previous application code and service configuration is stored on the server; no user data was included in the deployment package.
