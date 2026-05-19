#!/bin/bash
# ====================================================
#   电厂运行人员工作笔记系统 - macOS/Linux 启动器
# ====================================================

set -e

# ---- 定位脚本所在目录（U盘根目录） ----
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_PATH"

echo "===================================================="
echo "  电厂运行人员工作笔记系统 - 便携启动器"
echo "===================================================="
echo ""

# ---- 第一步：找 Python ----
PYTHON=""

# 优先用自带的venv
if [ -f "$SCRIPT_PATH/venv/bin/python3" ]; then
    PYTHON="$SCRIPT_PATH/venv/bin/python3"
    echo "[OK] 检测到便携虚拟环境 Python"
elif [ -f "$SCRIPT_PATH/venv/bin/python" ]; then
    PYTHON="$SCRIPT_PATH/venv/bin/python"
    echo "[OK] 检测到便携虚拟环境 Python"
fi

# 其次找系统Python3
if [ -z "$PYTHON" ]; then
    if command -v python3 &>/dev/null; then
        PYTHON=$(which python3)
        echo "[OK] 检测到系统 Python3: $PYTHON"
    elif command -v python &>/dev/null; then
        PYTHON=$(which python)
        echo "[OK] 检测到系统 Python: $PYTHON"
    fi
fi

# 没找到Python，提示安装
if [ -z "$PYTHON" ]; then
    echo ""
    echo "[!] 未检测到Python，正在自动配置虚拟环境..."
    echo ""
    bash "$SCRIPT_PATH/setup_mac.sh"
    if [ -f "$SCRIPT_PATH/venv/bin/python3" ]; then
        PYTHON="$SCRIPT_PATH/venv/bin/python3"
    else
        echo ""
        echo "[X] 自动配置失败，请手动操作："
        echo "    1. 安装 Python 3.10+: https://www.python.org/downloads/"
        echo "    2. 或运行 ./setup_mac.sh 配置虚拟环境"
        echo ""
        exit 1
    fi
fi

# ---- 第二步：检查并安装依赖 ----
echo "[*] 检查依赖..."
if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    echo "[*] 安装依赖包..."
    "$PYTHON" -m pip install flask flask-cors openpyxl -q
    if [ $? -ne 0 ]; then
        echo "[X] 依赖安装失败，请检查网络连接"
        exit 1
    fi
    echo "[OK] 依赖安装完成"
else
    echo "[OK] 依赖已就绪"
fi

# ---- 第三步：检查数据库，首次运行初始化 ----
if [ ! -f "$SCRIPT_PATH/backend/notes.db" ]; then
    echo "[*] 首次运行，初始化数据库..."
    "$PYTHON" "$SCRIPT_PATH/backend/app.py" --init-only
fi

# ---- 第四步：启动服务 ----
echo ""
echo "[*] 启动服务..."
echo "===================================================="
echo "  访问地址: http://localhost:5000"
echo "  按 Ctrl+C 停止服务"
echo "===================================================="
echo ""

# 启动Flask（前台运行，Ctrl+C可退出）
"$PYTHON" "$SCRIPT_PATH/backend/app.py"
