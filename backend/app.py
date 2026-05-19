# -*- coding: utf-8 -*-
"""
电厂运行人员工作笔记 · 后端API
Flask + SQLite RESTful接口
跨平台兼容：Windows / macOS / Linux
"""

import sqlite3
import os
import sys
import platform
from datetime import datetime
from flask import Flask, request, jsonify, g, session
from flask_cors import CORS
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# ---- 跨平台路径计算 ----
# 项目根目录 = backend 的上级目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            static_folder=os.path.join(BASE_DIR, 'frontend'),
            static_url_path='')
CORS(app)

# ---- 会话密钥（自动生成并持久化） ----
_secret_key = os.environ.get('NOTES_SECRET_KEY', '')
if not _secret_key:
    _secret_file = os.path.join(BACKEND_DIR, '.secret_key')
    if os.path.exists(_secret_file):
        with open(_secret_file, 'r', encoding='utf-8') as _f:
            _secret_key = _f.read().strip()
    if not _secret_key:
        import secrets
        _secret_key = secrets.token_hex(32)
        with open(_secret_file, 'w', encoding='utf-8') as _f:
            _f.write(_secret_key)
app.secret_key = _secret_key

DB_PATH = os.path.join(BACKEND_DIR, 'notes.db')

# 跨平台浏览器打开
def open_browser(url):
    s = platform.system()
    if s == 'Darwin':
        os.system(f'open "{url}"')
    elif s == 'Windows':
        os.system(f'start "" "{url}"')
    else:
        os.system(f'xdg-open "{url}" 2>/dev/null')

# ==================== 数据库 ====================

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript('''
        CREATE TABLE IF NOT EXISTS notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT    NOT NULL UNIQUE,   -- 编号 A01-001
            section     TEXT    NOT NULL,           -- 章节编码 A01
            title       TEXT    NOT NULL,           -- 要点标题
            content     TEXT    NOT NULL DEFAULT '',-- 内容详情
            tags        TEXT    NOT NULL DEFAULT '',-- 关键词标签(逗号分隔)
            source      TEXT    NOT NULL DEFAULT '',-- 来源
            level       TEXT    NOT NULL DEFAULT '★',-- 等级 ★/★★/★★★
            note_date   TEXT    NOT NULL,           -- 日期 YYYY-MM-DD
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_section ON notes(section);
        CREATE INDEX IF NOT EXISTS idx_level   ON notes(level);
        CREATE INDEX IF NOT EXISTS idx_source  ON notes(source);
        CREATE INDEX IF NOT EXISTS idx_tags    ON notes(tags);
        CREATE INDEX IF NOT EXISTS idx_date    ON notes(note_date);

        CREATE TABLE IF NOT EXISTS sections (
            code        TEXT    PRIMARY KEY,       -- A01
            name        TEXT    NOT NULL,           -- 锅炉及辅助系统
            domain      TEXT    NOT NULL,           -- A/B/C/D/E
            scope       TEXT    NOT NULL DEFAULT '',-- 涵盖范围
            sort_order  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS domains (
            code        TEXT    PRIMARY KEY,
            name        TEXT    NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS config (
            key         TEXT    PRIMARY KEY,
            value       TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            password_hash   TEXT    NOT NULL,
            role            TEXT    NOT NULL DEFAULT 'viewer',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );
    ''')
    db.commit()
    db.close()

# ==================== 知识体系种子数据 ====================

DOMAINS_DATA = [
    ('A', '系统设备知识', 1),
    ('B', '运行操作知识', 2),
    ('C', '安全管理知识', 3),
    ('D', '技术标准知识', 4),
    ('E', '综合管理知识', 5),
]

