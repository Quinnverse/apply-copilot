(function(){
  var filled=0, missed=0;
  function set(el, v){
    if(!el || !v) return false;
    if(el.tagName==='SELECT'){ el.value=v; }
    else if(el.tagName==='TEXTAREA'){ el.value=v; }
    else { el.value=v; }
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
    el.style.backgroundColor='#e8f3ff';
    return true;
  }
  if(set(document.querySelector('#name'), '示例姓名')) filled++; else missed++;
  if(set(document.querySelector('#mobile'), '138-0000-0000')) filled++; else missed++;
  if(set(document.querySelector('#email'), 'you@example.com')) filled++; else missed++;
  if(set(document.querySelector('[name=school'), '示例大学')) filled++; else missed++;
  if(set(document.querySelector('[name=major'), '机器学习 / 自然语言处理 / 大数据开发 / 数据科学')) filled++; else missed++;
  if(set(document.querySelector('[name=degree'), '硕士')) filled++; else missed++;
  if(set(document.querySelector('[name=political'), '[待补充]')) filled++; else missed++;
  {var el=document.querySelector('#self'); if(el){ el.style.border='2px solid #e74c3c'; missed++; }}
  alert('已填充 '+filled+' 个字段，未命中 '+missed+' 个（红框）。请人工复核后提交。');
})();