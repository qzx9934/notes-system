# -*- coding: utf-8 -*-
"""后端 API 测试：认证/限流、字段校验、编号生成、批量录入与章节移动等。"""


# ---------------- 认证与限流 ----------------

def test_login_success(client):
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert data['role'] == 'admin'


def test_login_wrong_password(client):
    r = client.post('/api/login', json={'username': 'admin', 'password': 'nope'})
    assert r.status_code == 401


def test_default_password_flag(client):
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    assert r.get_json()['default_password'] is True


def test_login_rate_limited_after_repeated_failures(client):
    for _ in range(5):
        client.post('/api/login', json={'username': 'admin', 'password': 'x'})
    # 第 6 次（已达阈值）应被锁定
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    assert r.status_code == 429


def test_check_auth_requires_login(client):
    assert client.get('/api/check-auth').status_code == 401


def test_write_requires_admin(client):
    # 未登录写接口应 401
    r = client.post('/api/notes', json={'section': 'A01', 'title': 't'})
    assert r.status_code == 401


# ---------------- 字段校验 ----------------

def test_create_note_valid(admin):
    r = admin.post('/api/notes', json={
        'section': 'A01', 'title': '校验-正常', 'level': '★★', 'note_date': '2026-05-29'
    })
    assert r.status_code == 201
    body = r.get_json()
    assert body['code'].startswith('A01-')
    assert body['level'] == '★★'


def test_create_note_bad_level(admin):
    r = admin.post('/api/notes', json={'section': 'A01', 'title': 't', 'level': '<img>'})
    assert r.status_code == 400


def test_create_note_bad_section(admin):
    r = admin.post('/api/notes', json={'section': 'ZZZ', 'title': 't'})
    assert r.status_code == 400


def test_create_note_bad_date(admin):
    r = admin.post('/api/notes', json={'section': 'A01', 'title': 't', 'note_date': '2026/1/1'})
    assert r.status_code == 400


def test_update_note_bad_level(admin):
    created = admin.post('/api/notes', json={'section': 'A02', 'title': '待更新'}).get_json()
    r = admin.put('/api/notes/%d' % created['id'], json={'level': 'BAD'})
    assert r.status_code == 400


# ---------------- 编号生成 ----------------

def test_code_generation_sequential(admin):
    c1 = admin.post('/api/notes', json={'section': 'E03', 'title': '序号-1'}).get_json()['code']
    c2 = admin.post('/api/notes', json={'section': 'E03', 'title': '序号-2'}).get_json()['code']
    n1 = int(c1.split('-')[1])
    n2 = int(c2.split('-')[1])
    assert n2 == n1 + 1


# ---------------- 分页健壮性 ----------------

def test_pagination_junk_params(admin):
    r = admin.get('/api/notes?page=abc&per=-5')
    assert r.status_code == 200  # 不再 500


def test_pagination_per_capped(admin):
    r = admin.get('/api/notes?per=99999')
    assert r.get_json()['per'] == app_per_cap()


def app_per_cap():
    import app as app_module
    return app_module.MAX_PER


# ---------------- 批量录入 ingest ----------------

def test_ingest_multi_section_and_dedup(admin):
    payload = {'notes': [
        {'section': 'A03', 'title': 'ingest-唯一标题-X', 'content': 'v1'},
        {'section': 'B01', 'title': 'ingest-唯一标题-Y'},
        {'section': 'ZZZ', 'title': '非法章节'},
    ]}
    r = admin.post('/api/notes/ingest', json=payload)
    body = r.get_json()
    assert body['added'] == 2
    assert body['skipped'] == 1

    # 再次上传同标题 -> 合并更新，不新增
    r2 = admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A03', 'title': 'ingest-唯一标题-X', 'content': 'v2'}
    ]})
    assert r2.get_json()['merged'] == 1
    assert r2.get_json()['added'] == 0


def test_ingest_coerces_bad_level_and_date(admin):
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'C04', 'title': '强制归一化', 'level': 'BAD', 'date': 'nope'}
    ]})
    items = admin.get('/api/notes?section=C04&q=强制归一化').get_json()['items']
    assert items and items[0]['level'] == '★'


