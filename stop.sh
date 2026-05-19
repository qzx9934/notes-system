#!/bin/bash
# ====================================================
#   电厂运行人员工作笔记系统 - macOS/Linux 停止脚本
# ====================================================

echo "正在停止工作笔记系统服务..."

# 查找并终止运行 app.py 的 Python 进程
PIDS=$(ps aux | grep "[a]pp\.py" | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
    for PID in $PIDS; do
        kill "$PID" 2>/dev/null
    done
    echo "服务已停止 (PID: $PIDS)"
else
    echo "未检测到运行中的服务"
fi
