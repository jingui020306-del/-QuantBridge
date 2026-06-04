#!/usr/bin/env bash
# ============================================================
# QuantBridge 一键启动脚本
#
# 启动顺序：
#   1. 激活 conda 环境
#   2. 后台启动 QuantBridge daemon
#   3. 后台启动 Streamlit dashboard
#   4. 前台启动 FinceptTerminal（如果存在）
#   5. 退出时自动清理所有后台进程
# ============================================================

set -e

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV="quantbridge"
FINCEPT_HOME="${FINCEPT_HOME:-}"
WATCH_DIR="$SCRIPT_DIR/outputs/watch"
CLEANED_UP=0

# ---- 清理函数 ----
cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        exit 0
    fi
    CLEANED_UP=1
    trap - SIGINT SIGTERM EXIT

    echo ""
    echo -e "${YELLOW}正在关闭 QuantBridge...${NC}"

    # 停止 daemon
    if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
        kill "$DAEMON_PID" 2>/dev/null || true
        echo -e "${GREEN}✓ Daemon 已停止${NC}"
    fi

    # 停止 dashboard
    if [ -n "$DASHBOARD_PID" ] && kill -0 "$DASHBOARD_PID" 2>/dev/null; then
        kill "$DASHBOARD_PID" 2>/dev/null || true
        echo -e "${GREEN}✓ Dashboard 已停止${NC}"
    fi

    # 停止 FinceptTerminal（如果我们在前台启动了它）
    if [ -n "$FINCEPT_PID" ] && kill -0 "$FINCEPT_PID" 2>/dev/null; then
        kill "$FINCEPT_PID" 2>/dev/null || true
        echo -e "${GREEN}✓ FinceptTerminal 已停止${NC}"
    fi

    echo -e "${GREEN}QuantBridge 已完全关闭${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# ---- FinceptTerminal 发现 ----
resolve_fincept_exec() {
    if [ -n "${FINCEPT_EXEC:-}" ] && [ -x "$FINCEPT_EXEC" ]; then
        return 0
    fi

    FINCEPT_ROOTS=()
    if [ -n "$FINCEPT_HOME" ]; then
        FINCEPT_ROOTS+=("$FINCEPT_HOME")
    fi
    FINCEPT_ROOTS+=(
        "$SCRIPT_DIR/../FinceptTerminal"
        "$SCRIPT_DIR/vendor/FinceptTerminal"
    )

    FINCEPT_CANDIDATES=()
    for root in "${FINCEPT_ROOTS[@]}"; do
        FINCEPT_CANDIDATES+=(
            "$root/build/fincept"
            "$root/build/macos-release/FinceptTerminal"
            "$root/build/macos-debug/FinceptTerminal"
            "$root/fincept-qt/build/macos-release/FinceptTerminal"
            "$root/fincept-qt/build/macos-debug/FinceptTerminal"
            "$root/fincept-qt/build/macos-release/FinceptTerminal.app/Contents/MacOS/FinceptTerminal"
            "$root/fincept-qt/build/macos-debug/FinceptTerminal.app/Contents/MacOS/FinceptTerminal"
        )
    done

    for candidate in "${FINCEPT_CANDIDATES[@]}"; do
        if [ -x "$candidate" ]; then
            FINCEPT_EXEC="$candidate"
            return 0
        fi
    done

    return 1
}

# ---- 检查 conda ----
check_conda() {
    if [ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniforge3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    elif command -v conda &>/dev/null; then
        eval "$(conda shell.bash hook)"
    else
        echo -e "${RED}❌ 未找到 conda，请先安装 miniforge3 或 conda${NC}"
        exit 1
    fi
}

# ---- 主流程 ----
echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}   QuantBridge 一键启动${NC}"
echo -e "${BLUE}=====================================${NC}"
echo ""

# 1. 环境
check_conda
echo -e "${YELLOW}激活 conda 环境: ${CONDA_ENV}${NC}"
conda activate "$CONDA_ENV" 2>/dev/null || {
    echo -e "${RED}❌ conda 环境 '${CONDA_ENV}' 不存在${NC}"
    echo -e "${YELLOW}请先运行: conda env create -f environment.yml${NC}"
    exit 1
}
echo -e "${GREEN}✓ 环境已激活${NC}"

# 2. 确保输出目录
mkdir -p "$WATCH_DIR"
mkdir -p "$SCRIPT_DIR/outputs/cache"
mkdir -p "$SCRIPT_DIR/outputs/reports"

# 3. 启动 daemon（后台）
echo -e "${YELLOW}启动 QuantBridge Daemon...${NC}"
cd "$SCRIPT_DIR"
python -m quantbridge.pipeline --daemon \
    --config "$SCRIPT_DIR/config/default.yaml" &
DAEMON_PID=$!
echo -e "${GREEN}✓ Daemon 已启动 (PID: $DAEMON_PID)${NC}"

sleep 2

# 4. 启动 dashboard（后台）
echo -e "${YELLOW}启动 Streamlit Dashboard...${NC}"
streamlit run "$SCRIPT_DIR/quantbridge/dashboard.py" \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false &
DASHBOARD_PID=$!
echo -e "${GREEN}✓ Dashboard 已启动 (PID: $DASHBOARD_PID)${NC}"
echo -e "${GREEN}  打开 http://localhost:8501${NC}"

sleep 1

# 5. 启动 FinceptTerminal（前台）
resolve_fincept_exec || true

if [ -x "$FINCEPT_EXEC" ]; then
    echo -e "${YELLOW}启动 FinceptTerminal...${NC}"
    echo -e "${GREEN}✓ FinceptTerminal: $FINCEPT_EXEC${NC}"
    echo ""
    echo -e "${GREEN}=====================================${NC}"
    echo -e "${GREEN}   QuantBridge 已就绪${NC}"
    echo -e "${GREEN}   Dashboard: http://localhost:8501${NC}"
    echo -e "${GREEN}   Daemon: 后台运行中${NC}"
    echo -e "${GREEN}   FinceptTerminal: 前台运行中${NC}"
    echo -e "${GREEN}=====================================${NC}"
    echo ""

    "$FINCEPT_EXEC" &
    FINCEPT_PID=$!
    wait "$FINCEPT_PID"
else
    echo ""
    echo -e "${GREEN}=====================================${NC}"
    echo -e "${GREEN}   QuantBridge 已就绪（无 FinceptTerminal）${NC}"
    echo -e "${GREEN}   Dashboard: http://localhost:8501${NC}"
    echo -e "${GREEN}   Daemon: 后台运行中${NC}"
    echo -e "${GREEN}   按 Ctrl+C 关闭${NC}"
    echo -e "${GREEN}=====================================${NC}"
    echo ""

    # 没有 FinceptTerminal 时，等待 daemon
    wait "$DAEMON_PID" 2>/dev/null || true
fi
