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


# ---------------- 来源（source）校验 ----------------

def test_create_note_new_source_accepted(admin):
    r = admin.post('/api/notes', json={'section': 'A01', 'title': '技术通知样例', 'source': '技术通知'})
    assert r.status_code == 201 and r.get_json()['source'] == '技术通知'


def test_create_note_custom_source_accepted(admin):
    custom_source = '随便乱填'
    r = admin.post('/api/notes', json={'section': 'A01', 'title': 't', 'source': custom_source})
    assert r.status_code == 201 and r.get_json()['source'] == custom_source

def test_create_note_invalid_source_rejected(admin):
    assert admin.post('/api/notes', json={'section': 'A01', 'title': '空来源', 'source': ''}).status_code == 400
    assert admin.post('/api/notes', json={'section': 'A01', 'title': '过长来源', 'source': 'X' * 51}).status_code == 400
    assert admin.post('/api/notes', json={'section': 'A01', 'title': '控制字符来源', 'source': '异常\x01来源'}).status_code == 400

def test_update_custom_source_accepted(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '改来源'}).get_json()['id']
    assert admin.put(f'/api/notes/{nid}', json={'source': '现场自定义来源'}).status_code == 200
    assert admin.put(f'/api/notes/{nid}', json={'source': '技术通知'}).status_code == 200

def test_update_unchanged_legacy_source_allowed(admin):
    # Legacy custom source is allowed when unchanged; newly invalid source is still rejected.
    import os, sqlite3
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '遗留来源'}).get_json()['id']
    db = sqlite3.connect(os.environ['NOTES_DB_PATH'])
    db.execute('UPDATE notes SET source=? WHERE id=?', ('工作票(旧)', nid)); db.commit(); db.close()
    assert admin.put(f'/api/notes/{nid}', json={'title': '遗留来源-改名'}).status_code == 200
    assert admin.put(f'/api/notes/{nid}', json={'source': 'X' * 51}).status_code == 400

def test_batch_update_custom_source_accepted(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '批改来源'}).get_json()['id']
    assert admin.put('/api/notes/batch', json={'ids': [nid], 'updates': {'source': '自定义批量来源'}}).status_code == 200
    assert admin.put('/api/notes/batch', json={'ids': [nid], 'updates': {'source': '缺陷异常'}}).status_code == 200

def test_batch_update_invalid_source_rejected(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '批改非法来源'}).get_json()['id']
    assert admin.put('/api/notes/batch', json={'ids': [nid], 'updates': {'source': 'X' * 51}}).status_code == 400

def _docx_xml_from_zip_member(zf, name):
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(zf.read(name))) as docx:
        return docx.read('word/document.xml').decode('utf-8')


def test_export_exam_word_zip(admin):
    import io, zipfile
    n1 = admin.post('/api/notes', json={
        'section': 'A01', 'title': '试卷题一', 'content': '答案内容一', 'source': '自定义来源'
    }).get_json()
    n2 = admin.post('/api/notes', json={
        'section': 'A01', 'title': '试卷题二', 'content': '**答案内容二**', 'source': '技术文件'
    }).get_json()
    r = admin.post('/api/notes/export-exam', json={'ids': [n2['id'], n1['id']], 'exam_title': '班前测试'})
    assert r.status_code == 200
    assert r.mimetype == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(r.data)) as zf:
        names = set(zf.namelist())
        assert '运行工作笔记试卷-无答案.docx' in names
        assert '运行工作笔记试卷-含答案.docx' in names
        no_answer_xml = _docx_xml_from_zip_member(zf, '运行工作笔记试卷-无答案.docx')
        answer_xml = _docx_xml_from_zip_member(zf, '运行工作笔记试卷-含答案.docx')
        assert '班前测试' in no_answer_xml
        assert '班前测试' in answer_xml
        assert '班前测试（含答案）' not in answer_xml
        assert '编号：' not in no_answer_xml
        assert '来源：' not in answer_xml
        assert '答案内容二' in answer_xml


def test_viewer_can_export_exam_word_zip(admin):
    note = admin.post('/api/notes', json={
        'section': 'A01', 'title': '只读导出题', 'content': '答案内容'
    }).get_json()
    _make_user(admin, 'viewer_export', 'viewer')
    viewer = _new_client()
    viewer.post('/api/login', json={'username': 'viewer_export', 'password': 'secret123'})
    r = viewer.post('/api/notes/export-exam', json={'ids': [note['id']], 'exam_title': '只读试卷'})
    assert r.status_code == 200
    assert r.mimetype == 'application/zip'


