# 电厂运行人员工作笔记系统 · API 文档

本系统提供一套 RESTful API，支持通过**命令行**、**脚本**或**大模型流水线**自动整理并上传笔记，无需打开浏览器。

- 基础地址：`http://localhost:5000`（本机部署），或你的实际服务地址
- 数据格式：请求与响应均为 `JSON`（`Content-Type: application/json`）
- 字符编码：`UTF-8`

> 推荐流程：**大模型把零散资料整理成规范 JSON → 通过 API Token 调用 `POST /api/notes/ingest` 一次性上传**。
> 命令行用户可直接使用随附的 `note_cli.py`（见文末）。

---

## 一、认证

写接口需要管理员权限。系统支持两种认证方式，**API Token 是命令行 / 大模型场景的推荐方式**。

### 1. API Token（推荐，无需 Cookie）

在任意写请求上附带请求头之一：

```
X-API-Token: <你的令牌>
```
或

```
Authorization: Bearer <你的令牌>
```

**获取令牌的两种途径：**

| 途径 | 说明 |
| --- | --- |
| 创建持久令牌 | 用管理员账号登录后调用 `POST /api/tokens`，返回的明文令牌**只显示一次**，请妥善保存。 |
| 环境变量主令牌 | 部署服务时设置环境变量 `NOTES_API_TOKEN=xxxx`，该值即为一个始终有效的管理员令牌（适合便携/一次性部署）。 |

令牌在数据库中以 `sha256` 哈希存储，泄露数据库不会暴露原始令牌。

### 2. 会话 Cookie（网页端使用）

`POST /api/login` 后服务端下发会话 Cookie，后续请求自动携带。适合网页交互，不适合脚本。

- 登录响应及 `GET /api/check-auth` 会返回 `default_password` 布尔字段，提示是否仍在使用默认管理员口令。
- **登录失败限流**：同一 IP 连续失败达阈值（默认 5 次 / 5 分钟）后会被临时锁定，期间登录返回 `429`。

### 权限说明

- `admin` 角色：可读可写（增删改），直接生效；可审批共建者的变更申请。
- `contributor`（共建者）角色：可提交 新增/编辑/删除 单条笔记，但**不直接生效**——
  写接口返回 `202` 且生成一条「变更申请」，需管理员在 `/api/proposals` 审批通过后才真正执行。
- `viewer` 角色：仅可读。
- 未认证访问写接口返回 `401`；认证但权限不足返回 `403`。

---

## 二、章节编码体系

每条笔记必须归属一个**章节编码**（`section`）。编码为 5 大领域、26 个子类：

| 领域 | 章节编码与名称 |
| --- | --- |
| **A 系统设备知识** | A01 锅炉及辅助系统 / A02 汽轮机及辅助系统 / A03 电气系统 / A04 热控自动化系统 / A05 辅机系统 / A06 脱硫脱硝环保系统 / A07 化水处理系统 / A08 燃料供应系统 / A09 除灰除尘系统 |
| **B 运行操作知识** | B01 机组启停操作 / B02 正常运行调整 / B03 定期工作与试验 / B04 设备切换操作 / B05 停送电操作 |
| **C 安全管理知识** | C01 安措与两票管理 / C02 事故预案与应急处理 / C03 异常工况判断与处理 / C04 安全规程与制度 |
| **D 技术标准知识** | D01 设备参数与运行限额 / D02 保护定值与联锁逻辑 / D03 运行规程要点 / D04 检修质量标准 |
| **E 综合管理知识** | E01 事故通报与经验反馈 / E02 培训与考试笔记 / E03 值班管理 / E04 技术改造与优化 |

> 运行时可调用 `GET /api/sections` 获取权威的最新列表。

---