# ---------------- API 令牌 ----------------

def test_token_create_and_use_for_write(admin, client):
    created = admin.post('/api/tokens', json={'label': 'test', 'role': 'admin'}).get_json()
    token = created['token']
    assert token.startswith('ntk_')

    # 用全新（无会话）client + 令牌写入
    fresh = client.application.test_client()
    r = fresh.post('/api/notes', json={'section': 'D01', 'title': '令牌写入'},
                   headers={'X-API-Token': token})
    assert r.status_code == 201


def test_viewer_token_cannot_write(admin, client):
    token = admin.post('/api/tokens', json={'label': 'ro', 'role': 'viewer'}).get_json()['token']
    fresh = client.application.test_client()
    rw = fresh.post('/api/notes', json={'section': 'D01', 'title': 'x'},
                    headers={'X-API-Token': token})
    assert rw.status_code == 403
    rd = fresh.get('/api/stats', headers={'X-API-Token': token})
    assert rd.status_code == 200


# ---------------- 批量移动章节：编号随新章节重生成 ----------------

def test_batch_move_section_regenerates_code(admin):
    note = admin.post('/api/notes', json={'section': 'A04', 'title': '待移动'}).get_json()
    assert note['code'].startswith('A04-')

    r = admin.put('/api/notes/batch', json={'ids': [note['id']], 'updates': {'section': 'E04'}})
    assert r.status_code == 200

    moved = admin.get('/api/notes/%d' % note['id']).get_json()
    assert moved['section'] == 'E04'
    assert moved['code'].startswith('E04-')  # 编号已按新章节重新生成


def test_batch_append_uses_exact_title_dedup(admin):
    """/api/notes/batch (POST) 按精确标题去重：子串标题不应被误并、丢内容。"""
    admin.post('/api/notes/batch', json={'section': 'A08', 'entries': [
        {'title': '给水泵', 'content': 'c1'}
    ]})
    # 子串标题应作为新条目新增，而不是并入已有的"给水泵"
    r = admin.post('/api/notes/batch', json={'section': 'A08', 'entries': [
        {'title': '给水泵备用联启逻辑', 'content': 'c2'}
    ]})
    assert r.get_json()['added'] == 1 and r.get_json()['merged'] == 0
    # 标题完全相同才合并更新（且会更新内容）
    r2 = admin.post('/api/notes/batch', json={'section': 'A08', 'entries': [
        {'title': '给水泵', 'content': 'c1-更新'}
    ]})
    assert r2.get_json()['merged'] == 1 and r2.get_json()['added'] == 0
    item = admin.get('/api/notes?section=A08&q=给水泵备用联启逻辑').get_json()['items'][0]
    assert item['content'] == 'c2'  # 子串条目内容未被覆盖


# ---------------- 令牌管理员删除用户（回归：session KeyError → 500） ----------------

def test_token_admin_can_delete_user(admin, client):
    """API 令牌管理员（无浏览器会话）删除用户应成功，不再因 session['user_id'] 抛 500。"""
    admin.post('/api/users', json={'username': 'victim', 'password': 'orig123', 'role': 'viewer'})
    uid = next(u['id'] for u in admin.get('/api/users').get_json() if u['username'] == 'victim')

    token = admin.post('/api/tokens', json={'label': 'del', 'role': 'admin'}).get_json()['token']
    fresh = client.application.test_client()  # 全新、无会话
    r = fresh.delete('/api/users/%d' % uid, headers={'X-API-Token': token})
    assert r.status_code == 200
    assert r.get_json()['deleted']['username'] == 'victim'


# ---------------- 安全加固（响应头 / Cookie / CORS） ----------------

def test_security_headers_present(client):
    r = client.get('/api/check-auth')
    assert r.headers.get('X-Content-Type-Options') == 'nosniff'
    assert r.headers.get('X-Frame-Options') == 'DENY'
    assert 'Referrer-Policy' in r.headers


def test_no_hsts_when_not_https(client):
    # 测试环境未设 NOTES_HTTPS，不应下发 HSTS
    r = client.get('/api/check-auth')
    assert 'Strict-Transport-Security' not in r.headers


