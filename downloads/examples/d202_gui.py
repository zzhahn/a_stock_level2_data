#!/usr/bin/env python3
"""d202 Tkinter 大屏看板。

保持 d201 的深色大屏布局，但使用 d202 的五类数据：

* 千档深度：点击买卖档位可查看该档排队明细；
* 委托、成交、大单：使用 rows 对象数组，并支持滚到底部继续回溯；
* 队列：显示当前选中档位的排队股数和按价位换算的金额。

运行前请安装 websocket-client：
    python -m pip install websocket-client
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import tkinter as tk
import time
from tkinter import ttk
from typing import Any

from d201_gui import (
    BG,
    BLUE,
    BORDER,
    BORDER_LIGHT,
    DIM,
    FONT,
    FONT_SMALL,
    FONT_TINY,
    FONT_TITLE,
    GOLD,
    GREEN,
    INPUT,
    LINK,
    MAX_FLOW_ROWS,
    MUTED,
    RED,
    TEXT,
    TOP,
    WHITE,
    D201Gui,
    D201Stream,
    as_int,
    format_price,
    format_time,
    install_hint,
)


URL = "ws://127.0.0.1:8080/d202"
DEFAULT_CODE = "SZ300773"
PAGE_SIZE = 50
HISTORY_REQUEST_TIMEOUT_MS = 8_000
DEFAULT_LEVELS = 10
MAX_LEVELS = 1000
# 千档/委托的价格是“分”，队列 volumes 是“股”；结果换算为万元。
QUEUE_AMOUNT_DIVISOR = 1_000_000
BOTTOM_FRACTION = 0.995  # Tk 滚动条视觉到底时，yview 可能只到 0.997 左右。
FONT_WATERMARK = ("Microsoft YaHei UI", 24, "bold")

BASE_PARAMS = {
    "thousand": 2201,
    "entrust": 2202,
    "trade": 2203,
    "bigorder": 2204,
}
HISTORY_PARAMS = {
    "entrust": 9202,
    "trade": 9203,
    "bigorder": 9204,
}
QUEUE_PARAMS = {"B": 2205, "S": 2206}


def format_wan(value: Any) -> str:
    """d202 金额字段已经是万元，不能沿用 d201 的分转万元。"""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    if not number:
        return "0万"
    if abs(number) >= 10000:
        return f"{number / 10000:.1f}亿"
    if number == int(number):
        return f"{int(number)}万"
    return f"{number:.1f}万"


def normalize_levels(value: Any) -> int:
    return max(1, min(MAX_LEVELS, as_int(value, DEFAULT_LEVELS)))


def format_l2_time(value: Any) -> str:
    """将服务端 L2 时间值按千分之一显示，例如 93000000 -> 93000.000。"""
    number = as_int(value)
    if not number:
        return ""
    whole, milliseconds = divmod(number, 1000)
    return f"{whole}.{milliseconds:03d}"


def side_label(value: Any) -> tuple[str, str]:
    text = str(value).upper()
    if text in {"B", "66"}:
        return "买", RED
    if text in {"S", "83"}:
        return "卖", GREEN
    return "—", MUTED


def flatten_rows(value: Any) -> list[dict[str, Any]]:
    """兼容服务端当前偶发的 rows:[[...]] 和标准 rows:[...]."""
    rows = value if isinstance(value, list) else []
    while len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    return [row for row in rows if isinstance(row, dict)]


class D202Stream(D201Stream):
    """沿用 d201 的线程收发模型，只替换 d202 订阅命令。"""

    def __init__(self, url: str, code: str, events: queue.Queue, levels: int = DEFAULT_LEVELS) -> None:
        super().__init__(url, code, events)
        self.levels = normalize_levels(levels)
        self.base_commands = [
            {
                "type": "thousand",
                "code": code,
                "enable": 1,
                "levels": self.levels,
                "userParam": BASE_PARAMS["thousand"],
            },
            {
                "type": "entrust",
                "code": code,
                "enable": 1,
                "count": PAGE_SIZE,
                "userParam": BASE_PARAMS["entrust"],
            },
            {
                "type": "trade",
                "code": code,
                "enable": 1,
                "count": PAGE_SIZE,
                "userParam": BASE_PARAMS["trade"],
            },
            {
                "type": "bigorder",
                "code": code,
                "enable": 1,
                "count": PAGE_SIZE,
                "userParam": BASE_PARAMS["bigorder"],
            },
            {
                "type": "queue",
                "code": code,
                "enable": 1,
                "dir": "B",
                "level": 0,
                "userParam": QUEUE_PARAMS["B"],
            },
        ]


class D202Gui(D201Gui):
    """d202 单股票实时大屏。"""

    WATERMARK_TEXT = "d202\ndata interface"
    RENDER_VIEWS = ("depth", "queue", "entrust", "bigorder", "trade")

    def __init__(self, root: tk.Tk, url: str = URL, code: str = DEFAULT_CODE) -> None:
        self.depth_summary_var = tk.StringVar(master=root, value="")
        self.depth_l2_var = tk.StringVar(master=root, value="")
        self.depth_levels_var = tk.StringVar(master=root, value="")
        self.depth_latest_var = tk.StringVar(master=root, value="")
        self.depth_buy_var = tk.StringVar(master=root, value="")
        self.depth_sell_var = tk.StringVar(master=root, value="")
        self.queue_summary_var = tk.StringVar(master=root, value="")
        self.bigorder_summary_var = tk.StringVar(master=root, value="")
        self.levels_var = tk.StringVar(master=root, value=str(DEFAULT_LEVELS))
        super().__init__(root, url, code)
        self.root.title("d202 · 实时盘口大屏")
        self.root.minsize(1900, 760)

    def schedule_render(self, *views: str) -> None:
        """使用 d202 自己的面板名称，复用基类的合并定时器。"""
        if views:
            super().schedule_render(*views)
        else:
            super().schedule_render(*self.RENDER_VIEWS)

    # ── d202 布局 ──────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self._build_topbar()
        main = tk.Frame(self.root, bg=BG)
        main.grid(row=1, column=0, sticky="nsew")
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 大屏使用五栏：千档、队列、大单、委托、成交全部同时可见。
        # 大单列增加基础宽度；成交仍保留较大弹性，但不再独占大部分扩展空间。
        for column, (minimum, weight) in enumerate(
            ((390, 2), (285, 1), (360, 2), (315, 1), (550, 3))
        ):
            main.grid_columnconfigure(column, minsize=minimum, weight=weight)
        main.grid_rowconfigure(0, weight=1)

        self.flow_canvases: dict[str, tk.Canvas] = {}
        self.flow_scrollbars: dict[str, ttk.Scrollbar] = {}
        self.flow_titles: dict[str, tk.Label] = {}
        self.flow_kind_by_widget: dict[str, str] = {}
        self.flow_base_titles = {"entrust": "委托", "trade": "成交", "bigorder": "大单资金"}

        self.col1 = self._column_frame(main, 0)
        self.col2 = self._column_frame(main, 1)
        self.col3 = self._column_frame(main, 2)
        self.col4 = self._column_frame(main, 3)
        self.col5 = self._column_frame(main, 4)
        self._build_depth_column(self.col1)
        self._build_queue_column(self.col2)
        self._build_bigorder_column(self.col3)
        self._build_flow_column(self.col4, "委托", "entrust")
        self._build_flow_column(self.col5, "成交", "trade")

    def _build_topbar(self) -> None:
        self.topbar = tk.Frame(self.root, bg=TOP, height=32)
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)

        tk.Label(
            self.topbar,
            text="达塔接口  ·  d202",
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
        tk.Label(self.topbar, text="实时盘口大屏", bg=TOP, fg=TEXT, font=("Microsoft YaHei UI", 10)).pack(
            side="left", padx=(0, 9), pady=2
        )

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

        tk.Label(self.topbar, text="档数", bg=TOP, fg=MUTED, font=FONT_TINY).pack(
            side="left", padx=(0, 2), pady=2
        )
        self.levels_entry = tk.Spinbox(
            self.topbar,
            from_=1,
            to=MAX_LEVELS,
            increment=1,
            width=5,
            textvariable=self.levels_var,
            bg=INPUT,
            fg=TEXT,
            buttonbackground=INPUT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER_LIGHT,
            highlightcolor=LINK,
            font=FONT_SMALL,
        )
        self.levels_entry.pack(side="left", padx=(0, 5), pady=4, ipady=1)
        self.levels_entry.bind("<Return>", lambda _event: self.connect())
        self.levels_entry.bind("<FocusOut>", self._levels_focus_out)

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

    def _build_depth_column(self, parent: tk.Frame) -> None:
        self._section_title(parent, "千档深度")
        parent.grid_rowconfigure(3, weight=1)
        summary = tk.Frame(parent, bg=TOP)
        summary.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 2))
        summary_top = tk.Frame(summary, bg=TOP)
        summary_top.pack(fill="x")
        for variable, color in (
            (self.depth_l2_var, LINK),
            (self.depth_levels_var, MUTED),
            (self.depth_latest_var, GOLD),
        ):
            tk.Label(
                summary_top,
                textvariable=variable,
                bg=TOP,
                fg=color,
                anchor="w",
                font=FONT_SMALL,
            ).pack(side="left", padx=(4, 10))
        summary_bottom = tk.Frame(summary, bg=TOP)
        summary_bottom.pack(fill="x")
        for variable, color in ((self.depth_buy_var, RED), (self.depth_sell_var, GREEN)):
            tk.Label(
                summary_bottom,
                textvariable=variable,
                bg=TOP,
                fg=color,
                anchor="w",
                font=FONT_SMALL,
            ).pack(side="left", padx=(4, 12))
        self.depth_head = tk.Canvas(parent, height=22, bg=TOP, highlightthickness=0, bd=0)
        self.depth_head.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4)
        self.depth_canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        depth_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.depth_canvas.yview, style="D201.Vertical.TScrollbar")
        self.depth_canvas.configure(
            yscrollcommand=lambda first, last: self._watermark_scroll_set(
                self.depth_canvas, depth_scroll, first, last
            )
        )
        self.depth_canvas.grid(row=3, column=0, sticky="nsew", padx=(4, 0))
        depth_scroll.grid(row=3, column=1, sticky="ns", padx=(0, 3))
        self.depth_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.depth_canvas.bind("<Button-4>", lambda _event: self.depth_canvas.yview_scroll(-3, "units"))
        self.depth_canvas.bind("<Button-5>", lambda _event: self.depth_canvas.yview_scroll(3, "units"))
        self.depth_canvas.bind("<Button-1>", self._depth_click)
        self.depth_canvas.bind("<Configure>", lambda _event: self.schedule_render())
        self.depth_columns = [60, 90, 80, 110]

    def _build_queue_column(self, parent: tk.Frame) -> None:
        self._section_title(parent, "价位队列")
        parent.grid_rowconfigure(3, weight=1)
        tk.Label(
            parent,
            textvariable=self.queue_summary_var,
            bg=TOP,
            fg=TEXT,
            anchor="w",
            padx=4,
            font=FONT_SMALL,
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))
        queue_head = tk.Canvas(parent, height=22, bg=TOP, highlightthickness=0, bd=0)
        queue_head.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4)
        self.queue_head = queue_head
        self.queue_canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        queue_scroll = ttk.Scrollbar(parent, orient="vertical", command=self.queue_canvas.yview, style="D201.Vertical.TScrollbar")
        self.queue_canvas.configure(
            yscrollcommand=lambda first, last: self._watermark_scroll_set(
                self.queue_canvas, queue_scroll, first, last
            )
        )
        self.queue_canvas.grid(row=3, column=0, sticky="nsew", padx=(4, 0))
        queue_scroll.grid(row=3, column=1, sticky="ns", padx=(0, 3))
        self.queue_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.queue_canvas.bind("<Button-4>", lambda _event: self.queue_canvas.yview_scroll(-3, "units"))
        self.queue_canvas.bind("<Button-5>", lambda _event: self.queue_canvas.yview_scroll(3, "units"))
        self.queue_canvas.bind("<Configure>", lambda _event: self.schedule_render())

    def _build_bigorder_column(self, parent: tk.Frame) -> None:
        parent.grid_rowconfigure(3, weight=1)
        big_title = self._section_title(parent, "大单资金")
        self.flow_titles["bigorder"] = big_title
        tk.Label(
            parent,
            textvariable=self.bigorder_summary_var,
            bg=TOP,
            fg=TEXT,
            anchor="w",
            padx=4,
            font=FONT_TINY,
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 2))
        big_head = tk.Canvas(parent, height=22, bg=TOP, highlightthickness=0, bd=0)
        big_head.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4)
        self.bigorder_head = big_head
        big_body = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        big_scroll = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=lambda *args: self._flow_scroll_command("bigorder", *args),
            style="D201.Vertical.TScrollbar",
        )
        big_body.configure(
            yscrollcommand=lambda first, last: self._flow_scroll_set("bigorder", first, last)
        )
        big_body.grid(row=3, column=0, sticky="nsew", padx=(4, 0))
        big_scroll.grid(row=3, column=1, sticky="ns", padx=(0, 3))
        self.flow_canvases["bigorder"] = big_body
        self.flow_scrollbars["bigorder"] = big_scroll
        self.flow_kind_by_widget[str(big_body)] = "bigorder"
        big_body.bind("<MouseWheel>", self._on_mousewheel)
        big_body.bind("<Button-4>", lambda _event: self._flow_wheel("bigorder", -3))
        big_body.bind("<Button-5>", lambda _event: self._flow_wheel("bigorder", 3))
        big_body.bind("<Configure>", lambda _event: self.schedule_render())
        big_scroll.bind(
            "<ButtonRelease-1>",
            lambda _event: self._arm_flow_bottom("bigorder"),
        )

    def _build_flow_column(self, parent: tk.Frame, title: str, kind: str) -> None:
        title_label = self._section_title(parent, title)
        self.flow_titles[kind] = title_label
        parent.grid_rowconfigure(3, weight=1)
        head = tk.Canvas(parent, height=22, bg=TOP, highlightthickness=0, bd=0)
        head.grid(row=1, column=0, sticky="ew", padx=4)
        body = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(
            parent,
            orient="vertical",
            command=lambda *args, flow_kind=kind: self._flow_scroll_command(flow_kind, *args),
            style="D201.Vertical.TScrollbar",
        )
        body.configure(
            yscrollcommand=lambda first, last, flow_kind=kind: self._flow_scroll_set(
                flow_kind, first, last
            )
        )
        body.grid(row=3, column=0, sticky="nsew", padx=(4, 0))
        scroll.grid(row=3, column=1, sticky="ns", padx=(0, 3))
        self.flow_canvases[kind] = body
        self.flow_scrollbars[kind] = scroll
        self.flow_kind_by_widget[str(body)] = kind
        body.bind("<MouseWheel>", self._on_mousewheel)
        body.bind("<Button-4>", lambda _event, flow_kind=kind: self._flow_wheel(flow_kind, -3))
        body.bind("<Button-5>", lambda _event, flow_kind=kind: self._flow_wheel(flow_kind, 3))
        body.bind("<Configure>", lambda _event: self.schedule_render())
        scroll.bind(
            "<ButtonRelease-1>",
            lambda _event, flow_kind=kind: self._arm_flow_bottom(flow_kind),
        )
        setattr(self, f"{kind}_head", head)
        setattr(self, f"{kind}_canvas", body)

    # ── 滚动历史 ───────────────────────────────────────────────────────

    def _reset_data(self) -> None:
        previous_tokens = getattr(self, "history_request_token", {})
        self.thousand_data: dict[str, Any] = {}
        self.queue_data: dict[str, Any] = {}
        self.logs: dict[str, list[dict[str, Any]]] = {"entrust": [], "trade": [], "bigorder": []}
        self.seen: dict[str, set[int]] = {"entrust": set(), "trade": set(), "bigorder": set()}
        self.history_loading: dict[str, bool] = {kind: False for kind in self.logs}
        self.history_exhausted: dict[str, bool] = {kind: False for kind in self.logs}
        self.history_expected_start: dict[str, int] = {kind: 0 for kind in self.logs}
        self.history_next_start: dict[str, int] = {kind: 0 for kind in self.logs}
        self.history_request_token: dict[str, int] = {
            kind: previous_tokens.get(kind, -1) + 1 for kind in self.logs
        }
        self.history_timeout_after: dict[str, Any | None] = {kind: None for kind in self.logs}
        self.flow_bottom_armed: dict[str, bool] = {kind: False for kind in self.logs}
        self.flow_keep_bottom: dict[str, bool] = {kind: False for kind in self.logs}
        self.queue_dir = "B"
        self.queue_level = 0
        self.queue_price: int | None = None
        self.depth_selected: tuple[str, int] | None = None
        self.depth_columns = [60, 90, 80, 110]
        self.depth_summary_var.set("")
        self.depth_l2_var.set("")
        self.depth_levels_var.set("")
        self.depth_latest_var.set("")
        self.depth_buy_var.set("")
        self.depth_sell_var.set("")
        self.queue_summary_var.set("")
        self.bigorder_summary_var.set("")

    def _trim_flow_log(self, kind: str) -> None:
        """保留最新记录，并同步裁剪序号去重集合。"""
        rows = self.logs[kind]
        if len(rows) <= MAX_FLOW_ROWS:
            return
        del rows[MAX_FLOW_ROWS:]
        self.seen[kind].clear()
        self.seen[kind].update(
            as_int(row.get("seq")) for row in rows if as_int(row.get("seq")) > 0
        )

    def _clear_runtime_data(self) -> None:
        for kind in self.logs:
            self._cancel_history_timeout(kind)
        self._reset_data()
        for kind in self.logs:
            self._set_flow_title(kind)
        self.schedule_render()

    def _set_flow_title(self, kind: str, status: str = "") -> None:
        title = self.flow_titles.get(kind)
        if title is None:
            return
        base = self.flow_base_titles[kind]
        title.configure(text=f"{base} · {status}" if status else base)

    def _cancel_history_timeout(self, kind: str) -> None:
        pending = self.history_timeout_after.get(kind)
        if pending is not None:
            try:
                self.root.after_cancel(pending)
            except tk.TclError:
                pass
            self.history_timeout_after[kind] = None

    def _finish_history_without_data(self, kind: str, status: str) -> None:
        """结束无响应的历史请求，并把订阅切回实时模式。"""
        self._cancel_history_timeout(kind)
        self.history_loading[kind] = False
        self.history_expected_start[kind] = 0
        self.flow_keep_bottom[kind] = False
        self._set_flow_title(kind, status)
        self._set_status(f"⚠ {self.flow_base_titles[kind]} {status}，已恢复实时", RED)
        self._resume_realtime(kind)

    def _history_request_timeout(self, kind: str, token: int) -> None:
        if self.history_request_token.get(kind) != token:
            return
        if not self.history_loading.get(kind, False):
            return
        self.history_timeout_after[kind] = None
        self._finish_history_without_data(kind, "历史超时")

    def _on_mousewheel(self, event: tk.Event) -> None:
        """标记用户滚动，再交给基类处理滚轮位移。"""
        kind = self.flow_kind_by_widget.get(str(event.widget))
        if kind:
            self.flow_bottom_armed[kind] = True
        super()._on_mousewheel(event)

    def _arm_flow_bottom(self, kind: str) -> None:
        """滚动条拖动结束后，按实际 yview 判断是否已经触底。"""
        self.flow_bottom_armed[kind] = True
        self.root.after_idle(lambda flow_kind=kind: self._flow_bottom_check(flow_kind))

    def _flow_scroll_set(self, kind: str, first: str, last: str) -> None:
        """Canvas 的真实滚动回调；滚动条到末端时只安排一次历史加载。"""
        scrollbar = self.flow_scrollbars.get(kind)
        if scrollbar is not None:
            scrollbar.set(first, last)
        canvas = self.flow_canvases.get(kind)
        if canvas is not None:
            self._reposition_watermark(canvas)
        if not self.flow_bottom_armed.get(kind, False):
            return
        try:
            at_bottom = float(last) >= BOTTOM_FRACTION
        except (TypeError, ValueError):
            at_bottom = False
        if at_bottom:
            self.root.after_idle(lambda flow_kind=kind: self._flow_bottom_check(flow_kind))

    def _flow_bottom_check(self, kind: str) -> None:
        """只在用户动作把实际滚动位置送到最底部时触发。"""
        if not self.flow_bottom_armed.get(kind, False):
            return
        canvas = self.flow_canvases.get(kind)
        if canvas is None:
            self.flow_bottom_armed[kind] = False
            return
        _first, last = canvas.yview()
        if last < BOTTOM_FRACTION:
            # 鼠标滚轮或拖动停在中间位置时，不能把这次动作遗留给下一次重绘。
            self.flow_bottom_armed[kind] = False
            return
        if self.history_loading[kind] or self.history_exhausted[kind] or not self.logs[kind]:
            self.flow_bottom_armed[kind] = False
            return
        if self.stream is None or not self.connected:
            self.flow_bottom_armed[kind] = False
            return
        self.flow_bottom_armed[kind] = False
        self._maybe_load_history(kind)

    def _flow_wheel(self, kind: str, delta: int) -> str:
        canvas = self.flow_canvases[kind]
        self.flow_bottom_armed[kind] = True
        canvas.yview_scroll(delta, "units")
        self.root.after_idle(lambda flow_kind=kind: self._flow_bottom_check(flow_kind))
        return "break"

    def _flow_scroll_command(self, kind: str, *args: str) -> None:
        """让滚动条拖动/箭头滚动和鼠标滚轮走同一套历史触发。"""
        canvas = self.flow_canvases.get(kind)
        if canvas is None:
            return
        self.flow_bottom_armed[kind] = True
        canvas.yview(*args)
        self.root.after_idle(lambda flow_kind=kind: self._flow_bottom_check(flow_kind))

    def _maybe_load_history(self, kind: str) -> None:
        canvas = self.flow_canvases.get(kind)
        if canvas is None:
            return
        first, last = canvas.yview()
        if last - first >= 0.999 or last < 0.995:
            return
        if self.history_loading[kind] or self.history_exhausted[kind] or not self.logs[kind]:
            return
        self._request_history(kind)

    def _request_history(self, kind: str) -> None:
        stream = self.stream
        if stream is None or not self.connected:
            return
        if len(self.logs[kind]) >= MAX_FLOW_ROWS:
            self.history_exhausted[kind] = True
            self._set_flow_title(kind, f"仅保留最近 {MAX_FLOW_ROWS} 条")
            return
        oldest_seq = min(
            (as_int(row.get("seq")) for row in self.logs[kind] if as_int(row.get("seq")) > 0),
            default=0,
        )
        if oldest_seq <= 1:
            self.history_exhausted[kind] = True
            self._set_flow_title(kind, "已到最早")
            return
        start_seq = self.history_next_start[kind]
        if start_seq <= 0 or start_seq >= oldest_seq:
            start_seq = max(1, oldest_seq - PAGE_SIZE + 1)
        command = {
            "type": kind,
            "code": stream.code,
            "enable": 1,
            "count": PAGE_SIZE,
            "startSeq": start_seq,
            "userParam": HISTORY_PARAMS[kind],
        }
        if kind == "entrust":
            command["filter"] = 0
        if not stream.send(command):
            return
        self.history_loading[kind] = True
        self.history_request_token[kind] += 1
        request_token = self.history_request_token[kind]
        self.history_expected_start[kind] = start_seq
        self.flow_keep_bottom[kind] = True
        self._set_flow_title(kind, "加载历史…")
        self._cancel_history_timeout(kind)
        self.history_timeout_after[kind] = self.root.after(
            HISTORY_REQUEST_TIMEOUT_MS,
            lambda flow_kind=kind, token=request_token: self._history_request_timeout(
                flow_kind, token
            ),
        )

    def _resume_realtime(self, kind: str) -> None:
        stream = self.stream
        if stream is None or not self.connected:
            return
        command = {
            "type": kind,
            "code": stream.code,
            "enable": 1,
            "count": PAGE_SIZE,
            "startSeq": 0,
            "userParam": BASE_PARAMS[kind],
        }
        if kind == "entrust":
            command["filter"] = 0
        stream.send(command)

    def _restore_flow_bottom(self, kind: str) -> None:
        canvas = self.flow_canvases.get(kind)
        if canvas is not None:
            canvas.yview_moveto(1.0)
        self.flow_keep_bottom[kind] = False

    # ── 消息处理 ───────────────────────────────────────────────────────

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
                msg = str(item.get("msg", "服务错误"))
                self._set_status("⚠ " + msg, RED)
                for flow_kind in self.logs:
                    if self.history_loading[flow_kind]:
                        self._finish_history_without_data(flow_kind, "历史失败")
                continue
            if kind == "info":
                msg = str(item.get("msg", ""))
                if msg:
                    self._set_status(msg, MUTED)
                continue
            data = item.get("data")
            if not isinstance(data, dict):
                continue
            if kind == "thousand":
                self._update_thousand(data)
                self.dirty_views.add("depth")
                dirty = True
            elif kind == "queue":
                self._update_queue(data)
                self.dirty_views.add("queue")
                dirty = True
            elif kind in self.logs:
                user_param = as_int(item.get("userParam", data.get("userParam")))
                response_start = as_int(data.get("startSeq"))
                current_oldest = min(
                    (as_int(row.get("seq")) for row in self.logs[kind] if as_int(row.get("seq")) > 0),
                    default=0,
                )
                is_history = self.history_loading[kind] and (
                    user_param == HISTORY_PARAMS[kind]
                    or (
                        response_start > 0
                        and current_oldest > 0
                        and response_start <= self.history_expected_start[kind]
                        and response_start < current_oldest
                    )
                )
                if self._update_flow(kind, data, is_history) or kind == "bigorder":
                    self.dirty_views.add(kind)
                    dirty = True
        return dirty

    def _update_thousand(self, data: dict[str, Any]) -> None:
        self.thousand_data = data
        buys = data.get("buys") if isinstance(data.get("buys"), list) else []
        sells = data.get("sells") if isinstance(data.get("sells"), list) else []
        buy_count = len(flatten_rows(buys))
        sell_count = len(flatten_rows(sells))
        l2_time = format_l2_time(data.get("l2Time"))
        latest = format_price(data.get("price", data.get("latest")))
        self.depth_l2_var.set(f"L2时间 {l2_time}")
        self.depth_levels_var.set(f"档位 买{buy_count}/卖{sell_count}")
        self.depth_latest_var.set(f"最新 {latest}")
        self.depth_buy_var.set(
            f"买 {as_int(data.get('totalBuyVol'))}手/{format_wan(data.get('totalBuyAmt'))}"
        )
        self.depth_sell_var.set(
            f"卖 {as_int(data.get('totalSellVol'))}手/{format_wan(data.get('totalSellAmt'))}"
        )
        # 保留完整文本状态，便于离线测试或其它调用方读取；界面使用上面的彩色分段标签。
        self.depth_summary_var.set(
            f"L2时间 {l2_time}  档位 买{buy_count}/卖{sell_count}  最新 {latest}\n"
            f"{self.depth_buy_var.get()}  {self.depth_sell_var.get()}"
        )

    def _update_queue(self, data: dict[str, Any]) -> None:
        direction = str(data.get("dir", self.queue_dir)).upper()
        if direction not in {"B", "S"}:
            direction = self.queue_dir
        self.queue_dir = direction
        self.queue_level = as_int(data.get("level"), self.queue_level)
        response_price = data.get("p", data.get("price"))
        if response_price not in (None, "") and as_int(response_price) > 0:
            self.queue_price = as_int(response_price)
        self.queue_data = data
        label = "买" if direction == "B" else "卖"
        volumes = data.get("volumes") if isinstance(data.get("volumes"), list) else []
        price_text = format_price(self.queue_price) if self.queue_price else "--"
        self.queue_summary_var.set(
            f"{label}{self.queue_level + 1}  {price_text}  总量 {as_int(data.get('totalCount'))}股  明细 {len(volumes)}笔"
        )

    def _update_flow(self, kind: str, data: dict[str, Any], history: bool = False) -> int:
        rows = flatten_rows(data.get("rows"))
        was_empty = not self.logs[kind]
        fresh: list[dict[str, Any]] = []
        for row in rows:
            seq = as_int(row.get("seq"))
            if seq > 0:
                if seq in self.seen[kind]:
                    continue
                self.seen[kind].add(seq)
            fresh.append(row)
        fresh.sort(key=lambda row: (as_int(row.get("seq")), as_int(row.get("t"))), reverse=True)
        if history:
            self.logs[kind].extend(fresh)
            self._trim_flow_log(kind)
            self._cancel_history_timeout(kind)
            self.history_loading[kind] = False
            expected = self.history_expected_start[kind]
            self.history_expected_start[kind] = 0
            response_start = as_int(data.get("startSeq"), expected)
            actual_count = len(rows)
            next_start = max(1, response_start - actual_count + 1) if actual_count else 0
            self.history_next_start[kind] = next_start
            if len(self.logs[kind]) >= MAX_FLOW_ROWS:
                self.history_exhausted[kind] = True
                self._set_flow_title(kind, f"仅保留最近 {MAX_FLOW_ROWS} 条")
            elif not rows or response_start <= 1 or actual_count < PAGE_SIZE:
                self.history_exhausted[kind] = True
                self._set_flow_title(kind, "已到最早")
            else:
                self._set_flow_title(kind)
            self.root.after(80, lambda flow_kind=kind: self._resume_realtime(flow_kind))
        else:
            self.logs[kind][0:0] = fresh
            if was_empty and rows:
                response_start = as_int(data.get("startSeq"))
                if response_start > 0:
                    self.history_next_start[kind] = max(1, response_start - len(rows) + 1)

        self.logs[kind].sort(
            key=lambda row: (as_int(row.get("seq")), as_int(row.get("t"))),
            reverse=True,
        )
        self._trim_flow_log(kind)

        if kind == "bigorder":
            self.bigorder_summary_var.set(
                f"主买 {format_wan(data.get('activeBuy'))}  被买 {format_wan(data.get('passiveBuy'))}"
                f"  主卖 {format_wan(data.get('activeSell'))}  被卖 {format_wan(data.get('passiveSell'))}"
            )
        return len(fresh)

    # ── 渲染 ───────────────────────────────────────────────────────────

    @staticmethod
    def _fit_columns(width: int, base: list[int]) -> list[int]:
        width = max(265, width)
        total = sum(base)
        if width >= total:
            result = list(base)
            result[-1] += width - total
            return result
        scale = width / total
        result = [max(28, int(value * scale)) for value in base]
        result[-1] += width - sum(result)
        return result

    @staticmethod
    def _draw_header(canvas: tk.Canvas, columns: list[int], labels: list[str]) -> None:
        canvas.delete("all")
        x = 0
        for index, (column, label) in enumerate(zip(columns, labels)):
            anchor = "center" if index == 0 or label in {"方向", "主动"} else "w"
            tx = x + column / 2 if anchor == "center" else x + 4
            canvas.create_text(tx, 3, text=label, anchor="n" if anchor == "center" else "nw", fill=MUTED, font=FONT_TINY)
            x += column

    def _render_depth(self) -> None:
        width = max(265, self.depth_canvas.winfo_width())
        columns = self._fit_columns(width, [60, 90, 80, 110])
        self.depth_columns = columns
        self._draw_header(self.depth_head, columns, ["档位", "价位", "手数", "金额"])
        self.depth_canvas.delete("all")
        self._draw_watermark(self.depth_canvas, width, self.depth_canvas.winfo_height())
        buys = flatten_rows(self.thousand_data.get("buys"))
        sells = flatten_rows(self.thousand_data.get("sells"))
        sell_rows = sorted(
            (row for row in sells if isinstance(row, dict)),
            key=lambda row: as_int(row.get("p")),
            reverse=True,
        )
        buy_rows = sorted(
            (row for row in buys if isinstance(row, dict)),
            key=lambda row: as_int(row.get("p")),
            reverse=True,
        )
        depth_rows = [
            ("S", len(sell_rows) - index, row)
            for index, row in enumerate(sell_rows)
        ] + [
            ("B", index + 1, row)
            for index, row in enumerate(buy_rows)
        ]
        y = 2
        for index, (direction, level, row) in enumerate(depth_rows):
            color = GREEN if direction == "S" else RED
            selected = self.depth_selected == (direction, as_int(row.get("p")))
            if selected:
                self.depth_canvas.create_rectangle(
                    1,
                    y,
                    width - 1,
                    y + 19,
                    fill="#263b55",
                    outline=GOLD,
                    width=1,
                )
            values = [
                f"{'卖' if direction == 'S' else '买'}{level}",
                format_price(row.get("p")),
                str(as_int(row.get("v"))),
                format_wan(as_int(row.get("p")) * as_int(row.get("v")) / 10000),
            ]
            colors = [color, color, color, GOLD]
            x = 0
            for col_index, (column, value) in enumerate(zip(columns, values)):
                anchor = "center" if col_index == 0 else "e"
                tx = x + column / 2 if anchor == "center" else x + column - 4
                self.depth_canvas.create_text(
                    tx,
                    y + 2,
                    text=value,
                    anchor="n" if anchor == "center" else "ne",
                    fill=colors[col_index],
                    font=FONT_SMALL,
                )
                x += column
            separator_color = GOLD if index == len(sell_rows) - 1 and buy_rows else INPUT
            self.depth_canvas.create_line(0, y + 19, width, y + 19, fill=separator_color)
            y += 20
        if not depth_rows:
            self.depth_canvas.create_text(width / 2, 70, text="等待千档数据...", anchor="center", fill="#526d88", font=FONT_SMALL)
        self.depth_canvas.configure(scrollregion=(0, 0, width, max(y + 5, self.depth_canvas.winfo_height())))

    def _depth_click(self, event: tk.Event) -> None:
        y = self.depth_canvas.canvasy(event.y)
        index = int((y - 2) // 20)
        if index < 0:
            return
        buys = flatten_rows(self.thousand_data.get("buys"))
        sells = flatten_rows(self.thousand_data.get("sells"))
        sell_rows = sorted(
            (row for row in sells if isinstance(row, dict)),
            key=lambda row: as_int(row.get("p")),
            reverse=True,
        )
        buy_rows = sorted(
            (row for row in buys if isinstance(row, dict)),
            key=lambda row: as_int(row.get("p")),
            reverse=True,
        )
        if index < len(sell_rows):
            row = sell_rows[index]
            self._request_queue("S", len(sell_rows) - index - 1, as_int(row.get("p")))
        else:
            buy_index = index - len(sell_rows)
            if buy_index < len(buy_rows):
                row = buy_rows[buy_index]
                self._request_queue("B", buy_index, as_int(row.get("p")))

    def _request_queue(self, direction: str, level: int, price: int | None = None) -> None:
        direction = "S" if str(direction).upper() == "S" else "B"
        self.queue_dir = direction
        self.queue_level = level
        if price is not None and price > 0:
            self.queue_price = price
            self.depth_selected = (direction, price)
        label = "买" if direction == "B" else "卖"
        price_text = format_price(self.queue_price) if self.queue_price else "--"
        self.queue_summary_var.set(f"{label}{level + 1}  {price_text}  请求中...")
        self.schedule_render("depth", "queue")
        stream = self.stream
        if stream is None or not self.connected:
            return
        stream.send(
            {
                "type": "queue",
                "code": stream.code,
                "enable": 1,
                "dir": direction,
                "level": level,
                "userParam": QUEUE_PARAMS[direction],
            }
        )

    def _render_queue(self) -> None:
        width = max(265, self.queue_canvas.winfo_width())
        columns = self._fit_columns(width, [48, 82, 110])
        self._draw_header(self.queue_head, columns, ["#", "股数", "金额"])
        self.queue_canvas.delete("all")
        self._draw_watermark(self.queue_canvas, width, self.queue_canvas.winfo_height())
        volumes = self.queue_data.get("volumes", []) if isinstance(self.queue_data.get("volumes"), list) else []
        y = 2
        for index, value in enumerate(volumes):
            self.queue_canvas.create_text(columns[0] / 2, y + 2, text=str(index + 1), anchor="n", fill=MUTED, font=FONT_SMALL)
            volume = as_int(value)
            volume_color = RED if self.queue_dir == "B" else GREEN
            self.queue_canvas.create_text(
                columns[0] + columns[1] - 4,
                y + 2,
                text=str(volume),
                anchor="ne",
                fill=volume_color,
                font=FONT_SMALL,
            )
            amount = (
                format_wan(self.queue_price * volume / QUEUE_AMOUNT_DIVISOR)
                if self.queue_price
                else "—"
            )
            self.queue_canvas.create_text(
                sum(columns) - 4,
                y + 2,
                text=amount,
                anchor="ne",
                fill=GOLD,
                font=FONT_SMALL,
            )
            self.queue_canvas.create_line(0, y + 19, width, y + 19, fill=INPUT)
            y += 20
        if not volumes:
            self.queue_canvas.create_text(width / 2, 70, text="点击千档任一价位查看队列", anchor="center", fill="#526d88", font=FONT_SMALL)
        self.queue_canvas.configure(scrollregion=(0, 0, width, max(y + 5, self.queue_canvas.winfo_height())))

    def _flow_columns(self, kind: str, width: int) -> tuple[list[int], list[str]]:
        # seq 仍保留在内部记录中用于去重、排序和翻页游标；这里只隐藏可见列。
        if kind == "entrust":
            return self._fit_columns(width, [82, 72, 108, 55]), ["时间", "价", "量(额)", "方向"]
        if kind == "trade":
            return self._fit_columns(width, [92, 68, 128, 128, 142]), ["时间", "价", "买(手/万)", "卖(手/万)", "成交(手/万)"]
        return self._fit_columns(width, [84, 48, 48, 56, 44, 48]), ["时间", "均价", "量", "金额", "方向", "主动"]

    def _render_flow(self, kind: str) -> None:
        head = getattr(self, f"{kind}_head", None)
        canvas = self.flow_canvases[kind]
        width = max(265, canvas.winfo_width())
        columns, labels = self._flow_columns(kind, width)
        self._draw_header(head, columns, labels)
        canvas.delete("all")
        self._draw_watermark(canvas, width, canvas.winfo_height())
        rows = self.logs[kind]
        y = 2
        if kind == "trade":
            self._render_trade_rows(canvas, width, columns, rows)
        else:
            for row in rows:
                values, colors = self._flow_row_values(kind, row)
                self._draw_flow_row(canvas, columns, y, values, colors)
                y += 20
        if not rows:
            empty = {
                "entrust": "等待委托数据...",
                "trade": "等待成交数据...",
                "bigorder": "等待大单数据...",
            }[kind]
            canvas.create_text(width / 2, max(60, canvas.winfo_height() / 2), text=empty, anchor="center", fill="#526d88", font=FONT_SMALL)
        else:
            y = 2 + len(rows) * 20
        canvas.configure(scrollregion=(0, 0, width, max(y + 5, canvas.winfo_height())))
        if self.flow_keep_bottom.get(kind):
            self.root.after_idle(lambda flow_kind=kind: self._restore_flow_bottom(flow_kind))

    def _flow_row_values(self, kind: str, row: dict[str, Any]) -> tuple[list[str], list[str]]:
        direction, direction_color = side_label(row.get("d"))
        if kind == "entrust":
            volume = as_int(row.get("v"))
            amount = row.get("amt", row.get("amount"))
            if amount in (None, ""):
                amount = as_int(row.get("p")) * volume / 10000
            return (
                [format_time(row.get("t")), format_price(row.get("p")), f"{volume}({format_wan(amount)})", direction],
                [MUTED, direction_color, direction_color, direction_color],
            )
        active = "主动" if as_int(row.get("act")) else "被动"
        return (
            [
                format_time(row.get("t")),
                format_price(row.get("avgP")),
                str(as_int(row.get("v"))),
                format_wan(row.get("amt")),
                direction,
                active,
            ],
            [MUTED, TEXT, GOLD if as_int(row.get("v")) >= 100 else TEXT, GOLD, direction_color, GOLD if as_int(row.get("act")) else MUTED],
        )

    @staticmethod
    def _trade_leg_text(price: Any, volume: Any) -> str:
        """成交表只显示手/额；买卖委托号只留给外圈分组逻辑。"""
        volume_int = as_int(volume)
        amount_wan = as_int(price) * volume_int / 10000
        return f"{volume_int}({format_wan(amount_wan)})"

    @staticmethod
    def _draw_flow_row(canvas: tk.Canvas, columns: list[int], y: int, values: list[str], colors: list[str]) -> None:
        x = 0
        for index, (column, value) in enumerate(zip(columns, values)):
            anchor = "center" if index == len(values) - 1 else "e"
            tx = x + column / 2 if anchor == "center" else x + column - 4
            canvas.create_text(
                tx,
                y + 2,
                text=value,
                anchor="n" if anchor == "center" else "ne",
                fill=colors[index],
                font=FONT_SMALL,
            )
            x += column
        canvas.create_line(0, y + 19, x, y + 19, fill=INPUT)

    def _render_trade_rows(self, canvas: tk.Canvas, width: int, columns: list[int], rows: list[dict[str, Any]]) -> None:
        buy_groups = self._group_ranges(rows, "buyer")
        sell_groups = self._group_ranges(rows, "seller")
        buy_rows = {index for start, end in buy_groups for index in range(start, end + 1)}
        sell_rows = {index for start, end in sell_groups for index in range(start, end + 1)}
        buy_x1 = sum(columns[:2])
        buy_x2 = buy_x1 + columns[2]
        sell_x1 = buy_x2
        sell_x2 = sell_x1 + columns[3]

        for index, row in enumerate(rows):
            volume = as_int(row.get("v"))
            values = [
                format_time(row.get("t")),
                format_price(row.get("p")),
                self._trade_leg_text(row.get("p"), row.get("buyVol")),
                self._trade_leg_text(row.get("p"), row.get("sellVol")),
                self._trade_leg_text(row.get("p"), volume),
            ]
            colors = [MUTED, TEXT, RED, GREEN, GOLD if volume >= 100 else TEXT]
            self._draw_flow_row_without_separator(canvas, columns, 2 + index * 20, values, colors, buy_rows, sell_rows, buy_x1, buy_x2, sell_x1, sell_x2)

        for start, end in buy_groups:
            canvas.create_rectangle(buy_x1 + 1, 3 + start * 20, buy_x2 - 1, 2 + (end + 1) * 20 - 1, outline=GOLD, dash=(3, 2), width=1)
        for start, end in sell_groups:
            canvas.create_rectangle(sell_x1 + 1, 3 + start * 20, sell_x2 - 1, 2 + (end + 1) * 20 - 1, outline=BLUE, dash=(3, 2), width=1)

    @staticmethod
    def _group_ranges(rows: list[dict[str, Any]], field: str) -> list[tuple[int, int]]:
        groups: list[tuple[int, int]] = []
        index = 0
        while index < len(rows):
            value = as_int(rows[index].get(field))
            end = index
            if value:
                while end + 1 < len(rows) and as_int(rows[end + 1].get(field)) == value:
                    end += 1
                if end > index:
                    groups.append((index, end))
            index = end + 1
        return groups

    @staticmethod
    def _draw_flow_row_without_separator(
        canvas: tk.Canvas,
        columns: list[int],
        y: int,
        values: list[str],
        colors: list[str],
        buy_rows: set[int],
        sell_rows: set[int],
        buy_x1: int,
        buy_x2: int,
        sell_x1: int,
        sell_x2: int,
    ) -> None:
        x = 0
        for index, (column, value) in enumerate(zip(columns, values)):
            anchor = "e"
            tx = x + column / 2 if anchor == "center" else x + column - 4
            canvas.create_text(tx, y + 2, text=value, anchor="n" if anchor == "center" else "ne", fill=colors[index], font=FONT_SMALL)
            x += column
        blocked: list[tuple[int, int]] = []
        row_index = (y - 2) // 20
        if row_index in buy_rows:
            blocked.append((buy_x1, buy_x2))
        if row_index in sell_rows:
            blocked.append((sell_x1, sell_x2))
        cursor = 0
        for start, end in blocked:
            if start > cursor:
                canvas.create_line(cursor, y + 19, start, y + 19, fill=INPUT)
            cursor = max(cursor, end)
        if cursor < x:
            canvas.create_line(cursor, y + 19, x, y + 19, fill=INPUT)

    def _refresh_views(self) -> None:
        self.render_pending = False
        views = self.dirty_views
        self.dirty_views = set()
        if "depth" in views:
            self._render_depth()
        if "queue" in views:
            self._render_queue()
        if "entrust" in views:
            self._render_flow("entrust")
        if "bigorder" in views:
            self._render_flow("bigorder")
        if "trade" in views:
            self._render_flow("trade")

    # ── 连接控制 ───────────────────────────────────────────────────────

    def _levels_focus_out(self, _event: tk.Event) -> None:
        self.levels_var.set(str(normalize_levels(self.levels_var.get())))

    def _set_connection_state(self, state: str) -> None:
        super()._set_connection_state(state)
        if state != "closed":
            return
        for kind in getattr(self, "logs", {}):
            if not self.history_loading.get(kind, False):
                continue
            self._cancel_history_timeout(kind)
            self.history_loading[kind] = False
            self.history_expected_start[kind] = 0
            self.flow_keep_bottom[kind] = False
            self._set_flow_title(kind)

    def connect(self) -> None:
        code = self.code_var.get().strip().upper()
        self.code_var.set(code)
        if not re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", code):
            self._set_status("⚠ 代码格式应为 SH/SZ/BJ + 6 位数字", RED)
            return
        levels = normalize_levels(self.levels_var.get())
        self.levels_var.set(str(levels))
        self.disconnect(silent=True)
        self._clear_runtime_data()
        self.message_count = 0
        self.started_at = time.monotonic()
        self.message_var.set("0")
        self.rate_var.set("0")
        self.last_error = ""
        stream = D202Stream(self.url, code, self.events, levels)
        self.stream = stream
        self.connecting = True
        self.connected = False
        self._set_status("连接中...", MUTED)
        self.connect_button.configure(text="连接中...", state="disabled", bg="#1a2a4a", fg=LINK)
        self.disconnect_button.configure(state="normal")
        stream.start()

    def disconnect(self, silent: bool = False) -> None:
        for kind in getattr(self, "logs", {}):
            self._cancel_history_timeout(kind)
            self.history_loading[kind] = False
            self.history_expected_start[kind] = 0
            self.flow_keep_bottom[kind] = False
            self._set_flow_title(kind)
        stream = self.stream
        if stream is not None:
            disable = [
                {"type": command["type"], "code": command["code"], "enable": 0}
                for command in stream.base_commands
            ]
            stream._send_now(disable)
            stream.stop()
        self.stream = None
        self.connected = False
        self.connecting = False
        self.connect_button.configure(text="连接", state="normal", bg="#1a4a2e", fg="#aaddaa")
        self.disconnect_button.configure(state="disabled")
        if not silent:
            self._set_status("已断开", MUTED)

    def close(self) -> None:
        self.disconnect(silent=True)
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="d202 Tkinter 实时盘口大屏")
    parser.add_argument("--url", default=URL, help=f"WebSocket 地址，默认 {URL}")
    parser.add_argument("--code", default=DEFAULT_CODE, help=f"股票代码，默认 {DEFAULT_CODE}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = tk.Tk()
    D202Gui(root, args.url, args.code)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
