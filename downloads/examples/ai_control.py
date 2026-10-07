#!/usr/bin/env python3
"""无界面控制 data_interface 的标准库示例。

凭据通过环境变量提供：
  DI_PHONE、DI_PASSWORD、DI_CARD_KEY

示例：
  python ai_control.py status
  python ai_control.py login
  python ai_control.py web-off
  python ai_control.py recharge
  python ai_control.py start --port 8080
  python ai_control.py smoke
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_ADMIN_BASE = "http://127.0.0.1:9527"


def admin_base() -> str:
    return os.environ.get("DI_ADMIN_BASE", DEFAULT_ADMIN_BASE).rstrip("/")


def request_json(method: str, path: str, form: dict[str, str] | None = None) -> tuple[int, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if form is not None:
        body = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    req = Request(admin_base() + path, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as response:
            status = response.status
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"请求失败: {exc}", file=sys.stderr)
        raise SystemExit(10) from exc

    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw}


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"缺少环境变量 {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


def command_status(_: argparse.Namespace) -> int:
    status, body = request_json("GET", "/api/status")
    print_json(body)
    return 0 if status < 500 else 1


def command_login(_: argparse.Namespace) -> int:
    status, body = request_json(
        "POST",
        "/api/login",
        {"phone": required_env("DI_PHONE"), "password": required_env("DI_PASSWORD")},
    )
    print_json(body)
    if isinstance(body, dict) and (body.get("ok") is True or body.get("needRecharge") is True):
        return 0
    return 1 if status >= 400 else 1


def command_recharge(_: argparse.Namespace) -> int:
    status, body = request_json(
        "POST", "/api/recharge", {"cardKey": required_env("DI_CARD_KEY")}
    )
    print_json(body)
    return 0 if isinstance(body, dict) and body.get("ok") is True else 1


def command_start(args: argparse.Namespace) -> int:
    status, body = request_json("POST", "/api/server/start", {"port": str(args.port)})
    print_json(body)
    return 0 if isinstance(body, dict) and body.get("ok") is True else 1


def command_simple(path: str):
    def run(_: argparse.Namespace) -> int:
        status, body = request_json("POST", path)
        print_json(body)
        return 0 if status < 400 and not (isinstance(body, dict) and body.get("ok") is False) else 1

    return run


def command_smoke(args: argparse.Namespace) -> int:
    status, state = request_json("GET", "/api/status")
    print("[管理端状态]")
    print_json(state)
    if status >= 400 or not isinstance(state, dict):
        return 1
    if not state.get("running"):
        print("数据服务尚未运行，请先执行 start", file=sys.stderr)
        return 1

    port = int(state.get("proxyPort") or args.port)
    url = f"http://127.0.0.1:{port}/d1/article"
    form = urlencode({
        "a": "GetListByID",
        "c": "PCNewsFlash",
        "LastID": "0",
        "st": "1",
        "Type": "0",
    }).encode("utf-8")
    req = Request(
        url,
        data=form,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
            probe_status = response.status
    except HTTPError as exc:
        probe_status = exc.code
        raw = exc.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"数据端自测失败: {exc}", file=sys.stderr)
        return 1

    print(f"[D1 数据端 {probe_status}]")
    print(raw)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return 1
    return 0 if probe_status < 400 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通过本机管理 API 控制 data_interface")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="读取管理端状态").set_defaults(func=command_status)
    sub.add_parser("login", help="登录；新手机号会自动注册").set_defaults(func=command_login)
    sub.add_parser("recharge", help="使用 DI_CARD_KEY 充值").set_defaults(func=command_recharge)

    start = sub.add_parser("start", help="启动数据服务")
    start.add_argument("--port", type=int, default=8080)
    start.set_defaults(func=command_start)

    smoke = sub.add_parser("smoke", help="检查管理端和 D1 数据端")
    smoke.add_argument("--port", type=int, default=8080)
    smoke.set_defaults(func=command_smoke)

    sub.add_parser("stop", help="停止数据服务").set_defaults(func=command_simple("/api/server/stop"))
    sub.add_parser("logout", help="登出并停止数据服务").set_defaults(func=command_simple("/api/logout"))
    sub.add_parser("web-off", help="关闭启动后自动开页").set_defaults(func=command_simple("/api/open-web/off"))
    sub.add_parser("exit", help="退出整个客户端").set_defaults(func=command_simple("/api/exit"))
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))