SECTIONS_DATA = [
    ('A01', '锅炉及辅助系统', 'A', '锅炉本体、燃烧器、制粉系统、风烟系统、吹灰系统、锅炉辅机等', 1),
    ('A02', '汽轮机及辅助系统', 'A', '汽轮机本体、凝汽器、除氧器、高低加、给水泵、循环水系统等', 2),
    ('A03', '电气系统', 'A', '发电机、变压器、厂用电系统、6kV/380V配电、直流系统、UPS等', 3),
    ('A04', '热控自动化系统', 'A', 'DCS/DEH控制系统、FSSS炉膛安全、TSI监视、调节阀门、仪表等', 4),
    ('A05', '辅机系统', 'A', '各类泵、风机、压缩机、冷却水系统、压缩空气系统、暖通空调等', 5),
    ('A06', '脱硫脱硝环保系统', 'A', '石灰石-石膏湿法脱硫、SCR脱硝、除尘器、废水处理、CEMS监测等', 6),
    ('A07', '化水处理系统', 'A', '除盐水制备、凝结水精处理、加药系统、取样分析系统等', 7),
    ('A08', '燃料供应系统', 'A', '输煤系统、燃油系统、煤场管理、配煤掺烧等', 8),
    ('A09', '除灰除尘系统', 'A', '电除尘/布袋除尘、气力输灰、灰库、渣系统等', 9),
    ('B01', '机组启停操作', 'B', '冷/温/热态启动、滑参数停机、正常停机、紧急停机操作步骤与关键参数', 10),
    ('B02', '正常运行调整', 'B', '负荷调节、汽温汽压调整、水位调节、燃烧调整、真空调整等', 11),
    ('B03', '定期工作与试验', 'B', '定期切换、联锁试验、保护校验、阀门活动试验、油质化验等', 12),
    ('B04', '设备切换操作', 'B', '辅机并列/切换操作、备用设备投退、系统运行方式变更等', 13),
    ('B05', '停送电操作', 'B', '安措执行/恢复、停送电申请单、设备电源隔离、接地线装拆等', 14),
    ('C01', '安措与两票管理', 'C', '工作票/操作票管理、安措执行与恢复、危险点分析、安全交底等', 15),
    ('C02', '事故预案与应急处理', 'C', '各类型事故预案、应急响应流程、人员分工、汇报程序等', 16),
    ('C03', '异常工况判断与处理', 'C', '参数异常判断、设备故障诊断、隐患识别、临时处置措施等', 17),
    ('C04', '安全规程与制度', 'C', '安规条文、反措要求、两票三制、安全日活动、消防规程等', 18),
    ('D01', '设备参数与运行限额', 'D', '主辅设备额定参数、报警值、跳闸值、运行允许范围等', 19),
    ('D02', '保护定值与联锁逻辑', 'D', '机炉电大联锁、辅机联锁条件、保护投退规定、定值清单等', 20),
    ('D03', '运行规程要点', 'D', '各系统运行规程关键条文、操作注意事项、禁止事项等', 21),
    ('D04', '检修质量标准', 'D', '设备检修后验收标准、试运行要求、质量把关要点等', 22),
    ('E01', '事故通报与经验反馈', 'E', '行业事故通报学习、本厂异常分析、经验反馈落实、防范措施等', 23),
    ('E02', '培训与考试笔记', 'E', '规程考试重点、技能竞赛要点、培训课程笔记、取证考试等', 24),
    ('E03', '值班管理', 'E', '交接班要求、值班日志填写、人员出勤、现场巡视要点等', 25),
    ('E04', '技术改造与优化', 'E', '技改项目记录、节能优化措施、设备变更情况、运行方式优化等', 26),
]

