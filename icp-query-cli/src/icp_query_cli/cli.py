# -*- coding: utf-8 -*-
"""命令行入口。"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Sequence

from . import __version__
from .config import Settings, load_settings
from .core import IcpClient, QUERY_TYPES
from .output import (
    Palette,
    build_json_document,
    dump_json,
    dump_jsonl,
    render_brief,
    render_raw,
    render_text,
    summarize,
    use_color,
)
from .targets import resolve_target

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_RESULT = 2
EXIT_USAGE = 64

_TYPE_HELP = {
    "web": "网站备案",
    "app": "APP 备案",
    "mapp": "小程序备案",
    "kapp": "快应用备案",
    "bweb": "违法违规网站",
    "bapp": "违法违规 APP",
    "bmapp": "违法违规小程序",
    "bkapp": "违法违规快应用",
}

_EPILOG = """\
查询类型:
  web    网站备案（域名 / 单位名称 / 备案号）
  app    APP 备案
  mapp   小程序备案
  kapp   快应用备案
  bweb / bapp / bmapp / bkapp  违法违规黑名单查询

示例:
  icp-query baidu.com
  icp-query -f json baidu.com
  icp-query -t web -p 2 -s 20 深圳市腾讯计算机系统有限公司
  icp-query -f brief www.example.com 1.2.3.4
  cat domains.txt | icp-query -f jsonl -

提示:
  IP 目标会先做 PTR 反查；无 PTR 记录时无法直接查询 ICP 备案，请改用域名。
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: 参数错误: {message}\n")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


def _page_size(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 26:
        raise argparse.ArgumentTypeError("每页条数范围为 1-26（工信部接口限制）")
    return number


def _jobs(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 8:
        raise argparse.ArgumentTypeError("并发数范围为 1-8")
    return number


def _retry(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 10:
        raise argparse.ArgumentTypeError("重试次数范围为 1-10")
    return number


def _timeout(value: str) -> float:
    number = float(value)
    if not 3 <= number <= 120:
        raise argparse.ArgumentTypeError("超时范围为 3-120 秒")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="icp-query",
        description="工信部 ICP 备案查询 CLI（面向渗透测试信息收集）",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("targets", nargs="*", metavar="TARGET", help="域名 / URL / IP / 单位名称 / 备案号，可用 - 从管道读取")
    parser.add_argument("-t", "--type", choices=QUERY_TYPES, default="web", help="查询类型，默认 web")
    parser.add_argument("-p", "--page", type=_positive_int, default=1, help="页码，从 1 开始（默认 1）")
    parser.add_argument("-s", "--size", type=_page_size, default=10, help="每页条数 1-26（默认 10）")
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "brief", "json", "jsonl", "raw"),
        default="text",
        help="输出格式，默认 text",
    )
    parser.add_argument("-j", "--jobs", type=_jobs, default=1, help="批量查询并发数 1-8（默认 1，稳妥防拦截）")
    parser.add_argument("--timeout", type=_timeout, default=None, help="单次请求超时秒数（默认 15）")
    parser.add_argument("--retry", type=_retry, default=None, help="单目标最大尝试次数（默认 3）")
    parser.add_argument("--proxy", default=None, help="HTTP/SOCKS5 代理，如 http://127.0.0.1:8080 或 socks5://127.0.0.1:1080")
    parser.add_argument("--no-captcha", action="store_true", help="关闭滑块识别（使用内置 sign，可能失效）")
    parser.add_argument("--no-cache", action="store_true", help="不缓存 token")
    parser.add_argument("--color", choices=("auto", "always", "never"), default=None, help="彩色输出，默认 auto")
    parser.add_argument("-q", "--quiet", action="store_true", help="静默模式，仅输出结果")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="输出调试日志（-v 信息，-vv 调试）")
    parser.add_argument("--list-types", action="store_true", help="列出支持的查询类型并退出")
    parser.add_argument("--version", action="version", version=f"icp-query {__version__}")
    return parser


def _setup_logging(args: argparse.Namespace) -> None:
    if args.quiet:
        level = logging.CRITICAL
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s %(message)s",
        force=True,
    )


def _apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    if args.timeout is not None:
        settings.timeout = args.timeout
    if args.retry is not None:
        settings.retries = args.retry
    if args.proxy:
        settings.proxy = args.proxy
    if args.no_captcha:
        settings.captcha = False
    if args.no_cache:
        settings.cache = False
    if args.color:
        settings.color = args.color
    return settings


