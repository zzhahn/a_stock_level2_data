"""在 09:25:07 触发一次 D202 全市场竞价快照。

安装依赖：
    python -m pip install websocket-client

测试（先抓 10 只，立即执行）：
    python d202_snapshot_auction.py --limit 10 --run-now

正式使用（默认 0=全市场，等待中国时间 09:25:07）：
    python d202_snapshot_auction.py --output auction_092507.jsonl

输出采用 JSONL：每只股票一行，避免把全市场结果一次性组装到客户端内存。
每行的 data 字段包含 thousand、entrust、trade；entrust/trade 由服务端固定从
startSeq=1 顺序获取到 09:25:06，且不会保留截止时间之后的记录。客户端不能改为
全天回溯；建议在 09:25:07 获取，以得到完整的早盘竞价数据。

性能参考（Windows 客户端、batchSize=1、count=50、十档、cutoffTime=92506
的一次实测，不构成 SLA）：
    - 100 只股票落盘约 7.1 秒，返回约 20.8 万条委托/成交逐笔记录。
    - 全市场 4356 只，JSONL 落盘约 98~101 秒，文件约 331 MB。
    - 同参数不落盘、只接收并解析约 123 秒；测试中网络/服务端响应波动
      大于本地写盘差异，因此不落盘不保证更快。
    - JSONL 是流式写入，每只股票一行；全市场不会一次性堆成一个巨型对象。
      默认 batchSize=1 是实测最稳妥的设置，跨股票拼包不一定更快。
"""

from __future__ import annotations

import argparse
import json
import sys
import time as time_module
from contextlib import nullcontext
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import websocket
except ImportError:  # pragma: no cover - 给示例用户的安装提示
    print("缺少 websocket-client，请先执行: python -m pip install websocket-client", file=sys.stderr)
    raise


# 中国标准时间固定为 UTC+8，不依赖 Windows/Linux 的时区数据库。
CST = timezone(timedelta(hours=8), "Asia/Shanghai")
D202_MORNING_AUCTION_CUTOFF = 92506

PERFORMANCE_NOTE = """性能参考（实测参考，不构成 SLA）：
  batchSize=1、count=50、十档、竞价截止 92506 时，100 只股票落盘约 7.1 秒；
  全市场 4356 只 JSONL 落盘约 98~101 秒、文件约 331 MB；不落盘只接收解析约 123 秒。
  结果会受网络和服务端响应波动影响。JSONL 按股票流式写入，不会一次性占用巨型内存。

服务端始终固定为早盘竞价范围：startSeq=1、cutoffTime=92506；传入其他分页起点或
截止时间不会改变采集范围。
"""


def parse_clock(value: str) -> time:
    parts = value.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("时间格式应为 HH:MM:SS，例如 09:25:07")
    try:
        return time(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"无效时间: {value}") from exc


def next_trigger(now: datetime, trigger: time) -> datetime:
    return datetime.combine(now.date(), trigger, tzinfo=CST)


def wait_until(target: datetime) -> None:
    last_notice = 0.0
    while True:
        remaining = (target - datetime.now(CST)).total_seconds()
        if remaining <= 0:
            return
        current = time_module.monotonic()
        if current - last_notice >= 30 or remaining < 5:
            print(f"等待触发时间 {target:%Y-%m-%d %H:%M:%S %Z}，还剩 {remaining:.1f} 秒", flush=True)
            last_notice = current
        time_module.sleep(min(remaining, 1.0))


def make_output_path(value: str) -> Path:
    if value:
        return Path(value)
    return Path(f"d202_snapshot_{datetime.now(CST):%Y%m%d_%H%M%S}.jsonl")


