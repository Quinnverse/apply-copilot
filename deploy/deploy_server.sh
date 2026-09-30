#!/usr/bin/env bash
# 网申助手后端 · 服务器端部署脚本（腾讯云轻量 OpenCloudOS，root 执行）
# 前置：部署包已解压到 /tmp/copilot_deploy（只含代码、静态页和服务模板）
set -euo pipefail

DEPLOY_SRC="/tmp/copilot_deploy"
DEST="/opt/copilot"
PORT=8787
MIRROR="https://mirrors.cloud.tencent.com/pypi/simple"

echo "== [1/5] 校验部署包与令牌配置 =="
[ -f "$DEPLOY_SRC/app/server.py" ] && [ -f "$DEPLOY_SRC/copilot.service" ] || { echo "部署包不完整" >&2; exit 1; }
[ ! -e "$DEPLOY_SRC/data" ] && [ ! -e "$DEPLOY_SRC/skill/state" ] || { echo "拒绝包含用户数据的部署包" >&2; exit 1; }
[ -f "$DEST/.env" ] || { echo "缺少 $DEST/.env" >&2; exit 1; }
[ -f "$DEST/data/tokens.json" ] || { echo "缺少 $DEST/data/tokens.json" >&2; exit 1; }
[ "$(stat -c %a "$DEST/.env")" = "600" ] || { echo ".env 权限必须为 600" >&2; exit 1; }
[ "$(stat -c %a "$DEST/data/tokens.json")" = "600" ] || { echo "tokens.json 权限必须为 600" >&2; exit 1; }
echo "== [2/5] 停旧服务 + 布局代码文件 =="
systemctl stop copilot 2>/dev/null || true
mkdir -p "$DEST"
cp -a "$DEPLOY_SRC/app/." "$DEST/"
mkdir -p "$DEST/static" "$DEST/skill/scripts"
cp -a "$DEPLOY_SRC/static/." "$DEST/static/"
cp -a "$DEPLOY_SRC/skill/scripts/." "$DEST/skill/scripts/"
rm -f "$DEST/static/assistant.bookmarklet.js"
echo "布局完成：$DEST/{server.py,static,data,skill}"

echo "== [3/5] 检查端口 $PORT 是否被占用 =="
if ss -tlnp | grep -q ":$PORT "; then
  echo "!! 端口 $PORT 已被占用："
  ss -tlnp | grep ":$PORT "
  exit 1
fi
echo "端口 $PORT 空闲"

echo "== [4/5] 建 venv + 装依赖（腾讯镜像）=="
python3.11 -m venv "$DEST/venv" 2>/dev/null || python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --upgrade pip -q -i "$MIRROR"
"$DEST/venv/bin/pip" install -q -r "$DEPLOY_SRC/requirements.txt" -i "$MIRROR"
"$DEST/venv/bin/python" -c "import fastapi, uvicorn, pydantic; print('deps OK:', fastapi.__version__, uvicorn.__version__)"

echo "== [5/5] 安装 systemd 服务并验收 =="
cp "$DEPLOY_SRC/copilot.service" /etc/systemd/system/copilot.service
systemctl daemon-reload
systemctl enable copilot
systemctl restart copilot
sleep 3
systemctl --no-pager --lines=5 status copilot || true

for i in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/health" || true)
  [ "$code" = "200" ] && break
  sleep 1
done
echo "本机 /api/health -> HTTP $code"
if [ "$code" != "200" ]; then
  journalctl -u copilot -n 30 --no-pager
  exit 1
fi
python3 -c 'import json,sys; h=json.load(sys.stdin); assert h.get("auth") is True and h.get("auth_ready") is True, h' \
  < <(curl -fsS "http://127.0.0.1:$PORT/api/health")
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/profile")
[ "$code" = "401" ] || { echo "无令牌请求未被拒绝：HTTP $code" >&2; exit 1; }
if ss -tlnp | grep ":$PORT " | grep -v '127.0.0.1:'; then
  echo "后端绑定了非本机地址" >&2; exit 1
fi
echo "本机鉴权验收通过；请通过 HTTPS 反向代理访问，勿开放 $PORT 公网端口"