def _expand_targets(raw_targets: Sequence[str]) -> list[str]:
    expanded: list[str] = []
    for raw in raw_targets:
        if raw == "-":
            if sys.stdin.isatty():
                raise ValueError("使用 - 时需要从管道传入目标列表")
            for line in sys.stdin:
                line = line.strip()
                if line and not line.startswith("#"):
                    expanded.append(line)
        else:
            expanded.append(raw)

    seen: set[str] = set()
    unique: list[str] = []
    for item in expanded:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _error_result(raw: str, message: str, code: str, qtype: str, page: int, size: int, note: str = "") -> dict:
    return {
        "target": raw,
        "query": raw,
        "kind": "unknown",
        "note": note,
        "type": qtype,
        "page": page,
        "size": size,
        "ok": False,
        "code": code,
        "message": message,
        "count": 0,
        "total": 0,
        "pages": 0,
        "records": [],
        "raw": None,
    }


async def _execute(targets: list[str], args: argparse.Namespace, settings: Settings) -> list[dict]:
    client = IcpClient(settings)
    semaphore = asyncio.Semaphore(args.jobs)

    async def run_one(raw: str) -> dict:
        async with semaphore:
            try:
                info = await resolve_target(raw)
            except ValueError as exc:
                return _error_result(raw, str(exc), "INVALID_TARGET", args.type, args.page, args.size)
            except Exception as exc:
                return _error_result(raw, f"目标解析失败: {exc}", "INVALID_TARGET", args.type, args.page, args.size)

            if info.error:
                result = _error_result(
                    raw, info.error, "INVALID_TARGET", args.type, args.page, args.size, note=info.note
                )
                result["query"] = info.query
                result["kind"] = info.kind
                return result

            query_result = await client.query(
                info.query,
                qtype=args.type,
                page=args.page,
                size=args.size,
                proxy=settings.proxy,
            )

            if query_result.get("ok"):
                records, total, pages = summarize(query_result.get("data"))
                return {
                    "target": raw,
                    "query": info.query,
                    "kind": info.kind,
                    "note": info.note,
                    "type": args.type,
                    "page": args.page,
                    "size": args.size,
                    "ok": True,
                    "code": "OK",
                    "message": None,
                    "count": len(records),
                    "total": total,
                    "pages": pages,
                    "records": records,
                    "raw": query_result.get("data"),
                }

            return {
                "target": raw,
                "query": info.query,
                "kind": info.kind,
                "note": info.note,
                "type": args.type,
                "page": args.page,
                "size": args.size,
                "ok": False,
                "code": query_result.get("code", "QUERY_FAILED"),
                "message": query_result.get("message", "查询失败"),
                "count": 0,
                "total": 0,
                "pages": 0,
                "records": [],
                "raw": None,
            }

    if args.jobs == 1:
        return [await run_one(target) for target in targets]
    return list(await asyncio.gather(*(run_one(target) for target in targets)))


def _emit(results: list[dict], args: argparse.Namespace, settings: Settings) -> None:
    if args.format == "json":
        print(dump_json(build_json_document(results, args.type, args.page, args.size)))
    elif args.format == "jsonl":
        print(dump_jsonl(results, args.type, args.page, args.size))
    elif args.format == "raw":
        print(render_raw(results))
    elif args.format == "brief":
        text = render_brief(results)
        if text:
            print(text)
        for result in results:
            if not result.get("ok"):
                print(f"{result['target']}\tERROR\t{result.get('message')}", file=sys.stderr)
    else:
        print(render_text(results, Palette(use_color(settings.color))))

    if args.type in ("bweb", "bapp", "bmapp", "bkapp") and (args.page != 1 or args.size != 10):
        logging.getLogger("icp-query").warning("黑名单类型不支持分页，--page/--size 已忽略")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_types:
        for key, desc in _TYPE_HELP.items():
            print(f"{key:<6} {desc}")
        return EXIT_OK

    if not args.targets:
        parser.print_help()
        return EXIT_USAGE

    _setup_logging(args)
    settings = _apply_overrides(load_settings(verbose=args.verbose >= 2), args)

    try:
        targets = _expand_targets(args.targets)
    except ValueError as exc:
        print(f"icp-query: 参数错误: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if not targets:
        print("icp-query: 未读取到任何查询目标", file=sys.stderr)
        return EXIT_USAGE

    if not settings.captcha:
        logging.getLogger("icp-query").warning("已关闭验证码识别，内置 sign 可能过期导致查询失败")

    try:
        results = asyncio.run(_execute(targets, args, settings))
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"icp-query: 运行失败: {exc}", file=sys.stderr)
        return EXIT_ERROR

    _emit(results, args, settings)

    if any(not result.get("ok") for result in results):
        return EXIT_ERROR
    if all(result.get("count", 0) == 0 for result in results):
        return EXIT_NO_RESULT
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
