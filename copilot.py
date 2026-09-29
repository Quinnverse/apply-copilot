#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 (Application Copilot) —— 半自动、人类在环的校招网申辅助工具。

定位（先说清楚，避免误用）
--------------------------------------------------
本工具【不做】任何需要绕过平台安全机制的事：
  * 不代替你登录（各校招系统都要求本人账号 + 短信/人脸验证）
  * 不破解验证码 / 滑块 / 风控
  * 不批量自动提交
原因有二：一是技术上不可靠（每个 ATS 都不同、风控会变），二是合规风险
（多数平台 ToS 禁止自动化提交，可能导致账号被封）。真正的"提交"动作必须由你本人完成。

本工具做的是把每次网申【提交之前 / 之后】的机械劳动自动化：
  1. 多版本简历管理 + 根据 JD 自动推荐投哪份简历
  2. 结构化档案 -> 一键生成"字段速填表"（省去反复敲姓名/学校/专业）
  3. 依据真实经历生成"岗位匹配要点 + 高频问答草稿"（全部来自档案，不编造）
  4. 网页表单自动填充（只填字段，不提交）：输出 JS 片段粘贴到浏览器控制台
  5. 生成"投递清单 + 提交后记录命令"，并与投递追踪库 apply.py 打通

用法
--------------------------------------------------
  # 0) 注册简历版本（首次）
  python3 copilot.py register-resume --id agent-dev-v1 \
      --path "C:/Users/you/Downloads/简历2.pdf" \
      --tags "Agent开发,AI应用工程,LLM Agent系统,GUI Agent,多模态Agent"

  # 1) 从求职画像生成结构化档案（一次性 / 档案更新时）
  python3 copilot.py init-profile \
      --skill-profile <autumn-skill>/resumes/profile.json \
      --out profile.job.json

  # 2) 根据 JD 推荐简历
  python3 copilot.py match --jd jd.txt --out resumes/match.json

  # 3) 为某个岗位生成申请包（含推荐简历 + 自动填充脚本）
  python3 copilot.py kit --profile profile.job.json \
      --company "淘天" --title "大模型算法工程师" \
      --jd jd.txt --outdir kits

  # 4) 对保存的网页 HTML 生成填充脚本
  python3 copilot.py fill --profile profile.job.json --html page.html --outdir fills

  # 5) 提交完成后记录进投递库（网申后跑）
  python3 copilot.py mark --profile profile.job.json \
      --company "淘天" --title "大模型算法工程师" \
      --resume-version agent-dev-v1 --channel 官网

依赖：Python 3.11+，仅使用标准库（无第三方依赖）。
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import filler

SCHEMA_VERSION = 1


# ---------------------------------------------------------------- 基础工具

def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise SystemExit(f"[错误] 文件不存在：{p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[错误] JSON 解析失败 {p}：{exc}")


def dump_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dash(value, fallback="[待补充]"):
    """空值统一显示为占位符，绝不编造内容。"""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def load_resumes(path="resumes.json"):
    return load_json(path, {"schema_version": 1, "resumes": []})


def save_resumes(registry, path="resumes.json"):
    registry["schema_version"] = 1
    dump_json(path, registry)


def load_job_profile(path):
    return load_json(path)


# ---------------------------------------------------------------- init-profile

def build_self_intro(src):
    """用真实档案拼一段自我介绍骨架；缺失字段留占位符，不脑补。"""
    edu = src.get("education") or []
    exps = src.get("experiences") or []
    comps = src.get("competitions") or []
    name = dash(src.get("name_masked"), "[姓名]")

    edu_line = ""
    if edu:
        top = edu[0]
        major = dash(top.get("major"), "[专业]")
        edu_line = f"{dash(top.get('school'), '[学校]')}（{dash(top.get('rank'), '')}）{major}方向{dash(top.get('degree'), '硕士')}"

    exp_bits = []
    for e in exps[:2]:
        org = dash(e.get("org"), "[公司]")
        biz = dash(e.get("business"), "")
        exp_bits.append(f"{org}（{biz}）" if biz else org)
    exp_line = "；".join(exp_bits) if exp_bits else "[实习经历]"

    comp_line = "、".join(dash(c.get("award"), "") for c in comps[:3]) or "[竞赛奖项]"

    return (
        f"我是{name}，{edu_line}，{dash(src.get('grad_year'), '2027')} 届。"
        f"有两段大厂级算法实习：{exp_line}。"
        f"竞赛方面有{comp_line}。"
        f"求职方向聚焦大模型 / LLM Agent 与多模态算法工程落地。"
    )


