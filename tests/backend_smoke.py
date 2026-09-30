"""End-to-end HTTP checks in a disposable data directory."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

with tempfile.TemporaryDirectory() as temp:
    os.environ["AC_DATA_DIR"] = temp
    os.environ.pop("AC_APPLY_DIR", None)
    import server
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        assert client.get("/api/health").json()["ok"]
        assert client.get("/static/assistant.bookmarklet.js").status_code == 404
        profile = {"schema_version": 1, "basic": {"name": "Test User", "email": "test@example.invalid"}}
        assert client.put("/api/profile", json=profile).status_code == 200
        assert client.get("/api/profile").json()["profile"]["basic"]["name"] == "Test User"
        mapped = client.post("/api/fill", json={"fields": [{"tag": "input", "type": "text", "id": "name", "name": "name", "label": "姓名"}]}).json()["payload"]
        assert mapped[0]["value"] == "Test User"
        marked = client.post("/api/mark", json={"company": "Example Corp", "title": "Engineer"})
        assert marked.status_code == 200, marked.text
        assert client.post("/api/mark", json={"company": "Example Corp", "title": "Engineer"}).status_code == 409
        applications = json.loads((Path(temp) / "applications.json").read_text(encoding="utf-8"))["applications"]
        assert len(applications) == 1
        evil = client.get("/api/profile", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in evil.headers
        extension = client.get("/api/profile", headers={"Origin": "chrome-extension://abcdefghijklmnop"})
        assert extension.headers.get("access-control-allow-origin") == "chrome-extension://abcdefghijklmnop"
        original_argv = sys.argv[:]
        try:
            sys.argv = ["server.py", "--host", "0.0.0.0"]
            try:
                server.main()
                raise AssertionError("unauthenticated public bind should fail")
            except SystemExit as exc:
                assert "拒绝" in str(exc)
        finally:
            sys.argv = original_argv
        print(json.dumps({"health": True, "profile": True, "mapping": mapped[0]["value"],
                          "recorded": len(applications), "duplicate_blocked": True,
                          "foreign_origin_blocked": True, "extension_origin_allowed": True}, indent=2))
