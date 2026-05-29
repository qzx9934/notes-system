---
name: organize-notes
description: 把零散工作资料（文本/Word/Markdown/PDF/PPTX）整理成规范的电厂运行工作笔记并上传到笔记系统。当用户给出文件路径或粘贴资料、并希望"整理成笔记/录入/上传到笔记系统/归档"时使用。
---

# 整理并上传工作笔记

把用户提供的资料整理成符合本系统规范的结构化笔记，按章节编码归类，最后通过 API 批量上传。

## 前置：确认上传目标与令牌

笔记上传到**已部署的公网服务器**。开工前确认这两个环境变量已就绪（缺失则问用户要）：

```bash
echo "URL=$NOTES_API_URL  TOKEN设置=${NOTES_API_TOKEN:+yes}"
```

- `NOTES_API_URL`：你的服务地址，如 `https://notes.example.com`
- `NOTES_API_TOKEN`：管理员 API 令牌（形如 `ntk_...`，在网页端「令牌管理」创建）

> 切勿把令牌明文写进任何提交、日志或回复里。只通过环境变量传递。

## 步骤 1 · 抽取原始文本

按来源选择方式：

- **纯文本 / 粘贴内容**：直接用。
- **.md / .txt / .csv / .json**：用 Read 工具读，或 `python .claude/skills/organize-notes/extract_text.py 文件`。
- **.docx / .pptx**：`python .claude/skills/organize-notes/extract_text.py 文件路径`（零依赖，离线可用）。
- **.pdf**：优先用 Read 工具直接读取 PDF；批量或纯文本场景用 `extract_text.py`（需 pdftotext/pypdf/pymupdf 之一）。
- **多个文件**：可一次传多个路径，脚本会按文件分段输出。

## 步骤 2 · 整理成规范 JSON

把内容拆成一条条"笔记"，每条是一个 JSON 对象。字段规范：

| 字段　　　| 必填 | 规则　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　 |
| -----------| ------| ------------------------------------------------------------------------------|
| `section` | 是　 | 章节编码，从下表选**最贴切的一个**　　　　　　　　　　　　　　　　　　　　　 |
| `title`　 | 是　 | 要点标题，简洁准确，≤30 字，能独立看懂　　　　　　　　　　　　　　　　　　　 |
| `content` | 否　 | 内容详情，可用要点编号，**保留关键数字/参数**，支持 Markdown　　　　　　　　 |
| `tags`　　| 否　 | 2~4 个关键词，**英文逗号**分隔　　　　　　　　　　　　　　　　　　　　　　　 |
| `level`　 | 否　 | 仅 `★`/`★★`/`★★★`；涉及保护、跳闸、安全取 `★★★`　　　　　　　　　　　　　　　|
| `source`　| 否　 | 从 规程/培训/操作票/事故预案/事故通报/经验反馈/技术文件/个人总结/规章制度 选 |
| `date`　　| 否　 | `YYYY-MM-DD`，默认今天。API 同时接受 `date` 和 `note_date` 两种字段名　　　 |
| `source_file` | 否 | **来源文件名（含格式）**，如 `运行规程.docx`、`事故通报.pdf`。**当本次整理是基于用户提供的文件时必须填**（同一文件出的多条笔记填同一文件名）；若是直接处理粘贴的纯文本、没有源文件，则**留空不填** |

**章节编码表（5 领域 26 子类）：**

```
A 系统设备：A01锅炉及辅助 A02汽轮机及辅助 A03电气 A04热控自动化 A05辅机
           A06脱硫脱硝环保 A07化水处理 A08燃料供应 A09除灰除尘
B 运行操作：B01机组启停 B02正常运行调整 B03定期工作与试验 B04设备切换 B05停送电
C 安全管理：C01安措与两票 C02事故预案与应急 C03异常工况判断处理 C04安全规程制度
D 技术标准：D01设备参数与限额 D02保护定值与联锁 D03运行规程要点 D04检修质量标准
E 综合管理：E01事故通报经验反馈 E02培训与考试 E03值班管理 E04技术改造与优化
```

> 不确定章节时，调 `GET $NOTES_API_URL/api/sections` 取权威列表。

### 整理原则（必须严格遵守）