## 三、笔记数据模型

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `code` | string | 否（自动生成） | 编号，形如 `A01-001`，由后端按章节自增生成 |
| `section` | string | **是** | 章节编码，如 `A01` |
| `title` | string | **是** | 要点标题 |
| `content` | string | 否 | 内容详情，支持 Markdown |
| `tags` | string | 否 | 关键词标签，**逗号分隔**，如 `MFT,保护` |
| `source` | string | 否 | 来源，默认 `个人总结`。**只能取以下 10 个值之一**（API 强校验，不接受自定义）：规程 / 规章制度 / 技术文件 / 技术通知 / 操作票 / 事故预案 / 事故通报 / 缺陷异常 / 培训 / 个人总结 |
| `level` | string | 否 | 重要等级，**只能为** `★` / `★★` / `★★★`，默认 `★` |
| `note_date` / `date` | string | 否 | 日期，**须为** `YYYY-MM-DD` 格式，默认今天 |
| `source_file` | string | 否 | 来源文件名（含格式，如 `运行规程.docx`）。大模型整理文件录入时自动记录；直接处理文本则留空。**不在总览列表显示**，仅在卡片背面顶部展示 |
| `ai_summary` | string | 只读 | AI 总结正文（Markdown），由 `POST /api/notes/<id>/summarize` 生成并保存，显示在卡片背面 |
| `ai_summary_at` | string | 只读 | AI 总结生成时间；若笔记此后又被更新，前端会提示总结可能已过时 |

> **字段校验：** 单条接口（`POST /api/notes`、`PUT /api/notes/<id>`、`PUT /api/notes/batch`）会严格校验 `section`（须存在）、`level`、`note_date`、`source`，非法时返回 `400`（`PUT /api/notes/<id>` 对 `source` 仅在本次实际改动时校验，以兼容历史遗留的自定义来源）。
> 批量接口（`POST /api/notes/ingest`、`POST /api/notes/batch`）更宽容：非法的 `level`/`date`/`source` 会**自动回退**为默认值（`★` / 今天 / `个人总结`），便于大模型批量上传；但 `section` 非法仍会被跳过。

---

## 四、核心接口：批量录入（推荐）

### `POST /api/notes/ingest` 🆕

**通用批量录入接口** —— 每条笔记可携带自己的 `section`，因此一次请求即可写入多个章节，最适合大模型整理后一次性上传。

**请求头**：`X-API-Token: <令牌>`（admin）

**请求体**：

```json
{
  "notes": [
    {
      "section": "A01",
      "title": "锅炉MFT动作条件",
      "content": "MFT主燃料跳闸条件共16项：炉膛压力高/低、汽包水位高/低...",
      "tags": "MFT,主燃料跳闸,炉膛保护",
      "source": "规程",
      "level": "★★★",
      "date": "2026-05-29"
    },
    {
      "section": "B02",
      "title": "一次调频投入要求",
      "content": "死区±2r/min，限幅±6%",
      "tags": "一次调频",
      "level": "★★"
    }
  ],
  "dedup": true
}
```

**可选顶层参数：**

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `section` | — | 缺省章节；当某条 note 未指定 `section` 时使用 |
| `dedup` | `true` | 是否按「章节 + 标题」去重；命中已有条目时**更新**而非新增 |
| `source_file` | — | 缺省来源文件名（含格式）；某条 note 未指定 `source_file` 时使用。整理同一个文件出的多条笔记可在顶层统一指定。重新整理时若未带 `source_file`，原有值会保留不被清空 |

> 兼容写法：顶层数组可放在 `notes` 或 `entries` 字段下。
> 每条 note 也可单独带 `source_file` 覆盖顶层缺省。

**响应 `200`：**

```json
{
  "ok": true,
  "added": 2,
  "merged": 0,
  "skipped": 1,
  "added_list":  [{"code": "A01-005", "title": "锅炉MFT动作条件"}],
  "merged_list": [],
  "skipped_list": [{"index": 3, "title": "xx", "reason": "未知 section: ZZZ"}]
}
```

- `added`：新建条数；`merged`：命中去重后被更新的条数；`skipped`：被跳过条数（标题为空或章节非法），`skipped_list` 给出每条原因。

> **手动图片自动保留**：去重更新会整体覆盖正文。若旧正文里有你在网页端手动插入的图片（`/uploads/...`）、而新正文不含，系统会把这些图片自动追加到正文末尾（多次重新整理保持幂等，每张图最多一份），因此**重新整理同一条笔记不会丢图**。你的整理大模型无需关心图片，照旧只产文本即可。

---

## 五、其它笔记接口

### `POST /api/notes` —— 新增单条笔记（admin）

请求体见上表字段（`section`、`title` 必填，`code` 自动生成）。响应 `201` 返回完整笔记对象。

### `POST /api/notes/batch` —— 单章节批量追加（admin，旧接口）

需要顶层 `section` + `entries` 数组，**所有条目写入同一章节**；按标题相似（子串）去重。新项目建议优先用 `/api/notes/ingest`。

