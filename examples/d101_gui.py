#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""d101 用户侧实时行情大屏（Tkinter）。

这是一个只依赖 Tkinter 和 ``websocket-client`` 的用户侧测试面板：

* 通过本地 ``ws://127.0.0.1:8080/d101`` 订阅实时行情；
* 支持行情全推和盘口异动两个独立 TAB；
* 行情 TAB 支持 ``universe`` 全市场订阅和 ``limit=0`` 全量推送；
* 盘口异动 TAB 按时间/序号去重排序，滚动到底部自动用游标拼接更早历史；
* 行情字段支持“省带宽基础 / 常用 / 自定义 / 全部 203”四种请求方案；
* 默认只请求基础原始字段，确定性指标在客户端计算，不把全字段当默认值；
* 按 ``code`` 合并增量行情，处理 null、缺失字段和单位换算；
* 每个 TAB 用独立的窗口化 Treeview 表格实时更新，并支持横向查看全部字段；
* 全量数据保存在客户端缓存，表格只渲染可见行；高频变化按约 50ms 合并绘制，避免界面被重绘拖住；
* 所有网络接收都在后台线程，Tkinter 主线程只负责绘制和交互。

运行：

    python d101_gui.py
    python d101_gui.py --url ws://127.0.0.1:8080/d101

依赖：

    python -m pip install websocket-client

先启动本地数据接口程序并完成登录，再点击面板右上角的“连接”。

给 AI agent 的重要提示：不要为了“字段齐全”直接请求全部 203 个字段。先按
任务选择最小字段集合；最新价、昨收价、最高价、最低价、均价等基础值已经收到时，
 涨跌幅、涨跌额、振幅、成交额和现价均价差可在代码侧计算。只有确实需要
服务端原始值或做字段对照时，才选择“全部 203 字段（单命令）”。
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import math
import queue
import re
import sys
import threading
import time
import tkinter as tk
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from privacy_display import display_name, is_name_field

try:
    import websocket
except ImportError:  # pragma: no cover - 运行时给出更友好的 GUI 提示
    websocket = None  # type: ignore[assignment]


def websocket_install_hint() -> str:
    return f'当前 Python：{sys.executable}\n请执行："{sys.executable}" -m pip install websocket-client'


# ── 视觉系统 ────────────────────────────────────────────────────────────────

BG = "#070b14"
BG_2 = "#0a1220"
SURFACE = "#101a2a"
SURFACE_2 = "#14243a"
SURFACE_3 = "#0c1524"
INPUT = "#0b1524"
BORDER = "#203650"
BORDER_BRIGHT = "#315375"
TEXT = "#edf6ff"
TEXT_SOFT = "#b5c8df"
MUTED = "#7289a4"
CYAN = "#43d9ff"
CYAN_DARK = "#123f56"
PURPLE = "#a38bff"
PINK = "#ff5c85"
UP = "#ff5c72"  # A股界面约定：上涨为红色
DOWN = "#36d399"
FLAT = "#92a4ba"
AMBER = "#ffc857"
WHITE = "#ffffff"

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_MONO = ("Consolas", 10)
FONT_MONO_SMALL = ("Consolas", 9)
FONT_WATERMARK = ("Microsoft YaHei UI", 24, "bold")

MODE_INFO = {
    "snapshot": ("行情全推", "全市场或自定义标的快照", CYAN),
    "market_event": ("盘口异动", "市场异动事件流", AMBER),
}

UNIVERSE_OPTIONS = {
    "沪深京 A股 · 全市场": "cn_hsj_stock",
    "沪深 A股 · 全市场": "cn_hs_stock",
    "上海 A股 · 全市场": "cn_sh_stock",
    "深圳 A股 · 全市场": "cn_sz_stock",
    "北交所股票 · 全市场": "cn_bse_stock",
    "科创板股票 · 全市场": "cn_star_stock",
    "上海 B 股 · 全市场": "cn_sh_b_stock",
    "深圳 B 股 · 全市场": "cn_sz_b_stock",
    "沪深指数 · 全市场": "cn_index",
    "沪深基金（ETF/LOF/REIT）· 全市场": "cn_fund",
    "上海基金 · 全市场": "cn_sh_fund",
    "深圳基金 · 全市场": "cn_sz_fund",
    "REIT · 全市场": "cn_reit",
    "上海债券 · 全市场": "cn_sh_bond",
    "深圳债券 · 全市场": "cn_sz_bond",
    "期权 · 全市场": "cn_option",
    "ETF 期权 · 全市场": "cn_etf_option",
    "期权认购 · 全市场": "cn_option_call",
    "期权认沽 · 全市场": "cn_option_put",
    "中金所股指期货 · 当前合约": "cn_cffex_index_futures",
    "中金所国债期货 · 当前合约": "cn_cffex_treasury_futures",
    "中金所期货 · 当前合约": "cn_cffex_futures",
}

TABLE_FALLBACK_COLUMNS = {
    "snapshot": [
        "__kind",
        "code",
        "name",
        "price",
        "change_pct",
        "change_amt",
        "amplitude",
        "high",
        "low",
        "pre_close",
        "open_price",
        "avg_price",
        "price_avg_diff",
        "volume",
        "tick_vol",
        "buy_sell_flag",
        "amount",
        "turnover_ratio",
        "volume_ratio",
        "industry_name",
        "__updated",
    ],
    "market_event": [
        "__kind",
        "pk_time",
        "pk_name",
        "code",
        "pk_type_name",
        "pk_value",
        "pk_detail",
        "__updated",
    ],
}

TABLE_HEADINGS = {
    "__kind": "推送类型",
    "__updated": "最近更新",
    "code": "代码",
    "name": "名称",
    "price": "最新价",
    "change_pct": "涨跌幅",
    "change_amt": "涨跌额",
    "high": "最高",
    "low": "最低",
    "pre_close": "昨收",
    "open_price": "今开",
    "avg_price": "均价",
    "close": "收盘",
    "volume": "成交量",
    "tick_vol": "现手",
    "buy_sell_flag": "现手方向(0无/1卖/2买/3未知/4竞价)",
    "amount": "成交额",
    "turnover_ratio": "换手率",
    "volume_ratio": "量比",
    "industry_name": "行业",
    "date": "日期",
    "time": "时间",
    "type_name": "事件名称",
    "info": "事件说明",
    "pk_time": "时间",
    "pk_name": "股票名称",
    "pk_type_name": "异动类型",
    "pk_value": "关键值",
    "pk_detail": "指标拆解",
}

CURRENT_VOLUME_FLAG_LABELS = {
    0: "无方向",
    1: "卖",
    2: "买",
    3: "未知",
    4: "竞价",
}

QUOTE_FIELDS = [
    "code",
    "name",
    "price",
    "high",
    "low",
    "pre_close",
    "open_price",
    "avg_price",
    "volume",
    "tick_vol",
    "buy_sell_flag",
    "amount",
    "change_pct",
    "change_amt",
    "turnover_ratio",
    "amplitude",
    "volume_ratio",
    "real_turnover_ratio",
    "bid1_price",
    "bid1_vol",
    "ask1_price",
    "ask1_vol",
    "inner_vol",
    "outer_vol",
    "inner_outer_ratio",
    "order_buy_volume",
    "order_sell_volume",
    "order_buy_sell_diff",
    "limit_up_price",
    "limit_down_price",
    "market_value",
    "float_market_value",
    "industry_name",
    "total_share",
    "float_share",
    "free_float_market_share",
    "prev_day_change_pct",
    "prev_day_volume",
    "high_60d",
    "auction_unmatched_volume",
    "first_limit_time",
    "last_limit_time",
    "limit_up_days_legacy",
    "limit_up_open_count",
    "yearly_limit_up_days",
    "net_inflow",
    "increase_rate_1min",
    "increase_rate_2min",
    "increase_rate_3min",
    "increase_rate_4min",
    "increase_rate_5min",
    "change_pct_5d",
    "turnover_ratio_6d",
]

# decimal_num/display_decimal_num 是价格字段的行内元数据，只参与换算或
# 展示精度控制，不作为行情表格列显示。
QUOTE_REQUEST_FIELDS = [*QUOTE_FIELDS, "decimal_num", "display_decimal_num"]


# D101 请求字段目录优先从同目录的用户文档读取。这样 JSON 键和中文语义只
# 维护一份，用户在“字段设置”里看到的列名会与文档保持一致。
# 脚本被单独复制出去时，仍保留一个最小回退；在完整示例目录中运行时应当
# 始终读取到完整的 203 字段目录。
FIELD_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|")


def normalize_field_search_text(value: Any) -> str:
    """统一中英文、全半角和分隔符，避免输入格式导致字段漏匹配。"""

    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(
        char
        for char in normalized
        if char.isalnum() or "\u3400" <= char <= "\u9fff"
    )


def field_search_matches(query: str, key: str, meaning: str) -> bool:
    """支持连续匹配、分词匹配和中文顺序匹配。"""

    compact_query = normalize_field_search_text(query)
    if not compact_query:
        return True
    haystack = normalize_field_search_text(f"{key} {meaning}")
    if compact_query in haystack:
        return True

    # 例如“涨速 1 分钟”与“1分钟涨速”按词匹配，输入顺序不同也能找到。
    tokens = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", compact_query)
    if tokens and all(token in haystack for token in tokens):
        return True

    # 中文短语中可能夹有“成交”等修饰词；保留查询字符顺序可避免漏掉
    # “现手方向”这类用户自然输入，同时不把单字符查询放大成全表命中。
    if len(compact_query) >= 2:
        cursor = iter(haystack)
        if all(any(char == candidate for candidate in cursor) for char in compact_query):
            return True
    return False


def _load_d101_field_catalog() -> tuple[tuple[str, str], ...]:
    candidates = (
        Path(__file__).resolve().parents[1] / "doc" / "user" / "d101_fields.md",
        Path.cwd() / "apps" / "data_interface" / "doc" / "user" / "d101_fields.md",
    )
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        catalog: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        in_catalog_table = False
        for line in lines:
            if line.startswith("| JSON 字段 |"):
                in_catalog_table = True
                continue
            if not in_catalog_table:
                continue
            if not line.startswith("|"):
                if catalog:
                    break
                continue
            match = FIELD_ROW_RE.match(line)
            if not match:
                continue
            key = match.group(1).strip()
            meaning = match.group(2).strip()
            if key in seen_keys or not key or not meaning:
                continue
            seen_keys.add(key)
            catalog.append((key, meaning))
        if len(catalog) == 203:
            return tuple(catalog)

    # Standalone fallback for the common columns. The full example set is
    # expected to use the documented 203-entry catalog above.
    fallback = {
        key: TABLE_HEADINGS.get(key, key.replace("_", " "))
        for key in {"code", "name", *QUOTE_FIELDS, "decimal_num", "display_decimal_num"}
    }
    return tuple((key, fallback[key]) for key in fallback)


D101_FIELD_CATALOG = _load_d101_field_catalog()
D101_FIELD_KEYS = tuple(key for key, _meaning in D101_FIELD_CATALOG)
D101_FIELD_LABELS = {key: meaning for key, meaning in D101_FIELD_CATALOG}
TABLE_HEADINGS.update(D101_FIELD_LABELS)


# 这些指标能由已请求的基础字段在本地稳定计算。它们默认只在 GUI 中
# 计算，不再为了显示重复向服务端请求；“全部 203 字段”仍会明确请求它们
# 的原始值，便于做原始数据对照。使用 tuple 保持字段提示顺序稳定。
LOCAL_COMPUTED_FIELDS = (
    "change_pct",
    "change_amt",
    "amplitude",
    "price_avg_diff",
    "amount",
    "body_change_pct",
    "open_pre_ratio",
    "this_month_pct",
    "this_year_pct",
    "change_pct_20d",
    "change_pct_recent_year",
    "change_pct_5d",
    "turnover_ratio",
    "real_turnover_ratio",
    "inner_outer_ratio",
    "order_buy_sell_diff",
)

# 推荐的省带宽默认请求：服务器只在字段变化时推送，因此默认集合优先保留
# 身份、精度、日内/历史参考基线、品种单位元数据，以及最新价、最高/最低价、
# 均价、成交量这些真正需要随行情变化的原始值。成交额、涨跌类指标在客户端
# 计算；现手、买卖方向和盘口是高频字段，按需再选。AI agent 不应把
# QUOTE_REQUEST_FIELDS 或 D101_FIELD_KEYS 直接作为默认请求列表。
BANDWIDTH_REQUEST_FIELDS = [
    "code",
    "name",
    "decimal_num",
    "display_decimal_num",
    "price",
    "pre_close",
    "high",
    "low",
    "open_price",
    "avg_price",
    "volume",
    "net_inflow",
    "float_share",
    "free_float_market_share",
    "last_month_price",
    "last_year_price",
    "prev_19_price",
    "prev_249_price",
    "prev4_price",
    "limit_up_price",
    "limit_down_price",
    "high_all_time",
    "high_60d",
    "volume_unit_flag",
    "stock_type",
    "contract_type",
    "trade_date",
    "market",
]

COMMON_REQUEST_FIELDS = [
    key for key in QUOTE_REQUEST_FIELDS if key not in LOCAL_COMPUTED_FIELDS
]

FIELD_PROFILE_LABELS = {
    "bandwidth": "省带宽·基础行情（推荐）",
    "common": "常用行情·统计字段",
    "custom": "自定义字段",
    "all": "全部 203 字段（单命令）",
}
FIELD_PROFILE_VALUES = tuple(FIELD_PROFILE_LABELS.values())
MAX_FIELDS_PER_COMMAND = 255  # 公共单命令上限；当前正式字段目录为 203 个
MAX_CODES_PER_CONNECTION = 6000

# AI agent note: keep every received row in rows_by_mode, but never create one
# Tk Treeview item per row.  The table paints only the visible window plus a
# small buffer.  The two clocks are deliberately separate: ingest promptly,
# then coalesce intermediate states into one inexpensive screen paint.  This
# drops only intermediate paints, never received messages or cached values.
QUEUE_DRAIN_INTERVAL_MS = 20
UI_REFRESH_INTERVAL_MS = 50
HORIZONTAL_SCROLL_COALESCE_MS = 32
VIRTUAL_TABLE_BUFFER_ROWS = 4
TABLE_ROW_HEIGHT_FALLBACK = 26
TABLE_HEADING_HEIGHT = 30

LOCAL_COMPUTED_NOTES = {
    "change_pct": "涨跌幅 = (最新价 - 昨收价) / 昨收价",
    "change_amt": "涨跌额 = 最新价 - 昨收价",
    "amplitude": "振幅 = (最高价 - 最低价) / 昨收价",
    "price_avg_diff": "现价与均价差 = 最新价 - 均价",
    "body_change_pct": "实体涨幅 = (最新价 - 今开价) / 今开价",
    "open_pre_ratio": "开盘/昨收比 = 今开价 / 昨收价",
    "this_month_pct": "本月涨幅 = (最新价 - 上月参考价) / 上月参考价",
    "this_year_pct": "本年涨幅 = (最新价 - 上年参考价) / 上年参考价",
    "change_pct_20d": "20 日涨幅 = (最新价 - 前 19 日参考价) / 前 19 日参考价",
    "change_pct_recent_year": "近一年涨幅 = (最新价 - 前 249 日参考价) / 前 249 日参考价",
    "change_pct_5d": "5 日涨幅 = (最新价 - 前 4 日参考价) / 前 4 日参考价",
    "amount": "成交额 ≈ 成交量 × 均价（先还原价格，再按品种成交单位换算）",
    "turnover_ratio": "换手率 = 成交量 / 流通股本（按资产成交单位换算）",
    "real_turnover_ratio": "实际换手率 = 成交量 / 自由流通股本（按资产成交单位换算）",
    "inner_outer_ratio": "内外盘比 = 内盘累计量 / 外盘累计量",
    "order_buy_sell_diff": "委差 = 委买量 - 委卖量",
}

