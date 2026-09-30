#!/usr/bin/env bash
# Run on the server after the apply.quinnverse.tech A record resolves to this host.
set -euo pipefail

DOMAIN=apply.quinnverse.tech
EXPECTED_IP=124.223.15.11
WEBROOT=/var/www/letsencrypt
CONF=/etc/nginx/conf.d/apply.conf
SOURCE_CONF="${AC_HTTPS_CONF:-/opt/copilot/apply_https.conf}"
EMAIL="${1:-${CERTBOT_EMAIL:-}}"

resolved=$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u)
if [ "$resolved" != "$EXPECTED_IP" ]; then
  echo "DNS 未指向预期服务器：$DOMAIN，暂不申请证书" >&2
  exit 2
fi
[ -f "$SOURCE_CONF" ] || { echo "缺少 HTTPS 配置模板：$SOURCE_CONF" >&2; exit 1; }
mkdir -p "$WEBROOT/.well-known/acme-challenge"
if [ -n "$EMAIL" ]; then
  certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL"
else
  certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email
fi

backup="${CONF}.pre-https.$(date +%Y%m%d%H%M%S)"
cp -a "$CONF" "$backup"
install -m 644 "$SOURCE_CONF" "$CONF"
if ! nginx -t; then
  cp -a "$backup" "$CONF"
  nginx -t
  exit 1
fi
systemctl reload nginx
health=$(curl --noproxy '*' -fsS --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health")
python3 -c 'import json,sys; h=json.loads(sys.argv[1]); assert h.get("auth") is True and h.get("auth_ready") is True' "$health"
code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/profile")
[ "$code" = "401" ] || { echo "HTTPS 匿名档案请求未被拒绝：$code" >&2; exit 1; }
echo "HTTPS、鉴权与证书验收通过"