def test_ingest_coerces_bad_source(admin):
    admin.post('/api/notes/ingest', json={'notes': [
        {'section': 'C04', 'title': '来源归一化', 'source': '不存在的来源'}
    ]})
    items = admin.get('/api/notes?section=C04&q=来源归一化').get_json()['items']
    assert items and items[0]['source'] == '个人总结'


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



def test_notes_list_returns_filtered_level_counts(admin):
    query = '筛选统计'
    admin.post('/api/notes', json={'section': 'A01', 'title': query + '核心', 'level': '★★★'})
    admin.post('/api/notes', json={'section': 'A01', 'title': query + '参考', 'level': '★'})
    admin.post('/api/notes', json={'section': 'A02', 'title': query + '外部', 'level': '★★'})
    data = admin.get('/api/notes?section=A01&q=' + query).get_json()
    by_level = {row['level']: row['cnt'] for row in data['by_level']}
    assert data['total'] == 2
    assert by_level == {'★': 1, '★★★': 1}

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
    assert moved['code'].startswith('E04-')


def test_edit_change_section_regenerates_code(admin):
    # 单条编辑改章节：section 与编号 code 都要随之变化（修复"编辑改章节没用"）
    note = admin.post('/api/notes', json={'section': 'B02', 'title': '编辑改章节'}).get_json()
    assert note['code'].startswith('B02-')

    r = admin.put('/api/notes/%d' % note['id'], json={'section': 'D03', 'title': '编辑改章节'})
    assert r.status_code == 200
    assert r.get_json().get('code', '').startswith('D03-')

    after = admin.get('/api/notes/%d' % note['id']).get_json()
    assert after['section'] == 'D03'
    assert after['code'].startswith('D03-')


def test_edit_unknown_section_rejected(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '非法章节编辑'}).get_json()['id']
    assert admin.put('/api/notes/%d' % nid, json={'section': 'ZZZ'}).status_code == 400  # 编号已按新章节重新生成


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


def test_batch_append_reports_malformed_entries_as_skipped(admin):
    r = admin.post('/api/notes/batch', json={'section': 'A09', 'entries': [
        {'title': '批量跳过-有效', 'content': 'ok'},
        '不是对象',
        {'title': '   ', 'content': 'no title'},
    ]})
    assert r.status_code == 200
    body = r.get_json()
    assert body['added'] == 1
    assert body['skipped'] == 2
    assert [item['reason'] for item in body['skipped_list']] == ['条目不是对象', 'title 为空']

    items = admin.get('/api/notes?section=A09&q=批量跳过-有效').get_json()['items']
    assert len(items) == 1 and items[0]['content'] == 'ok'


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


# ---------------- 标题/正文一致性检查 ----------------

def test_title_content_check_requires_admin(client):
    assert client.post('/api/notes/title-content-check').status_code == 401


def test_title_content_check_background_job_flags_mismatch(admin, monkeypatch):
    monkeypatch.setattr(_app, '_start_title_check_worker', lambda job_id: None)
    bad = admin.post('/api/notes', json={
        'section': 'A01',
        'title': '给水泵启动条件',
        'content': '凝结水泵联锁投入后，检查凝汽器水位和凝结水压力。'
    }).get_json()['id']
    good = admin.post('/api/notes', json={
        'section': 'A01',
        'title': '锅炉MFT动作条件',
        'content': '锅炉MFT动作条件包括炉膛压力高、汽包水位低等保护动作。'
    }).get_json()['id']

    r = admin.post('/api/notes/title-content-check')
    assert r.status_code == 202
    job_id = r.get_json()['job']['id']
    _app._run_title_check_job(job_id)
    job = admin.get(f'/api/notes/title-content-check/{job_id}').get_json()['job']
    ids = {x['id'] for x in job['results']}
    assert bad in ids
    assert good not in ids
    assert job['suspicious'] == len(job['results'])