### `GET /api/notes` —— 查询/搜索笔记

查询参数：`q`（关键词，匹配标题/内容/标签/编号）、`section`、`level`、`source`、`domain`、`sort`（`code`/`updated`/`created`/`random`）、`page`、`per`。
响应：`{ "items": [...], "total", "page", "per", "pages" }`。

> **全文搜索：** `q` 默认走 SQLite FTS5 倒排索引（trigram 分词器，支持中文子串、大小写不敏感），数据量大时显著快于全表扫描。查询不足 3 个字符（trigram 下限）或运行环境不支持 FTS5 时，自动回退到 `LIKE` 模糊匹配，行为一致。索引由触发器与笔记表自动同步，无需维护。

### `GET /api/notes/<id>` —— 获取单条
### `PUT /api/notes/<id>` —— 更新单条（admin，仅传需要改的字段）
### `DELETE /api/notes/<id>` —— 删除单条（admin）
### `PUT /api/notes/batch` —— 批量改字段（admin，`{ids, updates}`，仅允许 `level`/`section`/`source`）
> 当 `updates` 含 `section`（移动章节）时，被移动笔记的编号 `code` 会按新章节自动重新生成，保持编号前缀与所在章节一致。
### `DELETE /api/notes/batch` —— 批量删除（admin，`{ids}`）

### 收藏（每个用户独立）

- `POST /api/notes/<id>/favorite` —— 收藏；`DELETE /api/notes/<id>/favorite` —— 取消收藏（任意登录用户，**仅会话用户**，API 令牌不支持）。
- `GET /api/notes?favorites=1` —— 只返回当前用户收藏的笔记。
- 笔记的查询/详情响应都带 `favorited` 布尔字段，表示当前用户是否已收藏（令牌调用恒为 `false`）。删除笔记时其收藏记录一并清理。

### `GET /api/sections` —— 章节列表（含领域名）
### `GET /api/domains` —— 领域列表
### `GET /api/stats` —— 统计（按等级/来源/章节）

### `POST /api/upload` —— 上传图片（admin）

`multipart/form-data`，字段名 `file`，单张图片，支持 JPG/PNG/GIF/WEBP，默认上限 5MB（可用 `NOTES_MAX_UPLOAD_MB` 调整）。按文件头魔数校验真实类型，文件名取内容 SHA256，内容相同自动去重。

响应：`{"ok": true, "url": "/uploads/<hash>.png", "filename": "...", "size": 1234, "mime": "image/png"}`。

把返回的 `url` 写进笔记 `content` 的 Markdown 即可显示：`![说明](/uploads/<hash>.png)`。网页编辑器已内置「🖼 插入图片」按钮，并支持**直接粘贴截图**和**拖拽图片**自动上传。

> 图片文件存于服务器 `NOTES_UPLOAD_DIR`（默认 `backend/uploads/`），需与数据库一样**持久化**，勿随重新部署清空。

### `GET /uploads/<name>` —— 下发已上传图片（公开，强缓存）

### `POST /api/uploads/cleanup` —— 清理孤儿图片（admin）

回收**无任何笔记引用、且上传超过宽限期**（默认 24h，`NOTES_UPLOAD_GRACE_SECONDS` 可调）的图片文件。删除/编辑笔记时本就会自动清理，此接口用于按需手动触发。宽限期可避免刚上传、还没保存进笔记的图片被误删。

- 传 `?dry_run=1` 仅预览不删除。
- 响应：`{"ok": true, "dry_run": false, "removed": 2, "freed_bytes": 34567, "kept": 5, "removed_list": [...]}`。

### `POST /api/notes/<id>/summarize` —— AI 总结（admin）

调用 DeepSeek 大模型，按「电厂集控运行人员」视角把该笔记内容总结成 Markdown 要点，保存到笔记的 `ai_summary` 字段（显示在卡片背面），可重复调用覆盖。

