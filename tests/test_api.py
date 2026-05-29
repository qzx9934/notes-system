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
