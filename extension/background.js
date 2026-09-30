// 网申助手 Copilot —— background service worker
// 角色：浏览器扩展与本地后端(http://127.0.0.1:8787)之间的 HTTP 客户端桥接。
// 不代登录、不自动提交；只做"准备材料 + 记录"的辅助请求。

const BASE = "http://127.0.0.1:8787";

async function api(path, opts) {
  const resp = await fetch(BASE + path, opts);
  if (resp.status === 409) {
    const e = await resp.json().catch(() => ({}));
    return { error: e.detail || "已记录过" };
  }
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    return { error: e.detail || ("HTTP " + resp.status) };
  }
  // 文件接口返回 blob
  if (path.startsWith("/api/resume-file")) {
    const name = (resp.headers.get("content-disposition") || "")
      .split("filename=")[1] || "resume.pdf";
    const buf = await resp.arrayBuffer();
    const b64 = base64FromArrayBuffer(buf);
    return { ok: true, name: name.replace(/"/g, ""), dataUrl: "data:application/pdf;base64," + b64 };
  }
  return { ok: true, json: await resp.json() };
}

function base64FromArrayBuffer(buf) {
  let binary = "";
  const bytes = new Uint8Array(buf);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

// 消息路由：popup / content 都通过这里访问后端
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {
        case "getResumes":
          sendResponse(await api("/api/resumes"));
          return;
        case "getProfile":
          sendResponse(await api("/api/profile"));
          return;
        case "putProfile":
          sendResponse(await api("/api/profile", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(msg.profile || {}),
          }));
          return;
        case "getQueue":
          sendResponse(await api("/api/queue"));
          return;
        case "match":
          sendResponse(await api("/api/match", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ jd: msg.jd || "" }),
          }));
          return;
        case "fill":
          sendResponse(await api("/api/fill", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fields: msg.fields || [], jd: msg.jd || null }),
          }));
          return;
        case "mark":
          sendResponse(await api("/api/mark", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(msg.payload || {}),
          }));
          return;
        case "resumeFile":
          sendResponse(await api("/api/resume-file/" + encodeURIComponent(msg.id)));
          return;
        default:
          sendResponse({ error: "unknown type: " + msg.type });
      }
    } catch (e) {
      sendResponse({ error: String(e) });
    }
  })();
  return true; // 保持消息通道开放，等待异步响应
});

// 仅在用户先于 popup 明确允许过的网站，后续同站页面完成加载后再注入。
// 未获允许的网站没有内容脚本，也不会把页面字段发送到后端。
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !/^https?:\/\//.test(tab.url || "")) return;
  const url = new URL(tab.url);
  const origin = `${url.protocol}//${url.hostname}/*`;
  chrome.permissions.contains({ origins: [origin] }, (granted) => {
    if (!granted) return;
    chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] }).catch(() => {});
  });
});

// 启动提示（仅本机）
console.log("[网申助手] background ready，后端", BASE);
