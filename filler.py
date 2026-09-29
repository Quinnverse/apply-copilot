#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页表单解析与自动填充逻辑（纯标准库）。

只做"识别字段 -> 把档案值填进去"这件事：
  * 不提交、不绕验证码、不登录。
  * 输出一份"字段映射表" + 一段可粘贴到浏览器控制台的 JS。
  * 对没把握命中的字段，用红框标出来让人工补。
"""

import re
import urllib.parse
from html.parser import HTMLParser


class _FieldScanner(HTMLParser):
    """扫描 HTML 里的可填字段及其附近的 label 文本。"""

    def __init__(self):
        super().__init__()
        self.fields = []
        self._current_label = None
        self._label_for = None

    def handle_starttag(self, tag, attrs):
        attr = {k: v for k, v in attrs}
        if tag == "label":
            self._current_label = ""
            self._label_for = attr.get("for")
            return
        if tag in ("input", "select", "textarea"):
            fid = attr.get("id", "")
            name = attr.get("name", "")
            placeholder = attr.get("placeholder", "")
            ftype = attr.get("type", "text") if tag == "input" else tag
            # select / textarea 没有 type
            if tag == "select":
                ftype = "select"
            if tag == "textarea":
                ftype = "textarea"
            self.fields.append({
                "tag": tag,
                "type": ftype,
                "id": fid,
                "name": name,
                "placeholder": placeholder,
                "label": "",
                "label_for": self._label_for,
                "options": [],
            })
        if tag == "select" and self.fields:
            self.fields[-1]["select_open"] = True
        if tag == "option" and self.fields and self.fields[-1].get("select_open"):
            val = attr.get("value", "")
            # option 的显示文本在 handle_data 里累积
            self.fields[-1]["options"].append({"value": val, "text": ""})

    def handle_data(self, data):
        if self._current_label is not None:
            self._current_label += data.strip()

    def handle_endtag(self, tag):
        if tag == "label" and self._current_label is not None:
            text = self._current_label.strip()
            # 把 label 文本绑定到对应的字段
            if self._label_for:
                for f in self.fields:
                    if f["id"] == self._label_for:
                        f["label"] = text
                        break
            else:
                # 没有 for 时，简单挂到最后一个字段（label 紧跟 input）
                if self.fields and not self.fields[-1].get("label"):
                    self.fields[-1]["label"] = text
            self._current_label = None
            self._label_for = None
        if tag == "select":
            if self.fields and self.fields[-1].get("select_open"):
                self.fields[-1].pop("select_open", None)


def parse_html_fields(html_text):
    """返回从 HTML 扫描到的可填字段列表（轻量、容错）。"""
    scanner = _FieldScanner()
    try:
        scanner.feed(html_text)
    except Exception:
        pass
    # 清理临时键
    for f in scanner.fields:
        f.pop("select_open", None)
        f.pop("label_for", None)
    return scanner.fields


# 字段关键词 -> profile 取值路径
# 每一项：匹配关键词列表 + 取值函数(profile) + 字段类型白名单（空表示不限制）
def _basic(key):
    return lambda p: (p.get("basic") or {}).get(key, "")


def _edu_top(key):
    def fn(p):
        edu = p.get("education") or []
        return edu[0].get(key, "") if edu else ""
    return fn


FIELD_RULES = [
    # 姓名
    (["姓名", "name", "真实姓名", "中文姓名"], _basic("name"), []),
    # 手机
    (["手机", "移动电话", "电话", "手机号", "mobile", "phone", "联系电话"], _basic("phone"), ["tel", "text"]),
    # 邮箱
    (["邮箱", "电子邮箱", "email", "e-mail", "邮件"], _basic("email"), ["email", "text"]),
    # 微信
    (["微信", "微信号", "wechat"], _basic("wechat"), ["text"]),
    # 性别
    (["性别", "gender", "sex"], _basic("gender"), ["select", "radio", "text"]),
    # 政治面貌
    (["政治面貌", "political"], _basic("political_status"), ["select", "text"]),
    # 籍贯
    (["籍贯", "出生地", "户籍", " hometown"], _basic("hometown"), ["text"]),
    # 学校
    (["学校", "院校", "毕业院校", "大学", "university", "school", "本科院校", "硕士院校"],
     _edu_top("school"), ["text"]),
    # 专业
    (["专业", "所学专业", "major"], _edu_top("major"), ["text"]),
    # 学历
    (["学历", "学位", "最高学历", "degree"], lambda p: p.get("highest_degree", ""), ["select", "text"]),
    # 毕业时间
    (["毕业时间", "毕业年份", "graduation", "预计毕业", "毕业年月"],
     lambda p: p.get("grad_time", ""), ["text", "month", "date"]),
    # 届别
    (["届别", "毕业届别"], lambda p: p.get("grad_year", ""), ["text"]),
]


# ---- 宽松同义词兜底（与 assistant.js 的 SYN 对齐，唯一真源）----
# 每条：(正则模式串, 中文规范名)。JS 端用 new RegExp(re, 'i') 重建；Python 端用 re.search。
FIELD_SYN = [
    (r"姓名|名字|中文名|真实姓名|fullname|full_name|yourname|givenname|familyname", "姓名"),
    (r"手机|电话|联系方式|联系号码|mobile|phone|\btel\b|contact", "手机"),
    (r"邮箱|邮件|email|e-mail|\bmail\b", "邮箱"),
    (r"微信|wechat|weixin", "微信"),
    (r"性别|gender|\bsex\b", "性别"),
    (r"政治面貌|政治|party|political", "政治面貌"),
    (r"籍贯|户籍|出生地|户口|hometown|native", "籍贯"),
    (r"学校|院校|大学|就读|graduated|university|school|college", "学校"),
    (r"专业|major|discipline", "专业"),
    (r"学历|学位|degree|education", "学历"),
    (r"毕业时间|毕业年份|毕业年月|预计毕业|graduation|graduate", "毕业时间"),
    (r"届别|毕业届|\b届\b", "届别"),
    (r"入学|入学年|enroll", "入学时间"),
    (r"意向城市|期望城市|期望工作地|工作城市|期望地点|preferredcity|city", "意向城市"),
    (r"意向岗位|期望岗位|求职意向|应聘岗位|目标岗位|position|intention", "意向方向"),
]

# 中文规范名 -> 档案取值函数（供 build_fill_payload 兜底使用）
SYN_NAME_GETTER = {
    "姓名": _basic("name"),
    "手机": _basic("phone"),
    "邮箱": _basic("email"),
    "微信": _basic("wechat"),
    "性别": _basic("gender"),
    "政治面貌": _basic("political_status"),
    "籍贯": _basic("hometown"),
    "学校": _edu_top("school"),
    "专业": _edu_top("major"),
    "学历": lambda p: p.get("highest_degree", ""),
    "毕业时间": lambda p: p.get("grad_time"),
    "届别": lambda p: p.get("grad_year"),
    "入学时间": _edu_top("start"),
    "意向城市": lambda p: "、".join((p.get("cities_preferred") or [])[:6]),
    "意向方向": lambda p: "、".join((p.get("directions") or [])[:4]),
}


def _score_field(field, keyword):
    """单个字段与关键词的匹配得分（0-1）。"""
    hay = f"{field.get('label','')} {field.get('name','')} {field.get('id','')} {field.get('placeholder','')}".lower()
    if keyword in hay:
        return 1.0
    # 模糊：关键词拆分后分别出现
    parts = re.split(r"[\s\-_]", keyword.lower())
    if parts and all(p in hay for p in parts if len(p) > 1):
        return 0.7
    return 0.0


def is_multi_value(value):
    """是否多值档案值（如"浙江、上海、江苏" / "北京,上海"）：含常见分隔符即视为多值。

    与 assistant.js 的 isMultiValue 保持一致。多值在 select 上只接受精确/归一后
    相等，绝不做子串包含匹配，否则选项"上海"会被整个多值串反向命中而错填。
    """
    return bool(re.search(r"[、,，/;；|]", str(value or "")))


def build_fill_payload(fields, profile, threshold=0.5):
    """为每个可填字段匹配档案值，返回映射列表。

    匹配顺序：① FIELD_RULES（带类型白名单） → ② 宽松同义词兜底（FIELD_SYN，
    忽略类型白名单，解决关键词没对齐的情况）。两条实现均与 assistant.js 对齐。
    """
    payload = []
    for f in fields:
        label_text = str(f.get("label") or "").strip()
        # Long prompts often contain contact-field words in a different sense
        # (e.g. "Email Management for Executives..."). Leave them to the user.
        if len(re.findall(r"[A-Za-z]+", label_text)) > 3 or "?" in label_text or "？" in label_text:
            payload.append({"label": label_text or "未知字段", "selector": "", "type": f.get("type"),
                            "value": "", "confidence": 0.0})
            continue
        best_rule = None
        best_score = 0.0
        for keywords, getter, types in FIELD_RULES:
            if types and f.get("type") not in types:
                continue
            score = max(_score_field(f, kw) for kw in keywords)
            if score > best_score:
                best_score = score
                best_rule = (keywords, getter)
        value = ""
        if best_rule and best_score >= threshold:
            value = best_rule[1](profile) or ""
        else:
            # 兜底：宽松同义词（忽略类型白名单 —— 很多 SPA 的 type 是 text）
            hay = " ".join(str(f.get(k, "") or "") for k in
                          ("label", "name", "id", "placeholder")).lower()
            for pat, name in FIELD_SYN:
                if re.search(pat, hay):
                    g = SYN_NAME_GETTER.get(name)
                    val = g(profile) if g else ""
                    if val:
                        value = val
                        best_score = 0.9
                        break
        # select + 多值档案值：没有选项能与整串精确相等，直接判未命中（标红），
        # 不做子串匹配，与 assistant.js setVal 的 isMultiValue 行为一致。
        if value and str(f.get("type", "")).lower() == "select" and is_multi_value(value):
            value = ""
            best_score = 0.0
        # ATS forms often split names. Reusing the full name in both fields is wrong.
        name_hay = " ".join(str(f.get(k, "") or "") for k in
                            ("label", "name", "id", "placeholder")).lower()
        if re.search(r"\b(first[\s_-]*name|given[\s_-]*name)\b", name_hay) or \
                re.search(r"\b(last[\s_-]*name|family[\s_-]*name|surname)\b", name_hay):
            parts = str((profile.get("basic") or {}).get("name") or "").strip().split()
            if len(parts) >= 2:
                value = parts[0] if re.search(r"\b(first[\s_-]*name|given[\s_-]*name)\b", name_hay) else " ".join(parts[1:])
                best_score = 1.0
            else:
                value = ""
                best_score = 0.0
        # 构造 CSS 选择器（优先 id，其次 name）
        sel = ""
        if f.get("id"):
            sel = f"#{f['id']}"
        elif f.get("name"):
            sel = f'[name="{f["name"]}"]'
        payload.append({
            "label": f.get("label") or f.get("placeholder") or f.get("name") or f.get("id") or "未知字段",
            "selector": sel,
            "type": f.get("type"),
            "value": str(value),
            "confidence": best_score,
        })
    return payload


def generate_bookmarklet(payload):
    """生成一段可粘贴到浏览器控制台执行的 JS。只填字段、高亮未命中、绝不提交。"""
    lines = [
        "(function(){",
        "  var filled=0, missed=0;",
        "  function set(el, v){",
        "    if(!el || !v) return false;",
        "    if(el.tagName==='SELECT'){ el.value=v; }",
        "    else if(el.tagName==='TEXTAREA'){ el.value=v; }",
        "    else { el.value=v; }",
        "    el.dispatchEvent(new Event('input',{bubbles:true}));",
        "    el.dispatchEvent(new Event('change',{bubbles:true}));",
        "    el.style.backgroundColor='#e8f3ff';",
        "    return true;",
        "  }",
    ]
    for p in payload:
        sel = p["selector"]
        if not sel:
            continue
        if p["confidence"] >= 0.5 and p["value"]:
            # 转义引号，避免 JS 字符串断裂
            val = p["value"].replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
            lines.append(f"  if(set(document.querySelector('{sel}'), '{val}')) filled++; else missed++;")
        else:
            # 未命中字段标红
            lines.append(f"  {{var el=document.querySelector('{sel}'); if(el){{ el.style.border='2px solid #e74c3c'; missed++; }}}}")
    lines.append("  alert('已填充 '+filled+' 个字段，未命中 '+missed+' 个（红框）。请人工复核后提交。');")
    lines.append("})();")
    return "\n".join(lines)


def generate_copy_paste_table(payload):
    """生成 Markdown 表格，供手动复制粘贴（标签式填充）。"""
    rows = ["| 字段 | 值 | 置信度 |", "|---|---|---|"]
    for p in payload:
        conf = "高" if p["confidence"] >= 0.8 else ("中" if p["confidence"] >= 0.5 else "低/未命中")
        rows.append(f"| {p['label']} | `{p['value'] or '[待补充]'}]` | {conf} |")
    return "\n".join(rows)
