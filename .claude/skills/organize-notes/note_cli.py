#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电厂运行人员工作笔记 · 命令行工具 (note_cli.py)

通过 API Token 在命令行 / 脚本 / 大模型流水线中读写笔记，无需浏览器登录。
仅依赖 Python 标准库，可直接拷贝到任意机器运行。

配置（命令行参数优先，其次环境变量）：
    --url    服务地址      默认 $NOTES_API_URL 或 http://localhost:5000
    --token  API 令牌      默认 $NOTES_API_TOKEN

获取令牌：登录系统后调用 POST /api/tokens 创建，或部署时设置环境变量
NOTES_API_TOKEN 作为主令牌。

常用命令：
    # 列出全部章节编码（写笔记前先确认 section）
    python note_cli.py sections

    # 新增单条笔记
    python note_cli.py add --section A01 --title "MFT动作条件" \
        --content "炉膛压力高/低..." --tags "MFT,保护" --level ★★★ --source 规程

    # 从 JSON 文件批量上传（最适合大模型整理后导入）
    python note_cli.py import notes.json

    # 从标准输入读取 JSON 批量上传
    cat notes.json | python note_cli.py import -

    # 搜索 / 统计
    python note_cli.py search 给水泵
    python note_cli.py stats

JSON 文件格式（数组，或 {"notes": [...]}）：
[
  {"section": "A01", "title": "标题", "content": "内容",
   "tags": "关键词1,关键词2", "level": "★★", "source": "规程",
   "date": "2026-05-29"}
]
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error


def _request(method, base_url, path, token, payload=None):
    url = base_url.rstrip('/') + path
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('X-API-Token', token)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode('utf-8')
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {'error': body}
    except urllib.error.URLError as e:
        print(f'✗ 无法连接服务 {url}: {e.reason}', file=sys.stderr)
        sys.exit(2)


def _check_auth(status, resp):
    if status == 401:
        print('✗ 未授权：请通过 --token 或环境变量 NOTES_API_TOKEN 提供有效令牌', file=sys.stderr)
        sys.exit(1)
    if status == 403:
        print(f'✗ 权限不足：{resp.get("message", resp.get("error", ""))}', file=sys.stderr)
        sys.exit(1)


def cmd_sections(args):
    status, resp = _request('GET', args.url, '/api/sections', args.token)
    _check_auth(status, resp)
    if status != 200:
        print(f'✗ 获取章节失败: {resp}', file=sys.stderr)
        sys.exit(1)
    domain = None
    for s in resp:
        if s.get('domain') != domain:
            domain = s.get('domain')
            print(f'\n[{domain}] {s.get("domain_name", "")}')
        print(f'  {s["code"]}  {s["name"]}')


def cmd_add(args):
    note = {
        'section': args.section,
        'title': args.title,
        'content': args.content or '',
        'tags': args.tags or '',
        'source': args.source or '个人总结',
        'level': args.level or '★',
    }
    if args.date:
        note['note_date'] = args.date
    if getattr(args, 'source_file', None):
        note['source_file'] = args.source_file
    status, resp = _request('POST', args.url, '/api/notes', args.token, note)
    _check_auth(status, resp)
    if status == 201:
        print(f'✓ 已新增 {resp["code"]}  {resp["title"]}')
    else:
        print(f'✗ 新增失败: {resp.get("error", resp)}', file=sys.stderr)
        sys.exit(1)


def cmd_import(args):
    raw = sys.stdin.read() if args.file == '-' else open(args.file, encoding='utf-8').read()
    try:
        parsed = json.loads(raw)
    except ValueError as e:
        print(f'✗ JSON 解析失败: {e}', file=sys.stderr)
        sys.exit(1)

    if isinstance(parsed, list):
        payload = {'notes': parsed}
    elif isinstance(parsed, dict):
        payload = parsed if ('notes' in parsed or 'entries' in parsed) else {'notes': [parsed]}
    else:
        print('✗ JSON 顶层须为数组或对象', file=sys.stderr)
        sys.exit(1)

    if args.no_dedup:
        payload['dedup'] = False

    # 来源文件：命令行 --source-file 作为顶层缺省（JSON 内已显式指定的条目优先）
    if getattr(args, 'source_file', None) and 'source_file' not in payload:
        payload['source_file'] = args.source_file

    status, resp = _request('POST', args.url, '/api/notes/ingest', args.token, payload)
    _check_auth(status, resp)
    if status != 200:
        print(f'✗ 上传失败: {resp.get("error", resp)}', file=sys.stderr)
        sys.exit(1)

    print(f'✓ 新增 {resp["added"]} 条，合并更新 {resp["merged"]} 条，跳过 {resp["skipped"]} 条')
    for it in resp.get('added_list', []):
        print(f'  + {it["code"]}  {it["title"]}')
    for it in resp.get('merged_list', []):
        print(f'  ~ {it["code"]}  {it["title"]} (已存在，已更新)')
    for it in resp.get('skipped_list', []):
        print(f'  - [{it.get("index")}] {it.get("title", "")}: {it.get("reason")}')


def cmd_get(args):
    status, resp = _request('GET', args.url, f'/api/notes/{args.id}', args.token)
    _check_auth(status, resp)
    if status != 200:
        print(f'✗ 获取失败: {resp.get("error", resp)}', file=sys.stderr)
        sys.exit(1)
    print(json.dumps(resp, ensure_ascii=False, indent=2))


