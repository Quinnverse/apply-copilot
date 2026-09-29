#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · 桌面壳 v2（PyQt6 + QtWebEngine，单窗口内嵌多标签浏览器）

布局（对齐「Offer来了」参考截图）：
  ┌──────────┬─────────────────────────────────────┐
  │ 助手侧边栏 │ ← → ⟳  [地址栏]  ％缩放  [打开]        │
  │ (仪表板    ├─────────────────────────────────────┤
  │  紧凑模式) │ 标签页: [求职信息][公司A ×][+ …]        │
  │           │   真 Chromium(QtWebEngine) 渲染官网    │
  └──────────┴─────────────────────────────────────┘

关键机制：
  * 后端复用 server.py（线程内 uvicorn, 127.0.0.1:8787）。
  * 仪表板(侧边栏)点「打开」→ POST /api/bridge → 本壳 400ms 轮询 → 新标签页打开官网。
  * 每个标签 loadFinished 后（只要 URL 不是 127.0.0.1 后端自身）都注入 🛠 填充助手：
    公司/resume 由当前 URL 反查队列（_company_for_url）兜底，匹配不到也注入（至少能点选/速查）。
  * 助手② 记录已投：直接 POST /api/mark 真实入库（见 assistant.js doRecord），不再走 polyfill。

安全红线（不变）：
  * 助手只做人触发后的字段填充与状态标记；绝不代登录、绝不破解验证码、绝不自动提交。
  * 登录态由用户本人在内嵌浏览器里维持；后端仅监听 127.0.0.1。

用法：
  python app_desktop_qt.py
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

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTabWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  必须在 QApplication 之前 import

import server  # noqa: E402  复用后端 app / PROFILE / copilot / filler
# 注入脚本拼接只依赖 assistant_bridge（不 import app_desktop，避免强拉 pywebview）
from assistant_bridge import build_assistant_js  # noqa: E402

BACKEND = "http://127.0.0.1:8787"

# 历史 polyfill：原把 callApi('mark_recorded') 转成本机 PUT /api/queue/{company}/status（仅翻徽章）。
# 现助手② 记录已投已改为直接 POST /api/mark 真实入库（见 assistant.js doRecord），
# 不再需要此 shim。保留空结构以备排查。
RECORD_SHIM = """
// 历史 mark_recorded polyfill 已弃用：助手② 现直接 fetch('/api/mark') 真实入库。
// （本文件保留空壳，避免其他历史引用处因缺变量报错。）
"""

EXPECT_BUILD = "2026-09-13d"   # 与 server.BUILD_ID 对应（云端关闭 docs + 信息泄露收敛）


def _backend_alive():
    """探测 127.0.0.1:8787 上是否已有可用后端（本机直连，绕过代理）。

    顺便校验 build 号：若残留的是旧进程，新接口（如 /api/scan-dump）会 404，
    这里提前给出可操作的提示。
    """
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(BACKEND + "/api/health", timeout=1.5) as r:
            if r.status != 200:
                return False
            try:
                info = json.loads(r.read().decode("utf-8"))
            except Exception:
                return True
            if info.get("build") and info.get("build") != EXPECT_BUILD:
                print(f"[后端] 8787 上跑的是旧版本后端(build={info.get('build')})，"
                      f"新接口可能缺失。建议关闭所有网申助手窗口与黑框命令行后重新启动。")
            return True
    except Exception:
        return False


