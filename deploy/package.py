#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地打包：把云端部署所需文件汇总到 deploy/package/（供 scp 上传解压为 /tmp/copilot_deploy）。

布局（与 deploy_server.sh 约定一致）：
  package/app/      server.py copilot.py filler.py company_util.py assistant_bridge.py refresh_queue.py
  package/static/   dashboard.html assistant.bookmarklet.js
  package/data/     profile.job.json resumes.json resume_active.json queue.json queue_seed.json
                    research_inbox.json / suggestions.json / field_memory.json / applications.json（存在才带）
                    resumes/*.pdf（简历 PDF，含个人信息，只进服务器）
  package/skill/    scripts/apply.py + state/{applications.json, seen_postings.json}
  package/requirements.txt + copilot.service + deploy_server.sh

绝不改动本地真实数据文件 —— 全部 cp。
"""
import shutil
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent          # apply-copilot/
SKILL = Path(r"D:/WorkBuddyData/.workbuddy/skills/autumn-recruitment-tracker")
DL = Path(r"C:/Users/you/Downloads")
PKG = PROJ / "deploy" / "package"

APP_FILES = ["server.py", "local_apply.py", "copilot.py", "filler.py", "company_util.py",
             "assistant_bridge.py", "refresh_queue.py"]
STATIC_FILES = ["dashboard.html", "assistant.bookmarklet.js"]
DATA_FILES = ["profile.job.json", "resumes.json", "resume_active.json",
              "queue.json", "queue_seed.json",
              "research_inbox.json", "suggestions.json", "field_memory.json"]
PDFS = ["简历.pdf", "简历2.pdf"]
SKILL_STATE = ["applications.json", "seen_postings.json"]
ROOT_FILES = ["requirements.txt", "copilot.service", "deploy_server.sh"]


def cp(src: Path, dst: Path):
    if not src.exists():
        print(f"  skip(不存在): {src}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  ok: {dst.relative_to(PKG)}")


def main():
    # 目录复用（不整体 rmtree：大批量删除会触发安全确认），文件逐一覆盖
    print(f"打包到 {PKG}")
    for f in APP_FILES:
        cp(PROJ / f, PKG / "app" / f)
    for f in STATIC_FILES:
        cp(PROJ / "static" / f, PKG / "static" / f)
    for f in DATA_FILES:
        cp(PROJ / f, PKG / "data" / f)
    for f in PDFS:
        cp(DL / f, PKG / "data" / "resumes" / f)
    cp(SKILL / "scripts" / "apply.py", PKG / "skill" / "scripts" / "apply.py")
    for f in SKILL_STATE:
        cp(SKILL / "state" / f, PKG / "skill" / "state" / f)
    for f in ROOT_FILES:
        cp(PROJ / "deploy" / f, PKG / f)
    print("打包完成")


if __name__ == "__main__":
    main()