# 自定义字段模式中如果用户勾选了某个本地派生字段，自动补入它的原始
# 依赖字段；默认模式则只发送 BANDWIDTH_REQUEST_FIELDS，避免为了可选指标
# 把高频内外盘/委托量带进来。
LOCAL_FIELD_DEPENDENCIES = {
    "change_pct": ("price", "pre_close"),
    "change_amt": ("price", "pre_close"),
    "amplitude": ("high", "low", "pre_close"),
    "price_avg_diff": ("price", "avg_price"),
    "amount": ("avg_price", "volume", "decimal_num", "volume_unit_flag"),
    "body_change_pct": ("price", "open_price"),
    "open_pre_ratio": ("open_price", "pre_close"),
    "this_month_pct": ("price", "last_month_price"),
    "this_year_pct": ("price", "last_year_price"),
    "change_pct_20d": ("price", "prev_19_price"),
    "change_pct_recent_year": ("price", "prev_249_price"),
    "change_pct_5d": ("price", "prev4_price"),
    "turnover_ratio": ("volume", "float_share", "volume_unit_flag"),
    "real_turnover_ratio": ("volume", "free_float_market_share", "volume_unit_flag"),
    "inner_outer_ratio": ("inner_vol", "outer_vol"),
    "order_buy_sell_diff": ("order_buy_volume", "order_sell_volume"),
}

PRICE_FIELDS = {
    "price",
    "open",
    "close",
    "high",
    "low",
    "pre_close",
    "open_price",
    "avg_price",
    "bid1_price",
    "bid2_price",
    "bid3_price",
    "bid4_price",
    "bid5_price",
    "ask1_price",
    "ask2_price",
    "ask3_price",
    "ask4_price",
    "ask5_price",
    "limit_up_price",
    "limit_down_price",
    "last_month_price",
    "last_year_price",
    "prev_19_price",
    "prev_249_price",
    "prev4_price",
    "up_buy_price",
    "down_sell_price",
    "price_avg_diff",
    "before_after_price",
    "high_all_time",
    "high_60d",
    "otc_fund_nav",
    "after_hours_price",
    "after_hours_high_price",
    "after_hours_low_price",
    "change_amt",
    "before_after_change",
    "after_hours_change",
}
PERCENT_FIELDS = {
    "change_pct",
    "turnover_ratio",
    "real_turnover_ratio",
    "amplitude",
    "body_change_pct",
    "growth_3min",
    "this_month_pct",
    "this_year_pct",
    "change_pct_20d",
    "change_pct_recent_year",
    "before_after_pct",
    "change_pct_60d",
    "change_pct_recent_6month",
    "auction_change_pct",
    "change_pct_since_ipo",
    "change_pct_3y",
    "change_pct_3d",
    "change_pct_5d",
    "change_pct_6d",
    "change_pct_10d",
    "prev_day_change_pct",
    "auction_turnover_ratio",
    "auction_real_turnover_ratio",
    "increase_rate_1min",
    "increase_rate_2min",
    "increase_rate_3min",
    "increase_rate_4min",
    "increase_rate_5min",
    "main_net_ratio",
    "inc_pos_ratio",
    "inc_pos_ratio_3d",
    "inc_pos_ratio_10d",
    "inc_pos_ratio_20d",
    "open_pre_ratio",
    "order_buy_sell_ratio",
    "block_ratio",
    "pre_block_ratio",
    "block_flow_ratio",
    "block_flow_ratio2",
    "after_hours_change_pct",
    "dividend_yield",
    "turnover_ratio_3d",
    "turnover_ratio_5d",
    "turnover_ratio_6d",
    "turnover_ratio_10d",
    "turnover_ratio_20d",
}
RATIO_FIELDS = {
    "volume_ratio",
    "inner_outer_ratio",
    "auction_volume_ratio",
    "auction_pre_volume_ratio_legacy",
    "auction_pre_volume_ratio",
    "pe_ratio",
    "dynamic_pe",
    "static_pe",
    "ttm_pe",
    "pb_ratio",
    "ps_ratio",
    "ddx",
    "ddy",
    "ddz",
    "ddf",
    "ddf_ma1",
    "ddf_ma2",
    "ddf_ma3",
    "ddf_ma5",
    "ddf_ma10",
    "ddf_ma20",
}


def safe_number(value: Any) -> float | None:
    """返回有限数字；接口的 null/哨兵值不会进入绘图。"""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number == 2147483647:
        return None
    return number


def normalize_d101_code(value: str) -> str:
    """将用户输入转换为 D101 的规范代码。

    D101 的快照通道本身接受变长代码；这里补齐常见的市场前缀，避免
    把小写期货品种、美股代码或八位期权合约误当成普通 A股代码。
    """

    code = value.strip()
    if not code:
        return ""

    if re.fullmatch(r"\d{6}", code):
        # 兼容传统的六位 A股输入。
        prefix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
        return prefix + code

    option_match = re.fullmatch(r"(SO|ZO)(\d{8})", code, re.IGNORECASE)
    if option_match:
        return option_match.group(1).upper() + option_match.group(2)

    if re.fullmatch(r"\d{8}", code):
        # 9 开头的八位期权合约属于深圳期权，其余常见合约属于上海期权。
        return ("ZO" if code.startswith("9") else "SO") + code

    cffex_option = re.fullmatch(
        r"(?:IO|HO|MO)\d{4}-[CP]-\d+(?:\.\d+)?",
        code,
        re.IGNORECASE,
    )
    if cffex_option:
        return "CFFEXOPTION|" + cffex_option.group(0).upper()

    if "|" in code:
        exchange, payload = code.split("|", 1)
        exchange = exchange.strip().upper()
        payload = payload.strip()
        if exchange in {"DCE", "SHFE", "CZCE", "INE", "GFEX"}:
            payload = payload.lower()
        elif exchange in {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "OTC"}:
            payload = payload.upper()
        elif exchange == "CFFEXOPTION":
            payload = payload.upper()
        else:
            # HKDL 等市场的代码通常是数字；对未知市场保留可读的规范大写形式。
            payload = payload.upper()
        return f"{exchange}|{payload}"

    # 裸小写的 1~3 位品种名按国内商品期货连续合约处理，例如 jmm。
    # 美股请显式填写 NASDAQ|、NYSE| 或 AMEX|，避免市场歧义。
    if re.fullmatch(r"[a-z]{1,3}(?:\d{2,6})?", code):
        return "DCE|" + code.lower()

    return code.upper()


def is_option_code(code: str) -> bool:
    normalized = code.strip().upper()
    return bool(
        re.fullmatch(r"(?:SO|ZO)\d{8}", normalized)
        or normalized.startswith("CFFEXOPTION|")
    )


# 成交额不是所有资产都能用同一个乘数推导。这里仅登记已经用实盘样本和
# 合约口径确认的类别；未知类别返回 None，宁可显示“—”也不伪造金额。
DCE_AMOUNT_MULTIPLIERS = {
    "JM": 60.0,
    "JMM": 60.0,
}
US_EXCHANGES = ("NASDAQ|", "NYSE|", "AMEX|", "ARCA|", "BATS|", "OTC|")
CALCULATION_SENTINELS = {
    4294967295.0,
    9223372036854775807.0,
    2199023251456.0,
    4398046507008.0,
}


def calculation_number(value: Any) -> float | None:
    """读取可参与本地公式的数字，并排除常见无效哨兵值。"""

    number = safe_number(value)
    if number is None or number in CALCULATION_SENTINELS:
        return None
    return number


def declared_volume_multiplier(row: dict[str, Any] | None) -> float | None:
    """按 `volume_unit_flag` 的原始单位标志返回成交量换算乘数。

    `volume_unit_flag`：0 表示成交量按股/份，1 表示按手。
    股本字段的单位是万股/万份时，按手的 volume 需要乘 100 才能参与
    换手率或成交额计算；按股/份时乘 1。未知标志不参与公式。
    """

    if not row:
        return None
    flag = calculation_number(row.get("volume_unit_flag"))
    if flag is None or not flag.is_integer():
        return None
    return {0: 1.0, 1: 100.0}.get(int(flag))


def amount_volume_multiplier(
    code: str, row: dict[str, Any] | None = None
) -> float | None:
    """返回 volume × average_price 转为成交额所需的品种乘数。"""

    normalized = code.strip().upper()
    if re.fullmatch(r"(?:SO|ZO)\d{8}", normalized):
        # 沪深 ETF/股票期权：一张合约对应 10,000 份标的。
        return 10000.0
    if normalized.startswith("CFFEXOPTION|"):
        # 股指期权合约乘数为 100。
        return 100.0
    if normalized.startswith(US_EXCHANGES):
        # 美股 volume 以股计，价格已由 decimal_num 还原。
        return 1.0
    if normalized.startswith("DCE|"):
        payload = normalized.split("|", 1)[1]
        product_match = re.match(r"[A-Z]+", payload)
        product = product_match.group(0) if product_match else ""
        return DCE_AMOUNT_MULTIPLIERS.get(product)

    mainland = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", normalized)
    if not mainland:
        # 指数（例如 SH000001、SZ399001、IS932000）不把 volume × price
        # 当作成交额；它们的 amount 保持服务端口径。
        return None
    exchange, digits = mainland.groups()
    if (exchange == "SH" and digits.startswith("000")) or (
        exchange == "SZ" and digits.startswith("399")
    ):
        return None
    declared = declared_volume_multiplier(row)
    if declared is not None:
        return declared
    if exchange == "SH" and digits.startswith(("5", "6")):
        return 100.0
    if exchange == "SZ" and digits.startswith(("0", "2", "3", "15", "16", "18")):
        return 100.0
    if exchange == "BJ" and digits.startswith(("4", "8")):
        return 100.0
    return None


def local_amount(row: dict[str, Any], code: str) -> int | None:
    """按已确认的资产单位估算成交额，返回与 `amount` 同口径的金额整数。"""

    volume = calculation_number(row.get("volume"))
    average_price = calculation_number(row.get("avg_price"))
    multiplier = amount_volume_multiplier(code, row)
    if volume is None or average_price is None or multiplier is None:
        return None
    if volume < 0 or average_price < 0:
        return None
    amount = volume * (average_price / (10 ** price_decimal_num(row, code))) * multiplier
    if not math.isfinite(amount):
        return None
    return int(round(amount))


def raw_percent_change(current: float | None, reference: float | None) -> float | None:
    """按 D101 百分数 raw 规则返回 (current-reference)/reference × 10000。"""

    if current is None or reference in (None, 0):
        return None
    return (current - reference) / reference * 10000.0


def turnover_volume_multiplier(
    code: str, row: dict[str, Any] | None = None
) -> float | None:
    """返回 volume/股本换算为 D101 百分比 raw 值所需的单位乘数。"""

    declared = declared_volume_multiplier(row)
    if declared is not None:
        return declared

    normalized = code.strip().upper()
    if normalized.startswith(US_EXCHANGES):
        # 美股 volume 以股计，而股本字段按万股计。
        return 1.0
    if re.fullmatch(r"IS\d+", normalized):
        # 中证指数样本与沪深指数样本的 volume/float_share 口径一致。
        return 100.0
    mainland = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", normalized)
    if mainland:
        exchange, digits = mainland.groups()
        if (exchange == "SH" and digits.startswith("000")) or (
            exchange == "SZ" and digits.startswith("399")
        ):
            return 100.0
        if amount_volume_multiplier(code, row) == 100.0:
            return 100.0
    return None


def local_turnover_ratio(row: dict[str, Any], code: str, denominator_key: str) -> int | None:
    """从累计成交量和股本字段生成 D101 百分比 raw 值。"""

    volume = calculation_number(row.get("volume"))
    shares = calculation_number(row.get(denominator_key))
    multiplier = turnover_volume_multiplier(code, row)
    if volume is None or shares is None or shares <= 0 or multiplier is None:
        return None
    ratio = volume / shares * multiplier
    if not math.isfinite(ratio) or ratio < 0:
        return None
    return int(round(ratio))


def local_inner_outer_ratio(row: dict[str, Any]) -> int | None:
    """从内盘/外盘累计量生成内外盘比 raw 值。"""

    inner = calculation_number(row.get("inner_vol"))
    outer = calculation_number(row.get("outer_vol"))
    if inner is None or outer is None or outer <= 0 or inner < 0:
        return None
    ratio = inner / outer * 100.0
    return int(round(ratio)) if math.isfinite(ratio) else None


def price_decimal_num(row: dict[str, Any] | None, code: str = "") -> int:
    """读取当前行情行的价格精度；缺失时才按资产类型使用保守回退值。"""

    if row:
        raw = safe_number(row.get("decimal_num"))
        if raw is not None and raw.is_integer() and 0 <= raw <= 9:
            return int(raw)
    normalized = code.strip().upper()
    if normalized.startswith("CFFEXOPTION|"):
        return 1
    return 4 if is_option_code(code) else 2


def display_decimal_num(row: dict[str, Any] | None, code: str = "") -> int:
    """读取当前行情行的展示小数位；缺失时回退到价格精度。"""

    if row:
        raw = safe_number(row.get("display_decimal_num"))
        if raw is not None and raw.is_integer() and 0 <= raw <= 9:
            return int(raw)
    return price_decimal_num(row, code)


def normalize_value(
    field: str,
    value: Any,
    code: str = "",
    row: dict[str, Any] | None = None,
) -> float | None:
    """把接口数值转换成适合用户界面显示的值。"""

    number = safe_number(value)
    if number is None:
        return None
    if field in PRICE_FIELDS:
        return number / (10 ** price_decimal_num(row, code))
    if field in PERCENT_FIELDS or field in RATIO_FIELDS:
        return number / 100.0
    return number


def normalized_row(row: dict[str, Any]) -> dict[str, Any]:
    """保留接口行键，同时生成少量带单位的内部显示值。"""

    code = str(row.get("code") or "")
    result = dict(row)
    for key, value in row.items():
        if key in PRICE_FIELDS or key in PERCENT_FIELDS or key in RATIO_FIELDS:
            result[f"_{key}"] = normalize_value(key, value, code, result)
    return result


def add_local_computed_fields(row: dict[str, Any]) -> dict[str, Any]:
    """用已经收到的基础值补充确定性指标，避免额外占用推送带宽。

    这里只补充公式明确、依赖字段在同一行且价格精度一致的指标。服务端
    如果实际返回了同名原始字段，则原始字段优先，客户端不会覆盖它。
    """

    result = dict(row)
    provided_keys = set(row)
    local_fields = set(result.get("__local_fields", ()))

    def raw_number(key: str) -> float | None:
        return calculation_number(result.get(key))

    def should_compute(key: str) -> bool:
        # 增量推送时，前一帧生成的本地字段已经在缓存中；基础字段变化后
        # 必须重新计算。服务端明确返回同名字段时，由调用方清除本地标记，
        # 从而保留服务端原始值。
        return key not in result or key in local_fields

    price = raw_number("price")
    pre_close = raw_number("pre_close")
    high = raw_number("high")
    low = raw_number("low")
    avg_price = raw_number("avg_price")
    open_price = raw_number("open_price")

    if should_compute("change_pct"):
        value = raw_percent_change(price, pre_close)
        if value is not None:
            result["change_pct"] = value
            local_fields.add("change_pct")
        elif "change_pct" in local_fields:
            result["change_pct"] = None
    if should_compute("change_amt") and price is not None and pre_close is not None:
        result["change_amt"] = price - pre_close
        local_fields.add("change_amt")
    elif should_compute("change_amt") and "change_amt" in local_fields:
        result["change_amt"] = None
    if should_compute("amplitude") and high is not None and low is not None and pre_close not in (None, 0):
        result["amplitude"] = (high - low) / pre_close * 10000.0
        local_fields.add("amplitude")
    elif should_compute("amplitude") and "amplitude" in local_fields:
        result["amplitude"] = None
    if should_compute("price_avg_diff") and price is not None and avg_price is not None:
        result["price_avg_diff"] = price - avg_price
        local_fields.add("price_avg_diff")
    elif should_compute("price_avg_diff") and "price_avg_diff" in local_fields:
        result["price_avg_diff"] = None
    if should_compute("body_change_pct"):
        value = raw_percent_change(price, open_price)
        if value is not None:
            result["body_change_pct"] = value
            local_fields.add("body_change_pct")
        elif "body_change_pct" in local_fields:
            result["body_change_pct"] = None
    if should_compute("open_pre_ratio") and open_price is not None and pre_close not in (None, 0):
        result["open_pre_ratio"] = open_price / pre_close * 10000.0
        local_fields.add("open_pre_ratio")
    elif should_compute("open_pre_ratio") and "open_pre_ratio" in local_fields:
        result["open_pre_ratio"] = None

    reference_fields = (
        ("this_month_pct", "last_month_price"),
        ("this_year_pct", "last_year_price"),
        ("change_pct_20d", "prev_19_price"),
        ("change_pct_recent_year", "prev_249_price"),
        ("change_pct_5d", "prev4_price"),
    )
    for derived_key, reference_key in reference_fields:
        if not should_compute(derived_key):
            continue
        value = raw_percent_change(price, raw_number(reference_key))
        if value is not None:
            result[derived_key] = value
            local_fields.add(derived_key)
        elif derived_key in local_fields:
            result[derived_key] = None

    if should_compute("amount"):
        value = local_amount(result, str(result.get("code") or ""))
        if value is not None:
            result["amount"] = value
            local_fields.add("amount")
        elif "amount" in local_fields:
            result["amount"] = None

    code = str(result.get("code") or "")
    if should_compute("turnover_ratio"):
        value = local_turnover_ratio(result, code, "float_share")
        if value is not None:
            result["turnover_ratio"] = value
            local_fields.add("turnover_ratio")
        elif "turnover_ratio" in local_fields:
            result["turnover_ratio"] = None
    if should_compute("real_turnover_ratio"):
        value = local_turnover_ratio(result, code, "free_float_market_share")
        if value is not None:
            result["real_turnover_ratio"] = value
            local_fields.add("real_turnover_ratio")
        elif "real_turnover_ratio" in local_fields:
            result["real_turnover_ratio"] = None
    if should_compute("inner_outer_ratio"):
        value = local_inner_outer_ratio(result)
        if value is not None:
            result["inner_outer_ratio"] = value
            local_fields.add("inner_outer_ratio")
        elif "inner_outer_ratio" in local_fields:
            result["inner_outer_ratio"] = None
    if should_compute("order_buy_sell_diff"):
        buy_volume = raw_number("order_buy_volume")
        sell_volume = raw_number("order_sell_volume")
        if buy_volume is not None and sell_volume is not None:
            result["order_buy_sell_diff"] = buy_volume - sell_volume
            local_fields.add("order_buy_sell_diff")
        elif "order_buy_sell_diff" in local_fields:
            result["order_buy_sell_diff"] = None

    for key in LOCAL_COMPUTED_FIELDS:
        if key in provided_keys and key not in local_fields:
            local_fields.discard(key)
    result["__local_fields"] = tuple(sorted(local_fields))
    return result


