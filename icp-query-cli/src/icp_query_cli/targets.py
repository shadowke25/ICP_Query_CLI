# -*- coding: utf-8 -*-
"""查询目标归一化：URL/域名/IP/单位名称/备案号 -> 可提交给工信部接口的关键词。"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

logger = logging.getLogger("icp-query")

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


@dataclass
class TargetInfo:
    original: str
    query: str
    kind: str  # domain | ip | keyword
    note: str = ""
    error: str = ""


def _extract_host(value: str) -> tuple[str, bool]:
    """返回 (host, 是否来自 URL)。"""
    text = value.strip()
    if "://" in text:
        try:
            host = urlsplit(text).hostname or ""
            return host, True
        except Exception:
            return "", True

    if text.startswith("["):  # [IPv6]:port
        end = text.find("]")
        if end > 0:
            return text[1:end], False

    # 去掉路径/查询串
    for sep in ("/", "?", "#"):
        if sep in text:
            text = text.split(sep, 1)[0]

    if text.count(":") == 1:  # host:port
        return text.split(":", 1)[0], False
    return text, False


def normalize_target(raw: str) -> TargetInfo:
    original = raw.strip()
    if not original:
        raise ValueError("查询目标不能为空")

    host, from_url = _extract_host(original)
    host = (host or "").strip().rstrip(".")
    if not host:
        return TargetInfo(original=original, query=original, kind="keyword")

    try:
        ip = ipaddress.ip_address(host)
        return TargetInfo(original=original, query=str(ip), kind="ip")
    except ValueError:
        pass

    ascii_host = host
    if any(ord(ch) > 127 for ch in host):
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except Exception:
            ascii_host = host

    if _DOMAIN_RE.match(ascii_host.lower()):
        return TargetInfo(
            original=original,
            query=ascii_host.lower(),
            kind="domain",
            note="URL 已归一化为域名" if from_url else "",
        )

    # 单位名称、备案号等关键词原样提交
    return TargetInfo(original=original, query=original, kind="keyword")


async def resolve_target(raw: str, ptr_timeout: float = 3.0) -> TargetInfo:
    """IP 目标尝试反查 PTR 得到域名；无 PTR 时返回明确的错误提示。"""
    info = normalize_target(raw)
    if info.kind != "ip":
        return info

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, socket.gethostbyaddr, info.query), timeout=ptr_timeout
        )
        hostname = (result[0] or "").strip().rstrip(".")
    except Exception:
        return TargetInfo(
            original=info.original,
            query=info.query,
            kind="ip",
            error="该 IP 无 PTR 记录，工信部接口不支持直接按 IP 查询 ICP 备案，请改传域名",
        )

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return TargetInfo(
            original=info.original,
            query=info.query,
            kind="ip",
            error="该 IP 的 PTR 记录指向其他 IP，无法用于备案查询，请改传域名",
        )

    ascii_host = hostname
    if any(ord(ch) > 127 for ch in hostname):
        try:
            ascii_host = hostname.encode("idna").decode("ascii")
        except Exception:
            ascii_host = hostname

    if not _DOMAIN_RE.match(ascii_host.lower()):
        return TargetInfo(
            original=info.original,
            query=info.query,
            kind="ip",
            error=f"PTR 记录 {hostname!r} 不是有效域名，请改传域名",
        )

    logger.debug("IP %s 反查到域名 %s", info.query, ascii_host)
    return TargetInfo(
        original=info.original,
        query=ascii_host.lower(),
        kind="domain",
        note=f"IP 反查: {info.query} -> {ascii_host.lower()}",
    )
