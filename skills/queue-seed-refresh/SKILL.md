---
name: queue-seed-refresh
description: 秋招官网投递清单的检索与并入。当用户要求"找新岗位/补充投递清单/刷新 queue_seed/调研 2026 秋招官网投递入口"时使用。检索岗位 → 按固定 schema 组装 → 调 /api/queue-merge 确定性并入（不要手写 JSON 文件）。
agent_created: true
---

# queue-seed-refresh · 投递清单检索与并入

你是秋招投递清单的检索员。目标：找到**可以直接官网网申**的 2026 届秋招岗位，把它们**确定性地并入**本地投递清单（queue_seed.json）。

## 检索约束（全部满足才收录）

1. **岗位方向**：算法 / AI / 大模型 / LLM / Agent / 具身智能 / 智驾 / AIGC / 量化 / AI Infra 方向优先。
2. **Base 地点**：浙江 / 上海 / 江苏优先，其余城市仅在岗位特别强时收录。
3. **排除**：央国企、华为、小米、银行（政策或用户明确排除）；纯硬件/非算法岗不收。
4. **批次**：2026 秋招正式批 / 提前批（2026 年 9-11 月在网期）。
5. **每条必须带官网投递 URL**：校招系统 / 官网 careers 页的真实入口（如 `campus-talent.alibaba.com`、`talent.antgroup.com`）。**找不到官网投递 URL 的岗位一律不入清单**（BOSS/猎聘链接不算）。
6. 每次检索 5-15 条即可，宁缺毋滥；截止日期必须给出（查不到写"招满即止"）。

## 固定输出 schema（与 queue_seed.json 一字不差）

每条 item 必须且只能包含以下字段，类型如下：

```json
{
  "id": "公司名（全清单内唯一；同公司多岗位用 公司名·岗位名）",
  "company": "公司名",
  "cat": "必补大厂|具身智驾|量化私募|智驾中厂|中小厂-具身|中小厂-大模型Infra|AI芯片|互联网中厂 之一",
  "role": "岗位方向名",
  "sal": "薪资或'面议(高)'等一句话",
  "loc": "城市1/城市2",
  "deadline": "网申9/26截止! 或 正式批统一10/30 或 10/30",
  "urg": "urgent|near|open（只是初值，后端会按 deadline 重算，可空串）",
  "ltype": "官网",
  "url": "https://官网投递入口"
}
```

完整示例（可直接作为 items 传参）：

```json
[
  {
    "id": "蚂蚁集团",
    "company": "蚂蚁集团",
    "cat": "必补大厂",
    "role": "LLM/算法（正式批）",
    "sal": "正式批多方向",
    "loc": "杭州/上海",
    "deadline": "正式批统一10/30",
    "urg": "near",
    "ltype": "官网",
    "url": "https://talent.antgroup.com/campus/home"
  },
  {
    "id": "深言科技",
    "company": "深言科技",
    "cat": "中小厂-大模型Infra",
    "role": "LLM算法",
    "sal": "面议(高)",
    "loc": "北京",
    "deadline": "10/20",
    "urg": "",
    "ltype": "官网",
    "url": "https://www.deeplang.ai/join"
  }
]
```

注意：
- `id` 若与已有清单同公司同岗位会自动去重；同公司**新岗位**会自动追加为多岗位，不必担心覆盖。
- 已投递过的公司（applications.json 里有记录，含别名如"宽德"↔"宽德投资"）会被后端自动剔除。
- `urg` 不用猜，后端 refresh_queue 会按 deadline 重算（≤7天 urgent / ≤21天 near / 其余 open / 过期 expired）。

## 落地动作（做完检索后必须执行）

**不要**直接改写 queue_seed.json / queue.json 文件。把上述 items 数组 POST 给后端。

后端有两种运行方式，**优先用云端**（不用每次都开本地服务）：

| 模式 | Base URL | 认证 |
|------|----------|------|
| 云端（推荐） | `http://124.223.15.11:8787` | 请求头 `X-AC-Token: <令牌>` |
| 本地 | `http://127.0.0.1:8787` | 无（本地默认不开 token） |

```
POST {BASE}/api/queue-merge
Content-Type: application/json
X-AC-Token: <令牌>            # 仅云端需要

{"items": [ ...上述 schema 的数组... ]}
```

云端令牌存在用户配置里（`apply-copilot` 的 `SET.token` / 部署时生成的 `AC_TOKEN`）；**先读一下 `apply-copilot/.cloud_token`（若存在）或询问用户**，不要瞎猜。若云端 401，说明令牌不对，提示用户核对；若云端连接超时，回退到本地模式并提示用户启动 `python server.py`。

- 后端会确定性执行：时间衰减重算 urg → 剔除已投 → 同公司同岗位去重 / 新岗位追加 → 排序写回 queue_seed.json 并同步 queue.json。
- 返回 `{"ok":true,"added":N,"merged":N,"removed_recorded":N,"total":N}`，把这几个数字原样报给用户。
- 后端不可达（云端超时且 127.0.0.1:8787 也没起）时：提示用户先启动 `python server.py`，**不要**退回手写 JSON。
- 若用户要求"从收件箱合并"（AI 调研回写已在 research_inbox.json），POST `{"source":"inbox"}` 即可。

## 红线

- 绝不编造 URL / 截止日期；查不到就如实说查不到。
- 绝不写入 applications.json（那是真实投递记录，只有投递成功才由助手自动记）。
