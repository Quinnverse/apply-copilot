"""Offline browser checks. Synthetic data only; no application is submitted."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROFILE = {"basic": {"name": "Test User", "email": "test@example.invalid", "phone": "13800000000"},
           "education": [{"school": "Example University", "major": "Computer Science"}],
           "highest_degree": "硕士", "grad_time": "2027-06"}


def run():
    import filler
    split_fields = [{"tag": "input", "type": "text", "label": "First Name", "name": "first_name"},
                    {"tag": "input", "type": "text", "label": "Last Name", "name": "last_name"}]
    assert [p["value"] for p in filler.build_fill_payload(split_fields, PROFILE)] == ["Test", "User"]
    chinese_profile = {**PROFILE, "basic": {**PROFILE["basic"], "name": "张三"}}
    assert all(not p["value"] for p in filler.build_fill_payload(split_fields, chinese_profile))
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel="msedge")
        def mount(page, html, local_profile=PROFILE):
            page.set_content(html)
            page.evaluate("""() => {
              window.__submitted = false;
              const form = document.querySelector('form');
              if(form) form.addEventListener('submit', e => { e.preventDefault(); window.__submitted = true; });
              window.chrome = {runtime:{sendMessage:(msg, cb) => {
                if(msg.type === 'fill') cb({ok:true,json:{payload:window.__testPayload(msg.fields)}});
                else cb({error:'not used in test'});
              }}, storage:{local:{get:(_keys,cb)=>cb({})}}};
            }""")
            # The real server maps the scan it receives. This callback does the same locally.
            page.expose_function("__mapFields", lambda fs: filler.build_fill_payload(fs, local_profile))
            page.evaluate("""() => { chrome.runtime.sendMessage = (msg, cb) => {
              if (msg.type === 'fill') window.__mapFields(msg.fields).then(payload => cb({ok:true,json:{payload}}));
              else cb({error:'not used in test'});
            }; }""")
            page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
            page.click("#ac-toggle")

        page = browser.new_page()
        mount(page, (ROOT / "test_form.html").read_text(encoding="utf-8"))
        page.click("#ac-fill")
        page.wait_for_timeout(100)
        results["preview"] = page.evaluate("""() => ({name:document.querySelector('#name').value,
          count:document.querySelector('#ac-review').textContent,
          choices:document.querySelectorAll('#ac-review input[type=checkbox]:checked').length})""")
        page.click("#ac-review button")
        results["plain"] = page.evaluate("""() => ({name:document.querySelector('#name').value,
          email:document.querySelector('#email').value, degree:document.querySelector('select').value,
          submitted:window.__submitted, status:document.querySelector('#ac-st').textContent})""")
        assert results["preview"]["name"] == "", "preview must not write"
        assert results["preview"]["choices"] >= 3
        assert results["plain"]["name"] == "Test User"
        assert results["plain"]["email"] == "test@example.invalid"
        assert results["plain"]["submitted"] is False

        complex_page = browser.new_page()
        mount(complex_page, """<form>
          <label for='controlled'>姓名</label><input id='controlled' name='name'>
          <label for='school'>学校</label><select id='school' name='school'><option value=''>请选择</option><option value='other'>Other</option></select>
          <label><input type='radio' name='gender' value='男'>男</label>
          <label><input type='radio' name='gender' value='女'>女</label>
          <label for='month'>毕业时间</label><input id='month' type='month' name='graduation'>
          <label for='custom'>为什么选择我们</label><textarea id='custom' name='why_company'></textarea>
          <button type='submit'>Submit</button></form>""", {**PROFILE, "basic": {**PROFILE["basic"], "gender": "女"}})
        complex_page.evaluate("""() => {
          const el = document.querySelector('#controlled');
          let tracker = el.value;
          Object.defineProperty(el, 'value', {configurable:true, get(){return HTMLInputElement.prototype.__lookupGetter__('value').call(this)},
            set(v){ tracker = v; HTMLInputElement.prototype.__lookupSetter__('value').call(this,v) }});
          window.__reactState = '';
          el.addEventListener('input', () => { if(el.value !== tracker) {window.__reactState=el.value; tracker=el.value;} });
        }""")
        complex_page.click("#ac-fill")
        complex_page.locator("#ac-review button").click()
        results["complex"] = complex_page.evaluate("""() => ({controlled:window.__reactState,
          school:document.querySelector('#school').value,
          female:document.querySelector('input[value="女"]').checked,
          month:document.querySelector('#month').value,
          custom:document.querySelector('#custom').value,
          submitted:window.__submitted,
          status:document.querySelector('#ac-st').textContent})""")
        assert results["complex"]["controlled"] == "Test User"
        assert results["complex"]["school"] == ""
        assert results["complex"]["female"] is True
        assert results["complex"]["month"] == "2027-06"
        assert results["complex"]["custom"] == ""
        assert results["complex"]["submitted"] is False
        browser.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