1. **一条笔记 = 一个知识点**：一条笔记可以包含多个操作要点，但必须确实是一个知识主题。同一件事故或完整案例可以整理成一条笔记。
2. **标题能独立看懂**：不带上下文也能准确描述该笔记的知识点，≤30 字。
3. **原样保留关键数字**：数字、定值、动作条件务必原样保留，不得杜撰资料中没有的内容。
4. **换行处理**：原始资料有小标题或序号时，注意在笔记 content 中用换行分隔层次。
5. **字数控制**：每条笔记尽量不少于 200 字，也不要超过 1500 字。除非确实是一个完整项目无法拆分（如一个事故案例的全过程或一个完整知识点的系统阐述），否则不得超限。
6. **大文件拆分**：必须在原文档的分节/分章处拆分，不得在连续叙述的段落中间切断。
7. **每条笔记内序号独立重编**：笔记来自正式文档时，必须做编号规范化（见步骤 2.5），不得沿用原文档的章节编号。

把结果写到临时文件 `/tmp/notes.json`，格式为数组或 `{"notes":[...]}`：

```json
[
  {"section":"A02","title":"汽轮机超速保护定值","content":"OPC 103%；OST 110%(3360r/min)","tags":"超速保护,定值","level":"★★★","source":"规程","date":"2026-05-30","source_file":"汽轮机运行规程.docx"}
]
```

> **来源文件**：基于文件整理时，给每条都带上 `source_file`（同一文件填同一值）；也可在上传时统一指定：`python note_cli.py import /tmp/notes.json --source-file 汽轮机运行规程.docx`。直接处理纯文本（无源文件）则不要填。

## 步骤 2.5 · 编号规范化（如来源为正式文档）🔴 必须执行

如果原始资料来自规程/制度等正式文档，笔记内容会带上原文档的章节编号（如 `17.1` `21.3.1`），**必须**规范化为笔记内独立编号。每条笔记的编号从 1 重新开始。

使用随附脚本：

```bash
python .claude/skills/organize-notes-v1/normalize_numbers.py /tmp/notes.json /tmp/notes_fixed.json
```

转换规则：

| 原格式 | 新格式 | 说明 |
|--------|--------|------|
| `17.1` `17.2` `17.3` | `1` `2` `3` | 去掉原文档章节前缀 |
| `21.3.1` `21.3.2` | `3.1` `3.2` | 三段式→两段式，保留子层级 |
| `3 防止锅炉四管泄漏` | `防止锅炉四管泄漏` | 纯数字小标题去数字 |
| `0.25MPa` / `0.6kPa` | 不动 | 参数值 X=0 自动跳过 |

也可在 Python 中直接调用函数：

```python
from normalize_numbers import normalize_numbers
note['content'] = normalize_numbers(note['content'])
```

**重要**：每条笔记的编号独立重新开始，不要沿用原文档的章节号。参数值（`0.25MPa`、`0.6kPa`、`120℃`等）会被自动识别并保留。脚本使用单次正则 pass 处理，避免多步顺序替换导致的三段式 `1.1` 被二次错误匹配。

## 步骤 3 · 上传

> ⚠️ **严禁使用 PowerShell 的 `Invoke-RestMethod` 上传含中文的 JSON！** PowerShell 的 `ConvertTo-Json` + `Invoke-RestMethod` 组合会导致中文字符全部变成问号（`?`），这是已知的编码损坏问题。
>
> **必须使用 Python 上传**，Python 的 `urllib` 配合 `json.dumps(ensure_ascii=False).encode('utf-8')` 能正确保留所有中文字符。

### API 接口速查

| 接口 | 方法 | 用途 | 关键参数 |
|------|------|------|---------|
| `/api/notes/ingest` | POST | **批量录入（推荐）**，支持跨章节 | `notes` 数组 + `dedup`（默认 true）。顶层可选 `section` 作为缺省章节。也接受 `entries` 作数组键名 |
| `/api/notes` | POST | 新增单条 | `section`、`title` 必填。严格校验 `level`/`date`，非法返回 400 |
| `/api/notes/<id>` | PUT | 更新单条（任意字段） | 只传需要变更的字段即可 |
| `/api/notes/<id>` | DELETE | 删除单条 | — |
| `/api/notes/batch` | PUT | 批量改字段 | **仅允许改 `level`/`section`/`source`，不能改 content！** 改 `section` 时编号会自动重编 |
| `/api/notes/batch` | DELETE | 批量删除 | `{"ids": [...]}` |
| `/api/notes` | GET | 查询/搜索 | `q`（关键词）、`section`、`level`、`source`、`sort`、`page`、`per`。走 FTS5 全文索引 |
| `/api/sections` | GET | 章节列表 | 含领域名 |
| `/api/stats` | GET | 统计 | 按等级/来源/章节分布 |

