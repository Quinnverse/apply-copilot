"""Server-side disposable isolation check. Run only on the Apply Copilot host."""
import hashlib
import json
import os
import pathlib
import secrets
import shutil
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path("/opt/copilot/data")
TOKENS = ROOT / "tokens.json"
BASE = "http://127.0.0.1:8787"


def tid(token):
    return "t_" + hashlib.sha256(token.encode()).hexdigest()[:16]


def save(table):
    temp = TOKENS.with_name("tokens.json.codex-test-tmp")
    temp.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, TOKENS)


def call(path, token=None, method="GET", data=None, content_type=None):
    headers = {"X-AC-Token": token} if token else {}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            body = response.read()
            parsed = json.loads(body) if response.headers.get_content_type() == "application/json" else None
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        return exc.code, None


def main():
    assert TOKENS.is_file() and ROOT.resolve() == pathlib.Path("/opt/copilot/data")
    original = json.loads(TOKENS.read_text(encoding="utf-8"))
    assert isinstance(original.get("tokens"), dict)
    assert not any(str(v.get("label", "")).startswith("codex-probe-")
                   for v in original["tokens"].values() if isinstance(v, dict))
    pairs = [(secrets.token_hex(24), "codex-probe-A"),
             (secrets.token_hex(24), "codex-probe-B")]
    table = dict(original)
    table["tokens"] = dict(original["tokens"])
    for token, label in pairs:
        table["tokens"][token] = {"label": label, "tenant": tid(token)}
    try:
        save(table)
        time.sleep(0.1)
        a, b = [token for token, _ in pairs]
        aw, bw = call("/api/whoami", a), call("/api/whoami", b)
        assert aw[0] == bw[0] == 200 and aw[1]["tenant"] != bw[1]["tenant"]
        assert call("/api/profile")[0] == 401
        marker = "CODEX_TEST_" + secrets.token_hex(4)
        payload = json.dumps({"basic": {"name": marker}}).encode()
        assert call("/api/profile", a, "PUT", payload, "application/json")[0] == 200
        assert marker in json.dumps(call("/api/profile", a)[1])
        assert marker not in json.dumps(call("/api/profile", b)[1])
        boundary = "codex" + secrets.token_hex(8)
        pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
        body = (("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="synthetic.pdf"'
                 "\r\nContent-Type: application/pdf\r\n\r\n").encode() + pdf +
                ("\r\n--" + boundary + "--\r\n").encode())
        uploaded = call("/api/resume", a, "POST", body, "multipart/form-data; boundary=" + boundary)
        assert uploaded[0] == 200
        resume_id = uploaded[1]["resume"]["id"]
        assert len(call("/api/resumes", a)[1]["resumes"]) == 1
        assert call("/api/resumes", b)[1]["resumes"] == []
        assert call("/api/resume-file/" + resume_id, b)[0] == 404
        memory = json.dumps({"fields": {"codex-probe": "A only"}}).encode()
        assert call("/api/field-memory", a, "POST", memory, "application/json")[0] == 200
        assert "codex-probe" not in json.dumps(call("/api/field-memory", b)[1])
        print("LIVE_ISOLATION_PASS: profile resume field-memory anonymous-auth")
    finally:
        latest = json.loads(TOKENS.read_text(encoding="utf-8"))
        for token, _ in pairs:
            latest["tokens"].pop(token, None)
        save(latest)
        tenant_root = (ROOT / "tenants").resolve()
        for token, _ in pairs:
            directory = tenant_root / tid(token)
            if directory.is_dir() and directory.resolve().parent == tenant_root:
                shutil.rmtree(directory)
        print("LIVE_PROBE_CLEANUP_DONE")


if __name__ == "__main__":
    main()
