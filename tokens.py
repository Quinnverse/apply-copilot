#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · 令牌 / 租户管理（多租户：一个令牌 = 一个独立数据空间）

服务端后台后，用这个脚本给每个人发令牌 —— 谁的令牌进来就只看谁自己的目录。

    python tokens.py list                 列出所有令牌 / 租户
    python tokens.py add 张三              新增一个用户，打印其专属令牌
    python tokens.py add 我 --migrate-root 新增用户，并把旧单用户数据迁进他的租户
    python tokens.py rm  t_1a2b3c...       吊销令牌（数据目录保留，确认后可手动删）
    python tokens.py path t_1a2b3c...      打印该租户的数据目录

环境变量与 server.py 一致：AC_DATA_DIR / AC_TOKENS_FILE / AC_TENANTS_DIR / AC_APPLY_DIR。
令牌表落在 tokens.json（权限 600），服务端按 mtime 自动重载 —— 增删令牌无需重启服务。
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("AC_DATA_DIR") or HERE).resolve()
TOKENS_FILE = Path(os.environ.get("AC_TOKENS_FILE") or DATA_DIR / "tokens.json").resolve()
TENANTS_DIR = Path(os.environ.get("AC_TENANTS_DIR") or DATA_DIR / "tenants").resolve()


def tid_of(token):
    return "t_" + hashlib.sha256(str(token).encode("utf-8")).hexdigest()[:16]


def load():
    if not TOKENS_FILE.exists():
        return {}
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8")).get("tokens") or {}
    except Exception as exc:
        sys.exit(f"[错误] 令牌表解析失败 {TOKENS_FILE}：{exc}")


