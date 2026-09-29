"""Run the unpacked MV3 extension against a disposable local API and form."""
import json
import os
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT))
test_data = tempfile.TemporaryDirectory(prefix="ac-extension-test-")
os.environ["AC_DATA_DIR"] = test_data.name
Path(os.environ["AC_DATA_DIR"], "profile.job.json").write_text(json.dumps({
    "schema_version": 1,
    "basic": {"name": "Test User", "email": "test@example.invalid", "phone": "13800000000"},
    "education": [{"school": "Example University", "major": "Computer Science"}],
    "highest_degree": "硕士"}, ensure_ascii=False), encoding="utf-8")
resume_dir = Path(os.environ["AC_DATA_DIR"], "resumes")
resume_dir.mkdir()
resume_path = resume_dir / "synthetic.pdf"
resume_path.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF")
Path(os.environ["AC_DATA_DIR"], "resumes.json").write_text(json.dumps({"resumes": [
    {"id": "test-pdf", "name": "synthetic.pdf", "path": str(resume_path), "tags": []}]}), encoding="utf-8")

import uvicorn
import server

api = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=8787, log_level="error"))
api_thread = threading.Thread(target=api.run, daemon=True)
api_thread.start()
form = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT)))
form_thread = threading.Thread(target=form.serve_forever, daemon=True)
form_thread.start()

try:
    with tempfile.TemporaryDirectory(prefix="ac-browser-") as browser_data, sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(browser_data, channel="msedge", headless=True,
            args=[f"--disable-extensions-except={ROOT / 'extension'}", f"--load-extension={ROOT / 'extension'}"])
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{form.server_port}/test_form.html")
        page.wait_for_timeout(2000)
        toolbar = page.locator("#ac-toggle").count()
        if toolbar:
            page.click("#ac-toggle")
            page.click("#ac-fill")
            page.wait_for_timeout(1000)
        before = page.locator("#name").input_value()
        review = page.locator("#ac-review").text_content()[:250] if toolbar else ""
        if toolbar:
            page.click("#ac-review button")
        after = page.locator("#name").input_value()
        assert toolbar and before == "" and after == "Test User"
        page.once("dialog", lambda dialog: dialog.accept("test-pdf"))
        page.click("#ac-up")
        page.wait_for_timeout(700)
        uploaded = page.locator("#resume").evaluate("el => el.files.length === 1 && el.files[0].name === 'synthetic.pdf'")
        assert uploaded
        results = {"local_form": {"toolbar": bool(toolbar), "review": review,
                          "name_before_confirm": before, "name_after_confirm": after,
                          "synthetic_pdf_attached": uploaded}}
        workers = context.service_workers
        if workers:
            extension_id = workers[0].url.split("/")[2]
            popup = context.new_page()
            popup.goto(f"chrome-extension://{extension_id}/popup.html")
            popup.wait_for_timeout(700)
            before_name = popup.locator("#profileName").input_value()
            popup.locator("#profileSchool").fill("Example University")
            popup.locator("#saveProfile").click()
            popup.wait_for_timeout(500)
            results["popup"] = {"loaded_name": before_name,
                                "status": popup.locator("#profileStatus").text_content()}
            assert before_name == "Test User"
            assert "已保存" in results["popup"]["status"]
            popup.close()
        for name, url in {
            "greenhouse": "https://job-boards.greenhouse.io/boldly/jobs/4005594006",
            "lever": "https://jobs.lever.co/usasurveyjob/fe664ea7-bfc2-4e3d-913b-1de52c59fa41/apply",
        }.items():
            ats = context.new_page()
            ats.route("**/*", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
            try:
                ats.goto(url, wait_until="domcontentloaded", timeout=30000)
                ats.wait_for_timeout(5000)
                toolbar_count = ats.locator("#ac-toggle").count()
                if not toolbar_count:
                    results[name] = {"error": "toolbar not injected", "url": ats.url, "title": ats.title()}
                    ats.close()
                    continue
                ats.click("#ac-toggle", timeout=5000)
                ats.click("#ac-fill", timeout=5000)
                ats.wait_for_timeout(600)
                suggestions = ats.locator("#ac-review input:checked").count()
                detected = ats.locator("#ac-review .ac-row").count()
                selected = ats.locator("#ac-review .ac-row").evaluate_all("els => els.filter(el => el.querySelector('input:checked')).map(el => el.textContent)")
                if suggestions:
                    ats.click("#ac-review button")
                results[name] = {"detected": detected, "suggested": suggestions,
                                 "selected": selected, "status": ats.locator("#ac-st").text_content(), "submit_clicked": False}
            except Exception as exc:
                results[name] = {"error": str(exc).splitlines()[0], "url": ats.url,
                                 "toolbar": ats.locator("#ac-toggle").count()}
            ats.close()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        context.close()
finally:
    api.should_exit = True
    api_thread.join(timeout=5)
    form.shutdown()
    test_data.cleanup()
