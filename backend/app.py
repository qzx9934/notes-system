# -*- coding: utf-8 -*-
"""
电厂运行人员工作笔记 · 后端API
Flask + SQLite RESTful接口
跨平台兼容：Windows / macOS / Linux
"""

import sqlite3
import os
import re
import sys
import time
import hashlib
import platform
import subprocess
import mimetypes

# 确保 PWA 清单以正确 MIME 类型下发（开启了 nosniff，类型错误会被浏览器拒绝）
mimetypes.add_type('application/manifest+json', '.webmanifest')
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g, session, send_from_directory
from flask_cors import CORS
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix


def _env_bool(name, default=False):
    """读取布尔型环境变量（1/true/yes/on 视为真）"""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')

# ---- 跨平台路径计算 ----
# 项目根目录 = backend 的上级目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            static_folder=os.path.join(BASE_DIR, 'frontend'),
            static_url_path='')

# ---- 公网安全相关开关（均可用环境变量配置，默认对本地/便携部署友好） ----
# NOTES_HTTPS=1        ：站点经 HTTPS 提供，开启后下发 Secure Cookie 并发送 HSTS
# NOTES_TRUST_PROXY=1  ：位于反向代理(nginx/caddy 等)之后，按 X-Forwarded-* 还原真实 IP/协议
# NOTES_CORS_ORIGINS   ：允许跨域的来源（逗号分隔）；不设则不开放跨域（同源前端无需 CORS）
# NOTES_COOKIE_SAMESITE：会话 Cookie 的 SameSite，默认 Lax（可设 Strict/None）
HTTPS_ENABLED = _env_bool('NOTES_HTTPS', False)
TRUST_PROXY = _env_bool('NOTES_TRUST_PROXY', False)

# 反向代理之后：让 request.remote_addr / scheme 反映真实客户端（限流、Secure 判断依赖它）
if TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# 跨域：仅当显式配置来源时开启（携带凭证），否则不下发 CORS 头（更安全）
_cors_origins = os.environ.get('NOTES_CORS_ORIGINS', '').strip()
if _cors_origins:
    CORS(app, origins=[o.strip() for o in _cors_origins.split(',') if o.strip()],
         supports_credentials=True)

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

# ---- 会话有效期 8 小时（防止浏览器恢复会话导致自动登录） ----
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

# ---- 会话 Cookie 安全加固 ----
app.config['SESSION_COOKIE_HTTPONLY'] = True          # 禁止 JS 读取会话 Cookie（配合 XSS 防御）
app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('NOTES_COOKIE_SAMESITE', 'Lax')  # 防 CSRF
app.config['SESSION_COOKIE_SECURE'] = HTTPS_ENABLED   # HTTPS 下仅经加密连接发送，防明文泄露

@app.after_request
def set_security_headers(resp):
    """统一注入基础安全响应头"""
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')      # 禁止 MIME 嗅探
    resp.headers.setdefault('X-Frame-Options', 'DENY')                # 防点击劫持
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    # HTML 外壳（index.html）禁用强缓存：代码更新后用户刷新即可拿到新版，
    # 避免浏览器拿旧缓存导致"看起来没变化"。静态资源(js/图标)仍可被 SW/浏览器缓存。
    if resp.mimetype == 'text/html':
        resp.headers['Cache-Control'] = 'no-cache'
    if HTTPS_ENABLED:
        # 强制后续访问走 HTTPS（仅在确为 HTTPS 部署时下发）
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return resp

# ---- 安全拦截：禁止访问隐藏文件/目录（.git / .env 等） ----
BANNED_PREFIXES = ('.git', '.svn', '.env', '.htaccess', '.htpasswd', '.DS_Store')

@app.before_request
def block_sensitive_paths():
    path = request.path
    for segment in path.split('/'):
        if segment.startswith(BANNED_PREFIXES):
            return jsonify({'error': 'forbidden'}), 404

# ---- 全局错误处理：API 路径统一返回干净 JSON，避免泄露堆栈或返回 HTML ----
@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'not found'}), 404
    return e  # 非 API（静态资源/页面）保留默认 404 处理

@app.errorhandler(500)
def handle_500(e):
    app.logger.exception('未处理的服务端错误')   # 堆栈仅进服务端日志
    return jsonify({'error': '服务器内部错误'}), 500

DB_PATH = os.environ.get('NOTES_DB_PATH', os.path.join(BACKEND_DIR, 'notes.db'))