def test_session_cookie_is_hardened(client):
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    set_cookie = ' '.join(r.headers.getlist('Set-Cookie'))
    assert 'HttpOnly' in set_cookie
    assert 'SameSite=Lax' in set_cookie
    # 测试环境非 HTTPS，不应带 Secure（否则本地 HTTP 无法登录）
    assert 'Secure' not in set_cookie


def test_cors_not_open_by_default(client):
    r = client.get('/api/check-auth', headers={'Origin': 'https://evil.example'})
    assert r.headers.get('Access-Control-Allow-Origin') is None


def test_env_bool_helper():
    import app as app_module
    import os
    os.environ['X_TMP_FLAG'] = 'yes'
    assert app_module._env_bool('X_TMP_FLAG') is True
    os.environ['X_TMP_FLAG'] = '0'
    assert app_module._env_bool('X_TMP_FLAG') is False
    del os.environ['X_TMP_FLAG']
    assert app_module._env_bool('X_TMP_FLAG', False) is False


# ---------------- 全文搜索（FTS5 trigram） ----------------

def test_fts_is_enabled_in_tests():
    import app as app_module
    assert app_module.FTS_ENABLED is True


def _search(client, q):
    return client.get('/api/notes', query_string={'q': q}).get_json()


def test_fts_chinese_substring_search(admin):
    admin.post('/api/notes', json={
        'section': 'A05', 'title': '唯一标记ZZQ', 'content': '汽轮机超速保护跳闸值唯一标记ZZQ'
    })
    # 中文子串（≥3 字符）应能命中正文
    items = _search(admin, '超速保护')['items']
    assert any('唯一标记ZZQ' in it['title'] for it in items)


def test_fts_stays_in_sync_on_update_and_delete(admin):
    created = admin.post('/api/notes', json={
        'section': 'A06', 'title': 'FTS同步检验XQW', 'content': '初始关键词蓝色海洋'
    }).get_json()
    nid = created['id']

    assert any(it['id'] == nid for it in _search(admin, '蓝色海洋')['items'])

    # 更新正文 -> 旧词查不到、新词查得到
    admin.put('/api/notes/%d' % nid, json={'content': '替换关键词红色沙漠'})
    assert not any(it['id'] == nid for it in _search(admin, '蓝色海洋')['items'])
    assert any(it['id'] == nid for it in _search(admin, '红色沙漠')['items'])

    # 删除 -> 查不到
    admin.delete('/api/notes/%d' % nid)
    assert not any(it['id'] == nid for it in _search(admin, '红色沙漠')['items'])


def test_short_query_falls_back_to_like(admin):
    admin.post('/api/notes', json={'section': 'A07', 'title': '短查询QY测试'})
    # 2 字符查询走 LIKE 回退，仍应命中标题
    items = _search(admin, 'QY')['items']
    assert any('短查询QY测试' in it['title'] for it in items)


# ---------------- 修改密码（隔离用户，避免影响默认 admin） ----------------

def test_change_password_flow(admin, client):
    admin.post('/api/users', json={'username': 'pwuser', 'password': 'orig123', 'role': 'viewer'})
    u = client.application.test_client()
    assert u.post('/api/login', json={'username': 'pwuser', 'password': 'orig123'}).status_code == 200
    assert u.post('/api/change-password',
                  json={'old_password': 'orig123', 'new_password': 'new12345'}).status_code == 200
    u.post('/api/logout')
    # 旧密码失效、新密码可用
    assert u.post('/api/login', json={'username': 'pwuser', 'password': 'orig123'}).status_code == 401
    assert u.post('/api/login', json={'username': 'pwuser', 'password': 'new12345'}).status_code == 200


# ---------------- 图片上传 ----------------
import base64
import io

# 1x1 透明 PNG（最小合法 PNG）
_TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
)


def test_upload_requires_admin(client):
    r = client.post('/api/upload',
                    data={'file': (io.BytesIO(_TINY_PNG), 'a.png')},
                    content_type='multipart/form-data')
    assert r.status_code == 401


