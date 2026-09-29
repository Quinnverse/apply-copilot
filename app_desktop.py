#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · 桌面壳 (pywebview 6.x)  [保留作为 pywebview 备选路径]

职责：
  * 本进程内用线程启动 FastAPI 后端（127.0.0.1:8787）。
  * 创建主窗口加载仪表板（http://127.0.0.1:8787/）。
  * 通过 pywebview JS API 暴露 open_site / mark_recorded / regenerate / research。
  * open_site 为每个招聘官网打开一个独立的真实 WebView2 窗口（因招聘站设了
    X-Frame-Options/CSP，无法 iframe 嵌入），并在页面加载后注入浮动填空助手。

安全红线（与后端一致）：
  * 助手只做人触发后的字段填充与记录标记，绝不代登录、绝不破解验证码、绝不自动提交。
  * 每个招聘窗口都是用户自己的浏览器会话，登录态由用户本人维持。

说明：注入脚本拼接逻辑已抽到 assistant_bridge.py（Qt 版 app_desktop_qt.py 也只依赖它，
不再强拉 webview）。本文件仍需 webview，仅作为 pywebview 备选入口。

用法：
  python app_desktop.py
"""

import sys
import os
import json
import time
import threading
import atexit
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import server  # noqa: E402  (复用后端 app / PROFILE / filler.FIELD_RULES)
import webview  # noqa: E402

# 注入脚本拼接（从 assistant_bridge 取，不再在本文件重复实现）
from assistant_bridge import build_assistant_js  # noqa: E402


class Api:
    """暴露给前端 JS 的 API（window.pywebview.api）。"""

    def __init__(self):
        self._main_window = None

    # ---- 打开招聘官网（独立真实窗口 + 注入助手）----
    def open_site(self, url, resume_id="", company=""):
        if not url:
            return {"ok": False, "error": "url 为空"}
        try:
            resume_name = ""
            reg = server.copilot.load_resumes(server.REGISTRY_PATH)
            for r in reg.get("resumes", []):
                if r.get("id") == resume_id:
                    resume_name = r.get("name", "")
                    break
            assistant_js = build_assistant_js(company or "", resume_id or "", resume_name)
            win = webview.create_window(
                title=company or "招聘站点",
                url=url,
                js_api=self,
                width=1180,
                height=820,
            )

            def _on_loaded(_w=None):
                # 用闭包 win 而非回调参数，确保即使回调未传参也能注入
                try:
                    win.evaluate_js(assistant_js)
                except Exception:
                    pass

            win.events.loaded += _on_loaded
            return {"ok": True, "title": win.title}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---- 记录投递状态（仅 pywebview 路径兼容；Qt 路径助手② 已直接 POST /api/mark）----
    def mark_recorded(self, company, status="已投"):
        if not company:
            return {"ok": False, "error": "company 为空"}
        status = status or "已投"
        try:
            data = json.dumps({"status": status}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8787/api/queue/" + urllib.parse.quote(company) + "/status",
                data=data,
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                resp = json.loads(r.read().decode("utf-8"))
            self._refresh_main()
            return resp
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---- 按投递情况重生成清单（重跑父目录 gen_submit_list.py）----
    def regenerate(self):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8787/api/regenerate",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=70) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        self._refresh_main()
        return resp

    # ---- 发起调研入箱（给 WorkBuddy AI 助手）----
    def research(self, cat, keywords):
        try:
            data = json.dumps({"cat": cat or "", "keywords": keywords or ""}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8787/api/research",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _refresh_main(self):
        """通知主仪表板窗口刷新队列。"""
        try:
            if self._main_window is not None:
                self._main_window.evaluate_js(
                    "if(window.__reloadQueue)window.__reloadQueue();"
                )
        except Exception:
            pass


def main():
    from uvicorn import Config, Server

    uv_config = Config(app=server.app, host="127.0.0.1", port=8787, log_level="warning")
    uv_server = Server(uv_config)
    threading.Thread(target=uv_server.run, daemon=True).start()
    time.sleep(1.5)  # 等待后端就绪

    api = Api()
    main_win = webview.create_window(
        "网申助手",
        url="http://127.0.0.1:8787/",
        width=1180,
        height=820,
        js_api=api,
    )
    api._main_window = main_win

    def _shutdown():
        try:
            uv_server.should_exit = True
        except Exception:
            pass

    atexit.register(_shutdown)
    webview.start()  # 阻塞，直到所有窗口关闭


if __name__ == "__main__":
    main()
