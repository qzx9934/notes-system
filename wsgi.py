# -*- coding: utf-8 -*-
"""
WSGI 入口文件
Gunicorn 通过此文件加载 Flask 应用
用法: gunicorn wsgi:app
"""
import sys
import os

# 将 backend 目录加入 Python 模块搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app import app   # noqa: E402