def cmd_init(args):
    src = load_json(args.skill_profile)
    skill_dir = Path(args.skill_profile).resolve().parents[1]

    edu = src.get("education") or []
    intent = src.get("intent") or {}
    basic = {
        "name": dash(src.get("name_masked")),
        "phone": dash((src.get("contact") or {}).get("phone")),
        "email": dash((src.get("contact") or {}).get("email")),
        "wechat": "[待补充]",
        "gender": "[待补充]",
        "political_status": "[待补充]",
        "hometown": "[待补充]",
        "id_card": "[敏感信息·不落库，网申时本人现填]",
    }

    job = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_profile": str(Path(args.skill_profile).resolve()),
        "paths": {"autumn_skill_dir": str(skill_dir)},
        "basic": basic,
        "education": edu,
        "highest_degree": dash(edu[0].get("degree")) if edu else "[待补充]",
        "grad_time": dash(edu[0].get("end")) if edu else "[待补充]",
        "grad_year": dash(src.get("grad_year")),
        "competitions": src.get("competitions") or [],
        "skills": src.get("skills") or {},
        "experiences": src.get("experiences") or [],
        "strengths": src.get("strengths") or [],
        "gaps": src.get("gaps") or [],
        "directions": [d.get("name") for d in (src.get("recommended_directions") or [])],
        "cities_preferred": intent.get("cities_preferred") or [],
        "cities_backup": intent.get("cities_backup") or [],
        "match_keywords": src.get("match_keywords") or [],
        "answers": {
            "self_intro": build_self_intro(src),
            "why_company": "",
            "career_plan": "",
            "project_deepdive": "",
        },
    }
    dump_json(args.out, job)
    print(f"[ok] 已生成结构化档案：{args.out}")
    print("     其中 answers.why_company / career_plan 为空白，请按目标公司补充（不编造）。")


# ---------------------------------------------------------------- register-resume

def cmd_register_resume(args):
    reg = load_resumes(args.registry)
    resumes = reg.setdefault("resumes", [])
    path = str(Path(args.path).resolve())
    item = {
        "id": args.id,
        "name": args.name or args.id,
        "path": path,
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "note": args.note or "",
        "registered_at": now_iso(),
    }
    # 去重：同 id 覆盖
    reg["resumes"] = [r for r in resumes if r.get("id") != args.id]
    reg["resumes"].append(item)
    save_resumes(reg, args.registry)
    print(f"[ok] 已注册简历版本：{args.id} -> {path}")
    print(f"     标签：{', '.join(item['tags'])}")


# ---------------------------------------------------------------- match

# 简历标签 / 方向信号 的同义词扩展（中文 ↔ 英文 / 口语说法）。
# 解决"JD 不含标签字面但含同义词（如大模型/LLM/后训练/RL/SFT/GRPO/reward）时直接 0 分"的问题。
RESUME_SYNONYMS = {
    "算法": ["大模型", "llm", "大模型算法", "后训练", "强化学习", "rl", "grpo", "reward", "sft", "预训练"],
    "开发": ["agent开发", "ai应用", "应用工程", "gui agent", "应用落地", "工具调用", "tool calling", "工程化"],
    "研究": ["research", "大模型研究"],
    "系统": ["infra", "基础架构", "分布式"],
}


def _tag_hit(tag, jd):
    """标签是否命中 JD：字面命中，或其同义词命中。"""
    if not tag:
        return False
    if tag in jd:
        return True
    for syn in RESUME_SYNONYMS.get(tag, []):
        if syn in jd:
            return True
    return False


