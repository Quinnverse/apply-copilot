#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · 本地后端 (FastAPI)

把 copilot.py / filler.py / apply.py 的能力通过 HTTP 暴露给浏览器扩展、仪表板与桌面壳。

安全边界（与 copilot.py 一致，再强调一次）：
  * 只在本机 127.0.0.1 监听，不对外网开放。
  * 不代登录、不破解验证码、不自动提交；所有"提交"动作由用户本人完成。
  * 不读取任何账号凭据，不写运行日志，PII 仅留在本地文件。
  * CORS 允许扩展来源及显式配置的页面来源；普通招聘网页不可直接读取本机档案。
    不要用 `--host 0.0.0.0` 暴露无令牌服务。

启动：
  python server.py            # 默认 127.0.0.1:8787
  python server.py --port 9xxx

云端部署（腾讯云轻量等）环境变量覆盖 —— 全部可选，不设置则保持本地默认：
  AC_DATA_DIR    数据 JSON 目录（profile/queue_seed/queue/resumes/resume_active/
                 research_inbox/suggestions/field_memory/applications 等）
  AC_APPLY_DIR   apply.py 所在目录（默认从 profile.paths.autumn_skill_dir 推导）
  AC_STATIC_DIR  静态资源目录（默认 ./static）
  AC_RESUME_DIR  简历 PDF 兜底目录（注册路径失效时按文件名到该目录找，默认 DATA_DIR/resumes）
  AC_TOKEN       访问令牌：设置后除 /api/health 外所有 /api/* 需带 X-AC-Token 头或 ?token=
  AC_HOST/AC_PORT 监听地址/端口（命令行 --host/--port 优先）

⚠️ 公网部署安全：服务器上以 systemd 绑定 0.0.0.0 时务必设置 AC_TOKEN；
   本地开发请保持 127.0.0.1，不要在本机用 0.0.0.0 跑。
"""
import argparse
import contextvars
import hashlib
import hmac
import os
import re
import sys
import subprocess
import json
import threading
import uuid
from pathlib import Path
from datetime import date, datetime
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import copilot  # noqa: E402
import filler   # noqa: E402
from company_util import (  # noqa: E402  公司匹配共用模块（refresh_queue.py 也用）
    COMPANY_ALIAS, company_matches, company_tokens, norm_company,
)

# ---- 云端部署覆盖项（不设置则保持本地默认，行为零改动）----
DATA_DIR = Path(os.environ.get("AC_DATA_DIR") or HERE).resolve()
STATIC_DIR = Path(os.environ.get("AC_STATIC_DIR") or HERE / "static").resolve()
RESUME_DIR = Path(os.environ.get("AC_RESUME_DIR") or DATA_DIR / "resumes").resolve()
AC_TOKEN = (os.environ.get("AC_TOKEN") or "").strip()
# 多租户：令牌表文件（{tokens: {"<token>": {"label": "张三", "tenant": "t_xxx"}}}）
TOKENS_FILE = Path(os.environ.get("AC_TOKENS_FILE") or DATA_DIR / "tokens.json").resolve()
TENANTS_DIR = Path(os.environ.get("AC_TENANTS_DIR") or DATA_DIR / "tenants").resolve()

# 多令牌（可选）：AC_TOKENS="标签1:令牌1,标签2:令牌2"，逗号分隔；不含 ':' 时标签留空
_ENV_TOKENS = []
for _raw in (os.environ.get("AC_TOKENS") or "").split(","):
    _raw = _raw.strip()
    if not _raw:
        continue
    if ":" in _raw:
        _lab, _tok = _raw.split(":", 1)
    else:
        _lab, _tok = "", _raw
    _tok = _tok.strip()
    if _tok:
        _ENV_TOKENS.append((_tok, _lab.strip()))

# ---- 路径 ----
PROFILE_PATH = DATA_DIR / "profile.job.json"
REGISTRY_PATH = DATA_DIR / "resumes.json"
SEED_PATH = DATA_DIR / "queue_seed.json"
QUEUE_DB = DATA_DIR / "queue.json"
RESEARCH_INBOX_PATH = DATA_DIR / "research_inbox.json"
SUGGESTIONS_PATH = DATA_DIR / "suggestions.json"
RESUME_ACTIVE_PATH = DATA_DIR / "resume_active.json"
FIELD_MEMORY_PATH = DATA_DIR / "field_memory.json"
SCAN_DUMP_PATH = DATA_DIR / "scan_dump.json"

# 从 profile 推导 autumn 技能目录（AC_APPLY_DIR 可直接指定 apply.py 所在目录）
_job = copilot.load_json(PROFILE_PATH) if PROFILE_PATH.exists() else {}
_apply_env = (os.environ.get("AC_APPLY_DIR") or "").strip()
_skill_dir = ""   # 先在 if/else 之前初始化，避免 /api/health 在云端分支下 NameError
if _apply_env:
    APPLY_DIR = Path(_apply_env).resolve()
    APP_JSON = APPLY_DIR.parent / "state" / "applications.json"
    STATE_JSON = APPLY_DIR.parent / "state" / "seen_postings.json"
    _skill_dir = str(APPLY_DIR.parent)   # 语义同 else：指向技能目录（非 scripts/）
else:
    _skill_dir = (_job.get("paths") or {}).get("autumn_skill_dir", "")
    APPLY_DIR = Path(_skill_dir) / "scripts" if _skill_dir else None
    APP_JSON = Path(_skill_dir) / "state" / "applications.json" if _skill_dir else DATA_DIR / "applications.json"
    STATE_JSON = Path(_skill_dir) / "state" / "seen_postings.json" if _skill_dir else DATA_DIR / "seen_postings.json"
if APPLY_DIR and str(APPLY_DIR) not in sys.path:
    sys.path.insert(0, str(APPLY_DIR))
try:
    import apply as apply_mod  # noqa: E402
except ModuleNotFoundError as exc:
    if exc.name != "apply":
        raise
    import local_apply as apply_mod  # bundled fallback for a clean checkout

# 预加载档案（fill/match 用）
PROFILE = copilot.load_json(PROFILE_PATH) if PROFILE_PATH.exists() else {}


# ============================================================== 多租户（令牌分租户）
# 规则：一个访问令牌 = 一个租户 = 一个自包含的数据目录 DATA_DIR/tenants/<tid>。
# 不同令牌的用户之间，档案 / 简历 PDF / 投递记录 / 字段记忆 / 队列状态 完全隔离，
# 服务端按请求令牌路由目录，Token A 的请求永远读不到 Token B 目录里的任何字节。
# 没配任何令牌（本地 127.0.0.1 自用）时走 DEFAULT_PATHS，行为与改造前完全一致。

def _tid_of(token):
    """令牌 -> 租户 id（只落哈希前 16 位，令牌原文不写进目录名）。"""
    return "t_" + hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def _mk_paths(root, tid="", label=""):
    """按目录 root 组装一套完整数据路径（租户目录自包含，含 applications.json）。"""
    root = Path(root)
    return SimpleNamespace(
        tid=tid, label=label, root=root,
        DATA_DIR=root,
        RESUME_DIR=root / "resumes",
        PROFILE_PATH=root / "profile.job.json",
        REGISTRY_PATH=root / "resumes.json",
        SEED_PATH=root / "queue_seed.json",
        QUEUE_DB=root / "queue.json",
        RESEARCH_INBOX_PATH=root / "research_inbox.json",
        SUGGESTIONS_PATH=root / "suggestions.json",
        RESUME_ACTIVE_PATH=root / "resume_active.json",
        FIELD_MEMORY_PATH=root / "field_memory.json",
        SCAN_DUMP_PATH=root / "scan_dump.json",
        APP_JSON=root / "applications.json",
        STATE_JSON=root / "seen_postings.json",
    )


# 单用户 / 无令牌时的默认路径（就是上面的模块级常量，保持旧行为）
DEFAULT_PATHS = _mk_paths(DATA_DIR, tid="default", label="本地")
DEFAULT_PATHS.RESUME_DIR = RESUME_DIR
DEFAULT_PATHS.APP_JSON = APP_JSON
DEFAULT_PATHS.STATE_JSON = STATE_JSON

_TENANT_PATHS = {"default": DEFAULT_PATHS}
_TENANT_LOCK = threading.Lock()

# 令牌表缓存：{token: {"label":..,"tid":..}}，按文件 mtime 失效 —— 改 tokens.json 无需重启
_TOKEN_CACHE = {"mtime": -1.0, "map": {}}


def load_tokens():
    """读取令牌表（tokens.json 优先 + 环境变量 / AC_TOKEN 兜底）。"""
    try:
        mtime = TOKENS_FILE.stat().st_mtime if TOKENS_FILE.exists() else -1.0
    except OSError:
        mtime = -1.0
    if mtime != _TOKEN_CACHE["mtime"]:
        raw = {}
        if TOKENS_FILE.exists():
            try:
                raw = json.loads(TOKENS_FILE.read_text(encoding="utf-8")).get("tokens") or {}
            except Exception:
                raw = {}
        mp = {}
        for tok, meta in raw.items():
            tok = str(tok or "").strip()
            if not tok:
                continue
            meta = meta if isinstance(meta, dict) else {"label": str(meta)}
            mp[tok] = {"label": str(meta.get("label") or ""),
                       "tid": str(meta.get("tenant") or _tid_of(tok))}
        for tok, label in _ENV_TOKENS:
            mp.setdefault(tok, {"label": label, "tid": _tid_of(tok)})
        if AC_TOKEN and AC_TOKEN not in mp:
            mp[AC_TOKEN] = {"label": "owner", "tid": _tid_of(AC_TOKEN)}
        _TOKEN_CACHE["mtime"] = mtime
        _TOKEN_CACHE["map"] = mp
    return _TOKEN_CACHE["map"]


def match_token(given):
    """校验令牌，命中返回元信息 dict，否则 None（逐个 compare_digest，不早退）。"""
    given = str(given or "")
    if not given:
        return None
    hit = None
    for tok, meta in load_tokens().items():
        if hmac.compare_digest(given, tok):
            hit = meta
    return hit


def _seed_tenant(root):
    """新租户首次访问时初始化为空数据 —— 绝不从别的租户/root 目录继承任何内容。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "resumes").mkdir(parents=True, exist_ok=True)

    def _init(name, obj):
        p = root / name
        if not p.exists():
            copilot.dump_json(p, obj)

    _init("resumes.json", {"resumes": []})
    _init("resume_active.json", {"active": ""})
    _init("field_memory.json", {"fields": {}})
    _init("queue.json", {"status": {}, "items": [], "bind": {}})
    _init("applications.json", {"applications": {}})
    _init("profile.job.json", {"schema_version": 1, "basic": {}})
    # 岗位种子是公共数据：给新租户复制一份（之后各改各的，互不干扰）
    if not (root / "queue_seed.json").exists():
        shared = DATA_DIR / "queue_seed.json"
        items = copilot.load_json(shared).get("items", []) if shared.exists() else []
        copilot.dump_json(root / "queue_seed.json", {"items": items})


def tenant_paths(meta):
    """按令牌元信息取（必要时创建）租户路径对象。"""
    tid = meta["tid"]
    ps = _TENANT_PATHS.get(tid)
    if ps is not None and ps.root.exists():
        return ps
    with _TENANT_LOCK:
        ps = _TENANT_PATHS.get(tid)
        if ps is None:
            _seed_tenant(TENANTS_DIR / tid)
            ps = _mk_paths(TENANTS_DIR / tid, tid, meta.get("label", ""))
            _TENANT_PATHS[tid] = ps
        return ps


# 当前请求所属租户（middleware 鉴权通过后 set；本地无令牌时为 DEFAULT_PATHS）
_tenant_var = contextvars.ContextVar("ac_tenant", default=None)


def current_paths():
    return _tenant_var.get() or DEFAULT_PATHS


def current_profile():
    """按当前租户实时读档案（多租户下不能用 import 期预加载的 PROFILE）。"""
    p = current_paths().PROFILE_PATH
    return copilot.load_json(p) if p.exists() else {}


class _TenantProxy:
    """让 TENANT.REGISTRY_PATH 这类写法按当前请求动态解析到该租户的目录。"""

    def __getattr__(self, name):
        return getattr(current_paths(), name)


TENANT = _TenantProxy()

# 是否需要令牌（import 期判定，仅用于决定是否关闭 /docs）
AUTH_ENABLED = bool(AC_TOKEN or _ENV_TOKENS or TOKENS_FILE.exists())

# ==== END TENANT CONFIG ====

# 父目录（gen_submit_list.py 所在处；脚本用相对路径读 秋招投递进度.html）
PARENT_DIR = HERE.parent


# ---------------------------------------------------------------- 请求模型

class MatchReq(BaseModel):
    jd: str


class FillField(BaseModel):
    tag: str = "input"
    type: str = "text"
    id: str = ""
    name: str = ""
    placeholder: str = ""
    label: str = ""


class FillReq(BaseModel):
    fields: List[dict]
    jd: Optional[str] = None


class StatusReq(BaseModel):
    status: str  # 未投 / 进行中 / 已投 / 笔试 / 面试


class BindReq(BaseModel):
    resume_id: str = ""


class MarkReq(BaseModel):
    company: str
    title: str = ""  # 可选：不传则由后端按 company 反查 seed 的 role 作默认标题
    resume_version: Optional[str] = None
    channel: str = "官网"
    jd: Optional[str] = None
    date: Optional[str] = None
    note: Optional[str] = ""


class ResearchReq(BaseModel):
    cat: str = ""
    keywords: str = ""


class InboxPostReq(BaseModel):
    request_id: str
    items: List[dict] = []


class AdoptReq(BaseModel):
    id: str


class ActiveReq(BaseModel):
    active: str


class BridgeReq(BaseModel):
    action: str
    payload: dict = {}


class FieldMemReq(BaseModel):
    host: str = ""
    fields: dict = {}
    company: str = ""
    resume_id: str = ""


class QueueMergeReq(BaseModel):
    """queue_seed 合并请求：直接给 items，或 source='inbox' 从调研回写取。"""
    items: Optional[List[dict]] = None
    source: Optional[str] = None


# 允许写入 queue.json 的状态集合（"已记录" 由 applications.json 派生，不在此列）
VALID_STATUS = {"未投", "进行中", "已投", "笔试", "面试"}


# ---------------------------------------------------------------- 队列状态

def load_seed():
    if TENANT.SEED_PATH.exists():
        return copilot.load_json(TENANT.SEED_PATH).get("items", [])
    return []


# 公司名规范化/别名匹配已抽到 company_util.py（server 与 refresh_queue 共用）。
# 这里保留旧内部名做兼容别名。
_norm_company = norm_company
_alias_groups = None  # 历史名，已并入 company_util.alias_groups；server 内部不再使用


def load_queue_doc():
    """读取 queue.json 全量文档：{status:{id:status}, items:[采纳后的岗位]}。"""
    if TENANT.QUEUE_DB.exists():
        doc = copilot.load_json(TENANT.QUEUE_DB)
        doc.setdefault("status", {})
        doc.setdefault("items", [])
        return doc
    return {"status": {}, "items": []}


def save_queue_doc(doc):
    copilot.dump_json(TENANT.QUEUE_DB, doc)


def load_queue_state():
    return load_queue_doc().get("status", {})


def save_queue_state(state):
    """仅更新 status 映射，保留已采纳的 items。"""
    doc = load_queue_doc()
    doc["status"] = state
    save_queue_doc(doc)


def load_queue_items():
    return load_queue_doc().get("items", [])


def recorded_companies():
    """从 applications.json 取出已记录投递的公司名集合。"""
    if not TENANT.APP_JSON or not TENANT.APP_JSON.exists():
        return set()
    store = apply_mod.load_store(str(TENANT.APP_JSON))
    out = set()
    for a in store.get("applications", {}).values():
        c = (a.get("company") or "").strip()
        if c:
            out.add(c)
    return out


def merge_queue():
    """合并 seed(队列种子) + 已记录(applications.json) + 已采纳(queue.json items)
    + 待采纳建议(suggestions.json)，派生统一的队列视图。

    状态优先级：已记录(投递库) > queue.json 状态(进行中/已投/笔试/面试) > 未投(默认)。
    "已记录"永远由 applications.json 推导，不会被 queue.json 覆盖。
    """
    seed = load_seed()
    doc = load_queue_doc()
    state = doc.get("status", {})
    custom = doc.get("items", [])
    bind = doc.get("bind", {})  # 行级简历绑定: {queue_id: resume_id}
    recorded = recorded_companies()
    seed_ids = set()
    out = []
    for it in seed:
        cid = it.get("id")
        seed_ids.add(cid)
        company = it.get("company", "")
        # 状态优先级：已记录(来自投递库) > 进行中/未投(来自 queue.json) > 未投(默认)
        status = "未投"
        if any(company and company_matches(company, rc) for rc in recorded):
            status = "已记录"
        elif cid in state:
            status = state[cid]
        # 已记录的company，把已投title回写
        titles = []
        if status == "已记录" and TENANT.APP_JSON and TENANT.APP_JSON.exists():
            store = apply_mod.load_store(str(TENANT.APP_JSON))
            for a in store.get("applications", {}).values():
                if a.get("company") and company and company_matches(company, a["company"]):
                    titles.append({"title": a.get("title"), "resume_version": a.get("resume_version"),
                                   "stage": a.get("stage"), "applied_at": a.get("applied_at")})
        out.append({**it, "status": status, "recorded_titles": titles,
                    "sugg": False, "adopted": False})
    # 已采纳的自定义岗位（不在 seed 里）
    custom_ids = set()
    for it in custom:
        cid = it.get("id")
        if cid in seed_ids:
            continue
        custom_ids.add(cid)
        status = state.get(cid, "未投")
        out.append({**it, "status": status, "recorded_titles": [],
                    "sugg": bool(it.get("sugg", False)), "adopted": bool(it.get("adopted", True))})
    # 待采纳建议（sugg:True、尚未采纳）——合并进队列视图，带 sugg 标记，
    # 由前端「生成更多」面板展示，用户「采纳」后转入 custom items。
    sugg = load_suggestions()
    for s in sugg:
        cid = s.get("id")
        if cid in seed_ids or cid in custom_ids:
            continue
        status = state.get(cid, "未投")
        out.append({**s, "status": status, "recorded_titles": [],
                    "sugg": True, "adopted": False})
    # 行级简历绑定回填：把 queue.json 的 bind map 写进每个 item
    for it in out:
        it["resume_id"] = bind.get(it.get("id"), "")
    return out


# ---------------------------------------------------------------- 简历激活态

def active_resume_id():
    if TENANT.RESUME_ACTIVE_PATH.exists():
        d = copilot.load_json(TENANT.RESUME_ACTIVE_PATH)
        aid = d.get("active")
        if aid:
            return aid
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    rs = reg.get("resumes", [])
    return rs[0].get("id") if rs else None


# ---------------------------------------------------------------- 调研入箱 / 建议

def load_inbox():
    if TENANT.RESEARCH_INBOX_PATH.exists():
        return copilot.load_json(TENANT.RESEARCH_INBOX_PATH).get("requests", [])
    return []


def save_inbox(reqs):
    copilot.dump_json(TENANT.RESEARCH_INBOX_PATH, {"requests": reqs})


def load_suggestions():
    if TENANT.SUGGESTIONS_PATH.exists():
        return copilot.load_json(TENANT.SUGGESTIONS_PATH).get("items", [])
    return []


def save_suggestions(items):
    copilot.dump_json(TENANT.SUGGESTIONS_PATH, {"items": items})


def resume_file_path(r):
    """解析简历 PDF 实际路径：注册的 path 失效时，按文件名到当前租户的 resumes/ 目录兜底查找
    （云端布局下 resumes.json 里的 Windows 本机路径不存在，PDF 统一放租户目录 resumes/）。

    注意：云服务器是 POSIX，Windows 反斜杠不是分隔符，必须先归一化成 '/'，
    否则 Path(...).name 会是整串路径、兜底查找失败（本地 Windows 跑不出来这个 bug）。
    """
    raw = str(r.get("path") or "").replace("\\", "/")
    p = Path(raw)
    if not p.is_absolute():
        p = TENANT.DATA_DIR / p
    if not p.exists():
        cand = TENANT.RESUME_DIR / Path(raw).name
        if cand.exists():
            return cand
    return p


# ---------------------------------------------------------------- 应用

app = FastAPI(
    title="网申助手 Copilot 后端",
    # 云端（设置了 AC_TOKEN）关闭交互文档：/docs /redoc /openapi.json 会匿名泄露全部路由清单；
    # middleware 只管 /api/*，拦不住这三个框架自带端点。本地无 token 保持原样（行为不变）。
    **({"docs_url": None, "redoc_url": None, "openapi_url": None} if AUTH_ENABLED else {}),
)

app.add_middleware(
    CORSMiddleware,
    # Extension background requests originate from chrome-extension://<id>.
    # A wildcard would let any visited web page read an unauthenticated local profile.
    allow_origins=["http://127.0.0.1:8787", "http://localhost:8787"] +
                  [x.strip() for x in os.environ.get("AC_ALLOWED_ORIGINS", "").split(",") if x.strip()],
    allow_origin_regex=r"^(chrome-extension|moz-extension)://[a-zA-Z0-9-]+$",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


# 后端构建号：桌面壳据此判断 8787 上跑的是不是当前代码（避免旧进程残留导致新接口 404）
BUILD_ID = "2026-09-29a"


# ---- 访问令牌鉴权（仅云端：设置了 AC_TOKEN 才启用；本地不设 = 行为与旧版一致）----
@app.middleware("http")
async def _token_guard(request: Request, call_next):
    """除 /api/health 外，所有 /api/* 要求 X-AC-Token 头或 ?token= 命中令牌表。

    多租户：命中哪个令牌，就把该令牌对应的租户目录绑到当前请求（contextvars），
    之后所有数据读写只看这一个目录 —— 令牌 A 的请求读不到令牌 B 的任何数据。
    静态页（/ 与 /static/*）只是壳，不鉴权 —— 数据都走 /api/*。
    """
    p = request.url.path
    if p.startswith("/api/") and p != "/api/health" and load_tokens():
        given = (request.headers.get("X-AC-Token") or ""
                 or request.query_params.get("token") or "")
        meta = match_token(given)
        if not meta:
            return JSONResponse({"detail": "访问令牌缺失或不正确"}, status_code=401)
        _tenant_var.set(tenant_paths(meta))
    else:
        _tenant_var.set(DEFAULT_PATHS)
    try:
        return await call_next(request)
    finally:
        _tenant_var.set(None)


@app.get("/api/health")
def health():
    # health 是唯一豁免鉴权的端点：云端模式下不回显内部路径（避免匿名泄露服务器布局）
    out = {"ok": True, "build": BUILD_ID, "auth": bool(load_tokens())}
    if not load_tokens():
        out["autumn_skill_dir"] = _skill_dir or None
        out["applications_json"] = str(TENANT.APP_JSON) if TENANT.APP_JSON else None
    return out


@app.get("/api/whoami")
def api_whoami():
    """当前令牌对应的身份（面板用来显示"你是谁"，也用来确认数据确实分了租户）。"""
    ps = current_paths()
    return {"ok": True, "build": BUILD_ID, "tenant": ps.tid, "label": ps.label or "",
            "multi_tenant": bool(load_tokens())}


@app.get("/api/resumes")
def api_resumes():
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    items = []
    for r in reg.get("resumes", []):
        item = {
            "id": r.get("id"),
            "name": r.get("name"),
            "tags": r.get("tags", []),
            "note": r.get("note", ""),
            "filename": resume_file_path(r).name,
        }
        if not AC_TOKEN:
            # 本地模式保留原 path 字段（行为不变）；云端模式不回显本机 Windows 路径
            item["path"] = r.get("path")
        items.append(item)
    return {"resumes": items}


@app.post("/api/match")
def api_match(req: MatchReq):
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    if not reg.get("resumes"):
        raise HTTPException(400, "还没有注册简历，先跑 register-resume")
    if not req.jd.strip():
        raise HTTPException(400, "match 需要 jd 文本")
    scored = [copilot.score_resume(r, req.jd) for r in reg["resumes"]]
    scored.sort(key=lambda x: -x["score"])
    return {"jd_chars": len(req.jd), "recommended": scored[0], "candidates": scored}


@app.post("/api/fill")
def api_fill(req: FillReq):
    if not current_profile():
        raise HTTPException(500, "档案 profile.job.json 缺失")
    fields = req.fields
    if not isinstance(fields, list) or not fields:
        raise HTTPException(400, "fields 必须是非空列表")
    payload = filler.build_fill_payload(fields, current_profile())
    # 若带了 JD，顺带给出简历推荐
    rec = None
    if req.jd and req.jd.strip():
        reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
        if reg.get("resumes"):
            scored = sorted((copilot.score_resume(r, req.jd) for r in reg["resumes"]),
                            key=lambda x: -x["score"])
            rec = scored[0]
    return {
        "fields": len(payload),
        "payload": payload,
        "recommended_resume": rec,
        "filled": sum(1 for p in payload if p["confidence"] >= 0.5 and p["value"]),
        "missed": sum(1 for p in payload if not (p["confidence"] >= 0.5 and p["value"])),
    }


@app.get("/api/queue")
def api_queue():
    return {"items": merge_queue()}


@app.put("/api/queue/{item_id}/status")
def api_queue_status(item_id: str, req: StatusReq):
    if req.status not in VALID_STATUS:
        raise HTTPException(400, "status 仅支持: " + " / ".join(sorted(VALID_STATUS)))
    doc = load_queue_doc()
    doc.setdefault("status", {})[item_id] = req.status
    save_queue_doc(doc)
    return {"id": item_id, "status": req.status}


@app.put("/api/queue/{item_id}/bind")
def api_queue_bind(item_id: str, req: BindReq):
    """行级简历绑定：把 resume_id 写入 queue.json 的 bind 字段。"""
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    ids = [r.get("id") for r in reg.get("resumes", [])]
    if req.resume_id not in ids:
        raise HTTPException(400, f"无效 resume id：{req.resume_id}")
    doc = load_queue_doc()
    doc.setdefault("bind", {})[item_id] = req.resume_id
    save_queue_doc(doc)
    return {"ok": True, "id": item_id, "resume_id": req.resume_id}


@app.post("/api/mark")
def api_mark(req: MarkReq):
    if not TENANT.APP_JSON:
        raise HTTPException(500, "未配置 applications.json 路径")
    if not req.company:
        raise HTTPException(400, "company 必填")
    # 外部未传 title：按 company 匹配 seed 拿 role 作默认标题（找不到留空串）
    title = (req.title or "").strip()
    if not title:
        seed_items = load_seed()
        # ① 规范化后精确相等（同主体同名，最可靠）
        for it in seed_items:
            if _norm_company(it.get("company")) == _norm_company(req.company):
                title = it.get("role", "") or ""
                break
        # ② 别名兜底：显式登记的同主体不同写法（如"字节"→"字节跳动"）
        if not title:
            for it in seed_items:
                if company_matches(it.get("company"), req.company):
                    title = it.get("role", "") or ""
                    break
    # ---- 红线4：同公司·同天·同岗位去重（第一道闸）----
    # cmd_mark 的 app_id = "manual-{date}-{len+1}" 每次都是新 id，其自身去重永不触发，
    # 这里必须在调用前用 applications.json 做真实去重，否则同一天可重复记账 N 次。
    check_date = (req.date or date.today().isoformat())[:10]
    title_l = title.strip()
    try:
        store = apply_mod.load_store(str(TENANT.APP_JSON))
    except Exception:
        store = {}
    for a in (store.get("applications") or {}).values():
        if not company_matches(a.get("company") or "", req.company):
            continue
        if (a.get("applied_at") or "")[:10] != check_date:
            continue
        atitle = (a.get("title") or "").strip()
        # 同 title（或双方都无 title）即视为同一次投递
        if atitle == title_l or (not atitle and not title_l):
            raise HTTPException(409, f"已记录过：{req.company} · {atitle or title_l} · {check_date}")
    args = SimpleNamespace(
        applications=str(TENANT.APP_JSON),
        state=str(TENANT.STATE_JSON) if TENANT.STATE_JSON else None,
        posting_id=None,
        company=req.company,
        title=title,
        resume_version=req.resume_version or "",
        channel=req.channel or "官网",
        date=req.date,
        next_action=None,
        note=req.note or "",
        force=False,
    )
    # 捕获 apply.py 的 SystemExit（如已记录过）—— 第二道闸
    try:
        apply_mod.cmd_mark(args)
    except SystemExit as exc:
        msg = str(exc)
        if "已记录过" in msg:
            raise HTTPException(409, msg)
        raise HTTPException(400, msg)
    # 标记该公司在队列里为已记录（下次合并会由 applications.json 推导，这里也置一下）
    return {"ok": True, "company": req.company, "title": title,
            "resume_version": req.resume_version or "", "channel": req.channel}


# ---------------------------------------------------------------- 油猴助手上下文（一次拉齐全部注入数据）

def _host_of(url):
    """从 url 提取小写 hostname；解析失败返回空串。"""
    from urllib.parse import urlparse
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def _strip_www(h):
    return (h or "").lower().strip()[4:] if (h or "").lower().startswith("www.") else (h or "").lower().strip()


def find_seed_by_host(host):
    """按页面 host 反查 seed 岗位：① seed url 的 host 精确匹配（忽略 www. 前缀）；
    ② company_matches 兜底（host 里含公司 ascii 词元也算，如 galbot.com ↔ 银河通用 Galbot）。
    返回 (seed_item, match_kind)；找不到返回 (None, "")。"""
    h = _strip_www(host)
    if not h:
        return None, ""
    seeds = load_seed()
    # ① url host 精确匹配
    for it in seeds:
        if _strip_www(_host_of(it.get("url", ""))) == h:
            return it, "url"
    # ② 公司名/别名匹配：host 与公司名相等，或公司 ascii 词元出现在 host 里
    for it in seeds:
        c = it.get("company", "")
        if not c:
            continue
        if company_matches(h, c):
            return it, "company"
        toks = company_tokens(c)
        if toks and any(t in h for t in toks):
            return it, "company-token"
    return None, ""


@app.get("/api/assistant-context")
def api_assistant_context(host: str = "", request: Request = None):
    """油猴脚本开机第一问：一次返回填表所需的全部上下文。

    company 为空时（未命中公司）也返回 ok:True 与全局 rules/values/syn/learned，
    由前端决定是否在「用户手动启用」的站点上照常注入。
    """
    seed, match_kind = find_seed_by_host(host)
    company = (seed or {}).get("company", "")
    # 简历：行级绑定（queue.json bind，key 为 item id 或公司名）优先，回退激活简历
    bind = load_queue_doc().get("bind", {})
    resume_id = ""
    if seed:
        resume_id = bind.get(seed.get("id"), "") or bind.get(company, "")
    if not resume_id:
        resume_id = active_resume_id() or ""
    resume_name = ""
    if resume_id:
        for r in copilot.load_resumes(TENANT.REGISTRY_PATH).get("resumes", []):
            if r.get("id") == resume_id:
                resume_name = r.get("name", "")
                break
    # 规则表（filler.FIELD_RULES + 档案取值）——与 assistant_bridge.RULES_JSON 同源
    rules = [{"k": kw, "v": str(getter(current_profile()) or ""), "t": types}
             for kw, getter, types in filler.FIELD_RULES]
    # 宽松同义词（filler.FIELD_SYN 单一真源）——与 assistant_bridge.SYN_JSON 同源
    syn = [{"re": pat, "name": name} for pat, name in filler.FIELD_SYN]
    learned = load_field_memory().get("fields") or {}
    base = str(request.base_url).rstrip("/") if request is not None else "http://127.0.0.1:8787"
    return {
        "ok": True, "build": BUILD_ID,
        "company": company, "match_kind": match_kind,
        "resume_id": resume_id or "", "resume_name": resume_name,
        "role": (seed or {}).get("role", ""), "deadline": (seed or {}).get("deadline", ""),
        "ltype": (seed or {}).get("ltype", ""), "url": (seed or {}).get("url", ""),
        "rules": rules, "values": assistant_profile_values(current_profile()),
        "syn": syn, "learned": learned, "backend": base,
    }


def assistant_profile_values(p):
    """「点选填充 / 档案速查」扁平值表。延迟 import assistant_bridge 以避免
    循环 import（assistant_bridge 模块级 import server）。"""
    from assistant_bridge import profile_values
    return profile_values(p or {})


# ---------------------------------------------------------------- 队列种子合并（AI 回写 / 手动批量并入）

@app.post("/api/queue-merge")
def api_queue_merge(req: QueueMergeReq):
    """把 items（queue_seed 同 schema）或调研回写（source='inbox'）确定性并入清单。

    内部走 refresh_queue.refresh 四步：时间衰减 → 剔除已投 → 去重合并 → 排序写回。
    同公司新 role 追加为多岗位不覆盖；已投（含别名）剔除；写回 queue_seed.json
    并同步 queue.json（新 id 预置「未投」状态）。
    """
    extra = [it for it in (req.items or []) if isinstance(it, dict)]
    if not extra and (req.source or "").lower() == "inbox":
        for r in load_inbox():
            if r.get("status") != "done":
                continue
            for it in (r.get("items") or []):
                if isinstance(it, dict) and (it.get("company") or "").strip() \
                        and (it.get("url") or "").strip():
                    extra.append(it)
    if TENANT.APP_JSON:
        apps_path = str(TENANT.APP_JSON)
    else:
        apps_path = ""
    import refresh_queue as rq
    stat = rq.refresh(seed_path=TENANT.SEED_PATH, apps_path=apps_path, out_path=TENANT.SEED_PATH,
                      extra_items=extra, write=True)
    # 同步 queue.json：为新并入的 id 预置「未投」状态（已存在的状态不动）
    doc = load_queue_doc()
    changed = False
    for it in load_seed():
        sid = it.get("id")
        if sid and sid not in doc["status"]:
            doc["status"][sid] = "未投"
            changed = True
    if changed:
        save_queue_doc(doc)
    return {"ok": True, "added": stat["added"], "merged": stat["merged"],
            "removed_recorded": stat["removed_recorded"], "total": stat["total"],
            "decayed": stat["decayed"], "inbox_used": bool(extra) and not req.items}


@app.get("/api/resume-file/{rid}")
def api_resume_file(rid: str):
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    target = None
    for r in reg.get("resumes", []):
        if r.get("id") == rid:
            target = r
            break
    if not target:
        raise HTTPException(404, f"未找到简历版本 {rid}")
    path = resume_file_path(target)
    if not path.exists():
        raise HTTPException(404, f"简历文件不存在：{path}")
    return FileResponse(str(path), media_type="application/pdf",
                        filename=path.name)


# ---------------------------------------------------------------- 简历激活态

@app.get("/api/resume/active")
def api_resume_active_get():
    return {"active": active_resume_id()}


@app.put("/api/resume/active")
def api_resume_active_put(req: ActiveReq):
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    ids = [r.get("id") for r in reg.get("resumes", [])]
    if req.active not in ids:
        raise HTTPException(400, f"无效 resume id：{req.active}")
    copilot.dump_json(TENANT.RESUME_ACTIVE_PATH, {"active": req.active})
    return {"active": req.active}


# ---------------------------------------------------------------- 简历上传 / 删除（油猴面板自助管理）

@app.post("/api/resume")
async def api_resume_upload(file: UploadFile = File(...), name: str = Form("")):
    """上传简历（PDF/图片）：保存到当前租户的 resumes/ 目录，注册进该租户的 resumes.json；
    若是第一份简历则自动设为默认激活态。返回新注册的条目。"""
    TENANT.RESUME_DIR.mkdir(parents=True, exist_ok=True)
    orig = (name or (file.filename or "resume.pdf")).strip() or "resume.pdf"
    ext = Path(orig).suffix or ".pdf"
    stem = Path(orig).stem or "resume"
    # 安全文件名：只保留字母数字/连字符/汉字，超长截断，碰撞时追加随机后缀
    safe_stem = re.sub(r'[^\w\-\u4e00-\u9fff]+', '_', stem)[:60] or "resume"
    rid = "rs-" + uuid.uuid4().hex[:10]
    fname = f"{safe_stem}{ext}"
    cand = TENANT.RESUME_DIR / fname
    while cand.exists():
        fname = f"{safe_stem}_{uuid.uuid4().hex[:4]}{ext}"
        cand = TENANT.RESUME_DIR / fname
    contents = await file.read()
    cand.write_bytes(contents)
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    resumes = reg.get("resumes", [])
    entry = {"id": rid, "name": orig, "path": str(cand), "tags": []}
    resumes.append(entry)
    reg["resumes"] = resumes
    copilot.dump_json(TENANT.REGISTRY_PATH, reg)
    # 第一份简历自动设为默认（写 resume_active.json）
    if not active_resume_id():
        copilot.dump_json(TENANT.RESUME_ACTIVE_PATH, {"active": rid})
    return {"ok": True, "resume": entry}


@app.delete("/api/resume/{rid}")
def api_resume_delete(rid: str):
    """删除简历：从 resumes.json 移除条目并删除磁盘文件；
    若删掉的是默认简历，则改指下一份剩余简历，没有则清空默认态。"""
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    resumes = reg.get("resumes", [])
    target = next((r for r in resumes if r.get("id") == rid), None)
    if not target:
        raise HTTPException(404, f"未找到简历：{rid}")
    try:
        p = resume_file_path(target)
        if p.exists():
            p.unlink()
    except Exception:
        pass
    reg["resumes"] = [r for r in resumes if r.get("id") != rid]
    copilot.dump_json(TENANT.REGISTRY_PATH, reg)
    # 若删的是默认，则改指下一份或清空
    if active_resume_id() == rid:
        remaining = reg["resumes"]
        new_active = remaining[0]["id"] if remaining else ""
        copilot.dump_json(TENANT.RESUME_ACTIVE_PATH, {"active": new_active})
    return {"ok": True, "active": active_resume_id()}


# ---------------------------------------------------------------- 投递清单重生成

@app.post("/api/regenerate")
def api_regenerate():
    """子进程重跑父目录 gen_submit_list.py（cwd 设为父目录，因为脚本用相对路径读
    秋招投递进度.html）。成功返回 {'ok':True,'count': len(merge_queue())}。"""
    script = PARENT_DIR / "gen_submit_list.py"
    if not script.exists():
        return {"ok": False, "error": f"找不到脚本：{script}"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(PARENT_DIR),
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "gen_submit_list.py 执行超时(>60s)"}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"执行异常：{exc}"}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:600]
        return {"ok": False, "error": f"退出码 {proc.returncode}：{err}"}
    try:
        count = len(merge_queue())
    except Exception:
        count = 0
    return {"ok": True, "count": count}


# ---------------------------------------------------------------- 调研入箱（给 WorkBuddy AI 助手）

@app.post("/api/research")
def api_research(req: ResearchReq):
    """写入 research_inbox.json（待 AI 回写岗位）。返回 request_id + task_id + 状态。"""
    reqs = load_inbox()
    rid = "req-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    task_id = "task-" + uuid.uuid4().hex[:8]
    reqs.append({
        "id": rid,
        "task_id": task_id,
        "cat": req.cat or "",
        "keywords": req.keywords or "",
        "status": "queued",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "items": [],
    })
    save_inbox(reqs)
    return {"ok": True, "request_id": rid, "task_id": task_id, "status": "queued"}


@app.get("/api/research/status/{task_id}")
def api_research_status(task_id: str):
    """按 task_id 查调研任务状态（queued / done / failed）。

    status 从 research_inbox.json 中该任务的当前 status 推导；items_count 为
    已回写的岗位数（done 后才有意义）。查不到返回 404。
    """
    task_id = (task_id or "").strip()
    for r in load_inbox():
        if (r.get("task_id") or "").strip() == task_id:
            status = (r.get("status") or "queued").strip() or "queued"
            return {
                "ok": True,
                "task_id": task_id,
                "status": status,
                "items_count": len(r.get("items") or []),
                "created_at": r.get("created_at") or "",
            }
    raise HTTPException(404, f"未找到调研任务：{task_id}")


@app.get("/api/inbox")
def api_inbox():
    """返回 research_inbox.json 中 status=='done' 的请求及其 items（AI 回写的岗位）。"""
    reqs = load_inbox()
    done = [r for r in reqs if r.get("status") == "done"]
    return {"requests": done}


@app.post("/api/inbox")
def api_inbox_post(req: InboxPostReq):
    """AI 回写：把对应请求标 status='done'，并把 items 追加进 suggestions.json
    （每条加 sugg:True 与 id），同时把 items 回写进该 inbox 请求便于 /api/inbox 直接展示。"""
    reqs = load_inbox()
    target = next((r for r in reqs if r.get("id") == req.request_id), None)
    if not target:
        raise HTTPException(404, f"未找到调研请求：{req.request_id}")
    target["status"] = "done"
    target["items"] = req.items
    save_inbox(reqs)

    sugg = load_suggestions()
    added = 0
    for it in (req.items or []):
        sid = "sug-" + uuid.uuid4().hex[:8]
        entry = {
            "id": sid,
            "request_id": req.request_id,
            "sugg": True,
            "company": it.get("company", ""),
            "cat": it.get("cat", ""),
            "role": it.get("role", ""),
            "sal": it.get("sal", ""),
            "loc": it.get("loc", ""),
            "deadline": it.get("deadline", ""),
            "url": it.get("url", ""),
        }
        sugg.append(entry)
        added += 1
    save_suggestions(sugg)
    return {"ok": True, "added": added}


# ---------------------------------------------------------------- 建议（生成更多）

@app.get("/api/suggestions")
def api_suggestions():
    """返回 suggestions.json 的 items（供仪表板「生成更多」视图轮询展示）。"""
    return {"items": load_suggestions()}


@app.post("/api/suggestions/adopt")
def api_suggest_adopt(req: AdoptReq):
    """采纳一条建议：从 suggestions.json 移除，写入 queue.json（status=未投），
    下次合并即进入主队列视图。"""
    sugg = load_suggestions()
    found = next((s for s in sugg if s.get("id") == req.id), None)
    if not found:
        raise HTTPException(404, f"未找到建议：{req.id}")
    sugg = [s for s in sugg if s.get("id") != req.id]
    save_suggestions(sugg)

    doc = load_queue_doc()
    item = {k: found.get(k) for k in
            ("id", "company", "cat", "role", "sal", "loc", "deadline", "url")}
    item["sugg"] = False
    item["adopted"] = True
    doc.setdefault("items", []).append(item)
    doc.setdefault("status", {})[found.get("id")] = "未投"
    save_queue_doc(doc)
    return {"ok": True, "added": 1}


@app.delete("/api/suggestions/{sid}")
def api_suggest_dismiss(sid: str):
    """忽略一条建议：仅从 suggestions.json 移除，不写入队列。"""
    sugg = load_suggestions()
    sugg = [s for s in sugg if s.get("id") != sid]
    save_suggestions(sugg)
    return {"ok": True}


# ---------------------------------------------------------------- 字段记忆（每次投递沉淀，下次自动填）

def load_field_memory():
    """全局字段记忆（不按站点分桶 —— 同一份档案在所有站点填的内容是一样的）。
    兼容早期的 hosts 分桶格式：启动时合并进全局。"""
    if TENANT.FIELD_MEMORY_PATH.exists():
        doc = copilot.load_json(TENANT.FIELD_MEMORY_PATH)
        if isinstance(doc, dict):
            if not isinstance(doc.get("fields"), dict):
                merged = {}
                for _h, m in (doc.get("hosts") or {}).items():
                    if isinstance(m, dict):
                        merged.update(m)
                doc = {**doc, "fields": merged}
            return doc
    return {"fields": {}}


@app.get("/api/field-memory")
def api_field_memory_get(host: str = ""):
    """返回全局已记住的字段 {key: value}（忽略 host，保留参数只为兼容）。"""
    return {"fields": load_field_memory().get("fields") or {}}


@app.post("/api/field-memory")
def api_field_memory_post(req: FieldMemReq):
    """记住本页字段（含用户手填的），合并进全局 field_memory.json。"""
    doc = load_field_memory()
    cur = doc["fields"]
    added = 0
    for k, v in (req.fields or {}).items():
        k, v = str(k or "").strip(), str(v if v is not None else "").strip()
        if k and v:
            cur[k[:120]] = v[:500]
            added += 1
    copilot.dump_json(TENANT.FIELD_MEMORY_PATH, doc)
    return {"ok": True, "added": added, "total": len(cur)}


@app.delete("/api/field-memory/{key}")
def api_field_memory_delete(key: str):
    """删除单条字段记忆。存储时 key 会被截断到 120 字符，精确匹配不到时再试截断后的 key。"""
    doc = load_field_memory()
    cur = doc.setdefault("fields", {})
    removed = False
    if key in cur:
        del cur[key]
        removed = True
    else:
        tk = key[:120]
        if tk in cur:
            del cur[tk]
            removed = True
    copilot.dump_json(TENANT.FIELD_MEMORY_PATH, doc)
    return {"ok": True, "removed": removed}


# ---------------------------------------------------------------- 扫描诊断（回写本地，便于按站点适配）

class ScanDumpReq(BaseModel):
    url: str = ""
    host: str = ""
    company: str = ""
    count: int = 0
    filled: int = 0
    fields: list = []


@app.post("/api/scan-dump")
def api_scan_dump(req: ScanDumpReq):
    """招聘页助手把「扫到了什么字段、填了几个」回传，落盘供离线诊断/按站点适配。"""
    import datetime as _dt

    doc = copilot.load_json(TENANT.SCAN_DUMP_PATH) if TENANT.SCAN_DUMP_PATH.exists() else {}
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        doc = {"items": []}
    doc["items"].append({
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "url": req.url, "host": req.host, "company": req.company,
        "count": req.count, "filled": req.filled, "fields": req.fields[:80],
    })
    doc["items"] = doc["items"][-20:]          # 只保留最近 20 次
    copilot.dump_json(TENANT.SCAN_DUMP_PATH, doc)
    return {"ok": True, "stored": len(doc["items"])}


# ---------------------------------------------------------------- 档案（油猴面板自助编辑）

@app.get("/api/profile")
def api_profile_get():
    """返回当前 profile.job.json 全文（供面板展示/编辑）。"""
    if not TENANT.PROFILE_PATH.exists():
        return {"profile": {}}
    return {"profile": copilot.load_json(TENANT.PROFILE_PATH)}


@app.put("/api/profile")
async def api_profile_put(request: Request):
    """合并更新 profile.json：body 里提供的字段覆盖已有字段，其余保留（优先 merge）。"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "profile 必须是 JSON 对象")
    doc = copilot.load_json(TENANT.PROFILE_PATH) if TENANT.PROFILE_PATH.exists() else {}
    if not isinstance(doc, dict):
        doc = {}
    doc.update(body)
    copilot.dump_json(TENANT.PROFILE_PATH, doc)
    return {"ok": True, "profile": doc}


# ---------------------------------------------------------------- 桌面壳桥接（仪表板 -> Qt 壳）

# 内存命令队列：仪表板 POST 进来，Qt 壳每 400ms 轮询取走
BRIDGE_CMDS = []


@app.post("/api/bridge")
def api_bridge(req: BridgeReq):
    BRIDGE_CMDS.append({"action": req.action, **(req.payload or {})})
    return {"ok": True, "queued": len(BRIDGE_CMDS)}


@app.get("/api/bridge/poll")
def api_bridge_poll():
    out = BRIDGE_CMDS[:]
    BRIDGE_CMDS.clear()
    return {"commands": out}


# ---------------------------------------------------------------- 简历推荐（助手先推荐 -> 用户确认 -> 填）

@app.get("/api/recommend")
def api_recommend(company: str = "", role: str = "", cat: str = ""):
    """用 方向+类别+公司 拼伪 JD，按标签匹配打分，返回推荐简历与候选。"""
    reg = copilot.load_resumes(TENANT.REGISTRY_PATH)
    if not reg.get("resumes"):
        raise HTTPException(400, "还没有注册简历，先跑 register-resume")
    jd = " ".join(x for x in (role, cat, company) if x).strip()
    if not jd:
        raise HTTPException(400, "recommend 需要 role/cat/company 至少其一")
    scored = sorted((copilot.score_resume(r, jd) for r in reg["resumes"]),
                    key=lambda x: -x["score"])
    return {"recommended": scored[0], "candidates": scored, "jd_chars": len(jd)}


# ---------------------------------------------------------------- 起始页（浏览器区第一个标签）

NEWTAB_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f7fa;color:#1f2329;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;max-width:460px;padding:32px}
.logo{font-size:40px}
h1{font-size:22px;margin:10px 0 6px}
p{color:#5f6368;font-size:13.5px;line-height:1.8;margin:6px 0}
b{color:#185FA5}
</style></head><body><div class="card">
<div class="logo">🛠️</div>
<h1>网申助手 · 内嵌浏览器</h1>
<p>从<b>左侧助手栏</b>的「投递队列」点任意公司的<b>「打开」</b>按钮，<br>
会先给你<b>推荐简历</b>，确认后就在这里的<b>新标签页</b>打开招聘官网，<br>
页面右下角会出现 🛠 <b>填充助手</b>。</p>
<p style="color:#9aa3af">支持多标签同时打开 · 顶部地址栏可手动输网址 · 「打开」= 用系统浏览器打开当前页</p>
</div></body></html>"""


@app.get("/newtab")
def newtab():
    return HTMLResponse(NEWTAB_HTML)


# ---------------------------------------------------------------- 根路径 / 静态

@app.get("/")
def index():
    dash = STATIC_DIR / "dashboard.html"
    if dash.exists():
        return FileResponse(str(dash))
    raise HTTPException(404, "dashboard.html 不存在")


# 静态资源（assistant.bookmarklet.js 等），供仪表板同源加载，避免混合内容拦截
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("AC_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("AC_PORT", "8787")))
    args = ap.parse_args()
    import uvicorn
    print(f"[网申助手后端] http://{args.host}:{args.port}"
          + ("  (公网模式，令牌鉴权已启用)" if AC_TOKEN else "  (仅本机)"))
    print(f"  仪表板: http://{args.host}:{args.port}/")
    print(f"  投递库: {TENANT.APP_JSON}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
