#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成纯前端「书签小工具」助手 assistant.bookmarklet.js。

特点（相比 MV3 扩展）：
  * 零安装：不需要 Chrome 开发者模式、不需要加载解压目录。
  * 纯前端：档案字段值 + 字段映射规则全部内嵌进 JS，不连本地后端，
    因此在 https 网申页上也不会被"混合内容"拦截。
  * 功能：扫描网申页表单 → 按档案自动填值（未命中红框标出）；
    顶部浮标含「填充表单 / 打开仪表板(去记录)」按钮；
    检测"提交成功"页高亮提示。
  * 记录投递：回到 http://127.0.0.1:8787/ 仪表板点「标记已记录」（同源可写库）。

用法：
  python gen_bookmarklet.py        # 生成 assistant.bookmarklet.js
  然后把 dashboard.html 顶部的"网申助手"书签拖到书签栏即可。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
import copilot  # noqa: E402
import filler   # noqa: E402

profile = copilot.load_json(HERE / "profile.job.json") if (HERE / "profile.job.json").exists() else {}

# 把 filler.FIELD_RULES 的 getter 套用档案，预计算每条规则的填值
rules = []
for keywords, getter, types in filler.FIELD_RULES:
    val = getter(profile) or ""
    val = str(val).strip()
    # 占位符（如 [待补充]）视为空，不填
    if val.startswith("[") and val.endswith("]"):
        val = ""
    rules.append({"k": keywords, "v": val, "t": types})

RULES_JSON = json.dumps(rules, ensure_ascii=False)

JS = r"""
(function(){
  if (window.__acBM) return; window.__acBM = 1;
  const RULES = __RULES__;

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
""".replace("__RULES__", RULES_JSON)

out = HERE / "static" / "assistant.bookmarklet.js"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(JS, encoding="utf-8")
print(f"[ok] 已生成 {out}（{len(JS)} 字节，纯前端、零安装）")
print(f"     内嵌填表规则 {len(rules)} 条，含值 {sum(1 for r in rules if r['v'])} 条")