def score_resume(resume, jd_text):
    """根据 JD 给每份简历打分。算法：标签命中（含同义词）+ 方向信号词命中。

    推荐分 < 0.3 视为"无强匹配"，返回里带 weak:true，调用方据此提示用户手选。
    """
    jd = jd_text.lower()
    tags = [t.lower() for t in resume.get("tags", [])]
    hits = []
    for tag in tags:
        if _tag_hit(tag, jd):
            hits.append(tag)
    tag_score = len(hits) / max(len(tags), 1)

    # 额外方向信号（已含同义词）
    algo_signals = ["算法", "大模型", "llm", "后训练", "强化学习", "rl", "grpo", "reward", "sft"]
    dev_signals = ["agent开发", "ai应用", "应用工程", "gui agent", "系统", "工具调用", "开发", "落地"]
    algo_hits = sum(1 for s in algo_signals if s in jd)
    dev_hits = sum(1 for s in dev_signals if s in jd)

    # 根据简历 id / tags 里的关键词判断它偏哪边
    resume_text = " ".join(tags + [resume.get("id", ""), resume.get("name", "")]).lower()
    is_dev = any(k in resume_text for k in ["开发", "应用", "工程", "gui", "落地"])
    is_algo = any(k in resume_text for k in ["算法", "大模型", "后训练", "研究"])

    signal_score = 0.0
    if is_dev and dev_hits:
        signal_score += min(dev_hits * 0.15, 0.45)
    if is_algo and algo_hits:
        signal_score += min(algo_hits * 0.15, 0.45)

    total = min(tag_score * 0.7 + signal_score, 1.0)
    return {
        "id": resume.get("id"),
        "name": resume.get("name"),
        "score": round(total, 2),
        "weak": total < 0.3,  # 推荐分过低：无强匹配，调用方应提示"请手选"
        "tag_hits": hits,
        "tag_count": len(tags),
        "dev_signals": dev_hits,
        "algo_signals": algo_hits,
        "path": resume.get("path"),
    }


def cmd_match(args):
    reg = load_resumes(args.registry)
    jd_text = Path(args.jd).read_text(encoding="utf-8") if args.jd else ""
    if not jd_text:
        raise SystemExit("[错误] match 需要 --jd 提供 JD 文本。")
    if not reg.get("resumes"):
        raise SystemExit("[错误] 还没有注册简历，先跑 register-resume。")

    scored = [score_resume(r, jd_text) for r in reg["resumes"]]
    scored.sort(key=lambda x: -x["score"])

    result = {
        "jd_chars": len(jd_text),
        "recommended": scored[0],
        "candidates": scored,
        "generated_at": now_iso(),
    }
    if args.out:
        dump_json(args.out, result)
        print(f"[ok] 匹配结果已写入：{args.out}")

    print(f"\nJD 长度：{len(jd_text)} 字符\n")
    for s in scored:
        print(f"  {s['score']:.2f}  {s['id']} ({s['name']})")
        print(f"       标签命中：{', '.join(s['tag_hits']) or '无'}")
        print(f"       路径：{s['path']}")
    print(f"\n👉 推荐使用：{scored[0]['id']}（{scored[0]['name']}）")


# ---------------------------------------------------------------- kit

def render_field_sheet(job):
    """字段速填表：网申表单里那些反复要填的字段。"""
    b = job.get("basic") or {}
    edu = job.get("education") or []
    lines = [
        ("姓名", b.get("name")),
        ("手机", b.get("phone")),
        ("邮箱", b.get("email")),
        ("微信", b.get("wechat")),
        ("性别", b.get("gender")),
        ("政治面貌", b.get("political_status")),
        ("籍贯", b.get("hometown")),
    ]
    for e in edu:
        tag = "硕士" if e is edu[0] else "本科"
        lines.append((f"{tag}院校", e.get("school")))
        lines.append((f"{tag}专业", e.get("major")))
        lines.append((f"{tag}起止", f"{e.get('start')} ~ {e.get('end')}"))
    lines.append(("最高学历", job.get("highest_degree")))
    lines.append(("毕业时间", job.get("grad_time")))
    lines.append(("届别", f"{job.get('grad_year')} 届"))
    lines.append(("求职方向", " / ".join(job.get("directions") or []) or "[待补充]"))
    lines.append(("期望城市", " / ".join(job.get("cities_preferred") or []) or "[待补充]"))
    lines.append(("备选城市", " / ".join(job.get("cities_backup") or [])))

    rows = ["| 字段 | 值 |", "|---|---|"]
    for k, v in lines:
        rows.append(f"| {k} | {dash(v)} |")
    return "\n".join(rows)


