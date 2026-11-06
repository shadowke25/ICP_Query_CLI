#!/usr/bin/env bash
# ICP_Query CLI - Kali Linux 安装脚本
# 用法: ./install.sh [--python /path/to/python3] [--bin-dir DIR]
set -euo pipefail

APP_NAME="icp-query"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${ICP_QUERY_HOME:-$HOME/.local/share/icp-query}"
VENV_DIR="$DATA_DIR/venv"
BIN_DIR="${ICP_QUERY_BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="python3"

usage() {
    cat <<'EOF'
用法: ./install.sh [选项]

选项:
  --python PATH    指定 Python 解释器（默认 python3，需 >= 3.10）
  --bin-dir DIR    指定全局命令目录（默认 ~/.local/bin）
  -h, --help       显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --python)
            PYTHON_BIN="${2:?--python 需要参数}"
            shift 2
            ;;
        --bin-dir)
            BIN_DIR="${2:?--bin-dir 需要参数}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            usage
            exit 2
            ;;
    esac
done

err() { echo "错误: $*" >&2; exit 1; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 || err "未找到 $PYTHON_BIN，请先执行: sudo apt install -y python3 python3-venv"

if ! "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(1)
PY
then
    err "Python 版本过低（需要 >= 3.10），当前: $("$PYTHON_BIN" -V 2>&1)"
fi

if ! "$PYTHON_BIN" -c "import venv" >/dev/null 2>&1; then
    err "缺少 venv 模块，请先执行: sudo apt install -y python3-venv"
fi

mkdir -p "$DATA_DIR" "$BIN_DIR"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "[1/3] 创建虚拟环境: $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR" || err "创建虚拟环境失败，请确认已安装 python3-venv"
else
    echo "[1/3] 复用虚拟环境: $VENV_DIR"
fi

echo "[2/3] 安装依赖与 CLI（首次安装需要下载依赖）"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel -q
"$VENV_DIR/bin/python" -m pip install --upgrade "$SRC_DIR" -q

echo "[3/3] 注册全局命令"
chmod +x "$VENV_DIR/bin/$APP_NAME"
ln -sfn "$VENV_DIR/bin/$APP_NAME" "$BIN_DIR/$APP_NAME"

# ~/.local/bin 不在 PATH 时，尝试放到 /usr/local/bin（Kali 常配置免密 sudo）
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        if [[ -w /usr/local/bin ]]; then
            ln -sfn "$VENV_DIR/bin/$APP_NAME" "/usr/local/bin/$APP_NAME"
            BIN_DIR="/usr/local/bin"
        elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
            sudo ln -sfn "$VENV_DIR/bin/$APP_NAME" "/usr/local/bin/$APP_NAME"
            BIN_DIR="/usr/local/bin"
        else
            echo "提示: $BIN_DIR 不在 PATH 中，请将下面一行加入 ~/.bashrc 后重开终端:"
            echo "  export PATH=\"$BIN_DIR:\$PATH\""
        fi
        ;;
esac

hash -r 2>/dev/null || true

echo
echo "安装完成: $(command -v "$APP_NAME" 2>/dev/null || echo "$BIN_DIR/$APP_NAME")"
"$VENV_DIR/bin/$APP_NAME" --version
echo
echo "快速验证:"
echo "  $APP_NAME baidu.com"
echo "  $APP_NAME -f json baidu.com | jq -r '.results[0].records[0].unit_name'"
