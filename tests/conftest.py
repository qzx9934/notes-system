# -*- coding: utf-8 -*-
"""pytest 公共夹具：使用临时数据库导入后端 app，避免污染真实 notes.db。"""
import os
import sys
import tempfile

# 必须在 import app 之前设置环境变量（app 在模块加载时即初始化数据库）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
_TMPDIR = tempfile.mkdtemp(prefix='notes_test_')
os.environ['NOTES_DB_PATH'] = os.path.join(_TMPDIR, 'test_notes.db')
os.environ['NOTES_UPLOAD_DIR'] = os.path.join(_TMPDIR, 'uploads')
os.environ['NOTES_SECRET_KEY'] = 'test-secret-key'
os.environ.pop('NOTES_API_TOKEN', None)  # 确保不受外部主令牌影响

import pytest  # noqa: E402
import app as app_module  # noqa: E402


@pytest.fixture
def client():
    app_module.app.testing = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """每个测试前清空登录失败计数，避免限流测试影响其它用例。"""
    app_module._LOGIN_FAILS.clear()
    yield


@pytest.fixture
def admin(client):
    """登录为默认管理员的 client。"""
    r = client.post('/api/login', json={'username': 'admin', 'password': 'admin123'})
    assert r.status_code == 200
    return client
