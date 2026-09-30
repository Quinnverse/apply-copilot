"""Deployment package must contain only code, never user data."""
import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deploy_package", ROOT / "deploy" / "package.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    module.PROJ = root / "project"
    module.SKILL = root / "skill_source"
    module.PKG = root / "package"
    for name in module.APP_FILES:
        path = module.PROJ / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("code", encoding="utf-8")
    for name in module.STATIC_FILES:
        path = module.PROJ / "static" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("page", encoding="utf-8")
    for name in module.ROOT_FILES:
        path = module.PROJ / "deploy" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"line 1\r\nline 2\r\n" if name.endswith(".sh") else b"config")
    apply = module.SKILL / "scripts" / "apply.py"
    apply.parent.mkdir(parents=True, exist_ok=True)
    apply.write_text("code", encoding="utf-8")
    (module.PROJ / "profile.job.json").write_text("PRIVATE", encoding="utf-8")
    module.main()
    assert not (module.PKG / "data").exists()
    assert not (module.PKG / "skill" / "state").exists()
    assert not any("PRIVATE" in p.read_text(encoding="utf-8") for p in module.PKG.rglob("*") if p.is_file())
    assert b"\r\n" not in (module.PKG / "deploy_server.sh").read_bytes()
    (module.PKG / "data").mkdir()
    try:
        module.main()
    except SystemExit:
        pass
    else:
        raise AssertionError("stale data directory was accepted")
    (module.PKG / "data").rmdir()
    (module.PKG / "static" / "assistant.bookmarklet.js").write_text("PRIVATE", encoding="utf-8")
    try:
        module.main()
    except SystemExit:
        pass
    else:
        raise AssertionError("stale generated bookmarklet was accepted")
    print("deployment package excludes user data: PASS")
