#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地打包：把云端部署所需文件汇总到 deploy/package/（供 scp 上传解压为 /tmp/copilot_deploy）。

布局（与 deploy_server.sh 约定一致）：
  package/app/      server.py copilot.py filler.py company_util.py assistant_bridge.py refresh_queue.py
  package/static/   dashboard.html (generated bookmarklet is never deployed)
  package/skill/    scripts/apply.py（仅代码；用户数据与 state 不打包）
  package/requirements.txt + copilot.service + deploy_server.sh

部署包只包含代码与静态页面，不读取或复制用户数据。
"""
import shutil
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent          # apply-copilot/
SKILL = Path(r"D:/WorkBuddyData/.workbuddy/skills/autumn-recruitment-tracker")
PKG = PROJ / "deploy" / "package"

APP_FILES = ["server.py", "local_apply.py", "copilot.py", "filler.py", "company_util.py",
             "assistant_bridge.py", "refresh_queue.py"]
STATIC_FILES = ["dashboard.html"]
ROOT_FILES = ["requirements.txt", "copilot.service", "deploy_server.sh"]


def cp(src: Path, dst: Path):
    if not src.exists():
        raise FileNotFoundError(f"部署所需代码不存在: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  ok: {dst.relative_to(PKG)}")


def main():
    # 拒绝复用旧版含个人资料的部署目录，避免旧文件混入新包。
    if any(path.exists() for path in (PKG / "data", PKG / "skill" / "state",
                                      PKG / "static" / "assistant.bookmarklet.js")):
        raise SystemExit("旧部署目录含数据/state/生成书签；请先将其移出 deploy/package 再重新打包")
    required = ([PROJ / f for f in APP_FILES] +
                [PROJ / "static" / f for f in STATIC_FILES] +
                [SKILL / "scripts" / "apply.py"] +
                [PROJ / "deploy" / f for f in ROOT_FILES])
    missing = [str(f) for f in required if not f.is_file()]
    if missing:
        raise SystemExit("缺少部署文件: " + ", ".join(missing))
    print(f"打包到 {PKG}")
    for f in APP_FILES:
        cp(PROJ / f, PKG / "app" / f)
    for f in STATIC_FILES:
        cp(PROJ / "static" / f, PKG / "static" / f)
    cp(SKILL / "scripts" / "apply.py", PKG / "skill" / "scripts" / "apply.py")
    for f in ROOT_FILES:
        cp(PROJ / "deploy" / f, PKG / f)
    print("打包完成")


if __name__ == "__main__":
    main()