def test_upload_png_succeeds_and_serves(admin):
    r = admin.post('/api/upload',
                   data={'file': (io.BytesIO(_TINY_PNG), 'shot.png')},
                   content_type='multipart/form-data')
    assert r.status_code == 200
    data = r.get_json()
    assert data['url'].startswith('/uploads/') and data['url'].endswith('.png')
    assert data['mime'] == 'image/png'
    # 下发回来内容一致、MIME 正确、强缓存
    got = admin.get(data['url'])
    assert got.status_code == 200
    assert got.mimetype == 'image/png'
    assert got.data == _TINY_PNG
    assert 'immutable' in got.headers.get('Cache-Control', '')


def test_upload_dedup_same_content(admin):
    a = admin.post('/api/upload', data={'file': (io.BytesIO(_TINY_PNG), 'one.png')},
                   content_type='multipart/form-data').get_json()
    b = admin.post('/api/upload', data={'file': (io.BytesIO(_TINY_PNG), 'two.png')},
                   content_type='multipart/form-data').get_json()
    # 内容相同 -> 文件名（内容哈希）相同，复用同一文件
    assert a['url'] == b['url']


def test_upload_rejects_non_image(admin):
    r = admin.post('/api/upload',
                   data={'file': (io.BytesIO(b'#!/bin/sh\necho hi'), 'evil.png')},
                   content_type='multipart/form-data')
    assert r.status_code == 415


def test_upload_rejects_empty(admin):
    r = admin.post('/api/upload',
                   data={'file': (io.BytesIO(b''), 'empty.png')},
                   content_type='multipart/form-data')
    assert r.status_code == 400


# ---------------- 孤儿图片清理 ----------------
import os
import app as _app

_upload_salt = [0]

def _upload(admin):
    """上传一张内容唯一的图片（避免跨用例哈希去重相互干扰），返回 (url, 磁盘路径)"""
    _upload_salt[0] += 1
    # PNG 头合法即可通过魔数校验；追加唯一尾字节让每次内容/哈希都不同
    blob = _TINY_PNG + b'\x00salt' + str(_upload_salt[0]).encode()
    u = admin.post('/api/upload', data={'file': (io.BytesIO(blob), 'p.png')},
                   content_type='multipart/form-data').get_json()
    return u['url'], os.path.join(_app.UPLOAD_DIR, u['filename'])


def _backdate(path, seconds=3 * 86400):
    """把文件修改时间往前拨，绕过清理宽限期以便测试真实删除。"""
    past = os.path.getmtime(path) - seconds
    os.utime(path, (past, past))


def test_cleanup_grace_protects_fresh_orphan(admin):
    # 刚上传、未被任何笔记引用，但在宽限期内 -> 不应被删
    url, path = _upload(admin)
    r = admin.post('/api/uploads/cleanup')
    assert r.status_code == 200 and r.get_json()['removed'] == 0
    assert os.path.exists(path)


def test_cleanup_removes_aged_orphan(admin):
    url, path = _upload(admin)
    _backdate(path)  # 超过宽限期且无引用
    r = admin.post('/api/uploads/cleanup').get_json()
    assert r['removed'] == 1 and url.split('/')[-1] in r['removed_list']
    assert not os.path.exists(path)


def test_cleanup_keeps_referenced_image(admin):
    url, path = _upload(admin)
    _backdate(path)  # 即便超期，只要被笔记引用就保留
    admin.post('/api/notes', json={'section': 'A01', 'title': '带图笔记',
                                    'content': f'见图：![x]({url})'})
    r = admin.post('/api/uploads/cleanup').get_json()
    assert r['removed'] == 0
    assert os.path.exists(path)


def test_cleanup_dry_run_does_not_delete(admin):
    url, path = _upload(admin)
    _backdate(path)
    r = admin.post('/api/uploads/cleanup?dry_run=1').get_json()
    assert r['dry_run'] is True and r['removed'] == 1
    assert os.path.exists(path)  # 预览不真删


