#!/usr/bin/env python3
"""通过本地 D201 WebSocket 采集逐笔委托和逐笔成交到 CSV。"""

from __future__ import annotations

import argparse
import csv
import json
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import websocket


URL = "ws://127.0.0.1:8080/d201"
DEFAULT_CODES = ("SH600519", "SZ300750")
STOP = False


def stop(_signum: int, _frame: Any) -> None:
    global STOP
    STOP = True


def parallel_rows(data: dict[str, Any], fields: list[str]) -> list[dict[str, Any]]:
    """把 D201 的平行数组还原成逐笔记录，不用 zip 静默截断。"""
    arrays = {field: data.get(field) if isinstance(data.get(field), list) else [] for field in fields}
    length = max((len(values) for values in arrays.values()), default=0)
    if len({len(values) for values in arrays.values()}) > 1:
        print(f"警告：{data.get('code')} 的平行数组长度不一致", file=sys.stderr)

    rows: list[dict[str, Any]] = []
    for index in range(length):
        row = {field: values[index] if index < len(values) else "" for field, values in arrays.items()}
        row["index"] = index
        rows.append(row)
    return rows


class CsvFiles:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.handles: dict[tuple[str, str], tuple[Any, csv.DictWriter]] = {}
        self.lock = threading.Lock()

    def write(self, code: str, kind: str, row: dict[str, Any]) -> None:
        with self.lock:
            key = (code, kind)
            if key not in self.handles:
                path = self.output / f"{code}_{kind}.csv"
                handle = path.open("a", encoding="utf-8-sig", newline="")
                fields = list(row)
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                if handle.tell() == 0:
                    writer.writeheader()
                self.handles[key] = handle, writer
            handle, writer = self.handles[key]
            writer.writerow(row)
            handle.flush()

    def close(self) -> None:
        for handle, _writer in self.handles.values():
            handle.close()


def now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def process_item(
    item: dict[str, Any],
    expected_code: str,
    files: CsvFiles,
    seen: dict[tuple[str, str], set[str]],
) -> None:
    kind = item.get("type")
    if kind == "error":
        print(f"服务错误：{item.get('msg', item)}", file=sys.stderr)
        return
    if kind not in {"trade", "entrust"}:
        return
    data = item.get("data")
    if not isinstance(data, dict) or not data.get("code"):
        return

    code = str(data["code"])
    if code != expected_code:
        return
    if kind == "trade":
        fields = ["time", "seq", "price", "volume", "buyOrderId", "sellOrderId",
                  "buyVolume", "sellVolume", "active", "status", "buySize", "sellSize",
                  "buyAmount", "sellAmount"]
        rows = parallel_rows(data, fields)
    else:
        fields = ["time", "orderId", "price", "volume", "amount", "priceType", "size", "direction"]
        rows = parallel_rows(data, fields)

    for row in rows:
        # 服务端的 seq 在不同批次中可能重新从 0 开始，不能按单调递增过滤。
        # 用整笔记录指纹去重，既保留 seq 重复但内容不同的记录，也避免重连重复落盘。
        fingerprint = json.dumps([row.get(field) for field in fields], ensure_ascii=False)
        key = (code, kind)
        if fingerprint in seen.setdefault(key, set()):
            continue
        seen[key].add(fingerprint)

        output = {
            "received_at": now(),
            "code": code,
            "event_type": kind,
            "index": row.pop("index"),
            **row,
            "price_yuan": (float(row["price"]) / 100 if row.get("price") not in (None, "") else ""),
        }
        files.write(code, kind, output)


def subscriptions(code: str, count: int, user_param_base: int) -> list[dict[str, Any]]:
    return [
        {"type": "trade", "code": code, "enable": 1, "count": count, "userParam": user_param_base},
        {"type": "entrust", "code": code, "enable": 1, "count": count, "userParam": user_param_base + 1},
    ]


def run_for_code(
    code: str,
    user_param_base: int,
    args: argparse.Namespace,
    files: CsvFiles,
    started: float,
) -> None:
    """一个股票一条连接；该股票断线时只重连自己的连接。"""
    requests = subscriptions(code, args.count, user_param_base)
    seen: dict[tuple[str, str], set[str]] = {}
    deadline = started + args.seconds if args.seconds > 0 else None

    while not STOP and (deadline is None or time.monotonic() < deadline):
        ws = None
        try:
            print(f"[{code}] 连接 {args.url}", flush=True)
            ws = websocket.create_connection(args.url, timeout=5)
            ws.send(json.dumps(requests, ensure_ascii=False, separators=(",", ":")))
            print(f"[{code}] 已订阅逐笔成交和逐笔委托", flush=True)
            while not STOP and (deadline is None or time.monotonic() < deadline):
                try:
                    message = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if not isinstance(message, dict):
                    continue
                for item in message.get("list", []):
                    if isinstance(item, dict):
                        process_item(item, code, files, seen)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            if not STOP:
                print(f"[{code}] 连接断开：{exc}；5 秒后重连", file=sys.stderr, flush=True)
                wait_seconds = 5
                if deadline is not None:
                    wait_seconds = min(wait_seconds, max(0, deadline - time.monotonic()))
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
        finally:
            if ws is not None:
                try:
                    unsubscribe = [
                        {
                            "type": item["type"],
                            "code": item["code"],
                            "enable": 0,
                            "userParam": item["userParam"],
                        }
                        for item in requests
                    ]
                    ws.send(json.dumps(unsubscribe, separators=(",", ":")))
                except Exception:
                    pass
                ws.close()


def main() -> int:
    global STOP
    parser = argparse.ArgumentParser(description="采集 D201 逐笔委托和逐笔成交 CSV")
    parser.add_argument("--codes", nargs="+", default=list(DEFAULT_CODES), help="代码，例如 SH600519 SZ300750")
    parser.add_argument("--out", type=Path, default=Path("./d201_csv"), help="CSV 输出目录")
    parser.add_argument("--url", default=URL, help=f"D201 WebSocket 地址，默认 {URL}")
    parser.add_argument("--count", type=int, default=150, help="每次推送最多记录数，默认 150")
    parser.add_argument("--seconds", type=int, default=0, help="运行秒数；0 表示持续运行")
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count 必须大于 0")

    codes = [code.upper() for code in args.codes]
    files = CsvFiles(args.out)
    started = time.monotonic()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    workers = [
        threading.Thread(
            target=run_for_code,
            args=(code, 100 + index * 10, args, files, started),
            name=f"d201-{code}",
        )
        for index, code in enumerate(codes)
    ]

    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    finally:
        STOP = True
        for worker in workers:
            worker.join(timeout=6)
        files.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
