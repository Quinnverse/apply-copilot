# 网申助手 Application Copilot

一个**半自动、人类在环**的校招网申辅助工具（Python 3.11+；CLI 使用标准库，后端依赖 `deploy/requirements.txt`）。

## 当前 Browser Extension MVP

先读 [MVP_READINESS_REPORT.md](MVP_READINESS_REPORT.md)、[PRODUCT_AUDIT.md](PRODUCT_AUDIT.md) 和 [EXTENSION_AUDIT.md](EXTENSION_AUDIT.md)。后端可从干净仓库启动：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r deploy/requirements.txt  # Windows
.venv/Scripts/python server.py
```

在 Chrome/Edge 加载 `extension/` 后，点扩展图标填写基础档案。打开网申页后，先在 popup 点「在当前网站启用填表助手」；之后点 🛠 →“填充表单”，逐项核对建议并勾选，再点“填充勾选字段”。最后检查网页，提交由本人完成。后端默认只监听本机，档案写在本机 `profile.job.json`。本地 HTTP API 限制浏览器跨域来源；如使用油猴脚本从招聘页直连后端，需要显式设置 `AC_ALLOWED_ORIGINS`。

## 它做什么 / 不做什么

| 做 ✅ | 不做 ❌ |
|---|---|
| 结构化档案 → 一键"字段速填表" | 代替你登录（各系统要本人账号 + 短信/人脸） |
| 依据真实经历生成"匹配要点 + 高频问答草稿" | 破解验证码 / 滑块 / 风控 |
| 生成"投递 Checklist + 提交后记录命令" | 批量自动提交 |
| 与投递追踪库 `apply.py` 打通 | 编造简历里没有的经历 |

**为什么不做全自动提交**：① 技术上不可靠——每个公司 ATS 不同、风控随时变、验证码多为人工；② 合规风险——多数平台 ToS 禁止自动化提交，可能导致账号被封。真正"提交"这一步必须由你本人完成。

## 目录

```
apply-copilot/
├── copilot.py         # 主程序
├── profile.job.json   # 结构化档案（含 PII，勿外发）
├── kits/              # 生成的申请包（含 PII，勿外发）
└── README.md
```

## 快速开始

```bash
cd apply-copilot

# 0) 注册多份简历版本（首次）
python3 copilot.py register-resume --id algo-v1 \
  --path "C:/Users/you/Downloads/简历.pdf" \
  --tags "LLM Agent,Agent后训练,大模型算法,强化学习,GRPO,Reward,后训练,多模态算法,算法"
python3 copilot.py register-resume --id agent-dev-v1 \
  --path "C:/Users/you/Downloads/简历2.pdf" \
  --tags "Agent开发,AI应用工程,LLM Agent系统,GUI Agent,多模态Agent,工程化,开发,VLM,Grounding,OCR"

# 1) 从求职画像生成结构化档案（首次 / 档案更新时）
python3 copilot.py init-profile \
  --skill-profile "C:/Users/you/.workbuddy/skills/autumn-recruitment-tracker/resumes/profile.json" \
  --out profile.job.json

# 2) 网申前：根据 JD 推荐简历 + 生成申请包
python3 copilot.py match --jd jd.txt
python3 copilot.py kit --profile profile.job.json \
  --company "淘天" --title "大模型算法工程师" --jd jd.txt --outdir kits

# 3) 自动填充：把招聘页源码保存为 page.html，然后生成填充脚本
python3 copilot.py fill --profile profile.job.json --html page.html --outdir fills

# 4) 网申后：记录进投递库（带上简历版本，方便统计过筛率）
python3 copilot.py mark --profile profile.job.json \
  --company "淘天" --title "大模型算法工程师" --resume-version algo-v1