def cmd_update(args):
    """更新单条笔记的指定字段（只传你给的字段，其余不动）。"""
    fields = {}
    for k in ('title', 'content', 'tags', 'source', 'level', 'section'):
        v = getattr(args, k, None)
        if v is not None:
            fields[k] = v
    if args.date is not None:
        fields['note_date'] = args.date
    if not fields:
        print('✗ 未提供任何要更新的字段（--content/--title/--tags/--level/--source/--section/--date）',
              file=sys.stderr)
        sys.exit(1)
    status, resp = _request('PUT', args.url, f'/api/notes/{args.id}', args.token, fields)
    _check_auth(status, resp)
    if status == 200:
        print(f'✓ 已更新 #{args.id}：{", ".join(fields)}')
    elif status == 202:
        print(f'✓ 已提交更新申请 #{args.id}（共建者，待管理员确认）')
    else:
        print(f'✗ 更新失败: {resp.get("error", resp)}', file=sys.stderr)
        sys.exit(1)


def cmd_delete(args):
    """删除一条或多条笔记。多个 id 走批量接口。"""
    if len(args.ids) == 1:
        status, resp = _request('DELETE', args.url, f'/api/notes/{args.ids[0]}', args.token)
    else:
        status, resp = _request('DELETE', args.url, '/api/notes/batch', args.token,
                                {'ids': args.ids})
    _check_auth(status, resp)
    if status in (200, 202):
        print(f'✓ 已删除/已提交删除：{args.ids}')
    else:
        print(f'✗ 删除失败: {resp.get("error", resp)}', file=sys.stderr)
        sys.exit(1)


def cmd_search(args):
    from urllib.parse import quote
    status, resp = _request('GET', args.url,
                            f'/api/notes?q={quote(args.query)}&per={args.limit}', args.token)
    _check_auth(status, resp)
    items = resp.get('items', [])
    print(f'共 {resp.get("total", 0)} 条，显示前 {len(items)} 条：')
    for n in items:
        print(f'  {n["code"]} [{n.get("level","")}] {n["title"]}')


def cmd_stats(args):
    status, resp = _request('GET', args.url, '/api/stats', args.token)
    _check_auth(status, resp)
    print(f'笔记总数: {resp.get("total", 0)}')
    print('按等级:')
    for r in resp.get('by_level', []):
        print(f'  {r["level"]}: {r["cnt"]}')
    print('按章节:')
    for r in resp.get('by_section', []):
        print(f'  {r["section"]} {r.get("name","")}: {r["cnt"]}')


def build_parser():
    p = argparse.ArgumentParser(
        description='电厂运行笔记命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='提示：先运行 `note_cli.py sections` 查看可用章节编码。')
    p.add_argument('--url', default=os.environ.get('NOTES_API_URL', 'http://localhost:5000'),
                   help='服务地址，默认 $NOTES_API_URL 或 http://localhost:5000')
    p.add_argument('--token', default=os.environ.get('NOTES_API_TOKEN', ''),
                   help='API 令牌，默认取环境变量 $NOTES_API_TOKEN')
    sub = p.add_subparsers(dest='command', required=True)

    sub.add_parser('sections', help='列出全部章节编码').set_defaults(func=cmd_sections)

    a = sub.add_parser('add', help='新增单条笔记')
    a.add_argument('--section', required=True, help='章节编码，如 A01')
    a.add_argument('--title', required=True, help='要点标题')
    a.add_argument('--content', help='内容详情')
    a.add_argument('--tags', help='关键词标签，逗号分隔')
    a.add_argument('--source', help='来源，默认“个人总结”')
    a.add_argument('--level', help='等级 ★ / ★★ / ★★★，默认 ★')
    a.add_argument('--date', help='日期 YYYY-MM-DD，默认今天')
    a.add_argument('--source-file', dest='source_file',
                   help='来源文件名（含格式，如 运行规程.docx）；处理文件时填写，仅显示在卡片背面')
    a.set_defaults(func=cmd_add)

    i = sub.add_parser('import', help='从 JSON 文件批量上传（- 表示标准输入）')
    i.add_argument('file', help='JSON 文件路径，或用 - 从标准输入读取')
    i.add_argument('--no-dedup', action='store_true', help='关闭按标题去重（默认开启）')
    i.add_argument('--source-file', dest='source_file',
                   help='来源文件名（含格式）作为顶层缺省；整理某个文件出的所有笔记可统一标注来源')
    i.set_defaults(func=cmd_import)

    g = sub.add_parser('get', help='按 id 获取单条笔记（JSON）')
    g.add_argument('id', help='笔记 id')
    g.set_defaults(func=cmd_get)

    u = sub.add_parser('update', help='更新单条笔记的指定字段（只改你给的字段）')
    u.add_argument('id', help='笔记 id')
    u.add_argument('--title'); u.add_argument('--content'); u.add_argument('--tags')
    u.add_argument('--source'); u.add_argument('--level'); u.add_argument('--section')
    u.add_argument('--date', help='日期 YYYY-MM-DD')
    u.set_defaults(func=cmd_update)

    d = sub.add_parser('delete', help='删除一条或多条笔记（多个 id 走批量）')
    d.add_argument('ids', nargs='+', help='一个或多个笔记 id')
    d.set_defaults(func=cmd_delete)

    s = sub.add_parser('search', help='搜索笔记')
    s.add_argument('query', help='搜索关键词')
    s.add_argument('--limit', type=int, default=20, help='返回条数，默认 20')
    s.set_defaults(func=cmd_search)

    sub.add_parser('stats', help='显示统计信息').set_defaults(func=cmd_stats)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
