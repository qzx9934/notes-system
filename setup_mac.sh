#!/bin/bash
# ====================================================
#   便携Python虚拟环境配置工具 (macOS/Linux)
#   使用系统Python创建venv，安装项目依赖
#   创建后整个文件夹可拷贝到U盘，在其他Mac上直接使用
# ====================================================

set -e

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_PATH"

echo "===================================================="
echo "  便携Python虚拟环境自动配置工具"
echo "  创建本地venv + 安装依赖，U盘即插即用"
echo "===================================================="
echo ""

# ---- 检查是否已存在 ----
if [ -f "$SCRIPT_PATH/venv/bin/python3" ]; then
    echo "[OK] 虚拟环境已存在，无需重复配置"
    echo "    路径: $SCRIPT_PATH/venv/bin/python3"
    echo ""
    echo "如需重建，请先删除 venv 目录后重新运行"
    exit 0
fi

# ---- 找Python3 ----
PY_CMD=""
if command -v python3 &>/dev/null; then
    PY_CMD=$(which python3)
elif command -v python &>/dev/null; then
    PY_CMD=$(which python)
fi

if [ -z "$PY_CMD" ]; then
    echo "[X] 未找到Python3，请先安装："
    echo "    macOS:  brew install python3"
    echo "    或访问: https://www.python.org/downloads/"
    exit 1
fi

PY_VER=$("$PY_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[OK] 找到 Python $PY_VER: $PY_CMD"

# ---- 检查Python版本 ----
PY_MAJOR=$("$PY_CMD" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PY_CMD" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]); then
    echo "[X] Python版本过低（需3.8+），当前: $PY_VER"
    exit 1
fi

# ---- 创建venv ----
echo ""
echo "[1/3] 创建虚拟环境..."
"$PY_CMD" -m venv "$SCRIPT_PATH/venv"
if [ ! -f "$SCRIPT_PATH/venv/bin/python3" ]; then
    echo "[X] 创建虚拟环境失败"
    exit 1
fi
echo "[OK] 虚拟环境创建完成"

# ---- 安装依赖 ----
echo ""
echo "[2/3] 安装项目依赖..."
"$SCRIPT_PATH/venv/bin/pip" install --upgrade pip -q 2>/dev/null
"$SCRIPT_PATH/venv/bin/pip" install flask flask-cors openpyxl -q
if [ $? -ne 0 ]; then
    echo "[!] 部分依赖安装失败，首次启动时会自动重试"
else
    echo "[OK] 依赖安装完成"
fi

# ---- 初始化数据库 ----
echo ""
echo "[3/3] 初始化数据库..."
"$SCRIPT_PATH/venv/bin/python3" "$SCRIPT_PATH/backend/app.py" --init-only
echo "[OK] 数据库初始化完成"

echo ""
echo "===================================================="
echo "  便携Python配置完成！"
echo "  双击 start.sh 或运行 ./start.sh 即可运行"
echo "===================================================="
echo ""