SAMPLE_NOTES = [
    ('A01-001', 'A01', '锅炉MFT动作条件', 'MFT主燃料跳闸条件共16项：炉膛压力高/低、汽包水位高/低、全炉膛失火、送风机全停等', 'MFT,主燃料跳闸,炉膛保护', '规程', '★★★', '2026-05-17'),
    ('A01-002', 'A01', '磨煤机启动前检查', '1.润滑油系统正常 2.密封风压差>=2kPa 3.消防蒸汽阀门关闭 4.出口温度<80℃', '磨煤机,启动,检查', '个人总结', '★★', '2026-05-17'),
    ('A02-001', 'A02', '汽轮机冲转参数', '主汽压力:5.88MPa 主汽温度:>=380℃ 再热汽温:>=320℃ 真空:>=-85kPa', '冲转,参数,启动', '规程', '★★★', '2026-05-17'),
    ('A03-001', 'A03', '6kV厂用电切换', '正常切换采用并联切换，切换时间<200ms；事故切换采用快速切换，残压法切换时残压<30%额定电压', '厂用电,切换,6kV', '规程', '★★★', '2026-05-17'),
    ('A04-001', 'A04', 'DCS画面调出快捷方式', 'F1-F12对应12幅主画面；Ctrl+数字键调出系统分组画面；ALT+P调出参数趋势', 'DCS,快捷键,操作', '培训', '★', '2026-05-17'),
    ('A05-001', 'A05', '10kV高压辅机停送电要点', '一次风机/真空泵/烟气再循环风机等10kV高压辅机动力电源不计入停送电记录，仅记录控制电源', '10kV,高压辅机,停送电', '工作票', '★★★', '2026-05-17'),
    ('A06-001', 'A06', '脱硫浆液循环泵切换', '切换时先启备用泵运行稳定后再停运行泵；注意吸收塔液位>8m，pH值5.2-5.8', '脱硫,浆液循环泵,切换', '规程', '★★', '2026-05-17'),
    ('B01-001', 'B01', '冷态启动曲线要点', '冲转至3000r/min保持30min暖机；并网后以3%负荷率升荷；500MW以上注意汽温匹配', '冷态启动,冲转,暖机', '规程', '★★★', '2026-05-17'),
    ('B05-001', 'B05', '安措命名规范', '非旋转设备（电动门/挡板门/调整门/加热器）后缀用"电源"；旋转设备（风机/泵）后缀用"电机电源"；10kV高压辅机动力电源排除不计', '安措,命名规范,停送电', '个人总结', '★★★', '2026-05-17'),
    ('C01-001', 'C01', '热机工作票审核要点', '待许可票：核对安措完整性；待签发票：核实检修人员资质；编辑票：确认工作内容与安措匹配', '工作票,审核,安措', '个人总结', '★★★', '2026-05-17'),
    ('C02-001', 'C02', '锅炉灭火处理步骤', '1.确认MFT动作 2.检查所有燃料切断 3.维持送引风机运行炉膛吹扫5min 4.查明原因后方可恢复', '灭火,MFT,事故处理', '事故预案', '★★★', '2026-05-17'),
    ('D01-001', 'D01', '汽包水位报警值', '正常:0mm 高高报警:+250mm(MFT) 低低报警:-250mm(MFT) 高报警:+100mm 低报警:-100mm', '汽包水位,报警,MFT', '规程', '★★★', '2026-05-17'),
    ('E01-001', 'E01', '某厂磨煤机爆燃通报', '原因:停磨未充分惰化直接开人孔门;教训:停磨后持续通入惰化蒸汽>=15min，温度降至60℃以下方可开人孔', '磨煤机,爆燃,经验反馈', '事故通报', '★★★', '2026-05-17'),
]

