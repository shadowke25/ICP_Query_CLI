# -*- coding: utf-8 -*-
"""配置加载：内置默认值 -> 用户配置 -> 环境变量 -> 命令行覆盖。"""
from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_PATH = Path(__file__).with_name("config.default.yml")

_DEFAULTS: dict[str, Any] = {
    "network": {"timeout": 15, "retries": 3, "proxy": None},
    "captcha": {"enable": True, "detail_concurrency": 3},
    "cache": {"enable": True, "dir": None},
    "output": {"color": "auto"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _default_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg) if xdg else Path.home() / ".cache"
    return root / "icp-query"


@dataclass
class Settings:
    timeout: float = 15.0
    retries: int = 3
    proxy: str | None = None
    captcha: bool = True
    detail_concurrency: int = 3
    cache: bool = True
    cache_dir: Path = field(default_factory=_default_cache_dir)
    color: str = "auto"

    @property
    def token_file(self) -> Path:
        return self.cache_dir / "token.json"


def _user_config_path() -> Path | None:
    env = os.environ.get("ICP_QUERY_CONFIG")
    if env:
        return Path(env).expanduser()
    path = Path.home() / ".config" / "icp-query" / "config.yml"
    return path if path.is_file() else None


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def load_settings(verbose: bool = False) -> Settings:
    data = copy.deepcopy(_DEFAULTS)
    try:
        if _DEFAULT_PATH.is_file():
            with _DEFAULT_PATH.open("r", encoding="utf-8") as fh:
                data = _deep_merge(data, yaml.safe_load(fh) or {})
    except Exception as exc:  # 默认配置损坏不应阻断使用
        if verbose:
            print(f"[icp-query] 读取默认配置失败: {exc}", file=sys.stderr)

    user_path = _user_config_path()
    if user_path:
        try:
            with user_path.open("r", encoding="utf-8") as fh:
                data = _deep_merge(data, yaml.safe_load(fh) or {})
        except Exception as exc:
            print(f"[icp-query] 用户配置无效，已忽略 {user_path}: {exc}", file=sys.stderr)

    network = data.get("network") or {}
    captcha = data.get("captcha") or {}
    cache = data.get("cache") or {}
    output = data.get("output") or {}

    timeout = float(os.environ.get("ICP_QUERY_TIMEOUT") or network.get("timeout") or 15)
    retries = int(network.get("retries") or 3)
    proxy = os.environ.get("ICP_QUERY_PROXY") or network.get("proxy")
    captcha_enabled = _as_bool(
        os.environ.get("ICP_QUERY_CAPTCHA", captcha.get("enable", True)), True
    )
    cache_enabled = _as_bool(
        os.environ.get("ICP_QUERY_CACHE", cache.get("enable", True)), True
    )
    cache_dir = os.environ.get("ICP_QUERY_CACHE_DIR") or cache.get("dir")
    cache_dir_path = Path(cache_dir).expanduser() if cache_dir else _default_cache_dir()

    return Settings(
        timeout=max(3.0, timeout),
        retries=max(1, retries),
        proxy=proxy or None,
        captcha=captcha_enabled,
        detail_concurrency=max(1, int(captcha.get("detail_concurrency") or 3)),
        cache=cache_enabled,
        cache_dir=cache_dir_path,
        color=str(output.get("color") or "auto"),
    )
