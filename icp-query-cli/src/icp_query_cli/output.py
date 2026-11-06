# -*- coding: utf-8 -*-
"""结果归一化与多格式输出。"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

_FIELD_MAP = (
    ("domain", "domain"),
    ("domainName", "domain"),
    ("serviceName", "service_name"),
    ("unitName", "unit_name"),
    ("mainLicence", "main_licence"),
    ("serviceLicence", "service_licence"),
    ("natureName", "nature_name"),
    ("updateRecordTime", "update_time"),
    ("contentTypeName", "content_type"),
    ("limitAccess", "limit_access"),
    ("version", "version"),
    ("blackListLevel", "black_list_level"),
    ("mainUnitAddress", "unit_address"),
    ("mainId", "main_id"),
    ("serviceId", "service_id"),
    ("domainId", "domain_id"),
)

_LABELS = {
    "unit_name": "主体名称",
    "main_licence": "备案主体号",
    "service_licence": "备案服务号",
    "nature_name": "主体类型",
    "update_time": "审核时间",
    "domain": "域名",
    "service_name": "服务名称",
    "version": "服务版本",
    "content_type": "内容类型",
    "limit_access": "限制接入",
    "unit_address": "主体地址",
    "black_list_level": "威胁等级",
}

_DISPLAY_ORDER = (
    "unit_name",
    "main_licence",
    "service_licence",
    "nature_name",
    "update_time",
    "service_name",
    "domain",
    "version",
    "content_type",
    "limit_access",
    "unit_address",
    "black_list_level",
)


class Palette:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)


def use_color(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def normalize_record(item: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for source, target in _FIELD_MAP:
        if source not in item:
            continue
        value = item[source]
        if value is None:
            continue
        if target in ("main_id", "service_id", "domain_id"):
            record[target] = value
        else:
            record[target] = "" if value is None else str(value)
    return record


def summarize(payload: dict[str, Any] | None) -> tuple[list[dict], int, int]:
    """从工信部原始响应提取记录、总数、总页数。"""
    if not isinstance(payload, dict):
        return [], 0, 0
    params = payload.get("params")
    if isinstance(params, list):
        items = params
        total = len(items)
        pages = 1
    elif isinstance(params, dict) and "list" in params:
        items = params.get("list") or []
        total = params.get("total", len(items))
        pages = params.get("pages", 1)
    elif isinstance(params, dict) and any(
        key in params for key in ("domainName", "serviceName", "blackListLevel", "unitName")
    ):
        # 违法违规黑名单接口直接返回单条对象
        items = [params]
        total = 1
        pages = 1
    else:
        items, total, pages = [], 0, 0
    records = [normalize_record(item) for item in items if isinstance(item, dict)]
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(records)
    try:
        pages = int(pages)
    except (TypeError, ValueError):
        pages = 1 if records else 0
    return records, total, pages


def _brief_value(value: Any) -> str:
    return str(value if value is not None else "").replace("\t", " ").replace("\n", " ").strip()


def render_brief(results: list[dict]) -> str:
    lines = []
    for result in results:
        for record in result.get("records") or []:
            lines.append(
                "\t".join(
                    _brief_value(record.get(key))
                    for key in ("domain", "unit_name", "main_licence", "service_licence", "nature_name")
                )
            )
    return "\n".join(lines)


def render_text(results: list[dict], palette: Palette) -> str:
    blocks: list[str] = []
    for result in results:
        target = result["target"]
        header = palette.bold(f"▌ {target}") + palette.dim(f"  [{result['type']}]")
        if result.get("query") and result["query"] != target:
            header += palette.dim(f" -> {result['query']}")
        if result.get("note"):
            header += palette.dim(f"  ({result['note']})")

        if not result.get("ok"):
            blocks.append(
                f"{header}\n  {palette.red('✗ 查询失败')}: {result.get('message') or '未知错误'}"
            )
            continue

        count, total, pages = result["count"], result["total"], result["pages"]
        if count == 0:
            blocks.append(f"{header}\n  {palette.yellow('未查询到备案信息')}")
            continue

        meta = palette.dim(f"  共 {total} 条 / {pages} 页，本页 {count} 条")
        lines = [header, meta]
        for index, record in enumerate(result["records"], start=1):
            title = record.get("service_name") or record.get("domain") or f"记录 {index}"
            lines.append("")
            lines.append(f"  {palette.cyan(f'[{index}]')} {palette.bold(title)}")
            for key in _DISPLAY_ORDER:
                value = record.get(key)
                if value in (None, ""):
                    continue
                if key in ("domain", "service_name") and value == title:
                    continue
                if key == "black_list_level" and str(value) == "2":
                    value = "2（暂无违法违规信息）"
                lines.append(f"      {palette.dim(_LABELS[key] + ':')} {value}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_json_document(results: list[dict], qtype: str, page: int, size: int) -> dict:
    any_error = any(not result.get("ok") for result in results)
    found = any(result.get("count", 0) > 0 for result in results)
    return {
        "provider": "miit",
        "type": qtype,
        "page": page,
        "size": size,
        "ok": not any_error,
        "found": found,
        "results": [
            {
                "target": result["target"],
                "query": result.get("query"),
                "kind": result.get("kind"),
                "ok": result.get("ok"),
                "code": result.get("code"),
                "message": result.get("message"),
                "count": result.get("count", 0),
                "total": result.get("total", 0),
                "pages": result.get("pages", 0),
                "records": result.get("records") or [],
            }
            for result in results
        ],
    }


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def dump_jsonl(results: list[dict], qtype: str, page: int, size: int) -> str:
    document = build_json_document(results, qtype, page, size)
    lines = []
    for item in document["results"]:
        single = dict(document)
        single["results"] = [item]
        single["ok"] = bool(item.get("ok"))
        single["found"] = bool(item.get("count"))
        lines.append(json.dumps(single, ensure_ascii=False))
    return "\n".join(lines)


def render_raw(results: list[dict]) -> str:
    raws = [{"target": result["target"], "data": result.get("raw")} for result in results]
    if len(raws) == 1:
        return dump_json(raws[0]["data"])
    return dump_json(raws)