def test_title_content_check_ignore_skips_future_jobs(admin, monkeypatch):
    monkeypatch.setattr(_app, '_start_title_check_worker', lambda job_id: None)
    bad = admin.post('/api/notes', json={
        'section': 'A01',
        'title': '给水泵停运条件',
        'content': '凝结水泵运行中应关注凝汽器水位。'
    }).get_json()['id']

    r0 = admin.post('/api/notes/title-content-check')
    job0 = r0.get_json()['job']['id']
    _app._run_title_check_job(job0)
    assert bad in {x['id'] for x in admin.get(f'/api/notes/title-content-check/{job0}').get_json()['job']['results']}

    assert admin.post(f'/api/notes/{bad}/title-content-ignore').status_code == 200
    ignored = admin.get('/api/notes/title-content-ignore').get_json()['items']
    assert any(x['note_id'] == bad for x in ignored)

    r1 = admin.post('/api/notes/title-content-check')
    job1 = r1.get_json()['job']['id']
    _app._run_title_check_job(job1)
    job = admin.get(f'/api/notes/title-content-check/{job1}').get_json()['job']
    assert bad not in {x['id'] for x in job['results']}
    assert job['ignored'] >= 1

    assert admin.delete(f'/api/notes/{bad}/title-content-ignore').get_json()['removed'] == 1


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
                        lambda title, content, prompt=None, source=None: '## 要点\n- 总结好的内容')
    nid = admin.post('/api/notes', json={
        'section': 'A01', 'title': '可总结', 'content': '原始笔记内容'}).get_json()['id']
    r = admin.post(f'/api/notes/{nid}/summarize')
    assert r.status_code == 200
    assert '总结好的内容' in r.get_json()['ai_summary']
    # 已落库，可在背面读取
    got = admin.get(f'/api/notes/{nid}').get_json()
    assert '总结好的内容' in got['ai_summary'] and got['ai_summary_at']


def test_summarize_upstream_error_returns_502(admin, monkeypatch):
    def boom(title, content, prompt=None, source=None):
        raise RuntimeError('DeepSeek 接口返回 500：err')
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(_app, '_deepseek_summarize', boom)
    nid = admin.post('/api/notes', json={
        'section': 'A01', 'title': '上游错误', 'content': '内容'}).get_json()['id']
    assert admin.post(f'/api/notes/{nid}/summarize').status_code == 502


# ---------------- 登录日志 + 最后上线 ----------------

def _new_client():
    return _app.app.test_client()


def _make_user(admin, username, role, password='secret123'):
    admin.post('/api/users', json={'username': username, 'password': password, 'role': role})


def test_login_records_history_and_last_login(admin):
    # admin 已登录一次；用户列表应带 last_login_at
    users = admin.get('/api/users').get_json()
    me = [u for u in users if u['username'] == 'admin'][0]
    assert me['last_login_at']
    log = admin.get('/api/login-log').get_json()
    assert log['total'] >= 1
    assert any(it['username'] == 'admin' for it in log['items'])


def test_login_log_requires_admin(client):
    assert client.get('/api/login-log').status_code == 401


def test_login_log_filter_by_user(admin):
    _make_user(admin, 'viewer1', 'viewer')
    c = _new_client()
    c.post('/api/login', json={'username': 'viewer1', 'password': 'secret123'})
    users = admin.get('/api/users').get_json()
    vid = [u for u in users if u['username'] == 'viewer1'][0]['id']
    log = admin.get(f'/api/login-log?user_id={vid}').get_json()
    assert log['total'] >= 1 and all(it['user_id'] == vid for it in log['items'])


# ---------------- 共建者审批流 ----------------

def test_create_contributor_role_allowed(admin):
    r = admin.post('/api/users', json={'username': 'co1', 'password': 'secret123', 'role': 'contributor'})
    assert r.status_code == 201 and r.get_json()['role'] == 'contributor'


def _contributor_client(admin, name='co'):
    _make_user(admin, name, 'contributor')
    c = _new_client()
    c.post('/api/login', json={'username': name, 'password': 'secret123'})
    return c


def test_contributor_create_becomes_proposal(admin):
    co = _contributor_client(admin, 'co_create')
    r = co.post('/api/notes', json={'section': 'A01', 'title': '共建者新增', 'content': '内容'})
    assert r.status_code == 202 and r.get_json()['pending'] is True
    # 笔记尚未真正出现
    assert admin.get('/api/notes?q=共建者新增').get_json()['total'] == 0
    # 管理员能看到待审申请
    props = admin.get('/api/proposals?status=pending').get_json()
    assert any(p['kind'] == 'create' for p in props['items'])


def test_contributor_proposal_approve_applies(admin):
    co = _contributor_client(admin, 'co_appr')
    co.post('/api/notes', json={'section': 'A01', 'title': '待批准新增', 'content': '正文'})
    pid = [p for p in admin.get('/api/proposals?status=pending').get_json()['items']
           if p['payload'].get('title') == '待批准新增'][0]['id']
    assert admin.post(f'/api/proposals/{pid}/approve').status_code == 200
    assert admin.get('/api/notes?q=待批准新增').get_json()['total'] == 1


def test_contributor_proposal_reject_discards(admin):
    co = _contributor_client(admin, 'co_rej')
    co.post('/api/notes', json={'section': 'A01', 'title': '将被驳回', 'content': '正文'})
    pid = [p for p in admin.get('/api/proposals?status=pending').get_json()['items']
           if p['payload'].get('title') == '将被驳回'][0]['id']
    assert admin.post(f'/api/proposals/{pid}/reject', json={'review_note': '不合适'}).status_code == 200
    assert admin.get('/api/notes?q=将被驳回').get_json()['total'] == 0


