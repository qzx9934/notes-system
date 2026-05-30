#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量压缩已上传的图片（保清晰度、减体积）。

用于对历史上传的图片做一次性瘦身；新上传的图片在 /api/upload 时已自动压缩。
压缩是「就地、保文件名」的：因为文件名是内容哈希，压缩后字节变化、哈希也会变，
故本脚本会按【新内容哈希】重命名文件，并同步把所有笔记正文里引用的旧文件名替换为新名，
保证图片不丢、引用不断。

用法：
    python tools/compress_images.py            # 预览（dry-run），只统计不改动
    python tools/compress_images.py --apply    # 实际执行
环境变量沿用后端：NOTES_UPLOAD_DIR / NOTES_DB_PATH / NOTES_IMG_MAX_DIM / NOTES_IMG_QUALITY
"""
import os
import sys
import hashlib
import sqlite3

# 复用后端的压缩函数与路径配置
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'backend'))
import app as backend  # noqa: E402


def human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.1f}{unit}'
        n /= 1024


def main():
    apply = '--apply' in sys.argv
    upload_dir = backend.UPLOAD_DIR
    db_path = os.environ.get('NOTES_DB_PATH', os.path.join(BASE, 'backend', 'notes.db'))
    if not os.path.isdir(upload_dir):
        print(f'上传目录不存在：{upload_dir}')
        return

    files = [f for f in os.listdir(upload_dir)
             if os.path.isfile(os.path.join(upload_dir, f)) and '.' in f]
    print(f'共 {len(files)} 个文件，目录：{upload_dir}（{"执行" if apply else "预览"}模式）\n')

    renames = {}          # 旧文件名 -> 新文件名
    saved = total_old = 0
    for name in files:
        ext = name.rsplit('.', 1)[1].lower()
        if ext not in ('jpg', 'jpeg', 'png', 'webp'):
            continue
        path = os.path.join(upload_dir, name)
        with open(path, 'rb') as fh:
            data = fh.read()
        out = backend.compress_image_bytes(data, ext)
        if len(out) >= len(data):
            continue  # 没有变小，跳过
        total_old += len(data)
        saved += len(data) - len(out)
        new_name = hashlib.sha256(out).hexdigest() + '.' + ext
        print(f'  {name[:16]}… {human(len(data))} -> {human(len(out))}  省 {human(len(data)-len(out))}')
        if apply and new_name != name:
            with open(os.path.join(upload_dir, new_name), 'wb') as fh:
                fh.write(out)
            os.remove(path)
            renames[name] = new_name
        elif apply:
            with open(path, 'wb') as fh:
                fh.write(out)

    # 同步更新笔记正文里的引用（文件名变了的）
    if apply and renames:
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        for row in db.execute('SELECT id, content FROM notes'):
            c = row['content'] or ''
            new_c = c
            for old, new in renames.items():
                if old in new_c:
                    new_c = new_c.replace(old, new)
            if new_c != c:
                db.execute('UPDATE notes SET content=? WHERE id=?', (new_c, row['id']))
        db.commit(); db.close()
        print(f'\n已更新 {len(renames)} 个文件名引用。')

    print(f'\n合计可省：{human(saved)}（原 {human(total_old)}）')
    if not apply:
        print('这是预览。加 --apply 实际执行。')


if __name__ == '__main__':
    main()
