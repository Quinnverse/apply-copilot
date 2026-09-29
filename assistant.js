(function(){
  if (window.__acBM) return; window.__acBM = 1;
  var RULES   = __RULES__;      // [{k:[关键词], v:值, t:[类型白名单]}]
  var VALUES  = __VALUES__;     // [{k:标签, v:值}]  点选填充 / 档案速查
  var SYN_TXT = __SYN__;        // [{re:正则串, name:中文规范名}] 宽松同义词（来自 filler.FIELD_SYN）
  var LEARNED = __LEARNED__;    // 已记住的字段（跨站点通用，历史投递沉淀）
  var BACKEND = '__BACKEND__';
  var COMPANY = __COMPANY__;
  var RESUME_ID = __RESUME_ID__;
  var RESUME_NAME = __RESUME_NAME__;

  var AC_IDX = 0;
  var PICK_MODE = false;
  var LAST_FIELDS = [];

  var VALMAP = {};
  VALUES.forEach(function(x){ VALMAP[x.k] = x.v; });

  // 宽松同义词：JS 端用 new RegExp(re, 'i') 重建（与 filler.FIELD_SYN 对齐）
  var SYN = (function(){
    var arr = SYN_TXT || [];
    return arr.map(function(x){
      try { return [new RegExp(x.re, 'i'), x.name]; } catch(e) { return [new RegExp('x'), x.name]; }
    });
  })();

  // ---------------------------------------------------------- 工具
  function cssEsc(s){ try{ return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/([ #;?%&,.+*~\':"!^$[\]()=>|/@])/g,'\\$1'); }catch(e){ return s; } }
  function textOf(el){ try{ return (el.textContent||'').replace(/\s+/g,' ').trim(); }catch(e){ return ''; } }
  function docOf(el){ try{ return el.ownerDocument || document; }catch(e){ return document; } }

  // 语义 key：优先 label/placeholder，去掉标点空白
  function keyOf(f){
    var s = String(f.label||f.aria||f.placeholder||f.title||f.name||f.id||'')
      .toLowerCase().replace(/[\s　]+/g,' ').replace(/[:：*＊（）()？?]/g,'').trim();
    return s.slice(0,120);
  }
  function scoreField(f, kw){
    var hay = f.hay || '';
    var k = String(kw||'').toLowerCase();
    if (!k) return 0;
    if (hay.indexOf(k) >= 0) return 1.0;
    var parts = k.split(/[\s\-_]/).filter(function(p){ return p.length > 1; });
    if (parts.length && parts.every(function(p){ return hay.indexOf(p) >= 0; })) return 0.7;
    return 0.0;
  }

  // 规则归一 key：命中 RULES 关键词则返回该规则的中文规范名（如"姓名"），否则回退标签字面。
  // 这样同义标签（"姓名" / "name" / "LastName"）跨站都能命中同一份记忆。
  function ruleKeyOf(f){
    var hay = f.hay || '';
    for (var i=0;i<RULES.length;i++){
      var kws = RULES[i].k;
      if (!kws) continue;
      var arr = Array.isArray(kws) ? kws : [kws];
      for (var j=0;j<arr.length;j++){
        if (arr[j] && hay.indexOf(String(arr[j]).toLowerCase()) >= 0) return arr[0];
      }
    }
    return keyOf(f);
  }

  // 标签抽取：label[for] → aria-labelledby → 包裹 label → 向上 6 层找容器里除自己外的文本 → 前一个兄弟
  function labelOf(el){
    var s = '';
    try{
      var d = docOf(el);
      if (el.id){ var l = d.querySelector('label[for="'+cssEsc(el.id)+'"]'); if (l) s = textOf(l); }
      if (!s){ var lb = el.getAttribute('aria-labelledby');
        if (lb){ var t = d.getElementById(lb); if (t) s = textOf(t); } }
      if (!s){ var pl = el.closest ? el.closest('label') : null; if (pl) s = textOf(pl); }
      // 容器文本兜底：只在"小容器"里取，且优先左右紧邻的兄弟节点，避免把 body 的第一个块当标签
      if (!s && el.closest){
        var n = el, depth = 0;
        while (n && depth < 6){
          var c = n.parentElement; if (!c) break;
          var cand = '';
          var pv = n.previousElementSibling, nx = n.nextElementSibling;
          if (pv && !pv.contains(el)) cand = textOf(pv);
          if (!cand && nx && !nx.contains(el)) cand = textOf(nx);
          if (!cand && c.children.length <= 6){
            var kids = c.children;
            for (var i=0;i<kids.length;i++){
              var k = kids[i];
              if (k === n || k.contains(el)) continue;
              var t2 = textOf(k);
              if (t2){ cand = t2; break; }
            }
          }
          if (cand){ s = cand; break; }
          n = c; depth++;
        }
      }
      if (!s){ var prev = el.previousElementSibling; if (prev) s = textOf(prev); }
    }catch(e){}
    return String(s||'').replace(/[\*＊:：\s]+$/g,'').slice(0,60);
  }

  function visible(el){
    try{
      var r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return false;
      var st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) < 0.05) return false;
      return true;
    }catch(e){ return true; }
  }

  // 很多招聘门户把表单放在 iframe 里 —— 穿透同源 iframe 一起扫（跨域拿不到 contentDocument）
  function allDocs(){
    var docs = [document];
    try{
      var fr = document.querySelectorAll('iframe');
      for (var i=0;i<fr.length;i++){
        try{ var d = fr[i].contentDocument; if (d) docs.push(d); }catch(e){}
      }
    }catch(e){}
    return docs;
  }

  function describe(el){
    var t = el.tagName.toLowerCase();
    var label = labelOf(el);
    var aria  = (el.getAttribute && el.getAttribute('aria-label')) || '';
    var title = (el.getAttribute && el.getAttribute('title')) || '';
    var ph = '';
    try{ ph = el.placeholder || el.getAttribute('data-ph') || el.getAttribute('data-placeholder') || ''; }catch(e){}
    var sel = '';
    if (el.id) sel = '#'+cssEsc(el.id);
    else if (el.name) sel = '[name="'+String(el.name).replace(/"/g,'\\"')+'"]';
    else {
      var idx = el.getAttribute && el.getAttribute('data-ac-idx');
      if (!idx){ idx = 'ac'+(++AC_IDX); try{ el.setAttribute('data-ac-idx', idx); }catch(e){} }
      sel = '[data-ac-idx="'+idx+'"]';
    }
    var hay = [label, aria, title, ph, el.name, el.id].filter(Boolean).join(' ').toLowerCase();
    return {el:el, tag:t, type:t==='input'?(el.type||'text'):t, id:el.id||'', name:el.name||'',
            placeholder:ph||'', label:label||'', aria:aria||'', title:title||'', sel:sel, hay:hay,
            group:(el.name||'')};
  }

  function scanFields(){
    var out = [];
    allDocs().forEach(function(doc){
      Array.prototype.slice.call(doc.querySelectorAll(
        'input,select,textarea,[contenteditable="true"],[role="textbox"]'))
      .filter(function(el){
        if (el.id === 'ac-pick-input') return false;
        if (el.closest && el.closest('#ac-fab')) return false;
        var t = el.tagName.toLowerCase();
        if (t === 'input'){
          var ty = (el.type||'text').toLowerCase();
          // 排除隐藏/按钮/文件；radio 保留（性别等需自动填），checkbox 排除（多选语义复杂，暂不自动勾）
          return ['hidden','submit','reset','button','image','file','checkbox'].indexOf(ty) < 0;
        }
        return true;
      })
      .forEach(function(el){ out.push(describe(el)); });
    });
    var vis = out.filter(function(f){ return visible(f.el); });
    return vis.length ? vis : out;   // 全隐藏时退回全集，避免"扫描 0 个"
  }

  // ---------------------------------------------------------- 匹配
  // 宽松同义词兜底（忽略类型白名单），解决关键词没对齐的情况（SYN 来自 filler.FIELD_SYN）
  function usable(v){ return !!(v && String(v).charAt(0) !== '['); }   // 过滤 [待补充]/[敏感信息]

  function buildPayload(fields){
    var out = [];
    fields.forEach(function(f){
      var key = ruleKeyOf(f);
      // ① 已记住的值（跨站点通用），命中即满置信
      if (key && LEARNED && LEARNED[key]){
        out.push({el:f.el, label:f.label||f.placeholder||f.name||f.id||'字段', selector:f.sel, type:f.type,
                  value:LEARNED[key], confidence:1.0, learned:true, key:key, hay:f.hay});
        return;
      }
      var best = null, bs = 0;
      // ② 规则匹配（带类型白名单）
      RULES.forEach(function(r){
        if (r.t.length && f.type && r.t.indexOf(f.type) < 0) return;
        var sc = Math.max.apply(null, r.k.map(function(kw){ return scoreField(f, kw); }));
        if (sc > bs && usable(r.v)){ bs = sc; best = r; }
      });
      // ③ 规则匹配（忽略类型白名单 —— 很多 SPA 的 type 是 text）
      if (bs < 0.5){
        RULES.forEach(function(r){
          var sc = Math.max.apply(null, r.k.map(function(kw){ return scoreField(f, kw); }));
          if (sc > bs && usable(r.v)){ bs = sc; best = r; }
        });
      }
      // ④ 宽松同义词（与 filler.FIELD_SYN 对齐）
      if (bs < 0.5){
        for (var i=0;i<SYN.length;i++){
          if (SYN[i][0].test(f.hay)){
            var v = VALMAP[SYN[i][1]];
            if (usable(v)){ best = {v:v}; bs = 0.9; break; }
          }
        }
      }
      // ⑤ input type 兜底
      if (bs < 0.5){
        var ty = (f.type||'').toLowerCase();
        if (ty === 'tel' && usable(VALMAP['手机'])) { best = {v:VALMAP['手机']}; bs = 0.8; }
        else if (ty === 'email' && usable(VALMAP['邮箱'])) { best = {v:VALMAP['邮箱']}; bs = 0.8; }
      }
      out.push({el:f.el, label:f.label||f.placeholder||f.name||f.id||'字段', selector:f.sel, type:f.type,
                value:(best && usable(best.v)) ? best.v : '', confidence:bs, key:key, hay:f.hay});
    });
    return out;
  }

  // ---------------------------------------------------------- 赋值（React/Vue 受控组件必须走原生 setter）
  function fire(el, name){ try{ el.dispatchEvent(new Event(name, {bubbles:true})); }catch(e){} }

  // 是否多值档案值（如"浙江、上海、江苏" / "北京,上海"）：含常见分隔符即视为多值。
  // 多值绝不做"包含匹配" —— 否则选项"上海"会被整个多值串反向命中而错填，
  // 或反过来把 select 填成一个无意义值还不标红。多值只接受精确/归一后相等。
  function isMultiValue(v){
    return /[、,，\/;；|]/.test(String(v==null?'':v));
  }

  // 学历/学位等选项归一：去掉"全日制/应届/在读/统招/普通/学历/学位/研究生/大学/学院/院/系"等噪音词，
  // 保留核心词（硕士/本科/博士…），使"硕士"能匹配"硕士研究生"、"本科（统招）"等。
  function normEdu(s){
    return String(s==null?'':s).toLowerCase()
      .replace(/[\s　]/g,'')
      .replace(/全日制|应届|在读|统招|普通|学历|学位|研究生|大学|学院|院|系/g,'')
      .trim();
  }

  // radio 组：按相邻 label/aria/父容器文本找"男/女"等，匹配档案值后勾选对应项
  function radioLabel(el){
    try{
      var d = docOf(el);
      if (el.id){ var l = d.querySelector('label[for="'+cssEsc(el.id)+'"]'); if (l) return textOf(l); }
      if (el.closest){
        var pl = el.closest('label'); if (pl) return textOf(pl);
        var par = el.parentElement; if (par) return textOf(par);
      }
    }catch(e){}
    return '';
  }
  function setValRadio(el, v){
    var name = el.name; if (!name) return false;
    var group = Array.prototype.slice.call(
      document.querySelectorAll('input[type="radio"][name="'+String(name).replace(/"/g,'\\"')+'"]'));
    if (!group.length) return false;
    var wantMale = /男/.test(v), wantFemale = /女/.test(v);
    var target = null;
    for (var i=0;i<group.length && !target;i++){
      var lab = radioLabel(group[i]) || '';
      var low = (lab + ' ' + (group[i].value||'')).toLowerCase();
      if (wantMale && (lab.indexOf('男') >= 0 || /\bmale\b/.test(low) || low === 'm')) target = group[i];
      else if (wantFemale && (lab.indexOf('女') >= 0 || /\bfemale\b/.test(low) || low === 'f')) target = group[i];
      else if (group[i].value && (group[i].value === v || group[i].value.toLowerCase() === String(v).toLowerCase())) target = group[i];
    }
    if (target){
      if (!target.checked){ target.checked = true; fire(target, 'change'); fire(target, 'input'); }
      target.style.backgroundColor = '#e8f3ff';
      return true;
    }
    return false;
  }

  function setVal(el, v){
    try{
      var tag = el.tagName;
      if (tag === 'INPUT' && el.type === 'radio'){
        return setValRadio(el, v);
      }
      if (tag === 'SELECT'){
        var opts = Array.prototype.slice.call(el.options || []);
        var vNorm = normEdu(v);
        var hit = null;
        // ① 精确：选项 text/value 原始相等，或归一后相等
        for (var i=0;i<opts.length && !hit;i++){
          var t = String(opts[i].textContent||'').trim(), ov = String(opts[i].value||'').trim();
          if (t === v || ov === v || normEdu(t) === vNorm || normEdu(ov) === vNorm) hit = opts[i];
        }
        // ② 双向包含（归一）：如"硕士"包含于"硕士研究生"或反之
        //    多值档案值跳过此步（只认精确），避免"上海"被"浙江、上海、江苏"反向命中
        if (!hit && !isMultiValue(v)){
          for (var j=0;j<opts.length && !hit;j++){
            var t2 = normEdu(String(opts[j].textContent||'').trim());
            if (t2 && vNorm && (t2.indexOf(vNorm) >= 0 || vNorm.indexOf(t2) >= 0)) hit = opts[j];
          }
        }
        if (hit){ el.value = hit.value; fire(el, 'change'); fire(el, 'input'); return true; }
        // ③ 都没中：红框标记、不偷赋值，返回 false 让 applyPayload 计入未命中（避免"填了等于没填"）
        try{ el.style.border = '2px solid #e74c3c'; el.setAttribute('data-ac-miss', '1'); }catch(e){}
        return false;
      }
      if (tag === 'INPUT' && (el.type === 'date' || el.type === 'month')){
        var val = v;
        if (el.type === 'date' && /^\d{4}-\d{2}$/.test(v)) val = v + '-01';
        if (el.type === 'month' && /^\d{4}-\d{2}-\d{2}$/.test(v)) val = v.slice(0,7);
        var p2 = Object.getPrototypeOf(el), d2 = p2 && Object.getOwnPropertyDescriptor(p2, 'value');
        if (d2 && d2.set) d2.set.call(el, val); else el.value = val;
        fire(el, 'input'); fire(el, 'change');
      } else if (el.isContentEditable || (el.getAttribute && el.getAttribute('contenteditable') === 'true')){
        el.focus();
        try{
          var r = document.createRange(); r.selectNodeContents(el);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          document.execCommand('insertText', false, v);
        }catch(e){ el.textContent = v; }
        fire(el, 'input');
      } else {
        var proto3 = Object.getPrototypeOf(el);
        var desc3 = proto3 && Object.getOwnPropertyDescriptor(proto3, 'value');
        if (desc3 && desc3.set) desc3.set.call(el, v); else el.value = v;
        fire(el, 'input'); fire(el, 'change');
      }
      // 复位红框（之前标过未命中的）
      try{ el.style.backgroundColor = '#e8f3ff'; el.style.border = ''; el.removeAttribute('data-ac-miss'); }catch(e){}
      return true;
    }catch(e){ return false; }
  }

  function postJSON(path, body){
    try{
      return fetch(BACKEND + path, {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body)}).then(function(r){ return r.json(); })
        .catch(function(e){ return {ok:false, error:String(e)}; });
    }catch(e){ return Promise.resolve({ok:false, error:String(e)}); }
  }

  // 记住单个字段（点选填充后立刻沉淀，下次/别的站点自动命中，用规则归一 key 跨站通用）
  function rememberOne(f, v){
    var key = ruleKeyOf(f);
    if (!key || !v) return;
    var payload = {}; payload[key] = v;
    postJSON('/api/field-memory', {host: location.host, company: COMPANY,
      resume_id: RESUME_ID, fields: payload});
    LEARNED[key] = v;
  }

  // 记住本页所有已填字段（含用户手填的），下次所有站点自动命中
  function rememberPage(){
    var fields = scanFields(), out = {}, n = 0;
    fields.forEach(function(f){
      var key = ruleKeyOf(f), v = '';
      try{ v = (f.el.value != null) ? String(f.el.value) : ''; }catch(e){}
      if (!v){ try{ v = (f.el.textContent||'').trim(); }catch(e){} }
      if (key && v && v.length < 500){ out[key] = v; n++; }
    });
    if (!n){ status('本页没有可记住的字段值（先手动填几个再点）'); return; }
    postJSON('/api/field-memory', {host: location.host, company: COMPANY,
      resume_id: RESUME_ID, fields: out}).then(function(r){
      if (r && r.ok) status('已记住 '+n+' 个字段（所有站点通用），累计 '+r.total);
      else status('记忆失败：'+((r && r.error) || '未知'));
    });
  }

  // ---------------------------------------------------------- 面板交互
  function progress(w){
    var b = document.getElementById('ac-bar');
    if (b) b.style.width = Math.max(0, Math.min(100, w)) + '%';
  }
  function status(m){ if (window.__acST) window.__acST.textContent = m; }
  function toast(m){
    var t = document.createElement('div'); t.textContent = m;
    t.style.cssText = 'position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#222;color:#fff;padding:8px 14px;border-radius:9px;font-size:13px;z-index:2147483647';
    document.body.appendChild(t); setTimeout(function(){ try{ t.remove(); }catch(e){} }, 2600);
  }

  function dumpScan(p, filled){
    try{
      var dump = p.slice(0, 80).map(function(x){
        return {label:(x.label||'').slice(0,40), ph:(x.placeholder||'').slice(0,40),
                name:(x.name||'').slice(0,40), id:(x.id||'').slice(0,40),
                type:x.type||'', hay:(x.hay||'').slice(0,60), conf:x.confidence||0};
      });
      postJSON('/api/scan-dump', {url: location.href, host: location.host, company: COMPANY,
        count: p.length, filled: filled, fields: dump});
    }catch(e){}
  }

  function applyPayload(p){
    var filled = 0, missed = 0;
    p.forEach(function(x){
      var el = x.el || (x.selector ? document.querySelector(x.selector) : null);
      if (!el){ missed++; return; }
      if (x.confidence >= 0.5 && x.value && setVal(el, x.value)) filled++;
      else {
        try{
          el.style.border = '2px solid #e74c3c';
          el.setAttribute && el.setAttribute('data-ac-miss', '1');
        }catch(e){}
        missed++;
      }
    });
    LAST_FIELDS = p;
    var msg = '扫描 '+p.length+' 个 → 已填 '+filled+' / 未命中 '+missed;
    if (filled === 0){
      var frN = document.querySelectorAll('iframe').length;
      var withHay = p.filter(function(x){ return (x.hay||'').length > 0; }).length;
      var sample = p.slice(0,3).map(function(x){
        return '"'+String(x.label||x.placeholder||x.name||x.id||'(无)').slice(0,10)+'"'; }).join(' ');
      msg += ' ｜ 样例 '+sample+' ｜ 有文本 '+withHay+'/'+p.length;
      if (frN){
        msg += '（检测到 '+frN+' 个 iframe：若为跨域则前端无法填充，请用官网直链或浏览器开发者工具）';
      } else {
        msg += (withHay === 0) ? '（都不是表单字段：可能在跨域 iframe / 未登录）'
                             : '（关键词没对上 → 用「④ 点选填充」）';
      }
    } else {
      msg += '（红框：开④点选填充后点它选值）';
    }
    status(msg);
    dumpScan(p, filled);
  }

  function doFill(){
    var f = scanFields();
    if (!f.length){
      var frN = document.querySelectorAll('iframe').length;
      if (frN){
        status('未识别到可填字段：检测到 '+frN+' 个 iframe。若为跨域 iframe，前端无法填充，请用官网直链或浏览器开发者工具');
      } else {
        status('未识别到可填字段（页面还在加载？等 2 秒再点一次）');
      }
      return;
    }
    progress(20);
    setTimeout(function(){
      var p = buildPayload(f);
      progress(65);
      setTimeout(function(){ applyPayload(p); progress(100); }, 20);
    }, 20);
  }

  // ---- 点选填充：点页面上的输入框 → 面板列出档案值 → 选一个填进去并记住 ----
  function renderValues(container, onPick){
    container.innerHTML = '';
    VALUES.forEach(function(v){
      var b = document.createElement('button');
      b.className = 'chip';
      b.innerHTML = '<b>'+String(v.k).replace(/[<>&]/g,'')+'</b><span>'+String(v.v).replace(/[<>&]/g,'').slice(0,18)+'</span>';
      b.onclick = function(){ onPick(v.k, v.v); };
      container.appendChild(b);
    });
  }
  function openPanel(id){
    var panel = document.getElementById('ac-panel');
    if (!panel) return;
    ['ac-main','ac-picker','ac-copy'].forEach(function(x){
      var n = document.getElementById(x); if (n) n.style.display = (x === id) ? 'block' : 'none';
    });
    panel.classList.add('open');
  }
  function openPicker(f){
    var box = document.getElementById('ac-picker');
    if (!box) return;
    var title = f.label || f.placeholder || f.name || f.id || '该字段';
    box.innerHTML = '<div class="ph">把这个字段填成？<br><b>'+String(title).replace(/[<>&]/g,'').slice(0,30)+'</b></div><div class="chips" id="ac-chips"></div>'
      + '<input id="ac-pick-input" placeholder="或手输一个值，回车填入" />'
      + '<button class="act ghost" id="ac-pick-back">← 返回</button>';
    var chips = box.querySelector('#ac-chips');
    renderValues(chips, function(k, v){
      setVal(f.el, v); rememberOne(f, v);
      toast('已填「'+k+'」并记住');
      openPanel('ac-main');
    });
    box.querySelector('#ac-pick-input').onkeydown = function(e){
      if (e.key === 'Enter'){
        var v = this.value.trim();
        if (v){ setVal(f.el, v); rememberOne(f, v); toast('已填入并记住'); openPanel('ac-main'); }
      }
    };
    box.querySelector('#ac-pick-back').onclick = function(){ openPanel('ac-main'); };
    openPanel('ac-picker');
  }
  function togglePick(){
    PICK_MODE = !PICK_MODE;
    var b = document.getElementById('ac-pick');
    if (b){ b.textContent = PICK_MODE ? '④ 点选中…（点输入框）' : '④ 点选填充'; b.className = 'act' + (PICK_MODE ? ' on' : ''); }
    status(PICK_MODE ? '点选模式：点击页面上任意输入框 → 选值填入' : '已退出点选模式');
  }

  // ---- 档案速查：一键复制，填不进去时至少能秒粘 ----
  function openCopy(){
    var box = document.getElementById('ac-copy');
    if (!box) return;
    box.innerHTML = '<div class="ph">点一下即复制</div><div class="chips" id="ac-cchips"></div>'
      + '<button class="act ghost" id="ac-copy-back">← 返回</button>';
    var chips = box.querySelector('#ac-cchips');
    renderValues(chips, function(k, v){ copyText(v); toast('已复制「'+k+'」'); });
    box.querySelector('#ac-copy-back').onclick = function(){ openPanel('ac-main'); };
    openPanel('ac-copy');
  }
  function copyText(t){
    try{
      if (navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(t); return; }
    }catch(e){}
    try{
      var ta = document.createElement('textarea');
      ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    }catch(e){}
  }

  // 历史兼容：pywebview 路径下 window.pywebview.api 可用；Qt 路径用 fetch 直连后端（见 doRecord）
  function callApi(method){
    var args = Array.prototype.slice.call(arguments, 1);
    function run(api){ return (api && api[method]) ? api[method].apply(api, args) : null; }
    if (window.pywebview && window.pywebview.api) return Promise.resolve(run(window.pywebview.api));
    return new Promise(function(res){
      window.addEventListener('pywebviewready', function(){ res(run(window.pywebview.api)); }, {once:true});
    });
  }

  // ② 记录已投：直接 POST /api/mark 真实入库（不再只翻队列徽章）。
  // 未传 title 时后端按 company 反查 seed 的 role 作默认标题。
  function doRecord(){
    if (!COMPANY){
      status('当前页未关联公司，请回仪表板用「记录入库」');
      toast('当前页未关联公司，请回仪表板记录');
      return;
    }
    postJSON('/api/mark', {
      company: COMPANY,
      channel: (window.__acChannel || '官网'),
      resume_version: (window.__acRV || '')
    }).then(function(r){
      if (r && r.ok){ status('已入库：' + COMPANY + ' · ' + (r.title || '')); toast('已记录入库：' + COMPANY); }
      else { status('入库失败：' + ((r && r.error) || '未知错误')); }
    });
  }

  // ---------------------------------------------------------- 注入
  function inject(){
    if (document.getElementById('ac-fab')) return;
    var css = '#ac-fab{position:fixed;right:14px;bottom:14px;width:46px;height:46px;z-index:2147483647;pointer-events:none;font-family:-apple-system,"PingFang SC",sans-serif}'
      + '#ac-fab .fab{pointer-events:auto;width:46px;height:46px;border-radius:50%;background:#185FA5;color:#fff;border:none;font-size:22px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.3)}'
      + '#ac-fab .panel{pointer-events:auto;display:none;position:absolute;right:0;bottom:56px;width:246px;background:#fff;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.25);padding:12px;color:#1f2329}'
      + '#ac-fab .panel.open{display:block}'
      + '#ac-fab button.act{display:block;width:100%;margin:5px 0;background:#185FA5;color:#fff;border:none;border-radius:8px;padding:9px;font-size:13px;font-weight:600;cursor:pointer}'
      + '#ac-fab button.act.on{background:#C2410C}'
      + '#ac-fab button.act.rec{background:#1F7A4D}'
      + '#ac-fab button.act.ghost{background:#eef1f5;color:#1f2329}'
      + '#ac-fab .st{font-size:11.5px;color:#5f6368;margin-top:6px;line-height:1.5}'
      + '#ac-fab .meta{font-size:11px;color:#888;margin-bottom:4px}'
      + '#ac-fab .ph{font-size:12px;color:#5f6368;margin-bottom:8px;line-height:1.5}'
      + '#ac-fab .ph b{color:#185FA5}'
      + '#ac-fab .chips{max-height:230px;overflow:auto;margin-bottom:6px}'
      + '#ac-fab .chip{display:block;width:100%;text-align:left;margin:3px 0;padding:6px 8px;border:1px solid #e3e8ef;background:#fff;border-radius:7px;cursor:pointer;font-size:12px;line-height:1.4}'
      + '#ac-fab .chip:hover{border-color:#185FA5;background:#f2f7fd}'
      + '#ac-fab .chip b{color:#185FA5;margin-right:6px}'
      + '#ac-fab .chip span{color:#5f6368}'
      + '#ac-fab input#ac-pick-input{width:100%;box-sizing:border-box;padding:7px 8px;border:1px solid #d7dce3;border-radius:7px;font-size:12px;margin-top:4px}'
      + '#ac-fab .pw{height:5px;background:#eef1f5;border-radius:3px;overflow:hidden;margin:6px 0}'
      + '#ac-fab #ac-bar{height:100%;width:0;background:#185FA5;transition:width .18s}';
    var stl = document.createElement('style'); stl.textContent = css;
    (document.head || document.documentElement).appendChild(stl);

    var root = document.createElement('div'); root.id = 'ac-fab';
    root.innerHTML = '<div class="panel" id="ac-panel">'
      + '<div class="meta" id="ac-meta"></div>'
      + '<div class="pw"><div id="ac-bar"></div></div>'
      + '<div id="ac-main">'
      +   '<button class="act" id="ac-fill">① 填充表单</button>'
      +   '<button class="act" id="ac-pick">④ 点选填充</button>'
      +   '<button class="act" id="ac-remember">③ 记住本页字段</button>'
      +   '<button class="act ghost" id="ac-copybtn">📋 档案速查（复制）</button>'
      +   '<button class="act rec" id="ac-record">② 记录已投</button>'
      + '</div>'
      + '<div id="ac-picker" style="display:none"></div>'
      + '<div id="ac-copy" style="display:none"></div>'
      + '<div class="st" id="ac-st"></div></div>'
      + '<button class="fab" id="ac-toggle" title="网申助手">🛠</button>';
    document.body.appendChild(root);
    window.__acST = root.querySelector('#ac-st');
    var meta = root.querySelector('#ac-meta');
    meta.textContent = (RESUME_NAME ? ('简历: '+RESUME_NAME) : '') + (COMPANY ? (' · '+COMPANY) : '');
    root.querySelector('#ac-toggle').onclick = function(){ root.querySelector('#ac-panel').classList.toggle('open'); };
    root.querySelector('#ac-fill').onclick = doFill;
    root.querySelector('#ac-pick').onclick = togglePick;
    root.querySelector('#ac-remember').onclick = rememberPage;
    root.querySelector('#ac-copybtn').onclick = openCopy;
    root.querySelector('#ac-record').onclick = doRecord;

    // 点选模式：点击页面任意输入框 → 弹出选值
    document.addEventListener('click', function(e){
      if (!PICK_MODE) return;
      var t = e.target;
      if (t && t.closest && t.closest('#ac-fab')) return;
      var el = (t && t.closest) ? t.closest('input,select,textarea,[contenteditable="true"],[role="textbox"]') : null;
      if (!el) return;
      e.preventDefault(); e.stopPropagation();
      PICK_MODE = false;
      var b = document.getElementById('ac-pick');
      if (b){ b.textContent = '④ 点选填充'; b.className = 'act'; }
      openPicker(describe(el));
    }, true);
  }

  // 暴露到 window 便于控制台/自动化排查（页面是用户自己的会话，无越权风险）
  try{
    window.__ac = {scanFields:scanFields, buildPayload:buildPayload, applyPayload:applyPayload,
                   doFill:doFill, setVal:setVal, describe:describe, VALUES:VALUES, RULES:RULES, SYN:SYN};
  }catch(e){}

  function boot(){ inject(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