def seed_db():
    db = sqlite3.connect(DB_PATH)

    # 检查是否已执行过种子数据初始化
    seeded = db.execute("SELECT value FROM config WHERE key='seeded'").fetchone()

    # 数据库迁移：为旧版本 users 表添加 role 列
    try:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'viewer'")
        db.commit()
        print('[迁移] 已为 users 表添加 role 列')
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 确保已有 admin 用户的角色为 admin
    db.execute("UPDATE users SET role='admin' WHERE username='admin' AND role!='admin'")
    db.commit()

    # 默认管理员账号（首次运行自动创建）
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        db.execute("INSERT INTO users(username, password_hash, role) VALUES(?, ?, ?)",
                   ('admin', generate_password_hash('admin123'), 'admin'))
        db.commit()
        print('[认证] 已创建默认管理员账号: admin / admin123 (角色: admin)')

    if seeded:
        # 已初始化过，只确保领域和章节数据完整（用 OR IGNORE）
        db.executemany('INSERT OR IGNORE INTO domains(code,name,sort_order) VALUES(?,?,?)', DOMAINS_DATA)
        db.executemany('INSERT OR IGNORE INTO sections(code,name,domain,scope,sort_order) VALUES(?,?,?,?,?)', SECTIONS_DATA)
        db.commit()
        db.close()
        return

    # 首次初始化：写入全部种子数据
    db.executemany('INSERT OR IGNORE INTO domains(code,name,sort_order) VALUES(?,?,?)', DOMAINS_DATA)
    db.executemany('INSERT OR IGNORE INTO sections(code,name,domain,scope,sort_order) VALUES(?,?,?,?,?)', SECTIONS_DATA)
    # 示例笔记
    for note in SAMPLE_NOTES:
        try:
            db.execute(
                'INSERT INTO notes(code,section,title,content,tags,source,level,note_date) VALUES(?,?,?,?,?,?,?,?)',
                note
            )
        except sqlite3.IntegrityError:
            pass
    # 标记已初始化
    db.execute("INSERT INTO config(key,value) VALUES('seeded','1')")
    db.commit()
    db.close()

# 模块加载时自动初始化数据库（兼容 gunicorn/wsgi 导入）
init_db()
seed_db()

# ==================== 认证 ====================

def login_required(f):
    """登录验证装饰器：未登录返回 401 JSON"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """管理员权限装饰器：非 admin 角色返回 403"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'unauthorized'}), 401
        if session.get('role') != 'admin':
            return jsonify({'error': 'forbidden', 'message': '仅管理员可执行此操作'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/api/check-auth')
def api_check_auth():
    """检查当前登录状态"""
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'username': session.get('username', ''),
            'role': session.get('role', 'viewer')
        })
    return jsonify({'authenticated': False}), 401

