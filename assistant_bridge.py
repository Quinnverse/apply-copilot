#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · 注入脚本桥接（从 app_desktop / app_desktop_qt 抽出的独立模块）

只负责：
  * 读取 assistant.js 模板、拼接可注入的助手 JS（build_assistant_js）
  * 由 filler.FIELD_RULES + 全局档案 PROFILE 预生成「字段规则表」(RULES_JSON)
  * 由 profile_values 生成「点选填充 / 档案速查」值表 (VALUES_JSON)
  * 由 filler.FIELD_SYN 生成宽松同义词表 (SYN_JSON)

刻意不 import webview / PyQt，保证 Qt 版桌面壳只依赖本模块、不再强拉 pywebview。
"""

import io
import os
import json
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import server  # 复用 server.PROFILE / server.filler
import filler  # 字段规则 + 同义词真源


def _safe(v):
    """档案里的占位值（[待补充] / 敏感信息）不当作可填值。"""
    s = str(v or "").strip()
    if not s or s.startswith("[待补充") or s.startswith("[敏感"):
        return ""
    return s


def profile_values(p):
    """给「点选填充 / 档案速查」用的扁平值表：[{k:标签, v:值}]。"""
    b = p.get("basic") or {}
    edu = (p.get("education") or [{}])[0]
    pairs = [
        ("姓名", b.get("name")),
        ("手机", b.get("phone")),
        ("邮箱", b.get("email")),
        ("微信", b.get("wechat")),
        ("性别", b.get("gender")),
        ("政治面貌", b.get("political_status")),
        ("籍贯", b.get("hometown")),
        ("学校", edu.get("school")),
        ("专业", edu.get("major")),
        ("学历", p.get("highest_degree")),
        ("入学时间", edu.get("start")),
        ("毕业时间", edu.get("grad_time") or edu.get("end")),
        ("届别", p.get("grad_year")),
        ("意向城市", "、".join((p.get("cities_preferred") or [])[:6])),
        ("意向方向", "、".join((p.get("directions") or [])[:4])),
        ("个人优势", "；".join(str(x) for x in (p.get("strengths") or [])[:2])),
    ]
    return [{"k": k, "v": v} for k, v in ((k, _safe(v)) for k, v in pairs) if v]


# 由 filler.FIELD_RULES + 全局档案 PROFILE 预生成「字段规则表」(keywords + 取值 + 类型白名单)。
RULES_JSON = json.dumps(
    [
        {"k": kw, "v": str(getter(server.PROFILE) or ""), "t": types}
        for kw, getter, types in server.filler.FIELD_RULES
    ],
    ensure_ascii=False,
)

# 「点选填充 / 档案速查」的值表（已过滤 [待补充] 占位值）
VALUES_JSON = json.dumps(profile_values(server.PROFILE), ensure_ascii=False)

# 宽松同义词（与 filler.FIELD_SYN 对齐的唯一真源），JS 端用 new RegExp(re, 'i') 重建
SYN_JSON = json.dumps(
    [{"re": pat, "name": name} for pat, name in filler.FIELD_SYN],
    ensure_ascii=False,
)


# ---------------------------------------------------------------- 注入到招聘页的填空助手 JS

ASSISTANT_JS_PATH = os.path.join(HERE, "assistant.js")


def load_assistant_template():
    """注入脚本放在 assistant.js（便于单独编辑/校验），运行时读取。"""
    try:
        with io.open(ASSISTANT_JS_PATH, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


ASSISTANT_TEMPLATE = load_assistant_template()


def build_assistant_js(company="", resume_id="", resume_name="", learned=None,
                       backend="http://127.0.0.1:8787"):
    """拼出可注入招聘页的填空助手 JS。

    RULES 来自 FIELD_RULES+PROFILE；VALUES 是「点选填充/档案速查」的值表；
    SYN 是宽松同义词（来自 filler.FIELD_SYN）；learned 是历史记住的字段
    （{key: value}），优先级高于规则推断；backend 用于页面回写本机后端。
    """
    tpl = load_assistant_template() or ASSISTANT_TEMPLATE
    js = tpl
    js = js.replace("__RULES__", RULES_JSON)
    js = js.replace("__VALUES__", VALUES_JSON)
    js = js.replace("__SYN__", SYN_JSON)
    js = js.replace("__LEARNED__", json.dumps(learned or {}, ensure_ascii=False))
    js = js.replace("__BACKEND__", backend)
    js = js.replace("__COMPANY__", json.dumps(company, ensure_ascii=False))
    js = js.replace("__RESUME_ID__", json.dumps(resume_id, ensure_ascii=False))
    js = js.replace("__RESUME_NAME__", json.dumps(resume_name, ensure_ascii=False))
    return js
