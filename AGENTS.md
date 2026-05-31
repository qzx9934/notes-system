# AGENTS.md

给 Codex/Claude 等代码智能体的项目说明。进入本项目后先读本文件，再按任务需要读取具体源码和文档。

## 项目概览

这是“电厂运行人员工作笔记系统”，用于整理、检索、维护运行工作知识笔记。

- 后端：Flask + SQLite，核心文件 `backend/app.py`
- 前端：原生 HTML/CSS/JS 单页应用，核心文件 `frontend/index.html`
- 数据库：`backend/notes.db`
- API 文档：`API文档.md`
- 用户说明：`使用说明.md`
- 命令行工具：`note_cli.py`
- 测试：`tests/`
- 笔记整理 skill：`.agents/skills/organize-notes/`

## 运行与测试

本地开发运行：

```bash
python backend/app.py
```

访问：

```text
http://localhost:5000
```

后端测试：

```bash
pytest tests/ -q
```

测试使用临时数据库，不应污染 `backend/notes.db`。

## 关键约定

- 不要随意修改或删除 `backend/notes.db`，它是实际用户数据。
- 涉及数据库结构时，优先在 `backend/app.py` 里延续现有自动迁移风格，并补充测试。
- 后端 API 改动后，优先更新 `API文档.md` 和相关测试。
- 前端没有构建链，直接修改 `frontend/index.html`；必要时启动 Flask 后用浏览器检查。
- 前端依赖放在 `frontend/vendor/`，不要默认引入外部 CDN。
- 资料整理和批量上传优先使用 `.agents/skills/organize-notes/` 与 `note_cli.py`。
- API Token、DeepSeek Key、Secret Key 等敏感信息只通过环境变量传递，不写入代码、文档、提交或回复。

## Git 注意事项

- 当前仓库可能有未跟踪的 `.agents/` 和 `.claude/settings.local.json`。
- 提交前先看 `git status --short` 和 diff，确认只提交本次任务相关文件。
- 不要使用 `git reset --hard` 或批量回滚，除非用户明确要求。

## 常见改动入口

- API / 认证 / 数据模型 / AI 功能：`backend/app.py`
- 页面布局 / 交互 / 样式：`frontend/index.html`
- CLI 导入上传：`note_cli.py`
- API 行为说明：`API文档.md`
- 用户使用说明：`使用说明.md`
- 部署说明：`docs/deploy/宝塔部署.md`
- 笔记整理流程：`docs/资料整理工作流程.md`

## 后续协作偏好

- 先读代码和现有文档，再改。
- 改动保持小范围，遵循项目已有风格。
- 能用现有脚本和接口解决的，不新增复杂依赖。
- 完成后说明改了哪些文件、是否跑过测试、还有什么风险。
