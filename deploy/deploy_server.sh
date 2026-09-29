#!/usr/bin/env bash
# 网申助手后端 · 服务器端部署脚本（腾讯云轻量 OpenCloudOS，root 执行）
# 前置：部署包已解压到 /tmp/copilot_deploy（含 app/ static/ data/ skill/ requirements.txt copilot.service）
set -euo pipefail

DEPLOY_SRC="/tmp/copilot_deploy"
DEST="/opt/copilot"
PORT=8787
MIRROR="https://mirrors.cloud.tencent.com/pypi/simple"

echo "== [1/7] 停旧服务 + 布局文件 =="
systemctl stop copilot 2>/dev/null || true
mkdir -p "$DEST"
# 优先 rsync，缺失则退化到 cp -a（OpenOS 精简镜像常无 rsync）
if command -v rsync >/dev/null 2>&1; then
  rsync -a "$DEPLOY_SRC/app/"            "$DEST/"
  rsync -a --delete "$DEPLOY_SRC/static/" "$DEST/static/"
  rsync -a --delete "$DEPLOY_SRC/data/"   "$DEST/data/"
  rsync -a --delete "$DEPLOY_SRC/skill/"  "$DEST/skill/"
else
  cp -a "$DEPLOY_SRC/app/." "$DEST/"
  rm -rf "$DEST/static" "$DEST/data" "$DEST/skill"
  mkdir -p "$DEST/static" "$DEST/data" "$DEST/skill"
  cp -a "$DEPLOY_SRC/static/." "$DEST/static/"
  cp -a "$DEPLOY_SRC/data/."   "$DEST/data/"
  cp -a "$DEPLOY_SRC/skill/."  "$DEST/skill/"
fi
chmod 600 "$DEST/data/resumes/"*.pdf    # 简历 PDF 含个人信息
echo "布局完成：$DEST/{server.py,static,data,skill}"

echo "== [2/7] 检查端口 $PORT 是否被占用 =="
if ss -tlnp | grep -q ":$PORT "; then
  echo "!! 端口 $PORT 已被占用："
  ss -tlnp | grep ":$PORT "
  exit 1
fi
echo "端口 $PORT 空闲"

echo "== [3/7] 建 venv + 装依赖（腾讯镜像）=="
python3.11 -m venv "$DEST/venv" 2>/dev/null || python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install --upgrade pip -q -i "$MIRROR"
"$DEST/venv/bin/pip" install -q -r "$DEPLOY_SRC/requirements.txt" -i "$MIRROR"
"$DEST/venv/bin/python" -c "import fastapi, uvicorn, pydantic; print('deps OK:', fastapi.__version__, uvicorn.__version__)"

echo "== [4/7] 安装 systemd 服务 =="
cp "$DEPLOY_SRC/copilot.service" /etc/systemd/system/copilot.service
systemctl daemon-reload
systemctl enable copilot
systemctl restart copilot
sleep 3
systemctl --no-pager --lines=5 status copilot || true

echo "== [5/7] 本机自检 =="
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
TOKEN=$(grep -oP 'AC_TOKEN=\K\S+' /etc/systemd/system/copilot.service)
echo "本机 /api/queue (无token)  -> HTTP $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/queue")"
echo "本机 /api/queue (带token)  -> HTTP $(curl -s -o /dev/null -w '%{http_code}' -H "X-AC-Token: $TOKEN" "http://127.0.0.1:$PORT/api/queue")"
echo "本机 / (dashboard)         -> HTTP $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/")"

echo "== [6/7] 防火墙（firewalld，若活跃）=="
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-port=$PORT/tcp
  firewall-cmd --reload
  echo "firewalld 已放行 $PORT/tcp"
else
  echo "firewalld 未活跃，跳过（OpenCloudOS 轻量默认可能无 firewalld）"
fi

echo "== [7/7] 安全组提示 =="
echo "⚠️  腾讯云【安全组】不在系统内，若外网 curl http://<IP>:$PORT/api/health 不通，"
echo "    请到腾讯云控制台：轻量应用服务器 -> 防火墙 -> 添加规则 放行 TCP $PORT。"
echo
echo "✅ 部署完成。访问令牌（油猴脚本 ⚙ 与仪表板配置用）："
echo "   $TOKEN"