@app.route('/api/login', methods=['POST'])
def api_login():
    """用户登录"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '请提供用户名和密码'}), 400
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': '用户名或密码错误'}), 401

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    session.permanent = True
    return jsonify({'ok': True, 'username': user['username'], 'role': user['role']})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """退出登录"""
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    """修改当前用户密码"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'error': '新旧密码不能为空'}), 400
    if len(new_password) < 6:
        return jsonify({'error': '新密码至少6位'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if not user or not check_password_hash(user['password_hash'], old_password):
        return jsonify({'error': '原密码错误'}), 401

    db.execute('UPDATE users SET password_hash=? WHERE id=?',
               (generate_password_hash(new_password), session['user_id']))
    db.commit()
    return jsonify({'ok': True})

# ---- 用户管理（仅管理员） ----
@app.route('/api/users')
@admin_required
def api_users_list():
    """列出所有用户（管理员专用）"""
    db = get_db()
    rows = db.execute('SELECT id, username, role, created_at FROM users ORDER BY id').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/users', methods=['POST'])
@admin_required
def api_user_create():
    """创建新用户（管理员专用）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'viewer').strip()

    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400
    if len(password) < 6:
        return jsonify({'error': '密码至少6位'}), 400
    if role not in ('admin', 'viewer'):
        return jsonify({'error': '角色只能为 admin 或 viewer'}), 400

    db = get_db()
    existing = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
    if existing:
        return jsonify({'error': f'用户名 "{username}" 已存在'}), 409

    try:
        db.execute('INSERT INTO users(username, password_hash, role) VALUES(?, ?, ?)',
                   (username, generate_password_hash(password), role))
        db.commit()
        user = db.execute('SELECT id, username, role, created_at FROM users WHERE username=?', (username,)).fetchone()
        return jsonify(dict(user)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/users/<int:id>', methods=['DELETE'])
@admin_required
def api_user_delete(id):
    """删除用户（管理员专用，不能删除自己）"""
    if id == session['user_id']:
        return jsonify({'error': '不能删除当前登录的管理员账号'}), 400

    db = get_db()
    user = db.execute('SELECT id, username FROM users WHERE id=?', (id,)).fetchone()
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    db.execute('DELETE FROM users WHERE id=?', (id,))
    db.commit()
    return jsonify({'ok': True, 'deleted': {'id': user['id'], 'username': user['username']}})

# ==================== API 路由 ====================

def note_to_dict(row):
    return {
        'id': row['id'],
        'code': row['code'],
        'section': row['section'],
        'title': row['title'],
        'content': row['content'],
        'tags': row['tags'],
        'source': row['source'],
        'level': row['level'],
        'note_date': row['note_date'],
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }

# --- 知识体系 ---
@app.route('/api/domains')
@login_required
def api_domains():
    db = get_db()
    rows = db.execute('SELECT * FROM domains ORDER BY sort_order').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/sections')
@login_required
def api_sections():
    db = get_db()
    rows = db.execute('SELECT s.*,d.name as domain_name FROM sections s LEFT JOIN domains d ON s.domain=d.code ORDER BY s.sort_order').fetchall()
    return jsonify([dict(r) for r in rows])

# --- 笔记 CRUD ---
@app.route('/api/notes')
@login_required
def api_notes_list():
    db = get_db()
    q    = request.args.get('q', '').strip()
    section = request.args.get('section', '').strip()
    level   = request.args.get('level', '').strip()
    source  = request.args.get('source', '').strip()
    domain  = request.args.get('domain', '').strip()
    page   = int(request.args.get('page', 1))
    per    = int(request.args.get('per', 50))
    offset = (page - 1) * per

    where = ['1=1']
    params = []

    if q:
        where.append('(n.title LIKE ? OR n.content LIKE ? OR n.tags LIKE ? OR n.code LIKE ?)')
        like = f'%{q}%'
        params.extend([like, like, like, like])

    if section:
        where.append('n.section = ?')
        params.append(section)

    if level:
        where.append('n.level = ?')
        params.append(level)

    if source:
        where.append('n.source = ?')
        params.append(source)

    if domain:
        where.append('n.section IN (SELECT code FROM sections WHERE domain = ?)')
        params.append(domain)

    where_clause = ' AND '.join(where)

    # count
    total = db.execute(f'SELECT COUNT(*) FROM notes n WHERE {where_clause}', params).fetchone()[0]

    # data
    rows = db.execute(
        f'SELECT n.*, s.name as section_name, s.domain as domain_code '
        f'FROM notes n LEFT JOIN sections s ON n.section = s.code '
        f'WHERE {where_clause} ORDER BY n.code LIMIT ? OFFSET ?',
        params + [per, offset]
    ).fetchall()

    return jsonify({
        'items': [dict(r) for r in rows],
        'total': total,
        'page': page,
        'per': per,
        'pages': (total + per - 1) // per if total > 0 else 0
    })

@app.route('/api/notes/<int:id>')
@login_required
def api_note_get(id):
    db = get_db()
    row = db.execute('SELECT n.*, s.name as section_name FROM notes n LEFT JOIN sections s ON n.section=s.code WHERE n.id=?', (id,)).fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    return jsonify(dict(row))

@app.route('/api/notes', methods=['POST'])
@admin_required
def api_note_create():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400

    section = data.get('section', '')
    title   = data.get('title', '').strip()
    if not section or not title:
        return jsonify({'error': 'section 和 title 为必填'}), 400

    db = get_db()
    # 自动生成编号
    max_code = db.execute(
        'SELECT code FROM notes WHERE section=? ORDER BY id DESC LIMIT 1', (section,)
    ).fetchone()
    if max_code:
        last_num = int(max_code['code'].split('-')[1])
        new_num = last_num + 1
    else:
        new_num = 1
    code = f'{section}-{new_num:03d}'

    content = data.get('content', '')
    tags    = data.get('tags', '')
    source  = data.get('source', '个人总结')
    level   = data.get('level', '★')
    note_date = data.get('note_date', datetime.now().strftime('%Y-%m-%d'))

    db.execute(
        'INSERT INTO notes(code,section,title,content,tags,source,level,note_date) VALUES(?,?,?,?,?,?,?,?)',
        (code, section, title, content, tags, source, level, note_date)
    )
    db.commit()

    row = db.execute('SELECT * FROM notes WHERE code=?', (code,)).fetchone()
    return jsonify(note_to_dict(row)), 201

@app.route('/api/notes/<int:id>', methods=['PUT'])
@admin_required
def api_note_update(id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400

    db = get_db()
    existing = db.execute('SELECT * FROM notes WHERE id=?', (id,)).fetchone()
    if not existing:
        return jsonify({'error': 'not found'}), 404

    title   = data.get('title', existing['title'])
    content = data.get('content', existing['content'])
    tags    = data.get('tags', existing['tags'])
    source  = data.get('source', existing['source'])
    level   = data.get('level', existing['level'])
    note_date = data.get('note_date', existing['note_date'])

    db.execute(
        'UPDATE notes SET title=?,content=?,tags=?,source=?,level=?,note_date=?,updated_at=datetime("now","localtime") WHERE id=?',
        (title, content, tags, source, level, note_date, id)
    )
    db.commit()

    row = db.execute('SELECT * FROM notes WHERE id=?', (id,)).fetchone()
    return jsonify(note_to_dict(row))

# --- 批量操作 ---
@app.route('/api/notes/batch', methods=['DELETE'])
@admin_required
def api_notes_batch_delete():
    """批量删除笔记"""
    data = request.get_json()
    ids = data.get('ids', []) if data else []
    if not ids:
        return jsonify({'error': 'ids 不能为空'}), 400
    db = get_db()
    placeholders = ','.join(['?'] * len(ids))
    cursor = db.execute(f'DELETE FROM notes WHERE id IN ({placeholders})', ids)
    db.commit()
    return jsonify({'ok': True, 'deleted': cursor.rowcount})

@app.route('/api/notes/batch', methods=['PUT'])
@admin_required
def api_notes_batch_update():
    """批量更新笔记字段（等级/章节/来源）"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400
    ids = data.get('ids', [])
    updates = data.get('updates', {})
    if not ids or not updates:
        return jsonify({'error': 'ids 和 updates 不能为空'}), 400

    # 只允许批量更新这些字段
    allowed = {'level', 'section', 'source'}
    set_parts = []
    params = []
    for k, v in updates.items():
        if k in allowed:
            set_parts.append(f'{k}=?')
            params.append(v)

    if not set_parts:
        return jsonify({'error': '无有效更新字段'}), 400

    db = get_db()
    placeholders = ','.join(['?'] * len(ids))
    sql = f'UPDATE notes SET {", ".join(set_parts)}, updated_at=datetime("now","localtime") WHERE id IN ({placeholders})'
    params.extend(ids)
    cursor = db.execute(sql, params)
    db.commit()
    return jsonify({'ok': True, 'updated': cursor.rowcount})

# --- 单条笔记 CRUD ---
@app.route('/api/notes/<int:id>', methods=['DELETE'])
@admin_required
def api_note_delete(id):
    db = get_db()
    db.execute('DELETE FROM notes WHERE id=?', (id,))
    db.commit()
    return jsonify({'ok': True})

# --- 统计 ---
@app.route('/api/stats')
@login_required
def api_stats():
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM notes').fetchone()[0]
    by_level = db.execute('SELECT level, COUNT(*) as cnt FROM notes GROUP BY level ORDER BY level DESC').fetchall()
    by_source = db.execute('SELECT source, COUNT(*) as cnt FROM notes GROUP BY source ORDER BY cnt DESC').fetchall()
    by_section = db.execute(
        'SELECT n.section, s.name, COUNT(*) as cnt FROM notes n '
        'LEFT JOIN sections s ON n.section=s.code '
        'GROUP BY n.section ORDER BY s.sort_order'
    ).fetchall()
    return jsonify({
        'total': total,
        'by_level': [dict(r) for r in by_level],
        'by_source': [dict(r) for r in by_source],
        'by_section': [dict(r) for r in by_section],
    })

# --- Agent 批量追加 ---
@app.route('/api/notes/batch', methods=['POST'])
@admin_required
def api_note_batch():
    """Agent批量追加接口，格式同Word文档JSON模板"""
    data = request.get_json()
    if not data or 'entries' not in data:
        return jsonify({'error': '需要 entries 数组'}), 400

    section = data.get('section', '')
    entries = data.get('entries', [])
    if not section or not entries:
        return jsonify({'error': 'section 和 entries 为必填'}), 400

    db = get_db()
    added = []
    skipped = []
    merged = []

    # 获取当前最大序号
    max_code_row = db.execute(
        'SELECT code FROM notes WHERE section=? ORDER BY id DESC LIMIT 1', (section,)
    ).fetchone()
    if max_code_row:
        next_num = int(max_code_row['code'].split('-')[1]) + 1
    else:
        next_num = 1

    # 获取已有标题用于重复检测
    existing_titles = [r['title'] for r in db.execute('SELECT title FROM notes WHERE section=?', (section,)).fetchall()]

    for entry in entries:
        title = entry.get('title', '').strip()
        if not title:
            continue

        # 重复检测（简单标题相似）
        is_dup = False
        for et in existing_titles:
            if title in et or et in title:
                # 合并：更新已有条目日期
                db.execute('UPDATE notes SET updated_at=datetime("now","localtime"), note_date=? WHERE section=? AND title=?',
                          (entry.get('date', datetime.now().strftime('%Y-%m-%d')), section, et))
                merged.append({'title': title, 'merged_to': et})
                is_dup = True
                break

        if is_dup:
            continue

        code = f'{section}-{next_num:03d}'
        db.execute(
            'INSERT INTO notes(code,section,title,content,tags,source,level,note_date) VALUES(?,?,?,?,?,?,?,?)',
            (code, section, title,
             entry.get('content', ''),
             entry.get('tags', ''),
             entry.get('source', '个人总结'),
             entry.get('level', '★'),
             entry.get('date', datetime.now().strftime('%Y-%m-%d')))
        )
        added.append({'code': code, 'title': title})
        next_num += 1

    db.commit()
    return jsonify({'added': len(added), 'merged': len(merged), 'skipped': len(skipped),
                    'added_list': added, 'merged_list': merged})

# --- 从 Excel 导入 ---
@app.route('/api/import-excel', methods=['POST'])
@admin_required
def api_import_excel():
    """从上传的Excel文件导入笔记（手动上传方式，暂不使用）"""
    return jsonify({'error': '请使用前端导入功能'}), 501

# ==================== 启动 ====================

@app.route('/')
def index():
    return app.send_static_file('index.html')

def main():
    """主入口：启动服务"""
    if '--init-only' in sys.argv:
        print('数据库初始化完成')
        return
    print('=' * 50)
    print('  电厂运行人员工作笔记系统')
    print('  访问地址: http://localhost:5000')
    print('  按 Ctrl+C 停止服务')
    print('=' * 50)

    # 2秒后自动打开浏览器
    import threading
    def _open():
        import time
        time.sleep(2)
        open_browser('http://localhost:5000')
    threading.Thread(target=_open, daemon=True).start()

    app.run(debug=False, host='127.0.0.1', port=5000)

if __name__ == '__main__':
    main()