def build_command(args: argparse.Namespace) -> dict[str, Any]:
    command: dict[str, Any] = {
        "type": "snapshot",
        "enable": 1,
        "levels": args.levels,
        "count": args.count,
        "workers": args.workers,
        "batchSize": args.batch_size,
        "filter": args.filter,
        "startSeq": 1,
        "cutoffTime": D202_MORNING_AUCTION_CUTOFF,
    }
    if args.codes:
        command["codes"] = [code.strip().upper() for code in args.codes.split(",") if code.strip()]
    else:
        # 0 表示服务端自动读取全部沪深京股票代码。
        command["limit"] = args.limit
    return command


def write_summary(output_path: Path, summary: dict[str, Any]) -> Path:
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary_path


def run(args: argparse.Namespace) -> int:
    output_path = None if args.no_output else make_output_path(args.output)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(CST)
    target = next_trigger(now, args.at)
    if args.run_now or now >= target:
        if not args.run_now and now >= target:
            print(f"当前已超过 {target:%H:%M:%S}，本次立即执行；测试可显式传 --run-now", flush=True)
        target = now

    command = build_command(args)
    print(f"连接 {args.url}", flush=True)
    ws = websocket.create_connection(args.url, timeout=args.connect_timeout)
    ws.settimeout(args.recv_timeout)
    print("WebSocket 已连接，连接保持后等待触发时间。", flush=True)

    request_sent_at: datetime | None = None
    snapshot_start: dict[str, Any] | None = None
    snapshot_done: dict[str, Any] | None = None
    error_messages: list[str] = []
    written = 0
    last_progress_print = time_module.monotonic()

    try:
        if target > datetime.now(CST):
            wait_until(target)

        request_sent_at = datetime.now(CST)
        ws.send(json.dumps([command], ensure_ascii=False, separators=(",", ":")))
        print(f"已发送 snapshot：{request_sent_at:%Y-%m-%d %H:%M:%S.%f %Z}", flush=True)
        if output_path is not None:
            print(f"输出文件：{output_path.resolve()}", flush=True)
        else:
            print("输出模式：不落盘（只接收并解析，不写 JSONL）", flush=True)

        output_context = (
            output_path.open("w", encoding="utf-8", buffering=1)
            if output_path is not None else nullcontext(None)
        )
        with output_context as output:
            while True:
                try:
                    message = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    progress = f"{written}/{snapshot_start.get('total', '?')}" if snapshot_start else str(written)
                    print(f"仍在等待服务端返回，当前进度 {progress}；高活跃股票分页较多时这是正常现象", flush=True)
                    continue

                for item in message.get("list", []):
                    item_type = item.get("type")
                    if item_type == "info":
                        print(f"[info] {item.get('msg', '')}", flush=True)
                    elif item_type == "error":
                        message_text = str(item.get("msg", "未知错误"))
                        error_messages.append(message_text)
                        print(f"[error] {message_text}", file=sys.stderr, flush=True)
                    elif item_type == "snapshot_start":
                        snapshot_start = item.get("data") or {}
                        print(f"开始快照：{snapshot_start}", flush=True)
                    elif item_type == "snapshot":
                        # 保留服务端消息时间戳和进度，data 是单只股票的完整结果。
                        stock_data = item.get("data") or {}
                        stock_errors = stock_data.get("errors") or []
                        if stock_errors:
                            code = stock_data.get("code", "?")
                            error_text = f"{code}: {','.join(map(str, stock_errors))}"
                            error_messages.append(error_text)
                            print(f"[stock-error] {error_text}", file=sys.stderr, flush=True)
                        progress = item.get("progress") or message.get("progress") or {}
                        if output is not None:
                            record = {
                                "ts": message.get("ts"),
                                "progress": progress,
                                "ok": not bool(stock_errors),
                                "errors": stock_errors,
                                "data": stock_data,
                            }
                            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                        written += 1
                        completed = progress.get("completed", written)
                        total = progress.get("total", snapshot_start.get("total", "?")) if snapshot_start else "?"
                        now_monotonic = time_module.monotonic()
                        if (written == 1 or written % 10 == 0 or completed == total
                                or now_monotonic - last_progress_print >= 30):
                            print(f"进度：{completed}/{total}，已写入 {written} 只", flush=True)
                            last_progress_print = now_monotonic
                    elif item_type == "snapshot_done":
                        snapshot_done = item.get("data") or {}
                        break

                if snapshot_done is not None:
                    break

        completed_at = datetime.now(CST)
        elapsed_seconds = (
            (completed_at - request_sent_at).total_seconds()
            if request_sent_at else None
        )
        summary = {
            "requestSentAt": request_sent_at.isoformat() if request_sent_at else None,
            "completedAt": completed_at.isoformat(),
            "url": args.url,
            "command": command,
            "output": str(output_path.resolve()) if output_path is not None else None,
            "written": written,
            "snapshotStart": snapshot_start,
            "snapshotDone": snapshot_done,
            "errors": error_messages,
        }
        if elapsed_seconds is not None:
            summary["elapsedSeconds"] = round(elapsed_seconds, 3)
        summary_path = write_summary(output_path, summary) if output_path is not None else None
        print(f"快照完成：{snapshot_done}，写入 {written} 只股票", flush=True)
        if summary_path is not None:
            print(f"汇总文件：{summary_path.resolve()}", flush=True)
        else:
            print(f"不落盘完成，接收并解析 {written} 只股票，耗时 {elapsed_seconds:.3f} 秒", flush=True)
        return 0 if snapshot_done and snapshot_done.get("failed", 0) == 0 else 2
    except KeyboardInterrupt:
        print("收到 Ctrl+C，正在请求取消快照……", file=sys.stderr, flush=True)
        try:
            ws.send(json.dumps([{"type": "snapshot", "enable": 0}], separators=(",", ":")))
        except Exception:
            pass
        return 130
    finally:
        ws.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="在 09:25:07 获取 D202 全市场竞价快照",
        epilog=PERFORMANCE_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default="ws://127.0.0.1:8080/d202", help="D202 WebSocket 地址")
    parser.add_argument("--at", type=parse_clock, default=time(9, 25, 7), help="触发时间，默认 09:25:07")
    parser.add_argument("--run-now", action="store_true", help="跳过等待，立即发送 snapshot")
    parser.add_argument("--limit", type=int, default=0, help="自动股票列表数量，0=全部，测试可设 10")
    parser.add_argument("--codes", default="", help="可选，逗号分隔的股票代码；指定后忽略 --limit")
    parser.add_argument("--levels", type=int, default=10, help="十档数量，默认 10")
    parser.add_argument("--count", type=int, default=50, help="委托/成交单页数量，默认 50")
    parser.add_argument("--workers", type=int, default=8, help="服务端并发度，默认 8")
    parser.add_argument("--batch-size", type=int, default=1,
                        help="每批请求的股票数，默认 1；大于1时启用多股票批量请求")
    parser.add_argument("--filter", type=int, default=0, help="委托金额筛选，默认 0")
    parser.add_argument("--output", default="", help="JSONL 输出文件，默认按当前时间生成")
    parser.add_argument("--no-output", action="store_true",
                        help="不写 JSONL/summary，只接收并解析，用于测量网络和解析耗时")
    parser.add_argument("--connect-timeout", type=int, default=10, help="WebSocket 连接超时秒数")
    parser.add_argument("--recv-timeout", type=int, default=30, help="无消息时打印心跳的秒数")
    args = parser.parse_args()

    if args.limit < 0 or args.levels < 1 or not 1 <= args.count <= 500:
        parser.error("limit/levels/count 参数范围无效")
    if args.no_output and args.output:
        parser.error("--no-output 不能与 --output 同时使用")
    if args.workers < 1 or not 0 <= args.filter <= 6:
        parser.error("workers/filter 参数范围无效")
    if args.batch_size < 1:
        parser.error("batch-size 必须大于 0")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
