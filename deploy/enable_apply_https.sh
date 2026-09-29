#!/usr/bin/env bash
# =============================================================================
# 一键为 apply.quinnverse.tech 启用 HTTPS 反代（Task A 第 3-6 步）
#
# 前置条件（必须先在用户侧完成，否则脚本会拒绝执行）：
#   1) DNS：添加 A 记录  apply.quinnverse.tech -> 124.223.15.11（本机公网 IP）
#   2) 控制台安全组：放行 TCP 443（当前 443 外网不通）
#
# 用法（在服务器上，root）：
#   bash enable_apply_https.sh                 # 用 certbot 现有账号/或免邮箱注册
#   bash enable_apply_https.sh me@example.com  # 指定邮箱注册/续期
#
# 幂等：可重复运行；certbot 已签发过会走续期，copilot.service 已改过会跳过。
# =============================================================================
set -euo pipefail

DOMAIN="apply.quinnverse.tech"
EMAIL="${1:-${CERTBOT_EMAIL:-}}"
SERVICE="/etc/systemd/system/copilot.service"

echo "[0] 检查 DNS 是否已生效 ..."
if ! getent hosts "$DOMAIN" >/dev/null 2>&1; then
  echo "ERROR: $DOMAIN 仍无 DNS 解析。请先添加 A 记录指向本机公网 IP，再运行本脚本。"
  exit 2
fi
echo "    DNS OK -> $(getent hosts "$DOMAIN" | awk '{print $1}' | paste -sd, -)"

echo "[1] certbot 申请证书并自动改写 nginx（含 80->443 跳转）..."
if [ -n "$EMAIL" ]; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL" --redirect
else
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
          --register-unsafely-without-email --redirect
fi

echo "[2] 把 copilot 后端收敛到 127.0.0.1:8787（不再对公网暴露 8787）..."
if grep -q -- "--host 0.0.0.0" "$SERVICE"; then
  cp -a "$SERVICE" "${SERVICE}.bak_https_$(date +%Y%m%d-%H%M%S)"
  sed -i 's/--host 0\.0\.0\.0/--host 127.0.0.1/' "$SERVICE"
  systemctl daemon-reload
  systemctl restart copilot
  echo "    已改为 127.0.0.1，copilot 已重启"
else
  echo "    copilot.service 已绑定 127.0.0.1（跳过）"
fi

echo "[3] 校验（服务器本机）..."
sleep 2
echo -n "    8787 监听: "; ss -tlnp | grep 8787 || true
echo -n "    health: "; curl -s --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health"; echo
echo -n "    root:   "; curl -s -o /dev/null -w '%{http_code}\n' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/"
echo -n "    queue(no token): "; curl -s -o /dev/null -w '%{http_code}\n' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/queue"
echo -n "    http->https: "; curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' -H "Host: $DOMAIN" http://127.0.0.1/

echo "[4] 其它站点回归 ..."
echo -n "    quinnverse: "; curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: quinnverse.tech' http://127.0.0.1/
echo -n "    job:        "; curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: job.quinnverse.tech' http://127.0.0.1/
echo -n "    8080:       "; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
echo "[done]"