- 模型/密钥/地址全部走环境变量：`NOTES_DEEPSEEK_API_KEY`（必填，否则返回 `503`）、`NOTES_DEEPSEEK_MODEL`（默认 `deepseek-v4-flash`）、`NOTES_DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）、`NOTES_DEEPSEEK_TIMEOUT`（默认 `60` 秒）。
- 响应：`{"ok": true, "ai_summary": "## 要点…", "ai_summary_at": "2026-05-29 10:00:00"}`。
- 错误码：`400` 笔记内容为空 / `503` 未配置密钥 / `502` 上游调用失败或超时。

### `GET /api/notes/duplicates` —— 查重（admin）

扫描全库，按「标题归一化相等」或「正文相似度 ≥ 阈值（`difflib`）」聚类，返回疑似重复的笔记簇，便于人工核对删除。

- `?threshold=` 正文相似度阈值，0.5~1.0，默认 `0.85`。
- `?scope=section`（默认，仅同章节内查重）或 `?scope=all`（跨章节全库查重）。
- 响应：`{"ok": true, "threshold": 0.85, "scope": "section", "total_notes": 120, "cluster_count": 2, "duplicate_notes": 5, "clusters": [[{"id","code","section","title","note_date","updated_at"}, …], …]}`。

### `POST /api/notes/summarize-batch` —— 一键批量总结（admin）

对一批勾选的笔记批量生成 AI 总结。body：`{"ids": [..], "force": false}`。默认跳过已有总结的，`force=true` 则全部重做；单次上限 50 条。响应：`{"ok": true, "done": N, "skipped": N, "failed": N, "failed_list": [..], "skipped_list": [..]}`。

### `POST /api/ai/fill` —— AI 填充结构化字段（admin / contributor）

根据正文 `content` 调用大模型推断并返回建议的 `title / tags / section / level / source`（**不落库**，由前端填入编辑框）。与 AI 总结共用 DeepSeek 密钥/模型。非法 `section`/`level`/`source` 会被置空。body：`{"content": "正文…"}`。

### `POST /api/ai/tidy` —— AI 整理（admin / contributor）

对正文做"轻度规整"并**同时**返回填充字段，一次调用省 token（**不落库**，前端可撤回）。整理动作：删除排班/通知/时效声明等非知识性内容、规范乱序或格式不统一的小序号、克制改动以防改错原意。body：`{"content": "正文…"}`。响应：`{"ok": true, "content": "整理后正文", "fields": {title, tags, section, level, source}}`。模型未给正文时兜底保留原文。

### `GET/PUT /api/config/ai-prompt` —— AI 提示词（admin）

支持两类提示词，用 `kind` 区分：`summary`（默认，AI 总结）/ `tidy`（AI 整理）。

- `GET /api/config/ai-prompt?kind=summary|tidy`：`{"prompt": "自定义或空", "default": "内置默认", "effective": "实际生效", "is_custom": bool, "kind": "…"}`。
- `PUT`：body `{"prompt": "…", "kind": "summary|tidy"}` 设置自定义提示词；`prompt` 传**空字符串**则恢复内置默认。两类提示词互相独立。

### `GET /api/login-log` —— 登录历史（admin）

`?user_id=` 按用户过滤、`?page=&per=` 分页。响应含 `items:[{id,user_id,username,ip,login_at}]` 与分页字段。`GET /api/users` 返回里也带每个用户的 `last_login_at`（最后上线时间）。

### 变更申请（共建者审批流）

- `GET /api/proposals?status=pending` —— 列出申请。admin 看全部，contributor 仅看自己提交的；含目标笔记当前快照 `current` 供对比，与解析后的 `payload`。
- `POST /api/proposals/<id>/approve`（admin）—— 批准并**真正执行**该变更；若目标笔记已被删除等导致无法执行，会自动驳回并返回 `409`。
- `POST /api/proposals/<id>/reject`（admin）—— 驳回，body 可带 `{"review_note": "原因"}`。

---

## 六、令牌管理接口（admin）

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/tokens` | 列出令牌（不含明文，含 `last_used_at`） |
| `POST /api/tokens` | 创建令牌，体 `{"label": "用途", "role": "admin"}`；响应含**仅此一次**的明文 `token` |
| `DELETE /api/tokens/<id>` | 吊销令牌 |

创建示例：

```bash
# 先用管理员账号登录拿到会话 Cookie
curl -c cookie.txt -X POST http://localhost:5000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}'

# 创建一个供大模型脚本使用的令牌
curl -b cookie.txt -X POST http://localhost:5000/api/tokens \
  -H 'Content-Type: application/json' \
  -d '{"label":"LLM整理脚本","role":"admin"}'
# => {"id":1,"label":"LLM整理脚本","role":"admin","token":"ntk_xxxxxxxx...","created_at":"..."}
```

---

## 七、调用示例

### curl 上传（API Token）

