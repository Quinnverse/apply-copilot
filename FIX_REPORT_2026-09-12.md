# 网申助手 · 缺陷修复完成报告

日期：2026-09-12
缺陷清单来源：`review_2026-09-12.md`
验证结论：**IS_PASS: YES**（QA 第 2 轮独立回归，14 项全部闭环）

---

## 一、交付状态

| 项 | 结果 |
|---|---|
| P0（3 项） | 全部修复并通过独立验证 |
| P1（7 项） | 全部修复并通过独立验证 |
| P2（4 项） | 全部修复并通过独立验证 |
| py_compile（6 个 py） | 全过 |
| node --check（assistant.js） | 过，8 个占位符无残留 |
| 离屏 Chromium e2e | 基线未退化（r1–r4 全 true、面板 chips 各 12） |

---

## 二、P0 修复

### P0-1 助手②「记录已投」只翻徽章、不真入库
- `assistant.js` `doRecord` 改为 `POST /api/mark`（带 company / channel / resume_version），不再走 pywebview polyfill。
- `server.py` `api_mark` 的 `MarkReq.title` 改为可选；title 缺失时按 company 反查 `queue_seed` 的 role 作默认标题。
- `app_desktop_qt.py` 的 `RECORD_SHIM` 假入库已删除。
- **返修记录**：首轮改完仍有死代码 —— `:435`/`:453` 把算好的局部 `title` 丢掉、仍传 `req.title`，导致入库标题为空。QA 第 1 轮抓到，已改为 `title=title`。现验证：只传 company 时，`cmd_mark` 收到的 title = seed role「具身多模态大模型」非空。

### P0-2 只有队列标签页注入助手
- 新增 `_company_for_url`（按 host 反查队列）+ `_inject_into`（loadFinished 触发）。
- 任意 http(s) 页面加载都注入；`127.0.0.1` / localhost 跳过。
- 验证：外部 URL 自动出现 🛠 浮标（含手动地址栏、新标签页路径），本地仪表板不重复注入。

### P0-3 简历推荐打分子串匹配、无阈值
- 新增 `RESUME_SYNONYMS` 同义词字典 + `_tag_hit()`（字面或同义词命中）；algo/dev signals 扩充。
- 返回 `weak: total < 0.3`，前端展示「无强匹配，请手选」。

---

## 三、P1 修复

| 项 | 修法 |
|---|---|
| P1-4 已记录判定误判 | `company_matches()` = NFKC 规范化精确相等 + `COMPANY_ALIAS` 别名白名单分组；**删除子串包含兜底** |
| P1-5 select 静默失败 | `normEdu` 归一化（去全日制/统招/学历/学位等噪音）；三级匹配，全不中则红框 `data-ac-miss` 计入未命中 |
| P1-6 多值档案值错填 | 新增 `isMultiValue`（JS）/ `is_multi_value`（Python），多值跳过子串匹配，只认精确/归一相等，否则标红 |
| P1-7 跨域 iframe 无提示 | 扫描为 0 或 filled=0 且存在 iframe 时给出明确提示 |
| P1-8 radio 性别填不了 | radio 移出排除列表，新增 `setValRadio`（按 label/aria/value 匹配） |
| P1-9 多余假事件 | 删除 `keydown('a')`；验证 keydown=0 而 input=1/change=1（真事件保留） |
| P1-10 跨站记忆失效 | `ruleKeyOf()` 作为记忆 key（跨站稳定）；`app_desktop_qt.py:246` 改为无条件取记忆 |

---

## 四、P2 修复

- **P2-11** 新建 `assistant_bridge.py` 承载 `build_assistant_js` 等，**不 import webview**；qt 版与 pywebview 版解耦。
- **P2-12** `filler.FIELD_SYN` 作唯一真源，JS 端 SYN 由 `assistant_bridge.py` 序列化注入，消除双份匹配表漂移。
- **P2-13** `/api/research` 返回 `task_id` + `status`；新增 `GET /api/research/status/{task_id}`（查不到 404）。
- **P2-14** dashboard `markRecorded` 不再用 `prompt()` 取 title，直接取 role。

---

## 五、使用方式

重启生效（后端有 BUILD_ID 版本校验，旧进程会提示版本不一致）：

```
start_copilot.bat
```

助手浮标按钮：①填充 / ②记录已投（真入库）/ ③记住本页字段 / ④点选填充 / 📋档案速查。

---

## 六、已知限制（非阻塞）

1. **公司别名需人工维护**：`COMPANY_ALIAS`（13 组）内嵌 `server.py:162`。新增公司若出现「简称 vs 全称」未登记 → 漏配（表现为重复投递提醒不准，属**安全方向的假阴性**）。建议后续外置为 `company_alias.json`。
2. **跨域 iframe 只能提示、无法填充**：浏览器安全限制，需改用官网直链。
3. **多值 select 一律标红**：意向城市等多值字段不自动填，需走④点选。语义正确（宁可不填也不错填），但红框可能被误认为出错。
4. **标签归属偶发偏差**：`labelOf` 取相邻兄弟/容器兜底，少数字段标签会认错。
5. **性别仍无法自动填**：`profile.job.json` 性别为 `[待补充]`，补全档案即可（radio 机制本身已验证可用）。
6. **未在真实招聘门户实测**：以上均为离屏模拟页验证，SPA 受控组件命中率建议首次真实使用时抽样核对。

---

## 七、验证资产

- `_e2e_setval.py` — 基础填充基线（input/select/textarea/radio）
- `_qa_e2e_extended.py` — QA 扩展用例（噪音词归一、必失配、仅 label radio、keydown 计数器等）
- `_qa_inject_check.py` / `_qa_inject_check2.py` — P0-2 注入机制 A/B 验证
- `_qa2_selftest.py` / `_qa3_*` — 第 2 轮复验脚本