def split_codes(value: str) -> list[str]:
    """把输入框中的代码转换为 D101 支持的规范代码数组。"""

    result: list[str] = []
    for item in re.split(r"[,;\s]+", value.strip()):
        code = normalize_d101_code(item)
        if not code:
            continue
        if code not in result:
            result.append(code)
    return result


def display_time(value: Any = None) -> str:
    if value is None:
        return datetime.now().strftime("%H:%M:%S")
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 0 <= raw <= 235959:
        return f"{raw // 10000:02d}:{raw // 100 % 100:02d}:{raw % 100:02d}"
    return str(raw)


def compact_number(value: Any, digits: int = 2) -> str:
    number = safe_number(value)
    if number is None:
        return "—"
    if abs(number) >= 100000000:
        return f"{number / 100000000:.{digits}f}亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.{digits}f}万"
    return f"{number:,.{digits}f}"


def compact_volume(value: Any) -> str:
    number = safe_number(value)
    if number is None:
        return "—"
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f}亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.1f}万"
    return f"{number:,.0f}"


def format_price(value: Any, decimals: int = 2) -> str:
    number = safe_number(value)
    decimals = max(0, min(int(decimals), 8))
    return "—" if number is None else f"{number:.{decimals}f}"


def format_pct(value: Any) -> str:
    number = safe_number(value)
    if number is None:
        return "—"
    return f"{number:+.2f}%"


def quote_color(value: Any) -> str:
    number = safe_number(value)
    if number is None or number == 0:
        return FLAT
    return UP if number > 0 else DOWN


