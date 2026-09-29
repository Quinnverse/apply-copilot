"""Small application ledger fallback when the external autumn skill is absent.

Keeps the `load_store` / `cmd_mark` interface used by server.py. It records
only user-confirmed submissions; it never submits an application.
"""

import json
import uuid
from datetime import date
from pathlib import Path


def load_store(path):
    file = Path(path)
    if not file.exists():
        return {"applications": {}}
    doc = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("applications", {}), dict):
        raise ValueError("Invalid applications store")
    return doc


def cmd_mark(args):
    file = Path(args.applications)
    store = load_store(file)
    applications = store.setdefault("applications", {})
    applied_at = args.date or date.today().isoformat()
    item_id = "manual-" + uuid.uuid4().hex[:12]
    applications[item_id] = {
        "id": item_id,
        "company": args.company,
        "title": args.title,
        "channel": args.channel,
        "resume_version": args.resume_version,
        "applied_at": applied_at,
        "stage": "已投",
        "note": args.note,
    }
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix(file.suffix + ".tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(file)