# ---- 图片上传配置 ----
# NOTES_UPLOAD_DIR：图片存储目录（需与数据库一样持久化，勿随重新部署清空）
# NOTES_MAX_UPLOAD_MB：单张图片大小上限（MB），默认 5
# NOTES_UPLOAD_GRACE_SECONDS：孤儿图片清理宽限期（秒），默认 86400(24h)，
#   防止刚上传、尚未保存进笔记的图片被误删
UPLOAD_DIR = os.environ.get('NOTES_UPLOAD_DIR', os.path.join(BACKEND_DIR, 'uploads'))
MAX_UPLOAD_MB = int(os.environ.get('NOTES_MAX_UPLOAD_MB', '5'))
UPLOAD_GRACE_SECONDS = int(os.environ.get('NOTES_UPLOAD_GRACE_SECONDS', '86400'))
# 请求体上限：图片上限 + 1MB 余量（含 multipart 边界等开销）
app.config['MAX_CONTENT_LENGTH'] = (MAX_UPLOAD_MB + 1) * 1024 * 1024
# 匹配笔记内容里引用的上传图片文件名：/uploads/<name>
_UPLOAD_REF_RE = re.compile(r'/uploads/([A-Za-z0-9._-]+)')

def _sniff_image_ext(data):
    """按文件头魔数判定图片类型，返回 (规范扩展名, MIME)；非图片返回 (None, None)"""
    if data[:3] == b'\xff\xd8\xff':
        return 'jpg', 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png', 'image/png'
    if data[:4] == b'GIF8':
        return 'gif', 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp', 'image/webp'
    return None, None

def _referenced_uploads(db):
    """扫描所有笔记内容，返回被引用的上传图片文件名集合"""
    refs = set()
    for row in db.execute('SELECT content FROM notes'):
        for m in _UPLOAD_REF_RE.finditer(row['content'] or ''):
            refs.add(m.group(1))
    return refs

# 匹配正文里的 Markdown 图片（仅本系统上传的 /uploads/ 图片）
_MD_UPLOAD_IMG_RE = re.compile(r'!\[[^\]]*\]\((/uploads/[A-Za-z0-9._/-]+)\)')

def merge_preserved_images(old_content, new_content):
    """ingest 去重更新会整体覆盖正文，导致用户手动插入的图片丢失。
    此函数把「旧正文里有、新正文里没有」的上传图片追加到新正文末尾，确保不丢图。
    多次重新整理也幂等：每张图最多保留一份。
    """
    old_content = old_content or ''
    new_content = new_content or ''
    preserved, seen = [], set()
    for m in _MD_UPLOAD_IMG_RE.finditer(old_content):
        token, url = m.group(0), m.group(1)
        if url in seen or url in new_content:  # 已收过，或新正文已含该图
            continue
        seen.add(url)
        preserved.append(token)
    if not preserved:
        return new_content
    marker = '\n\n---\n*以下图片为手动补充，整理更新时自动保留*\n\n'
    return new_content.rstrip() + marker + '\n\n'.join(preserved)

def sweep_orphan_uploads(db, dry_run=False, grace=None):
    """清理 UPLOAD_DIR 中未被任何笔记引用、且超过宽限期的图片文件。

    宽限期（按文件修改时间）保护刚上传、还没保存进笔记的图片不被误删。
    返回 {'removed': [...], 'freed': 字节数, 'kept': 保留数}。
    """
    grace = UPLOAD_GRACE_SECONDS if grace is None else grace
    result = {'removed': [], 'freed': 0, 'kept': 0}
    if not os.path.isdir(UPLOAD_DIR):
        return result
    refs = _referenced_uploads(db)
    now = time.time()
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if not os.path.isfile(path):
            continue
        # 仍被引用，或还在宽限期内 -> 保留
        if name in refs or (now - os.path.getmtime(path)) < grace:
            result['kept'] += 1
            continue
        try:
            size = os.path.getsize(path)
            if not dry_run:
                os.remove(path)
        except OSError:
            continue
        result['removed'].append(name)
        result['freed'] += size
    return result

def _sweep_quietly():
    """删除笔记后顺手清理孤儿图片；失败绝不影响主流程。"""
    try:
        sweep_orphan_uploads(get_db())
    except Exception:
        app.logger.exception('孤儿图片清理失败（忽略，不影响删除操作）')

