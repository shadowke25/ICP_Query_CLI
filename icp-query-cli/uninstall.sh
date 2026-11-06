#!/usr/bin/env bash
# ICP_Query CLI - 卸载脚本
set -euo pipefail

APP_NAME="icp-query"
DATA_DIR="${ICP_QUERY_HOME:-$HOME/.local/share/icp-query}"
BIN_DIR="${ICP_QUERY_BIN_DIR:-$HOME/.local/bin}"

remove_link() {
    local link="$1"
    [[ -L "$link" ]] || return 0
    local target
    target="$(readlink "$link" || true)"
    [[ "$target" == "$DATA_DIR/venv/bin/$APP_NAME" ]] || return 0

    if rm -f "$link" 2>/dev/null; then
        echo "已删除: $link"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        sudo rm -f "$link" && echo "已删除: $link"
    else
        echo "无权限删除 $link，请手动执行: sudo rm -f $link"
    fi
}

remove_link "$BIN_DIR/$APP_NAME"
remove_link "/usr/local/bin/$APP_NAME"

if [[ -d "$DATA_DIR" ]]; then
    rm -rf "$DATA_DIR"
    echo "已删除: $DATA_DIR"
fi

CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/icp-query"
if [[ -d "$CACHE_DIR" ]]; then
    rm -rf "$CACHE_DIR"
    echo "已删除: $CACHE_DIR"
fi

echo "卸载完成。用户配置保留在 ~/.config/icp-query/（如存在，可手动删除）。"