def render_match_points(job, jd_text):
    """匹配要点：优先用 JD 命中关键词，再回落到 strongest 三条。"""
    out = []
    if jd_text:
        jd = jd_text.lower()
        hits = [k for k in (job.get("match_keywords") or []) if k.lower() in jd]
        if hits:
            out.append(f"**JD 命中关键词（{len(hits)} 个）**：" + "、".join(hits))
        else:
            out.append("**JD 命中关键词**：未命中档案关键词，建议人工核对 JD 与经历的对口度。")
    out.append("")
    for s in (job.get("strengths") or []):
        out.append(f"- **{dash(s.get('claim'))}**")
        out.append(f"  - 证据：{dash(s.get('evidence'))}")
    gaps = job.get("gaps") or []
    if gaps:
        out.append("")
        out.append("**可能被追问的短板（提前准备说法）**：")
        for g in gaps:
            out.append(f"- {dash(g.get('claim'))} —— 影响：{dash(g.get('impact'))}")
    return "\n".join(out)


def render_qa(job, company):
    a = job.get("answers") or {}
    intro = dash(a.get("self_intro"))
    why = dash(a.get("why_company"), f"（请补充：为什么选择 {company}，一句话业务 + 一句话个人匹配）")
    plan = dash(a.get("career_plan"), "（请补充：1 年 / 3 年的成长目标，结合目标岗位业务）")
    deep = dash(a.get("project_deepdive"), "（请补充：一个可深挖的项目，STAR + 量化指标）")
    return (
        f"### 自我介绍（骨架，按岗位微调）\n\n{intro}\n\n"
        f"### 为什么选择 {company}\n\n{why}\n\n"
        f"### 职业规划\n\n{plan}\n\n"
        f"### 项目深挖（面试官最爱问）\n\n{deep}\n"
    )


def render_resume_recommendation(reg, jd_text, company, title):
    """生成简历推荐说明。"""
    if not reg.get("resumes"):
        return "> 尚未注册简历版本，请用 `register-resume` 先添加。\n"
    scored = [score_resume(r, jd_text) for r in reg["resumes"]]
    scored.sort(key=lambda x: -x["score"])
    top = scored[0]
    lines = [
        f"- **推荐简历**：`{top['id']}`（{top['name']}）—— 匹配分 {top['score']:.2f}",
        f"- **简历路径**：{top['path']}",
        f"- **命中标签**：{', '.join(top['tag_hits']) or '无'}",
        f"- **mark 时请加**：`--resume-version {top['id']}`",
    ]
    if len(scored) > 1:
        lines.append("- **其他候选**：" + " / ".join(f"{s['id']}({s['score']:.2f})" for s in scored[1:]))
    return "\n".join(lines) + "\n"


def render_form_fill_payload(job, outdir):
    """生成一个通用填充 payload 文件（不针对具体网页，用常见字段名）。"""
    # 用 filler 里的规则构造一个虚拟 fields 列表，再生成 copy-paste 表和 bookmarklet
    fields = [
        {"tag": "input", "type": "text", "id": "", "name": "姓名", "placeholder": "", "label": "姓名"},
        {"tag": "input", "type": "tel", "id": "", "name": "phone", "placeholder": "", "label": "手机"},
        {"tag": "input", "type": "email", "id": "", "name": "email", "placeholder": "", "label": "邮箱"},
        {"tag": "input", "type": "text", "id": "", "name": "学校", "placeholder": "", "label": "学校"},
        {"tag": "input", "type": "text", "id": "", "name": "专业", "placeholder": "", "label": "专业"},
        {"tag": "input", "type": "text", "id": "", "name": "毕业时间", "placeholder": "", "label": "毕业时间"},
    ]
    payload = filler.build_fill_payload(fields, job)
    return payload


