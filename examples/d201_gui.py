#!/usr/bin/env python3
"""d201 Tkinter 大屏看板。

布局和交互对应服务内置的 d201 看板页面：

* 左栏维护全息队列的价位和子队列增量；
* 点击价位后，第二栏订阅该价位的逐笔排队变化；
* 第三、四栏分别展示逐笔委托和逐笔成交；
* WebSocket 在后台线程接收，Tk 只在主线程刷新界面。

运行前请安装 websocket-client：
    python -m pip install websocket-client
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk
from typing import Any

try:
    import websocket
except ImportError:  # pragma: no cover - 运行环境缺包时由界面提示
    websocket = None  # type: ignore[assignment]


URL = "ws://127.0.0.1:8080/d201"
DEFAULT_CODE = "SZ002177"
ENTRUST_HISTORY_USER_PARAM = 6201
TRADE_HISTORY_USER_PARAM = 6202
ENTRUST_HISTORY_PAGE = 150
TRADE_HISTORY_PAGE = 60

# Tk Canvas 是全量重绘模型；给历史和事件设置上限，避免运行时间越长，
# 单次刷新需要处理的对象越多，最终拖垮主线程。
MAX_FLOW_ROWS = 800
EVENT_QUEUE_SIZE = 2048
POLL_INTERVAL_MS = 20
RENDER_INTERVAL_MS = 16

# 与网页看板保持同一组颜色。
BG = "#0a0e17"
TOP = "#111111"
INPUT = "#1a1a2e"
BORDER = "#222222"
BORDER_LIGHT = "#333333"
TEXT = "#cccccc"
MUTED = "#888888"
DIM = "#666666"
RED = "#e94560"
GREEN = "#38a141"
GOLD = "#e9c445"
BLUE = "#3498db"
LINK = "#6aaaff"
WHITE = "#f2f2f2"

FONT = ("Consolas", 10)
FONT_SMALL = ("Consolas", 9)
FONT_TINY = ("Consolas", 8)
FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")
FONT_WATERMARK = ("Microsoft YaHei UI", 24, "bold")


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_amount(value: Any) -> str:
    """沿用网页看板的金额显示：原值 / 10000，并以万显示。"""
    amount = as_int(value)
    if not amount:
        return "0"
    wan = amount / 10000
    if wan >= 100:
        return f"{int(wan)}万"
    if wan >= 1:
        return f"{wan:.1f}万"
    return f"{wan:.2f}万"


def format_holo_amount(value: Any) -> str:
    """全息队列金额统一保留一位小数。"""
    amount = as_int(value)
    wan = amount / 10000
    if abs(wan) >= 10000:
        return f"{wan / 10000:.1f}亿"
    return f"{wan:.1f}万"


def format_time(value: Any) -> str:
    if not value:
        return ""
    text = f"{as_int(value):06d}"[-6:]
    return f"{text[:2]}:{text[2:4]}:{text[4:6]}"


def format_price(value: Any, divisor: int = 100) -> str:
    return f"{as_int(value) / divisor:.2f}"


def parallel_rows(data: dict[str, Any], fields: list[str]) -> list[dict[str, Any]]:
    """将接口的平行数组恢复成记录，不因数组长度不齐而静默丢字段。"""
    arrays = {
        field: data.get(field) if isinstance(data.get(field), list) else []
        for field in fields
    }
    length = max((len(values) for values in arrays.values()), default=0)
    return [
        {
            field: values[index] if index < len(values) else ""
            for field, values in arrays.items()
        }
        for index in range(length)
    ]


def install_hint() -> str:
    return "此面板需要 websocket-client。请执行：python -m pip install websocket-client"


class D201Stream:
    """d201 WebSocket 接收线程；不直接触碰 Tk 控件。"""

    def __init__(
        self,
        url: str,
        code: str,
        events: queue.Queue[tuple["D201Stream", str, Any]],
    ) -> None:
        self.url = url
        self.code = code
        self.events = events
        self.stop_event = threading.Event()
        self.send_lock = threading.Lock()
        self.ws: Any = None
        self.thread = threading.Thread(target=self._run, name=f"d201-{code}", daemon=True)

        self.base_commands = [
            {"type": "holoqueue", "code": code, "enable": 1, "subDisplayCount": 6},
            {"type": "entrust", "code": code, "enable": 1, "count": 150},
            {"type": "trade", "code": code, "enable": 1, "count": 60},
        ]

    def start(self) -> None:
        self.thread.start()

    def _emit(self, kind: str, payload: Any = None) -> None:
        event = (self, kind, payload)
        # 只保留较新的事件。UI 已经落后时，继续无限积压旧行情只会让
        # 画面显示越来越“陈旧”；有界队列也能避免断线/重连时内存增长。
        while not self.stop_event.is_set():
            try:
                self.events.put_nowait(event)
                return
            except queue.Full:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    pass

    def _send_now(self, commands: list[dict[str, Any]]) -> bool:
        with self.send_lock:
            ws = self.ws
            if ws is None:
                return False
            try:
                ws.send(json.dumps(commands, ensure_ascii=False, separators=(",", ":")))
                return True
            except Exception as exc:
                self._emit("error", str(exc))
                return False

    def send(self, command: dict[str, Any]) -> bool:
        return self._send_now([command])

    def stop(self) -> None:
        self.stop_event.set()
        with self.send_lock:
            ws = self.ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=1.5)

    def _run(self) -> None:
        if websocket is None:
            self._emit("error", install_hint())
            self._emit("state", "closed")
            return

        ws: Any = None
        try:
            self._emit("state", "connecting")
            ws = websocket.create_connection(self.url, timeout=5)
            ws.settimeout(1.0)
            with self.send_lock:
                self.ws = ws
            self._emit("state", "connected")
            self._send_now(self.base_commands)

            while not self.stop_event.is_set():
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    break
                try:
                    message = json.loads(raw)
                except (TypeError, json.JSONDecodeError) as exc:
                    self._emit("error", f"JSON 消息解析失败：{exc}")
                    continue
                if isinstance(message, dict):
                    self._emit("message", message)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._emit("error", str(exc))
        finally:
            with self.send_lock:
                if self.ws is ws:
                    self.ws = None
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            self._emit("state", "closed")


class D201Gui:
    WATERMARK_TEXT = "d201\ndata interface"

    def __init__(self, root: tk.Tk, url: str = URL, code: str = DEFAULT_CODE) -> None:
        self.root = root
        self.url = url
        self.root.title("d201 · 实时盘口大屏")
        self.root.geometry("1600x960")
        self.root.minsize(1430, 700)
        self.root.configure(bg=BG)
        if sys.platform.startswith("win"):
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.events: queue.Queue[tuple[D201Stream, str, Any]] = queue.Queue(maxsize=EVENT_QUEUE_SIZE)
        self.stream: D201Stream | None = None
        self.connected = False
        self.connecting = False
        self.message_count = 0
        self.started_at = 0.0
        self.last_error = ""
        self.render_pending = False
        self.dirty_views: set[str] = set()
        self.hq_log_collapsed = False
        self.privacy_mode = False

        self.code_var = tk.StringVar(value=code)
        self.status_var = tk.StringVar(value="未连接")
        self.message_var = tk.StringVar(value="0")
        self.rate_var = tk.StringVar(value="0")
        self.sp_title_var = tk.StringVar(value="单个价位 — 等待选择")
        self.sp_summary_var = tk.StringVar(value="")

        self._reset_data()
        self._build_style()
        self._build_layout()
        self.schedule_render()
        self.root.after(POLL_INTERVAL_MS, self._poll_events)

    # ── 界面 ─────────────────────────────────────────────────────────────

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "D201.Treeview",
            background=BG,
            fieldbackground=BG,
            foreground=TEXT,
            borderwidth=0,
            relief="flat",
            rowheight=18,
            font=FONT_SMALL,
        )
        style.map(
            "D201.Treeview",
            background=[("selected", INPUT)],
            foreground=[("selected", WHITE)],
        )
        style.configure(
            "D201.Treeview.Heading",
            background=TOP,
            foreground=MUTED,
            borderwidth=0,
            relief="flat",
            font=FONT_TINY,
        )
        style.map("D201.Treeview.Heading", background=[("active", TOP)])
        style.configure(
            "D201.Vertical.TScrollbar",
            background="#333333",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=MUTED,
            relief="flat",
        )

    def _build_layout(self) -> None:
        self._build_topbar()
        main = tk.Frame(self.root, bg=BG)
        main.grid(row=1, column=0, sticky="nsew")
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main.grid_columnconfigure(0, minsize=520, weight=0)
        main.grid_columnconfigure(1, minsize=330, weight=0)
        main.grid_columnconfigure(2, minsize=300, weight=0)
        main.grid_columnconfigure(3, minsize=280, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self.flow_canvases: dict[str, tk.Canvas] = {}
        self.flow_scrollbars: dict[str, ttk.Scrollbar] = {}
        self.flow_titles: dict[str, tk.Label] = {}
        self.flow_kind_by_widget: dict[str, str] = {}
        self.flow_base_titles = {"entrust": "委托", "trade": "成交"}

        self.col1 = self._column_frame(main, 0, 520)
        self.col2 = self._column_frame(main, 1, 330)
        self.col3 = self._column_frame(main, 2, 300)
        self.col4 = self._column_frame(main, 3)
        self._build_holo_column(self.col1)
        self._build_single_price_column(self.col2)
        self._build_flow_column(self.col3, "委托", "entrust")
        self._build_flow_column(self.col4, "成交", "trade")

    def _build_topbar(self) -> None:
        self.topbar = tk.Frame(self.root, bg=TOP, height=32)
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)

        tk.Label(
            self.topbar,
            text="达塔接口  ·  d201",
            bg=TOP,
            fg=GOLD,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left", padx=(8, 8), pady=2)
        tk.Label(
            self.topbar,
            text="实时深度",
            bg=TOP,
            fg=GOLD,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left", padx=(0, 6), pady=2)
        tk.Label(
            self.topbar,
            text="实时盘口看板",
            bg=TOP,
            fg=TEXT,
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left", padx=(0, 9), pady=2)

        self.code_entry = tk.Entry(
            self.topbar,
            textvariable=self.code_var,
            width=10,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_LIGHT,
            highlightcolor=LINK,
            font=FONT_SMALL,
        )
        self.code_entry.pack(side="left", padx=(0, 5), pady=4, ipady=1)
        self.code_entry.bind("<Return>", lambda _event: self.connect())
        self.code_entry.bind("<FocusOut>", self._code_focus_out)

        self.connect_button = tk.Button(
            self.topbar,
            text="连接",
            command=self.connect,
            bg="#1a4a2e",
            activebackground="#2a6a3e",
            fg="#aaddaa",
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            padx=10,
            pady=2,
            font=FONT_SMALL,
        )
        self.connect_button.pack(side="left", padx=(0, 4), pady=3)
        self.disconnect_button = tk.Button(
            self.topbar,
            text="断开",
            command=self.disconnect,
            bg="#4a1a1a",
            activebackground="#6a2a2a",
            fg="#dd8888",
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            padx=10,
            pady=2,
            font=FONT_SMALL,
            state="disabled",
        )
        self.disconnect_button.pack(side="left", padx=(0, 6), pady=3)
        self._build_privacy_button()

        self.status_label = tk.Label(
            self.topbar,
            textvariable=self.status_var,
            bg=TOP,
            fg=MUTED,
            font=FONT_TINY,
            anchor="w",
        )
        self.status_label.pack(side="left", padx=(0, 8), pady=2)

        stats = tk.Frame(self.topbar, bg=TOP)
        stats.pack(side="right", padx=(0, 8), pady=2)
        for label, variable in (("消息:", self.message_var), ("速率:", self.rate_var)):
            tk.Label(stats, text=label, bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(8, 2))
            tk.Label(stats, textvariable=variable, bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left")

    def _build_privacy_button(self) -> None:
        self.privacy_button = tk.Button(
            self.topbar,
            text="隐藏中文名",
            command=self._toggle_privacy,
            bg="#26364d",
            activebackground="#35516d",
            fg=GOLD,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            padx=8,
            pady=2,
            font=FONT_TINY,
        )
        self.privacy_button.pack(side="left", padx=(0, 6), pady=3)

    @staticmethod
    def _column_frame(parent: tk.Widget, column: int, width: int | None = None) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG, highlightbackground=BORDER, highlightthickness=0, width=width or 0)
        frame.grid(row=0, column=column, sticky="nsew")
        if width is not None:
            frame.grid_propagate(False)
        frame.grid_columnconfigure(0, weight=1)
        return frame

    @staticmethod
    def _section_title(parent: tk.Widget, text: str) -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            bg=TOP,
            fg=RED,
            anchor="w",
            padx=4,
            font=FONT_TITLE,
        )
        label.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        return label

    @classmethod
    def _draw_watermark(cls, canvas: tk.Canvas, width: int, height: int) -> None:
        """在数据画布背景层绘制两处固定视口水印。"""
        height = max(1, height)
        for viewport_y in (int(height * 0.28), int(height * 0.72)):
            canvas.create_text(
                width / 2,
                canvas.canvasy(viewport_y),
                text=cls.WATERMARK_TEXT,
                anchor="center",
                justify="center",
                fill="#111c2a",
                font=FONT_WATERMARK,
                tags="watermark",
            )

    @staticmethod
    def _reposition_watermark(canvas: tk.Canvas) -> None:
        """滚动时只校正水印位置，不重绘行情内容。"""
        items = canvas.find_withtag("watermark")
        if not items:
            return
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        for item, viewport_y in zip(items, (int(height * 0.28), int(height * 0.72))):
            canvas.coords(item, width / 2, canvas.canvasy(viewport_y))

    @staticmethod
    def _watermark_scroll_set(
        canvas: tk.Canvas,
        scrollbar: ttk.Scrollbar,
        first: str,
        last: str,
    ) -> None:
        scrollbar.set(first, last)
        D201Gui._reposition_watermark(canvas)

    def _build_holo_column(self, parent: tk.Frame) -> None:
        # 这里不用 Treeview，是为了让六个子队列金额可以分别着色。
        self._section_title(parent, "全息队列 — 卖盘")
        parent.grid_rowconfigure(1, weight=1)
        self.hq_canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        self.hq_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.hq_canvas.yview, style="D201.Vertical.TScrollbar")
        self.hq_canvas.configure(
            yscrollcommand=lambda first, last: self._watermark_scroll_set(
                self.hq_canvas, self.hq_scroll, first, last
            )
        )
        self.hq_canvas.grid(row=1, column=0, sticky="nsew", padx=(4, 0))
        self.hq_scroll.grid(row=1, column=1, sticky="ns", padx=(0, 3))
        self.hq_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.hq_canvas.bind("<Button-4>", lambda _event: self.hq_canvas.yview_scroll(-3, "units"))
        self.hq_canvas.bind("<Button-5>", lambda _event: self.hq_canvas.yview_scroll(3, "units"))
        self.hq_canvas.bind("<Configure>", lambda _event: self.schedule_render())

    def _build_single_price_column(self, parent: tk.Frame) -> None:
        title = tk.Label(
            parent,
            textvariable=self.sp_title_var,
            bg=TOP,
            fg=TEXT,
            anchor="w",
            padx=4,
            font=FONT_TITLE,
        )
        title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(4, 2))
        parent.grid_rowconfigure(3, weight=1)

        self.sp_summary = tk.Label(
            parent,
            textvariable=self.sp_summary_var,
            bg=TOP,
            fg=TEXT,
            anchor="w",
            padx=4,
            font=FONT_SMALL,
        )
        self.sp_summary.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 2))
        self.sp_summary.grid_remove()
        self.sp_head = tk.Canvas(parent, height=22, bg=TOP, highlightthickness=0, bd=0)
        self.sp_head.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4)
        self.sp_canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        sp_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.sp_canvas.yview, style="D201.Vertical.TScrollbar")
        self.sp_canvas.configure(
            yscrollcommand=lambda first, last: self._watermark_scroll_set(
                self.sp_canvas, sp_scroll, first, last
            )
        )
        self.sp_canvas.grid(row=3, column=0, sticky="nsew", padx=(4, 0))
        sp_scroll.grid(row=3, column=1, sticky="ns", padx=(0, 3))
        self.sp_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.sp_canvas.bind("<Button-4>", lambda _event: self.sp_canvas.yview_scroll(-3, "units"))
        self.sp_canvas.bind("<Button-5>", lambda _event: self.sp_canvas.yview_scroll(3, "units"))
        self.sp_canvas.bind("<Configure>", lambda _event: self.schedule_render())

    def _build_flow_column(self, parent: tk.Frame, title: str, kind: str) -> None:
        title_label = self._section_title(parent, title)
        self.flow_titles[kind] = title_label
        parent.grid_rowconfigure(3, weight=1)
        head = tk.Canvas(parent, height=22, bg=TOP, highlightthickness=0, bd=0)
        head.grid(row=1, column=0, sticky="ew", padx=4)
        body = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=body.yview, style="D201.Vertical.TScrollbar")
        body.configure(
            yscrollcommand=lambda first, last, canvas=body, scrollbar=scroll: self._watermark_scroll_set(
                canvas, scrollbar, first, last
            )
        )
        body.grid(row=3, column=0, sticky="nsew", padx=(4, 0))
        scroll.grid(row=3, column=1, sticky="ns", padx=(0, 3))
        body.bind("<MouseWheel>", self._on_mousewheel)
        body.bind("<Button-4>", lambda _event, flow_kind=kind: self._flow_wheel(flow_kind, -3))
        body.bind("<Button-5>", lambda _event, flow_kind=kind: self._flow_wheel(flow_kind, 3))
        body.bind("<Configure>", lambda _event: self.schedule_render())
        scroll.bind(
            "<ButtonRelease-1>",
            lambda _event, flow_kind=kind: self.root.after_idle(lambda: self._maybe_load_history(flow_kind)),
        )
        setattr(self, f"{kind}_head", head)
        setattr(self, f"{kind}_canvas", body)
        self.flow_canvases[kind] = body
        self.flow_scrollbars[kind] = scroll
        self.flow_kind_by_widget[str(body)] = kind

    def _on_mousewheel(self, event: tk.Event) -> None:
        canvas = event.widget
        delta = -1 * (as_int(getattr(event, "delta", 0)) // 120)
        if delta == 0:
            delta = -1 if getattr(event, "num", 0) == 4 else 1
        canvas.yview_scroll(delta, "units")
        flow_kind = self.flow_kind_by_widget.get(str(canvas))
        if flow_kind:
            self.root.after_idle(lambda: self._maybe_load_history(flow_kind))

    def _flow_wheel(self, kind: str, delta: int) -> str:
        canvas = self.flow_canvases[kind]
        canvas.yview_scroll(delta, "units")
        self.root.after_idle(lambda: self._maybe_load_history(kind))
        return "break"

    def _set_flow_title(self, kind: str, status: str = "") -> None:
        title = self.flow_titles.get(kind)
        if title is None:
            return
        base = self.flow_base_titles[kind]
        title.configure(text=f"{base} · {status}" if status else base)

    def _maybe_load_history(self, kind: str) -> None:
        canvas = self.flow_canvases.get(kind)
        if canvas is None:
            return
        first, last = canvas.yview()
        if last - first >= 0.999 or last < 0.995:
            return
        if kind == "entrust":
            if self.ent_history_loading or self.ent_history_exhausted or not self.ent_log:
                return
        elif kind == "trade":
            if self.trd_history_loading or self.trd_history_exhausted or not self.trd_log:
                return
        else:
            return
        self._request_history(kind)

    def _request_history(self, kind: str) -> None:
        stream = self.stream
        if stream is None or not self.connected:
            return

        if kind == "entrust":
            if len(self.ent_log) >= MAX_FLOW_ROWS:
                self.ent_history_exhausted = True
                self._set_flow_title(kind, f"仅保留最近 {MAX_FLOW_ROWS} 条")
                return
            cursor = as_int(self.ent_log[-1].get("orderId"))
            if not cursor:
                self.ent_history_exhausted = True
                self._set_flow_title(kind, "无历史游标")
                return
            command = {
                "type": "entrust",
                "code": stream.code,
                "enable": 2,
                "history": 1,
                "orderId": cursor,
                "count": -ENTRUST_HISTORY_PAGE,
                "userParam": ENTRUST_HISTORY_USER_PARAM,
            }
        else:
            if len(self.trd_log) >= MAX_FLOW_ROWS:
                self.trd_history_exhausted = True
                self._set_flow_title(kind, f"仅保留最近 {MAX_FLOW_ROWS} 条")
                return
            oldest = self.trd_log[-1]
            cursor_time = as_int(oldest.get("time"))
            cursor_seq = as_int(oldest.get("seq"))
            if not cursor_time and not cursor_seq:
                self.trd_history_exhausted = True
                self._set_flow_title(kind, "无历史游标")
                return
            command = {
                "type": "trade",
                "code": stream.code,
                "enable": 2,
                "timeOfDay": cursor_time,
                "seqPos": cursor_seq,
                "count": -TRADE_HISTORY_PAGE,
                "userParam": TRADE_HISTORY_USER_PARAM,
            }

        if not stream.send(command):
            return
        self.flow_keep_bottom[kind] = True
        if kind == "entrust":
            self.ent_history_loading = True
        else:
            self.trd_history_loading = True
        self._set_flow_title(kind, "加载历史…")

    def _restore_flow_bottom(self, kind: str) -> None:
        canvas = self.flow_canvases.get(kind)
        if canvas is not None:
            canvas.yview_moveto(1.0)
        self.flow_keep_bottom[kind] = False

    # ── 数据状态 ─────────────────────────────────────────────────────────

    def _reset_data(self) -> None:
        self.hq_map: dict[tuple[int, int], dict[str, Any]] = {}
        self.hq_log: deque[dict[str, Any]] = deque(maxlen=200)
        self.sp_price: int | None = None
        self.sp_dir = 0
        self.sp_price_cent = 0
        self.sp_total = {"vol": 0, "amt": 0, "cnt": 0, "seq": 0, "cur": 0}
        self.sp_recs: list[dict[str, Any]] = []
        self.sp_index: dict[int, dict[str, Any]] = {}
        self.sp_had_records = False
        self.sp_had_first = False
        self.sp_resub_after: str | None = None
        self.ent_log: list[dict[str, Any]] = []
        self.trd_log: list[dict[str, Any]] = []
        self.ent_seen: set[str] = set()
        self.trd_seen: set[str] = set()
        self.ent_history_loading = False
        self.trd_history_loading = False
        self.ent_history_exhausted = False
        self.trd_history_exhausted = False
        self.trd_history_total = 0
        self.flow_keep_bottom = {"entrust": False, "trade": False}

    def _trim_flow_log(self, kind: str) -> None:
        """保留最新记录，并同步裁剪去重集合。"""
        if kind == "entrust":
            log = self.ent_log
            seen = self.ent_seen
            key = lambda row: f"{row.get('time')}_{row.get('orderId')}"
        else:
            log = self.trd_log
            seen = self.trd_seen
            key = lambda row: f"{row.get('time')}_{row.get('seq')}"

        if len(log) <= MAX_FLOW_ROWS:
            return
        del log[MAX_FLOW_ROWS:]
        seen.clear()
        seen.update(key(row) for row in log)

    def _clear_runtime_data(self) -> None:
        if self.sp_resub_after is not None:
            try:
                self.root.after_cancel(self.sp_resub_after)
            except tk.TclError:
                pass
        self._reset_data()
        self.sp_title_var.set("单个价位 — 等待选择")
        self.sp_summary_var.set("")
        self.sp_summary.grid_remove()
        self._set_flow_title("entrust")
        self._set_flow_title("trade")
        self.schedule_render()

    def _add_hq_log(self, price: int, direction: int, lines: list[str], removed: int = 0) -> None:
        self.hq_log.appendleft(
            {
                "ts": time.strftime("%H:%M:%S"),
                "price": price,
                "dir": direction,
                "lines": lines,
                "removed": removed,
            }
        )

    # ── 消息分发 ─────────────────────────────────────────────────────────

    def _poll_events(self) -> None:
        processed = 0
        dirty = False
        while processed < 350:
            try:
                source, kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if source is not self.stream:
                continue
            if kind == "state":
                self._set_connection_state(str(payload))
            elif kind == "error":
                self.last_error = "数据服务连接异常"
                self._set_status("⚠ " + self.last_error, RED)
            elif kind == "message" and isinstance(payload, dict):
                dirty = self._handle_message(payload) or dirty
        if dirty:
            self.schedule_render(*self.dirty_views)
        if processed:
            self.message_var.set(f"{self.message_count:,}")
            elapsed = max(0.001, time.monotonic() - self.started_at)
            self.rate_var.set(f"{self.message_count / elapsed:.1f}")
        self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def _handle_message(self, message: dict[str, Any]) -> bool:
        self.message_count += 1

        dirty = False
        items = message.get("list", [])
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "error":
                self._set_status("⚠ 数据服务返回错误", RED)
                continue
            if kind == "info":
                self._set_status("数据服务状态已更新", MUTED)
                continue
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            if kind == "holoqueue":
                if self._update_holoqueue(data):
                    self.dirty_views.add("hq")
                    dirty = True
            elif kind == "price":
                if self._update_price(data):
                    self.dirty_views.add("price")
                    dirty = True
            elif kind == "entrust":
                if self._update_entrust(data, as_int(data.get("userParam")) == ENTRUST_HISTORY_USER_PARAM):
                    self.dirty_views.add("entrust")
                    dirty = True
            elif kind == "trade":
                if self._update_trade(data, as_int(data.get("userParam")) == TRADE_HISTORY_USER_PARAM):
                    self.dirty_views.add("trade")
                    dirty = True
        return dirty

    # ── 全息队列 ─────────────────────────────────────────────────────────

    def _update_holoqueue(self, data: dict[str, Any]) -> bool:
        if not isinstance(data.get("levels"), list):
            return False
        changed = False
        for level in data["levels"]:
            if not isinstance(level, dict):
                continue
            changed = True
            change_type = as_int(level.get("changeType"))
            direction = as_int(level.get("direction"))
            price = as_int(level.get("price"))
            remove_price = as_int(level.get("removePrice"))
            key = (price, direction)

            # 先处理特殊的“清空旧价位”信号。
            if change_type == 1 and remove_price and price == 0:
                self.hq_map.pop((remove_price, direction), None)
                self._add_hq_log(remove_price, direction, ["  -价位已清空"])
                continue
            if price == 0:
                continue
            if change_type == 0:
                self.hq_map.pop(key, None)
                self._add_hq_log(price, direction, ["  -删除价位"])
                continue
            if change_type == 1 and remove_price:
                self.hq_map.pop((remove_price, direction), None)

            entry = self.hq_map.setdefault(key, {})
            entry.update(
                {
                    "price": price,
                    "volume": as_int(level.get("volume")),
                    "amount": as_int(level.get("amount")),
                    "direction": direction,
                    "queueCount": as_int(level.get("queueCount")),
                    "displayCnt": as_int(level.get("displayCnt")),
                }
            )
            sub_recs: list[dict[str, Any]] = entry.setdefault("subRecs", [])
            sub_index = {as_int(record.get("id")): record for record in sub_recs}
            log_lines: list[str] = []
            records = level.get("records") if isinstance(level.get("records"), list) else []
            for record in records:
                if not isinstance(record, dict):
                    continue
                record_id = as_int(record.get("id"))
                volume = as_int(record.get("volume"))
                amount = as_int(record.get("amount"))
                status = as_int(record.get("status"))
                old = sub_index.get(record_id)
                if old is not None:
                    previous_status = as_int(old.get("status"))
                    old.update(
                        {
                            "volume": volume,
                            "amount": amount,
                            "bigOrder": as_int(record.get("bigOrder")),
                            "prevStatus": previous_status,
                            "status": status,
                        }
                    )
                    if volume == 0:
                        old["_remove"] = True
                        log_lines.append("  -删除一笔排队")
                    elif previous_status != status:
                        log_lines.append("  ~排队状态更新")
                elif volume > 0:
                    sub_recs.append(
                        {
                            "id": record_id,
                            "volume": volume,
                            "amount": amount,
                            "bigOrder": as_int(record.get("bigOrder")),
                            "status": status,
                            "prevStatus": 0,
                            "isNew": True,
                        }
                    )
                    log_lines.append(f"  +新增 {volume}手 {format_holo_amount(amount)}")
            before = len(sub_recs)
            entry["subRecs"] = [record for record in sub_recs if not record.get("_remove")]
            if log_lines:
                self._add_hq_log(price, direction, log_lines, before - len(entry["subRecs"]))
        return changed

    def _render_hq(self) -> None:
        canvas = self.hq_canvas
        canvas.delete("all")
        width = max(390, canvas.winfo_width())
        self._draw_watermark(canvas, width, canvas.winfo_height())
        y = 4
        y = self._draw_hq_side(canvas, width, y, 1, "卖")
        y += 5
        canvas.create_text(4, y, text="全息队列 — 买盘", anchor="nw", fill=RED, font=FONT_TITLE)
        y += 22
        y = self._draw_hq_side(canvas, width, y, 0, "买")
        y += 7
        log_tag = "hqlog_toggle"
        canvas.create_rectangle(0, y, width, y + 20, fill=TOP, outline=TOP, tags=(log_tag,))
        canvas.create_text(4, y + 3, text="子队列变更日志  (点击折叠)", anchor="nw", fill=RED, font=FONT_SMALL, tags=(log_tag,))
        canvas.tag_bind(log_tag, "<Button-1>", self._toggle_hq_log)
        y += 23
        if self.hq_log_collapsed:
            canvas.create_text(4, y, text="已折叠", anchor="nw", fill=DIM, font=FONT_TINY)
            y += 16
        elif not self.hq_log:
            canvas.create_text(4, y, text="等待数据...", anchor="nw", fill=DIM, font=FONT_TINY)
            y += 18
        else:
            for log in list(self.hq_log)[:50]:
                color = GREEN if as_int(log.get("dir")) else RED
                lines = [
                    f"[{log.get('ts', '')}] {as_int(log.get('price')) / 100:.2f} ({'卖' if as_int(log.get('dir')) else '买'})"
                ]
                lines.extend(str(line) for line in log.get("lines", []))
                if as_int(log.get("removed")):
                    lines.append(f"  -移除 {as_int(log.get('removed'))} 条记录")
                canvas.create_text(4, y, text=lines[0], anchor="nw", fill=color, font=FONT_TINY)
                y += 12
                for line in lines[1:]:
                    canvas.create_text(4, y, text=line, anchor="nw", fill=MUTED, font=FONT_TINY)
                    y += 11
                y += 2
        canvas.configure(scrollregion=(0, 0, width, max(y + 8, canvas.winfo_height())))

    def _draw_hq_side(self, canvas: tk.Canvas, width: int, y: int, direction: int, label: str) -> int:
        rows = [row for row in self.hq_map.values() if as_int(row.get("direction")) == direction]
        rows.sort(key=lambda row: as_int(row.get("price")), reverse=True)
        x = 2
        usable = max(370, width - 6)
        fixed = 30 + 48 + 55 + 32 + 26
        sub_width = max(29, int((usable - fixed) / 6))
        columns = [30, 48, 55, 32] + [sub_width] * 6 + [26]
        labels = ["档位", "价位", "总额", "排队", "金额1", "金额2", "金额3", "金额4", "金额5", "金额6", "盯"]
        header_tag = f"hq_header_{direction}"
        canvas.create_rectangle(x, y, x + sum(columns), y + 18, fill=INPUT, outline=INPUT, tags=(header_tag,))
        cx = x
        for col_width, text in zip(columns, labels):
            anchor = "e" if text not in {"档位", "盯"} else "center"
            canvas.create_text(cx + col_width / 2 if anchor == "center" else cx + col_width - 3, y + 3, text=text, anchor="n" if anchor == "center" else "ne", fill=MUTED, font=FONT_TINY, tags=(header_tag,))
            cx += col_width
        y += 21
        if not rows:
            canvas.create_text(x + 4, y, text=f"暂无{label}盘数据", anchor="nw", fill=DIM, font=FONT_TINY)
            return y + 18

        for index, row in enumerate(rows[:10]):
            price = as_int(row.get("price"))
            row_tag = f"hq_row_{direction}_{price}_{index}"
            selected = self.sp_price == price and self.sp_dir == direction
            canvas.create_rectangle(
                x,
                y,
                x + sum(columns),
                y + 19,
                fill="#263b55" if selected else TOP,
                outline=GOLD if selected else TOP,
                width=1,
                tags=(row_tag,),
            )
            n_label = label + (str(len(rows[:10]) - index) if direction else str(index + 1))
            values = [n_label, f"{price / 100:.2f}", format_holo_amount(row.get("amount")), str(as_int(row.get("queueCount")))]
            cx = x
            for col_index, (col_width, text) in enumerate(zip(columns[:4], values)):
                color = RED if direction == 0 and col_index == 1 else GREEN if direction == 1 and col_index == 1 else MUTED if col_index >= 2 else TEXT
                anchor = "center" if col_index == 0 else "e"
                tx = cx + col_width / 2 if anchor == "center" else cx + col_width - 3
                canvas.create_text(tx, y + 3, text=text, anchor="n" if anchor == "center" else "ne", fill=color, font=FONT_SMALL, tags=(row_tag,))
                cx += col_width
            sub_records = row.get("subRecs") if isinstance(row.get("subRecs"), list) else []
            sub_color = RED if direction == 0 else GREEN
            for sub_index in range(6):
                col_width = columns[4 + sub_index]
                record = sub_records[sub_index] if sub_index < len(sub_records) else None
                text = "-" if record is None else format_holo_amount(record.get("amount"))
                color = sub_color
                if record is not None and as_int(record.get("bigOrder")):
                    color = GOLD if direction == 0 else BLUE
                canvas.create_text(cx + col_width - 3, y + 3, text=text, anchor="ne", fill=color, font=FONT_SMALL, tags=(row_tag,))
                cx += col_width
            button_x = cx
            canvas.create_rectangle(button_x + 2, y + 2, button_x + columns[-1] - 2, y + 17, fill="#1a3a5e", outline="#2a5a8e", tags=(row_tag,))
            canvas.create_text(button_x + columns[-1] / 2, y + 3, text="盯", anchor="n", fill=LINK, font=FONT_TINY, tags=(row_tag,))
            canvas.tag_bind(row_tag, "<Button-1>", lambda _event, p=price, d=direction: self.subscribe_price(p, d))
            y += 21
        return y

    def _toggle_hq_log(self, _event: tk.Event | None = None) -> None:
        self.hq_log_collapsed = not self.hq_log_collapsed
        self.schedule_render()

    # ── 单个价位 ─────────────────────────────────────────────────────────

    def subscribe_price(self, price: int, direction: int) -> None:
        if self.stream is not None and self.connected and self.sp_price is not None:
            self.stream.send(
                {
                    "type": "price",
                    "code": self.code_var.get().strip().upper(),
                    "enable": 0,
                    "direction": self.sp_dir,
                    "priceCent": self.sp_price_cent,
                }
            )
        if self.sp_resub_after is not None:
            try:
                self.root.after_cancel(self.sp_resub_after)
            except tk.TclError:
                pass
            self.sp_resub_after = None
        self.sp_price = as_int(price)
        self.sp_dir = as_int(direction)
        self.sp_price_cent = self.sp_price * 10
        self.sp_total = {"vol": 0, "amt": 0, "cnt": 0, "seq": 0, "cur": 0}
        self.sp_recs = []
        self.sp_index = {}
        self.sp_had_records = False
        self.sp_had_first = False
        self.sp_title_var.set(f"单个价位 — {self.sp_price / 100:.2f} {'买' if self.sp_dir == 0 else '卖'}")
        self.sp_summary_var.set("订阅中...")
        self.sp_summary.grid()
        if self.stream is not None and self.connected:
            self.stream.send(
                {
                    "type": "price",
                    "code": self.code_var.get().strip().upper(),
                    "enable": 1,
                    "direction": self.sp_dir,
                    "priceCent": self.sp_price_cent,
                }
            )
        else:
            self.sp_summary_var.set("尚未连接，连接后将订阅")
        self.schedule_render()

    def _update_price(self, data: dict[str, Any]) -> bool:
        if self.sp_price is None:
            return False
        response_price = as_int(data.get("price"))
        if abs(response_price / 10 - self.sp_price) > 1 or as_int(data.get("direction")) != self.sp_dir:
            return False
        records = data.get("records") if isinstance(data.get("records"), list) else []
        if as_int(data.get("isFirst")) == 1:
            if not self.sp_had_first:
                self.sp_total = {
                    "vol": as_int(data.get("totalVolume")),
                    "amt": as_int(data.get("totalAmount")),
                    "cnt": as_int(data.get("totalCount")),
                    "seq": as_int(data.get("seq")),
                    "cur": as_int(data.get("curCount")),
                }
                self.sp_had_first = True
            for record in records:
                if not isinstance(record, dict):
                    continue
                volume = as_int(record.get("volume"))
                record_id = as_int(record.get("id"))
                if volume == 0:
                    continue
                old = self.sp_index.get(record_id)
                if old is None:
                    old = {
                        "volume": volume,
                        "id": record_id,
                        "amount": as_int(record.get("amount")),
                        "bigOrder": as_int(record.get("bigOrder")),
                        "status": as_int(record.get("status")),
                        "prevStatus": 0,
                        "isNew": False,
                    }
                    self.sp_recs.append(old)
                    self.sp_index[record_id] = old
                else:
                    old.update(
                        {
                            "volume": volume,
                            "amount": as_int(record.get("amount")),
                            "bigOrder": as_int(record.get("bigOrder")),
                            "status": as_int(record.get("status")),
                        }
                    )
        else:
            self.sp_total["cur"] = as_int(data.get("curCount"))
            for record in records:
                if not isinstance(record, dict):
                    continue
                record_id = as_int(record.get("id"))
                volume = as_int(record.get("volume"))
                amount = as_int(record.get("amount"))
                status = as_int(record.get("status"))
                old = self.sp_index.get(record_id)
                if old is not None:
                    self.sp_total["vol"] += volume - as_int(old.get("volume"))
                    self.sp_total["amt"] += amount - as_int(old.get("amount"))
                    old.update({"volume": volume, "amount": amount, "bigOrder": as_int(record.get("bigOrder")), "prevStatus": as_int(old.get("status")), "status": status})
                    if volume == 0:
                        old["_remove"] = True
                        self.sp_total["cnt"] = max(0, as_int(self.sp_total.get("cnt")) - 1)
                elif volume > 0:
                    self.sp_total["vol"] += volume
                    self.sp_total["amt"] += amount
                    self.sp_total["cnt"] += 1
                    new_record = {
                        "volume": volume,
                        "id": record_id,
                        "amount": amount,
                        "bigOrder": as_int(record.get("bigOrder")),
                        "status": status,
                        "prevStatus": 0,
                        "isNew": True,
                    }
                    self.sp_recs.append(new_record)
                    self.sp_index[record_id] = new_record
            self.sp_recs = [record for record in self.sp_recs if not record.get("_remove")]
            self.sp_index = {as_int(record.get("id")): record for record in self.sp_recs}

            if self.sp_recs:
                self.sp_had_records = True
                if self.sp_resub_after is not None:
                    try:
                        self.root.after_cancel(self.sp_resub_after)
                    except tk.TclError:
                        pass
                    self.sp_resub_after = None
            elif self.sp_had_records and self.sp_resub_after is None:
                self.sp_resub_after = self.root.after(2000, self._resubscribe_selected_price)

        if self.sp_recs:
            self.sp_had_records = True
        self.sp_summary_var.set(
            f"总手 {as_int(self.sp_total.get('vol'))}   总金额 {format_amount(self.sp_total.get('amt'))}   总笔 {as_int(self.sp_total.get('cnt'))}   本次 {as_int(self.sp_total.get('cur'))}"
        )
        return True

    def _resubscribe_selected_price(self) -> None:
        self.sp_resub_after = None
        if self.sp_price is not None and self.connected:
            self.subscribe_price(self.sp_price, self.sp_dir)

    def _render_single_price(self) -> None:
        self.sp_head.delete("all")
        self.sp_canvas.delete("all")
        width = max(310, self.sp_canvas.winfo_width())
        columns = [28, 78, 112, max(42, width - 218)]
        labels = ["#", "手数", "金额", "状态"]
        self._draw_header(self.sp_head, columns, labels)
        self._draw_watermark(self.sp_canvas, width, self.sp_canvas.winfo_height())
        y = 4
        if self.sp_price is None:
            self.sp_canvas.create_text(4, y, text="等待选择价位", anchor="nw", fill=MUTED, font=FONT_SMALL)
            center_y = max(80, self.sp_canvas.winfo_height() / 2)
            self.sp_canvas.create_text(width / 2, center_y - 10, text="点击左侧全息队列的任一价位", anchor="center", fill="#526d88", font=FONT_SMALL)
            self.sp_canvas.create_text(width / 2, center_y + 10, text="查看该价位的单笔排队变化", anchor="center", fill=DIM, font=FONT_TINY)
            self.sp_canvas.configure(scrollregion=(0, 0, width, max(120, self.sp_canvas.winfo_height())))
            return
        first_change = next((index for index, record in enumerate(self.sp_recs) if as_int(record.get("status")) != 0), -1)
        for index, record in enumerate(self.sp_recs):
            row_y = y
            row_h = 19
            if index == first_change:
                self.sp_canvas.create_rectangle(1, row_y, width - 2, row_y + row_h, outline=GOLD, width=2, fill="#1a1a00")
            else:
                self.sp_canvas.create_line(0, row_y + row_h, width, row_y + row_h, fill=INPUT)
            color = RED if self.sp_dir == 0 else GREEN
            if as_int(record.get("bigOrder")):
                color = GOLD if self.sp_dir == 0 else BLUE
            status = self._price_status(record)
            # 委托号只保留在 sp_index 里用于增量更新/去重，界面不展示。
            values = [str(index + 1), str(as_int(record.get("volume"))), format_amount(record.get("amount")), status]
            cx = 0
            for col_index, (col_width, value) in enumerate(zip(columns, values)):
                anchor = "center" if col_index == 0 or col_index == 3 else "e"
                tx = cx + col_width / 2 if anchor == "center" else cx + col_width - 4
                cell_color = color if col_index in {1, 2} else MUTED if col_index == 3 else TEXT
                self.sp_canvas.create_text(tx, row_y + 2, text=value, anchor="n" if anchor == "center" else "ne", fill=cell_color, font=FONT_SMALL)
                cx += col_width
            y += row_h
        if not self.sp_recs:
            text = "价位已清空，2秒后自动重订阅..." if self.sp_had_records else "该价位暂无排队"
            self.sp_canvas.create_text(4, y, text=text, anchor="nw", fill=MUTED, font=FONT_TINY)
            y += 18
        self.sp_canvas.configure(scrollregion=(0, 0, width, max(y + 8, self.sp_canvas.winfo_height())))

    @staticmethod
    def _price_status(record: dict[str, Any]) -> str:
        volume = as_int(record.get("volume"))
        status = as_int(record.get("status"))
        if volume == 0 or status in {2, 32}:
            return ""
        if status in {4, 12, 64, 192}:
            return "更新"
        if status in {1, 9, 16, 128, 144}:
            return "变化"
        return "状态变化" if status else ""

    # ── 委托和成交 ──────────────────────────────────────────────────────

    def _update_entrust(self, data: dict[str, Any], history: bool = False) -> int:
        fields = ["time", "orderId", "price", "volume", "amount", "priceType", "size", "direction"]
        fresh: list[dict[str, Any]] = []
        for row in parallel_rows(data, fields):
            key = f"{row.get('time')}_{row.get('orderId')}"
            if key in self.ent_seen:
                continue
            self.ent_seen.add(key)
            fresh.append(row)
        fresh.sort(key=lambda row: (as_int(row.get("time")), as_int(row.get("orderId"))), reverse=True)
        if history:
            self.ent_log.extend(fresh)
            self._trim_flow_log("entrust")
            self.ent_history_loading = False
            if len(self.ent_log) >= MAX_FLOW_ROWS:
                self.ent_history_exhausted = True
                self._set_flow_title("entrust", f"仅保留最近 {MAX_FLOW_ROWS} 条")
            elif not fresh or as_int(data.get("count")) < ENTRUST_HISTORY_PAGE:
                self.ent_history_exhausted = True
                self._set_flow_title("entrust", "已到最早")
            else:
                self._set_flow_title("entrust")
        else:
            self.ent_log[0:0] = fresh
            self._trim_flow_log("entrust")
        return len(fresh)

    def _update_trade(self, data: dict[str, Any], history: bool = False) -> int:
        fields = [
            "time", "seq", "price", "volume", "buyOrderId", "sellOrderId",
            "buyVolume", "sellVolume", "active", "status", "buySize", "sellSize",
            "buyAmount", "sellAmount",
        ]
        fresh: list[dict[str, Any]] = []
        for row in parallel_rows(data, fields):
            key = f"{row.get('time')}_{row.get('seq')}"
            if key in self.trd_seen:
                continue
            self.trd_seen.add(key)
            fresh.append(row)
        fresh.sort(key=lambda row: (as_int(row.get("time")), as_int(row.get("seq"))), reverse=True)
        if history:
            self.trd_log.extend(fresh)
            self._trim_flow_log("trade")
            self.trd_history_loading = False
            self.trd_history_total = max(self.trd_history_total, as_int(data.get("totalCount")))
            if len(self.trd_log) >= MAX_FLOW_ROWS:
                self.trd_history_exhausted = True
                self._set_flow_title("trade", f"仅保留最近 {MAX_FLOW_ROWS} 条")
            elif (
                not fresh
                or as_int(data.get("count")) < TRADE_HISTORY_PAGE
                or (self.trd_history_total and len(self.trd_log) >= self.trd_history_total)
            ):
                self.trd_history_exhausted = True
                self._set_flow_title("trade", "已到最早")
            else:
                self._set_flow_title("trade")
        else:
            self.trd_log[0:0] = fresh
            self._trim_flow_log("trade")
        return len(fresh)

    def _draw_header(self, canvas: tk.Canvas, columns: list[int], labels: list[str]) -> None:
        canvas.delete("all")
        cx = 0
        for width, label in zip(columns, labels):
            anchor = "center" if label in {"#", "状态"} else "w"
            tx = cx + width / 2 if anchor == "center" else cx + 4
            canvas.create_text(tx, 3, text=label, anchor="n" if anchor == "center" else "nw", fill=MUTED, font=FONT_TINY)
            cx += width

    @staticmethod
    def _trade_group_ranges(rows: list[dict[str, Any]], field: str) -> list[tuple[int, int]]:
        """返回连续相同委托号的行范围；单行不画分组外框。"""
        groups: list[tuple[int, int]] = []
        index = 0
        while index < len(rows):
            order_id = as_int(rows[index].get(field))
            end = index
            if order_id:
                while end + 1 < len(rows) and as_int(rows[end + 1].get(field)) == order_id:
                    end += 1
                if end > index:
                    groups.append((index, end))
            index = end + 1
        return groups

    @staticmethod
    def _trade_leg_text(price: Any, volume: Any) -> str:
        """成交金额按成交价（分）×手数计算，避免万元整数舍入为 0。"""
        volume_int = as_int(volume)
        amount_text = format_amount(as_int(price) * volume_int)
        if "万" not in amount_text:
            amount_text += "万"
        return f"{volume_int}({amount_text})"

    def _render_entrust(self) -> None:
        head = self.entrust_head
        canvas = self.entrust_canvas
        width = max(265, canvas.winfo_width())
        columns = [58, 58, 40, 68, max(36, width - 58 - 58 - 40 - 68)]
        self._draw_header(head, columns, ["时间", "价", "量", "金额", "方向"])
        canvas.delete("all")
        self._draw_watermark(canvas, width, canvas.winfo_height())
        y = 2
        for row in self.ent_log:
            direction = as_int(row.get("direction"))
            side_color = GREEN if direction else RED
            big = as_int(row.get("volume")) >= 100
            if big:
                side_color = GOLD
            values = [
                format_time(row.get("time")),
                format_price(row.get("price")),
                str(as_int(row.get("volume"))),
                format_amount(row.get("amount")),
                "卖" if direction else "买",
            ]
            cx = 0
            for index, (col_width, value) in enumerate(zip(columns, values)):
                anchor = "center" if index == 4 else "e" if index > 0 else "w"
                tx = cx + col_width / 2 if anchor == "center" else cx + col_width - 4 if anchor == "e" else cx + 4
                color = MUTED if index == 0 else side_color if index in {1, 2, 3, 4} else TEXT
                canvas.create_text(tx, y + 2, text=value, anchor="n" if anchor == "center" else "ne" if anchor == "e" else "nw", fill=color, font=FONT_SMALL)
                cx += col_width
            canvas.create_line(0, y + 18, width, y + 18, fill=INPUT)
            y += 19
        if not self.ent_log:
            canvas.create_text(width / 2, max(60, canvas.winfo_height() / 2), text="等待委托数据...", anchor="center", fill="#526d88", font=FONT_SMALL)
        canvas.configure(scrollregion=(0, 0, width, max(y + 5, canvas.winfo_height())))
        if self.flow_keep_bottom.get("entrust"):
            self.root.after_idle(lambda: self._restore_flow_bottom("entrust"))

    def _render_trade(self) -> None:
        head = self.trade_head
        canvas = self.trade_canvas
        width = max(265, canvas.winfo_width())
        base_columns = [58, 60, 72, 72, 78, 38]
        base_width = sum(base_columns)
        if width >= base_width:
            extra = width - base_width
            share, remainder = divmod(extra, 4)
            columns = [
                base_columns[0],
                base_columns[1],
                base_columns[2] + share,
                base_columns[3] + share,
                base_columns[4] + share,
                base_columns[5] + remainder,
            ]
        else:
            scale = width / base_width
            columns = [max(30, int(value * scale)) for value in base_columns]
            columns[-1] += width - sum(columns)
        self._draw_header(head, columns, ["时间", "价", "买(手/万)", "卖(手/万)", "成交(手/万)", "状态"])
        canvas.delete("all")
        self._draw_watermark(canvas, width, canvas.winfo_height())
        buy_groups = self._trade_group_ranges(self.trd_log, "buyOrderId")
        sell_groups = self._trade_group_ranges(self.trd_log, "sellOrderId")
        buy_group_rows = {row_index for start, end in buy_groups for row_index in range(start, end + 1)}
        sell_group_rows = {row_index for start, end in sell_groups for row_index in range(start, end + 1)}
        buy_x1 = sum(columns[:2])
        buy_x2 = buy_x1 + columns[2]
        sell_x1 = buy_x2
        sell_x2 = sell_x1 + columns[3]
        y = 2
        for row_index, row in enumerate(self.trd_log):
            volume = as_int(row.get("volume"))
            big = volume >= 100
            values = [
                format_time(row.get("time")),
                format_price(row.get("price")),
                self._trade_leg_text(row.get("price"), row.get("buyVolume")),
                self._trade_leg_text(row.get("price"), row.get("sellVolume")),
                self._trade_leg_text(row.get("price"), volume),
                str(as_int(row.get("status"))),
            ]
            cx = 0
            for index, (col_width, value) in enumerate(zip(columns, values)):
                anchor = "center" if index == 5 else "e" if index else "w"
                tx = cx + col_width / 2 if anchor == "center" else cx + col_width - 4 if anchor == "e" else cx + 4
                if index == 0 or index == 5:
                    color = MUTED
                elif index == 2:
                    color = GOLD if big else RED
                elif index == 3:
                    color = GOLD if big else GREEN
                elif index == 4:
                    color = GOLD if big else TEXT
                else:
                    color = TEXT
                canvas.create_text(tx, y + 2, text=value, anchor="n" if anchor == "center" else "ne" if anchor == "e" else "nw", fill=color, font=FONT_SMALL)
                cx += col_width

            # 行分隔线避开同一委托号的买/卖分组单元格，组内不再出现横线。
            blocked = []
            if row_index in buy_group_rows:
                blocked.append((buy_x1, buy_x2))
            if row_index in sell_group_rows:
                blocked.append((sell_x1, sell_x2))
            cursor = 0
            for block_start, block_end in blocked:
                if block_start > cursor:
                    canvas.create_line(cursor, y + 18, block_start, y + 18, fill=INPUT)
                cursor = max(cursor, block_end)
            if cursor < width:
                canvas.create_line(cursor, y + 18, width, y + 18, fill=INPUT)
            y += 19
        # 每个连续委托号只画一个完整外框，而不是每一行重复套框。
        for start, end in buy_groups:
            canvas.create_rectangle(buy_x1 + 1, 2 + start * 19 + 1, buy_x2 - 1, 2 + (end + 1) * 19 - 1, outline=GOLD, dash=(3, 2), width=1)
        for start, end in sell_groups:
            canvas.create_rectangle(sell_x1 + 1, 2 + start * 19 + 1, sell_x2 - 1, 2 + (end + 1) * 19 - 1, outline=BLUE, dash=(3, 2), width=1)
        if not self.trd_log:
            canvas.create_text(width / 2, max(60, canvas.winfo_height() / 2), text="等待成交数据...", anchor="center", fill="#526d88", font=FONT_SMALL)
        canvas.configure(scrollregion=(0, 0, width, max(y + 5, canvas.winfo_height())))
        if self.flow_keep_bottom.get("trade"):
            self.root.after_idle(lambda: self._restore_flow_bottom("trade"))

    # ── 连接控制 ─────────────────────────────────────────────────────────

    def _code_focus_out(self, _event: tk.Event) -> None:
        self.code_var.set(self.code_var.get().strip().upper())

    def connect(self) -> None:
        code = self.code_var.get().strip().upper()
        self.code_var.set(code)
        if not re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", code):
            self._set_status("⚠ 代码格式应为 SH/SZ/BJ + 6 位数字", RED)
            return
        if websocket is None:
            self._set_status("⚠ " + install_hint(), RED)
            return
        self.disconnect(silent=True)
        self._clear_runtime_data()
        self.message_count = 0
        self.started_at = time.monotonic()
        self.message_var.set("0")
        self.rate_var.set("0")
        self.last_error = ""
        stream = D201Stream(self.url, code, self.events)
        self.stream = stream
        self.connecting = True
        self.connected = False
        self._set_status("连接中...", MUTED)
        self.connect_button.configure(text="连接中...", state="disabled", bg="#1a2a4a", fg=LINK)
        self.disconnect_button.configure(state="normal")
        stream.start()

    def disconnect(self, silent: bool = False) -> None:
        stream = self.stream
        if stream is not None:
            disable = [
                {"type": command["type"], "code": command["code"], "enable": 0}
                for command in stream.base_commands
            ]
            if self.sp_price is not None:
                disable.append(
                    {
                        "type": "price",
                        "code": stream.code,
                        "enable": 0,
                        "direction": self.sp_dir,
                        "priceCent": self.sp_price_cent,
                    }
                )
            stream._send_now(disable)
            stream.stop()
        self.stream = None
        self.connected = False
        self.connecting = False
        self.connect_button.configure(text="连接", state="normal", bg="#1a4a2e", fg="#aaddaa")
        self.disconnect_button.configure(state="disabled")
        if not silent:
            self._set_status("已断开", MUTED)

    def _set_connection_state(self, state: str) -> None:
        if state == "connecting":
            self.connecting = True
            self.connected = False
            self._set_status("连接中...", MUTED)
        elif state == "connected":
            self.connecting = False
            self.connected = True
            self._set_status("已连接", "#44cc66")
            self.connect_button.configure(text="已订阅", state="disabled", bg="#1a2a4a", fg=LINK)
            self.disconnect_button.configure(state="normal")
        elif state == "closed":
            was_active = self.connected or self.connecting
            self.connected = False
            self.connecting = False
            self.connect_button.configure(text="连接", state="normal", bg="#1a4a2e", fg="#aaddaa")
            self.disconnect_button.configure(state="disabled")
            if was_active and not self.last_error:
                self._set_status("已断开", MUTED)

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(fg=color)

    def _toggle_privacy(self) -> None:
        self.privacy_mode = not self.privacy_mode
        self.privacy_button.configure(text="恢复中文名" if self.privacy_mode else "隐藏中文名")
        self.schedule_render()

    def schedule_render(self, *views: str) -> None:
        if views:
            self.dirty_views.update(views)
        else:
            self.dirty_views.update(("hq", "price", "entrust", "trade"))
        if self.render_pending:
            return
        self.render_pending = True
        self.root.after(RENDER_INTERVAL_MS, self._refresh_views)

    def _refresh_views(self) -> None:
        self.render_pending = False
        views = self.dirty_views
        self.dirty_views = set()
        if "hq" in views:
            self._render_hq()
        if "price" in views:
            self._render_single_price()
        if "entrust" in views:
            self._render_entrust()
        if "trade" in views:
            self._render_trade()

    def close(self) -> None:
        self.disconnect(silent=True)
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="d201 Tkinter 实时盘口大屏")
    parser.add_argument("--url", default=URL, help=f"WebSocket 地址，默认 {URL}")
    parser.add_argument("--code", default=DEFAULT_CODE, help=f"股票代码，默认 {DEFAULT_CODE}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = tk.Tk()
    D201Gui(root, args.url, args.code)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
