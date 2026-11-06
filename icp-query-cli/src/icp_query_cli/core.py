# -*- coding: utf-8 -*-
"""工信部 ICP 备案查询核心（重构自 ICP_Query v0.7.6 的 ymicp.py）。

保留原有鉴权、创宇盾拦截处理、滑块验证码识别、分页查询与 APP 详情并发逻辑；
移除了 Web 服务、代理池、IPv6 轮询等 CLI 场景不需要的模块。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
from aiohttp import TCPConnector

try:  # 兼容无法安装 ujson 的环境
    import ujson as json
except ImportError:  # pragma: no cover
    import json

try:
    from aiohttp_socks import ProxyConnector
except ImportError:  # pragma: no cover
    ProxyConnector = None

from .captcha import find_slider_offset
from .config import Settings

logger = logging.getLogger("icp-query")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32"
)

AUTH_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth"
CHECK_IMAGE_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/getCheckImagePoint"
VERIFY_IMAGE_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/checkImage"
QUERY_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition"
BLACK_QUERY_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition"
BLACK_APP_QUERY_URL = (
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition_appAndMini"
)
DETAIL_URL = (
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryDetailByAppAndMiniId"
)

# 上游内置 fallback sign；仅在关闭验证码时使用，可能随官方更新失效
FALLBACK_SIGN = (
    "eyJ0eXBlIjozLCJleHREYXRhIjp7InZhZnljb2RlX2ltYWdlX2tleSI6IjUyZWI1ZTcyODViNzRmNWJhM2YwYzBkNTg0YTg3NmVmIn0s"
    "ImUiOjE3NTY5NzAyNDg4MjN9.Ngpkwn4T7sQoQF9pCk_sQQpH61wQUEKnK2sQ8hDIq-Q"
)

def _dumps(obj: Any) -> str:
    """与上游 ujson 一致的紧凑 JSON，避免请求体格式差异影响签名校验。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


BLOCK_MARK = "当前访问疑似黑客攻击"
BLOCK_MESSAGE = "当前访问已被创宇盾拦截"

TYPE_SERVICE = {"web": 1, "app": 6, "mapp": 7, "kapp": 8}
BLACK_SERVICE = {"bapp": 6, "bmapp": 7, "bkapp": 8}
NORMAL_TYPES = tuple(TYPE_SERVICE)
BLACK_TYPES = ("bweb", "bapp", "bmapp", "bkapp")
QUERY_TYPES = NORMAL_TYPES + BLACK_TYPES


class IcpClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.timeout = aiohttp.ClientTimeout(total=settings.timeout)
        self.connector_config: dict[str, Any] = {
            "limit": 30,
            "limit_per_host": 10,
            "ttl_dns_cache": 300,
            "use_dns_cache": True,
            "ssl": False,
            "keepalive_timeout": 15,
            "enable_cleanup_closed": True,
        }
        self._token_lock = asyncio.Lock()
        self.token = ""
        self.token_expire = 0
        self.cookie = ""
        self._load_token_cache()

    # ---------- token 缓存 ----------
    def _load_token_cache(self) -> None:
        if not self.settings.cache:
            return
        path = self.settings.token_file
        try:
            if not path.is_file():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("expire", 0)) > int(time.time() * 1000) + 5000:
                self.token = str(data.get("token") or "")
                self.token_expire = int(data.get("expire") or 0)
                self.cookie = str(data.get("cookie") or "")
                if self.token:
                    logger.debug("复用已缓存的 token")
        except Exception as exc:
            logger.debug("读取 token 缓存失败: %s", exc)

    def _save_token_cache(self) -> None:
        if not self.settings.cache or not self.token:
            return
        path = self.settings.token_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(
                json.dumps(
                    {"token": self.token, "expire": self.token_expire, "cookie": self.cookie}
                ),
                encoding="utf-8",
            )
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except Exception as exc:
            logger.debug("写入 token 缓存失败: %s", exc)

    def _clear_token(self) -> None:
        self.token = ""
        self.token_expire = 0
        self.cookie = ""
        try:
            if self.settings.cache:
                self.settings.token_file.unlink(missing_ok=True)
        except Exception:
            pass

    # ---------- HTTP ----------
    def _base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": UA,
            "Origin": "https://beian.miit.gov.cn",
            "Referer": "https://beian.miit.gov.cn/",
            "Cookie": self.cookie or f"__jsluid_s={uuid.uuid4().hex}",
            "Accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def _is_socks(proxy: str | None) -> bool:
        return bool(proxy) and proxy.lower().startswith(("socks4", "socks5", "socks://"))

    def _proxy_kw(self, proxy: str | None) -> dict[str, str]:
        if proxy and not self._is_socks(proxy):
            return {"proxy": proxy}
        return {}

    @asynccontextmanager
    async def _session(self, proxy: str | None = None):
        if self._is_socks(proxy):
            if ProxyConnector is None:
                raise RuntimeError("使用 SOCKS 代理需要安装 aiohttp-socks")
            connector = ProxyConnector.from_url(proxy, ssl=False)
        else:
            connector = TCPConnector(**self.connector_config)

        session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
            headers={"Connection": "keep-alive"},
            trust_env=False,
        )
        try:
            yield session
        finally:
            try:
                await session.close()
            except Exception:
                pass

    # ---------- 鉴权 ----------
    async def get_token(self, session: aiohttp.ClientSession, proxy: str | None = None) -> tuple[bool, str, dict]:
        async with self._token_lock:
            now = int(time.time() * 1000)
            if self.token and self.token_expire > now + 5000:
                return True, self.token, self._base_headers()

            if self.settings.cache:
                self._load_token_cache()
                if self.token and self.token_expire > now + 5000:
                    return True, self.token, self._base_headers()

            timestamp = round(time.time() * 1000)
            auth_key = hashlib.md5(("testtest" + str(timestamp)).encode("utf-8")).hexdigest()
            headers = self._base_headers()
            try:
                async with session.post(
                    AUTH_URL,
                    data={"authKey": auth_key, "timeStamp": timestamp},
                    headers=headers,
                    **self._proxy_kw(proxy),
                ) as resp:
                    text = await resp.text()
                    if BLOCK_MARK in text:
                        return False, BLOCK_MESSAGE, ""
                    payload = json.loads(text)
                    token = payload["params"]["bussiness"]
                    expire = int(time.time() * 1000) + int(payload["params"]["expire"])
                    self.token = token
                    self.token_expire = expire
                    self.cookie = headers["Cookie"]
                    self._save_token_cache()
                    return True, token, headers
            except Exception as exc:
                return False, f"鉴权失败: {exc}", ""

    @staticmethod
    def _client_uid() -> str:
        characters = "0123456789abcdef"
        unique_id = [random.choice(characters) for _ in range(36)]
        unique_id[14] = "4"
        unique_id[19] = characters[(3 & int(unique_id[19], 16)) | 8]
        unique_id[8] = unique_id[13] = unique_id[18] = unique_id[23] = "-"
        return _dumps({"clientUid": "point-" + "".join(unique_id)})

    async def check_image(
        self, session: aiohttp.ClientSession, proxy: str | None = None
    ) -> tuple[bool, str, str, str, dict]:
        success, token, headers = await self.get_token(session, proxy)
        if not success:
            return False, token, "", "", {}

        try:
            uid_data = self._client_uid()
            headers.update(
                {
                    "Content-Length": str(len(uid_data.encode("utf-8"))),
                    "token": token,
                    "Content-Type": "application/json",
                }
            )
            async with session.post(
                CHECK_IMAGE_URL, data=uid_data, headers=headers, **self._proxy_kw(proxy)
            ) as resp:
                payload = await resp.json(content_type=None)

            point_uuid = payload["params"]["uuid"]
            big_image = payload["params"]["bigImage"]
            small_image = payload["params"]["smallImage"]

            matched, offset = find_slider_offset(small_image, big_image)
            if not matched:
                return False, f"滑块匹配失败: {offset}", "", "", {}

            check_data = _dumps({"key": point_uuid, "value": str(offset)})
            headers["Content-Length"] = str(len(check_data.encode("utf-8")))
            async with session.post(
                VERIFY_IMAGE_URL, data=check_data, headers=headers, **self._proxy_kw(proxy)
            ) as resp:
                verify_payload = json.loads(await resp.text())

            logger.debug("checkImage success=%s msg=%s", verify_payload.get("success"), verify_payload.get("msg"))
            if not verify_payload.get("success", False):
                return False, "验证码识别失败", "", "", {}
            return True, point_uuid, token, verify_payload["params"], headers
        except Exception as exc:
            return False, f"验证码请求失败: {exc}", "", "", {}

    # ---------- 查询 ----------
    @staticmethod
    def _normal_payload(qtype: str, target: str, page: int, size: int) -> dict:
        return {
            "pageNum": page,
            "pageSize": size,
            "unitName": target,
            "serviceType": TYPE_SERVICE[qtype],
        }

    @staticmethod
    def _black_payload(qtype: str, target: str) -> dict | None:
        if qtype == "bweb":
            return {"domainName": target}
        return {"serviceName": target, "serviceType": BLACK_SERVICE[qtype]}

    async def _query_normal(
        self, session: aiohttp.ClientSession, qtype: str, target: str, page: int, size: int, proxy: str | None
    ) -> tuple[str, Any, dict]:
        payload = self._normal_payload(qtype, target, page, size)
        ctx: dict[str, Any] = {"captcha": self.settings.captcha, "token": "", "uuid": "", "sign": "", "headers": {}}

        if self.settings.captcha:
            success, point_uuid, token, sign, headers = await self.check_image(session, proxy)
            if not success:
                return "error", {"code": "CAPTCHA_FAILED", "message": point_uuid}, ctx
            body = _dumps(payload)
            headers.update(
                {
                    "Content-Length": str(len(body.encode("utf-8"))),
                    "uuid": point_uuid,
                    "token": token,
                    "sign": sign,
                }
            )
            ctx.update(token=token, uuid=point_uuid, sign=sign, headers=headers)
            async with session.post(
                QUERY_URL, data=body, headers=headers, **self._proxy_kw(proxy)
            ) as resp:
                text = await resp.text()
        else:
            success, token, headers = await self.get_token(session, proxy)
            if not success:
                return "error", {"code": "AUTH_FAILED", "message": token}, ctx
            headers.update({"token": token, "sign": FALLBACK_SIGN})
            ctx.update(token=token, sign=FALLBACK_SIGN, headers=headers)
            async with session.post(
                f"{QUERY_URL}/", json=payload, headers=headers, **self._proxy_kw(proxy)
            ) as resp:
                text = await resp.text()

        if BLOCK_MARK in text:
            logger.debug("查询接口返回拦截页: %s", text[:200])
            return "blocked", BLOCK_MESSAGE, ctx
        logger.debug("查询接口响应: %s", text[:200])
        state, payload = self._parse(text)
        return state, payload, ctx

    async def _query_black(
        self, session: aiohttp.ClientSession, qtype: str, target: str, proxy: str | None
    ) -> tuple[str, Any, dict]:
        payload = self._black_payload(qtype, target)
        ctx: dict[str, Any] = {"captcha": self.settings.captcha, "token": "", "uuid": "", "sign": "", "headers": {}}
        url = BLACK_QUERY_URL if qtype == "bweb" else BLACK_APP_QUERY_URL

        if self.settings.captcha:
            success, point_uuid, token, sign, headers = await self.check_image(session, proxy)
            if not success:
                return "error", {"code": "CAPTCHA_FAILED", "message": point_uuid}, ctx
            body = _dumps(payload)
            headers.update(
                {
                    "Content-Length": str(len(body.encode("utf-8"))),
                    "uuid": point_uuid,
                    "token": token,
                    "sign": sign,
                }
            )
            ctx.update(token=token, uuid=point_uuid, sign=sign, headers=headers)
            async with session.post(url, data=body, headers=headers, **self._proxy_kw(proxy)) as resp:
                text = await resp.text()
        else:
            success, token, headers = await self.get_token(session, proxy)
            if not success:
                return "error", {"code": "AUTH_FAILED", "message": token}, ctx
            headers.update({"token": token, "sign": FALLBACK_SIGN})
            ctx.update(token=token, sign=FALLBACK_SIGN, headers=headers)
            async with session.post(
                f"{url}/", json=payload, headers=headers, **self._proxy_kw(proxy)
            ) as resp:
                text = await resp.text()

        if BLOCK_MARK in text:
            return "blocked", BLOCK_MESSAGE, ctx
        state, payload = self._parse(text)
        return state, payload, ctx

    @staticmethod
    def _parse(text: str) -> tuple[str, Any]:
        try:
            payload = json.loads(text)
        except Exception:
            return "error", {"code": "BAD_RESPONSE", "message": f"接口返回非 JSON: {text[:120]}"}
        if isinstance(payload, dict) and (payload.get("success") is True or payload.get("code") == 200):
            return "ok", payload
        return "error", payload

    def _error_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("msg") or payload.get("code") or "查询失败")
        return str(payload)

    async def _fetch_details(
        self,
        session: aiohttp.ClientSession,
        payload: dict,
        qtype: str,
        ctx: dict,
        proxy: str | None,
    ) -> dict:
        params = payload.get("params") or {}
        items = params.get("list") if isinstance(params, dict) else None
        if not items:
            return payload

        service_type = TYPE_SERVICE[qtype]
        semaphore = asyncio.Semaphore(self.settings.detail_concurrency)
        headers = dict(ctx.get("headers") or {})
        if ctx.get("captcha"):
            headers.pop("Content-Length", None)

        async def fetch(item: dict) -> dict:
            if "dataId" not in item:
                return item
            info = {"dataId": item["dataId"], "serviceType": service_type}
            body = _dumps(info)
            req_headers = dict(headers)
            if ctx.get("captcha"):
                req_headers.update(
                    {
                        "Content-Length": str(len(body.encode("utf-8"))),
                        "uuid": ctx.get("uuid", ""),
                        "token": ctx.get("token", ""),
                        "sign": ctx.get("sign", ""),
                    }
                )
            else:
                req_headers["sign"] = FALLBACK_SIGN
            try:
                async with semaphore:
                    if ctx.get("captcha"):
                        async with session.post(
                            DETAIL_URL, data=body, headers=req_headers, **self._proxy_kw(proxy)
                        ) as resp:
                            detail = json.loads(await resp.text())
                    else:
                        async with session.post(
                            DETAIL_URL, json=info, headers=req_headers, **self._proxy_kw(proxy)
                        ) as resp:
                            detail = json.loads(await resp.text())
                if detail.get("success"):
                    return detail.get("params", item)
            except Exception as exc:
                logger.debug("获取详情失败 dataId=%s: %s", item.get("dataId"), exc)
            return item

        detailed = await asyncio.gather(*(fetch(item) for item in items))
        params["list"] = list(detailed)
        payload["params"] = params
        return payload

    # ---------- 对外接口 ----------
    async def query(
        self,
        target: str,
        qtype: str = "web",
        page: int = 1,
        size: int = 10,
        proxy: str | None = None,
    ) -> dict:
        """返回 {"ok": bool, "data": raw, "attempts": int} 或 {"ok": False, "code": ..., "message": ...}"""
        retries = max(1, self.settings.retries)
        last_message = "查询失败"
        last_code = "QUERY_FAILED"

        for attempt in range(1, retries + 1):
            try:
                async with self._session(proxy) as session:
                    if qtype in BLACK_TYPES:
                        state, payload, ctx = await self._query_black(session, qtype, target, proxy)
                    else:
                        state, payload, ctx = await self._query_normal(
                            session, qtype, target, page, size, proxy
                        )

                    if state == "ok" and qtype in ("app", "mapp", "kapp"):
                        payload = await self._fetch_details(session, payload, qtype, ctx, proxy)
            except asyncio.TimeoutError:
                state, payload, ctx = "error", {"message": f"请求超时（{self.settings.timeout:g}s）"}, {}
            except aiohttp.ClientError as exc:
                state, payload, ctx = "error", {"message": f"网络请求失败: {exc}"}, {}
            except Exception as exc:
                state, payload, ctx = "error", {"message": f"查询异常: {exc}"}, {}

            if state == "blocked":
                return {"ok": False, "code": "BLOCKED", "message": BLOCK_MESSAGE, "attempts": attempt}
            if state == "ok":
                return {"ok": True, "data": payload, "attempts": attempt}

            last_code = str(payload.get("code") or "QUERY_FAILED") if isinstance(payload, dict) else "QUERY_FAILED"
            last_message = self._error_message(payload)
            logger.debug("第 %s/%s 次尝试失败: %s", attempt, retries, last_message)

            if attempt < retries:
                # 失败后丢弃 token，下一轮重新鉴权，避免 token/sign 失效导致连续失败
                self._clear_token()
                await asyncio.sleep(0.4 * attempt + random.uniform(0, 0.3))

        return {
            "ok": False,
            "code": last_code,
            "message": last_message,
            "attempts": retries,
        }
