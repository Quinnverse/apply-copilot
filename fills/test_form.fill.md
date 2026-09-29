# 网页表单填充方案 · test_form.html

> 生成时间：2026-09-11T16:18:37+08:00
> ⚠️ 本文件含 PII，请勿外发。真正的提交必须你本人复核后点击。

## 识别到的字段

共识别 8 个字段，其中高/中置信度已自动匹配档案值，低置信度标红需人工补。

## 手动标签表

| 字段 | 值 | 置信度 |
|---|---|---|
| name | `示例姓名]` | 高 |
| mobile | `138-0000-0000]` | 高 |
| email | `you@example.com]` | 高 |
| 毕业院校 | `示例大学]` | 高 |
| 专业 | `机器学习 / 自然语言处理 / 大数据开发 / 数据科学]` | 高 |
| 最高学历请选择本科硕士博士 | `硕士]` | 高 |
| 政治面貌 | `[待补充]]` | 高 |
| self | `[待补充]]` | 低/未命中 |

## 一键填充脚本（粘贴到浏览器控制台）

```javascript
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
```