def build_command(
    mode: str,
    codes: list[str],
    seq: int,
    universe: str = "",
    limit: int = 0,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    if mode == "market_event":
        return {
            "type": "market_event",
            "seq": seq,
            "mode": 1,
            "count": 100,
            "enable": 1,
        }
    command: dict[str, Any] = {
        "type": "snapshot",
        "seq": seq,
        "enable": 1,
        "fields": list(BANDWIDTH_REQUEST_FIELDS if fields is None else fields),
    }
    if universe:
        command["universe"] = universe
        command["limit"] = max(0, min(int(limit), 65535))
    else:
        command["codes"] = codes or ["SZ000001", "SH600000"]
    return command


def prepare_snapshot_fields(fields: list[str], include_all: bool = False) -> list[str]:
    """整理 GUI 的字段选择，并补齐身份和价格显示所需的元数据。"""

    known = set(D101_FIELD_KEYS)
    selected: list[str] = []
    for key in fields:
        if key in known and key not in selected:
            selected.append(key)
    if "code" in known and "code" not in selected:
        selected.insert(0, "code")

    if not include_all:
        # 用户显式选择派生字段时自动补入其原始依赖；未显式选择的高频
        # 派生指标不会反向扩大“省带宽”默认集合。
        for key in tuple(selected):
            for dependency in LOCAL_FIELD_DEPENDENCIES.get(key, ()):
                if dependency in known and dependency not in selected:
                    selected.append(dependency)

    # 价格 raw 值必须结合 `decimal_num` 才能正确显示；
    # `display_decimal_num` 只控制展示位数。
    # “全部字段”本来就包含二者，部分字段模式下这里才自动补入。
    if not include_all and any(key in PRICE_FIELDS for key in selected):
        for dependency in ("decimal_num", "display_decimal_num"):
            if dependency in known and dependency not in selected:
                selected.append(dependency)
    return selected


def build_snapshot_commands(
    codes: list[str],
    seq: int,
    fields: list[str],
    universe: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    """构造一条完整快照命令。

    D101 的字段计数是单字节，当前已登记的 203 个字段可以一次请求。
    代码数量以 6000 只为单条底层连接的容量参考；超过时由服务端在同一条
    客户端命令内部拆成代码批次，GUI 不拆字段、不新建 WebSocket 连接。
    """

    prepared = prepare_snapshot_fields(fields, include_all=len(fields) == len(D101_FIELD_KEYS))
    if len(prepared) > MAX_FIELDS_PER_COMMAND:
        raise ValueError(
            f"D101 单条 snapshot 最多支持 {MAX_FIELDS_PER_COMMAND} 个字段"
        )
    return build_command(
        "snapshot",
        codes,
        max(1, int(seq)),
        universe=universe,
        limit=limit,
        fields=prepared,
    )


def build_market_event_history_command(
    seq: int,
    cursor: dict[str, int],
    count: int = -100,
) -> dict[str, Any]:
    """构造 market_event 的上一页请求；cursor 必须来自当前列表最末一行。"""

    return {
        "type": "market_event",
        "seq": seq,
        "mode": 2,
        "count": -abs(int(count)) or -100,
        "cursor": {
            "time": int(cursor["time"]),
            "seq": int(cursor["seq"]),
        },
        "enable": 1,
    }


@dataclass
class Quote:
    code: str
    data: dict[str, Any] = field(default_factory=dict)
    history: deque[float] = field(default_factory=lambda: deque(maxlen=160))
    updates: int = 0
    received_at: float = field(default_factory=time.time)

    @property
    def display(self) -> dict[str, Any]:
        return normalized_row(self.data)


class D101Stream:
    """后台 WebSocket 线程；不触碰 Tkinter 对象。"""

    def __init__(
        self,
        url: str,
        command: dict[str, Any] | list[dict[str, Any]],
        on_state: Callable[[str, str], None],
        on_message: Callable[[str], None],
    ) -> None:
        self.url = url
        self.command = command
        self.on_state = on_state
        self.on_message = on_message
        self.stop_event = threading.Event()
        self.ws: Any = None
        self.ws_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="d101-gui-ws", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        with self.ws_lock:
            current = self.ws
        if current is not None:
            try:
                current.close()
            except Exception:
                pass
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=3.0)

    def send(self, payload: dict[str, Any] | list[dict[str, Any]]) -> bool:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.ws_lock:
            current = self.ws
            if current is None:
                return False
            try:
                current.send(text)
                return True
            except Exception as exc:
                self.on_state("error", f"发送失败：{exc}")
                return False

    def _run(self) -> None:
        if websocket is None:
            self.on_state("error", f"缺少 websocket-client。\n{websocket_install_hint()}")
            return

        retry_delay = 1.0
        while not self.stop_event.is_set():
            try:
                self._run_once()
                retry_delay = 1.0
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.on_state("error", f"连接异常：{exc}")
            finally:
                with self.ws_lock:
                    self.ws = None
            if self.stop_event.is_set():
                break
            self.on_state("retry", f"连接已断开，{retry_delay:.0f} 秒后重试")
            self.stop_event.wait(retry_delay)
            retry_delay = min(retry_delay * 2.0, 8.0)

    def _run_once(self) -> None:
        assert websocket is not None
        self.on_state("connecting", "正在建立 d101 连接…")
        current = websocket.create_connection(
            self.url,
            timeout=8,
            enable_multithread=True,
            http_proxy_host=None,
            http_proxy_port=None,
        )
        current.settimeout(1.0)
        with self.ws_lock:
            self.ws = current
        self.on_state("connected", "连接已建立，正在等待数据…")
        current.send(json.dumps(self.command, ensure_ascii=False, separators=(",", ":")))
        self.on_state("subscribed", "订阅指令已发送")
        try:
            while not self.stop_event.is_set():
                try:
                    raw = current.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    return
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                self.on_message(str(raw))
        finally:
            try:
                commands = self.command if isinstance(self.command, list) else [self.command]
                disable_payload: dict[str, Any] | list[dict[str, Any]]
                disable_commands = [
                    {"type": item.get("type", "snapshot"), "enable": 0}
                    for item in commands
                ]
                disable_payload = disable_commands[0] if len(disable_commands) == 1 else disable_commands
                current.send(
                    json.dumps(
                        disable_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            except Exception:
                pass
            try:
                current.close()
            except Exception:
                pass


class D101Gui:
    def __init__(self, root: tk.Tk, url: str) -> None:
        self.root = root
        self.root.title("d101 · 用户侧实时全推控制台")
        self.root.geometry("1600x960")
        self.root.minsize(1180, 700)
        self.root.configure(bg=BG)

        self.endpoint_var = tk.StringVar(value=url)
        self.codes_var = tk.StringVar(value="SZ000001,SH600000,SZ300750")
        self.universe_var = tk.StringVar(value="沪深京 A股 · 全市场")
        self.subscription_mode_var = tk.StringVar(value="market")
        self.limit_var = tk.StringVar(value="0")
        self.field_profile_var = tk.StringVar(value=FIELD_PROFILE_LABELS["bandwidth"])
        self.field_profile_key = "bandwidth"
        self.custom_field_keys = list(BANDWIDTH_REQUEST_FIELDS)
        self.field_selector_window: tk.Toplevel | None = None
        self.mode = "snapshot"
        self.privacy_mode = False

        # 两个 TAB 各自保存自己的推送表，不混合、不覆盖。
        self.rows_by_mode: dict[str, dict[str, dict[str, Any]]] = {
            "snapshot": {},
            "market_event": {},
        }
        self.tree_iids: dict[str, dict[str, str]] = {"snapshot": {}, "market_event": {}}
        self.tree_key_by_iid: dict[str, str] = {}
        self.table_columns: dict[str, tuple[str, ...]] = {
            mode: tuple(columns) for mode, columns in TABLE_FALLBACK_COLUMNS.items()
        }
        self._table_orders: dict[str, list[str]] = {mode: [] for mode in self.rows_by_mode}
        self._table_order_dirty: set[str] = set(self.rows_by_mode)
        self._table_columns_dirty: set[str] = set(self.rows_by_mode)
        self._virtual_offsets: dict[str, int] = {mode: 0 for mode in self.rows_by_mode}
        self._virtual_tree_mode = ""
        self._virtual_slot_ids: list[str] = []
        self._virtual_rendered_rows = 0
        self._virtual_visible_rows = 1
        # 横向也做列窗口化：Treeview 只显示当前可视区的列，避免 203 列
        # 同时参与原生重绘。拖动时只保留最后一个位置，最多每 32ms 刷新一次。
        self._horizontal_start_column = 0
        self._horizontal_mode = ""
        self._horizontal_columns_signature: tuple[str, ...] = ()
        self._horizontal_display_columns: tuple[str, ...] = ()
        self._horizontal_column_widths: tuple[int, ...] = ()
        self._horizontal_column_prefix: tuple[int, ...] = (0,)
        self._horizontal_total_width = 0
        self._horizontal_view_width = 1
        self._horizontal_pending_command: tuple[str, ...] | None = None
        self._horizontal_scroll_job: Any = None
        self.table_ordinal = 0
        self._table_refresh_pending = False
        self.market_event_cursor: dict[str, int] | None = None
        self.market_event_loading = False
        self.market_event_has_more = True
        self.market_event_request_seq = 1000
        self.market_event_history_pages = 0
        self.market_event_scroll_at_bottom = False

        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._configure_widgets()

        self.queue: queue.Queue[tuple[int, str, Any]] = queue.Queue()
        self.session_id = 0
        self.stream: D101Stream | None = None
        self.connected = False
        self.connecting = False
        self.connection_text = "未连接"
        self.quotes: dict[str, Quote] = {}
        self.events: deque[dict[str, Any]] = deque(maxlen=80)
        self.selected_code = ""
        self.message_count = 0
        self.row_count = 0
        self.error_count = 0
        self.last_message_at = 0.0
        self.last_draw_at = 0.0
        self._draw_pending = False
        self._last_paint_monotonic = 0.0
        self.hover_target = ""
        self.layout: dict[str, tuple[float, float, float, float]] = {}

        self.canvas.bind("<Configure>", lambda _event: self.schedule_draw())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _event: self._set_hover(""))
        self.root.bind("<Return>", lambda _event: self.toggle_connection())
        self.root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _event: self.leave_fullscreen())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(QUEUE_DRAIN_INTERVAL_MS, self.drain_queue)
        self.root.after(1000, self._tick)
        self._add_event("SYS", "准备就绪：默认只请求省带宽基础字段；需要时再打开字段设置", MUTED)
        self.schedule_draw()

        try:
            self.root.state("zoomed")
        except tk.TclError:
            pass

    # ── Tk 控件和布局 ────────────────────────────────────────────────────

    def _configure_widgets(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.endpoint_entry = tk.Entry(
            self.root,
            textvariable=self.endpoint_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=CYAN,
            selectbackground=CYAN_DARK,
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
            font=FONT_MONO_SMALL,
        )
        self.codes_entry = tk.Entry(
            self.root,
            textvariable=self.codes_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=CYAN,
            selectbackground=CYAN_DARK,
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
            font=FONT_MONO_SMALL,
        )
        self.universe_box = ttk.Combobox(
            self.root,
            textvariable=self.universe_var,
            values=list(UNIVERSE_OPTIONS),
            state="readonly",
            style="D101.TCombobox",
            width=30,
        )
        self.limit_entry = tk.Entry(
            self.root,
            textvariable=self.limit_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=CYAN,
            selectbackground=CYAN_DARK,
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
            font=FONT_MONO_SMALL,
            justify="center",
        )
        self.field_profile_box = ttk.Combobox(
            self.root,
            textvariable=self.field_profile_var,
            values=list(FIELD_PROFILE_VALUES),
            state="readonly",
            style="D101.TCombobox",
            width=28,
        )
        style.configure(
            "D101.TCombobox",
            fieldbackground=INPUT,
            background=INPUT,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            arrowcolor=CYAN,
            padding=(6, 4),
            font=FONT_MONO_SMALL,
        )
        style.map(
            "D101.TCombobox",
            fieldbackground=[("readonly", INPUT)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", CYAN_DARK)],
            selectforeground=[("readonly", TEXT)],
        )
        style.configure(
            "D101.Treeview",
            background=SURFACE_3,
            fieldbackground=SURFACE_3,
            foreground=TEXT_SOFT,
            borderwidth=0,
            relief="flat",
            rowheight=26,
            font=FONT_MONO_SMALL,
        )
        style.configure(
            "D101.Treeview.Heading",
            background=SURFACE_2,
            foreground=CYAN,
            borderwidth=0,
            relief="flat",
            padding=(8, 7),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "D101.Treeview.Heading",
            background=[("pressed", CYAN_DARK), ("active", SURFACE_2)],
            foreground=[("pressed", WHITE), ("active", CYAN)],
        )
        style.map(
            "D101.Treeview",
            background=[("selected", "#1d4564")],
            foreground=[("selected", WHITE)],
        )
        style.configure(
            "D101.Vertical.TScrollbar",
            background=SURFACE_2,
            troughcolor=BG_2,
            bordercolor=BG_2,
            arrowcolor=CYAN,
        )
        style.configure(
            "D101.Horizontal.TScrollbar",
            background=SURFACE_2,
            troughcolor=BG_2,
            bordercolor=BG_2,
            arrowcolor=CYAN,
        )
        self.data_tree = ttk.Treeview(
            self.root,
            columns=self.table_columns[self.mode],
            show="headings",
            selectmode="browse",
            style="D101.Treeview",
        )
        self.vertical_scroll = ttk.Scrollbar(
            self.root,
            orient="vertical",
            command=self._on_vertical_scroll,
            style="D101.Vertical.TScrollbar",
        )
        self.horizontal_scroll = ttk.Scrollbar(
            self.root,
            orient="horizontal",
            command=self._on_horizontal_scroll,
            style="D101.Horizontal.TScrollbar",
        )
        self.empty_state_label = tk.Label(
            self.root,
            bg=SURFACE_3,
            fg=MUTED,
            font=("Microsoft YaHei UI", 11),
            justify="center",
        )
        self.data_tree.configure(
            yscrollcommand=self._on_tree_yview,
        )
        self.data_tree.tag_configure("even", background="#0d1828")
        self.data_tree.tag_configure("odd", background="#101e31")
        self.data_tree.tag_configure("even_red", background="#0d1828", foreground=UP)
        self.data_tree.tag_configure("odd_red", background="#101e31", foreground=UP)
        self.data_tree.tag_configure("even_green", background="#0d1828", foreground=DOWN)
        self.data_tree.tag_configure("odd_green", background="#101e31", foreground=DOWN)
        self.data_tree.tag_configure("even_unknown", background="#0d1828", foreground=TEXT_SOFT)
        self.data_tree.tag_configure("odd_unknown", background="#101e31", foreground=TEXT_SOFT)
        # 行情表沿用盘口异动的配色：行底保持深色交替，只用红/绿文字提示方向，
        # 避免整行大面积染色，也避免高频刷新时产生刺眼的闪烁。
        self.data_tree.tag_configure("even_up", background="#0d1828", foreground=UP)
        self.data_tree.tag_configure("odd_up", background="#101e31", foreground=UP)
        self.data_tree.tag_configure("even_down", background="#0d1828", foreground=DOWN)
        self.data_tree.tag_configure("odd_down", background="#101e31", foreground=DOWN)
        self.data_tree.tag_configure("even_flat", background="#0d1828", foreground=TEXT_SOFT)
        self.data_tree.tag_configure("odd_flat", background="#101e31", foreground=TEXT_SOFT)
        self.data_tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.data_tree.bind("<MouseWheel>", self._on_tree_mousewheel, add="+")
        self.data_tree.bind("<Button-4>", self._on_tree_button_scroll, add="+")
        self.data_tree.bind("<Button-5>", self._on_tree_button_scroll, add="+")
        for sequence in ("<Up>", "<Down>", "<Prior>", "<Next>", "<Home>", "<End>"):
            self.data_tree.bind(sequence, self._on_tree_key_scroll, add="+")
        self.universe_box.bind("<<ComboboxSelected>>", self._on_universe_selected)
        self.field_profile_box.bind("<<ComboboxSelected>>", self._on_field_profile_selected)
        self._sync_subscription_controls()

    def _place_widgets(self, width: int, toolbar_y: int) -> None:
        """只摆放当前 TAB 真正使用的控件，避免禁用控件占据界面空间。"""

        self._sync_subscription_controls()
        self._sync_field_controls()
        endpoint_x = 98
        endpoint_w = min(360, max(270, int(width * 0.27)))

        def place_widget(widget: tk.Widget, x: int, y: int, width: int, height: int) -> None:
            options = {"x": x, "y": y, "width": width, "height": height}
            if widget.winfo_manager() == "place":
                widget.place_configure(**options)
            else:
                widget.place(**options)

        def hide_widget(widget: tk.Widget) -> None:
            if widget.winfo_manager() == "place":
                widget.place_forget()

        place_widget(self.endpoint_entry, endpoint_x, toolbar_y + 20, endpoint_w, 26)

        self.layout["connect"] = (
            max(endpoint_x + endpoint_w + 24, width - 178),
            toolbar_y + 16,
            width - 96,
            toolbar_y + 49,
        )
        self.layout["clear"] = (width - 86, toolbar_y + 16, width - 30, toolbar_y + 49)

        if self.mode == "snapshot":
            toggle_x = 98
            toggle_w = 178
            toggle_y = toolbar_y + 48
            self.layout["subscription_market"] = (toggle_x, toggle_y, toggle_x + 86, toggle_y + 28)
            self.layout["subscription_codes"] = (
                toggle_x + 91,
                toggle_y,
                toggle_x + toggle_w,
                toggle_y + 28,
            )

            source_x = toggle_x + toggle_w + 18
            using_universe = self.subscription_mode_var.get() == "market"
            if using_universe:
                source_w = min(300, max(250, int(width * 0.20)))
                place_widget(self.universe_box, source_x, toolbar_y + 48, source_w, 26)
                limit_x = source_x + source_w + 18
                place_widget(self.limit_entry, limit_x, toolbar_y + 48, 72, 26)
                hide_widget(self.codes_entry)
            else:
                codes_w = min(460, max(320, int(width * 0.28)))
                place_widget(self.codes_entry, source_x, toolbar_y + 48, codes_w, 26)
                hide_widget(self.universe_box)
                hide_widget(self.limit_entry)

            field_x = 98
            field_w = min(300, max(240, int(width * 0.22)))
            place_widget(self.field_profile_box, field_x, toolbar_y + 84, field_w, 26)
            field_button_x = field_x + field_w + 12
            self.layout["field_settings"] = (
                field_button_x,
                toolbar_y + 82,
                field_button_x + 112,
                toolbar_y + 110,
            )
            return

        hide_widget(self.universe_box)
        hide_widget(self.codes_entry)
        hide_widget(self.limit_entry)
        hide_widget(self.field_profile_box)

    def _sync_subscription_controls(self) -> None:
        """让 UI 状态直接表达 market/code 二选一关系。"""

        is_snapshot = self.mode == "snapshot"
        using_universe = is_snapshot and self.subscription_mode_var.get() == "market"
        self.universe_box.configure(state="readonly" if using_universe else "disabled")
        self.codes_entry.configure(
            state="normal" if not is_snapshot or not using_universe else "disabled",
            disabledforeground="#536a83",
        )
        self.limit_entry.configure(
            state="normal" if using_universe else "disabled",
            disabledforeground="#536a83",
        )

    def _sync_field_controls(self) -> None:
        """字段选择只影响 snapshot；其他 TAB 不发送 fields。"""

        self.field_profile_box.configure(
            state="readonly" if self.mode == "snapshot" else "disabled"
        )

    def _field_profile_selected_keys(self) -> list[str]:
        if self.field_profile_key == "all":
            return list(D101_FIELD_KEYS)
        if self.field_profile_key == "common":
            return list(COMMON_REQUEST_FIELDS)
        if self.field_profile_key == "custom":
            return list(self.custom_field_keys)
        return list(BANDWIDTH_REQUEST_FIELDS)

    def _prepared_snapshot_fields(self) -> list[str]:
        return prepare_snapshot_fields(
            self._field_profile_selected_keys(),
            include_all=self.field_profile_key == "all",
        )

    def _subscription_command_count(self) -> int:
        """当前 GUI 始终只发送一条 snapshot 命令。

        代码数量超过单条底层连接容量时，由服务端在这条命令内部拆分，
        因此这里不把底层代码批次数伪装成客户端订阅命令数。
        """

        return 1

    def _field_summary(self) -> str:
        if self.mode != "snapshot":
            return "当前 TAB 不使用行情字段选择"
        fields = self._prepared_snapshot_fields()
        local_labels = [D101_FIELD_LABELS.get(key, key) for key in LOCAL_COMPUTED_FIELDS]
        local_names = "、".join(local_labels[:5])
        if len(local_labels) > 5:
            local_names += "等"
        command_count = self._subscription_command_count()
        return (
            f"请求 {len(fields)} 个原始字段 · {command_count} 条订阅命令 · "
            f"本地可算 {len(local_labels)} 项：{local_names}"
        )

    def _field_summary_short(self) -> str:
        if self.mode != "snapshot":
            return "—"
        return f"{len(self._prepared_snapshot_fields())} 个 / 1 条命令"

    def _on_field_profile_selected(self, _event: tk.Event) -> None:
        selected_label = self.field_profile_var.get()
        selected_key = next(
            (key for key, label in FIELD_PROFILE_LABELS.items() if label == selected_label),
            self.field_profile_key,
        )
        if selected_key == "custom":
            # 取消自定义对话框时恢复原来的方案，避免用户误以为已经改变请求。
            self.field_profile_var.set(FIELD_PROFILE_LABELS[self.field_profile_key])
            self.open_field_selector()
            return
        self.field_profile_key = selected_key
        self._field_selection_changed(f"字段方案：{FIELD_PROFILE_LABELS[selected_key]}")

    def _field_selection_changed(self, message: str) -> None:
        was_active = self.connected or self.connecting
        if was_active:
            self.disconnect(silent=True)
        self._table_columns_dirty.add("snapshot")
        self._add_event("FIELD", message, CYAN)
        if was_active:
            self._add_event("FIELD", "字段方案已改变，请点击连接重新订阅", AMBER)
        self.schedule_draw()

    def open_field_selector(self) -> None:
        """打开 203 字段选择器，勾选内容作为下一次 snapshot 请求。"""

        if self.mode != "snapshot":
            self._add_event("FIELD", "字段选择只适用于行情全推 TAB", MUTED)
            return
        if self.field_selector_window is not None:
            try:
                if self.field_selector_window.winfo_exists():
                    self.field_selector_window.deiconify()
                    self.field_selector_window.lift()
                    return
            except tk.TclError:
                pass

        dialog = tk.Toplevel(self.root)
        self.field_selector_window = dialog
        dialog.title("D101 请求字段设置 · 语义字段")
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        dialog_width = min(max(1120, screen_width - 48), 1900)
        # 给系统任务栏留出空间，避免最大化/滚轮后窗口底部被任务栏遮住。
        dialog_height = min(max(700, screen_height - 120), 1040)
        dialog.geometry(
            f"{dialog_width}x{dialog_height}+{max(0, (screen_width - dialog_width) // 2)}+"
            f"{max(0, (screen_height - dialog_height) // 2)}"
        )
        dialog.minsize(980, 640)
        # 字段网格按当前屏幕一次确定列数；固定窗口尺寸，避免拖动窗口时网格
        # 重新换列导致滚动区域和视觉位置跳变。
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.update_idletasks()
        actual_width = max(dialog.winfo_width(), 980)

        field_column_count = (
            6
            if actual_width >= 1700
            else 5
            if actual_width >= 1400
            else 4
            if actual_width >= 1100
            else 3
        )

        # 显示“实际会发送”的字段；例如只勾选 price 时，下面的两个
        # 精度元数据会被请求构造器自动补入，重新打开窗口时也应保持勾选。
        current_keys = set(self._prepared_snapshot_fields())
        field_vars = {
            key: tk.BooleanVar(value=key in current_keys)
            for key, _meaning in D101_FIELD_CATALOG
        }
        field_vars["code"].set(True)

        header_row = tk.Frame(dialog, bg=BG)
        header_row.pack(fill="x", padx=12, pady=(6, 2))
        title = tk.Label(
            header_row,
            text="选择要从服务端请求的原始字段",
            bg=BG,
            fg=TEXT,
            font=FONT_UI_BOLD,
            anchor="w",
        )
        title.pack(side="left")
        hint = tk.Label(
            header_row,
            text=(
                "默认省带宽；涨跌幅、成交额、换手率等可本地计算。高频盘口按需勾选，"
                "203 个字段可一次请求，代码量超 6000 只时自动分批。"
            ),
            bg=BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
            justify="left",
            anchor="w",
            wraplength=max(420, dialog_width - 300),
        )
        hint.pack(side="left", fill="x", expand=True, padx=(12, 0))

        control_row = tk.Frame(dialog, bg=BG)
        control_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(control_row, text="筛选", bg=BG, fg=MUTED, font=FONT_UI).pack(side="left")
        search_var = tk.StringVar()
        search_entry = tk.Entry(
            control_row,
            textvariable=search_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=CYAN,
            selectbackground=CYAN_DARK,
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=CYAN,
            font=FONT_MONO_SMALL,
            width=32,
        )
        search_entry.pack(side="left", padx=(8, 8), ipady=3)
        count_label = tk.Label(control_row, bg=BG, fg=CYAN, font=FONT_MONO_SMALL, width=24, anchor="w")
        count_label.pack(side="left", padx=(0, 8))

        list_outer = tk.Frame(dialog, bg=BG)
        list_outer.pack(fill="both", expand=True, padx=10)
        list_outer.grid_rowconfigure(0, weight=1)
        list_outer.grid_columnconfigure(0, weight=1)
        list_canvas = tk.Canvas(
            list_outer,
            bg=SURFACE_3,
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        list_scroll = ttk.Scrollbar(
            list_outer,
            orient="vertical",
            command=list_canvas.yview,
            style="D101.Vertical.TScrollbar",
        )
        list_frame = tk.Frame(list_canvas, bg=SURFACE_3)
        window_id = list_canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_canvas.configure(yscrollcommand=list_scroll.set)
        list_canvas.grid(row=0, column=0, sticky="nsew")
        list_scroll.grid(row=0, column=1, sticky="ns")

        def update_field_scrollregion() -> None:
            # Canvas 的 scrollregion 若小于可视区，Tk 会把 window item 垂直居中，
            # 于是顶部看起来像多出一块空白。最小高度取可视区，字段始终从顶部开始。
            list_frame.update_idletasks()
            width = max(1, list_canvas.winfo_width())
            height = max(1, list_canvas.winfo_height(), list_frame.winfo_reqheight())
            list_canvas.configure(scrollregion=(0, 0, width, height))

        def resize_field_frame(event: tk.Event) -> None:
            width = max(1, int(event.width))
            list_canvas.itemconfigure(window_id, width=width)
            update_field_scrollregion()

        list_canvas.bind("<Configure>", resize_field_frame, add="+")

        def scroll_fields(event: tk.Event) -> str:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta:
                # Windows: 正值向上，负值向下；不要用 abs，否则两个方向都会向上。
                units = -int(delta / 120)
                if units == 0:
                    units = -1 if delta > 0 else 1
            else:
                button = int(getattr(event, "num", 0) or 0)
                if button in {4, 5}:
                    units = -3 if button == 4 else 3
                else:
                    units = 0
            if units:
                list_canvas.yview_scroll(units, "units")
            return "break"

        for widget in (list_canvas, list_frame):
            widget.bind("<MouseWheel>", scroll_fields, add="+")
            widget.bind("<Button-4>", scroll_fields, add="+")
            widget.bind("<Button-5>", scroll_fields, add="+")

        visible_specs: list[tuple[str, str]] = []

        def update_selected_count() -> None:
            selected_count = sum(variable.get() for variable in field_vars.values())
            count_label.configure(
                text=f"显示 {len(visible_specs)} / 203 · 已选 {selected_count}"
            )

        def render_fields(*_args: Any) -> None:
            query = search_var.get().strip()
            visible_specs.clear()
            for key, meaning in D101_FIELD_CATALOG:
                if field_search_matches(query, key, meaning):
                    visible_specs.append((key, meaning))
            for child in list_frame.winfo_children():
                child.destroy()
            current_width = max(dialog.winfo_width(), 980)
            cell_width = max(180, (current_width - 64) // field_column_count)
            for index, (key, meaning) in enumerate(visible_specs):
                column = index % field_column_count
                row = index // field_column_count
                row_background = "#0d1828" if row % 2 == 0 else "#101e31"
                state = tk.DISABLED if key == "code" else tk.NORMAL
                check = tk.Checkbutton(
                    list_frame,
                    text=f"{meaning}  · {key}",
                    variable=field_vars[key],
                    state=state,
                    bg=row_background,
                    activebackground=row_background,
                    activeforeground=TEXT,
                    disabledforeground=CYAN,
                    fg=TEXT_SOFT,
                    selectcolor=CYAN_DARK,
                    anchor="w",
                    justify="left",
                    font=("Microsoft YaHei UI", 8),
                    padx=4,
                    pady=0,
                    wraplength=cell_width - 12,
                    command=update_selected_count,
                )
                check.grid(row=row, column=column, sticky="ew", padx=2, pady=0)
                check.bind("<MouseWheel>", scroll_fields, add="+")
                check.bind("<Button-4>", scroll_fields, add="+")
                check.bind("<Button-5>", scroll_fields, add="+")
            for column in range(6):
                list_frame.grid_columnconfigure(
                    column,
                    weight=1 if column < field_column_count else 0,
                    uniform="field" if column < field_column_count else "",
                )
            if not visible_specs:
                tk.Label(
                    list_frame,
                    text="没有匹配的语义字段",
                    bg=SURFACE_3,
                    fg=MUTED,
                    font=FONT_UI,
                ).grid(row=0, column=0, columnspan=field_column_count, pady=24)
            update_field_scrollregion()
            list_canvas.yview_moveto(0.0)
            update_selected_count()

        def select_visible(value: bool) -> None:
            for key, _meaning in visible_specs:
                if key != "code":
                    field_vars[key].set(value)
            render_fields()

        def use_bandwidth_defaults() -> None:
            selected = set(BANDWIDTH_REQUEST_FIELDS)
            for key, variable in field_vars.items():
                variable.set(key in selected)
            render_fields()

        search_var.trace_add("write", render_fields)
        render_fields()

        for label, command, color in (
            ("全选当前筛选", lambda: select_visible(True), CYAN),
            ("清空当前筛选", lambda: select_visible(False), PINK),
            ("恢复省带宽默认", use_bandwidth_defaults, AMBER),
        ):
            tk.Button(
                control_row,
                text=label,
                command=command,
                bg=SURFACE_2,
                fg=color,
                activebackground=CYAN_DARK,
                activeforeground=WHITE,
                relief="flat",
                bd=0,
                padx=8,
                pady=2,
                font=FONT_UI,
            ).pack(side="left", padx=(0, 6))

        def close_dialog() -> None:
            self.field_selector_window = None
            try:
                dialog.destroy()
            except tk.TclError:
                pass

        def apply_selection() -> None:
            selected = [
                key for key, _meaning in D101_FIELD_CATALOG
                if field_vars[key].get()
            ]
            if not selected:
                messagebox.showwarning("字段不能为空", "至少保留一个字段。", parent=dialog)
                return
            if "code" not in selected:
                selected.insert(0, "code")
            self.custom_field_keys = selected
            self.field_profile_key = "custom"
            self.field_profile_var.set(FIELD_PROFILE_LABELS["custom"])
            close_dialog()
            self._field_selection_changed(f"已选择 {len(selected)} 个原始字段")

        tk.Button(
            control_row,
            text="取消",
            command=close_dialog,
            bg=SURFACE_2,
            fg=TEXT_SOFT,
            activebackground=CYAN_DARK,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            padx=14,
            pady=4,
            font=FONT_UI,
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            control_row,
            text="应用并返回",
            command=apply_selection,
            bg=CYAN,
            fg=BG,
            activebackground=WHITE,
            activeforeground=BG,
            relief="flat",
            bd=0,
            padx=14,
            pady=4,
            font=FONT_UI_BOLD,
        ).pack(side="left", padx=(0, 6))
        search_entry.focus_set()

    def _on_universe_selected(self, _event: tk.Event) -> None:
        was_active = self.connected or self.connecting
        self.subscription_mode_var.set("market")
        self._sync_subscription_controls()
        self._add_event("SYS", "已选择市场池：代码输入和 limit 规则已停用", CYAN)
        if was_active:
            self.disconnect(silent=True)
            self._add_event("SYS", "市场池已改变，请点击连接使新市场生效", AMBER)
        self.schedule_draw()

    def _set_subscription_mode(self, mode: str) -> None:
        if mode not in {"market", "codes"} or mode == self.subscription_mode_var.get():
            return
        was_active = self.connected or self.connecting
        self.subscription_mode_var.set(mode)
        self._sync_subscription_controls()
        if mode == "market":
            self._add_event("SYS", "订阅模式：市场池", CYAN)
        else:
            self._add_event("SYS", "订阅模式：自定义代码", PURPLE)
        if was_active:
            self.disconnect(silent=True)
            self._add_event("SYS", "订阅方式已改变，请确认参数后点击连接", AMBER)
        self.schedule_draw()

    def _place_table(self, rect: tuple[float, float, float, float]) -> None:
        x1, y1, x2, y2 = rect
        tree_x = int(x1 + 14)
        tree_y = int(y1 + 50)
        tree_w = max(320, int(x2 - x1 - 32))
        tree_h = max(120, int(y2 - y1 - 70))
        scroll_w = 16
        self.data_tree.place(x=tree_x, y=tree_y, width=tree_w - scroll_w, height=tree_h)
        if self.rows_by_mode[self.mode]:
            self.empty_state_label.place_forget()
            self.vertical_scroll.place(x=x2 - 17, y=tree_y, width=16, height=tree_h)
            self.horizontal_scroll.place(x=tree_x, y=y2 - 19, width=tree_w - scroll_w, height=16)
        else:
            self.vertical_scroll.place_forget()
            self.horizontal_scroll.place_forget()
            empty_text = (
                "等待推送数据\n\n点击右上角“连接”开始订阅"
                if not (self.connected or self.connecting)
                else "已连接，等待服务端推送数据…"
            )
            self.empty_state_label.configure(text=empty_text)
            self.empty_state_label.place(
                x=tree_x,
                y=tree_y + TABLE_HEADING_HEIGHT,
                width=tree_w - scroll_w,
                height=max(60, tree_h - TABLE_HEADING_HEIGHT),
            )
            self.empty_state_label.lift()

    def _visible_table_row_count(self) -> int:
        """根据当前控件高度估算可见行数，虚表只维护这部分 Treeview item。"""

        try:
            row_height = int(
                ttk.Style(self.root).lookup("D101.Treeview", "rowheight")
                or TABLE_ROW_HEIGHT_FALLBACK
            )
        except (TypeError, ValueError, tk.TclError):
            row_height = TABLE_ROW_HEIGHT_FALLBACK
        height = max(1, int(self.data_tree.winfo_height()))
        return max(1, (height - TABLE_HEADING_HEIGHT) // max(1, row_height))

    def _table_order_for_mode(self, mode: str) -> list[str]:
        """只在行集合或排序键改变时排序，普通行情更新不重复排序几千行。"""

        if mode in self._table_order_dirty:
            table_rows = self.rows_by_mode[mode]
            self._table_orders[mode] = [
                key
                for key, _row in sorted(
                    table_rows.items(),
                    key=lambda item: self._table_sort_key(mode, item[0], item[1]),
                )
            ]
            self._table_order_dirty.discard(mode)
        return self._table_orders[mode]

    def _update_virtual_scrollbar(self) -> None:
        order = self._table_order_for_mode(self.mode)
        total = len(order)
        visible = max(1, self._virtual_visible_rows)
        if total <= visible:
            self.vertical_scroll.set(0.0, 1.0)
            return
        maximum = total - visible
        offset = min(max(self._virtual_offsets[self.mode], 0), maximum)
        self._virtual_offsets[self.mode] = offset
        self.vertical_scroll.set(offset / total, min(1.0, (offset + visible) / total))

    def _virtual_at_bottom(self) -> bool:
        order = self._table_order_for_mode(self.mode)
        if not order:
            return False
        visible = max(1, self._virtual_visible_rows)
        return self._virtual_offsets[self.mode] >= max(0, len(order) - visible)

    def _maybe_load_market_event_history(self) -> None:
        if self.mode != "market_event":
            return
        at_bottom = self._virtual_at_bottom()
        if at_bottom and not self.market_event_scroll_at_bottom:
            self.market_event_scroll_at_bottom = True
            self.root.after_idle(self.load_previous_market_event)
        elif not at_bottom:
            self.market_event_scroll_at_bottom = False

    def _clear_virtual_tree(self) -> None:
        for iid in self.data_tree.get_children(""):
            self.data_tree.delete(iid)
        for mapping in self.tree_iids.values():
            mapping.clear()
        self.tree_key_by_iid.clear()
        self._virtual_slot_ids.clear()
        self._virtual_rendered_rows = 0

    def _on_tree_yview(self, _first: str = "", _last: str = "") -> None:
        # Treeview 的原生分数只反映“窗口内的少量 item”，这里改用全量缓存计算滚动条。
        self._update_virtual_scrollbar()
        self._maybe_load_market_event_history()

    def _on_horizontal_scroll(self, *args: str) -> None:
        """合并拖动过程中的重复位置，避免每个鼠标事件都触发表格重绘。"""

        if not args:
            return
        self._horizontal_pending_command = tuple(str(arg) for arg in args)
        if self._horizontal_scroll_job is None:
            self._horizontal_scroll_job = self.root.after(
                HORIZONTAL_SCROLL_COALESCE_MS,
                self._flush_horizontal_scroll,
            )

    def _flush_horizontal_scroll(self) -> None:
        self._horizontal_scroll_job = None
        command = self._horizontal_pending_command
        self._horizontal_pending_command = None
        if not command or not self._horizontal_columns_signature:
            return

        operation = command[0]
        try:
            if operation == "moveto" and len(command) >= 2:
                fraction = min(1.0, max(0.0, float(command[1])))
                target_px = fraction * self._horizontal_total_width
                target = max(0, bisect_right(self._horizontal_column_prefix, target_px) - 1)
            elif operation == "scroll" and len(command) >= 2:
                amount = int(command[1])
                step = (
                    max(1, len(self._horizontal_display_columns) - 1)
                    if len(command) >= 3 and command[2] == "pages"
                    else 1
                )
                target = self._horizontal_start_column + amount * step
            else:
                return
        except (TypeError, ValueError):
            return

        maximum = max(0, len(self._horizontal_columns_signature) - 1)
        self._horizontal_start_column = min(max(0, target), maximum)
        self._refresh_horizontal_columns()

    def _refresh_horizontal_columns(self, columns: tuple[str, ...] | None = None) -> None:
        """只把当前可视列交给 Treeview，横向拖动不再重绘全部字段列。"""

        if columns is None:
            columns = tuple(self.table_columns.get(self.mode, ()))
        if not columns:
            self._horizontal_columns_signature = ()
            self._horizontal_display_columns = ()
            self._horizontal_column_widths = ()
            self._horizontal_column_prefix = (0,)
            self._horizontal_total_width = 0
            self._horizontal_view_width = max(1, int(self.data_tree.winfo_width()))
            self.data_tree.configure(displaycolumns=())
            self.horizontal_scroll.set(0.0, 1.0)
            return

        view_width = max(1, int(self.data_tree.winfo_width()))
        widths = tuple(max(64, self._table_column_width(column)) for column in columns)
        prefix: list[int] = [0]
        for width in widths:
            prefix.append(prefix[-1] + width)
        total_width = prefix[-1]
        signature_changed = columns != self._horizontal_columns_signature or self.mode != self._horizontal_mode
        if signature_changed:
            self._horizontal_start_column = 0
        self._horizontal_mode = self.mode
        self._horizontal_columns_signature = columns
        self._horizontal_column_widths = widths
        self._horizontal_column_prefix = tuple(prefix)
        self._horizontal_total_width = total_width
        self._horizontal_view_width = view_width
        maximum = max(0, len(columns) - 1)
        self._horizontal_start_column = min(max(0, self._horizontal_start_column), maximum)

        if total_width <= view_width:
            start = 0
            display = columns
        else:
            start = self._horizontal_start_column
            end = start
            visible_width = 0
            while end < len(columns) and (visible_width < view_width or end == start):
                visible_width += widths[end]
                end += 1
            display = columns[start:end]

        if display != self._horizontal_display_columns:
            self.data_tree.configure(displaycolumns=display)
            self._horizontal_display_columns = display

        if total_width <= view_width:
            self.horizontal_scroll.set(0.0, 1.0)
        else:
            first = prefix[start] / total_width
            last = min(1.0, (prefix[start] + view_width) / total_width)
            self.horizontal_scroll.set(first, last)

    def _on_vertical_scroll(self, *args: str) -> None:
        """把滚动条命令换算成缓存行偏移，再重用固定数量的 Treeview item。"""

        if not args:
            return
        mode = self.mode
        order = self._table_order_for_mode(mode)
        visible = max(1, self._visible_table_row_count())
        self._virtual_visible_rows = visible
        maximum = max(0, len(order) - visible)
        current = self._virtual_offsets[mode]
        command = str(args[0])
        try:
            if command == "moveto" and len(args) >= 2:
                fraction = min(1.0, max(0.0, float(args[1])))
                target = int(round(fraction * maximum))
            elif command == "scroll" and len(args) >= 2:
                amount = int(args[1])
                what = str(args[2]) if len(args) >= 3 else "units"
                step = visible if what == "pages" else 3
                target = current + amount * step
            else:
                return
        except (TypeError, ValueError):
            return
        target = min(max(0, target), maximum)
        if target != current:
            self._virtual_offsets[mode] = target
            self._refresh_table()
        else:
            self._update_virtual_scrollbar()
            self._maybe_load_market_event_history()

    def _virtual_scroll_rows(self, delta: int) -> None:
        mode = self.mode
        order = self._table_order_for_mode(mode)
        visible = max(1, self._visible_table_row_count())
        maximum = max(0, len(order) - visible)
        target = min(max(0, self._virtual_offsets[mode] + int(delta)), maximum)
        if target != self._virtual_offsets[mode]:
            self._virtual_offsets[mode] = target
            self._virtual_visible_rows = visible
            self._refresh_table()

    def _on_tree_mousewheel(self, event: tk.Event) -> str:
        delta = int(getattr(event, "delta", 0) or 0)
        if delta:
            steps = -int(delta / 120) * 3
            if steps == 0:
                steps = -1 if delta > 0 else 1
            self._virtual_scroll_rows(steps)
        return "break"

    def _on_tree_button_scroll(self, event: tk.Event) -> str:
        self._virtual_scroll_rows(-3 if getattr(event, "num", 0) == 4 else 3)
        return "break"

    def _on_tree_key_scroll(self, event: tk.Event) -> str:
        visible = max(1, self._visible_table_row_count())
        keys = {
            "Up": -1,
            "Down": 1,
            "Prior": -visible,
            "Next": visible,
            "Home": -10**9,
            "End": 10**9,
        }
        delta = keys.get(str(getattr(event, "keysym", "")))
        if delta is not None:
            self._virtual_scroll_rows(delta)
        return "break"

    # ── 网络和数据 ──────────────────────────────────────────────────────

    def _enqueue_state(self, session_id: int, state: str, text: str) -> None:
        self.queue.put((session_id, "state", (state, text)))

    def _enqueue_message(self, session_id: int, raw: str) -> None:
        self.queue.put((session_id, "message", raw))

    def toggle_connection(self) -> None:
        if self.connected or self.connecting:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        if websocket is None:
            messagebox.showerror(
                "缺少依赖",
                f"此面板需要 websocket-client。\n\n{websocket_install_hint()}",
                parent=self.root,
            )
            return
        url = self.endpoint_var.get().strip()
        if not url.startswith(("ws://", "wss://")):
            self._add_event("ERR", "连接地址必须以 ws:// 或 wss:// 开头", PINK)
            self.connection_text = "地址无效"
            self.schedule_draw()
            return
        codes = split_codes(self.codes_var.get())
        use_market = self.mode == "snapshot" and self.subscription_mode_var.get() == "market"
        universe = UNIVERSE_OPTIONS.get(self.universe_var.get(), "") if use_market else ""
        if self.mode == "snapshot" and not universe and not codes:
            self._add_event("ERR", "选择全市场，或至少填写一个自定义代码", PINK)
            return

        limit = 0
        if universe:
            try:
                limit = max(0, min(int(self.limit_var.get().strip() or "0"), 65535))
            except ValueError:
                self._add_event("ERR", "limit 必须是 0 到 65535 的整数", PINK)
                return

        self.disconnect(silent=True)
        self.session_id += 1
        sid = self.session_id
        if self.mode == "market_event":
            self.market_event_cursor = None
            self.market_event_loading = False
            self.market_event_has_more = True
            self.market_event_history_pages = 0
            self.market_event_scroll_at_bottom = False
            self.market_event_request_seq = max(1000, (sid * 1000) % 60000)
        if self.mode == "snapshot":
            selected_fields = self._prepared_snapshot_fields()
            command = build_snapshot_commands(
                codes,
                sid,
                selected_fields,
                universe=universe,
                limit=limit,
            )
            self._add_event(
                "FIELD",
                f"将请求 {len(selected_fields)} 个原始字段，使用一条 snapshot 订阅命令；"
                f"超过 {MAX_CODES_PER_CONNECTION} 只代码时由服务端按容量拆分；本地计算字段不重复请求",
                CYAN,
            )
        else:
            command = build_command(
                self.mode,
                codes,
                sid,
                universe=universe,
                limit=limit,
            )
        self.connected = False
        self.connecting = True
        self.connection_text = "连接中"
        self._add_event("SYS", f"正在连接 {url}", CYAN)
        self.stream = D101Stream(
            url,
            command,
            lambda state, text, sid=sid: self._enqueue_state(sid, state, text),
            lambda raw, sid=sid: self._enqueue_message(sid, raw),
        )
        self.stream.start()
        self.schedule_draw()

    def disconnect(self, silent: bool = False) -> None:
        self.session_id += 1
        stream = self.stream
        self.stream = None
        self.connected = False
        self.connecting = False
        self.connection_text = "已断开"
        self.market_event_loading = False
        if stream is not None:
            stream.stop()
        if not silent:
            self._add_event("SYS", "已断开 d101 数据流", MUTED)
        self.schedule_draw()

    def change_mode(self, mode: str) -> None:
        if mode not in MODE_INFO or mode == self.mode:
            return
        was_active = self.connected or self.connecting
        if was_active:
            self.disconnect(silent=True)
        self.mode = mode
        self.selected_code = ""
        self._add_event("MODE", f"切换到：{MODE_INFO[mode][0]}", MODE_INFO[mode][2])
        if was_active:
            self.connect()
        self.schedule_draw()

    def _next_market_event_request_seq(self) -> int:
        self.market_event_request_seq = self.market_event_request_seq % 65535 + 1
        return self.market_event_request_seq

    def load_previous_market_event(self) -> None:
        """滚动到列表底部或点击按钮时，向服务端请求更早的一页。"""

        if self.mode != "market_event" or self.market_event_loading or not self.market_event_has_more:
            return
        if not self.connected or self.stream is None:
            self._add_event("SYS", "先连接盘口异动数据流", MUTED)
            return
        if self.market_event_cursor is None:
            self._add_event("SYS", "当前页还没有完整游标，等待盘口异动数据", MUTED)
            return
        command = build_market_event_history_command(
            self._next_market_event_request_seq(),
            self.market_event_cursor,
            count=-100,
        )
        if self.stream.send(command):
            self.market_event_loading = True
            self.market_event_history_pages += 1
            self._add_event("HIST", f"正在加载更早异动 · 游标 {display_time(self.market_event_cursor['time'])}", AMBER)
            self.schedule_draw()

    def drain_queue(self) -> None:
        changed = False
        for _ in range(120):
            try:
                sid, kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if sid != self.session_id:
                continue
            if kind == "state":
                state, text = payload
                self._handle_state(state, text)
                changed = True
            elif kind == "message":
                self._handle_message(str(payload))
                changed = True
        if changed:
            self.schedule_draw()
        self.root.after(QUEUE_DRAIN_INTERVAL_MS, self.drain_queue)

    def _handle_state(self, state: str, text: str) -> None:
        if state == "connecting":
            self.connecting = True
            self.connected = False
            self.connection_text = "连接中"
        elif state in {"connected", "subscribed"}:
            self.connecting = False
            self.connected = True
            self.connection_text = "在线"
        elif state == "retry":
            self.connecting = True
            self.connected = False
            self.connection_text = "重试中"
        elif state == "error":
            self.error_count += 1
            self.connection_text = "异常"
            self._add_event("ERR", text, PINK)
        else:
            self.connection_text = text
        if state not in {"connected", "subscribed"}:
            self._add_event("NET", text, CYAN if state == "connecting" else MUTED)

    def _handle_message(self, raw: str) -> None:
        self.message_count += 1
        self.last_message_at = time.time()
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.error_count += 1
            self._add_event("ERR", f"收到无法解析的 JSON：{exc}", PINK)
            return
        if not isinstance(message, dict):
            return
        items = message.get("list", [])
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "info":
                message = self._neutral_message(item.get("msg"))
                self._add_event("INFO", message, CYAN)
            elif item_type == "error":
                self.error_count += 1
                message = self._neutral_message(item.get("msg"))
                self._add_event("ERR", message, PINK)
                if self.mode == "market_event":
                    self.market_event_loading = False
            elif item_type == "snapshot":
                self._handle_snapshot(item.get("data", []))
            elif item_type == "market_event":
                self._handle_market_event(item)
            elif item_type == "diag":
                self._add_event("DIAG", self._neutral_message(item.get("msg")), MUTED)

    @staticmethod
    def _neutral_message(value: Any) -> str:
        """服务端消息只做诊断展示，不将其当成业务状态机。"""

        if value is None:
            return "收到服务通知"
        text = str(value).replace("\r", " ").replace("\n", " ").strip()
        return text[:120] if text else "收到服务通知"

    def _handle_snapshot(self, rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            row = add_local_computed_fields(row)
            incoming_local_fields = set(row.pop("__local_fields", ()))
            code = row.get("code")
            if not isinstance(code, str) or not code:
                continue
            code = code.upper()
            quote = self.quotes.setdefault(code, Quote(code))
            old_price = quote.display.get("_price")
            cached_local_fields = set(quote.data.get("__local_fields", ()))
            for key in LOCAL_COMPUTED_FIELDS:
                if key in row and key not in incoming_local_fields:
                    # 这一帧明确带来了服务端原始字段，不能继续沿用旧的
                    # 本地计算标记；显式 null 也按无效值保留。
                    cached_local_fields.discard(key)
            quote.data.update(row)  # 增量行：缺失键保留，显式 null 保留为无效
            quote.data["__local_fields"] = tuple(
                sorted(cached_local_fields | incoming_local_fields)
            )
            quote.data = add_local_computed_fields(quote.data)
            current_price = quote.display.get("_price")
            if current_price is not None and current_price != old_price:
                quote.history.append(current_price)
            quote.updates += 1
            quote.received_at = time.time()
            table_row = dict(quote.data)
            table_row["code"] = code
            self._upsert_table_row("snapshot", code, table_row, merge=True)
            self.row_count += 1
            if not self.selected_code:
                self.selected_code = code

    def _handle_market_event(self, payload: Any) -> None:
        outer_code = ""
        if isinstance(payload, dict):
            rows = payload.get("data", [])
            outer_code = str(payload.get("code") or "")
        else:
            rows = payload
        if not isinstance(rows, list):
            return
        history_page = self.market_event_loading
        valid_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or outer_code or "—").upper()
            event_name = str(row.get("type_name") or "异动事件")
            info = str(row.get("info") or "").replace("\r", " ").replace("\n", " ").strip()
            event_time = self._market_event_int(row.get("time"))
            event_seq = self._market_event_int(row.get("seq"))
            valid_cursor = event_time > 0 and event_seq > 0
            if valid_cursor:
                valid_rows.append(row)
            key = self._market_event_key(row, code)
            quote = self.quotes.get(code)
            cached_name = quote.data.get("name") if quote else None
            table_row = {
                "pk_time": display_time(event_time) if event_time else "—",
                "pk_name": str(cached_name or row.get("name") or "—"),
                "code": code,
                "pk_type_name": event_name,
                "pk_value": self._market_event_value_text(row),
                "pk_detail": self._market_event_detail_text(row),
                "__market_event_time": event_time,
                "__market_event_seq": event_seq,
                "__market_event_color": row.get("type_color"),
            }
            self._upsert_table_row("market_event", key, table_row)
            message = f"{code}  {event_name}"
            if info:
                message += f"  ·  {info[:56]}"
            self._add_event("EVENT", message, DOWN if row.get("type_color") == 1 else UP)
            self.row_count += 1
        if valid_rows and (self.market_event_cursor is None or history_page):
            last = valid_rows[-1]
            self.market_event_cursor = {
                "time": self._market_event_int(last.get("time")),
                "seq": self._market_event_int(last.get("seq")),
            }
        if history_page:
            self.market_event_loading = False
        if not rows and history_page:
            self.market_event_loading = False
            self.market_event_has_more = False
            self._add_event("HIST", "已经加载到当前游标之前的最早记录", MUTED)

    @staticmethod
    def _market_event_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _market_event_key(self, row: dict[str, Any], code: str) -> str:
        event_time = self._market_event_int(row.get("time"))
        event_seq = self._market_event_int(row.get("seq"))
        if event_time > 0 and event_seq > 0:
            return f"{event_time}:{event_seq}:{code}"
        try:
            fingerprint = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            fingerprint = repr(row)
        return f"fallback:{code}:{fingerprint}"

    @staticmethod
    def _market_event_numbers(info: Any) -> list[float]:
        text = str(info or "")
        values: list[float] = []
        for token in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text):
            try:
                values.append(float(token))
            except ValueError:
                pass
        return values

    @staticmethod
    def _market_event_price(value: float) -> str:
        return f"{value:.2f}"

    @staticmethod
    def _market_event_percent(value: float) -> str:
        return f"{value * 100:+.2f}%"

    @staticmethod
    def _market_event_lots(value: float) -> str:
        if abs(value) >= 10000:
            return f"{value / 10000:.2f}万手"
        return f"{value:,.0f}手"

    def _market_event_value_text(self, row: dict[str, Any]) -> str:
        name = str(row.get("type_name") or "")
        values = self._market_event_numbers(row.get("info"))
        if not values:
            return "—"
        if "大笔买" in name or "大笔卖" in name:
            return self._market_event_lots(values[1] if len(values) > 1 else values[0])
        if "有大" in name or "打开" in name:
            return self._market_event_price(values[1] if len(values) > 1 else values[0])
        if "封" in name:
            return self._market_event_price(values[0])
        if "缺口" in name or "涨停" in name or "跌停" in name:
            return self._market_event_price(values[0])
        return self._market_event_percent(values[0])

    def _market_event_detail_text(self, row: dict[str, Any]) -> str:
        name = str(row.get("type_name") or "")
        values = self._market_event_numbers(row.get("info"))
        if not values:
            return "—"
        if "大笔买" in name or "大笔卖" in name:
            detail = [f"价 {self._market_event_price(values[0])}"]
            if len(values) > 1:
                detail.append(f"量 {self._market_event_lots(values[1])}")
            if len(values) > 3:
                detail.append(f"额 {compact_number(values[3])}")
            return " · ".join(detail)
        if "有大" in name or "打开" in name:
            detail = [f"量 {self._market_event_lots(values[0])}"]
            if len(values) > 1:
                detail.append(f"价 {self._market_event_price(values[1])}")
            if len(values) > 2:
                detail.append(f"涨跌 {self._market_event_percent(values[2])}")
            if len(values) > 3:
                detail.append(f"额 {compact_number(values[3])}")
            return " · ".join(detail)
        if "封" in name:
            detail = [f"价 {self._market_event_price(values[0])}"]
            if len(values) > 1:
                detail.append(f"涨跌 {self._market_event_percent(values[1])}")
            return " · ".join(detail)
        if len(values) > 1:
            return f"涨跌 {self._market_event_percent(values[0])} · 价 {self._market_event_price(values[1])}"
        return f"指标 {self._market_event_percent(values[0])}"

    def _upsert_table_row(
        self,
        mode: str,
        key: str,
        data: dict[str, Any],
        merge: bool = False,
    ) -> None:
        rows = self.rows_by_mode[mode]
        current = rows.get(key) if merge else None
        is_new = current is None
        old_code = current.get("code") if current is not None else None
        old_name = current.get("name") if current is not None else None
        if current is None:
            current = {}
            rows[key] = current
        current.update(data)
        current["__kind"] = mode
        current["__updated"] = time.time()
        self.table_ordinal += 1
        current["__ordinal"] = self.table_ordinal
        if is_new or old_code != current.get("code") or old_name != current.get("name"):
            self._table_order_dirty.add(mode)
        if is_new:
            self._table_columns_dirty.add(mode)
        if mode == "market_event" and len(rows) > 5000:
            oldest_key = min(
                rows,
                key=lambda item: (
                    rows[item].get("__market_event_time", 0),
                    rows[item].get("__market_event_seq", 0),
                ),
            )
            if oldest_key != key:
                rows.pop(oldest_key, None)
                self._table_order_dirty.add(mode)

    def _first_code(self) -> str:
        codes = split_codes(self.codes_var.get())
        return codes[0] if codes else ""

    # ── 绘制 ─────────────────────────────────────────────────────────────

    def schedule_draw(self) -> None:
        if self._draw_pending:
            return
        elapsed = time.monotonic() - self._last_paint_monotonic
        wait_ms = max(0.0, UI_REFRESH_INTERVAL_MS - elapsed * 1000.0)
        self._draw_pending = True
        if wait_ms <= 0:
            self.root.after_idle(self._draw)
        else:
            self.root.after(max(1, int(wait_ms)), self._draw)

    def _draw(self) -> None:
        self._draw_pending = False
        canvas = self.canvas
        width = max(canvas.winfo_width(), 1180)
        height = max(canvas.winfo_height(), 700)
        canvas.delete("all")
        self.layout = {}
        self._draw_background(width, height)
        self._draw_header(width)
        toolbar_y = 70
        self._place_widgets(width, toolbar_y)
        self._draw_toolbar(width, toolbar_y)
        toolbar_height = {"snapshot": 116, "market_event": 60}[self.mode]
        tabs_y = toolbar_y + toolbar_height + 10
        self._draw_tabs(width, tabs_y)
        self._draw_stats(width, tabs_y + 48)

        table_y = tabs_y + 112
        table = (28, table_y, width - 28, height - 24)
        self.layout["table"] = table
        self._draw_table_shell(table)
        self._place_table(table)
        self._refresh_table()
        self.last_draw_at = time.time()
        self._last_paint_monotonic = time.monotonic()

    def _draw_background(self, width: int, height: int) -> None:
        c = self.canvas
        c.create_rectangle(0, 0, width, height, fill=BG, outline="")
        for x in range(0, width, 72):
            c.create_line(x, 0, x, height, fill="#0c1726", width=1)
        for y in range(0, height, 72):
            c.create_line(0, y, width, y, fill="#0c1726", width=1)
        c.create_oval(width - 500, -240, width + 130, 370, fill="#0b1e35", outline="")
        c.create_oval(-280, height - 220, 300, height + 340, fill="#0b182b", outline="")
        c.create_line(28, 0, width - 28, 0, fill=CYAN, width=2)

    def _draw_header(self, width: int) -> None:
        c = self.canvas
        c.create_rectangle(0, 0, width, 64, fill="#09111e", outline="")
        c.create_line(28, 63, width - 28, 63, fill="#1c3a56", width=1)
        # 左侧紧凑产品标识
        c.create_rectangle(30, 23, 35, 51, fill=CYAN, outline="")
        c.create_rectangle(40, 30, 45, 51, fill=PURPLE, outline="")
        c.create_rectangle(50, 37, 55, 51, fill=PINK, outline="")
        c.create_text(72, 34, text="达塔接口  ·  d101", anchor="w", fill=AMBER, font=("Microsoft YaHei UI", 18, "bold"))
        c.create_text(width - 244, 11, text="d101 · data interface", anchor="e", fill="#17304a", font=FONT_MONO_SMALL)
        privacy_rect = (width - 410, 24, width - 260, 55)
        self.layout["privacy"] = privacy_rect
        self._button(
            privacy_rect,
            "恢复中文名" if self.privacy_mode else "隐藏中文名",
            AMBER if self.privacy_mode else BORDER_BRIGHT,
            "privacy",
            filled=self.privacy_mode,
        )

        status_color = CYAN if self.connected else (AMBER if self.connecting else MUTED)
        status_text = "●  " + self.connection_text.upper()
        self._pill(width - 224, 24, width - 32, 55, status_text, status_color, status_color == CYAN)
        c.create_text(width - 32, 57, text="F11 全屏  ·  ESC 退出全屏", anchor="e", fill="#58728f", font=("Microsoft YaHei UI", 8))

    def _draw_toolbar(self, width: int, y: int) -> None:
        toolbar_height = {"snapshot": 116, "market_event": 60}[self.mode]
        self._panel((28, y, width - 28, y + toolbar_height), accent=CYAN)
        c = self.canvas
        c.create_text(38, y + 11, text="WEBSOCKET 端点", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
        endpoint_w = min(360, max(270, int(width * 0.27)))
        c.create_text(
            98 + endpoint_w + 20,
            y + 11,
            text="当前 TAB：一条连接 · 一条订阅",
            anchor="w",
            fill="#58728f",
            font=("Microsoft YaHei UI", 8),
        )
        self._button(
            self.layout.get("connect", (width - 178, y + 16, width - 96, y + 49)),
            "断开" if self.connected or self.connecting else "连接",
            CYAN if not self.connected else PINK,
            "connect",
        )
        self._button(
            self.layout.get("clear", (width - 86, y + 16, width - 30, y + 49)),
            "清空",
            BORDER_BRIGHT,
            "clear",
        )

        if self.mode == "snapshot":
            toggle_x = 98
            toggle_w = 178
            source_x = toggle_x + toggle_w + 18
            using_universe = self.subscription_mode_var.get() == "market"
            self._button(
                self.layout["subscription_market"],
                "市场池",
                CYAN if using_universe else BORDER_BRIGHT,
                "subscription_market",
                filled=using_universe,
            )
            self._button(
                self.layout["subscription_codes"],
                "自定义代码",
                PURPLE if not using_universe else BORDER_BRIGHT,
                "subscription_codes",
                filled=not using_universe,
            )
            c.create_text(38, y + 62, text="订阅方式", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
            if using_universe:
                source_w = min(300, max(250, int(width * 0.20)))
                limit_x = source_x + source_w + 18
                c.create_text(source_x, y + 39, text="市场池", anchor="w", fill=CYAN, font=FONT_MONO_SMALL)
                c.create_text(limit_x, y + 39, text="limit（0=全量）", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
                c.create_text(width - 31, y + 62, text="市场池订阅", anchor="e", fill=CYAN, font=("Microsoft YaHei UI", 8))
            else:
                c.create_text(source_x, y + 39, text="代码（支持交易所|代码）", anchor="w", fill=PURPLE, font=FONT_MONO_SMALL)
                c.create_text(width - 31, y + 62, text="自定义代码订阅", anchor="e", fill=PURPLE, font=("Microsoft YaHei UI", 8))

            field_button = self.layout["field_settings"]
            c.create_text(38, y + 99, text="请求字段", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
            self._button(field_button, "字段设置", CYAN, "field_settings", filled=False)
            c.create_text(
                field_button[2] + 14,
                y + 99,
                text=self._field_summary(),
                anchor="w",
                fill=TEXT_SOFT,
                font=("Microsoft YaHei UI", 8),
            )
            return

        c.create_text(38, y + 38, text="数据类型", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
        c.create_text(98, y + 38, text="盘口异动事件流", anchor="w", fill=AMBER, font=FONT_UI)
        c.create_text(width - 31, y + 38, text="连接后接收市场异动事件", anchor="e", fill=TEXT_SOFT, font=("Microsoft YaHei UI", 8))

    def _draw_tabs(self, width: int, y: int) -> None:
        self._panel((28, y, width - 28, y + 40), accent=MODE_INFO[self.mode][2])
        c = self.canvas
        c.create_text(42, y + 20, text="数据 TAB", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
        tab_x = 128
        tab_w = 140
        for key in ("snapshot", "market_event"):
            rect = (tab_x, y + 6, tab_x + tab_w, y + 34)
            self.layout[f"tab_{key}"] = rect
            active = key == self.mode
            color = MODE_INFO[key][2]
            self._button(rect, MODE_INFO[key][0], color if active else BORDER_BRIGHT, f"tab_{key}", filled=active)
            tab_x += tab_w + 10
        c.create_text(width - 42, y + 20, text=MODE_INFO[self.mode][1], anchor="e", fill=TEXT_SOFT, font=FONT_UI)

    def _draw_stats(self, width: int, y: int) -> None:
        pad = 28
        gap = 12
        card_w = (width - pad * 2 - gap * 5) / 6
        current_rows = len(self.rows_by_mode[self.mode])
        cards = [
            ("当前 TAB 行数", f"{current_rows:,}", MODE_INFO[self.mode][2]),
            ("累计推送行", f"{self.row_count:,}", PURPLE),
            ("消息帧", f"{self.message_count:,}", AMBER),
            ("订阅范围", self._subscription_text(), CYAN),
            ("请求字段", self._field_summary_short(), PURPLE),
            ("最近消息", self._age_text(), DOWN),
        ]
        for index, (title, value, accent) in enumerate(cards):
            x1 = pad + index * (card_w + gap)
            rect = (x1, y, x1 + card_w, y + 60)
            self._panel(rect, accent=accent)
            c = self.canvas
            c.create_text(x1 + 16, y + 12, text=title.upper(), anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
            value_font = ("Segoe UI", 13 if len(value) > 9 else 18, "bold")
            c.create_text(x1 + 16, y + 39, text=value, anchor="w", fill=TEXT, font=value_font)
            c.create_rectangle(x1 + card_w - 18, y + 10, x1 + card_w - 14, y + 50, fill=accent, outline="")

    def _draw_table_shell(self, rect: tuple[float, float, float, float]) -> None:
        accent = MODE_INFO[self.mode][2]
        self._panel(rect, accent=accent)
        x1, y1, x2, y2 = rect
        c = self.canvas
        row_count = len(self.rows_by_mode[self.mode])
        title = "盘口异动 · 实时事件流" if self.mode == "market_event" else f"{MODE_INFO[self.mode][0]} · 实时行情表"
        c.create_text(x1 + 18, y1 + 20, text=title, anchor="w", fill=TEXT, font=("Microsoft YaHei UI", 12, "bold"))
        if self.mode == "market_event":
            more_rect = (x2 - 132, y1 + 7, x2 - 18, y1 + 35)
            self.layout["market_event_more"] = more_rect
            more_text = "加载中…" if self.market_event_loading else ("加载更早" if self.market_event_has_more else "没有更早")
            self._button(more_rect, more_text, AMBER if self.market_event_has_more else BORDER_BRIGHT, "market_event_more", filled=False)
            c.create_text(x2 - 148, y1 + 20, text=f"{row_count:,} 条  ·  滚到底部自动拼接历史", anchor="e", fill=MUTED, font=FONT_MONO_SMALL)
        else:
            c.create_text(x2 - 18, y1 + 20, text=f"{row_count:,} 行  ·  窗口化渲染可见行  ·  横向滚动查看已选字段", anchor="e", fill=MUTED, font=FONT_MONO_SMALL)
        c.create_line(x1 + 14, y1 + 39, x2 - 14, y1 + 39, fill=BORDER, width=1)

    def _refresh_table(self) -> None:
        mode = self.mode
        columns = self._table_columns_for_mode(mode)
        if columns != self.table_columns.get(mode):
            self.table_columns[mode] = columns
        current_tree_columns = tuple(self.data_tree["columns"])
        headings_ready = bool(columns) and bool(self.data_tree.heading(columns[0], "text"))
        columns_changed = current_tree_columns != columns or not headings_ready
        if columns_changed:
            self.data_tree.configure(columns=columns, displaycolumns=columns)
            for column in columns:
                self.data_tree.heading(column, text=TABLE_HEADINGS.get(column, column), anchor="w")
                self.data_tree.column(column, width=self._table_column_width(column), minwidth=64, stretch=False, anchor="w")

        if self._virtual_tree_mode != mode or columns_changed:
            self._clear_virtual_tree()
            self._virtual_tree_mode = mode

        order = self._table_order_for_mode(mode)
        total = len(order)
        visible = max(1, self._visible_table_row_count())
        self._virtual_visible_rows = visible
        maximum = max(0, total - visible)
        offset = min(max(self._virtual_offsets[mode], 0), maximum)
        self._virtual_offsets[mode] = offset
        render_count = min(max(0, total - offset), visible + VIRTUAL_TABLE_BUFFER_ROWS)

        # 调整固定的虚拟行槽位；无论缓存里有几千行，Tk 只持有几十个 item。
        while len(self._virtual_slot_ids) > render_count:
            iid = self._virtual_slot_ids.pop()
            if self.data_tree.exists(iid):
                self.data_tree.delete(iid)
        while len(self._virtual_slot_ids) < render_count:
            iid = f"virtual_row_{len(self._virtual_slot_ids)}"
            self.data_tree.insert("", "end", iid=iid, values=("",) * len(columns))
            self._virtual_slot_ids.append(iid)

        current_iids = self.tree_iids[mode]
        current_iids.clear()
        self.tree_key_by_iid.clear()
        table_rows = self.rows_by_mode[mode]
        for slot, key in enumerate(order[offset:offset + render_count]):
            row = table_rows.get(key, {})
            iid = self._virtual_slot_ids[slot]
            self.data_tree.item(
                iid,
                values=self._table_values(columns, row),
                tags=(self._table_tag(mode, row, offset + slot),),
            )
            current_iids[key] = iid
            self.tree_key_by_iid[iid] = key

        if mode == "snapshot":
            selected_iid = current_iids.get(self.selected_code)
            current_selection = self.data_tree.selection()
            if current_selection:
                self.data_tree.selection_remove(*current_selection)
            if selected_iid is not None:
                self.data_tree.selection_set(selected_iid)
        self._virtual_rendered_rows = render_count
        self._refresh_horizontal_columns(columns)
        self._update_virtual_scrollbar()
        self._maybe_load_market_event_history()

    def _table_columns_for_mode(self, mode: str) -> tuple[str, ...]:
        if mode not in self._table_columns_dirty:
            return self.table_columns[mode]
        preferred = list(TABLE_FALLBACK_COLUMNS[mode])
        allowed = set(preferred)
        keys: set[str]
        if mode == "snapshot":
            allowed.update(D101_FIELD_KEYS)
            requested = set(self._prepared_snapshot_fields())
            requested.update(LOCAL_COMPUTED_FIELDS)
            preferred = [
                column for column in preferred
                if column in requested or column in {"__kind", "__updated"}
            ]
            keys = set(preferred)
            keys.update(requested)
        else:
            keys = set(preferred)
        for row in self.rows_by_mode[mode].values():
            keys.update(
                key
                for key in row
                if key in allowed
            )
        preferred_set = set(preferred)
        if mode == "snapshot":
            extras = [key for key in D101_FIELD_KEYS if key in keys and key not in preferred_set]
            extras.extend(sorted(keys.difference(preferred_set).difference(D101_FIELD_KEYS)))
        else:
            extras = sorted(keys.difference(preferred_set))
        columns = tuple(preferred + extras)
        self.table_columns[mode] = columns
        self._table_columns_dirty.discard(mode)
        return columns

    @staticmethod
    def _table_sort_key(mode: str, key: str, row: dict[str, Any]) -> tuple[Any, ...]:
        if mode == "market_event":
            return (
                -int(row.get("__market_event_time", 0)),
                -int(row.get("__market_event_seq", 0)),
                -int(row.get("__ordinal", 0)),
            )
        return (str(row.get("code") or ""), str(row.get("name") or ""), key)

    @staticmethod
    def _table_tag(mode: str, row: dict[str, Any], index: int) -> str:
        parity = "even" if index % 2 == 0 else "odd"
        if mode == "market_event":
            color = row.get("__market_event_color")
            if color == 0:
                return f"{parity}_red"
            if color == 1:
                return f"{parity}_green"
            return f"{parity}_unknown"

        # change_pct 是原始百分数值，正负号不受显示缩放影响；若没有该
        # 字段，再用 price/pre_close 判断，兼容精简字段请求。
        change = safe_number(row.get("change_pct"))
        if change is None:
            price = safe_number(row.get("price", row.get("close")))
            pre_close = safe_number(row.get("pre_close", row.get("open")))
            if price is not None and pre_close is not None:
                change = price - pre_close
        if change is None or abs(change) < 1e-12:
            return f"{parity}_flat"
        return f"{parity}_{'up' if change > 0 else 'down'}"

    @staticmethod
    def _table_column_width(column: str) -> int:
        widths = {
            "__kind": 104,
            "__updated": 92,
            "code": 92,
            "name": 112,
            "price": 92,
            "change_pct": 92,
            "change_amt": 92,
            "amplitude": 92,
            "price_avg_diff": 112,
            "volume": 118,
            "amount": 132,
            "buy_sell_flag": 148,
            "info": 300,
            "industry_name": 130,
            "type_name": 150,
            "date": 104,
            "time": 92,
            "pk_time": 94,
            "pk_name": 120,
            "pk_type_name": 148,
            "pk_value": 118,
            "pk_detail": 360,
        }
        return widths.get(column, 112)

    def _table_values(self, columns: tuple[str, ...], row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(self._format_table_value(column, row.get(column), row) for column in columns)

    def _format_table_value(self, column: str, value: Any, row: dict[str, Any]) -> str:
        if column == "__kind":
            return MODE_INFO.get(str(value), ("服务信息" if value == "info" else "错误", "", MUTED))[0]
        if column == "__updated":
            try:
                return datetime.fromtimestamp(float(value)).strftime("%H:%M:%S.%f")[:-4]
            except (TypeError, ValueError, OSError):
                return "—"
        if value is None:
            return "—"
        if column == "buy_sell_flag":
            try:
                raw_flag = int(value)
            except (TypeError, ValueError):
                return str(value)
            label = CURRENT_VOLUME_FLAG_LABELS.get(raw_flag, "未知")
            return f"{label}({raw_flag})"
        if is_name_field(column):
            return display_name(str(value).replace("\r", " ").replace("\n", " ")[:260], self.privacy_mode)
        code = str(row.get("code") or "")
        if column in PRICE_FIELDS:
            decimals = display_decimal_num(row, code)
            return format_price(normalize_value(column, value, code, row), decimals)
        if column in PERCENT_FIELDS:
            return format_pct(normalize_value(column, value, code, row))
        if column in RATIO_FIELDS:
            normalized = normalize_value(column, value, code, row)
            return "—" if normalized is None else f"{normalized:.2f}"
        if column == "volume":
            return compact_volume(value)
        if column == "amount":
            return compact_number(value)
        if column == "time":
            return display_time(value)
        if column == "type_color":
            return {0: "红色", 1: "绿色"}.get(value, "—")
        if isinstance(value, (dict, list, tuple)):
            try:
                text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                text = str(value)
            return text[:260]
        return str(value).replace("\r", " ").replace("\n", " ")[:260]

    def _subscription_text(self) -> str:
        if self.mode == "market_event":
            suffix = " · 加载中" if self.market_event_loading else (f" · 历史 {self.market_event_history_pages} 页" if self.market_event_history_pages else "")
            return f"全市场异动{suffix}"
        universe = UNIVERSE_OPTIONS.get(self.universe_var.get(), "")
        if self.mode == "snapshot" and self.subscription_mode_var.get() == "market" and universe:
            try:
                limit = int(self.limit_var.get() or "0")
            except ValueError:
                limit = 0
            return "全市场" if limit == 0 else f"全市场 · {limit}"
        return f"自定义 · {len(split_codes(self.codes_var.get()))} 个"

    def _draw_watermark(self, rect: tuple[float, float, float, float]) -> None:
        """在图表背景层绘制固定视口的产品水印。"""
        x1, y1, x2, y2 = rect
        height = max(1.0, y2 - y1)
        for fraction in (0.34, 0.72):
            self.canvas.create_text(
                (x1 + x2) / 2,
                y1 + height * fraction,
                text="d101\ndata interface",
                anchor="center",
                justify="center",
                fill="#122235",
                font=FONT_WATERMARK,
            )

    def _draw_chart(self, rect: tuple[float, float, float, float]) -> None:
        self._panel(rect, accent=CYAN if self.mode == "snapshot" else PURPLE)
        x1, y1, x2, y2 = rect
        c = self.canvas
        self._draw_watermark(rect)
        selected = self.quotes.get(self.selected_code)
        selected_data = selected.display if selected else {}
        title = "行情脉冲" if self.mode == "snapshot" else "异动雷达"
        selected_name = display_name(str(selected_data.get("name") or "—"), self.privacy_mode)
        subtitle = "等待数据流" if not selected else f"{selected.code}  {selected_name}"
        c.create_text(x1 + 18, y1 + 20, text=title, anchor="w", fill=TEXT, font=FONT_UI_BOLD)
        c.create_text(x1 + 18, y1 + 43, text=subtitle, anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
        c.create_text(x2 - 18, y1 + 21, text=MODE_INFO[self.mode][1], anchor="e", fill=MUTED, font=("Microsoft YaHei UI", 8))
        plot = (x1 + 46, y1 + 66, x2 - 24, y2 - 30)
        px1, py1, px2, py2 = plot
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            gy = py1 + (py2 - py1) * fraction
            c.create_line(px1, gy, px2, gy, fill="#1a2d44", width=1)
            c.create_text(px1 - 8, gy, text="·", anchor="e", fill="#4a6782", font=FONT_MONO_SMALL)
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            gx = px1 + (px2 - px1) * fraction
            c.create_line(gx, py1, gx, py2, fill="#13243a", width=1)

        values: list[float] = []
        if selected is not None:
            values = list(selected.history)

        if len(values) < 2:
            c.create_text((px1 + px2) / 2, (py1 + py2) / 2, text="等待 d101 数据流…", fill="#52708e", font=("Microsoft YaHei UI", 13))
            c.create_text((px1 + px2) / 2, (py1 + py2) / 2 + 27, text="连接后这里会出现实时轨迹", fill="#344e69", font=FONT_MONO_SMALL)
            return

        low = min(values)
        high = max(values)
        if math.isclose(low, high):
            low -= 1.0
            high += 1.0
        def y_for(value: float) -> float:
            return py2 - (value - low) / (high - low) * (py2 - py1)

        points: list[float] = []
        for index, value in enumerate(values):
            x = px1 + index * (px2 - px1) / (len(values) - 1)
            points.extend((x, y_for(value)))
        area = [px1, py2, *points, px2, py2]
        c.create_polygon(area, fill="#102b45", outline="", stipple="gray25")
        c.create_line(*points, fill=CYAN, width=2, smooth=True)
        c.create_line(*points, fill="#b3f4ff", width=1, smooth=True)
        last_x, last_y = points[-2], points[-1]
        c.create_oval(last_x - 5, last_y - 5, last_x + 5, last_y + 5, fill=CYAN, outline=WHITE, width=1)
        c.create_text(px2, last_y - 14, text=f"{values[-1]:.2f}", anchor="e", fill=CYAN, font=FONT_MONO_SMALL)
        c.create_text(px1, py2 + 15, text=f"低 {low:.2f}", anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
        c.create_text(px2, py2 + 15, text=f"高 {high:.2f}", anchor="e", fill=MUTED, font=FONT_MONO_SMALL)

    def _draw_detail(self, rect: tuple[float, float, float, float]) -> None:
        self._panel(rect, accent=PINK)
        x1, y1, x2, y2 = rect
        c = self.canvas
        quote = self.quotes.get(self.selected_code)
        data = quote.display if quote else {}
        name = display_name(str(data.get("name") or "未选择标的"), self.privacy_mode)
        code = quote.code if quote else "—"
        price_decimals = display_decimal_num(data, code)
        c.create_text(x1 + 18, y1 + 20, text="焦点标的", anchor="w", fill=TEXT, font=FONT_UI_BOLD)
        c.create_text(x2 - 18, y1 + 20, text=code, anchor="e", fill=MUTED, font=FONT_MONO_SMALL)
        c.create_text(x1 + 18, y1 + 55, text=name, anchor="w", fill=TEXT, font=("Microsoft YaHei UI", 17, "bold"))
        price = data.get("_price")
        change = data.get("_change_pct")
        color = quote_color(change)
        c.create_text(x1 + 18, y1 + 96, text=format_price(price, price_decimals), anchor="w", fill=color if price is not None else MUTED, font=("Consolas", 27, "bold"))
        c.create_text(x1 + 166, y1 + 99, text=format_pct(change), anchor="w", fill=color, font=("Consolas", 13, "bold"))
        c.create_line(x1 + 18, y1 + 120, x2 - 18, y1 + 120, fill=BORDER, width=1)

        metrics = [
            ("今开", data.get("_open_price")),
            ("最高", data.get("_high")),
            ("最低", data.get("_low")),
            ("昨收", data.get("_pre_close")),
            ("成交量", compact_volume(data.get("volume"))),
            ("成交额", compact_number(data.get("amount"))),
        ]
        col_w = (x2 - x1 - 36) / 3
        for index, (label, value) in enumerate(metrics):
            col = index % 3
            row = index // 3
            xx = x1 + 18 + col * col_w
            yy = y1 + 143 + row * 43
            c.create_text(xx, yy, text=label, anchor="w", fill=MUTED, font=("Microsoft YaHei UI", 8))
            value_text = value if isinstance(value, str) else format_price(value, price_decimals)
            c.create_text(xx, yy + 20, text=value_text, anchor="w", fill=TEXT_SOFT, font=FONT_MONO_SMALL)

        book_y = y1 + 238
        if book_y + 70 < y2:
            c.create_text(x1 + 18, book_y, text="盘口", anchor="w", fill=MUTED, font=("Microsoft YaHei UI", 8))
            bid = data.get("_bid1_price")
            ask = data.get("_ask1_price")
            bid_vol = safe_number(data.get("bid1_vol"))
            ask_vol = safe_number(data.get("ask1_vol"))
            max_vol = max(bid_vol or 0, ask_vol or 0, 1)
            for index, (label, value, volume, color) in enumerate((("买一", bid, bid_vol, UP), ("卖一", ask, ask_vol, DOWN))):
                yy = book_y + 22 + index * 25
                c.create_text(x1 + 18, yy, text=label, anchor="w", fill=MUTED, font=FONT_MONO_SMALL)
                c.create_text(x1 + 64, yy, text=format_price(value, price_decimals), anchor="w", fill=color, font=FONT_MONO_SMALL)
                bar_x = x1 + 146
                bar_w = max(0.0, (x2 - 28 - bar_x) * min((volume or 0) / max_vol, 1.0))
                c.create_rectangle(bar_x, yy - 7, bar_x + bar_w, yy + 6, fill=color, outline="")
                c.create_text(x2 - 18, yy, text=compact_volume(volume), anchor="e", fill=TEXT_SOFT, font=FONT_MONO_SMALL)

        if quote is None:
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 + 25, text="点击左下行情表选择标的", fill="#526d88", font=FONT_UI)

    def _draw_table(self, rect: tuple[float, float, float, float]) -> None:
        self._panel(rect, accent=PURPLE)
        x1, y1, x2, y2 = rect
        c = self.canvas
        c.create_text(x1 + 18, y1 + 20, text="实时行情列表", anchor="w", fill=TEXT, font=FONT_UI_BOLD)
        c.create_text(x2 - 18, y1 + 20, text="按 code 合并增量 · 点击行查看焦点", anchor="e", fill=MUTED, font=("Microsoft YaHei UI", 8))
        header_y = y1 + 48
        c.create_rectangle(x1 + 12, header_y, x2 - 12, header_y + 28, fill=SURFACE_2, outline="")
        columns = [("代码", 0.02), ("名称", 0.18), ("最新价", 0.39), ("涨跌幅", 0.53), ("成交量", 0.66), ("成交额", 0.78), ("更新", 0.92)]
        for label, fraction in columns:
            c.create_text(x1 + 18 + (x2 - x1 - 36) * fraction, header_y + 14, text=label, anchor="w", fill=CYAN, font=("Microsoft YaHei UI", 8, "bold"))
        row_h = 30
        codes = list(self.quotes)
        requested = split_codes(self.codes_var.get())
        codes.sort(key=lambda code: (requested.index(code) if code in requested else 9999, code))
        for index, code in enumerate(codes):
            yy = header_y + 32 + index * row_h
            if yy + row_h > y2 - 10:
                break
            quote = self.quotes[code]
            data = quote.display
            selected = code == self.selected_code
            price_decimals = display_decimal_num(data, code)
            if selected:
                self._rounded_rect(x1 + 12, yy, x2 - 12, yy + row_h - 2, 5, "#17314b", "")
            elif index % 2 == 0:
                c.create_rectangle(x1 + 12, yy, x2 - 12, yy + row_h - 2, fill="#0d1828", outline="")
            color = quote_color(data.get("_change_pct"))
            values = [
                (code, TEXT_SOFT),
                (display_name(str(data.get("name") or "—")[:8], self.privacy_mode), TEXT),
                (format_price(data.get("_price"), price_decimals), color),
                (format_pct(data.get("_change_pct")), color),
                (compact_volume(data.get("volume")), TEXT_SOFT),
                (compact_number(data.get("amount")), TEXT_SOFT),
                (datetime.fromtimestamp(quote.received_at).strftime("%H:%M:%S"), MUTED),
            ]
            for (value, text_color), (_label, fraction) in zip(values, columns):
                c.create_text(x1 + 18 + (x2 - x1 - 36) * fraction, yy + 14, text=value, anchor="w", fill=text_color, font=FONT_MONO_SMALL)
        if not codes:
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2 + 12, text="连接 d101 后等待行情行…", fill="#526d88", font=FONT_UI)

    def _draw_events(self, rect: tuple[float, float, float, float]) -> None:
        self._panel(rect, accent=AMBER)
        x1, y1, x2, y2 = rect
        c = self.canvas
        c.create_text(x1 + 18, y1 + 20, text="活动流", anchor="w", fill=TEXT, font=FONT_UI_BOLD)
        c.create_text(x2 - 18, y1 + 20, text=f"错误 {self.error_count}", anchor="e", fill=PINK if self.error_count else MUTED, font=FONT_MONO_SMALL)
        row_h = 30
        visible = max(1, int((y2 - y1 - 50) / row_h))
        for index, event in enumerate(list(self.events)[-visible:]):
            yy = y1 + 44 + index * row_h
            color = event.get("color", MUTED)
            c.create_oval(x1 + 18, yy + 10, x1 + 24, yy + 16, fill=color, outline="")
            c.create_text(x1 + 34, yy + 13, text=event.get("time", ""), anchor="w", fill=MUTED, font=("Consolas", 8))
            c.create_text(x1 + 92, yy + 13, text=event.get("level", ""), anchor="w", fill=color, font=("Consolas", 8, "bold"))
            c.create_text(x1 + 140, yy + 13, text=event.get("message", "")[: max(12, int((x2 - x1) / 8))], anchor="w", fill=TEXT_SOFT, font=("Microsoft YaHei UI", 8))
        if not self.events:
            c.create_text((x1 + x2) / 2, (y1 + y2) / 2, text="暂无活动", fill="#526d88", font=FONT_UI)

    # ── 交互 ─────────────────────────────────────────────────────────────

    def _on_click(self, event: tk.Event) -> None:
        x, y = float(event.x), float(event.y)
        for target, rect in self.layout.items():
            if self._inside(rect, x, y):
                if target == "connect":
                    self.toggle_connection()
                    return
                if target == "clear":
                    self.clear_data()
                    return
                if target == "field_settings":
                    self.open_field_selector()
                    return
                if target == "privacy":
                    self._toggle_privacy()
                    return
                if target == "market_event_more":
                    self.load_previous_market_event()
                    return
                if target == "subscription_market":
                    self._set_subscription_mode("market")
                    return
                if target == "subscription_codes":
                    self._set_subscription_mode("codes")
                    return
                if target.startswith("tab_"):
                    self.change_mode(target[4:])
                    return

    def _on_tree_select(self, _event: tk.Event) -> None:
        selection = self.data_tree.selection()
        if not selection:
            return
        row = self.rows_by_mode[self.mode].get(self.tree_key_by_iid.get(selection[0], ""), {})
        code = row.get("code")
        if code:
            self.selected_code = str(code)

    def _on_motion(self, event: tk.Event) -> None:
        x, y = float(event.x), float(event.y)
        target = ""
        for key, rect in self.layout.items():
            if key.startswith(("tab_", "connect", "clear", "privacy", "field_settings", "market_event_more", "subscription_")) and self._inside(rect, x, y):
                target = key
                break
        self._set_hover(target)

    def _set_hover(self, target: str) -> None:
        if self.hover_target != target:
            self.hover_target = target
            self.schedule_draw()

    def _toggle_privacy(self) -> None:
        self.privacy_mode = not self.privacy_mode
        self.schedule_draw()

    def clear_data(self) -> None:
        self.quotes.clear()
        for mode, rows in self.rows_by_mode.items():
            rows.clear()
            self._table_orders[mode].clear()
            self._table_order_dirty.add(mode)
            self._table_columns_dirty.add(mode)
            self._virtual_offsets[mode] = 0
        for mapping in self.tree_iids.values():
            mapping.clear()
        for iid in self.data_tree.get_children(""):
            self.data_tree.delete(iid)
        self.tree_key_by_iid.clear()
        self._virtual_tree_mode = ""
        self._virtual_slot_ids.clear()
        self._virtual_rendered_rows = 0
        self.events.clear()
        self.message_count = 0
        self.row_count = 0
        self.error_count = 0
        self.selected_code = ""
        self.market_event_cursor = None
        self.market_event_loading = False
        self.market_event_has_more = True
        self.market_event_history_pages = 0
        self.market_event_scroll_at_bottom = False
        self._add_event("SYS", "面板数据已清空", MUTED)
        self.schedule_draw()

    def toggle_fullscreen(self) -> None:
        current = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not current)

    def leave_fullscreen(self) -> None:
        self.root.attributes("-fullscreen", False)

    def close(self) -> None:
        self.disconnect(silent=True)
        self.root.destroy()

    def _tick(self) -> None:
        self.schedule_draw()
        self.root.after(1000, self._tick)

    # ── 绘图小工具 ──────────────────────────────────────────────────────

    @staticmethod
    def _inside(rect: tuple[float, float, float, float], x: float, y: float) -> bool:
        return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]

    def _panel(self, rect: tuple[float, float, float, float], accent: str = BORDER_BRIGHT) -> None:
        x1, y1, x2, y2 = rect
        self._rounded_rect(x1, y1, x2, y2, 10, SURFACE, BORDER)
        self.canvas.create_rectangle(x1 + 14, y1 + 1, x1 + 82, y1 + 3, fill=accent, outline="")

    def _button(self, rect: tuple[float, float, float, float], text: str, color: str, target: str, filled: bool = False) -> None:
        x1, y1, x2, y2 = rect
        hover = self.hover_target == target
        fill = color if filled else ("#1a2f49" if hover else SURFACE_2)
        outline = color if (filled or hover) else BORDER_BRIGHT
        self._rounded_rect(x1, y1, x2, y2, 7, fill, outline)
        self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=text, fill=BG if filled else (color if hover else TEXT_SOFT), font=FONT_UI_BOLD)

    def _pill(self, x1: float, y1: float, x2: float, y2: float, text: str, color: str, filled: bool) -> None:
        self._rounded_rect(x1, y1, x2, y2, 16, color if filled else "#102337", color)
        self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=text, fill=BG if filled else color, font=("Consolas", 9, "bold"))

    def _rounded_rect(self, x1: float, y1: float, x2: float, y2: float, radius: float, fill: str, outline: str) -> None:
        c = self.canvas
        r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
        if outline:
            c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
            c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="")
            for box, start in (((x1, y1, x1 + 2 * r, y1 + 2 * r), 90), ((x2 - 2 * r, y1, x2, y1 + 2 * r), 0), ((x2 - 2 * r, y2 - 2 * r, x2, y2), 270), ((x1, y2 - 2 * r, x1 + 2 * r, y2), 180)):
                c.create_arc(*box, start=start, extent=90, fill=fill, outline="")
            c.create_line(x1 + r, y1, x2 - r, y1, fill=outline)
            c.create_line(x1 + r, y2, x2 - r, y2, fill=outline)
            c.create_line(x1, y1 + r, x1, y2 - r, fill=outline)
            c.create_line(x2, y1 + r, x2, y2 - r, fill=outline)
            for box, start in (((x1, y1, x1 + 2 * r, y1 + 2 * r), 90), ((x2 - 2 * r, y1, x2, y1 + 2 * r), 0), ((x2 - 2 * r, y2 - 2 * r, x2, y2), 270), ((x1, y2 - 2 * r, x1 + 2 * r, y2), 180)):
                c.create_arc(*box, start=start, extent=90, style="arc", outline=outline)
        else:
            c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")
            c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="")
            for box, start in (((x1, y1, x1 + 2 * r, y1 + 2 * r), 90), ((x2 - 2 * r, y1, x2, y1 + 2 * r), 0), ((x2 - 2 * r, y2 - 2 * r, x2, y2), 270), ((x1, y2 - 2 * r, x1 + 2 * r, y2), 180)):
                c.create_arc(*box, start=start, extent=90, fill=fill, outline="")

    def _add_event(self, level: str, message: str, color: str) -> None:
        self.events.append({"time": display_time(), "level": level, "message": message, "color": color})

    def _age_text(self) -> str:
        if not self.last_message_at:
            return "—"
        age = max(0, int(time.time() - self.last_message_at))
        return "刚刚" if age < 2 else f"{age}s 前"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="d101 Tkinter 用户侧实时行情大屏")
    parser.add_argument("--url", default="ws://127.0.0.1:8080/d101", help="d101 WebSocket 地址")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = tk.Tk()
    D101Gui(root, args.url)
    root.mainloop()


if __name__ == "__main__":
    main()