def cmd_kit(args):
    job = load_job_profile(args.profile)
    reg = load_resumes(args.registry)
    jd_text = ""
    if args.jd:
        jd_text = Path(args.jd).read_text(encoding="utf-8")

    skill_dir = (job.get("paths") or {}).get("autumn_skill_dir", "<autumn-skill>")
    mark_cmd = (
        f"python3 {skill_dir}/scripts/apply.py mark "
        f"--applications {skill_dir}/state/applications.json "
        f"--state {skill_dir}/state/seen_postings.json "
        f"--company \"{args.company}\" --title \"{args.title}\" --channel 官网"
    )
    if reg.get("resumes") and jd_text:
        top = max([score_resume(r, jd_text) for r in reg["resumes"]], key=lambda x: x["score"])
        mark_cmd += f" --resume-version {top['id']}"

    # 表单填充：生成 copy-paste 表 + 通用 bookmarklet
    payload = render_form_fill_payload(job, args.outdir)
    copy_table = filler.generate_copy_paste_table(payload)
    bookmarklet = filler.generate_bookmarklet(payload)
    safe_company = f"{args.company}-{args.title}".replace("/", "_").replace(" ", "")

    md = f"""# 申请包 · {args.company} · {args.title}

> 生成时间：{now_iso()}
> ⚠️ 本文件含手机号 / 邮箱等个人信息，仅供本地使用，**请勿外发**。
> ⚠️ 本工具不代登录、不破解验证码、不自动提交；最后的"提交"一步必须你本人完成。

---

## 1. 推荐简历

{render_resume_recommendation(reg, jd_text, args.company, args.title)}

---

## 2. 字段速填表（照抄进网申表单）

{render_field_sheet(job)}

---

## 3. 岗位匹配要点（全部来自真实档案，勿编造）

{render_match_points(job, jd_text)}

---

## 4. 高频问答草稿（先填骨架，再按岗位微调）

{render_qa(job, args.company)}

---

## 5. 自动填充方案（只填字段，不提交）

### 5.1 手动标签式填充

如果自动脚本跑不通，直接点网页输入框 → 复制下表对应值粘贴：

{copy_table}

### 5.2 一键填充脚本（粘贴到浏览器控制台）

把下面整段代码复制，打开目标网页后按 F12 → Console → 粘贴 → 回车。
字段会自动填入，**未命中的字段会被红框标出**，请人工复核后再提交。

```javascript
{bookmarklet}
```

---

## 6. 投递 Checklist（人工完成打勾）

- [ ] 打开 {args.company} 官方校招页，用**本人账号**登录（短信/人脸验证）
- [ ] 找到「{args.title}」岗位，确认届别与工作地符合预期
- [ ] 上传推荐简历 PDF（见第 1 节）
- [ ] 把第 2 节字段速填表逐项粘进表单
- [ ] 按第 4 节填写开放性问题（务必改成贴合该公司的内容）
- [ ] 完成测评 / 笔试（如有）
- [ ] 提交前**逐项复核**，确认无误后本人点击提交
- [ ] 截图留存"投递成功"页面

---

## 7. 提交后把这条记录进投递库

```bash
{mark_cmd}
```
"""
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{safe_company}.md"
    out_path.write_text(md, encoding="utf-8")

    # 同时输出一个纯 bookmarklet 文件，方便收藏到浏览器书签
    bm_path = outdir / f"{safe_company}.bookmarklet.js"
    bm_path.write_text(bookmarklet, encoding="utf-8")

    print(f"[ok] 申请包已生成：{out_path}")
    print(f"[ok] 填充脚本已生成：{bm_path}")
    print(f"[tip] 若 JD 匹配到的简历不是你想要的，编辑 resumes.json 调整标签，或手动指定 --resume-version。")


# ---------------------------------------------------------------- fill

