# Apply Copilot production status — 2026-09-30

## Current state

The security build `2026-09-30-security` is running on the server. Its API is bound to `127.0.0.1:8787`; anonymous profile access returns 401; authentication is ready; generated bookmarklet access returns 404. Existing tenant directories and files are restricted to modes 700 and 600. A disposable two-user live isolation test passed after deployment and cleaned up its test data.

The public Apply Copilot domain is **intentionally unavailable**: Nginx returns HTTP 503 for `apply.quinnverse.tech` instead of transmitting access tokens and applicant data over HTTP. Other sites on the server remain active.

## Remaining P0: DNS and HTTPS

- Add or verify an **A record** in the authoritative DNS zone for `quinnverse.tech`: host `apply`, value `124.223.15.11`. Use the zone's normal TTL. The server's `getent ahostsv4 apply.quinnverse.tech` returned no address during this run. This workspace's DNS returned a proxy address, which cannot verify public resolution.
- Confirm inbound TCP 80 and 443 reach the server for certificate validation and HTTPS. The server has Nginx listeners on both ports, but external reachability was not verified here.
- Once the A record resolves to the server, install the prepared `deploy/apply_https.conf` on the server and run `deploy/enable_apply_https.sh` there to request a certificate through the ACME webroot and switch Nginx to HTTPS. The script checks DNS before issuance and checks certificate validation, `auth: true`, `auth_ready: true`, and anonymous 401 afterward.
- Re-run public HTTPS and browser extension checks before inviting users. Do not change the HTTP 503 hold merely to make the page reachable without a valid certificate.

The DNS console could not be opened through the available browser because its security permission check failed. No DNS record was changed in this run. A root-only rollback archive of the previous application code and service configuration is stored on the server; no user data was included in the deployment package.