# 跨平台浏览器打开（用列表式 subprocess，避免 shell 拼接/注入风险）
def open_browser(url):
    s = platform.system()
    try:
        if s == 'Darwin':
            subprocess.Popen(['open', url])
        elif s == 'Windows':
            os.startfile(url)  # Windows 上打开默认浏览器的标准做法
        else:
            subprocess.Popen(['xdg-open', url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # 打开浏览器失败不影响服务正常启动

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

        CREATE TABLE IF NOT EXISTS api_tokens (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            token           TEXT    NOT NULL UNIQUE,   -- sha256(明文令牌)
            label           TEXT    NOT NULL DEFAULT '',-- 用途备注
            role            TEXT    NOT NULL DEFAULT 'admin',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            last_used_at    TEXT
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
    ('A03', '电气系统', 'A', '发电机、变压器、厂用电系统、10kV/380V配电、直流系统、UPS等', 3),
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
    ('A05-001', 'A05', '10kV高压辅机停送电要点', '一次风机/真空泵/烟气再循环风机等10kV高压辅机动力电源不计入停送电记录，仅记录控制电源', '10kV,高压辅机,停送电', '操作票', '★★★', '2026-05-17'),
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

    # 数据修正：统一 A03 涵盖范围 6kV -> 10kV（仅当仍为旧值时更新，避免覆盖用户自定义）
    db.execute("UPDATE sections SET scope=REPLACE(scope,'6kV/380V','10kV/380V') "
               "WHERE code='A03' AND scope LIKE '%6kV/380V%'")
    db.commit()

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

# ==================== 全文搜索（FTS5） ====================

# 运行时标志：FTS5 + trigram 是否可用（不可用则自动回退到 LIKE 搜索）
FTS_ENABLED = False

def init_fts():
    """创建 FTS5 全文索引（trigram 分词器，支持中文子串匹配）并保持与 notes 同步。

    采用「外部内容表」模式（content='notes'），索引只存倒排数据、不重复存正文；
    通过触发器在增删改时自动更新。若当前 SQLite 不支持 FTS5/trigram，则静默回退。
    """
    global FTS_ENABLED
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title, content, tags,
                content='notes', content_rowid='id',
                tokenize='trigram'
            )
        """)
        # 触发器：保持 FTS 索引与 notes 表同步
        db.executescript("""
            CREATE TRIGGER IF NOT EXISTS notes_fts_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, content, tags)
                VALUES (new.id, new.title, new.content, new.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_fts_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content, tags)
                VALUES ('delete', old.id, old.title, old.content, old.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_fts_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content, tags)
                VALUES ('delete', old.id, old.title, old.content, old.tags);
                INSERT INTO notes_fts(rowid, title, content, tags)
                VALUES (new.id, new.title, new.content, new.tags);
            END;
        """)
        # 首次启用时全量回填（含历史数据库的存量笔记）
        built = db.execute("SELECT value FROM config WHERE key='fts_built'").fetchone()
        if not built:
            db.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
            db.execute("INSERT OR REPLACE INTO config(key,value) VALUES('fts_built','1')")
        db.commit()
        FTS_ENABLED = True
        print('[搜索] FTS5 trigram 全文索引已启用')
    except sqlite3.Error as e:
        FTS_ENABLED = False
        print(f'[搜索] FTS5 不可用，已回退到 LIKE 搜索：{e}')
    finally:
        db.close()

# 全文搜索 trigram 的最小匹配长度（少于此长度回退到 LIKE）
FTS_MIN_LEN = 3

def fts_match_expr(q):
    """把用户输入转成安全的 FTS5 MATCH 表达式：用双引号包成字符串字面量，
    避免输入中的 FTS 运算符（如 * : - NEAR 等）被解释。"""
    return '"' + q.replace('"', '""') + '"'

# 模块加载时自动初始化数据库（兼容 gunicorn/wsgi 导入）
init_db()
seed_db()
init_fts()

# ==================== 认证 ====================

# ---- 登录失败限流（按客户端 IP，进程内内存计数） ----
LOGIN_MAX_FAILS = 5        # 窗口内允许的失败次数
LOGIN_WINDOW = 300         # 失败计数统计窗口（秒）
LOGIN_LOCK_SECONDS = 300   # 达到阈值后的锁定时长（秒）
_LOGIN_FAILS = {}          # ip -> [fail_count, window_start_ts, locked_until_ts]
DEFAULT_ADMIN_PW = 'admin123'

def _client_ip():
    # remote_addr 已由 ProxyFix（当 NOTES_TRUST_PROXY 开启时）按可信代理还原为真实客户端 IP；
    # 不直接读取 X-Forwarded-For，避免未经可信代理时被伪造头绕过限流。
    return request.remote_addr or 'unknown'

def login_lock_remaining(ip):
    """返回该 IP 剩余锁定秒数；未锁定返回 0"""
    rec = _LOGIN_FAILS.get(ip)
    if not rec:
        return 0
    remaining = rec[2] - time.time()
    return int(remaining) if remaining > 0 else 0

def record_login_fail(ip):
    now = time.time()
    rec = _LOGIN_FAILS.get(ip)
    if not rec or now - rec[1] > LOGIN_WINDOW:
        rec = [0, now, 0]
    rec[0] += 1
    if rec[0] >= LOGIN_MAX_FAILS:
        rec[2] = now + LOGIN_LOCK_SECONDS
    _LOGIN_FAILS[ip] = rec

def clear_login_fails(ip):
    _LOGIN_FAILS.pop(ip, None)

def _token_role():
    """从请求头读取 API Token 并返回其角色；无效或缺失返回 None。

    支持两种写法：
      X-API-Token: <token>
      Authorization: Bearer <token>
    另外支持环境变量 NOTES_API_TOKEN 作为主令牌（始终为 admin）。
    """
    token = request.headers.get('X-API-Token', '').strip()
    if not token:
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            token = auth[7:].strip()
    if not token:
        return None

    # 环境变量主令牌（便于一次性/便携部署）
    env_token = os.environ.get('NOTES_API_TOKEN', '')
    if env_token and token == env_token:
        return 'admin'

    th = hashlib.sha256(token.encode('utf-8')).hexdigest()
    db = get_db()
    row = db.execute('SELECT id, role FROM api_tokens WHERE token=?', (th,)).fetchone()
    if not row:
        return None
    db.execute('UPDATE api_tokens SET last_used_at=datetime("now","localtime") WHERE id=?', (row['id'],))
    db.commit()
    return row['role']

def login_required(f):
    """登录验证装饰器：支持会话 Cookie 或 API Token，未授权返回 401 JSON"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' in session:
            return f(*args, **kwargs)
        if _token_role() is not None:
            return f(*args, **kwargs)
        return jsonify({'error': 'unauthorized'}), 401
    return decorated

def admin_required(f):
    """管理员权限装饰器：支持会话 Cookie 或 API Token，非 admin 角色返回 403"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' in session:
            if session.get('role') != 'admin':
                return jsonify({'error': 'forbidden', 'message': '仅管理员可执行此操作'}), 403
            return f(*args, **kwargs)
        role = _token_role()
        if role is None:
            return jsonify({'error': 'unauthorized'}), 401
        if role != 'admin':
            return jsonify({'error': 'forbidden', 'message': '该令牌无管理员权限'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/api/check-auth')
def api_check_auth():
    """检查当前登录状态"""
    if 'user_id' in session:
        return jsonify({
            'authenticated': True,
            'username': session.get('username', ''),
            'role': session.get('role', 'viewer'),
            'default_password': session.get('default_password', False)
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

    ip = _client_ip()
    locked = login_lock_remaining(ip)
    if locked:
        return jsonify({'error': f'登录失败次数过多，请 {locked} 秒后再试'}), 429

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
    if not user or not check_password_hash(user['password_hash'], password):
        record_login_fail(ip)
        return jsonify({'error': '用户名或密码错误'}), 401

    clear_login_fails(ip)
    # 检测是否仍在使用默认管理员口令（用于前端提示横幅）
    default_pw = (user['role'] == 'admin'
                  and check_password_hash(user['password_hash'], DEFAULT_ADMIN_PW))

    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    session['default_password'] = default_pw
    session.permanent = True
    return jsonify({'ok': True, 'username': user['username'], 'role': user['role'],
                    'default_password': default_pw})

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
    session['default_password'] = False  # 已改密，撤下默认口令提示
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
    except Exception:
        db.rollback()
        app.logger.exception('创建用户失败')          # 详情仅记录到服务端日志
        return jsonify({'error': '创建用户失败，请稍后重试'}), 500

@app.route('/api/users/<int:id>', methods=['DELETE'])
@admin_required
def api_user_delete(id):
    """删除用户（管理员专用，不能删除自己）

    注意：@admin_required 也允许 API 令牌管理员（无浏览器会话）调用，
    此时 session 中没有 user_id，用 .get() 避免 KeyError 导致 500。
    """
    if id == session.get('user_id'):
        return jsonify({'error': '不能删除当前登录的管理员账号'}), 400

    db = get_db()
    user = db.execute('SELECT id, username FROM users WHERE id=?', (id,)).fetchone()
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    db.execute('DELETE FROM users WHERE id=?', (id,))
    db.commit()
    return jsonify({'ok': True, 'deleted': {'id': user['id'], 'username': user['username']}})

# ---- API 令牌管理（仅管理员） ----
@app.route('/api/tokens')
@admin_required
def api_tokens_list():
    """列出所有 API 令牌（不含明文，明文仅在创建时返回一次）"""
    db = get_db()
    rows = db.execute(
        'SELECT id, label, role, created_at, last_used_at FROM api_tokens ORDER BY id'
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tokens', methods=['POST'])
@admin_required
def api_token_create():
    """创建 API 令牌；返回的明文 token 只显示这一次，请妥善保存"""
    data = request.get_json() or {}
    label = data.get('label', '').strip()
    role = data.get('role', 'admin').strip()
    if role not in ('admin', 'viewer'):
        return jsonify({'error': '角色只能为 admin 或 viewer'}), 400

    import secrets
    raw = 'ntk_' + secrets.token_hex(24)
    th = hashlib.sha256(raw.encode('utf-8')).hexdigest()

    db = get_db()
    db.execute('INSERT INTO api_tokens(token, label, role) VALUES(?, ?, ?)', (th, label, role))
    db.commit()
    row = db.execute('SELECT id, label, role, created_at FROM api_tokens WHERE token=?', (th,)).fetchone()
    result = dict(row)
    result['token'] = raw  # 明文仅此一次返回
    return jsonify(result), 201

@app.route('/api/tokens/<int:id>', methods=['DELETE'])
@admin_required
def api_token_delete(id):
    """吊销（删除）一个 API 令牌"""
    db = get_db()
    row = db.execute('SELECT id FROM api_tokens WHERE id=?', (id,)).fetchone()
    if not row:
        return jsonify({'error': 'token 不存在'}), 404
    db.execute('DELETE FROM api_tokens WHERE id=?', (id,))
    db.commit()
    return jsonify({'ok': True})

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

# --- 字段校验 ---
VALID_LEVELS = {'★', '★★', '★★★'}
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MAX_PER = 200  # 单页最大返回条数，防止超大查询

def valid_level(v):
    return v in VALID_LEVELS

def valid_date(v):
    """校验 YYYY-MM-DD 且为真实日期"""
    if not _DATE_RE.match(v or ''):
        return False
    try:
        datetime.strptime(v, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def section_exists(db, code):
    return db.execute('SELECT 1 FROM sections WHERE code=?', (code,)).fetchone() is not None

def parse_int(value, default, lo=None, hi=None):
    """安全地解析整数查询参数，非法时回退默认值并夹在 [lo, hi] 区间"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n

def next_code_num(db, section):
    """取某章节当前最大编号序号 + 1（按数字部分计算，不依赖插入顺序）"""
    row = db.execute(
        "SELECT MAX(CAST(substr(code, instr(code,'-')+1) AS INTEGER)) AS m "
        "FROM notes WHERE section=?",
        (section,)
    ).fetchone()
    return (row['m'] or 0) + 1

def insert_note(db, section, title, content='', tags='', source='个人总结',
                level='★', note_date=None):
    """生成 section 下一个编号并插入；遇编号唯一约束冲突自动重试（防并发竞态）。
    返回生成的 code。"""
    if note_date is None:
        note_date = datetime.now().strftime('%Y-%m-%d')
    for _ in range(10):
        code = f'{section}-{next_code_num(db, section):03d}'
        try:
            db.execute(
                'INSERT INTO notes(code,section,title,content,tags,source,level,note_date) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (code, section, title, content, tags, source, level, note_date)
            )
            return code
        except sqlite3.IntegrityError:
            continue  # 编号被并发占用，重新计算后重试
    raise sqlite3.IntegrityError(f'无法为章节 {section} 生成唯一编号')

def move_note_to_section(db, note_id, target_section, extra=None):
    """把笔记移动到目标章节并按新章节重新生成编号；遇冲突自动重试。返回新 code。
    extra: 需一并更新的字段，如 {'level': '★★', 'source': 'x'}。"""
    extra = extra or {}
    for _ in range(10):
        code = f'{target_section}-{next_code_num(db, target_section):03d}'
        cols = ['section=?', 'code=?'] + [f'{k}=?' for k in extra] + ['updated_at=datetime("now","localtime")']
        vals = [target_section, code] + list(extra.values()) + [note_id]
        try:
            db.execute(f'UPDATE notes SET {", ".join(cols)} WHERE id=?', vals)
            return code
        except sqlite3.IntegrityError:
            continue
    raise sqlite3.IntegrityError(f'无法为章节 {target_section} 生成唯一编号')

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
    sort    = request.args.get('sort', 'code').strip()
    page   = parse_int(request.args.get('page'), 1, lo=1)
    per    = parse_int(request.args.get('per'), 50, lo=1, hi=MAX_PER)
    offset = (page - 1) * per

    where = ['1=1']
    params = []

    if q:
        if FTS_ENABLED and len(q) >= FTS_MIN_LEN:
            # FTS5 全文索引：title/content/tags 走倒排索引；code 仍用 LIKE 兜底
            where.append('(n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?) OR n.code LIKE ?)')
            params.extend([fts_match_expr(q), f'%{q}%'])
        else:
            # 回退：FTS 不可用或查询过短（trigram 需 ≥3 字符）
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
    # 'code' 按「章节 + 编号数字部分」排序：避免纯文本排序在某章节超过 999 条时
    # 把 A01-1000 排到 A01-999 之前（编号 :03d 仅是最小宽度，可自然增长到 4 位以上）
    code_order = 'n.section, CAST(substr(n.code, instr(n.code, "-") + 1) AS INTEGER)'
    order_map = {
        'code':    code_order,
        'updated': 'n.updated_at DESC',
        'created': 'n.created_at DESC',
        'random':  'RANDOM()'
    }
    order_by = order_map.get(sort, code_order)
    rows = db.execute(
        f'SELECT n.*, s.name as section_name, s.domain as domain_code '
        f'FROM notes n LEFT JOIN sections s ON n.section = s.code '
        f'WHERE {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?',
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
    if not section_exists(db, section):
        return jsonify({'error': f'未知的章节编码: {section}'}), 400

    level   = data.get('level', '★')
    note_date = data.get('note_date', datetime.now().strftime('%Y-%m-%d'))
    if not valid_level(level):
        return jsonify({'error': 'level 只能为 ★ / ★★ / ★★★'}), 400
    if not valid_date(note_date):
        return jsonify({'error': 'note_date 格式应为 YYYY-MM-DD'}), 400

    code = insert_note(
        db, section, title,
        content=data.get('content', ''),
        tags=data.get('tags', ''),
        source=data.get('source', '个人总结'),
        level=level, note_date=note_date
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

    if not valid_level(level):
        return jsonify({'error': 'level 只能为 ★ / ★★ / ★★★'}), 400
    if not valid_date(note_date):
        return jsonify({'error': 'note_date 格式应为 YYYY-MM-DD'}), 400

    db.execute(
        'UPDATE notes SET title=?,content=?,tags=?,source=?,level=?,note_date=?,updated_at=datetime("now","localtime") WHERE id=?',
        (title, content, tags, source, level, note_date, id)
    )
    db.commit()

    # 内容变更可能移除了图片引用 -> 顺手回收孤儿图片
    if 'content' in data and content != existing['content']:
        _sweep_quietly()

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
    try:
        placeholders = ','.join(['?'] * len(ids))
        cursor = db.execute(f'DELETE FROM notes WHERE id IN ({placeholders})', ids)
        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception('批量删除失败')
        return jsonify({'error': '批量删除失败，请稍后重试'}), 500
    _sweep_quietly()  # 顺手回收因删除而无人引用的图片
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

    db = get_db()

    # 只允许批量更新这些字段；section 变更会触发编号重新生成
    target_section = None
    extra = {}  # 随更新一并设置的字段（level/source）
    for k, v in updates.items():
        if k == 'level':
            if not valid_level(v):
                return jsonify({'error': 'level 只能为 ★ / ★★ / ★★★'}), 400
            extra['level'] = v
        elif k == 'source':
            extra['source'] = v
        elif k == 'section':
            if not section_exists(db, v):
                return jsonify({'error': f'未知的章节编码: {v}'}), 400
            target_section = v

    if not extra and target_section is None:
        return jsonify({'error': '无有效更新字段'}), 400

    placeholders = ','.join(['?'] * len(ids))

    try:
        if target_section is not None:
            # 移动章节：逐条按新章节重新生成编号（编号前缀与所在章节保持一致）
            rows = db.execute(
                f'SELECT id, section FROM notes WHERE id IN ({placeholders})', ids
            ).fetchall()
            updated = 0
            for r in rows:
                if r['section'] == target_section:
                    # 已在目标章节，编号无需变动，仅更新附加字段
                    if extra:
                        cols = [f'{k}=?' for k in extra] + ['updated_at=datetime("now","localtime")']
                        db.execute(f'UPDATE notes SET {", ".join(cols)} WHERE id=?',
                                   list(extra.values()) + [r['id']])
                else:
                    move_note_to_section(db, r['id'], target_section, extra)
                updated += 1
            db.commit()
            return jsonify({'ok': True, 'updated': updated})

        # 仅批量更新 level/source
        cols = [f'{k}=?' for k in extra] + ['updated_at=datetime("now","localtime")']
        sql = f'UPDATE notes SET {", ".join(cols)} WHERE id IN ({placeholders})'
        cursor = db.execute(sql, list(extra.values()) + ids)
        db.commit()
        return jsonify({'ok': True, 'updated': cursor.rowcount})
    except sqlite3.Error:
        # 中途异常：回滚整批，避免半提交 / 连接停留在错误事务态
        db.rollback()
        app.logger.exception('批量更新失败')
        return jsonify({'error': '批量更新失败，请稍后重试'}), 500

# --- 单条笔记 CRUD ---
@app.route('/api/notes/<int:id>', methods=['DELETE'])
@admin_required
def api_note_delete(id):
    db = get_db()
    db.execute('DELETE FROM notes WHERE id=?', (id,))
    db.commit()
    _sweep_quietly()  # 顺手回收因删除而无人引用的图片
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
    if not section_exists(db, section):
        return jsonify({'error': f'未知的章节编码: {section}'}), 400

    added = []
    skipped = []
    merged = []

    def norm_level(entry):
        lv = entry.get('level', '★')
        return lv if valid_level(lv) else '★'

    def norm_date(entry):
        d = entry.get('date', '')
        return d if valid_date(d) else datetime.now().strftime('%Y-%m-%d')

    # 已有标题集合，用于精确去重（与 /ingest 一致：按「章节+标题」完全相等才算重复；
    # 旧版用子串匹配会把"给水泵"误并入"给水泵备用联启逻辑"并丢内容，已弃用）
    existing_titles = {r['title'] for r in db.execute(
        'SELECT title FROM notes WHERE section=?', (section,)).fetchall()}

    try:
        for entry in entries:
            title = entry.get('title', '').strip()
            if not title:
                continue

            if title in existing_titles:
                # 命中已有条目：更新其内容/标签/来源/等级/日期（不再只改日期）
                old = db.execute(
                    'SELECT content FROM notes WHERE section=? AND title=?',
                    (section, title)).fetchone()
                # 保留手动插入、而新正文缺失的图片，避免重新整理时丢图
                content = merge_preserved_images(
                    old['content'] if old else '', entry.get('content', ''))
                db.execute(
                    'UPDATE notes SET content=?,tags=?,source=?,level=?,note_date=?,'
                    'updated_at=datetime("now","localtime") WHERE section=? AND title=?',
                    (content, entry.get('tags', ''),
                     entry.get('source', '个人总结'), norm_level(entry),
                     norm_date(entry), section, title)
                )
                merged.append({'title': title, 'merged_to': title})
                continue

            code = insert_note(
                db, section, title,
                content=entry.get('content', ''),
                tags=entry.get('tags', ''),
                source=entry.get('source', '个人总结'),
                level=norm_level(entry),
                note_date=norm_date(entry)
            )
            existing_titles.add(title)  # 防止同一批内重复标题被重复插入
            added.append({'code': code, 'title': title})

        db.commit()
    except sqlite3.Error:
        db.rollback()
        app.logger.exception('批量追加失败')
        return jsonify({'error': '批量追加失败，请稍后重试'}), 500

    return jsonify({'added': len(added), 'merged': len(merged), 'skipped': len(skipped),
                    'added_list': added, 'merged_list': merged})

# --- 通用批量录入（推荐：命令行 / 大模型整理后上传） ---
@app.route('/api/notes/ingest', methods=['POST'])
@admin_required
def api_notes_ingest():
    """通用批量录入接口。

    与 /api/notes/batch 不同：每条笔记可携带自己的 section，
    因此可在一次请求中向多个章节写入，最适合大模型整理后一次性上传。

    请求体（任选其一）：
      {"notes": [ {note}, ... ]}
      {"entries": [ {note}, ... ]}          # 兼容旧字段名
      {"section": "A01", "notes": [ ... ]}  # 缺省 section，条目未指定时使用

    单条 note 字段：
      section  章节编码（如 A01）；条目未给时用顶层 section
      title    要点标题（必填）
      content  内容详情
      tags     关键词标签，逗号分隔
      source   来源（默认“个人总结”）
      level    等级 ★ / ★★ / ★★★（默认 ★）
      date     日期 YYYY-MM-DD（默认今天，亦兼容 note_date）

    可选顶层参数：
      dedup    是否按「章节+标题」去重并更新已有条目，默认 true

    编号（code）由后端按章节自动生成，无需提供。
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400

    notes = data.get('notes') or data.get('entries') or []
    if not isinstance(notes, list) or not notes:
        return jsonify({'error': '需要非空的 notes 数组'}), 400

    dedup = data.get('dedup', True)
    default_section = (data.get('section') or '').strip()

    db = get_db()
    valid_sections = {r['code'] for r in db.execute('SELECT code FROM sections').fetchall()}

    def pick_date(entry):
        d = entry.get('date') or entry.get('note_date') or ''
        return d if valid_date(d) else datetime.now().strftime('%Y-%m-%d')

    def pick_level(entry):
        lv = entry.get('level', '★')
        return lv if valid_level(lv) else '★'

    added, merged, skipped = [], [], []
    try:
        for idx, entry in enumerate(notes):
            if not isinstance(entry, dict):
                skipped.append({'index': idx, 'reason': '条目不是对象'})
                continue
            title = (entry.get('title') or '').strip()
            section = (entry.get('section') or default_section or '').strip()
            if not title:
                skipped.append({'index': idx, 'reason': 'title 为空'})
                continue
            if section not in valid_sections:
                skipped.append({'index': idx, 'title': title,
                                'reason': f'未知 section: {section or "(空)"}'})
                continue

            if dedup:
                dup = db.execute(
                    'SELECT code, content FROM notes WHERE section=? AND title=?', (section, title)
                ).fetchone()
                if dup:
                    # 保留手动插入、而新正文缺失的图片，避免重新整理时丢图
                    content = merge_preserved_images(dup['content'], entry.get('content', ''))
                    db.execute(
                        'UPDATE notes SET content=?,tags=?,source=?,level=?,note_date=?,'
                        'updated_at=datetime("now","localtime") WHERE code=?',
                        (content, entry.get('tags', ''),
                         entry.get('source', '个人总结'), pick_level(entry),
                         pick_date(entry), dup['code'])
                    )
                    merged.append({'code': dup['code'], 'title': title})
                    continue

            code = insert_note(
                db, section, title,
                content=entry.get('content', ''), tags=entry.get('tags', ''),
                source=entry.get('source', '个人总结'),
                level=pick_level(entry), note_date=pick_date(entry)
            )
            added.append({'code': code, 'title': title})

        db.commit()
    except sqlite3.Error:
        # 整批回滚：避免中途异常留下半提交、连接停留在错误事务态
        db.rollback()
        app.logger.exception('批量录入(ingest)失败')
        return jsonify({'error': '批量录入失败，请稍后重试'}), 500
    return jsonify({'ok': True,
                    'added': len(added), 'merged': len(merged), 'skipped': len(skipped),
                    'added_list': added, 'merged_list': merged, 'skipped_list': skipped})

# --- 从 Excel 导入 ---
@app.route('/api/import-excel', methods=['POST'])
@admin_required
def api_import_excel():
    """从上传的Excel文件导入笔记（手动上传方式，暂不使用）"""
    return jsonify({'error': '请使用前端导入功能'}), 501

# ==================== 图片上传 ====================

@app.route('/api/upload', methods=['POST'])
@admin_required
def api_upload():
    """上传单张图片，返回可直接写进 Markdown 的 URL。
    仅管理员/可编辑者可用；按文件头魔数校验真实类型，文件名取内容 SHA256+扩展名（天然去重）。
    """
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': '未收到文件'}), 400

    data = f.read()
    if not data:
        return jsonify({'error': '文件为空'}), 400
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        return jsonify({'error': f'图片超过 {MAX_UPLOAD_MB}MB 上限'}), 413

    ext, mime = _sniff_image_ext(data)
    if not ext:
        return jsonify({'error': '仅支持 JPG/PNG/GIF/WEBP 图片'}), 415

    digest = hashlib.sha256(data).hexdigest()
    name = f'{digest}.{ext}'
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.exists(path):  # 内容相同则复用，避免重复落盘
        with open(path, 'wb') as out:
            out.write(data)

    return jsonify({'ok': True, 'url': f'/uploads/{name}',
                    'filename': name, 'size': len(data), 'mime': mime})

@app.route('/uploads/<path:name>')
def serve_upload(name):
    """下发已上传的图片（长缓存，文件名即内容哈希，可安全永久缓存）"""
    resp = send_from_directory(UPLOAD_DIR, name)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp

@app.errorhandler(413)
def handle_413(e):
    """请求体超过 MAX_CONTENT_LENGTH（上传图片过大）时返回干净 JSON"""
    return jsonify({'error': f'上传内容过大，单张图片不得超过 {MAX_UPLOAD_MB}MB'}), 413

@app.route('/api/uploads/cleanup', methods=['POST'])
@admin_required
def api_uploads_cleanup():
    """手动清理孤儿图片（无任何笔记引用且超过宽限期的图片文件）。
    传 ?dry_run=1 仅预览不删除。删除笔记时本就会自动清理，此接口用于按需手动触发。
    """
    dry = request.args.get('dry_run', '').strip().lower() in ('1', 'true', 'yes', 'on')
    res = sweep_orphan_uploads(get_db(), dry_run=dry)
    return jsonify({'ok': True, 'dry_run': dry,
                    'removed': len(res['removed']), 'freed_bytes': res['freed'],
                    'kept': res['kept'], 'removed_list': res['removed']})

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
