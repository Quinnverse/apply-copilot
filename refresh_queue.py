#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · queue_seed.json 确定性刷新（独立可跑，也可 import）

四步（全部确定性规则，无 AI 参与）：
  1. 时间衰减：按 deadline 文本解析出日期，重算每条的 urg
     （≤7天 urgent / ≤21天 near / 其余 open / 已过期 expired —— 保留不删）。
  2. 剔除已投：读 applications.json，company_matches 命中（含显式别名，
     如"宽德"↔"宽德投资"）即从清单移除。
  3. 合并 extra_items：同公司同 role 去重（merged）；同公司新 role 追加为
     多岗位（不覆盖）；新公司直接追加（added）。
  4. 排序写回：urg(expired 最后) → cat 权重 → deadline 升序。

安全约定：
  * 默认 dry-run —— 只打印各步计数，绝不写文件；加 --write 才落盘。
  * 路径全部显式传入，测试时可指向临时目录，不碰真实数据。

CLI：
  python refresh_queue.py [--in queue_seed.json] [--out queue_seed.json] [--write]
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_util import company_matches, norm_company  # noqa: E402

YEAR_DEFAULT = 2026          # 校招季统一年份（截止文本如 "9/26" 默认 2026 年）
SEED_FIELDS = ("id", "company", "cat", "role", "sal", "loc", "deadline", "urg",
               "ltype", "url")

# urg 排序权重（expired 沉底但不删除）
URG_RANK = {"urgent": 0, "near": 1, "open": 2, "expired": 3}

# 类别权重：必补大厂最优先，未知类别排最后
CAT_WEIGHT = {
    "必补大厂": 0,
    "具身智驾": 1,
    "量化私募": 2,
    "智驾中厂": 3,
    "中小厂-具身": 4,
    "中小厂-大模型Infra": 5,
    "AI芯片": 6,
    "互联网中厂": 7,
}
CAT_WEIGHT_DEFAULT = 9


# ---------------------------------------------------------------- 步骤 0：解析

def parse_deadline(s):
    """把截止文本解析成 date；解析不出返回 None。

    支持格式：
      "网申9/26截止!" / "正式批统一10/30" / "10/30" / "9/26"   → 2026 年
      "2026-10-30" / "2026.10.30" / "2026/10/30" / "2026年10月30日" → 全日期
      "10月30日"                                              → 2026 年
    """
    if not s:
        return None
    s = str(s)
    # 全日期：2026-10-30 / 2026.10.30 / 2026/10/30 / 2026年10月30日
    m = re.search(r"(\d{4})[-/.年]\s*(\d{1,2})[-/.月]\s*(\d{1,2})", s)
    if m:
        mo, da = int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            try:
                return date(int(m.group(1)), mo, da)
            except ValueError:
                return None
    # 月/日：9/26、10-30、10月30日（取第一处命中）
    m = re.search(r"(\d{1,2})[-/.月]\s*(\d{1,2})\s*[日号]?", s)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            try:
                return date(YEAR_DEFAULT, mo, da)
            except ValueError:
                return None
    return None


def urgency_of(dl, today=None):
    """deadline 日期 → urg 等级。dl=None 视为长期开放（open）。"""
    today = today or date.today()
    if dl is None:
        return "open"
    days = (dl - today).days
    if days < 0:
        return "expired"
    if days <= 7:
        return "urgent"
    if days <= 21:
        return "near"
    return "open"


def _sort_key(it):
    """排序键：expired 沉底 → urg → cat 权重 → deadline 升序（无日期靠后）。"""
    urg = it.get("urg") or "open"
    dl = it.get("_dl")
    cat_w = CAT_WEIGHT.get(it.get("cat") or "", CAT_WEIGHT_DEFAULT)
    dl_key = dl.toordinal() if dl else 99999999
    return (URG_RANK.get(urg, 2), cat_w, dl_key)


# ---------------------------------------------------------------- 已投读取

def load_recorded(apps_path):
    """读 applications.json，返回已记录公司名集合。结构：
    {"applications": {id: {company, title, ...}}, "updated_at": ...}"""
    p = Path(apps_path) if apps_path else None
    if not p or not p.exists():
        return set()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return set()
    apps = doc.get("applications", {}) if isinstance(doc, dict) else {}
    out = set()
    vals = apps.values() if isinstance(apps, dict) else (apps if isinstance(apps, list) else [])
    for a in vals:
        if isinstance(a, dict):
            c = (a.get("company") or "").strip()
            if c:
                out.add(c)
    return out


# ---------------------------------------------------------------- 主流程