def test_delete_note_reclaims_orphan_image(admin):
    url, path = _upload(admin)
    _backdate(path)
    c = admin.post('/api/notes', json={'section': 'A01', 'title': '待删带图',
                                        'content': f'![x]({url})'}).get_json()
    nid = c['id'] if 'id' in c else None
    # 取回 id（创建响应若不含 id 则按 code 查）
    if nid is None:
        items = admin.get('/api/notes?q=待删带图').get_json()['items']
        nid = items[0]['id']
    assert os.path.exists(path)
    admin.delete(f'/api/notes/{nid}')
    # 笔记删除后图片不再被引用且已超期 -> 被自动回收
    assert not os.path.exists(path)


def test_cleanup_requires_admin(client):
    assert client.post('/api/uploads/cleanup').status_code == 401


# ---------------- 重新整理保留手动图片 ----------------

def test_merge_preserved_images_unit():
    f = _app.merge_preserved_images
    # 旧有图、新没图 -> 追加保留
    out = f('正文\n\n![截图](/uploads/a.png)', '新正文')
    assert '/uploads/a.png' in out and '新正文' in out
    # 新正文已含该图 -> 不重复
    assert f('![x](/uploads/a.png)', '见![x](/uploads/a.png)').count('/uploads/a.png') == 1
    # 没有旧图 -> 原样返回
    assert f('纯文本', '新正文') == '新正文'
    # 幂等：把上一轮结果当旧正文再合并，仍只保留一份
    once = f('![x](/uploads/a.png)', '新正文')
    twice = f(once, '又一版新正文')
    assert twice.count('/uploads/a.png') == 1


def test_ingest_preserves_manual_image_on_recompile(admin):
    # 1) 首次整理录入（纯文本）
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A02', 'title': '给水泵联启', 'content': '原始要点'}]})
    # 2) 人工在网页端编辑，加入图片
    nid = admin.get('/api/notes?q=给水泵联启').get_json()['items'][0]['id']
    admin.put(f'/api/notes/{nid}', json={'content': '原始要点\n\n![现场图](/uploads/x.png)'})
    # 3) 重新整理：同 section+title 再次 ingest，新正文不含图片
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A02', 'title': '给水泵联启', 'content': '更新后的要点'}]})
    content = admin.get(f'/api/notes/{nid}').get_json()['content']
    assert '更新后的要点' in content          # 文本已更新
    assert '/uploads/x.png' in content        # 图片被保留
    # 4) 再整理一次仍只保留一份图片（幂等）
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A02', 'title': '给水泵联启', 'content': '第三版要点'}]})
    content2 = admin.get(f'/api/notes/{nid}').get_json()['content']
    assert content2.count('/uploads/x.png') == 1 and '第三版要点' in content2


# ---------------- 来源文件字段（source_file） ----------------

def test_new_columns_present_and_default_empty(admin):
    r = admin.post('/api/notes', json={'section': 'A01', 'title': '新列默认值'})
    body = r.get_json()
    assert body['source_file'] == ''
    assert body['ai_summary'] == ''
    assert body['ai_summary_at'] is None


def test_create_note_records_source_file(admin):
    r = admin.post('/api/notes', json={
        'section': 'A01', 'title': '带来源文件', 'source_file': '运行规程.docx'})
    assert r.get_json()['source_file'] == '运行规程.docx'


def test_ingest_records_source_file_top_level_and_entry(admin):
    # 顶层 source_file 作缺省，条目可覆盖
    admin.post('/api/notes/ingest', json={
        'source_file': '交接班记录.pdf',
        'notes': [
            {'section': 'A03', 'title': '来源缺省继承'},
            {'section': 'A03', 'title': '来源条目覆盖', 'source_file': '专项.xlsx'},
        ]})
    items = admin.get('/api/notes?section=A03&per=200').get_json()['items']
    by_title = {it['title']: it for it in items}
    assert by_title['来源缺省继承']['source_file'] == '交接班记录.pdf'
    assert by_title['来源条目覆盖']['source_file'] == '专项.xlsx'