```

## 申请包内容

1. **字段速填表** — 姓名/手机/邮箱/院校/专业/起止/届别/求职方向/期望城市，照抄进表单。
2. **岗位匹配要点** — 从真实经历提炼的 Claim + 证据 + 可能被追问的短板。
3. **高频问答草稿** — 自我介绍（自动从档案拼）、为什么选我们、职业规划、项目深挖。空白项标 `[待补充]`，需你按公司补，**不编造**。
4. **投递 Checklist** — 从登录到提交的人工步骤清单。
5. **记录命令** — 提交后把这行粘到终端即可入库。

## 安全与合规

- 档案与申请包含手机号 / 邮箱等 PII，**仅本地保存，勿外发**。
- 本工具不读取任何凭据，不联网，不写日志。
- 危险动作（提交）永远是人工执行；工具只准备材料。

## 浏览器扩展 + 本地后端（已落地）

把上面的能力做成可一键操作的形态，契合「结合投递链接清单逐个投递 + 投完立即记录」。

```bash
cd apply-copilot
python server.py                 # 启动本地后端 http://127.0.0.1:8787
# 浏览器打开 http://127.0.0.1:8787/ 即状态化投递队列仪表板
```

- **后端** `server.py`：封装 `copilot.py` / `filler.py` / `apply.py`，暴露
  `/api/health` `/api/resumes` `/api/match` `/api/fill` `/api/queue(+status)` `/api/mark` `/api/resume-file`。
- **仪表板** `static/dashboard.html`：57 家清单带 未投/进行中/已记录 状态徽章，可匹配简历、标记已记录。
- **扩展** `extension/`（MV3）：popup 选当前目标公司 + 匹配简历；content 扫描表单、填充、上传简历、检测提交成功页并弹记录气泡；background 作 HTTP 桥接。
- **队列种子** `queue_seed.json`：重跑 `gen_submit_list.py` 时**自动同步导出**（从主数据 `D` 直接生成，单一数据源），与 `applications.json` 合并出真实状态。无需单独跑 `gen_queue_seed.py`（该脚本已废弃，仅留作参考）。

详细安装与用法见 `extension/README.md`。

## 旧版书签工具（仅限本机自行使用）

`gen_bookmarklet.py` 会把档案值直接写入 `static/assistant.bookmarklet.js`。这个文件包含个人信息，不再提交到 Git、部署到服务器或经 `/static` 提供下载。当前推荐使用上面的扩展流程。

1. `cd apply-copilot && python server.py` 启动后端。
2. 本机运行 `python gen_bookmarklet.py` 后，只在本机读取生成文件；不要把文件上传、分享或复制到公共网页。

该工具是旧版路径，不经过扩展的逐字段确认与兼容性回归。

**合规边界不变**：不代登录、不破解验证码、不自动提交；提交永远是你本人。

## 下一步（可选，需你确认）

浏览器自动化层（Playwright / agent-browser）：只做「打开官网 → 导航到岗位 → 预填已知字段 → 截图」，**验证码与提交仍由你本人完成**。在没确认前不会做，因为它会显著增加脆弱性与合规风险。

## 桌面应用助手浮标（内嵌浏览器版）

启动：`start_copilot.bat`（PyQt6 + QtWebEngine，单窗口：左侧助手栏 + 右侧多标签内嵌浏览器）。
注入脚本在 **`assistant.js`**（不再是内联字符串），改完重启即生效。

浮标按钮：
1. **① 填充表单** —— 扫描可见字段 → 规则/同义词/记忆三级匹配 → 用原生 setter 写入（兼容 React 受控组件）。
2. **④ 点选填充** —— 打开后点页面上任意输入框 → 面板列出档案值 → 选一个即填入并**记住**（下次所有站点自动命中）。
   这是关键词匹配失效时的兜底，任何 DOM 结构都能填。
3. **③ 记住本页字段** —— 把本页已填（含你手填的）全部沉淀到 `field_memory.json`（**全局，不按站点分桶**）。
4. **📋 档案速查** —— 点一下复制，填不进去时至少能秒粘贴。
5. **② 记录已投** —— 回写队列状态。

匹配优先级：`已记住的值(1.0)` > `FIELD_RULES 关键词(带类型白名单)` > `关键词(忽略类型)` > `宽松同义词` > `input type 兜底`。
`[待补充]` 这类占位值不会写入。

诊断：每次填充会把「扫到了哪些字段、填了几个」POST 到 `/api/scan-dump`，落盘 `scan_dump.json`（保留最近 20 次）。
匹配效果差时直接看这个文件即可定位（标签抓错 / 跨域 iframe / 未登录）。

冒烟测试：`python _e2e_setval.py`（离屏真实 Chromium，跑 扫描→匹配→填充→面板 UI 四步，结果写 `_setval_result.json`）。
