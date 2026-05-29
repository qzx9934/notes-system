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

把内容拆成一条条"要点"，每条是一个 JSON 对象。字段规范：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `section` | 是 | 章节编码，从下表选**最贴切的一个** |
| `title` | 是 | 要点标题，简洁准确，≤30 字 |
| `content` | 否 | 内容详情，可用要点编号，**保留关键数字/参数**，支持 Markdown |
| `tags` | 否 | 3~5 个关键词，**英文逗号**分隔 |
| `level` | 否 | 仅 `★`/`★★`/`★★★`；涉及保护、跳闸、安全取 `★★★` |
| `source` | 否 | 从 规程/培训/工作票/事故预案/事故通报/经验反馈/技术文件/个人总结 选 |
| `date` | 否 | `YYYY-MM-DD`，默认今天 |

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
> 整理原则：一条笔记只讲一个要点；标题能独立看懂；数字、定值、条件务必原样保留；不要杜撰资料里没有的内容。

把结果写到临时文件 `/tmp/notes.json`，格式为数组或 `{"notes":[...]}`：

```json
[
  {"section":"A02","title":"汽轮机超速保护定值","content":"OPC 103%；OST 110%(3360r/min)","tags":"超速保护,定值","level":"★★★","source":"规程"}
]
```

## 步骤 3 · 上传（去重合并）

优先用随附 CLI（零依赖）：

```bash
python note_cli.py import /tmp/notes.json
```

或直接调 ingest 接口（按「章节+标题」去重，命中则更新而非新增）：

```bash
curl -s -X POST "$NOTES_API_URL/api/notes/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $NOTES_API_TOKEN" \
  --data-binary @/tmp/notes.json
```

## 步骤 4 · 回报结果

读响应里的 `added`（新增）/ `merged`（更新）/ `skipped`（跳过及原因），向用户汇报。
若有 `skipped`（多为章节非法或标题为空），列出并提议修正后重传。

## 注意

- 批量接口对非法 `level`/`date` 会自动回退默认值；但 `section` 非法会被跳过——务必选对章节。
- 资料较多时分批整理上传，每批先给用户看 1~2 条样例确认风格，再整体跑。
- 清理临时文件：`rm -f /tmp/notes.json`。
