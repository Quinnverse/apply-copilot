"""Opt-in public ATS smoke check. Synthetic data; never click Submit."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(ROOT))
import filler

PROFILE = {"basic": {"name": "Test User", "email": "test@example.invalid", "phone": "13800000000"}}
URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/boldly/jobs/4005594006",
    "lever": "https://jobs.lever.co/usasurveyjob/fe664ea7-bfc2-4e3d-913b-1de52c59fa41/apply",
}

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, channel="msedge")
    results = {}
    for name, url in URLS.items():
        page = browser.new_page()
        result = {"url": url, "submitted": False}
        try:
            page.route("**/*", lambda route: route.abort() if route.request.method == "POST" else route.continue_())
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            page.evaluate("""() => { window.chrome={runtime:{sendMessage:(msg,cb)=>{
              if(msg.type==='fill') window.__mapFields(msg.fields).then(payload=>cb({ok:true,json:{payload}}));
              else cb({error:'not used'});
            }},storage:{local:{get:(_k,cb)=>cb({})}}}; }""")
            page.expose_function("__mapFields", lambda fs: filler.build_fill_payload(fs, PROFILE))
            page.evaluate((ROOT / "extension/content.js").read_text(encoding="utf-8"))
            page.click("#ac-toggle", timeout=5000)
            page.click("#ac-fill", timeout=5000)
            page.wait_for_timeout(800)
            result["detected"] = page.locator("#ac-review .ac-row").count()
            result["suggested"] = page.locator("#ac-review input:checked").count()
            result["labels"] = page.locator("#ac-review .ac-row").all_text_contents()[:12]
            result["suggestions"] = page.locator("#ac-review .ac-row").evaluate_all("els => els.filter(el => el.querySelector('input:checked')).map(el => el.textContent)")
            result["before_fill"] = page.locator("#ac-review").is_visible()
            if result["suggested"]:
                page.click("#ac-review button")
                result["fill_status"] = page.locator("#ac-st").text_content()
            (ROOT / "evidence").mkdir(exist_ok=True)
            page.screenshot(path=str(ROOT / "evidence" / f"{name}-after-fill.png"), full_page=False)
            result["screenshot"] = f"evidence/{name}-after-fill.png"
            result["submit_clicked"] = False
        except Exception as exc:
            result["error"] = str(exc).splitlines()[0]
        results[name] = result
        page.close()
    browser.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
