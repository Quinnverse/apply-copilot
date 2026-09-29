// 网申助手 popup —— 选当前目标公司、匹配简历、查看已注册简历
const $ = (s) => document.querySelector(s);
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('show'),2200);}
function send(type, extra){return new Promise(res=>chrome.runtime.sendMessage({type, ...extra}, r=>res(r)));}
let currentProfile = {};

async function loadProfile(){
  const r=await send('getProfile');
  if(!r || r.error){$('#profileStatus').textContent='后端未连接：'+((r&&r.error)||'无响应');return;}
  currentProfile=r.json.profile||{};
  const basic=currentProfile.basic||{}, education=(currentProfile.education||[])[0]||{};
  $('#profileName').value=basic.name||'';
  $('#profileEmail').value=basic.email||'';
  $('#profilePhone').value=basic.phone||'';
  $('#profileSchool').value=education.school||'';
  $('#profileDegree').value=currentProfile.highest_degree||education.degree||'';
  $('#profileMajor').value=education.major||'';
  $('#profileStatus').textContent=basic.name?'已载入档案':'请先填写档案，再打开网申页';
}

$('#saveProfile').onclick=async()=>{
  const basic={...(currentProfile.basic||{})};
  basic.name=$('#profileName').value.trim();
  basic.email=$('#profileEmail').value.trim();
  basic.phone=$('#profilePhone').value.trim();
  const education=[...(currentProfile.education||[])];
  education[0]={...(education[0]||{}),school:$('#profileSchool').value.trim(),major:$('#profileMajor').value.trim(),degree:$('#profileDegree').value.trim()};
  const profile={...currentProfile,basic,education,highest_degree:$('#profileDegree').value.trim()};
  const r=await send('putProfile',{profile});
  if(!r || r.error){$('#profileStatus').textContent='保存失败：'+((r&&r.error)||'无响应');return;}
  currentProfile=r.json.profile||profile;
  $('#profileStatus').textContent='档案已保存；填充前仍需逐项确认';
};

async function init(){
  await loadProfile();
  const q = await send('getQueue');
  const resumes = await send('getResumes');
  if(q.error){toast('后端未连接：'+q.error);return;}
  const items = (q.json && q.json.items) || [];
  const sel = $('#company');
  sel.replaceChildren();
  items.filter(i=>i.status!=='已记录').forEach(i=>{
    const option=document.createElement('option');
    option.value=encodeURIComponent(i.company||'');
    option.dataset.url=i.url||'';
    option.textContent=`${i.company}（${i.cat}·${i.status}）`;
    sel.appendChild(option);
  });
  if(!sel.options.length){const option=document.createElement('option');option.textContent='无可用公司';sel.appendChild(option);}

  if(resumes && resumes.json){
    const list=$('#resumes'); list.replaceChildren();
    (resumes.json.resumes||[]).forEach(r=>{
      const div=document.createElement('div');div.className='rv';
      const bold=document.createElement('b');bold.textContent=r.id||'';
      const tags=document.createElement('div');tags.className='t';tags.textContent=(r.tags||[]).join('、');
      div.append(bold,document.createTextNode(' '+(r.name||'')),tags);list.appendChild(div);
    });
    if(!list.childNodes.length)list.textContent='（未注册简历）';
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
  const out=$('#matchOut');out.replaceChildren();
  const recommendation=document.createElement('div');recommendation.className='rec';
  recommendation.textContent=`👉 推荐：${rec.id} ${rec.name} — 分 ${rec.score}`;
  const hits=document.createElement('div');hits.textContent='命中：'+((rec.tag_hits||[]).join('、')||'无');
  const details=document.createElement('details');
  const summary=document.createElement('summary');summary.textContent='全部候选';details.appendChild(summary);
  (r.json.candidates||[]).forEach(c=>{const div=document.createElement('div');div.textContent=`${c.score} · ${c.id}（${c.name}）`;details.appendChild(div);});
  out.append(recommendation,hits,details);
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
