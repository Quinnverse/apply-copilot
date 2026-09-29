// 网申助手 content script —— 在网申页上：
//  · 扫描表单字段，调用后端生成填充方案并填值（不提交）
//  · 上传推荐简历到文件框
//  · 检测"提交成功"页，弹出"记录投递"气泡（仍需你本人点击，合规）
// 人类在环：所有填充/上传/记录都是你点按钮触发，提交永远是你本人。

(function () {
  if (window.__applyCopilotInjected) return;
  window.__applyCopilotInjected = true;

  const SUCCESS_KW = ["投递成功", "提交成功", "申请已提交", "简历已收到", "投递完成", "您已成功投递", "报名成功", "已成功投递"];
  let successFlagged = false;
  let statusEl = null;
  let pending = [];

  function send(type, extra) {
    return new Promise((res) => chrome.runtime.sendMessage({ type, ...extra }, (r) => res(r || { error: "no response" })));
  }
  function getStore(key) {
    return new Promise((res) => chrome.storage.local.get([key], (s) => res(s)));
  }
  function status(msg) { if (statusEl) statusEl.textContent = msg; }
  function toast(msg) {
    const t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText = "position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#222;color:#fff;padding:8px 14px;border-radius:9px;font-size:13px;z-index:2147483647;box-shadow:0 4px 12px rgba(0,0,0,.3)";
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2400);
  }

  // ---- 字段扫描（与 filler.py 思路一致，但跑在真实 DOM 上）----
  function scanFields() {
    const radioGroups = new Set();
    const els = [...document.querySelectorAll("input,select,textarea")].filter((el) => {
      if (el.closest("#ac-fab")) return false;
      const t = el.tagName.toLowerCase();
      if (t === "input") {
        const ty = (el.type || "text").toLowerCase();
        if (["hidden", "submit", "reset", "button", "image", "file", "password"].includes(ty)) return false;
        if (ty === "radio") {
          const key = el.name || el.id;
          if (key && radioGroups.has(key)) return false;
          if (key) radioGroups.add(key);
        }
      }
      return !el.disabled && el.getClientRects().length > 0;
    });
    return els.map((el) => {
      const t = el.tagName.toLowerCase();
      let label = "";
      if (el.id) {
        const l = document.querySelector("label[for='" + (window.CSS && CSS.escape ? CSS.escape(el.id) : el.id) + "']");
        if (l) label = l.textContent.trim();
      }
      if (!label) { const pl = el.closest("label"); if (pl) label = pl.textContent.trim(); }
      if (!label) { const p = el.previousElementSibling; if (p && p.tagName === "LABEL") label = p.textContent.trim(); }
      return { el, field: {
        tag: t,
        type: t === "input" ? (el.type || "text") : t,
        id: el.id || "",
        name: el.name || "",
        placeholder: el.placeholder || "",
        label: label || el.getAttribute("aria-label") || "",
      }};
    });
  }

  function setVal(el, v) {
    try {
      const value = String(v);
      if (el.tagName === "SELECT") {
        const option = [...el.options].find(o => o.value === value || o.text.trim() === value);
        if (!option) return false;
        el.value = option.value;
      } else if (el.type === "radio" || el.type === "checkbox") {
        if (el.type === "checkbox" && !/^(true|yes|是|1)$/i.test(value)) return false;
        let target = el;
        if (el.type === "radio") {
          const group = el.name ? [...document.querySelectorAll('input[type="radio"]')].filter(x => x.name === el.name) : [el];
          target = group.find(x => {
            const label = (x.labels && [...x.labels].map(y => y.textContent).join(" ")) || x.getAttribute("aria-label") || "";
            return x.value === value || label.trim() === value;
          });
          if (!target) return false;
        }
        target.checked = true;
        el = target;
      } else {
        if (el.type === "date" && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
        if (el.type === "month" && !/^\d{4}-\d{2}$/.test(value)) return false;
        const setter = Object.getOwnPropertyDescriptor(
          el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value").set;
        setter.call(el, value);
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      const ok = el.type === "radio" || el.type === "checkbox" ? el.checked : el.value === value || el.tagName === "SELECT";
      if (!ok) return false;
      el.style.backgroundColor = "#e8f3ff";
      return true;
    } catch (e) { return false; }
  }
  function applyPayload() {
    let filled = 0, missed = 0;
    pending.forEach(({el, p, checkbox}) => {
      if (!checkbox.checked || !el.isConnected) return;
      if (setVal(el, p.value)) filled++;
      else { el.style.border = "2px solid #e74c3c"; missed++; }
    });
    status("已填充 " + filled + " 个，写入失败 " + missed + " 个。请检查后自行提交。");
    rootReview().hidden = true;
  }

  function rootReview() { return document.getElementById("ac-review"); }

  function showReview(scanned, payload) {
    const review = rootReview();
    review.replaceChildren();
    pending = [];
    let reliable = 0, confirm = 0, manual = 0;
    payload.forEach((p, i) => {
      const item = scanned[i];
      if (!item) return;
      const value = String(p.value || "").trim();
      const usable = p.confidence >= 0.5 && value && !/^\[(待补充|敏感)/.test(value);
      const category = !usable ? "需手填" : p.confidence >= 0.8 ? "可填写" : "需确认";
      if (!usable) manual++; else if (p.confidence >= 0.8) reliable++; else confirm++;
      const row = document.createElement("label");
      row.className = "ac-row";
      const check = document.createElement("input"); check.type = "checkbox";
      check.checked = !!usable; check.disabled = !usable;
      const caption = document.createElement("span");
      caption.textContent = `${category} · ${p.label || item.field.label || item.field.name || "未命名"} → ${usable ? value : "由你填写"}`;
      row.append(check, caption); review.appendChild(row);
      if (usable) pending.push({el:item.el, p, checkbox:check});
    });
    const heading = document.createElement("div");
    heading.textContent = `发现 ${scanned.length} 个字段：${reliable} 个可填写，${confirm} 个需确认，${manual} 个需手填`;
    review.prepend(heading);
    const button = document.createElement("button");
    button.className = "act"; button.textContent = "填充勾选字段";
    button.onclick = applyPayload; review.appendChild(button);
    review.hidden = false;
    status("请核对每个建议，再填充勾选字段。");
  }

  async function doFill() {
    const scanned = scanFields();
    if (!scanned.length) { status("未识别到可填字段；请检查 iframe 或稍后重试"); return; }
    const s = await getStore("currentTarget");
    const jd = (s.currentTarget && s.currentTarget.jd) || null;
    const r = await send("fill", { fields: scanned.map(x => x.field), jd });
    if (r.error) { status("填充失败：" + r.error); return; }
    showReview(scanned, r.json.payload || []);
  }

  async function uploadResume() {
    let st = await getStore("currentResumeId");
    let id = (st && st.currentResumeId) || null;
    if (!id) {
      const r = await send("getResumes");
      const list = (r.json && r.json.resumes) || [];
      id = prompt("上传哪份简历？输入 id：\n" + list.map((x) => x.id + "  " + x.name).join("\n"), list[0] && list[0].id);
      if (!id) return;
    }
    const r = await send("resumeFile", { id });
    if (r.error) { status("获取简历失败：" + r.error); return; }
    const input = document.querySelector("input[type=file]");
    if (!input) { status("未找到文件上传框，请手动上传"); return; }
    try {
      const blob = await (await fetch(r.dataUrl)).blob();
      const file = new File([blob], r.name, { type: "application/pdf" });
      const dt = new DataTransfer();
      dt.items.add(file);
      try { input.files = dt.files; }
      catch (e) { Object.defineProperty(input, "files", { value: dt.files, configurable: true }); }
      input.dispatchEvent(new Event("change", { bubbles: true }));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      status("已尝试上传简历：" + r.name + "（页面若无反应请手动确认）");
    } catch (e) { status("上传失败：" + e); }
  }

  async function doRecord() {
    const s = await getStore("currentTarget");
    const company = (s.currentTarget && s.currentTarget.company) || "";
    const c = prompt("公司名", company) || company;
    if (!c) return;
    const title = prompt("岗位标题（用于投递库记录）", "") || "";
    const rv = prompt("简历版本 id（可选，如 algo-v1 / agent-dev-v1）", "") || "";
    const r = await send("mark", { payload: { company: c, title, resume_version: rv || null, channel: "官网" } });
    if (r.error) { status("记录失败：" + r.error); toast("记录失败：" + r.error); }
    else { status("已记录：" + c + " · " + title); toast("已记录 ✓"); }
  }

  function flagSuccess() {
    if (successFlagged) return;
    successFlagged = true;
    const b = document.getElementById("ac-record");
    if (b) { b.classList.add("ac-pulse"); b.style.background = "#1F7A4D"; }
    banner("🎉 检测到提交成功页 —— 点「记录投递」入库（仍需你本人确认）");
  }
  function banner(msg) {
    const d = document.createElement("div");
    d.textContent = msg;
    d.style.cssText = "position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#1F7A4D;color:#fff;padding:9px 16px;border-radius:10px;font-size:13px;z-index:2147483647;box-shadow:0 4px 12px rgba(0,0,0,.3)";
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 6000);
  }

  // ---- 注入浮动工具条 ----
  function inject() {
    if (document.getElementById("ac-fab")) return;
    const css = `
      #ac-fab{position:fixed;right:14px;bottom:14px;z-index:2147483647;font-family:-apple-system,'PingFang SC',sans-serif}
      #ac-fab .fab{width:46px;height:46px;border-radius:50%;background:#185FA5;color:#fff;border:none;font-size:22px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.3)}
      #ac-fab .panel{display:none;position:absolute;right:0;bottom:56px;width:330px;max-height:70vh;overflow:auto;background:#fff;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.25);padding:12px;color:#1f2329}
      #ac-fab .panel.open{display:block}
      #ac-fab button.act{display:block;width:100%;margin:5px 0;background:#185FA5;color:#fff;border:none;border-radius:8px;padding:9px;font-size:13px;font-weight:600;cursor:pointer}
      #ac-fab button.act.rec{background:#1F7A4D}
      #ac-fab button.act.up{background:#d98210}
      #ac-fab .st{font-size:11.5px;color:#5f6368;margin-top:6px;line-height:1.5;min-height:16px}
      #ac-fab #ac-review[hidden]{display:none}#ac-fab .ac-row{display:flex;gap:6px;padding:5px 0;font-size:11px;line-height:1.3;overflow-wrap:anywhere}
      #ac-fab .act.ac-pulse{animation:acp 1s infinite}@keyframes acp{0%{box-shadow:0 0 0 0 rgba(31,122,77,.6)}70%{box-shadow:0 0 0 10px rgba(31,122,77,0)}100%{box-shadow:0 0 0 0 rgba(31,122,77,0)}}`;
    const style = document.createElement("style"); style.textContent = css; document.head.appendChild(style);

    const root = document.createElement("div");
    root.id = "ac-fab";
    root.innerHTML = `
      <div class="panel" id="ac-panel">
        <button class="act" id="ac-fill">① 填充表单</button>
        <div id="ac-review" hidden></div>
        <button class="act up" id="ac-up">② 上传推荐简历</button>
        <button class="act rec" id="ac-record">③ 记录投递</button>
        <div class="st" id="ac-st"></div>
      </div>
      <button class="fab" id="ac-toggle" title="网申助手">🛠</button>`;
    document.body.appendChild(root);
    statusEl = root.querySelector("#ac-st");

    root.querySelector("#ac-toggle").onclick = () => root.querySelector("#ac-panel").classList.toggle("open");
    root.querySelector("#ac-fill").onclick = doFill;
    root.querySelector("#ac-up").onclick = uploadResume;
    root.querySelector("#ac-record").onclick = doRecord;
  }

  function checkSuccess() {
    if (successFlagged || !document.body) return;
    const txt = document.body.innerText || "";
    if (SUCCESS_KW.some((k) => txt.includes(k))) flagSuccess();
  }

  function boot() {
    inject();
    checkSuccess();
    const mo = new MutationObserver(() => { if (!document.getElementById("ac-fab")) inject(); checkSuccess(); });
    mo.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