**校验差异**：
- 单条接口（POST/PUT 单条）：严格校验 `section`、`level`、`date`，非法返回 `400`
- 批量接口（ingest）：更宽容——非法的 `level`/`date` 自动回退默认值（`★` / 当天），但 **`section` 非法仍会被跳过**

**去重逻辑**：ingest 接口按「章节 + 标题」去重。命中已有条目时**更新**而非新增。响应中 `added` 为新建数、`merged` 为更新数、`skipped` 为跳过数（附带原因列表）。

### 3a · 上传新增笔记（ingest，去重合并）

```python
import json, urllib.request, os

token = os.environ['NOTES_API_TOKEN']
url = os.environ['NOTES_API_URL'] + '/api/notes/ingest'

with open('/tmp/notes.json', 'r', encoding='utf-8') as f:
    notes = json.load(f)

body = json.dumps({'notes': notes, 'dedup': True}, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(url, data=body, method='POST')
req.add_header('Content-Type', 'application/json; charset=utf-8')
req.add_header('X-API-Token', token)

with urllib.request.urlopen(req) as r:
    result = json.loads(r.read().decode('utf-8'))
    print(f"added={result['added']} merged={result['merged']} skipped={result['skipped']}")
```

### 3b · 更新已有笔记的 content（PUT 逐条）

> 注意：批量改字段接口 `/api/notes/batch` **不支持 content 字段**。如需更新 content，必须逐条 PUT。

```python
for n in notes:
    update = json.dumps({'content': n['content']}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f"{url}/api/notes/{n['id']}", data=update, method='PUT')
    req.add_header('Content-Type', 'application/json; charset=utf-8')
    req.add_header('X-API-Token', token)
    urllib.request.urlopen(req)
```

### 3c · 备选：CLI 工具

```bash
python note_cli.py import /tmp/notes.json
```

> `note_cli.py` 内部也使用 Python urllib，编码是安全的。

## 步骤 4 · 回报结果

读响应里的 `added`（新增）/ `merged`（更新）/ `skipped`（跳过及原因），向用户汇报。
若有 `skipped`（多为章节非法或标题为空），列出 `skipped_list` 中每条的原因并提议修正后重传。

## 常见问题与踩坑记录

### Word 智能引号导致 400 错误

从 Word 文档提取的内容可能包含弯引号（`"` U+201C / `"` U+201D），nginx 会拒绝这些字符，返回 `400 Bad Request`。

**处理**：上传前替换为普通引号：

```python
content = content.replace('\u201c', '"').replace('\u201d', '"')
```

### PowerShell 编码损坏

**症状**：上传后所有中文字符变成 `?`。
**原因**：PowerShell 的 `Invoke-RestMethod` 与 `ConvertTo-Json` 在处理中文时编码处理不可靠。
**解决**：永远用 Python urllib 上传（见步骤 3）。

### 编号规范化不要多步正则

使用单次正则 pass 处理所有编号（包含回调函数判断两段式/三段式），避免三步顺序替换导致的二次匹配问题（如三段式生成的 `1.1` 被后续两段式正则在第二轮错误匹配为 `1`）。

### 环境变量检查

如果 Python 脚本连不上服务器但 PowerShell 可以，先检查 DNS/代理设置。可用 `curl -v` 诊断，或直接用 PowerShell 做连通性测试后切回 Python 上传。

### 注意日期来源

笔记日期优先使用文件内标注的日期（如文件末尾或标题下的日期），而非整理当天的日期。例如文件标注"二〇二六年五月二十五日"→ `date: "2026-05-25"`。

### 忽略署名行

文件末尾的专业署名行（如"发电部锅炉专业"、"发电部电气专业"等）不是知识点，不写入笔记。

## 随附脚本一览

| 脚本 | 用途 |
|------|------|
| `extract_text.py` | 从 docx/pptx/pdf/txt 抽取纯文本 |
| `normalize_numbers.py` | 将原文档章节编号转换为笔记内独立编号 |
| `note_cli.py` | 命令行工具：增/查/导入/统计 |
