// ==UserScript==
// @name         网申助手 Copilot
// @namespace    apply-copilot
// @version      1.3.0
// @description  网申辅助：字段建议、简历附件与投递记录；最终提交只由用户本人执行。
// @author       apply-copilot
// @match        *://*/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant       GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_openInTab
// @grant        GM_addStyle
// @grant        GM_listValues
// @connect      127.0.0.1
// @connect      localhost
// @connect      apply.quinnverse.tech
// @run-at       document-idle
// @noframes
// ==/UserScript==

/* 全链路说明：
 *  开机  GET {backend}/api/assistant-context?host=... → 未命中公司且未手动启用 → 静默退出
 *  填表  scanFields → buildPayload（LEARNED→RULES→关键词→SYN→type 兜底 5 级匹配）→ setVal
 *  挂简历  GM blob 拉 /api/resume-file/{rid} → DataTransfer → input[type=file].files
 *  提交闸门  只高亮提交按钮，用户本人点击
 *  记账  URL/文案命中成功关键词 → GM 去重（同公司同天一次）→ POST /api/mark
 *
 *  设计约束：核心逻辑（填表/挂简历/侦测/记账）一律经 GMshim 访问 GM 能力，
 *  无 GM 环境自动降级 fetch/localStorage —— 同一份代码可在 offscreen Chromium e2e 直跑。
 */