```bash
curl -X POST http://localhost:5000/api/notes/ingest \
  -H 'Content-Type: application/json' \
  -H 'X-API-Token: ntk_xxxxxxxx' \
  -d '{
        "notes": [
          {"section":"A01","title":"磨煤机启动前检查","content":"1.润滑油正常 2.密封风压差≥2kPa","tags":"磨煤机,启动","level":"★★","source":"规程"}
        ]
      }'
```

### Python（标准库，可嵌入大模型流水线）

```python
import json, urllib.request

def upload_notes(notes, base="http://localhost:5000", token="ntk_xxxx"):
    body = json.dumps({"notes": notes}).encode("utf-8")
    req = urllib.request.Request(base + "/api/notes/ingest", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-Token", token)
    with urllib.request.urlopen(req) as r:
        return json.load(r)

print(upload_notes([
    {"section": "C01", "title": "热机工作票审核要点",
     "content": "待许可票核对安措完整性；待签发票核实人员资质",
     "tags": "工作票,审核", "level": "★★★", "source": "个人总结"}
]))
```

---

## 八、命令行工具 `note_cli.py`

仓库根目录附带零依赖的命令行工具，封装了上述接口。

```bash
# 配置（二选一：环境变量或每条命令的 --url/--token 参数）
export NOTES_API_URL=http://localhost:5000
export NOTES_API_TOKEN=ntk_xxxxxxxx

python note_cli.py sections                 # 查看全部章节编码
python note_cli.py add --section A01 --title "MFT动作条件" \
    --content "炉膛压力高/低..." --tags "MFT,保护" --level ★★★ --source 规程
python note_cli.py import notes.json        # 从 JSON 文件批量上传
cat notes.json | python note_cli.py import - # 从标准输入批量上传
python note_cli.py search 给水泵            # 搜索
python note_cli.py stats                     # 统计
```

`import` 接受的 JSON 文件即一个笔记数组（或 `{"notes": [...]}`）：

```json
[
  {"section": "A01", "title": "标题", "content": "内容",
   "tags": "关键词1,关键词2", "level": "★★", "source": "规程"}
]
```

---

## 九、给大模型的提示词模板

把下面这段作为系统/任务提示，模型即可把任意资料整理成可直接上传的 JSON：

```
你是电厂运行笔记整理助手。请把我提供的资料整理成结构化笔记，输出一个 JSON 数组，
数组每个元素是一条笔记，字段如下：
- section：章节编码，必须从下列编码中选择最贴切的一个：
  A01锅炉及辅助系统 A02汽轮机及辅助系统 A03电气系统 A04热控自动化系统 A05辅机系统
  A06脱硫脱硝环保系统 A07化水处理系统 A08燃料供应系统 A09除灰除尘系统
  B01机组启停操作 B02正常运行调整 B03定期工作与试验 B04设备切换操作 B05停送电操作
  C01安措与两票管理 C02事故预案与应急处理 C03异常工况判断与处理 C04安全规程与制度
  D01设备参数与运行限额 D02保护定值与联锁逻辑 D03运行规程要点 D04检修质量标准
  E01事故通报与经验反馈 E02培训与考试笔记 E03值班管理 E04技术改造与优化
- title：要点标题，简洁准确，不超过 30 字
- content：内容详情，可用要点编号，保留关键数字/参数
- tags：3~5 个关键词，用英文逗号分隔
- level：重要等级，★/★★/★★★（涉及保护、跳闸、安全的取 ★★★）
- source：来源，从 规程/规章制度/技术文件/技术通知/操作票/事故预案/事故通报/缺陷异常/培训/个人总结 中选择（仅此 10 项，非法值上传时会被归一为「个人总结」）
只输出 JSON 数组本身，不要任何解释或 Markdown 代码块标记。
```

得到 JSON 后保存为 `notes.json`，运行 `python note_cli.py import notes.json` 或直接 `POST /api/notes/ingest` 上传即可。

---

## 十、状态码

| 码 | 含义 |
| --- | --- |
| `200` | 成功 |
| `201` | 创建成功 |
| `400` | 请求体缺失或参数非法 |
| `401` | 未认证（缺令牌/令牌无效） |
| `403` | 已认证但无管理员权限 |
| `404` | 资源不存在 |
| `409` | 冲突（如用户名已存在） |
| `429` | 登录失败次数过多，被临时限流 |