def test_ingest_redo_without_source_file_keeps_existing(admin):
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A04', 'title': '保留来源文件', 'source_file': '台账.docx'}]})
    # 重新整理但不带 source_file -> 原值应保留
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A04', 'title': '保留来源文件', 'content': '更新'}]})
    nid = admin.get('/api/notes?q=保留来源文件').get_json()['items'][0]['id']
    assert admin.get(f'/api/notes/{nid}').get_json()['source_file'] == '台账.docx'


def test_source_file_not_required_for_plain_text(admin):
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A05', 'title': '纯文本无来源'}]})
    nid = admin.get('/api/notes?q=纯文本无来源').get_json()['items'][0]['id']
    assert admin.get(f'/api/notes/{nid}').get_json()['source_file'] == ''


# ---------------- 查重 ----------------

def test_duplicates_requires_admin(client):
    assert client.get('/api/notes/duplicates').status_code == 401


def test_duplicates_same_title_clustered(admin):
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A06', 'title': '脱硫浆液 循环泵切换', 'content': '甲版本内容'},
        {'section': 'A06', 'title': '脱硫浆液循环泵切换', 'content': '乙完全不同的内容'},
    ]})
    data = admin.get('/api/notes/duplicates').get_json()
    titles = {n['title'] for c in data['clusters'] for n in c}
    # 归一标题相等 -> 即便正文不同也应聚为一簇
    assert '脱硫浆液 循环泵切换' in titles and '脱硫浆液循环泵切换' in titles


def test_duplicates_similar_content_clustered(admin):
    base = '锅炉MFT动作条件共十六项，包含炉膛压力高低、汽包水位高低、全炉膛失火等保护' * 2
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A07', 'title': 'MFT条件甲', 'content': base},
        {'section': 'A07', 'title': 'MFT条件乙', 'content': base + '（另补充一句）'},
    ]})
    data = admin.get('/api/notes/duplicates').get_json()
    sizes = [len(c) for c in data['clusters']]
    assert any(s >= 2 for s in sizes)


def test_duplicates_distinct_notes_not_clustered(admin):
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'A08', 'title': '输煤皮带', 'content': '输煤系统皮带巡检要点完全独立'},
        {'section': 'A08', 'title': '燃油泵', 'content': '燃油系统油泵切换毫不相干'},
    ]})
    data = admin.get('/api/notes/duplicates?scope=section').get_json()
    flat = {n['title'] for c in data['clusters'] for n in c}
    assert '输煤皮带' not in flat and '燃油泵' not in flat


# ---------------- AI 总结（DeepSeek，打桩） ----------------

def test_summarize_requires_admin(client):
    assert client.post('/api/notes/1/summarize').status_code == 401


def test_summarize_missing_key_returns_503(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', '')
    nid = admin.post('/api/notes', json={
        'section': 'A01', 'title': '待总结', 'content': '一些内容'}).get_json()['id']
    r = admin.post(f'/api/notes/{nid}/summarize')
    assert r.status_code == 503


def test_summarize_empty_content_returns_400(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '空内容'}).get_json()['id']
    assert admin.post(f'/api/notes/{nid}/summarize').status_code == 400


def test_summarize_success_saves_to_note(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(_app, '_deepseek_summarize',
                        lambda title, content: '## 要点\n- 总结好的内容')
    nid = admin.post('/api/notes', json={
        'section': 'A01', 'title': '可总结', 'content': '原始笔记内容'}).get_json()['id']
    r = admin.post(f'/api/notes/{nid}/summarize')
    assert r.status_code == 200
    assert '总结好的内容' in r.get_json()['ai_summary']
    # 已落库，可在背面读取
    got = admin.get(f'/api/notes/{nid}').get_json()
    assert '总结好的内容' in got['ai_summary'] and got['ai_summary_at']


def test_summarize_upstream_error_returns_502(admin, monkeypatch):
    def boom(title, content):
        raise RuntimeError('DeepSeek 接口返回 500：err')
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(_app, '_deepseek_summarize', boom)
    nid = admin.post('/api/notes', json={
        'section': 'A01', 'title': '上游错误', 'content': '内容'}).get_json()['id']
    assert admin.post(f'/api/notes/{nid}/summarize').status_code == 502
