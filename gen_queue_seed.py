#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 gen_submit_list.py 的主数据 D 重新导出队列种子 queue_seed.json。

保持单一数据源：清单 HTML 与队列种子都由同一份 D 生成。
用法：python gen_queue_seed.py
"""
import importlib.util
import json
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent

spec = importlib.util.spec_from_file_location(
    "gsl", str(HERE.parent / "gen_submit_list.py"))
gsl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gsl)

D = gsl.D
is_submitted = gsl.is_submitted


def boss(name):
    return "https://www.zhipin.com/web/geek/search?query=" + urllib.parse.quote(name)


items = []
for cat, name, role, sal, loc, dl, urg, ltype, link in D:
    if is_submitted(name):
        continue
    url = link if ltype == "官网" else boss(name)
    items.append({
        "id": name,
        "company": name,
        "cat": cat,
        "role": role,
        "sal": sal,
        "loc": loc,
        "deadline": dl,
        "urg": urg,
        "ltype": ltype,
        "url": url,
    })

out = {"generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
       "items": items}
dest = HERE / "queue_seed.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"[ok] 队列种子已写入 {dest}，共 {len(items)} 家")
for it in items:
    print("  ", it["urg"].ljust(6), it["cat"], it["company"], it["ltype"])
