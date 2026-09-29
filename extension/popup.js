// 网申助手 popup —— 选当前目标公司、匹配简历、查看已注册简历
const $ = (s) => document.querySelector(s);
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),2200);}
function send(type, extra){return new Promise(res=>chrome.runtime.sendMessage({type, ...extra}, r=>res(r)));}

async function init(){
  const q = await send('getQueue');
  const resumes = await send('getResumes');
  if(q.error){toast('后端未连接：'+q.error);return;}
  const items = (q.json && q.json.items) || [];
  const sel = $('#company');
  sel.innerHTML = items
    .filter(i=>i.status!=='已记录')
    .map(i=>`<option value="${encodeURIComponent(i.company)}" data-url="${i.url}">${i.company}（${i.cat}·${i.status}）</option>`)
    .join('') || '<option>无可用公司</option>';

  if(resumes && resumes.json){
    $('#resumes').innerHTML = (resumes.json.resumes||[]).map(r=>
      `<div class="rv"><b>${r.id}</b> ${r.name}<div class="t">${r.tags.join('、')}</div></div>`).join('') || '（未注册简历）';
  }

  // 当前目标（来自 storage）
  chrome.storage.local.get(['currentTarget'], (s)=>{
    if(s.currentTarget){$('#curTarget').textContent='当前：'+s.currentTarget.company+(s.currentTarget.url?'':'')+'（扩展在网申页会据此预填）';}
  });
}

$('#setTarget').onclick = async ()=>{
  const sel=$('#company');
  const opt=sel.options[sel.selectedIndex];
  if(!opt)return;
  const company=decodeURIComponent(opt.value);
  const url=opt.dataset.url;
  await chrome.storage.local.set({currentTarget:{company,url}});
  $('#curTarget').textContent='当前：'+company+'（扩展在网申页会据此预填）';
  toast('已设为当前目标');
};

$('#matchBtn').onclick = async ()=>{
  const jd=$('#jd').value.trim();
  if(!jd){toast('先粘贴 JD');return;}
  const r=await send('match',{jd});
  if(r.error){toast('匹配失败：'+r.error);return;}
  const rec=r.json.recommended;
  $('#matchOut').innerHTML =
    `<div class="rec">👉 推荐：${rec.id} ${rec.name} — 分 ${rec.score}</div>`+
    `命中：${(rec.tag_hits||[]).join('、')||'无'}`+
    `<details><summary>全部候选</summary>`+
    r.json.candidates.map(c=>`<div>${c.score} · ${c.id}（${c.name}）</div>`).join('')+`</details>`;
  // 记住推荐版本，供内容页上传简历时使用
  await chrome.storage.local.set({currentResumeId:rec.id});
};

$('#openDash').onclick = ()=>chrome.tabs.create({url:'http://127.0.0.1:8787/'});
$('#openTarget').onclick = async ()=>{
  const s=await new Promise(r=>chrome.storage.local.get(['currentTarget'],r));
  if(s.currentTarget&&s.currentTarget.url){chrome.tabs.create({url:s.currentTarget.url});}
  else{toast('先选当前目标公司');}
};

init();
