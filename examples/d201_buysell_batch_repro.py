"""D201 83 只股票买卖盘口示例（每只股票使用一个 WebSocket 连接）。

示例内容：
    - 为 83 只股票分别建立 WebSocket 连接；
    - 每个连接订阅一只股票的十档买盘和十档卖盘；
    - 遍历每个 JSON 消息中的完整 ``list`` 数组；
    - 使用 ``latest_by_code`` 保存每只股票的最新盘口数据。

运行前提：
    1. 本地数据接口程序已经启动、登录，并且 D201 服务可用；
    2. 安装依赖：python -m pip install websocket-client。

运行：
    python d201_buysell_batch_repro.py
    python d201_buysell_batch_repro.py --seconds 15

脚本不会保存行情原文，只会在本 examples 目录生成一个统计汇总 JSON，
便于确认连接数量、股票覆盖率和每只股票的消息数量。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

try:
    import websocket
except ImportError:
    print(
        "缺少 websocket-client，请先执行: python -m pip install websocket-client",
        file=sys.stderr,
    )
    raise


URL = "ws://127.0.0.1:8080/d201"

# 与示例需求对应的 83 只股票代码。
CODES = [
    "SH511180", "SH110075", "SH110076", "SH110077", "SH110084", "SH110085",
    "SH110086", "SH110087", "SH110090", "SH110093", "SH110097", "SH110098",
    "SH110099", "SH110100", "SH110101", "SH111002", "SH111009", "SH111014",
    "SH111017", "SH111025", "SH113039", "SH113042", "SH113043", "SH113046",
    "SH113048", "SH113049", "SH113051", "SH113052", "SH113053", "SH113054",
    "SH113056", "SH113058", "SH113059", "SH113062", "SH113066", "SH113067",
    "SH113070", "SH113605", "SH113615", "SH113616", "SH113627", "SH113631",
    "SH113633", "SH113634", "SH113638", "SH113647", "SH113652", "SH113655",
    "SH113659", "SH113661", "SH113666", "SH113670", "SH113671", "SH113673",
    "SH113674", "SH113682", "SH113688", "SH113691", "SH113692", "SH113693",
    "SH113696", "SH113697", "SH113699", "SH113700", "SH113702", "SH113704",
    "SH113706", "SH118013", "SH118022", "SH118024", "SH118030", "SH118031",
    "SH118034", "SH118053", "SH118058", "SH118059", "SH118063", "SH118064",
    "SH118065", "SH118070", "SH118071", "SH132024", "SH132026",
]


def build_command(code: str) -> list[dict[str, Any]]:
    return [{
        "type": "buysell",
        "code": code,
        "enable": 1,
        "buyLevels": 10,
        "sellLevels": 10,
    }]


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return Path(__file__).resolve().parent / f"d201_buysell_83_result_{stamp}.json"


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D201 83 只股票买卖盘口示例",
        epilog="每个连接的消息都应遍历 list 数组，并按 data.code 保存最新数据。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default=URL, help=f"D201 WebSocket 地址，默认 {URL}")
    parser.add_argument("--seconds", type=float, default=60.0, help="接收时长，默认 60 秒")
    parser.add_argument("--output", default="", help="统计汇总 JSON 路径，默认写入 examples")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="连接超时秒数")
    parser.add_argument("--recv-timeout", type=float, default=1.0, help="单次接收等待秒数")
    args = parser.parse_args()
    if args.seconds <= 0 or args.connect_timeout <= 0 or args.recv_timeout <= 0:
        parser.error("seconds/connect-timeout/recv-timeout 必须大于 0")
    return args


def receive_one(
    code: str,
    args: argparse.Namespace,
    started: float,
    deadline: float,
    latest_by_code: dict[str, dict[str, Any]],
    latest_lock: Lock,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "status": "connect_failed",
        "frames": 0,
        "infoCount": 0,
        "dataCount": 0,
        "firstDataSeconds": None,
        "errors": [],
        "connectSeconds": None,
    }
    ws = None

    try:
        connect_started = time.monotonic()
        ws = websocket.create_connection(args.url, timeout=args.connect_timeout)
        result["connectSeconds"] = round(time.monotonic() - connect_started, 3)
        result["status"] = "connected"
        ws.settimeout(args.recv_timeout)
        ws.send(json.dumps(build_command(code), separators=(",", ":")))

        while time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException as exc:
                result["status"] = "closed"
                result["errors"].append(str(exc))
                break

            if not raw:
                result["status"] = "closed"
                break

            result["frames"] += 1
            try:
                message = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                result["errors"].append(f"JSON: {exc}")
                continue

            items = message.get("list", [])
            if not isinstance(items, list):
                result["errors"].append("list 不是数组")
                continue

            for item in items:
                item_type = item.get("type")
                if item_type == "info":
                    result["infoCount"] += 1
                    continue
                if item_type == "error":
                    result["errors"].append(str(item.get("msg", "未知错误")))
                    continue
                if item_type != "buysell":
                    continue

                data = item.get("data") or {}
                if data.get("code") != code:
                    continue

                result["dataCount"] += 1
                if result["firstDataSeconds"] is None:
                    result["firstDataSeconds"] = round(time.monotonic() - started, 3)
                with latest_lock:
                    latest_by_code[code] = data
    except Exception as exc:
        result["errors"].append(str(exc))
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    return result


def run(args: argparse.Namespace) -> int:
    output_path = Path(args.output).expanduser() if args.output else default_output_path()
    started_wall = datetime.now().astimezone().isoformat(timespec="seconds")
    started = time.monotonic()
    deadline = started + args.seconds
    latest_by_code: dict[str, dict[str, Any]] = {}
    latest_lock = Lock()

    print(f"准备建立 {len(CODES)} 个 WebSocket 连接，每个连接订阅 1 只股票")
    print(f"连接地址：{args.url}")
    print(f"接收时长：{args.seconds:g} 秒")
    print(f"统计文件：{output_path.resolve()}")

    results: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=len(CODES), thread_name_prefix="d201") as pool:
            futures = [
                pool.submit(receive_one, code, args, started, deadline, latest_by_code, latest_lock)
                for code in CODES
            ]
            for index, future in enumerate(as_completed(futures), 1):
                results.append(future.result())
                if index % 10 == 0 or index == len(futures):
                    print(f"已完成 {index}/{len(futures)} 个连接", flush=True)
    except KeyboardInterrupt:
        print("收到 Ctrl+C，正在关闭连接……", file=sys.stderr)
    except Exception as exc:
        print(f"执行过程中发生异常：{exc}", file=sys.stderr)

    results.sort(key=lambda item: item["code"])
    counts = {item["code"]: item["dataCount"] for item in results}
    expected = set(CODES)
    received = {code for code, count in counts.items() if count > 0}
    missing = sorted(expected - received)
    errors = [
        f"{item['code']}: {message}"
        for item in results
        for message in item["errors"]
    ]
    connected_count = sum(
        item["status"] in {"connected", "closed"}
        for item in results
    )
    summary = {
        "status": "ok" if not errors and not missing else "completed_with_errors",
        "startedAt": started_wall,
        "finishedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "url": args.url,
        "durationSeconds": args.seconds,
        "connectionCount": len(CODES),
        "connectedCount": connected_count,
        "dataCodeCount": len(received),
        "latestCodeCount": len(latest_by_code),
        "totalDataCount": sum(counts.values()),
        "dataCountDistribution": dict(sorted(Counter(counts.values()).items())),
        "missingCodes": missing,
        "errorCount": len(errors),
        "errors": errors,
        "perCode": results,
    }
    write_summary(output_path, summary)

    print()
    print("========== 结果 ==========")
    print(f"连接成功：{connected_count}/{len(CODES)}")
    print(f"收到行情的股票：{len(received)}/{len(CODES)}")
    print(f"最新盘口缓存：{len(latest_by_code)}/{len(CODES)}")
    print(f"行情消息总数：{sum(counts.values())}")
    print(f"统计汇总已落盘：{output_path.resolve()}")
    if missing:
        print(f"未收到行情的代码：{','.join(missing)}")
    if errors:
        print(f"错误数：{len(errors)}")
        for message in errors[:10]:
            print(f"  - {message}")
    print("每个连接都遍历了完整 list，并按 data.code 更新 latest_by_code。")

    return 0 if summary["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