def refresh(seed_path, apps_path, out_path=None, extra_items=None, write=False,
            today=None):
    """四步刷新。write=False 时只统计不写盘（dry-run）。

    返回 {"added", "merged", "removed_recorded", "total", "decayed"}：
      added            新公司并入条数
      merged           同公司同 role 去重条数
      removed_recorded 命中已投记录被剔除条数
      decayed          urg 等级相对原值发生变化条数（时间衰减）
      total            刷新后清单总数
    """
    today = today or date.today()
    extra_items = extra_items or []
    seed_path = Path(seed_path)
    out_path = Path(out_path) if out_path else seed_path

    doc = {}
    if seed_path.exists():
        try:
            doc = json.loads(seed_path.read_text(encoding="utf-8"))
        except Exception:
            doc = {}
    items = [dict(x) for x in (doc.get("items") or []) if isinstance(x, dict)]

    # ---- 步骤 1：时间衰减重算 urg ----
    decayed = 0
    for it in items:
        old = it.get("urg")
        dl = parse_deadline(it.get("deadline"))
        it["_dl"] = dl
        new = urgency_of(dl, today)
        it["urg"] = new
        if old and old != new:
            decayed += 1

    # ---- 步骤 2：剔除已投（含别名匹配）----
    recorded = load_recorded(apps_path)
    kept = []
    removed_recorded = 0
    for it in items:
        c = it.get("company") or ""
        if c and any(company_matches(c, rc) for rc in recorded):
            removed_recorded += 1
            continue
        kept.append(it)
    items = kept

    # ---- 步骤 3：合并 extra_items（同公司同 role 去重 / 新 role 追加）----
    def norm_role(r):
        return re.sub(r"\s+", "", str(r or "")).lower()

    existing_ids = {it.get("id") for it in items}
    added = 0
    merged = 0
    for raw in extra_items:
        if not isinstance(raw, dict) or not (raw.get("company") or "").strip():
            continue
        it = {k: raw.get(k, "") for k in SEED_FIELDS if k != "urg"}
        it["urg"] = raw.get("urg") or ""
        dl = parse_deadline(it.get("deadline"))
        it["_dl"] = dl
        it["urg"] = urgency_of(dl, today) if dl or not it["urg"] else it["urg"]
        # 已投（含别名）的新条目直接剔除，不入清单
        if it["company"] and any(company_matches(it["company"], rc) for rc in recorded):
            removed_recorded += 1
            continue
        # 同公司同 role → 去重；同公司新 role → 追加为多岗位（不覆盖）
        dup = None
        for ex in items:
            if company_matches(ex.get("company"), it["company"]) \
                    and norm_role(ex.get("role")) == norm_role(it["role"]):
                dup = ex
                break
        if dup is not None:
            merged += 1
            continue
        # 保证 id 唯一
        base_id = it.get("id") or it["company"]
        nid, k = base_id, 1
        while nid in existing_ids:
            nid = f"{base_id}·{it.get('role') or k}" if k == 1 else f"{base_id}·{k}"
            k += 1
        it["id"] = nid
        existing_ids.add(nid)
        items.append(it)
        added += 1

    # ---- 步骤 4：排序写回 ----
    items.sort(key=_sort_key)
    total = len(items)
    if write:
        out_doc = {"generated_at": datetime.now().isoformat(timespec="seconds"),
                   "items": [{k: it.get(k, "") for k in SEED_FIELDS} for it in items]}
        out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    return {"added": added, "merged": merged, "removed_recorded": removed_recorded,
            "decayed": decayed, "total": total}


def main():
    ap = argparse.ArgumentParser(description="queue_seed.json 确定性刷新（默认 dry-run）")
    ap.add_argument("--in", dest="inp", default=str(HERE / "queue_seed.json"))
    ap.add_argument("--out", dest="out", default=str(HERE / "queue_seed.json"))
    ap.add_argument("--apps", dest="apps", default="")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="（默认即 dry-run）只打印不写")
    ap.add_argument("--write", action="store_true",
                    help="真正写回 --out（不加此参数绝不写盘）")
    args = ap.parse_args()

    apps = args.apps
    if not apps:
        # 没显式给 apps 时，尝试从 server 拿真实路径（拿不到就跳过剔除步骤）
        try:
            import server  # noqa
            apps = str(server.APP_JSON) if server.APP_JSON else ""
        except Exception:
            apps = ""

    stat = refresh(args.inp, apps, args.out, extra_items=[], write=args.write)
    mode = "WRITE" if args.write else "DRY-RUN（未写盘）"
    print(f"[refresh_queue] {mode}")
    print(f"  时间衰减(urg 变化): {stat['decayed']}")
    print(f"  剔除已投: {stat['removed_recorded']}")
    print(f"  新增: {stat['added']}  合并去重: {stat['merged']}")
    print(f"  清单总数: {stat['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