def save(tokens):
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_FILE.write_text(
        json.dumps({"tokens": tokens}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    try:
        os.chmod(TOKENS_FILE, 0o600)      # 令牌表只有 owner 能读
    except OSError:
        pass


def tenant_dir(tid):
    return TENANTS_DIR / tid


# 旧单用户布局里属于"个人数据"的文件（迁进租户目录）
MIGRATE_FILES = [
    "profile.job.json", "resumes.json", "resume_active.json", "field_memory.json",
    "queue.json", "queue_seed.json", "suggestions.json", "research_inbox.json",
]
# 每个文件在缺失时的初始内容（迁不动就建空的）
EMPTY_DEFAULTS = {
    "resumes.json": {"resumes": []},
    "resume_active.json": {"active": ""},
    "field_memory.json": {"fields": {}},
    "queue.json": {"status": {}, "items": [], "bind": {}},
    "suggestions.json": {"items": []},
    "research_inbox.json": {"requests": []},
    "profile.job.json": {"schema_version": 1, "basic": {}},
    "applications.json": {"applications": {}},
}


def ensure_tenant(tid, migrate_root=False):
    """建好租户目录（空态），可选把旧的单用户数据迁进来。"""
    d = tenant_dir(tid)
    (d / "resumes").mkdir(parents=True, exist_ok=True)
    for name in MIGRATE_FILES:
        dst, src = d / name, DATA_DIR / name
        if dst.exists():
            continue
        # queue_seed.json 是公共岗位数据：不管要不要迁旧数据，都给新租户复制一份
        if src.exists() and (migrate_root or name == "queue_seed.json"):
            shutil.copy2(src, dst)
        else:
            dst.write_text(json.dumps(EMPTY_DEFAULTS.get(name, {}),
                                      ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    # 投递库单独处理：旧布局下它在 autumn 技能目录（AC_APPLY_DIR 的父级 state/），
    # 不在 DATA_DIR 根目录 —— 必须先找旧位置，找不到才建空的。
    dst = d / "applications.json"
    if not dst.exists() or dst.stat().st_size < 8:
        src = None
        if migrate_root:
            env_apply = (os.environ.get("AC_APPLY_DIR") or "").strip()
            if env_apply:
                cand = Path(env_apply).resolve().parent / "state" / "applications.json"
                if cand.exists():
                    src = cand
            if src is None and (DATA_DIR / "applications.json").exists():
                src = DATA_DIR / "applications.json"
        if src is not None:
            shutil.copy2(src, dst)
        else:
            dst.write_text(json.dumps(EMPTY_DEFAULTS["applications.json"],
                                      ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    # 旧简历 PDF
    if migrate_root:
        old_resumes = Path(os.environ.get("AC_RESUME_DIR") or DATA_DIR / "resumes")
        if old_resumes.exists() and old_resumes.resolve() != (d / "resumes").resolve():
            for f in old_resumes.iterdir():
                if f.is_file() and f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
                    shutil.copy2(f, d / "resumes" / f.name)
    return d


def main():
    ap = argparse.ArgumentParser(description="网申助手 令牌/租户管理")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有令牌与租户")

    p_add = sub.add_parser("add", help="新增用户并发放令牌")
    p_add.add_argument("label", help="用户备注名，如 张三")
    p_add.add_argument("--token", default="",
                       help="沿用已有令牌（如 .env 里的 AC_TOKEN），不指定则随机生成")
    p_add.add_argument("--migrate-root", action="store_true",
                       help="把旧单用户数据（DATA_DIR 根目录 + 旧 applications.json）迁进该租户")

    p_rm = sub.add_parser("rm", help="吊销令牌")
    p_rm.add_argument("target", help="租户 id 或令牌前缀")

    p_path = sub.add_parser("path", help="打印租户数据目录")
    p_path.add_argument("target")

    args = ap.parse_args()
    tokens = load()

    if args.cmd == "list":
        if not tokens:
            print("（还没有任何令牌）")
            return
        print(f"{'标签':<16}{'租户 id':<20}{'数据目录'}")
        for tok, meta in tokens.items():
            meta = meta if isinstance(meta, dict) else {"label": str(meta), "tenant": tid_of(tok)}
            print(f"{meta.get('label','') or '-':<16}{meta.get('tenant') or tid_of(tok):<20}"
                  f"{tenant_dir(meta.get('tenant') or tid_of(tok))}")
        print(f"\n共 {len(tokens)} 个令牌；令牌表：{TOKENS_FILE}")

    elif args.cmd == "add":
        token = (args.token or "").strip() or secrets.token_hex(24)   # 默认 192bit 随机
        tid = tid_of(token)
        ensure_tenant(tid, migrate_root=args.migrate_root)
        tokens[token] = {"label": args.label, "tenant": tid,
                         "created": __import__("datetime").date.today().isoformat()}
        save(tokens)
        print("=" * 62)
        print(f"  用户：{args.label}")
        print(f"  令牌：{token}" + ("（沿用已有令牌）" if args.token else ""))
        print(f"  租户：{tid}   目录：{tenant_dir(tid)}")
        print("=" * 62)
        print("把上面「令牌」那一行发给本人，在插件/面板的令牌框里粘贴即可。")
        print("（服务端按 tokens.json 的 mtime 自动重载，无需重启服务）")

    elif args.cmd in ("rm", "path"):
        hit_tok, hit_meta = None, None
        for tok, meta in tokens.items():
            meta = meta if isinstance(meta, dict) else {"label": str(meta), "tenant": tid_of(tok)}
            if args.target in (meta.get("tenant"), tok) or tok.startswith(args.target):
                hit_tok, hit_meta = tok, meta
                break
        if not hit_tok:
            sys.exit(f"[错误] 没找到令牌/租户：{args.target}")
        tid = hit_meta.get("tenant") or tid_of(hit_tok)
        if args.cmd == "path":
            print(tenant_dir(tid))
            return
        tokens.pop(hit_tok, None)
        save(tokens)
        print(f"已吊销 {hit_meta.get('label','') or '-'} 的令牌（{tid}）。")
        print(f"数据仍在：{tenant_dir(tid)} —— 确认无用后手动删除。")


if __name__ == "__main__":
    main()