def http_json(method, path, body=None, timeout=5):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BACKEND + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    # 本机直连，绕过任何系统代理
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class BrowserTab(QWebEngineView):
    """单个内嵌浏览器标签；页面每次加载完成后交给 MainWindow 注入填充助手。"""

    def __init__(self, url, mainwin, parent=None):
        super().__init__(parent)
        self._mainwin = mainwin
        # 关键：QWidget 默认 NoFocus，页面拿不到焦点会导致键盘/部分鼠标交互失效
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.loadFinished.connect(self._on_loaded)
        self.load(QUrl(url))

    def _on_loaded(self, _ok):
        try:
            url = self.url().toString()
        except Exception:
            url = ""
        try:
            self._mainwin._inject_into(self, url)
        except Exception:
            pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("网申助手")
        self.resize(1440, 900)

        # 队列缓存：_company_for_url 反查公司用（loadFinished 时刷新）
        self._queue_cache = []

        # ---- 整体布局：左助手栏 + 右浏览器区 ----
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)

        self.sidebar = QWebEngineView()
        self.sidebar.setMinimumWidth(280)
        self.sidebar.load(QUrl(BACKEND + "/?sidebar=1&mode=app"))

        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(6, 6, 6, 0)
        v.setSpacing(4)

        # 工具栏：← → ⟳ | 地址栏 | 缩放 | 打开
        tb = QHBoxLayout()
        self.b_back = QPushButton("←")
        self.b_fwd = QPushButton("→")
        self.b_rel = QPushButton("⟳")
        for b in (self.b_back, self.b_fwd, self.b_rel):
            b.setFixedWidth(34)
            tb.addWidget(b)
        self.urlbar = QLineEdit()
        self.urlbar.setPlaceholderText("输入网址回车跳转")
        tb.addWidget(self.urlbar, 1)
        self.b_zo = QPushButton("－")
        self.b_zi = QPushButton("＋")
        self.lab_zoom = QLabel("100%")
        self.lab_zoom.setFixedWidth(42)
        self.lab_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for b in (self.b_zo, self.b_zi):
            b.setFixedWidth(30)
        self.b_open = QPushButton("打开")
        tb.addWidget(self.b_zo)
        tb.addWidget(self.lab_zoom)
        tb.addWidget(self.b_zi)
        tb.addWidget(self.b_open)
        v.addLayout(tb)

        # 多标签
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        v.addWidget(self.tabs)

        split.addWidget(self.sidebar)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([330, 1110])
        self.setCentralWidget(split)

        # 起始标签（127.0.0.1 后端自身 → 不注入助手）
        self._new_tab(BACKEND + "/newtab", "求职信息")

        # ---- 信号 ----
        self.b_back.clicked.connect(lambda: self._cur() and self._cur().back())
        self.b_fwd.clicked.connect(lambda: self._cur() and self._cur().forward())
        self.b_rel.clicked.connect(lambda: self._cur() and self._cur().reload())
        self.urlbar.returnPressed.connect(self._nav_to_bar)
        self.b_open.clicked.connect(self._open_external)
        self.b_zo.clicked.connect(lambda: self._zoom(-0.1))
        self.b_zi.clicked.connect(lambda: self._zoom(0.1))
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # ---- 桥接轮询：仪表板 -> 壳 ----
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(400)

    # ---------------- 注入：每次 http(s) 加载都注入（127.0.0.1 后端自身除外） ----------------

    def _company_for_url(self, url):
        """按 URL host 反查队列里匹配的公司，返回 {company, resume_id, ltype}（匹配不到返回空）。"""
        try:
            host = urllib.parse.urlparse(url).hostname or ""
            items = self._queue_cache
            if not items:  # 兜底：缓存空时直接拉一次
                try:
                    items = http_json("GET", "/api/queue", timeout=3).get("items") or []
                    self._queue_cache = items
                except Exception:
                    items = []
            for it in items:
                u = it.get("url") or ""
                try:
                    ih = urllib.parse.urlparse(u).hostname or ""
                except Exception:
                    ih = ""
                if ih and ih == host:
                    return {"company": it.get("company", ""),
                            "resume_id": it.get("resume_id", ""),
                            "ltype": it.get("ltype", "官网")}
        except Exception:
            pass
        return {"company": "", "resume_id": "", "ltype": "官网"}

    def _inject_into(self, tab, url):
        """对每次加载都注入助手：127.0.0.1 后端仪表板/newtab 不注入；其余 http(s) 都注入。"""
        try:
            host = urllib.parse.urlparse(url).hostname or ""
        except Exception:
            host = ""
        if host in ("127.0.0.1", "localhost", "::1"):
            return
        # 刷新队列缓存（拿最新公司/resume 绑定）
        try:
            self._queue_cache = http_json("GET", "/api/queue", timeout=3).get("items") or []
        except Exception:
            pass
        info = self._company_for_url(url)
        company = info.get("company", "")
        resume_id = info.get("resume_id", "")
        # 记忆按 host 取（无条件取：URL 没匹配到公司时也要有跨站记忆，ruleKeyOf 才生效）
        learned = self._learned_for(url)
        resume_name = self._resume_name(resume_id)
        js = build_assistant_js(company or "", resume_id or "", resume_name,
                                learned=learned, backend=BACKEND)
        # 给助手② 记录已投用：默认渠道与简历版本（doRecord 会读 window.__acChannel / __acRV）
        prelude = "window.__acChannel=" + json.dumps(info.get("ltype") or "官网") + ";"
        prelude += "window.__acRV=" + json.dumps(resume_id or "") + ";"
        full = prelude + js
        try:
            tab.page().runJavaScript(full)
        except Exception:
            pass

    # ---------------- 标签管理 ----------------

    def _learned_for(self, url):
        """取该站点已记住的字段（历史投递沉淀），失败时降级为空。"""
        try:
            host = urllib.parse.urlparse(url).hostname or "global"
            return http_json("GET", "/api/field-memory?host=" + urllib.parse.quote(host),
                             timeout=3).get("fields") or {}
        except Exception:
            return {}

    def _new_tab(self, url, title, resume_id="", company=""):
        # 注入已移到 loadFinished（_inject_into），这里只需建标签；company 仅用于标题约定。
        view = BrowserTab(url, self)
        idx = self.tabs.addTab(view, title or "新标签")
        self.tabs.setCurrentIndex(idx)
        view.urlChanged.connect(lambda _u, vw=view: self._on_url_changed(vw))
        view.loadFinished.connect(lambda _ok, vw=view: self._sync_bar(vw))
        return view

    def open_site(self, url, company="", resume_id=""):
        if not url:
            return
        self._new_tab(url, company or "新标签", resume_id=resume_id or "", company=company or "")

    def _close_tab(self, idx):
        w = self.tabs.widget(idx)
        if w is not None:
            w.deleteLater()
        self.tabs.removeTab(idx)

    def _cur(self):
        return self.tabs.currentWidget()

    def _resume_name(self, rid):
        try:
            reg = server.copilot.load_resumes(server.REGISTRY_PATH)
            for r in reg.get("resumes", []):
                if r.get("id") == rid:
                    return r.get("name", "")
        except Exception:
            pass
        return ""

    # ---------------- 工具栏行为 ----------------

    def _on_tab_changed(self, _idx):
        self._sync_bar()
        # 切换标签后把焦点交给页面，避免"看得见点不动"
        view = self._cur()
        if view is not None:
            view.setFocus()

    def _on_url_changed(self, view):
        if view is self._cur():
            self._sync_bar(view)

    def _sync_bar(self, view=None):
        view = view or self._cur()
        if view is None:
            return
        try:
            self.urlbar.setText(view.url().toString())
        except Exception:
            pass

    def _nav_to_bar(self):
        text = self.urlbar.text().strip()
        if not text:
            return
        if "://" not in text:
            text = "https://" + text
        view = self._cur()
        if view is not None:
            view.load(QUrl(text))   # 触发 loadFinished → 已注入助手

    def _zoom(self, delta):
        view = self._cur()
        if view is None:
            return
        z = max(0.3, min(2.0, view.zoomFactor() + delta))
        view.setZoomFactor(z)
        self.lab_zoom.setText(f"{int(round(z * 100))}%")

    def _open_external(self):
        view = self._cur()
        if view is not None:
            QDesktopServices.openUrl(view.url())

    # ---------------- 桥接：仪表板命令 ----------------
    # 本地 127.0.0.1 一次 GET 仅几毫秒，直接同步轮询即可，
    # 无需工作线程 + 跨线程 signal（链路更短、错误不会被吞）。

    def _poll(self):
        try:
            j = http_json("GET", "/api/bridge/poll", timeout=2)
        except Exception as exc:
            # 后端尚未就绪是启动初期的正常情况，其余异常打印出来便于排查
            if "Connection refused" not in str(exc) and "refused" not in str(exc).lower():
                print(f"[bridge poll] {type(exc).__name__}: {exc}")
            return
        for c in j.get("commands") or []:
            try:
                if c.get("action") == "open_site":
                    # 后端目前把 payload 展平到顶层；两种形状都兼容
                    p = c.get("payload") or c
                    self.open_site(p.get("url", ""), p.get("company", ""),
                                   p.get("resume_id", ""))
            except Exception as exc:
                print(f"[bridge cmd] {type(exc).__name__}: {exc} | cmd={c}")


def main():
    # QtWebEngine 要求：共享 OpenGL 上下文，且在 QApplication 创建前设置
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    # ---- 后端：已有实例在跑就复用，避免 10048 端口占用 ----
    uv = None
    if _backend_alive():
        print("[后端] 检测到已在运行，直接复用（端口 8787）")
    else:
        from uvicorn import Config, Server

        uv = Server(Config(app=server.app, host="127.0.0.1", port=8787, log_level="warning"))
        threading.Thread(target=uv.run, daemon=True).start()
        # 等后端就绪（最多 10s）
        for _ in range(40):
            if _backend_alive():
                break
            time.sleep(0.25)

    win = MainWindow()
    win.show()

    def _shutdown():
        if uv is not None:
            try:
                uv.should_exit = True
            except Exception:
                pass

    atexit.register(_shutdown)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
