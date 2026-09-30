# 多租户隔离（令牌分租户）

> 一句话：**一个访问令牌 = 一个租户 = 一个自包含的数据目录。** 当前代码验证见 `PRIVACY_SECURITY_AUDIT.md`；生产部署状态仍需单独核对。
> 谁的令牌进来，服务端就把这次请求的全部读写指向谁的目录；别的租户的字节一个都读不到。

## 为什么这么做

原来只有一个 `AC_TOKEN`，所有人共用一份数据 —— 你的简历、档案、投递记录会被任何拿到令牌的人看到。
现在不发通用令牌了，改成给每个人发一张专属令牌。

| 对比 | 改造前 | 改造后 |
|---|---|---|
| 身份 | 无（只有一把钥匙） | 令牌 = 身份 |
| 数据位置 | 全部平铺在 `DATA_DIR` | `DATA_DIR/tenants/<tid>/` 一人一份 |
| 互相可见 | 全可见 | 完全不可见（目录级隔离） |
| 新用户初始状态 | 看到上一个人的简历 | 空档案 / 空简历 / 空投递记录 |
| 需要登录页 / 微信授权 | — | 不需要（OAuth 要企业资质，个人开发者做不到） |

## 数据目录布局

```
DATA_DIR/                      # 云端是 /opt/copilot/data
├── tokens.json                # 令牌表（chmod 600，绝不入库）
├── queue_seed.json            # 公共岗位种子：新租户会复制一份
└── tenants/
    ├── t_c26bb101bb88b15f/    # 令牌 A（我）
    │   ├── profile.job.json      档案
    │   ├── resumes.json          简历索引
    │   ├── resumes/*.pdf         简历 PDF
    │   ├── resume_active.json    默认简历
    │   ├── field_memory.json     字段记忆
    │   ├── queue.json            队列状态 / 简历绑定
    │   ├── queue_seed.json       自己的岗位清单
    │   ├── applications.json     投递记录
    │   └── scan_dump.json        扫描诊断
    └── t_fc3282c9e8f19305/    # 令牌 B（朋友试用）—— 同样是空起步
```

每个租户目录**自包含**，删掉一个目录就彻底删掉一个人的全部数据。`tenant id` 是令牌的 SHA256 前 16 位，令牌原文不出现在目录名里。

## 发令牌（服务端操作）

```bash
cd /opt/copilot
export AC_DATA_DIR=/opt/copilot/data          # ⚠️ 必须和 systemd 里的一致，否则写错位置
export AC_APPLY_DIR=/opt/copilot/skill/scripts
export AC_STATIC_DIR=/opt/copilot/static

venv/bin/python tokens.py list                       # 看已有令牌
venv/bin/python tokens.py add 张三                    # 发一张新令牌（打印出来发给本人）
venv/bin/python tokens.py add 我 --token "$AC_TOKEN" --migrate-root
                                                     # 把已有令牌登记成租户，并迁入旧数据
venv/bin/python tokens.py rm  t_xxxxxxxxxxxx          # 吊销（数据目录保留，需手动删）
venv/bin/python tokens.py path t_xxxxxxxxxxxx         # 打印该租户目录
```

令牌表按文件 mtime 自动重载 —— **增删令牌不用重启服务**。

⚠️ 踩过的坑：手动跑 `tokens.py` 时忘了 `export AC_DATA_DIR=...`，令牌表会写到 `/opt/copilot/tokens.json`，
而服务读的是 `/opt/copilot/data/tokens.json`。新版服务模板设置 `AC_REQUIRE_AUTH=1`，令牌文件缺失或损坏时 API 拒绝请求；已部署的旧服务不自动获得这个保护。
每次操作后用 `curl http://127.0.0.1:8787/api/health` 确认 `"auth":true` 且 `"auth_ready":true`。

## 鉴权与接口

- 除 `/api/health` 外，所有 `/api/*` 必须带 `X-AC-Token` 头，否则 401。URL 查询参数中的令牌不再接受，以免令牌进入访问日志或浏览器历史。
- 新接口 `GET /api/whoami` → `{"tenant":"t_xxx","label":"张三","multi_tenant":true}`，
  插件面板标题下会显示「👤 张三 · 独立数据空间」，用来确认自己进的是哪份数据。
- 令牌校验逐个 `hmac.compare_digest`，不早退。

## 本地自用（不配令牌）

不配任何令牌时 `load_tokens()` 为空 → 不鉴权、走 `DEFAULT_PATHS`（原来的平铺布局），行为与改造前完全一致。
只有云端（配了令牌）才启用多租户。

## 验收记录（2026-09-29，服务器实测）

| 检查项 | 结果 |
|---|---|
| 无令牌 / 错令牌访问 `/api/*` | 401 |
| 两个令牌 `whoami` 返回不同 tenant id | t_5eab… / t_91fb… |
| A 上传简历后 B 列表 | B 看不到，A 只看到自己的 |
| A 写档案 / 字段记忆后 B 读取 | B 读到空 |
| A 拿 B 的 resume_id 取文件 | 404（跨租户取不到） |
| 生产 owner 视角 | 57 条岗位、45 条自己的投递记录（旧数据完整迁入） |
| 生产试用令牌视角 | 57 条公共岗位、0 条投递、空档案、空简历 |
