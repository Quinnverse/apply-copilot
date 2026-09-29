
(function(){
  if (window.__acBM) return; window.__acBM = 1;
  const RULES = [{"k": ["姓名", "name", "真实姓名", "中文姓名"], "v": "示例姓名", "t": []}, {"k": ["手机", "移动电话", "电话", "手机号", "mobile", "phone", "联系电话"], "v": "138-0000-0000", "t": ["tel", "text"]}, {"k": ["邮箱", "电子邮箱", "email", "e-mail", "邮件"], "v": "you@example.com", "t": ["email", "text"]}, {"k": ["微信", "微信号", "wechat"], "v": "", "t": ["text"]}, {"k": ["性别", "gender", "sex"], "v": "", "t": ["select", "radio", "text"]}, {"k": ["政治面貌", "political"], "v": "", "t": ["select", "text"]}, {"k": ["籍贯", "出生地", "户籍", " hometown"], "v": "", "t": ["text"]}, {"k": ["学校", "院校", "毕业院校", "大学", "university", "school", "本科院校", "硕士院校"], "v": "示例大学", "t": ["text"]}, {"k": ["专业", "所学专业", "major"], "v": "机器学习 / 自然语言处理 / 大数据开发 / 数据科学", "t": ["text"]}, {"k": ["学历", "学位", "最高学历", "degree"], "v": "硕士", "t": ["select", "text"]}, {"k": ["毕业时间", "毕业年份", "graduation", "预计毕业", "毕业年月"], "v": "2026-10", "t": ["text", "month", "date"]}, {"k": ["届别", "毕业届别"], "v": "2027", "t": ["text"]}];

  function scoreField(f, kw){
    const hay = (f.label+' '+f.name+' '+f.id+' '+f.placeholder).toLowerCase();
    if (kw.toLowerCase() in hay) return 1.0;
    const parts = kw.toLowerCase().split(/[\s\-_]/).filter(p=>p.length>1);
    if (parts.length && parts.every(p=>hay.includes(p))) return 0.7;
    return 0.0;
  }
  function buildPayload(fields){
    const out=[];
    fields.forEach(f=>{
      let best=null, bs=0;
      RULES.forEach(r=>{
        if (r.t.length && f.type && !r.t.includes(f.type)) return;
        const sc = Math.max(...r.k.map(kw=>scoreField(f,kw)));
        if (sc>bs){bs=sc;best=r;}
      });
      let sel='';
      if (f.id) sel='#'+CSS.escape(f.id);
      else if (f.name) sel='[name="'+f.name+'"]';
      out.push({label:f.label||f.placeholder||f.name||f.id||'字段', selector:sel, type:f.type,
                value: best?best.v:'', confidence:bs});
    });
    return out;
  }
  function scanFields(){
    return [...document.querySelectorAll('input,select,textarea')]
      .filter(el=>{ const t=el.tagName.toLowerCase();
        if(t==='input'){const ty=(el.type||'text').toLowerCase();
          return !['hidden','submit','reset','button','image','radio','checkbox'].includes(ty);}
        return true; })
      .map(el=>{ const t=el.tagName.toLowerCase(); let label='';
        if(el.id){const l=document.querySelector('label[for="'+CSS.escape(el.id)+'"]'); if(l)label=l.textContent.trim();}
        if(!label){const pl=el.closest('label'); if(pl)label=pl.textContent.trim();}
        if(!label){const p=el.previousElementSibling; if(p&&p.tagName==='LABEL')label=p.textContent.trim();}
        return {tag:t, type:t==='input'?(el.type||'text'):t, id:el.id||'', name:el.name||'', placeholder:el.placeholder||'', label}; });
  }
  function setVal(el,v){ try{ if(el.tagName==='SELECT')el.value=v; else el.value=v;
    el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
    el.style.backgroundColor='#e8f3ff'; }catch(e){} }
  function applyPayload(p){ let filled=0,missed=0;
    p.forEach(x=>{ if(!x.selector)return; const el=document.querySelector(x.selector);
      if(!el){missed++;return;}
      if(x.confidence>=0.5 && x.value){setVal(el,x.value);filled++;} else {el.style.border='2px solid #e74c3c';missed++;} });
    status('已填充 '+filled+' 个，未命中 '+missed+' 个（红框需手填）'); }
  function doFill(){ const f=scanFields(); if(!f.length){status('未识别到可填字段');return;}
    applyPayload(buildPayload(f)); }
  function openDash(){ window.open('http://127.0.0.1:8787/','_blank'); toast('已打开仪表板，去点「标记已记录」'); }
  function toast(m){ const t=document.createElement('div'); t.textContent=m;
    t.style.cssText='position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#222;color:#fff;padding:8px 14px;border-radius:9px;font-size:13px;z-index:2147483647';
    document.body.appendChild(t); setTimeout(()=>t.remove(),2600); }
  function status(m){ if(window.__acST) window.__acST.textContent=m; }

  const SUCCESS_KW=['投递成功','提交成功','申请已提交','简历已收到','投递完成','您已成功投递','报名成功','已成功投递'];
  let flagged=false;
  function checkSuccess(){ if(flagged||!document.body)return;
    const txt=document.body.innerText||'';
    if(SUCCESS_KW.some(k=>txt.includes(k))){ flagged=true;
      const b=document.getElementById('ac-record'); if(b){b.classList.add('ac-pulse');b.style.background='#1F7A4D';}
      toast('🎉 检测到提交成功页 —— 打开仪表板点「标记已记录」'); } }

  function inject(){ if(document.getElementById('ac-fab'))return;
    const css='#ac-fab{position:fixed;right:14px;bottom:14px;z-index:2147483647;font-family:-apple-system,"PingFang SC",sans-serif}'
      +'#ac-fab .fab{width:46px;height:46px;border-radius:50%;background:#185FA5;color:#fff;border:none;font-size:22px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.3)}'
      +'#ac-fab .panel{display:none;position:absolute;right:0;bottom:56px;width:220px;background:#fff;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.25);padding:12px;color:#1f2329}'
      +'#ac-fab .panel.open{display:block}#ac-fab button.act{display:block;width:100%;margin:5px 0;background:#185FA5;color:#fff;border:none;border-radius:8px;padding:9px;font-size:13px;font-weight:600;cursor:pointer}'
      +'#ac-fab button.act.rec{background:#1F7A4D}#ac-fab .st{font-size:11.5px;color:#5f6368;margin-top:6px;line-height:1.5}'
      +'#ac-fab .act.ac-pulse{animation:acp 1s infinite}@keyframes acp{0%{box-shadow:0 0 0 0 rgba(31,122,77,.6)}70%{box-shadow:0 0 0 10px rgba(31,122,77,0)}100%{box-shadow:0 0 0 0 rgba(31,122,77,0)}}';
    const st=document.createElement('style'); st.textContent=css; document.head.appendChild(st);
    const root=document.createElement('div'); root.id='ac-fab';
    root.innerHTML='<div class="panel" id="ac-panel"><button class="act" id="ac-fill">① 填充表单</button>'
      +'<button class="act rec" id="ac-record">② 打开仪表板·记录</button><div class="st" id="ac-st"></div></div>'
      +'<button class="fab" id="ac-toggle" title="网申助手">🛠</button>';
    document.body.appendChild(root); window.__acST=root.querySelector('#ac-st');
    root.querySelector('#ac-toggle').onclick=()=>root.querySelector('#ac-panel').classList.toggle('open');
    root.querySelector('#ac-fill').onclick=doFill;
    root.querySelector('#ac-record').onclick=openDash;
  }
  function boot(){ inject(); checkSuccess();
    new MutationObserver(()=>checkSuccess()).observe(document.documentElement,{childList:true,subtree:true,characterData:true}); }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot); else boot();
})();