def cmd_fill(args):
    """对保存的网页 HTML 生成字段映射 + 填充脚本。"""
    job = load_job_profile(args.profile)
    html = Path(args.html).read_text(encoding="utf-8")
    fields = filler.parse_html_fields(html)
    if not fields:
        raise SystemExit("[错误] 没有从 HTML 里识别到可填字段。请确认传入的是包含表单的目标网页源码。")

    payload = filler.build_fill_payload(fields, job)
    copy_table = filler.generate_copy_paste_table(payload)
    bookmarklet = filler.generate_bookmarklet(payload)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    base = Path(args.html).stem
    md_path = outdir / f"{base}.fill.md"
    js_path = outdir / f"{base}.fill.js"
    json_path = outdir / f"{base}.fill.json"

    md = f"""# 网页表单填充方案 · {args.html}

> 生成时间：{now_iso()}
> ⚠️ 本文件含 PII，请勿外发。真正的提交必须你本人复核后点击。

## 识别到的字段

共识别 {len(fields)} 个字段，其中高/中置信度已自动匹配档案值，低置信度标红需人工补。

## 手动标签表

{copy_table}

## 一键填充脚本（粘贴到浏览器控制台）

```javascript
{bookmarklet}
```
"""
    md_path.write_text(md, encoding="utf-8")
    js_path.write_text(bookmarklet, encoding="utf-8")
    dump_json(json_path, {"fields": len(fields), "payload": payload, "generated_at": now_iso()})

    print(f"[ok] 字段映射 Markdown：{md_path}")
    print(f"[ok] 填充 JS 脚本：{js_path}")
    print(f"[ok] 结构化 JSON：{json_path}")
    print(f"     识别字段 {len(fields)} 个，高置信度 {sum(1 for p in payload if p['confidence']>=0.8)} 个，"
          f"中置信度 {sum(1 for p in payload if 0.5<=p['confidence']<0.8)} 个，"
          f"未命中 {sum(1 for p in payload if p['confidence']<0.5)} 个。")


# ---------------------------------------------------------------- mark

def cmd_mark(args):
    job = load_job_profile(args.profile)
    skill_dir = (job.get("paths") or {}).get("autumn_skill_dir")
    if not skill_dir or not Path(skill_dir).exists():
        raise SystemExit("[错误] 档案里没有有效的 autumn_skill_dir，请重跑 init-profile 或在档案中补全 paths。")

    apply_py = Path(skill_dir) / "scripts" / "apply.py"
    cmd = [
        sys.executable, str(apply_py), "mark",
        "--applications", str(Path(skill_dir) / "state" / "applications.json"),
        "--state", str(Path(skill_dir) / "state" / "seen_postings.json"),
        "--company", args.company,
        "--title", args.title,
        "--channel", args.channel,
    ]
    if args.resume_version:
        cmd.extend(["--resume-version", args.resume_version])
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise SystemExit(f"[错误] 找不到 apply.py：{apply_py}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"[错误] apply.py mark 失败（退出码 {exc.returncode}）。"
                         f"若提示已记录过，属正常，加 --force 可覆盖。")


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="网申助手（半自动，人类在环）")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-profile", help="从求职画像生成结构化档案")
    p.add_argument("--skill-profile", required=True, help="autumn 技能里的 resumes/profile.json")
    p.add_argument("--out", default="profile.job.json")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("register-resume", help="注册一个简历版本")
    p.add_argument("--registry", default="resumes.json")
    p.add_argument("--id", required=True, help="版本 ID，如 algo-v1 / agent-dev-v1")
    p.add_argument("--path", required=True, help="简历 PDF 路径")
    p.add_argument("--name", help="显示名称")
    p.add_argument("--tags", required=True, help="逗号分隔的标签，用于 JD 匹配")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_register_resume)

    p = sub.add_parser("match", help="根据 JD 推荐简历版本")
    p.add_argument("--registry", default="resumes.json")
    p.add_argument("--jd", required=True, help="JD 文本文件")
    p.add_argument("--out", help="可选：JSON 结果保存路径")
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("kit", help="为某个岗位生成申请包")
    p.add_argument("--profile", required=True)
    p.add_argument("--registry", default="resumes.json")
    p.add_argument("--company", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--jd", help="可选：JD 纯文本文件，用于关键词命中 + 简历推荐")
    p.add_argument("--outdir", default="kits")
    p.set_defaults(func=cmd_kit)

    p = sub.add_parser("fill", help="对保存的网页 HTML 生成填充脚本")
    p.add_argument("--profile", required=True)
    p.add_argument("--html", required=True, help="保存的网页 HTML 文件路径")
    p.add_argument("--outdir", default="fills")
    p.set_defaults(func=cmd_fill)

    p = sub.add_parser("mark", help="提交完成后记录进投递库")
    p.add_argument("--profile", required=True)
    p.add_argument("--company", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--resume-version", help="简历版本 ID（建议带上，用于过筛率统计）")
    p.add_argument("--channel", default="官网")
    p.set_defaults(func=cmd_mark)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