def test_contributor_update_proposal_then_approve(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '原标题', 'content': '原文'}).get_json()['id']
    co = _contributor_client(admin, 'co_upd')
    r = co.put(f'/api/notes/{nid}', json={'title': '改后标题'})
    assert r.status_code == 202
    # 未生效
    assert admin.get(f'/api/notes/{nid}').get_json()['title'] == '原标题'
    pid = admin.get('/api/proposals?status=pending').get_json()['items'][0]['id']
    admin.post(f'/api/proposals/{pid}/approve')
    assert admin.get(f'/api/notes/{nid}').get_json()['title'] == '改后标题'


def test_contributor_delete_proposal(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '待删除卡', 'content': 'x'}).get_json()['id']
    co = _contributor_client(admin, 'co_del')
    assert co.delete(f'/api/notes/{nid}').status_code == 202
    assert admin.get(f'/api/notes/{nid}').status_code == 200  # 仍在
    pid = admin.get('/api/proposals?status=pending').get_json()['items'][0]['id']
    admin.post(f'/api/proposals/{pid}/approve')
    assert admin.get(f'/api/notes/{nid}').status_code == 404


def test_proposal_create_illegal_source_coerced_on_approve(admin):
    """防御：直接构造非法 source 的 create 提议，批准落库时应被归一为默认来源。"""
    import os, sqlite3
    co = _contributor_client(admin, 'co_src_c')
    co.post('/api/notes', json={'section': 'A01', 'title': '非法来源提议', 'content': 'x'})
    pid = [p for p in admin.get('/api/proposals?status=pending').get_json()['items']
           if p['payload'].get('title') == '非法来源提议'][0]['id']
    # 绕过前端，直接把非法 source 写进 payload，模拟伪造请求
    db = sqlite3.connect(os.environ['NOTES_DB_PATH'])
    db.execute("UPDATE proposals SET payload=json_set(payload,'$.source',?) WHERE id=?", ('X' * 51, pid))
    db.commit(); db.close()
    assert admin.post(f'/api/proposals/{pid}/approve').status_code == 200
    item = admin.get('/api/notes?q=非法来源提议').get_json()['items'][0]
    assert item['source'] in _app.VALID_SOURCES  # 已归一，非法值未入库


def test_proposal_update_illegal_source_rejected_on_approve(admin):
    """防御：update 提议把 source 改成非法值，批准时应被拦截（自动驳回）。"""
    import os, sqlite3
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '改来源提议', 'content': 'y'}).get_json()['id']
    co = _contributor_client(admin, 'co_src_u')
    co.put(f'/api/notes/{nid}', json={'title': '改来源提议2'})
    pid = admin.get('/api/proposals?status=pending').get_json()['items'][0]['id']
    db = sqlite3.connect(os.environ['NOTES_DB_PATH'])
    db.execute("UPDATE proposals SET payload=json_set(payload,'$.source',?) WHERE id=?", ('X' * 51, pid))
    db.commit(); db.close()
    # 非法来源 -> 自动驳回 409，原笔记来源不变
    assert admin.post(f'/api/proposals/{pid}/approve').status_code == 409
    assert admin.get(f'/api/notes/{nid}').get_json()['source'] in _app.VALID_SOURCES


def test_contributor_sees_only_own_proposals(admin):
    co = _contributor_client(admin, 'co_own')
    co.post('/api/notes', json={'section': 'A01', 'title': '我的提交', 'content': 'x'})
    mine = co.get('/api/proposals').get_json()
    assert all(p['proposer_name'] == 'co_own' for p in mine['items'])
    assert any(p['payload'].get('title') == '我的提交' for p in mine['items'])


def test_approve_update_on_deleted_note_auto_rejects(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '将消失', 'content': 'x'}).get_json()['id']
    co = _contributor_client(admin, 'co_gone')
    co.put(f'/api/notes/{nid}', json={'content': '改'})
    pid = admin.get('/api/proposals?status=pending').get_json()['items'][0]['id']
    admin.delete(f'/api/notes/{nid}')  # 管理员先删了目标
    r = admin.post(f'/api/proposals/{pid}/approve')
    assert r.status_code == 409 and r.get_json().get('auto_rejected') is True


# ---------------- AI 提示词配置 ----------------

def test_get_ai_prompt_default(admin):
    d = admin.get('/api/config/ai-prompt').get_json()
    assert d['is_custom'] is False
    assert d['effective'] == _app.AI_SUMMARY_SYSTEM_PROMPT