(function () {
  'use strict';
  if (window.__acCopilot) return; window.__acCopilot = 1;

  // ================================================================ GMshim
  // GM API 抽象层：有 GM 用 GM，没有降级 fetch / localStorage（e2e 路径）。
  var GMshim = (function () {
    var hasXHR = typeof GM_xmlhttpRequest === 'function';
    var hasGet = (typeof GM_getValue === 'function') ||
      (typeof GM !== 'undefined' && GM && typeof GM.getValue === 'function');
    var hasSet = (typeof GM_setValue === 'function') ||
      (typeof GM !== 'undefined' && GM && typeof GM.setValue === 'function');

    function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
    function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

    function http(opt) {
      // opt: {method, url, headers, data, responseType('text'|'blob'), timeout}
      // 返回 Promise<{status, text, blob}>；blob 仅 responseType='blob' 且成功时非空。
      return new Promise(function (resolve, reject) {
        if (hasXHR) {
          try {
            GM_xmlhttpRequest({
              method: opt.method || 'GET',
              url: opt.url,
              headers: opt.headers || {},
              data: opt.data || undefined,
              responseType: opt.responseType || 'text',
              timeout: opt.timeout || 15000,
              onload: function (r) {
                resolve({ status: r.status, text: (r.responseText || ''), blob: r.response || null });
              },
              onerror: function () { reject(new Error('GM_xmlhttpRequest error')); },
              ontimeout: function () { reject(new Error('timeout')); }
            });
          } catch (e) { reject(e); }
          return;
        }
        // 降级 fetch
        var init = { method: opt.method || 'GET', headers: opt.headers || {} };
        if (opt.data) init.body = opt.data;
        fetch(opt.url, init).then(function (r) {
          if (opt.responseType === 'blob') {
            return r.blob().then(function (b) { return { status: r.status, text: '', blob: b }; });
          }
          return r.text().then(function (t) { return { status: r.status, text: t, blob: null }; });
        }).then(resolve, function (e) { reject(e); });
      });
    }

    return {
      http: http,
      // 多部件上传（简历 PDF/图片）：构造 FormData，交给 GM_xmlhttpRequest / fetch
      upload: function (path, file) {
        return new Promise(function (resolve, reject) {
          var fd = new FormData();
          fd.append('file', file, (file && file.name) ? file.name : 'resume.pdf');
          if (hasXHR) {
            try {
              GM_xmlhttpRequest({
                method: 'POST', url: SET.backend + path,
                headers: { 'X-AC-Token': SET.token || '' },
                data: fd, timeout: 60000,
                onload: function (r) { resolve({ status: r.status, text: (r.responseText || '') }); },
                onerror: function () { reject(new Error('upload error')); },
                ontimeout: function () { reject(new Error('timeout')); }
              });
              return;
            } catch (e) { reject(e); }
          }
          fetch(SET.backend + path, { method: 'POST', headers: { 'X-AC-Token': SET.token || '' }, body: fd })
            .then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
            .then(resolve, reject);
        });
      },
      get: function (k) {                    // 一律返回 Promise<string|null>
        if (typeof GM !== 'undefined' && GM && typeof GM.getValue === 'function') {
          return Promise.resolve(GM.getValue(k)).then(function (v) { return v == null ? null : String(v); });
        }
        if (typeof GM_getValue === 'function') {
          try { var v = GM_getValue(k); return Promise.resolve(v == null ? null : String(v)); } catch (e) {}
        }
        return Promise.resolve(lsGet(k));
      },
      set: function (k, v) {                 // 一律返回 Promise
        if (typeof GM !== 'undefined' && GM && typeof GM.setValue === 'function') {
          try { GM.setValue(k, String(v)); } catch (e) {}
          return Promise.resolve();
        }
        if (typeof GM_setValue === 'function') { try { GM_setValue(k, String(v)); } catch (e) {} return Promise.resolve(); }
        lsSet(k, String(v));
        return Promise.resolve();
      },
      hasGM: function () { return hasXHR || hasGet || hasSet; }
    };
  })();

  // ================================================================ 状态
  var DEFAULT_BACKEND = 'http://127.0.0.1:8787';
  var SET = { backend: DEFAULT_BACKEND, token: '', autoFill: '0', autoAttach: '0', autoCloseTab: '0', pickMode: '1', debug: '0' };
  function safeBackend(raw) {
    try {
      var url = new URL(raw);
      return url.protocol === 'https:' ||
        (url.protocol === 'http:' && /^(127\.0\.0\.1|localhost|\[::1\])$/.test(url.hostname));
    } catch (e) { return false; }
  }
  var CTX = null;           // /api/assistant-context 原始返回
  var RULES = [], VALUES = [], LEARNED = {}, SYN = [];
  var COMPANY = '', COMPANY_SRC = '', ROLE = '', LTYPE = '', RESUME_ID = '', RESUME_NAME = '';
  var VALMAP = {};
  var MARKED = false;       // 本次页面生命周期内已记账
  var SUBMIT_CLICKED = false; // Bug#6：本页提交按钮是否被真实点击过（成功侦测的闸门）
  var PICK_MODE = false;
  var LAST_FIELDS = [];
  var AC_IDX = 0;
  var RESCAN_T = null;
  var SUCCESS_T = null;

  // 成功关键词（Bug#6 收紧：URL 只认回执型路径，去掉裸 "success" 避免 success-stories 误报；
  // 文案侦测只在用户真点过提交按钮后才启用 —— 见 SUBMIT_CLICKED 闸）
  var SUCCESS_TEXT = /(投递成功|申请成功|提交成功|投递完成|申请已提交|已成功提交|已收到您的?(简历|申请|投递)|简历已(成功)?提交|application\s+(has\s+been\s+)?(successfully\s+)?(submitted|received)|your\s+application\s+(has\s+been\s+)?(submitted|received))/i;
  var SUCCESS_URL = /(\/apply[-_]?(success|ok|done)|\/success(?![a-z-])|\/submitted|application[-_]?submitted|submit[-_]?success|[?&](result|status)=success)/i;

  // ================================================================ 工具（移植自 assistant.js，QA 两轮验证过的核心）
  function cssEsc(s) { try { return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/([ #;?%&,.+*~\':"!^$[\]()=>|/@])/g, '\\$1'); } catch (e) { return s; } }
  function textOf(el) { try { return (el.textContent || '').replace(/\s+/g, ' ').trim(); } catch (e) { return ''; } }
  function docOf(el) { try { return el.ownerDocument || document; } catch (e) { return document; } }

  function keyOf(f) {
    var s = String(f.label || f.aria || f.placeholder || f.title || f.name || f.id || '')
      .toLowerCase().replace(/[\s　]+/g, ' ').replace(/[:：*＊（）()？?]/g, '').trim();
    return s.slice(0, 120);
  }
  function scoreField(f, kw) {
    var hay = f.hay || '';
    var k = String(kw || '').toLowerCase();
    if (!k) return 0;
    if (hay.indexOf(k) >= 0) return 1.0;
    var parts = k.split(/[\s\-_]/).filter(function (p) { return p.length > 1; });
    if (parts.length && parts.every(function (p) { return hay.indexOf(p) >= 0; })) return 0.7;
    return 0.0;
  }
  // 规则归一 key：命中 RULES 关键词返回规则中文规范名（跨站记忆通用），否则回退标签字面。
  function ruleKeyOf(f) {
    var hay = f.hay || '';
    for (var i = 0; i < RULES.length; i++) {
      var kws = RULES[i].k;
      if (!kws) continue;
      var arr = Array.isArray(kws) ? kws : [kws];
      for (var j = 0; j < arr.length; j++) {
        if (arr[j] && hay.indexOf(String(arr[j]).toLowerCase()) >= 0) return arr[0];
      }
    }
    return keyOf(f);
  }
  // 标签抽取：label[for] → aria-labelledby → 包裹 label → 向上 6 层容器文本 → 前兄弟
  function labelOf(el) {
    var s = '';
    try {
      var d = docOf(el);
      if (el.id) { var l = d.querySelector('label[for="' + cssEsc(el.id) + '"]'); if (l) s = textOf(l); }
      if (!s) { var lb = el.getAttribute('aria-labelledby'); if (lb) { var t = d.getElementById(lb); if (t) s = textOf(t); } }
      if (!s) { var pl = el.closest ? el.closest('label') : null; if (pl) s = textOf(pl); }
      if (!s && el.closest) {
        var n = el, depth = 0;
        while (n && depth < 6) {
          var c = n.parentElement; if (!c) break;
          var cand = '';
          var pv = n.previousElementSibling, nx = n.nextElementSibling;
          if (pv && !pv.contains(el)) cand = textOf(pv);
          if (!cand && nx && !nx.contains(el)) cand = textOf(nx);
          if (!cand && c.children.length <= 6) {
            var kids = c.children;
            for (var i = 0; i < kids.length; i++) {
              var k = kids[i];
              if (k === n || k.contains(el)) continue;
              var t2 = textOf(k);
              if (t2) { cand = t2; break; }
            }
          }
          if (cand) { s = cand; break; }
          n = c; depth++;
        }
      }
      if (!s) { var prev = el.previousElementSibling; if (prev) s = textOf(prev); }
    } catch (e) {}
    return String(s || '').replace(/[\*＊:：\s]+$/g, '').slice(0, 60);
  }
  function visible(el) {
    try {
      var r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return false;
      var st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.05) return false;
      return true;
    } catch (e) { return true; }
  }
  // 招聘门户常把表单放 iframe —— 穿透同源 iframe 一起扫
  function allDocs() {
    var docs = [document];
    try {
      var fr = document.querySelectorAll('iframe');
      for (var i = 0; i < fr.length; i++) {
        try { var d = fr[i].contentDocument; if (d) docs.push(d); } catch (e) {}
      }
    } catch (e) {}
    return docs;
  }
  function describe(el) {
    var t = el.tagName.toLowerCase();
    var label = labelOf(el);
    var aria = (el.getAttribute && el.getAttribute('aria-label')) || '';
    var title = (el.getAttribute && el.getAttribute('title')) || '';
    var ph = '';
    try { ph = el.placeholder || el.getAttribute('data-ph') || el.getAttribute('data-placeholder') || ''; } catch (e) {}
    var sel = '';
    if (el.id) sel = '#' + cssEsc(el.id);
    else if (el.name) sel = '[name="' + String(el.name).replace(/"/g, '\\"') + '"]';
    else {
      var idx = el.getAttribute && el.getAttribute('data-ac-idx');
      if (!idx) { idx = 'ac' + (++AC_IDX); try { el.setAttribute('data-ac-idx', idx); } catch (e) {} }
      sel = '[data-ac-idx="' + idx + '"]';
    }
    var hay = [label, aria, title, ph, el.name, el.id].filter(Boolean).join(' ').toLowerCase();
    // radio 组：单个选项的 label 只有"男/女"，把外层容器文本（"性别 男 女"）并进 hay 才能命中"性别"规则
    if (t === 'input' && (el.type || '').toLowerCase() === 'radio' && el.closest) {
      try {
        var anc = el.closest('label');
        anc = anc ? anc.parentElement : el.parentElement;
        if (anc) hay = (hay + ' ' + textOf(anc)).toLowerCase().slice(0, 200);
      } catch (e) {}
    }
    return { el: el, tag: t, type: t === 'input' ? (el.type || 'text') : t, id: el.id || '', name: el.name || '',
             placeholder: ph || '', label: label || '', aria: aria || '', title: title || '', sel: sel, hay: hay,
             group: (el.name || '') };
  }
  function scanFields() {
    var out = [];
    allDocs().forEach(function (doc) {
      Array.prototype.slice.call(doc.querySelectorAll(
        'input,select,textarea,[contenteditable="true"],[role="textbox"]'))
        .filter(function (el) {
          if (el.id === 'ac-pick-input') return false;
          if (el.closest && el.closest('#ac-fab')) return false;
          var t = el.tagName.toLowerCase();
          if (t === 'input') {
            var ty = (el.type || 'text').toLowerCase();
            // 隐藏/按钮/文件/checkbox 不自动填；radio 保留（性别等）
            return ['hidden', 'submit', 'reset', 'button', 'image', 'file', 'checkbox'].indexOf(ty) < 0;
          }
          return true;
        })
        .forEach(function (el) { out.push(describe(el)); });
    });
    var vis = out.filter(function (f) { return visible(f.el); });
    return vis.length ? vis : out;
  }

  // ================================================================ 匹配（5 级：LEARNED→RULES→关键词→SYN→type）
  function usable(v) { return !!(v && String(v).charAt(0) !== '['); }   // 过滤 [待补充]/[敏感信息]

  function buildPayload(fields) {
    var out = [];
    fields.forEach(function (f) {
      var key = ruleKeyOf(f);
      // ① 已记住的值（跨站点通用）
      if (key && LEARNED && LEARNED[key]) {
        out.push({ el: f.el, label: f.label || f.placeholder || f.name || f.id || '字段', selector: f.sel, type: f.type,
                   value: LEARNED[key], confidence: 1.0, learned: true, key: key, hay: f.hay });
        return;
      }
      var best = null, bs = 0;
      var kwsOf = function (r) { return Array.isArray(r.k) ? r.k : [r.k]; };
      // ② 规则匹配（带类型白名单）
      RULES.forEach(function (r) {
        if (r.t && r.t.length && f.type && r.t.indexOf(f.type) < 0) return;
        var sc = Math.max.apply(null, kwsOf(r).map(function (kw) { return scoreField(f, kw); }));
        if (sc > bs && usable(r.v)) { bs = sc; best = r; }
      });
      // ③ 规则匹配（忽略类型白名单 —— 很多 SPA 的 type 是 text）
      if (bs < 0.5) {
        RULES.forEach(function (r) {
          var sc = Math.max.apply(null, kwsOf(r).map(function (kw) { return scoreField(f, kw); }));
          if (sc > bs && usable(r.v)) { bs = sc; best = r; }
        });
      }
      // ④ 宽松同义词
      if (bs < 0.5) {
        for (var i = 0; i < SYN.length; i++) {
          if (SYN[i][0].test(f.hay)) {
            var v = VALMAP[SYN[i][1]];
            if (usable(v)) { best = { v: v }; bs = 0.9; break; }
          }
        }
      }
      // ⑤ input type 兜底
      if (bs < 0.5) {
        var ty = (f.type || '').toLowerCase();
        if (ty === 'tel' && usable(VALMAP['手机'])) { best = { v: VALMAP['手机'] }; bs = 0.8; }
        else if (ty === 'email' && usable(VALMAP['邮箱'])) { best = { v: VALMAP['邮箱'] }; bs = 0.8; }
      }
      out.push({ el: f.el, label: f.label || f.placeholder || f.name || f.id || '字段', selector: f.sel, type: f.type,
                 value: (best && usable(best.v)) ? best.v : '', confidence: bs, key: key, hay: f.hay });
    });
    return out;
  }

  // ================================================================ 赋值（React/Vue 受控组件走原生 setter）
  function fire(el, name) { try { el.dispatchEvent(new Event(name, { bubbles: true })); } catch (e) {} }
  // 多值档案值（如"浙江、上海、江苏"）：只认精确匹配，绝不做包含匹配
  function isMultiValue(v) { return /[、,，\/;；|]/.test(String(v == null ? '' : v)); }
  // 学历/学位选项归一：去噪音词，保留核心词（硕士/本科/博士…）
  function normEdu(s) {
    return String(s == null ? '' : s).toLowerCase()
      .replace(/[\s　]/g, '')
      .replace(/全日制|应届|在读|统招|普通|学历|学位|研究生|大学|学院|院|系/g, '')
      .trim();
  }
  function radioLabel(el) {
    try {
      var d = docOf(el);
      if (el.id) { var l = d.querySelector('label[for="' + cssEsc(el.id) + '"]'); if (l) return textOf(l); }
      if (el.closest) {
        var pl = el.closest('label'); if (pl) return textOf(pl);
        var par = el.parentElement; if (par) return textOf(par);
      }
    } catch (e) {}
    return '';
  }
  function setValRadio(el, v) {
    var name = el.name; if (!name) return false;
    var group = Array.prototype.slice.call(
      document.querySelectorAll('input[type="radio"][name="' + String(name).replace(/"/g, '\\"') + '"]'));
    if (!group.length) return false;
    var wantMale = /男/.test(v), wantFemale = /女/.test(v);
    var target = null;
    for (var i = 0; i < group.length && !target; i++) {
      var lab = radioLabel(group[i]) || '';
      var low = (lab + ' ' + (group[i].value || '')).toLowerCase();
      if (wantMale && (lab.indexOf('男') >= 0 || /\bmale\b/.test(low) || low === 'm')) target = group[i];
      else if (wantFemale && (lab.indexOf('女') >= 0 || /\bfemale\b/.test(low) || low === 'f')) target = group[i];
      else if (group[i].value && (group[i].value === v || group[i].value.toLowerCase() === String(v).toLowerCase())) target = group[i];
    }
    if (target) {
      if (!target.checked) { target.checked = true; fire(target, 'change'); fire(target, 'input'); }
      target.style.backgroundColor = '#e8f3ff';
      return true;
    }
    return false;
  }
  function setVal(el, v) {
    try {
      var tag = el.tagName;
      if (tag === 'INPUT' && el.type === 'radio') return setValRadio(el, v);
      if (tag === 'SELECT') {
        var opts = Array.prototype.slice.call(el.options || []);
        var vNorm = normEdu(v);
        var hit = null;
        // ① 精确：text/value 原始相等，或归一后相等
        for (var i = 0; i < opts.length && !hit; i++) {
          var t = String(opts[i].textContent || '').trim(), ov = String(opts[i].value || '').trim();
          if (t === v || ov === v || normEdu(t) === vNorm || normEdu(ov) === vNorm) hit = opts[i];
        }
        // ② 双向包含（归一）；多值档案值跳过此步
        if (!hit && !isMultiValue(v)) {
          for (var j = 0; j < opts.length && !hit; j++) {
            var t2 = normEdu(String(opts[j].textContent || '').trim());
            if (t2 && vNorm && (t2.indexOf(vNorm) >= 0 || vNorm.indexOf(t2) >= 0)) hit = opts[j];
          }
        }
        if (hit) { el.value = hit.value; fire(el, 'change'); fire(el, 'input'); return true; }
        // ③ 都没中：红框标记、不偷赋值
        try { el.style.border = '2px solid #e74c3c'; el.setAttribute('data-ac-miss', '1'); } catch (e) {}
        return false;
      }
      if (tag === 'INPUT' && (el.type === 'date' || el.type === 'month')) {
        var val = v;
        if (el.type === 'date' && /^\d{4}-\d{2}$/.test(v)) val = v + '-01';
        if (el.type === 'month' && /^\d{4}-\d{2}-\d{2}$/.test(v)) val = v.slice(0, 7);
        var p2 = Object.getPrototypeOf(el), d2 = p2 && Object.getOwnPropertyDescriptor(p2, 'value');
        if (d2 && d2.set) d2.set.call(el, val); else el.value = val;
        fire(el, 'input'); fire(el, 'change');
      } else if (el.isContentEditable || (el.getAttribute && el.getAttribute('contenteditable') === 'true')) {
        el.focus();
        try {
          var r = document.createRange(); r.selectNodeContents(el);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          document.execCommand('insertText', false, v);
        } catch (e) { el.textContent = v; }
        fire(el, 'input');
      } else {
        var proto3 = Object.getPrototypeOf(el);
        var desc3 = proto3 && Object.getOwnPropertyDescriptor(proto3, 'value');
        if (desc3 && desc3.set) desc3.set.call(el, v); else el.value = v;
        fire(el, 'input'); fire(el, 'change');
      }
      // 复位红框（之前标过未命中的）
      try { el.style.backgroundColor = '#e8f3ff'; el.style.border = ''; el.removeAttribute('data-ac-miss'); } catch (e) {}
      return true;
    } catch (e) { return false; }
  }

  // ================================================================ 后端通信
  // 返回 {ok, ...data, status} —— status 是 HTTP 状态码，409 判定依赖它（Bug#3）
  function postJSON(path, body) {
    return GMshim.http({
      method: 'POST', url: SET.backend + path, timeout: 12000,
      headers: { 'Content-Type': 'application/json', 'X-AC-Token': SET.token || '' },
      data: JSON.stringify(body || {})
    }).then(function (res) {
      if (res.status === 401) {
        logLine('后端 401：令牌缺失或不正确 → 请到 ⚙ 填「访问令牌」');
      }
      var data = null;
      try { data = JSON.parse(res.text); } catch (e) { data = null; }
      if (!data || typeof data !== 'object') data = { ok: false, error: 'HTTP ' + res.status };
      data.status = res.status;
      return data;
    }).catch(function (e) {
      return { ok: false, error: String(e && e.message || e), status: 0 };
    });
  }

  // GET 取 JSON（带 X-AC-Token），返回 {ok, ..., status}
  function getJSON(path) {
    return GMshim.http({
      method: 'GET', url: SET.backend + path, timeout: 12000,
      headers: { 'X-AC-Token': SET.token || '' }
    }).then(function (res) {
      if (res.status === 401) {
        logLine && logLine('后端 401：令牌缺失或不正确 → 请到 ⚙ 填「访问令牌」');
      }
      var data = null;
      try { data = JSON.parse(res.text); } catch (e) { data = null; }
      if (!data || typeof data !== 'object') data = { ok: false, error: 'HTTP ' + res.status };
      data.status = res.status;
      return data;
    }).catch(function (e) {
      return { ok: false, error: String(e && e.message || e), status: 0 };
    });
  }

  // ================================================================ 填充执行
  function applyPayload(p, opts) {
    opts = opts || {};
    var filled = 0, missed = 0, skipped = 0;
    p.forEach(function (x) {
      var el = x.el || (x.selector ? document.querySelector(x.selector) : null);
      if (!el) { missed++; return; }
      // 自动重扫时跳过已有值的字段，避免覆盖用户手填内容
      if (opts.skipFilled) {
        var cur = '';
        try { cur = (el.value != null) ? String(el.value) : (el.textContent || '').trim(); } catch (e) {}
        if (cur && cur.length) { skipped++; return; }
      }
      if (x.confidence >= 0.5 && x.value && setVal(el, x.value)) filled++;
      else {
        try {
          el.style.border = '2px solid #e74c3c';
          el.setAttribute && el.setAttribute('data-ac-miss', '1');
        } catch (e) {}
        missed++;
      }
    });
    LAST_FIELDS = p;
    var msg = '扫描 ' + p.length + ' 个 → 已填 ' + filled + ' / 未命中 ' + missed +
      (skipped ? ' / 已有值跳过 ' + skipped : '');
    if (!opts.auto) {
      if (filled === 0) {
        var frN = document.querySelectorAll('iframe').length;
        var withHay = p.filter(function (x) { return (x.hay || '').length > 0; }).length;
        var sample = p.slice(0, 3).map(function (x) {
          return '"' + String(x.label || x.placeholder || x.name || x.id || '(无)').slice(0, 10) + '"'; }).join(' ');
        msg += ' ｜ 样例 ' + sample + ' ｜ 有文本 ' + withHay + '/' + p.length;
        if (frN) msg += '（检测到 ' + frN + ' 个 iframe：若为跨域则前端无法填充）';
        else msg += (withHay === 0) ? '（都不是表单字段：可能未登录）' : '（关键词没对上 → 用「④ 点选填充」）';
      } else {
        msg += '（红框：开④点选填充后点它选值）';
      }
      logLine(msg);
      dumpScan(p, filled);
    } else if (filled > 0) {
      logLine('自动填充：' + msg);
    }
    if (filled > 0 || (!opts.auto && p.length)) highlightSubmit();
  }

  function doFill(opts) {
    opts = opts || {};
    var f = scanFields();
    if (!f.length) {
      var frN = document.querySelectorAll('iframe').length;
      logLine(frN ? ('未识别到可填字段：检测到 ' + frN + ' 个 iframe（跨域 iframe 前端无法填充）')
                  : '未识别到可填字段（页面还在加载？等 2 秒再点一次）');
      return;
    }
    var p = buildPayload(f);
    applyPayload(p, opts);
  }

  // ================================================================ 提交闸门：默认只高亮，用户本人点
  function findSubmitButtons() {
    var out = [], seen = [];
    function push(el) {
      if (!el) return;
      for (var i = 0; i < seen.length; i++) if (seen[i] === el) return;
      seen.push(el); out.push(el);
    }
    allDocs().forEach(function (doc) {
      Array.prototype.slice.call(doc.querySelectorAll('input[type="submit"], button[type="submit"]')).forEach(push);
      Array.prototype.slice.call(doc.querySelectorAll('button, a, input[type="button"], [role="button"]')).forEach(function (el) {
        var t = String(el.innerText || el.textContent || el.value || '').replace(/\s+/g, '');
        if (t && t.length <= 8 && /(提交|投递|申请|submit|apply)/i.test(t) &&
            !/(取消|返回|关闭|撤销|编辑|修改|进度|记录|cancel|back|withdraw)/i.test(t)) push(el);
      });
    });
    return out.filter(function (el) { return visible(el); });
  }
  function highlightSubmit() {
    try {
      var btns = findSubmitButtons();
      btns.forEach(function (b) {
        if (b.classList) b.classList.add('ac-submit-hi');
        else b.style.outline = '3px solid #1F7A4D';
      });
      if (btns.length) {
        logLine('🔎 已高亮 ' + btns.length + ' 个疑似提交按钮（请本人确认后点击提交）');
      }
    } catch (e) {}
  }

  // ================================================================ ⑤ 挂简历：blob → File → DataTransfer → input.files
  function findFileInputs() {
    var out = [];
    allDocs().forEach(function (doc) {
      Array.prototype.slice.call(doc.querySelectorAll('input[type="file"]')).forEach(function (el) { out.push(el); });
    });
    return out;
  }
  var ATTACHED_URL = '';   // 同一 URL 只自动挂一次（v1.1.2：站点重渲染出新空上传框会造成重复上传死循环）
  function tryAutoAttach() {
    if (SET.autoAttach !== '1' || !RESUME_ID) return;
    if (ATTACHED_URL === location.href) return;       // 本页已自动挂过（成败都不再自动重试，可手动点按钮）
    // 自动挂：只挑还没挂上文件的输入框（已挂过的由用户/表单自己管理）
    var inputs = findFileInputs().filter(function (el) { return !el.files || !el.files.length; });
    if (!inputs.length) return;                       // 还没进到上传步骤，静默等待
    var pdfOnes = inputs.filter(function (el) {
      var a = (el.getAttribute('accept') || '');
      return !a || /pdf/i.test(a);
    });
    ATTACHED_URL = location.href;                     // 先占位再挂，防挂简历本身触发的变更再次进本函数
    attachResume(pdfOnes[0] || inputs[0]);
  }
  function attachResume(input) {
    if (!input) { toast('未找到文件上传框（进入填写步骤后再试）'); return; }
    logLine('⑤ 正在拉取简历附件…');
    GMshim.http({
      method: 'GET', responseType: 'blob', timeout: 30000,
      url: SET.backend + '/api/resume-file/' + encodeURIComponent(RESUME_ID || ''),
      headers: { 'X-AC-Token': SET.token || '' }
    }).then(function (res) {
      if (res.status === 401) { logLine('⑤ 后端 401：请到 ⚙ 填「访问令牌」'); throw new Error('401 需要访问令牌'); }
      if (res.status !== 200 || !res.blob) throw new Error('HTTP ' + res.status);
      var name = RESUME_NAME || ((RESUME_ID || 'resume') + '.pdf');
      if (!/\.[a-z0-9]{2,5}$/i.test(name)) name += '.pdf';
      var file;
      try { file = new File([res.blob], name, { type: 'application/pdf' }); }
      catch (e) { file = res.blob; }
      var dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      fire(input, 'change'); fire(input, 'input');
      try { input.style.outline = '2px solid #1F7A4D'; input.style.outlineOffset = '2px'; } catch (e) {}
      logLine('⑤ 简历已挂上：' + name + '（' + Math.round((file.size || 0) / 1024) + ' KB）');
      toast('简历已自动挂上：' + name);
    }).catch(function (e) {
      logLine('⑤ 自动挂简历失败（' + String(e && e.message || e) + '）→ 请手动上传');
      toast('自动挂简历失败，请手动上传');
    });
  }

  // ================================================================ 成功侦测 → 记账（GM 去重：同公司同天一次）
  function ymd(d) {
    d = d || new Date();
    function p2(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
  }
  function checkSuccess() {
    if (MARKED || !COMPANY) return;
    // Bug#6：只有本标签页里提交按钮被真实点击过才开始侦测，防 FAQ/成功案例页假记账
    if (!SUBMIT_CLICKED) return;
    var hit = SUCCESS_URL.test(location.href);
    if (!hit) {
      try { hit = SUCCESS_TEXT.test((document.body && document.body.innerText || '').slice(0, 30000)); } catch (e) {}
    }
    if (hit) markApplied('自动侦测');
  }
  function markApplied(src) {
    // 记账目标公司：优先用后端匹配到的 COMPANY；弱识别(推测)或未知时，弹窗让用户确认/修正公司名，
    // 避免误记到错误的公司（高置信的 backend/known 命中则直达，不弹窗）。
    var company = COMPANY;
    if (src === '手动' && COMPANY_SRC !== 'backend' && COMPANY_SRC !== 'known') {
      var def = COMPANY || (location.host || '').replace(/^www\./, '');
      var input = (window.prompt('请确认/修改要记账的公司名（留空=取消）：', def) || '').trim();
      if (!input) { toast('已取消记录'); return; }
      company = input;
    }
    if (!company) {
      logLine('当前页未识别到公司，无法自动记账（可在 ⚙ 或油猴菜单手动启用本站点）');
      toast('当前页未识别到公司，无法自动记账');
      return;
    }
    if (MARKED) { toast('今天已记录过：' + company); return; }
    var key = 'ac:mark:' + company + ':' + ymd();
    GMshim.get(key).then(function (v) {
      if (v) { MARKED = true; logLine('今天已记录过：' + company + '（GM 去重命中）'); toast('今天已记录过：' + company); return; }
      postJSON('/api/mark', {
        company: company, title: ROLE, role: ROLE, channel: LTYPE || '官网',
        resume_version: RESUME_ID || '', note: 'copilot:' + (src || '手动')
      }).then(function (r) {
        // Bug#3：postJSON 现在带 HTTP status；409 / detail 含"已记录过"都视为已记账并停表
        var dup = r && (r.status === 409 ||
          (r.detail && String(r.detail).indexOf('已记录过') >= 0));
        if (r && r.ok && r.status === 200) {
          MARKED = true;
          GMshim.set(key, '1');
          var now = new Date();
          var tstr = ymd(now) + ' ' + String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
          var line = '✅ 已记录：' + company + ' · ' + (r.title || ROLE || '') + ' · ' + tstr;
          logLine(line);
          toast('已记录：' + company + ' · ' + (ROLE || ''));
          if (SET.autoCloseTab === '1') setTimeout(function () { try { window.close(); } catch (e) {} }, 2500);
        } else if (dup) {
          MARKED = true; GMshim.set(key, '1');
          logLine('后端已有该公司记录（409 已记录过），视为已记账，停止重试');
        } else {
          logLine('记账失败：' + ((r && (r.detail || r.error)) || ('HTTP ' + (r && r.status || '?'))));
        }
      });
    });
  }

  // ================================================================ 记忆 / 速查 / 点选
  // 把 {key:value} 合并进内存 LEARNED，并刷新“字段记忆”面板（否则要刷新页面或点“从服务器同步”才看得到）
  function syncLearned(fields) {
    if (!fields) return;
    var changed = false;
    Object.keys(fields).forEach(function (k) {
      var v = fields[k];
      if (!k || v == null) return;
      v = String(v);
      if (LEARNED[k] !== v) { LEARNED[k] = v; changed = true; }
    });
    VALMAP = {}; VALUES.forEach(function (x) { VALMAP[x.k] = x.v; });
    if (changed && document.getElementById('ac-mem-list')) renderMemoryList();
  }
  function rememberOne(f, v) {
    var key = ruleKeyOf(f);
    if (!key || !v) return;
    var payload = {}; payload[key] = v;
    postJSON('/api/field-memory', { host: location.host, company: COMPANY,
      resume_id: RESUME_ID, fields: payload });
    syncLearned(payload);
  }
  function rememberPage() {
    var fields = scanFields(), out = {}, n = 0;
    fields.forEach(function (f) {
      var key = ruleKeyOf(f), v = '';
      try { v = (f.el.value != null) ? String(f.el.value) : ''; } catch (e) {}
      if (!v) { try { v = (f.el.textContent || '').trim(); } catch (e) {} }
      if (key && v && v.length < 500) { out[key] = v; n++; }
    });
    if (!n) { logLine('本页没有可记住的字段值（先手动填几个再点）'); return; }
    postJSON('/api/field-memory', { host: location.host, company: COMPANY,
      resume_id: RESUME_ID, fields: out }).then(function (r) {
      if (r && r.ok) { syncLearned(out); logLine('已记住 ' + n + ' 个字段（所有站点通用），累计 ' + r.total); }
      else logLine('记忆失败：' + ((r && r.error) || '未知'));
    });
  }
  function renderValues(container, onPick) {
    container.innerHTML = '';
    VALUES.forEach(function (v) {
      var b = document.createElement('button');
      b.className = 'chip';
      b.innerHTML = '<b>' + String(v.k).replace(/[<>&]/g, '') + '</b><span>' + String(v.v).replace(/[<>&]/g, '').slice(0, 18) + '</span>';
      b.onclick = function () { onPick(v.k, v.v); };
      container.appendChild(b);
    });
  }
  function copyText(t) {
    try { if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(t); return; } } catch (e) {}
    try {
      var ta = document.createElement('textarea');
      ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    } catch (e) {}
  }

  // ================================================================ 面板 UI
  function progress(w) {
    var b = document.getElementById('ac-bar');
    if (b) b.style.width = Math.max(0, Math.min(100, w)) + '%';
  }
  function status(m) { var el = document.getElementById('ac-st'); if (el) el.textContent = m; }
  function logLine(m) {
    if (SET.debug === '1') { try { console.log('[网申助手] ' + m); } catch (e) {} }
    status(m);
    var el = document.getElementById('ac-log');
    if (!el) return;
    var d = document.createElement('div');
    d.textContent = '[' + new Date().toTimeString().slice(0, 5) + '] ' + m;
    el.appendChild(d);
    while (el.children.length > 30) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
  }
  function toast(m) {
    var t = document.createElement('div'); t.textContent = m;
    t.id = 'ac-toast';   // MutationObserver 跳过自己的 toast，避免触发重扫循环
    t.style.cssText = 'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#222;color:#fff;padding:8px 14px;border-radius:9px;font-size:13px;z-index:2147483647';
    (document.body || document.documentElement).appendChild(t);
    setTimeout(function () { try { t.remove(); } catch (e) {} }, 2600);
  }
  function dumpScan(p, filled) {
    try {
      var dump = p.slice(0, 80).map(function (x) {
        return { label: (x.label || '').slice(0, 40), ph: (x.placeholder || '').slice(0, 40),
                 name: (x.name || '').slice(0, 40), id: (x.id || '').slice(0, 40),
                 type: x.type || '', hay: (x.hay || '').slice(0, 60), conf: x.confidence || 0 };
      });
      postJSON('/api/scan-dump', { url: location.href, host: location.host, company: COMPANY,
        count: p.length, filled: filled, fields: dump });
    } catch (e) {}
  }

  // 居中弹窗开关：面板与遮罩联动（点遮罩 / ✕ / Esc 都能关）
  function setPanel(open) {
    var p = document.getElementById('ac-panel');
    var m = document.getElementById('ac-panel-mask');
    if (p) p.classList.toggle('open', !!open);
    if (m) m.classList.toggle('show', !!open);
  }
  function isPanelOpen() {
    var p = document.getElementById('ac-panel');
    return !!(p && p.classList.contains('open'));
  }

  function openPanel(id) {
    var panel = document.getElementById('ac-panel');
    if (!panel) return;
    ['ac-main', 'ac-picker', 'ac-copy', 'ac-set', 'ac-resumes', 'ac-memory', 'ac-profile'].forEach(function (x) {
      var n = document.getElementById(x); if (n) n.style.display = (x === id) ? 'block' : 'none';
    });
    setPanel(true);
  }
  function openPicker(f) {
    var box = document.getElementById('ac-picker');
    if (!box) return;
    var title = f.label || f.placeholder || f.name || f.id || '该字段';
    box.innerHTML = '<div class="ph">把这个字段填成？<br><b>' + String(title).replace(/[<>&]/g, '').slice(0, 30) + '</b></div><div class="chips" id="ac-chips"></div>'
      + '<input id="ac-pick-input" placeholder="或手输一个值，回车填入" />'
      + '<button class="act ghost" id="ac-pick-back">← 返回</button>';
    var chips = box.querySelector('#ac-chips');
    renderValues(chips, function (k, v) {
      setVal(f.el, v); rememberOne(f, v);
      toast('已填「' + k + '」并记住');
      openPanel('ac-main');
    });
    box.querySelector('#ac-pick-input').onkeydown = function (e) {
      if (e.key === 'Enter') {
        var v = this.value.trim();
        if (v) { setVal(f.el, v); rememberOne(f, v); toast('已填入并记住'); openPanel('ac-main'); }
      }
    };
    box.querySelector('#ac-pick-back').onclick = function () { openPanel('ac-main'); };
    openPanel('ac-picker');
  }
  function togglePick() {
    PICK_MODE = !PICK_MODE;
    var b = document.getElementById('ac-pick');
    if (b) { b.textContent = PICK_MODE ? '④ 点选中…（点输入框）' : '④ 点选填充'; b.className = 'act' + (PICK_MODE ? ' on' : ''); }
    logLine(PICK_MODE ? '点选模式：点击页面上任意输入框 → 选值填入' : '已退出点选模式');
  }
  function openCopy() {
    var box = document.getElementById('ac-copy');
    if (!box) return;
    box.innerHTML = '<div class="ph">点一下即复制</div><div class="chips" id="ac-cchips"></div>'
      + '<button class="act ghost" id="ac-copy-back">← 返回</button>';
    renderValues(box.querySelector('#ac-cchips'), function (k, v) { copyText(v); toast('已复制「' + k + '」'); });
    box.querySelector('#ac-copy-back').onclick = function () { openPanel('ac-main'); };
    openPanel('ac-copy');
  }
  // ---- 当前身份（多租户：一个令牌 = 一份独立数据，面板上明示"你是谁"）----
  var WHOAMI = { label: '', tenant: '', multi: false };
  function fetchWhoami() {
    if (!SET.backend || !SET.token) return Promise.resolve(null);
    return GMshim.http({
      method: 'GET', timeout: 8000, url: SET.backend + '/api/whoami',
      headers: { 'X-AC-Token': SET.token || '' }
    }).then(function (r) {
      if (!r || r.status !== 200) return null;
      try {
        var d = JSON.parse(r.text);
        if (d && d.ok) {
          WHOAMI = { label: d.label || '', tenant: d.tenant || '', multi: !!d.multi_tenant };
          updateWho();
          return WHOAMI;
        }
      } catch (e) {}
      return null;
    }).catch(function () { return null; });
  }
  function updateWho() {
    var el = document.getElementById('ac-who');
    if (el) {
      el.textContent = WHOAMI.multi
        ? ('👤 ' + (WHOAMI.label || '未命名') + ' · 独立数据空间')
        : (WHOAMI.tenant ? '👤 本地单用户' : '');
    }
    var sr = document.getElementById('ac-who-set');
    if (sr) {
      sr.textContent = '当前身份：' + (WHOAMI.multi
        ? ((WHOAMI.label || '未命名') + '（' + WHOAMI.tenant + '）')
        : (WHOAMI.tenant ? '本地单用户' : '未连接（填后端地址与令牌后自动识别）'));
    }
  }

  function settingsFormHTML() {
    function chk(id, label, val) {
      return '<label class="srow"><input type="checkbox" id="' + id + '"' + (val === '1' ? ' checked' : '') + '> ' + label + '</label>';
    }
    return chk('set-fill', '页面加载自动填表', SET.autoFill)
      + chk('set-attach', '自动挂简历（找到 pdf 上传框就挂）', SET.autoAttach)
      + chk('set-close', '记账成功后自动关标签页', SET.autoCloseTab)
      + chk('set-pick', '点选填充模式（默认开，点输入框即弹选值）', SET.pickMode)
      + chk('set-debug', '调试日志（控制台输出运行信息）', SET.debug)
      + '<label class="srow">后端地址 <input id="set-backend" value="' + String(SET.backend).replace(/"/g, '&quot;') + '"></label>'
      + '<label class="srow">访问令牌 <input id="set-token" type="password" value="' + String(SET.token || '').replace(/"/g, '&quot;') + '"></label>'
      + '<div class="srow" id="ac-who-set" style="opacity:.8"></div>';
  }
  function bindSettingsSave(box, onDone) {
    box.querySelector('#set-save').onclick = function () {
      SET.autoFill = box.querySelector('#set-fill').checked ? '1' : '0';
      SET.autoAttach = box.querySelector('#set-attach').checked ? '1' : '0';
      SET.autoCloseTab = box.querySelector('#set-close').checked ? '1' : '0';
      SET.pickMode = box.querySelector('#set-pick').checked ? '1' : '0';
      SET.debug = box.querySelector('#set-debug').checked ? '1' : '0';
      var bk = box.querySelector('#set-backend').value.trim();
      if (!safeBackend(bk)) { toast('远程后端必须使用 HTTPS'); return Promise.resolve(); }
      SET.backend = bk.replace(/\/$/, '');
      SET.token = box.querySelector('#set-token').value.trim();
      return Promise.all([
        GMshim.set('ac:backend', SET.backend), GMshim.set('ac:token', SET.token),
        GMshim.set('ac:autoFill', SET.autoFill),
        GMshim.set('ac:autoAttach', SET.autoAttach), GMshim.set('ac:autoSubmit', '0'),
        GMshim.set('ac:autoCloseTab', SET.autoCloseTab),
        GMshim.set('ac:pickMode', SET.pickMode), GMshim.set('ac:debug', SET.debug)
      ]).then(function () {
        toast('设置已保存');
        logLine('⚙ 设置已保存；最终提交始终由本人执行');
        // 令牌可能刚换过：重新确认身份（谁的令牌就进谁的数据空间）
        fetchWhoami().then(function (w) {
          if (w && w.multi) logLine('👤 当前身份：' + (w.label || '未命名') + '（独立数据空间）');
          if (onDone) onDone();
        });
      });
    };
  }
  function openSettings() {
    var box = document.getElementById('ac-set');
    if (!box) return;
    box.innerHTML = '<div class="ph">⚙ 设置（存 GM，跨站生效）</div>' + settingsFormHTML()
      + '<button class="act" id="set-save">保存设置</button>'
      + '<button class="act ghost" id="set-back">← 返回</button>';
    bindSettingsSave(box, function () { openPanel('ac-main'); });
    box.querySelector('#set-back').onclick = function () { openPanel('ac-main'); };
    updateWho(); fetchWhoami();
    openPanel('ac-set');
  }
  // 任意页面可用的独立设置卡：不依赖悬浮面板（登录页 / 未启用站点也能打开）
  function openSettingsCard() {
    if (document.getElementById('ac-setup')) return;
    if (!document.getElementById('ac-setup-st')) {
      var st = document.createElement('style'); st.id = 'ac-setup-st';
      st.textContent = '#ac-setup{position:fixed;right:14px;bottom:14px;z-index:2147483647;width:360px;background:#fff;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.25);padding:12px;color:#1f2329;font-family:-apple-system,"PingFang SC",sans-serif}'
        + '#ac-setup .ph{font-size:12px;color:#5f6368;margin-bottom:8px;line-height:1.5}#ac-setup .ph b{color:#185FA5}'
        + '#ac-setup .srow{display:flex;align-items:center;gap:6px;font-size:12px;margin:6px 0;color:#333}'
        + '#ac-setup .srow input[type=text],#ac-setup #set-backend{flex:1;min-width:0;padding:5px 7px;border:1px solid #d7dce3;border-radius:6px;font-size:11.5px}'
        + '#ac-setup button.act{display:block;width:100%;margin:5px 0;background:#185FA5;color:#fff;border:none;border-radius:8px;padding:9px;font-size:13px;font-weight:600;cursor:pointer}'
        + '#ac-setup button.act.ghost{background:#eef1f5;color:#1f2329}';
      (document.head || document.documentElement).appendChild(st);
    }
    var card = document.createElement('div'); card.id = 'ac-setup';
    card.innerHTML = '<div class="ph"><b>⚙ 网申助手 · 设置</b>（存 GM，跨站生效）</div>' + settingsFormHTML()
      + '<button class="act" id="set-save">保存设置</button>'
      + '<button class="act ghost" id="ac-setup-close">关闭</button>';
    (document.body || document.documentElement).appendChild(card);
    bindSettingsSave(card, function () { try { card.remove(); } catch (e) {} });
    card.querySelector('#ac-setup-close').onclick = function () { try { card.remove(); } catch (e) {} };
  }
  // 全局菜单：任何页面（含登录页/未启用站点）都能从油猴图标进入
  function registerGlobalMenu() {
    if (typeof GM_registerMenuCommand !== 'function') return;
    try { GM_registerMenuCommand('⚙ 网申助手设置', openSettingsCard); } catch (e) {}
    try { GM_registerMenuCommand('在此站点启用助手', function () {
      GMshim.set('ac:enabled:' + location.host, '1').then(function () { location.reload(); });
    }); } catch (e) {}
    try { GM_registerMenuCommand('打开仪表板', function () {
      var u = SET.backend + '/';
      // v1.1.2：永远新标签页、不劫持当前页。GM_openInTab 不受浏览器弹窗拦截限制，优先用。
      try { if (typeof GM_openInTab === 'function') { GM_openInTab(u, { active: true }); return; } } catch (e) {}
      var w = null;
      try { w = window.open(u, '_blank'); } catch (e) {}
      if (!w) { try { copyText(u); } catch (e2) {} toast('弹窗被拦截，仪表板地址已复制，请粘贴到新标签页打开：' + u); }
    }); } catch (e) {}
  }
  // 首次使用（后端/令牌未配置）只自动弹一次设置卡，之后从油猴菜单进
  function maybeFirstRun() {
    if (SET.backend && SET.token) return;
    GMshim.get('ac:setupHint').then(function (v) {
      if (!v) { GMshim.set('ac:setupHint', '1'); openSettingsCard(); }
    });
  }

  // ================================================================ 自助管理面板（简历 / 字段记忆 / 档案）
  // 纯原生 DOM，无框架；所有数据走 /api/*（复用 X-AC-Token 鉴权）。

  // ---------------------------------------------------------- ① 简历管理
  function openResumes() {
    var box = document.getElementById('ac-resumes');
    if (!box) return;
    box.innerHTML = '<div class="ph">📄 简历管理（存在你自己的后端）</div>'
      + '<div class="drop" id="ac-drop">把 PDF / 图片 拖到这里，或 <b>点击选择文件</b></div>'
      + '<input type="file" id="ac-file" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" style="display:none">'
      + '<div class="ph" id="ac-res-status"></div>'
      + '<div class="list" id="ac-res-list">加载中…</div>'
      + '<button class="act ghost" id="ac-res-back">← 返回</button>';
    var drop = box.querySelector('#ac-drop');
    var fileInput = box.querySelector('#ac-file');
    drop.onclick = function () { fileInput.click(); };
    fileInput.onchange = function () {
      if (fileInput.files && fileInput.files[0]) uploadResumeFile(fileInput.files[0]);
    };
    ['dragenter', 'dragover'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); });
    });
    drop.addEventListener('drop', function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) uploadResumeFile(f);
    });
    box.querySelector('#ac-res-back').onclick = function () { openPanel('ac-main'); };
    openPanel('ac-resumes');
    refreshResumes();
  }
  function uploadResumeFile(file) {
    var st = document.getElementById('ac-res-status');
    if (st) st.textContent = '上传中：' + file.name + ' …';
    if (SET.debug === '1') console.log('[网申助手] 上传简历', file.name, file.size);
    GMshim.upload('/api/resume', file).then(function (res) {
      if (res.status === 401) { if (st) st.textContent = '后端 401：请到 ⚙ 填「访问令牌」'; return; }
      var data = null; try { data = JSON.parse(res.text); } catch (e) {}
      if (data && data.ok) {
        if (st) st.textContent = '✅ 已上传：' + file.name;
        toast('简历已上传：' + file.name);
        refreshResumes();
      } else {
        if (st) st.textContent = '上传失败：' + ((data && data.error) || ('HTTP ' + res.status));
      }
    }).catch(function (e) {
      if (st) st.textContent = '上传失败：' + String(e && e.message || e);
    });
  }
  function refreshResumes() {
    var list = document.getElementById('ac-res-list');
    if (!list) return;
    getJSON('/api/resumes').then(function (r) {
      if (!r || r.status !== 200 || !r.resumes) {
        list.innerHTML = '<div class="ph">无法获取简历列表（' + ((r && r.error) || ('HTTP ' + (r && r.status))) + '）</div>';
        return;
      }
      getJSON('/api/resume/active').then(function (a) {
        var active = (a && a.active) || '';
        if (!r.resumes.length) { list.innerHTML = '<div class="ph">还没有简历，拖一个上来吧。</div>'; return; }
        list.innerHTML = '';
        r.resumes.forEach(function (res) {
          var item = document.createElement('div');
          item.className = 'ritem' + (res.id === active ? ' active' : '');
          var name = String(res.name || res.filename || res.id).replace(/[<>&]/g, '');
          var tagTxt = (res.tags && res.tags.length) ? (' · ' + res.tags.join(',')) : '';
          item.innerHTML = '<b>' + name + (res.id === active ? ' ✅' : '') + '</b>'
            + '<span class="tag">' + String(res.filename || '').replace(/[<>&]/g, '') + tagTxt + '</span>';
          var actBtn = document.createElement('button');
          actBtn.className = 'actv'; actBtn.textContent = '设为默认';
          actBtn.onclick = function () {
            postJSON('/api/resume/active', { active: res.id }).then(function (x) {
              if (x && x.ok) { toast('已设为默认简历'); refreshResumes(); }
              else { toast('失败：' + ((x && (x.error || x.detail)) || '')); }
            });
          };
          var delBtn = document.createElement('button');
          delBtn.className = 'del'; delBtn.textContent = '删除';
          delBtn.onclick = function () {
            if (!window.confirm('确定删除「' + name + '」？此操作不可恢复')) return;
            GMshim.http({ method: 'DELETE', url: SET.backend + '/api/resume/' + encodeURIComponent(res.id),
              timeout: 12000, headers: { 'X-AC-Token': SET.token || '' } }).then(function (dr) {
              var dd = null; try { dd = JSON.parse(dr.text); } catch (e) {}
              if (dr.status === 200 || (dd && dd.ok)) { toast('已删除'); refreshResumes(); }
              else { toast('删除失败：' + ((dd && dd.error) || ('HTTP ' + dr.status))); }
            });
          };
          item.appendChild(actBtn); item.appendChild(delBtn);
          list.appendChild(item);
        });
      });
    });
  }

  // ---------------------------------------------------------- ② 字段记忆管理
  function openMemory() {
    var box = document.getElementById('ac-memory');
    if (!box) return;
    box.innerHTML = '<div class="ph">🧠 字段记忆（下次自动填，所有站点通用）</div>'
      + '<div class="list" id="ac-mem-list">加载中…</div>'
      + '<button class="act" id="ac-mem-sync">⇩ 从服务器同步</button>'
      + '<button class="act ghost" id="ac-mem-back">← 返回</button>';
    box.querySelector('#ac-mem-sync').onclick = function () { syncFieldMemory(); };
    box.querySelector('#ac-mem-back').onclick = function () { openPanel('ac-main'); };
    openPanel('ac-memory');
    renderMemoryList();
  }
  function renderMemoryList() {
    var list = document.getElementById('ac-mem-list');
    if (!list) return;
    var keys = Object.keys(LEARNED || {});
    if (!keys.length) {
      list.innerHTML = '<div class="ph">还没有记住的字段。在填写页点「③ 记住本页字段」即可沉淀。</div>';
      return;
    }
    list.innerHTML = '';
    keys.forEach(function (k) {
      var item = document.createElement('div'); item.className = 'ritem';
      item.innerHTML = '<b>' + String(k).replace(/[<>&]/g, '') + '</b>'
        + '<span class="tag">' + String(LEARNED[k] || '').replace(/[<>&]/g, '').slice(0, 40) + '</span>';
      var del = document.createElement('button'); del.className = 'del'; del.textContent = '删除';
      del.onclick = function () { deleteFieldMemory(k); };
      item.appendChild(del); list.appendChild(item);
    });
  }
  function deleteFieldMemory(key) {
    GMshim.http({ method: 'DELETE', url: SET.backend + '/api/field-memory/' + encodeURIComponent(key),
      timeout: 12000, headers: { 'X-AC-Token': SET.token || '' } }).then(function (dr) {
      var dd = null; try { dd = JSON.parse(dr.text); } catch (e) {}
      if (dr.status === 200 || (dd && dd.ok)) {
        delete LEARNED[key]; renderMemoryList(); toast('已删除记忆：' + key);
      } else { toast('删除失败：' + ((dd && dd.error) || ('HTTP ' + dr.status))); }
    });
  }
  function syncFieldMemory() {
    getJSON('/api/field-memory').then(function (r) {
      if (r && r.status === 200 && r.fields) {
        LEARNED = r.fields || {};
        VALMAP = {}; VALUES.forEach(function (x) { VALMAP[x.k] = x.v; });
        renderMemoryList();
        toast('已从服务器同步 ' + Object.keys(LEARNED).length + ' 条记忆');
        logLine('⇩ 已同步字段记忆 ' + Object.keys(LEARNED).length + ' 条');
      } else {
        toast('同步失败：' + ((r && r.error) || ('HTTP ' + (r && r.status))));
      }
    });
  }

  // ---------------------------------------------------------- ③ 档案编辑
  function openProfile() {
    var box = document.getElementById('ac-profile');
    if (!box) return;
    box.innerHTML = '<div class="ph">👤 编辑档案（存你自己的后端 profile）</div>'
      + '<textarea id="ac-prof-ta" placeholder="加载中…"></textarea>'
      + '<div class="ph" id="ac-prof-st"></div>'
      + '<button class="act" id="ac-prof-save">保存档案</button>'
      + '<button class="act ghost" id="ac-prof-back">← 返回</button>';
    var ta = box.querySelector('#ac-prof-ta');
    var st = box.querySelector('#ac-prof-st');
    getJSON('/api/profile').then(function (r) {
      if (r && r.status === 200 && r.profile) { ta.value = JSON.stringify(r.profile, null, 2); }
      else if (r && r.status === 401) { ta.value = ''; st.textContent = '后端 401：请到 ⚙ 填「访问令牌」'; }
      else { ta.value = '{}'; st.textContent = '无法获取档案：' + ((r && r.error) || ('HTTP ' + (r && r.status))); }
    });
    box.querySelector('#ac-prof-save').onclick = function () {
      var txt = ta.value, obj;
      try { obj = JSON.parse(txt); } catch (e) { st.textContent = 'JSON 解析失败：' + e.message; return; }
      if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) { st.textContent = '档案必须是 JSON 对象'; return; }
      st.textContent = '保存中…';
      postJSON('/api/profile', obj).then(function (x) {
        if (x && x.ok) { st.textContent = '✅ 已保存档案'; toast('档案已更新'); }
        else { st.textContent = '保存失败：' + ((x && (x.error || x.detail)) || ('HTTP ' + (x && x.status))); }
      });
    };
    box.querySelector('#ac-prof-back').onclick = function () { openPanel('ac-main'); };
    openPanel('ac-profile');
  }

  // ---------------------------------------------------------- 首次使用：欢迎 / 隐私说明（仅弹一次）
  function showWelcome() {
    GMshim.get('ac:welcomed').then(function (v) {
      if (v) return;
      var mask = document.createElement('div'); mask.id = 'ac-modal-mask';
      mask.innerHTML = '<div id="ac-modal">'
        + '<h3>🛠️ 网申助手 Copilot</h3>'
        + '<p>这是一个 <b>自动填表 + 自动挂简历</b> 的浏览器助手，帮你在各厂官网网申时一键填好个人信息、挂上简历、记录投递。</p>'
        + '<p><b>隐私说明：</b>你的简历、档案、字段记忆都只存在你<b>自己部署的后端</b>上，不会上传任何第三方。请妥善保管后端地址与访问令牌。</p>'
        + '<p style="color:#9aa3af">红线：绝不代登录、绝不碰验证码；自动提交默认关闭，需本人点击提交。</p>'
        + '<button class="act" id="ac-welcome-ok">我已知晓，开始使用</button></div>';
      (document.body || document.documentElement).appendChild(mask);
      mask.querySelector('#ac-welcome-ok').onclick = function () {
        GMshim.set('ac:welcomed', '1'); try { mask.remove(); } catch (e) {}
      };
    });
  }

  function inject() {
    if (document.getElementById('ac-fab')) return;
    var css = '#ac-fab{position:fixed;right:14px;bottom:14px;width:46px;height:46px;z-index:2147483647;pointer-events:none;font-family:-apple-system,"PingFang SC",sans-serif}'
      + '#ac-fab .fab{pointer-events:auto;width:46px;height:46px;border-radius:50%;background:#185FA5;color:#fff;border:none;font-size:22px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.3)}'
      + '#ac-fab .ac-mask{pointer-events:auto;display:none;position:fixed;inset:0;background:rgba(15,23,42,.42);z-index:2147483646}'
      + '#ac-fab .ac-mask.show{display:block}'
      + '#ac-fab .panel{pointer-events:auto;display:none;position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:400px;max-width:92vw;max-height:82vh;overflow-y:auto;background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.28);padding:0;color:#1f2329;z-index:2147483647}'
      + '#ac-fab .ac-hd{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #eef1f5;background:#fff;border-radius:14px 14px 0 0}'
      + '#ac-fab .ac-hd-t{font-size:14px;font-weight:700;color:#1f2329}'
      + '#ac-fab .ac-who{font-size:11px;color:#8a94a6;margin-top:2px;max-width:210px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
      + '#ac-fab .ac-x{width:26px;height:26px;border:none;background:#f2f5f9;color:#5f6368;border-radius:50%;font-size:13px;cursor:pointer;line-height:1}'
      + '#ac-fab .ac-x:hover{background:#e6ebf2;color:#1f2329}'
      + '#ac-fab .ac-bd{padding:12px 14px 14px}'
      + '#ac-fab .panel.open{display:block}'
      + '#ac-fab button.act{display:block;width:100%;margin:6px 0;background:#185FA5;color:#fff;border:none;border-radius:8px;padding:11px;font-size:14px;font-weight:600;cursor:pointer}'
      + '#ac-fab button.act.on{background:#C2410C}'
      + '#ac-fab button.act.rec{background:#1F7A4D}'
      + '#ac-fab button.act.ghost{background:#eef1f5;color:#1f2329}'
      + '#ac-fab .st{font-size:11.5px;color:#5f6368;margin-top:6px;line-height:1.5}'
      + '#ac-fab .meta{font-size:11px;color:#888;margin-bottom:4px}'
      + '#ac-fab .ph{font-size:12px;color:#5f6368;margin-bottom:8px;line-height:1.5}'
      + '#ac-fab .ph b{color:#185FA5}'
      + '#ac-fab .chips{max-height:340px;overflow:auto;margin-bottom:6px}'
      + '#ac-fab .chip{display:block;width:100%;text-align:left;margin:3px 0;padding:6px 8px;border:1px solid #e3e8ef;background:#fff;border-radius:7px;cursor:pointer;font-size:13px;line-height:1.4}'
      + '#ac-fab .chip:hover{border-color:#185FA5;background:#f2f7fd}'
      + '#ac-fab .chip b{color:#185FA5;margin-right:6px}'
      + '#ac-fab .chip span{color:#5f6368}'
      + '#ac-fab input#ac-pick-input{width:100%;box-sizing:border-box;padding:7px 8px;border:1px solid #d7dce3;border-radius:7px;font-size:12px;margin-top:4px}'
      + '#ac-fab #ac-log{max-height:150px;overflow:auto;font-size:11.5px;color:#444;background:#f7f9fc;border-radius:7px;padding:6px;margin-top:6px;line-height:1.5}'
      + '#ac-fab .srow{display:flex;align-items:center;gap:6px;font-size:12px;margin:6px 0;color:#333}'
      + '#ac-fab .srow input[type=text],#ac-fab #set-backend{flex:1;min-width:0;padding:5px 7px;border:1px solid #d7dce3;border-radius:6px;font-size:11.5px}'
      + '#ac-fab .pw{height:5px;background:#eef1f5;border-radius:3px;overflow:hidden;margin:6px 0}'
      + '#ac-fab #ac-bar{height:100%;width:0;background:#185FA5;transition:width .18s}'
      + '.ac-submit-hi{outline:3px solid #1F7A4D !important;outline-offset:2px;box-shadow:0 0 0 5px rgba(31,122,77,.22) !important;}'
      + '#ac-fab .list{font-size:13px;max-height:340px;overflow:auto;margin-top:4px}'
      + '#ac-fab .ritem{display:flex;align-items:center;gap:6px;padding:6px 7px;border:1px solid #e3e8ef;border-radius:7px;margin:5px 0;background:#fff}'
      + '#ac-fab .ritem b{flex:1;color:#1f2329;font-weight:600;word-break:break-all}'
      + '#ac-fab .ritem .tag{font-size:10px;color:#5f6368;max-width:42%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
      + '#ac-fab .ritem.active{border-color:#1F7A4D;background:#f0faf3}'
      + '#ac-fab .ritem button{font-size:11px;padding:4px 7px;border:none;border-radius:6px;cursor:pointer;color:#fff;white-space:nowrap}'
      + '#ac-fab .ritem .del{background:#e74c3c}'
      + '#ac-fab .ritem .actv{background:#1F7A4D}'
      + '#ac-fab .drop{border:2px dashed #b9c2cf;border-radius:9px;padding:14px;text-align:center;color:#5f6368;font-size:12px;margin:6px 0;cursor:pointer}'
      + '#ac-fab .drop.over{background:#eef7ff;border-color:#185FA5;color:#185FA5}'
      + '#ac-fab textarea#ac-prof-ta{width:100%;height:220px;box-sizing:border-box;font-family:monospace;font-size:11px;padding:6px;border:1px solid #d7dce3;border-radius:6px;resize:vertical}'
      + '#ac-modal-mask{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2147483646;display:none;align-items:center;justify-content:center;font-family:-apple-system,"PingFang SC",sans-serif}'
      + '#ac-modal{width:340px;max-width:92vw;background:#fff;border-radius:14px;padding:18px;color:#1f2329;font-size:13px;line-height:1.7;box-shadow:0 10px 40px rgba(0,0,0,.3)}'
      + '#ac-modal h3{margin:0 0 8px;font-size:16px}'
      + '#ac-modal p{color:#5f6368;margin:8px 0}'
      + '#ac-modal b{color:#185FA5}'
      + '#ac-modal .act{display:block;width:100%;margin-top:10px;background:#185FA5;color:#fff;border:none;border-radius:8px;padding:9px;font-size:13px;font-weight:600;cursor:pointer}';
    var stl = document.createElement('style'); stl.textContent = css;
    (document.head || document.documentElement).appendChild(stl);

    var root = document.createElement('div'); root.id = 'ac-fab';
    root.innerHTML = '<div class="ac-mask" id="ac-panel-mask"></div>'
      + '<div class="panel" id="ac-panel">'
      + '<div class="ac-hd"><div style="min-width:0"><span class="ac-hd-t">🛠 网申助手 Copilot</span>'
      + '<div class="ac-who" id="ac-who"></div></div>'
      + '<button class="ac-x" id="ac-close" title="关闭（Esc）">✕</button></div>'
      + '<div class="ac-bd">'
      + '<div class="meta" id="ac-meta"></div>'
      + '<div class="pw"><div id="ac-bar"></div></div>'
      + '<div id="ac-main">'
      +   '<button class="act" id="ac-fill">① 填充表单</button>'
      +   '<button class="act" id="ac-attach">② 挂简历附件</button>'
      +   '<button class="act" id="ac-pick">③ 点选填充</button>'
      +   '<button class="act" id="ac-remember">④ 记住本页字段</button>'
      +   '<button class="act ghost" id="ac-copybtn">📋 档案速查（复制）</button>'
      +   '<button class="act" id="ac-resbtn">📄 简历管理</button>'
      +   '<button class="act" id="ac-membtn">🧠 字段记忆</button>'
      +   '<button class="act" id="ac-profbtn">👤 编辑档案</button>'
      +   '<button class="act ghost" id="ac-setbtn">⚙ 设置</button>'
      +   '<button class="act rec" id="ac-record">⑤ 记录已投</button>'
      + '</div>'
      + '<div id="ac-picker" style="display:none"></div>'
      + '<div id="ac-copy" style="display:none"></div>'
      + '<div id="ac-set" style="display:none"></div>'
      + '<div id="ac-resumes" style="display:none"></div>'
      + '<div id="ac-memory" style="display:none"></div>'
      + '<div id="ac-profile" style="display:none"></div>'
      + '<div id="ac-log"></div>'
      + '<div class="st" id="ac-st"></div></div></div>'
      + '<button class="fab" id="ac-toggle" title="网申助手 Copilot（可拖动）">🛠</button>';
    (document.body || document.documentElement).appendChild(root);

    var meta = root.querySelector('#ac-meta');
    meta.textContent = (RESUME_NAME ? ('简历: ' + RESUME_NAME) : '') + (COMPANY ? (' · ' + COMPANY) : '')
      + (ROLE ? (' · ' + ROLE) : '');
    var tag = COMPANY
      ? (COMPANY_SRC === 'backend' ? ('命中 ' + COMPANY + (CTX && CTX.match_kind ? ('（' + CTX.match_kind + '）') : ''))
         : ('自动识别 ' + COMPANY + '（' + (COMPANY_SRC === 'known' ? '已知' : '推测') + '）'))
      : '未识别公司（手动启用）';
    logLine('已启用：' + tag);

    // 可拖动浮标：>4px 位移算拖动并吞掉该次 click
    var fabBtn = root.querySelector('#ac-toggle');
    var drag = null, moved = false;
    fabBtn.addEventListener('mousedown', function (e) {
      drag = { x: e.clientX, y: e.clientY, r: root.getBoundingClientRect() };
      moved = false; e.preventDefault();
    });
    document.addEventListener('mousemove', function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) moved = true;
      root.style.right = 'auto'; root.style.bottom = 'auto';
      root.style.left = Math.max(0, drag.r.left + dx) + 'px';
      root.style.top = Math.max(0, drag.r.top + dy) + 'px';
    });
    document.addEventListener('mouseup', function () { drag = null; });
    fabBtn.addEventListener('click', function (e) {
      if (moved) { e.stopImmediatePropagation(); moved = false; return; }
      setPanel(!isPanelOpen());
    });
    // 点遮罩关闭 / ✕ 关闭 / Esc 关闭
    var maskEl = root.querySelector('#ac-panel-mask');
    if (maskEl) maskEl.addEventListener('click', function () { setPanel(false); });
    var closeEl = root.querySelector('#ac-close');
    if (closeEl) closeEl.onclick = function () { setPanel(false); };
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') setPanel(false); });

    root.querySelector('#ac-fill').onclick = function () { progress(10); doFill({ auto: false }); progress(100); };
    root.querySelector('#ac-attach').onclick = function () {
      var inputs = findFileInputs();
      if (!inputs.length) { toast('未找到文件上传框（进入填写步骤后再试）'); logLine('⑤ 页面上没有 file input'); return; }
      var pdfOnes = inputs.filter(function (el) { var a = (el.getAttribute('accept') || ''); return !a || /pdf/i.test(a); });
      attachResume(pdfOnes[0] || inputs[0]);
    };
    root.querySelector('#ac-pick').onclick = togglePick;
    // 初始点选态跟随设置（SET.pickMode 默认开）
    PICK_MODE = SET.pickMode === '1';
    var pickBtn = root.querySelector('#ac-pick');
    if (PICK_MODE) { pickBtn.textContent = '④ 点选中…（点输入框）'; pickBtn.className = 'act on'; }
    root.querySelector('#ac-remember').onclick = rememberPage;
    root.querySelector('#ac-copybtn').onclick = openCopy;
    root.querySelector('#ac-resbtn').onclick = openResumes;
    root.querySelector('#ac-membtn').onclick = openMemory;
    root.querySelector('#ac-profbtn').onclick = openProfile;
    root.querySelector('#ac-setbtn').onclick = openSettings;
    root.querySelector('#ac-record').onclick = function () { markApplied('手动'); };

    // 点选模式：点击页面任意输入框 → 弹出选值
    document.addEventListener('click', function (e) {
      if (!PICK_MODE) return;
      var t = e.target;
      if (t && t.closest && t.closest('#ac-fab')) return;
      var el = (t && t.closest) ? t.closest('input,select,textarea,[contenteditable="true"],[role="textbox"]') : null;
      if (!el) return;
      e.preventDefault(); e.stopPropagation();
      PICK_MODE = false;
      var b = document.getElementById('ac-pick');
      if (b) { b.textContent = '④ 点选填充'; b.className = 'act'; }
      openPicker(describe(el));
    }, true);
  }

  // ================================================================ SPA 导航 + DOM 变更 → 防抖重扫
  // 捕获阶段监听全页点击，识别用户点击的提交类按钮。
  document.addEventListener('click', function (e) {
    try {
      var t = e.target;
      if (!t || !t.closest) return;
      var el = t.closest('button, input[type="submit"], input[type="button"], [role="button"], a');
      if (!el || (el.closest && el.closest('#ac-fab'))) return;
      var isSubmit = (el.type === 'submit') || (el.classList && el.classList.contains('ac-submit-hi'));
      if (!isSubmit) {
        var txt = String(el.innerText || el.textContent || el.value || '').replace(/\s+/g, '');
        isSubmit = !!txt && txt.length <= 8 && /(提交|投递|申请|submit|apply)/i.test(txt) &&
          !/(取消|返回|关闭|撤销|编辑|修改|进度|记录|cancel|back|withdraw)/i.test(txt);
      }
      if (isSubmit) SUBMIT_CLICKED = true;
    } catch (e2) {}
  }, true);
  var FILL_URL = '', FILL_TRIES = 0;   // v1.1.2：同一 URL 最多自动填 3 次（防站点组件重置字段造成的死循环）
  function onNav() {
    clearTimeout(RESCAN_T);
    RESCAN_T = setTimeout(function () {
      if (SET.autoFill !== '1') return;
      if (FILL_URL !== location.href) { FILL_URL = location.href; FILL_TRIES = 0; }
      if (FILL_TRIES >= 3) return;
      FILL_TRIES++;
      // skipFilled：重扫绝不覆盖用户手填/已填的值（Bug#2）
      doFill({ auto: true, skipFilled: true });
      tryAutoAttach();
    }, 1000);
  }
  function hookSpa() {
    try {
      var ps = history.pushState, rs = history.replaceState;
      history.pushState = function () { var r = ps.apply(this, arguments); onNav(); return r; };
      history.replaceState = function () { var r = rs.apply(this, arguments); onNav(); return r; };
      window.addEventListener('popstate', onNav);
    } catch (e) {}
    try {
      var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var m = muts[i];
          var tg = m.target;
          // 忽略自己面板/浮层引起的变更，避免自我触发重扫循环
          if (tg && (tg.id === 'ac-fab' || (tg.closest && tg.closest('#ac-fab')))) continue;
          var own = false;
          if (m.addedNodes && m.addedNodes.length) {
            for (var k = 0; k < m.addedNodes.length; k++) {
              var nd = m.addedNodes[k];
              if (nd && nd.nodeType === 1 &&
                  (nd.id === 'ac-toast' || nd.id === 'ac-fab' ||
                   (nd.closest && (nd.closest('#ac-fab') || nd.closest('#ac-toast'))))) { own = true; break; }
            }
          }
          if (own) continue;
          if (m.addedNodes && m.addedNodes.length) { onNav(); break; }
        }
      });
      mo.observe(document.documentElement || document, { childList: true, subtree: true });
    } catch (e) {}
  }

  // ================================================================ 开机流程
  function isManualEnabled() {
    return GMshim.get('ac:enabled:' + location.host).then(function (v) { return !!v; });
  }
  function loadSettings() {
    return Promise.all([
      GMshim.get('ac:backend'), GMshim.get('ac:autoFill'), GMshim.get('ac:autoAttach'),
      GMshim.get('ac:autoCloseTab'), GMshim.get('ac:token'),
      GMshim.get('ac:pickMode'), GMshim.get('ac:debug')
    ]).then(function (r) {
      if (r[0] && safeBackend(r[0])) SET.backend = r[0];
      if (r[1]) SET.autoFill = r[1];
      if (r[2]) SET.autoAttach = r[2];
      if (r[3]) SET.autoCloseTab = r[3];
      SET.token = r[4] || '';
      if (r[5]) SET.pickMode = r[5];
      if (r[6]) SET.debug = r[6];
    });
  }
  // 后端完全不可达时的兜底：仅当用户手动启用过该站点才注入空上下文（Bug#5：
  // context 请求成功的情况在 boot 里保留已拉到的全局数据，不走这里清空）
  function maybeManual() {
    isManualEnabled().then(function (on) {
      if (!on) return;   // 普通网页：什么都不注入
      RULES = []; VALUES = []; SYN = []; LEARNED = {};
      init();
    });
  }
  function init() {
    VALMAP = {};
    VALUES.forEach(function (x) { VALMAP[x.k] = x.v; });
    // 未知站点后端没给 resume_id：拉一次默认简历，保证"② 挂简历附件"在所有站点都能用
    if (!RESUME_ID) {
      getJSON('/api/resume/active').then(function (a) {
        if (a && a.active) { RESUME_ID = a.active; RESUME_NAME = a.name || ''; }
      });
    }
    inject();
    // 油猴菜单（仅注册依赖站点上下文的项；全局菜单在 boot 里注册）
    if (typeof GM_registerMenuCommand === 'function') {
      try { GM_registerMenuCommand('重置本页今天的记账去重', function () {
        GMshim.set('ac:mark:' + COMPANY + ':' + ymd(), '').then(function () { MARKED = false; toast('已重置，可重新记账'); });
      }); } catch (e) {}
    }
    // 自动填表 + 自动挂简历（页面首次就绪后延迟执行）
    if (SET.autoFill === '1') setTimeout(function () { doFill({ auto: true }); }, 1500);
    if (SET.autoAttach === '1' && RESUME_ID) setTimeout(tryAutoAttach, 2500);
    hookSpa();
    // 成功侦测轮询（轻量：3s 一次，命中即记账并停止）
    SUCCESS_T = setInterval(checkSuccess, 3000);
    setTimeout(function () { clearInterval(SUCCESS_T); }, 10 * 60 * 1000);  // 10 分钟后停止轮询
  }
  function buildSyn(list) {
    return (list || []).map(function (x) {
      try { return [new RegExp(x.re, 'i'), x.name]; }
      catch (e) { return [new RegExp('x'), x.name]; }
    });
  }
  // ================================================================ 公司自动识别（免逐站手动启用）
  // 后端没命中公司时，尽力从页面识别：① 已知招聘域名映射 ② 标题含招聘关键词则提炼品牌名。
  // 返回 {name, src}：src='known' 表示高置信（已知域名），src='guess' 表示标题推测（记账前会让用户确认）。
  function detectCompany() {
    try {
      var host = (location.host || '').toLowerCase().replace(/^www\./, '').split(':')[0];
      // 已知招聘官网（根域 / 招聘子域）→ 公司名。覆盖常见 2026 秋招大厂，命中即高置信。
      var KNOWN = {
        'huawei.com': '华为', 'career.huawei.com': '华为',
        'bytedance.com': '字节跳动', 'bytedancejobs.com': '字节跳动', 'job.toutiao.com': '字节跳动', 'jobs.bytedance.com': '字节跳动',
        'tencent.com': '腾讯', 'join.qq.com': '腾讯', 'careers.tencent.com': '腾讯', 'join.tencent.com': '腾讯',
        'alibaba.com': '阿里巴巴', 'alibaba-inc.com': '阿里巴巴', 'talent.alibaba.com': '阿里巴巴',
        'baidu.com': '百度', 'talent.baidu.com': '百度',
        'jd.com': '京东', 'zhaopin.jd.com': '京东',
        'meituan.com': '美团', 'zhaopin.meituan.com': '美团',
        'xiaomi.com': '小米', 'hr.xiaomi.com': '小米', 'job.xiaomi.com': '小米',
        'didiglobal.com': '滴滴', 'didi.com': '滴滴',
        'kuaishou.com': '快手', 'zhiyan.mokahr.com': '快手',
        'netease.com': '网易', 'hr.netease.com': '网易', 'campus.163.com': '网易',
        'bilibili.com': '哔哩哔哩', 'jobs.bilibili.com': '哔哩哔哩',
        'antgroup.com': '蚂蚁集团', 'job.alipay.com': '蚂蚁集团',
        'hikvision.com': '海康威视', 'zhaopin.hikvision.com': '海康威视',
        'zju.edu.cn': '浙江大学', 'sjtu.edu.cn': '上海交通大学', 'tsinghua.edu.cn': '清华大学', 'pku.edu.cn': '北京大学'
      };
      var parts = host.split('.');
      for (var i = 0; i < parts.length - 1; i++) {
        var cand = parts.slice(i).join('.');
        if (KNOWN[cand]) return { name: KNOWN[cand], src: 'known' };
      }
      // 标题含招聘关键词 → 提炼公司/品牌名（去掉招聘后缀、年份、标点）
      var title = (document.title || '').replace(/\s+/g, ' ').trim();
      if (/(招聘|校招|社招|网申|应聘|招贤|加入我们|talent|careers|jobs|recruit|apply|人才)/i.test(title)) {
        var t2 = title
          .replace(/(校园|社会|在线|官方|人才)?(招聘|招骋|网申|应聘|招贤纳士|加入我们|talent|careers|jobs|recruit|apply|校招|社招|招聘网)/gi, '')
          .replace(/\b20\d{2}\b/g, '').replace(/[_\-|—·•]/g, ' ').replace(/\s+/g, ' ').trim();
        if (t2.length >= 2 && t2.length <= 16 && /[一-龥A-Za-z]/.test(t2)) return { name: t2, src: 'guess' };
      }
    } catch (e) {}
    return { name: '', src: '' };
  }

  function boot() {
    // 后端自身的仪表板页不需要助手
    if (/^127\.0\.0\.1(:8787)?$/.test(location.host) || /^localhost(:8787)?$/.test(location.host)) return;
    loadSettings().then(function () {
      // 全局菜单 + 首次未配置引导：任何页面都可用（含登录页/未启用站点）
      registerGlobalMenu();
      maybeFirstRun();
      showWelcome();
      // 后端自身托管的仪表板页（本地或云端同源）不需要助手
      if (location.origin === SET.backend) return null;
      return GMshim.http({
        method: 'GET', timeout: 8000,
        url: SET.backend + '/api/assistant-context?host=' + encodeURIComponent(location.host),
        headers: { 'X-AC-Token': SET.token || '' }
      });
    }).then(function (res) {
      if (!res) return;   // 仪表板页直接退出
      if (res && res.status === 401) {
        // 云端令牌未填/填错：直接弹窗让你粘贴新令牌（存进 GM 后自动重连），
        // 不用再去油猴菜单翻设置。同一天只问一次；取消则当天不再打扰。
        console.warn('[网申助手] 后端 401：访问令牌无效或缺失');
        logLine('后端 401：令牌无效，请在弹窗中粘贴新令牌');
        var dt = new Date();
        var ymd = '' + dt.getFullYear() + ('0' + (dt.getMonth() + 1)).slice(-2) + ('0' + dt.getDate()).slice(-2);
        return GMshim.get('ac:token_ask').then(function (asked) {
          if (asked === ymd) return maybeManual();
          GMshim.set('ac:token_ask', ymd);
          var tk = (window.prompt(
            '网申助手：后端返回 401，访问令牌无效或缺失。\n\n请粘贴新的访问令牌（留空 / 取消 = 今天不再提示）：',
            ''
          ) || '').trim();
          if (!tk) return maybeManual();
          GMshim.set('ac:token', tk);
          SET.token = tk;
          logLine('已保存新令牌，正在重新连接…');
          setTimeout(boot, 300);
        });
      }
      var data = null;
      try { data = JSON.parse(res.text); } catch (e) {}
      if (!res || res.status !== 200 || !data || !data.ok) {
        // 后端未命中(未知站点/未配置公司)：仍尝试从页面自动识别公司并注入，免去逐站手动启用
        var d0 = detectCompany();
        if (d0.name) { COMPANY = d0.name; COMPANY_SRC = d0.src; ROLE = ''; LTYPE = '官网'; init(); }
        else maybeManual();
        return;
      }
      CTX = data;
      // 多租户：确认当前令牌对应哪份数据空间（面板标题下会显示身份）
      fetchWhoami().then(function (w) {
        if (w && w.multi) logLine('👤 当前身份：' + (w.label || '未命名') + '（独立数据空间）');
      });
      RULES = data.rules || [];
      VALUES = data.values || [];
      LEARNED = data.learned || {};
      SYN = buildSyn(data.syn);
      COMPANY = data.company || '';
      COMPANY_SRC = COMPANY ? 'backend' : '';
      ROLE = data.role || '';
      LTYPE = data.ltype || '';
      RESUME_ID = data.resume_id || '';
      RESUME_NAME = data.resume_name || '';
      if (!COMPANY) {
        // 后端没命中公司：尽力从页面(标题/域名/品牌词)自动识别，让面板在任意网申页可用
        var d = detectCompany();
        if (d.name) { COMPANY = d.name; COMPANY_SRC = d.src; ROLE = ''; LTYPE = '官网'; }
      }
      if (COMPANY) { init(); return; }   // 识别到公司(后端/已知/推测) → 直接注入，免去逐站手动启用
      // 啥都没识别到：保留手动启用兜底，否则静默退出
      isManualEnabled().then(function (on) { if (on) init(); });
    }).catch(function () {
      // 后端不可达也注入（本地兜底）：自动识别公司，至少能记账/填通用字段
      var d1 = detectCompany();
      if (d1.name) { COMPANY = d1.name; COMPANY_SRC = d1.src; ROLE = ''; LTYPE = '官网'; init(); }
      else maybeManual();
    });
  }

  // 暴露到 window 便于控制台/自动化排查与 e2e 断言
  try {
    window.__ac = {
      scanFields: scanFields, buildPayload: buildPayload, applyPayload: applyPayload,
      doFill: doFill, setVal: setVal, describe: describe, VALUES: VALUES, RULES: RULES,
      SYN: SYN, tryAutoAttach: tryAutoAttach, attachResume: attachResume, findFileInputs: findFileInputs,
      markApplied: markApplied, checkSuccess: checkSuccess, findSubmitButtons: findSubmitButtons,
      submitClicked: function () { return SUBMIT_CLICKED; },
      getCtx: function () { return CTX; }, getSet: function () { return SET; }
    };
  } catch (e) {}

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
