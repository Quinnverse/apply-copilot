"""Security regression: two tokens stay isolated and bad token config fails closed."""
import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

with tempfile.TemporaryDirectory() as temp:
    data = Path(temp)
    os.environ["AC_DATA_DIR"] = temp
    os.environ["AC_REQUIRE_AUTH"] = "1"
    os.environ.pop("AC_TOKEN", None)
    os.environ.pop("AC_TOKENS", None)
    os.environ.pop("AC_APPLY_DIR", None)
    token_file = data / "tokens.json"
    tid_a = "t_" + hashlib.sha256(b"test-token-A").hexdigest()[:16]
    tid_b = "t_" + hashlib.sha256(b"test-token-B").hexdigest()[:16]
    token_file.write_text(json.dumps({"tokens": {
        "test-token-A": {"label": "A", "tenant": tid_a},
        "test-token-B": {"label": "B", "tenant": tid_b},
    }}), encoding="utf-8")

    import server
    from fastapi.testclient import TestClient

    with TestClient(server.app) as client:
        A = {"X-AC-Token": "test-token-A"}
        B = {"X-AC-Token": "test-token-B"}
        assert client.get("/api/profile").status_code == 401
        assert client.get("/api/profile", headers={"X-AC-Token": "wrong"}).status_code == 401
        assert client.get("/api/profile?token=test-token-A").status_code == 401
        assert client.get("/api/whoami", headers=A).json()["tenant"] == tid_a
        assert client.get("/api/whoami", headers=B).json()["tenant"] == tid_b

        assert client.put("/api/profile", headers=A, json={"basic": {"name": "A Private"}}).status_code == 200
        assert client.get("/api/profile", headers=A).json()["profile"]["basic"]["name"] == "A Private"
        assert client.get("/api/profile", headers=B).json()["profile"]["basic"] == {}

        uploaded = client.post("/api/resume", headers=A,
                               files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
        assert uploaded.status_code == 200, uploaded.text
        rid = uploaded.json()["resume"]["id"]
        assert len(client.get("/api/resumes", headers=A).json()["resumes"]) == 1
        assert client.get("/api/resumes", headers=B).json()["resumes"] == []
        assert client.get(f"/api/resume-file/{rid}", headers=B).status_code == 404

        assert client.post("/api/field-memory", headers=A, json={"fields": {"school": "A School"}}).status_code == 200
        assert client.get("/api/field-memory", headers=B).json()["fields"] == {}
        assert client.post("/api/mark", headers=A,
                           json={"company": "Example Corp", "title": "Engineer"}).status_code == 200
        assert len(json.loads((data / "tenants" / tid_a / "applications.json").read_text(encoding="utf-8"))["applications"]) == 1
        assert json.loads((data / "tenants" / tid_b / "applications.json").read_text(encoding="utf-8"))["applications"] == {}

        token_file.write_text(json.dumps({"tokens": {
            "test-token-A": {"tenant": tid_b}, "test-token-B": {"tenant": tid_b}}}), encoding="utf-8")
        assert client.get("/api/profile", headers=A).status_code == 401
        assert client.get("/api/profile", headers=B).status_code == 401

        # A damaged or removed token file must not expose the default profile.
        token_file.write_text("{broken", encoding="utf-8")
        assert client.get("/api/profile").status_code == 401
        assert client.get("/api/profile", headers=A).status_code == 401
        assert client.get("/api/health").json()["auth_ready"] is False
        token_file.write_text('{"tokens": ["invalid"]}', encoding="utf-8")
        assert client.get("/api/profile", headers=A).status_code == 401
        assert client.get("/api/health").json()["auth_ready"] is False
        token_file.unlink()
        assert client.get("/api/profile").status_code == 401
        assert client.get("/api/health").json()["auth"] is True
        print("tenant isolation and fail-closed auth: PASS")