def test_set_and_revert_ai_prompt(admin):
    admin.put('/api/config/ai-prompt', json={'prompt': '自定义提示词内容'})
    d = admin.get('/api/config/ai-prompt').get_json()
    assert d['is_custom'] is True and d['effective'] == '自定义提示词内容'
    # 清空恢复默认
    admin.put('/api/config/ai-prompt', json={'prompt': ''})
    d2 = admin.get('/api/config/ai-prompt').get_json()
    assert d2['is_custom'] is False and d2['effective'] == _app.AI_SUMMARY_SYSTEM_PROMPT


def test_summarize_uses_custom_prompt(admin, monkeypatch):
    captured = {}
    def fake_chat(system, user, temperature=0.3):
        captured['system'] = system
        return '## 总结'
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat', fake_chat)
    admin.put('/api/config/ai-prompt', json={'prompt': '电厂专用提示词X'})
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': 't', 'content': '正文'}).get_json()['id']
    admin.post(f'/api/notes/{nid}/summarize')
    assert captured['system'] == '电厂专用提示词X'
    admin.put('/api/config/ai-prompt', json={'prompt': ''})  # 还原


# ---------------- 一键（批量）总结 ----------------

def test_summarize_batch(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, 'SUMMARY_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(_app, '_start_summary_worker', lambda job_id: None)
    monkeypatch.setattr(_app, '_deepseek_summarize', lambda t, c, p=None, s=None: '## 批量总结')
    a = admin.post('/api/notes', json={'section': 'A01', 'title': '批1', 'content': '甲'}).get_json()['id']
    b = admin.post('/api/notes', json={'section': 'A01', 'title': '批2', 'content': '乙'}).get_json()['id']
    empty = admin.post('/api/notes', json={'section': 'A01', 'title': '批空'}).get_json()['id']
    r = admin.post('/api/notes/summarize-batch', json={'ids': [a, b, empty]})
    assert r.status_code == 202
    job_id = r.get_json()['job']['id']
    _app._run_summary_job(job_id)
    body = admin.get(f'/api/notes/summarize-jobs/{job_id}').get_json()['job']
    assert body['done'] == 2 and body['skipped'] == 1
    # 默认跳过已有总结
    r2 = admin.post('/api/notes/summarize-batch', json={'ids': [a]})
    job_id2 = r2.get_json()['job']['id']
    _app._run_summary_job(job_id2)
    body2 = admin.get(f'/api/notes/summarize-jobs/{job_id2}').get_json()['job']
    assert body2['skipped'] == 1 and body2['done'] == 0
    # force 重做
    r3 = admin.post('/api/notes/summarize-batch', json={'ids': [a], 'force': True})
    job_id3 = r3.get_json()['job']['id']
    _app._run_summary_job(job_id3)
    assert admin.get(f'/api/notes/summarize-jobs/{job_id3}').get_json()['job']['done'] == 1


def test_summarize_batch_requires_admin(client):
    assert client.post('/api/notes/summarize-batch', json={'ids': [1]}).status_code == 401


def test_summarize_batch_over_limit_rejected(admin, monkeypatch):
    # 单批上限 30 条：超过应被拒；实际调用在后台慢速执行
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    r = admin.post('/api/notes/summarize-batch', json={'ids': list(range(1, 32))})
    assert r.status_code == 400
    assert '30' in r.get_json()['error']


def test_summarize_all_creates_background_job_and_skips_existing(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, 'SUMMARY_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(_app, '_start_summary_worker', lambda job_id: None)
    monkeypatch.setattr(_app, '_deepseek_summarize', lambda t, c, p=None, s=None: '## 全库总结')
    a = admin.post('/api/notes', json={'section': 'A01', 'title': '全1', 'content': '甲'}).get_json()['id']
    b = admin.post('/api/notes', json={'section': 'A01', 'title': '全2', 'content': '乙'}).get_json()['id']
    admin.post(f'/api/notes/{a}/summarize')

    r = admin.post('/api/notes/summarize-all')
    assert r.status_code == 202
    job_id = r.get_json()['job']['id']
    _app._run_summary_job(job_id)
    job = admin.get(f'/api/notes/summarize-jobs/{job_id}').get_json()['job']
    assert job['done'] >= 1
    assert any(x['id'] == a and x['reason'] == '已有总结' for x in job['skipped_list'])
    assert admin.get(f'/api/notes/{b}').get_json()['ai_summary'] == '## 全库总结'


# ---------------- AI 填充 ----------------

def test_ai_fill_parses_fields(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat',
                        lambda system, user, temperature=0.3:
                        '```json\n{"title":"MFT动作条件","tags":"MFT,保护","section":"A01","level":"★★★","source":"规程"}\n```')
    r = admin.post('/api/ai/fill', json={'content': '锅炉MFT动作条件十六项…'})
    f = r.get_json()['fields']
    assert f['title'] == 'MFT动作条件' and f['section'] == 'A01'
    assert f['level'] == '★★★' and f['source'] == '规程' and 'MFT' in f['tags']


def test_ai_fill_drops_invalid_section(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat',
                        lambda system, user, temperature=0.3:
                        '{"title":"x","tags":"a","section":"ZZZ","level":"★","source":"乱来"}')
    f = admin.post('/api/ai/fill', json={'content': '一些内容'}).get_json()['fields']
    assert f['section'] == '' and f['source'] == ''


def test_ai_fill_empty_content_400(admin):
    assert admin.post('/api/ai/fill', json={'content': ''}).status_code == 400


def test_ai_fill_contributor_allowed(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat',
                        lambda system, user, temperature=0.3: '{"title":"t","tags":"a","section":"A01","level":"★","source":"规程"}')
    co = _contributor_client(admin, 'co_fill')
    assert co.post('/api/ai/fill', json={'content': 'x'}).status_code == 200


# ---------------- AI 整理 ----------------

def test_ai_tidy_returns_content_and_fields(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat',
                        lambda system, user, temperature=0.3:
                        '```json\n{"content":"1. 知识点一\\n2. 知识点二","title":"整理标题",'
                        '"tags":"MFT,保护","section":"A01","level":"★★","source":"规程"}\n```')
    r = admin.post('/api/ai/tidy', json={'content': '安排某班 即日起 一、知识点一 三、知识点二'})
    body = r.get_json()
    assert r.status_code == 200
    assert body['content'] == '1. 知识点一\n2. 知识点二'
    f = body['fields']
    assert f['title'] == '整理标题' and f['section'] == 'A01' and f['source'] == '规程'


def test_ai_tidy_delimiter_format(admin, monkeypatch):
    # 新版「正文 + ===字段=== + 单行JSON」协议：正文是纯文本，多行不再塞进 JSON
    reply = ('1. 知识点一\n2. 知识点二\n===字段===\n'
             '{"title":"整理标题","tags":"MFT,保护","section":"A01","level":"★★","source":"规程"}')
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat', lambda system, user, temperature=0.3: reply)
    body = admin.post('/api/ai/tidy', json={'content': '安排某班 一、知识点一 三、知识点二'}).get_json()
    assert body['content'] == '1. 知识点一\n2. 知识点二'
    assert body['fields']['title'] == '整理标题' and body['fields']['section'] == 'A01'


def test_ai_tidy_non_object_reply_no_500(admin, monkeypatch):
    # 模型返回数组等非对象时不应 500：正文兜底、字段置空
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat', lambda system, user, temperature=0.3: '[1,2,3]')
    r = admin.post('/api/ai/tidy', json={'content': '原文必须保留'})
    assert r.status_code == 200
    assert r.get_json()['content'] == '原文必须保留'


def test_ai_fill_non_object_reply_502(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat', lambda system, user, temperature=0.3: '["not","an","object"]')
    assert admin.post('/api/ai/fill', json={'content': 'x'}).status_code == 502


def test_ai_tidy_blank_content_keeps_original(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    # 模型未给 content 时，兜底保留原文，避免清空
    monkeypatch.setattr(_app, '_deepseek_chat',
                        lambda system, user, temperature=0.3: '{"title":"t","tags":"a","section":"A01"}')
    body = admin.post('/api/ai/tidy', json={'content': '原始正文不能丢'}).get_json()
    assert body['content'] == '原始正文不能丢'


def test_ai_tidy_empty_content_400(admin):
    assert admin.post('/api/ai/tidy', json={'content': ''}).status_code == 400


def test_ai_tidy_contributor_allowed(admin, monkeypatch):
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    monkeypatch.setattr(_app, '_deepseek_chat',
                        lambda system, user, temperature=0.3: '{"content":"x","title":"t","section":"A01"}')
    co = _contributor_client(admin, 'co_tidy')
    assert co.post('/api/ai/tidy', json={'content': 'x'}).status_code == 200


def test_tidy_prompt_config_independent(admin):
    # tidy 与 summary 提示词互不影响
    admin.put('/api/config/ai-prompt', json={'prompt': '整理专用', 'kind': 'tidy'})
    t = admin.get('/api/config/ai-prompt?kind=tidy').get_json()
    s = admin.get('/api/config/ai-prompt').get_json()
    assert t['is_custom'] is True and t['effective'] == '整理专用'
    assert s['is_custom'] is False and s['effective'] == _app.AI_SUMMARY_SYSTEM_PROMPT
    admin.put('/api/config/ai-prompt', json={'prompt': '', 'kind': 'tidy'})  # 还原
    assert admin.get('/api/config/ai-prompt?kind=tidy').get_json()['is_custom'] is False


def test_tidy_uses_custom_prompt(admin, monkeypatch):
    captured = {}
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    def fake_chat(system, user, temperature=0.3):
        captured['system'] = system
        return '{"content":"x","title":"t","section":"A01"}'
    monkeypatch.setattr(_app, '_deepseek_chat', fake_chat)
    admin.put('/api/config/ai-prompt', json={'prompt': '我的整理规则', 'kind': 'tidy'})
    admin.post('/api/ai/tidy', json={'content': '一些正文'})
    assert captured['system'] == '我的整理规则'
    admin.put('/api/config/ai-prompt', json={'prompt': '', 'kind': 'tidy'})  # 还原


def test_fill_prompt_config_independent(admin):
    # fill 提示词独立于 summary / tidy
    d0 = admin.get('/api/config/ai-prompt?kind=fill').get_json()
    assert d0['is_custom'] is False and d0['effective'] == _app.AI_FILL_SYSTEM_PROMPT
    admin.put('/api/config/ai-prompt', json={'prompt': '填充专用规则', 'kind': 'fill'})
    f = admin.get('/api/config/ai-prompt?kind=fill').get_json()
    s = admin.get('/api/config/ai-prompt').get_json()
    assert f['is_custom'] is True and f['effective'] == '填充专用规则'
    assert s['is_custom'] is False  # summary 不受影响
    admin.put('/api/config/ai-prompt', json={'prompt': '', 'kind': 'fill'})  # 还原
    assert admin.get('/api/config/ai-prompt?kind=fill').get_json()['is_custom'] is False


def test_fill_uses_custom_prompt(admin, monkeypatch):
    captured = {}
    monkeypatch.setattr(_app, 'DEEPSEEK_API_KEY', 'k')
    def fake_chat(system, user, temperature=0.3):
        captured['system'] = system
        return '{"title":"t","tags":"a,b","section":"A01","level":"★","source":"规程"}'
    monkeypatch.setattr(_app, '_deepseek_chat', fake_chat)
    admin.put('/api/config/ai-prompt', json={'prompt': '我的填充规则', 'kind': 'fill'})
    admin.post('/api/ai/fill', json={'content': '一些正文'})
    assert captured['system'] == '我的填充规则'
    admin.put('/api/config/ai-prompt', json={'prompt': '', 'kind': 'fill'})  # 还原


# ---------------- 用户收藏 ----------------

def test_favorite_add_list_remove(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '收藏目标', 'content': 'x'}).get_json()['id']
    # 初始未收藏
    assert admin.get(f'/api/notes/{nid}').get_json()['favorited'] is False
    # 收藏
    r = admin.post(f'/api/notes/{nid}/favorite')
    assert r.status_code == 200 and r.get_json()['favorited'] is True
    assert admin.get(f'/api/notes/{nid}').get_json()['favorited'] is True
    # 列表 favorites=1 只返回收藏
    fav = admin.get('/api/notes?favorites=1&per=200').get_json()
    assert any(it['id'] == nid for it in fav['items'])
    assert all(it['favorited'] for it in fav['items'])
    # 取消收藏
    admin.delete(f'/api/notes/{nid}/favorite')
    assert admin.get(f'/api/notes/{nid}').get_json()['favorited'] is False
    fav2 = admin.get('/api/notes?favorites=1&per=200').get_json()
    assert not any(it['id'] == nid for it in fav2['items'])


def test_favorite_is_per_user(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '私有收藏', 'content': 'x'}).get_json()['id']
    admin.post(f'/api/notes/{nid}/favorite')
    _make_user(admin, 'favu', 'viewer')
    other = _new_client()
    other.post('/api/login', json={'username': 'favu', 'password': 'secret123'})
    # 另一个用户看不到 admin 的收藏标记，也筛不出来
    assert other.get(f'/api/notes/{nid}').get_json()['favorited'] is False
    assert other.get('/api/notes?favorites=1&per=200').get_json()['total'] == 0


def test_favorite_requires_login(client):
    assert client.post('/api/notes/1/favorite').status_code == 401


def test_favorite_cleaned_on_delete(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '删后清收藏', 'content': 'x'}).get_json()['id']
    admin.post(f'/api/notes/{nid}/favorite')
    admin.delete(f'/api/notes/{nid}')
    # 收藏筛选里不应再残留
    fav = admin.get('/api/notes?favorites=1&per=200').get_json()
    assert not any(it['id'] == nid for it in fav['items'])


# ---------------- 跨页全选 ids_only ----------------

def test_ids_only_returns_all_matching_ids(admin):
    for i in range(3):
        admin.post('/api/notes', json={'section': 'E02', 'title': f'全选项-{i}', 'content': 'x'})
    d = admin.get('/api/notes?section=E02&ids_only=1').get_json()
    assert 'ids' in d and d['total'] == len(d['ids'])
    assert d['total'] >= 3
    # ids_only 下不返回分页 items
    assert 'items' not in d


def test_proposal_current_includes_content_for_diff(admin):
    nid = admin.post('/api/notes', json={'section': 'A01', 'title': '差异原文', 'content': '原始正文ABC'}).get_json()['id']
    co = _contributor_client(admin, 'co_diff')
    co.put(f'/api/notes/{nid}', json={'content': '修改后的正文XYZ'})
    p = admin.get('/api/proposals?status=pending').get_json()['items'][0]
    assert p['current']['content'] == '原始正文ABC'      # 原文可对比
    assert p['payload']['content'] == '修改后的正文XYZ'   # 新值


def test_proposals_pagination(admin):
    co = _contributor_client(admin, 'co_page')
    for i in range(5):
        co.post('/api/notes', json={'section': 'A01', 'title': f'分页申请-{i}', 'content': 'x'})
    d = admin.get('/api/proposals?per=2&page=1').get_json()
    assert d['per'] == 2 and d['page'] == 1
    assert len(d['items']) == 2
    assert d['total'] >= 5 and d['pages'] >= 3
    # 第二页内容不同
    d2 = admin.get('/api/proposals?per=2&page=2').get_json()
    assert d2['page'] == 2 and len(d2['items']) == 2
    assert d['items'][0]['id'] != d2['items'][0]['id']


# ---------------- 使用反馈 / 建议 ----------------

def test_feedback_submit_and_admin_list(admin):
    # 普通用户提交反馈
    _make_user(admin, 'fbuser', 'viewer')
    u = _new_client(); u.post('/api/login', json={'username': 'fbuser', 'password': 'secret123'})
    assert u.post('/api/feedback', json={'content': '希望增加导出功能'}).status_code == 200
    # 普通用户不能查看反馈列表
    assert u.get('/api/feedback').status_code == 403
    # 管理员可见，且能看到内容与提交人
    data = admin.get('/api/feedback').get_json()
    item = [it for it in data['items'] if it['content'] == '希望增加导出功能'][0]
    assert item['username'] == 'fbuser' and item['status'] == 'open'
    assert data['open'] >= 1


def test_feedback_empty_rejected(admin):
    assert admin.post('/api/feedback', json={'content': '   '}).status_code == 400


def test_feedback_requires_login(client):
    assert client.post('/api/feedback', json={'content': 'x'}).status_code == 401


def test_feedback_mark_done_and_delete(admin):
    admin.post('/api/feedback', json={'content': '待处理项'})
    fid = admin.get('/api/feedback?status=open').get_json()['items'][0]['id']
    # 标记已处理
    assert admin.patch(f'/api/feedback/{fid}', json={'status': 'done'}).status_code == 200
    assert admin.get('/api/feedback/open-count').get_json()['open'] == \
        admin.get('/api/feedback?status=open').get_json()['total']
    done = admin.get('/api/feedback?status=done').get_json()['items']
    assert any(it['id'] == fid and it['handled_by'] for it in done)
    # 删除
    assert admin.delete(f'/api/feedback/{fid}').status_code == 200


# ---------------- 图片压缩 ----------------

def _big_jpeg(w=2600, h=1800):
    from PIL import Image
    im = Image.new('RGB', (w, h))
    px = im.load()
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            c = ((x * 255) // w, (y * 255) // h, 100)
            for dy in range(3):
                for dx in range(3):
                    if x + dx < w and y + dy < h:
                        px[x + dx, y + dy] = c
    buf = io.BytesIO(); im.save(buf, 'JPEG', quality=95)
    return buf.getvalue()


def test_upload_compresses_large_image(admin):
    raw = _big_jpeg()
    r = admin.post('/api/upload', data={'file': (io.BytesIO(raw), 'big.jpg')},
                   content_type='multipart/form-data')
    assert r.status_code == 200
    body = r.get_json()
    # 返回的 size 是压缩后的字节数，应明显小于原图
    assert body['size'] < len(raw)
    # 长边被压到 <= 1920
    from PIL import Image
    served = admin.get(body['url']).data
    w, h = Image.open(io.BytesIO(served)).size
    assert max(w, h) <= 1920


def test_compress_helper_falls_back_for_gif(admin):
    # GIF 原样返回（可能是动图）
    gif = b'GIF89a' + b'\x00' * 50
    assert _app.compress_image_bytes(gif, 'gif') == gif
