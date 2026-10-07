#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D4 用户侧数据工作台。

只使用 Python 标准库：Tkinter + urllib。程序启动后不会自动访问网络，
点击查询按钮后才向本地 D4 HTTP 接口发起只读请求。

运行：
    python d4_gui.py
    python d4_gui.py --base-url http://127.0.0.1:8080

工作区：
    市场列表   /d4/l1/instrument_list
    K 线       /d4/l1/kline
    资金摘要   /d4/l1/money_flow
    分钟历史   /d4/l1/minute_history
    分时成交   /d4/l1/minute_trades
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from privacy_display import display_name, is_name_field


# ── 视觉系统 ────────────────────────────────────────────────────────────────

BACKGROUND = "#07111f"
TOPBAR = "#081522"
SURFACE = "#0e1a2b"
SURFACE_2 = "#14253b"
SURFACE_3 = "#0a1422"
INPUT = "#0b1728"
BORDER = "#203852"
BORDER_BRIGHT = "#315779"
TEXT = "#edf6ff"
TEXT_SOFT = "#b7cbe0"
MUTED = "#7f96b0"
DIM = "#526b86"
CYAN = "#49d9ff"
CYAN_DARK = "#123d56"
PURPLE = "#ad94ff"
AMBER = "#ffc857"
UP = "#ff5c72"       # A 股常用约定：上涨为红色
DOWN = "#38d39a"     # 下跌为绿色
FLAT = "#9aadc2"
WHITE = "#ffffff"

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 10)
FONT_MONO_SMALL = ("Consolas", 9)
FONT_TITLE = ("Microsoft YaHei UI", 18, "bold")
FONT_WATERMARK = ("Microsoft YaHei UI", 24, "bold")


KLINE_PERIODS = [
    ("7", "日 K"),
    ("8", "周 K"),
    ("9", "月 K"),
    ("1", "1 分钟"),
    ("2", "5 分钟"),
    ("3", "15 分钟"),
    ("4", "30 分钟"),
    ("5", "60 分钟"),
]
KLINE_PERIOD_LABELS = [label for _code, label in KLINE_PERIODS]
KLINE_FQ_OPTIONS = [(18, "前复权"), (0, "不复权"), (9, "后复权")]
KLINE_FQ_LABELS = [label for _code, label in KLINE_FQ_OPTIONS]


UNIVERSES = [
    ("cn_hsj_stock", "沪深京 A 股"),
    ("cn_hs_stock", "沪深 A 股"),
    ("cn_sh_stock", "上海 A 股"),
    ("cn_sz_stock", "深圳 A 股"),
    ("cn_bse_stock", "北交所股票"),
    ("cn_star_stock", "科创板股票"),
    ("cn_sh_b_stock", "上海 B 股"),
    ("cn_sz_b_stock", "深圳 B 股"),
    ("cn_index", "沪深指数"),
    ("cn_fund", "基金混合集合"),
    ("cn_sh_fund", "上海基金"),
    ("cn_sz_fund", "深圳基金"),
    ("cn_reit", "REIT"),
    ("cn_sh_bond", "上海债券"),
    ("cn_sz_bond", "深圳债券"),
    ("cn_option", "期权合并集合"),
    ("cn_etf_option", "ETF 期权"),
    ("cn_option_call", "期权认购"),
    ("cn_option_put", "期权认沽"),
]
UNIVERSE_LABELS = [label for _code, label in UNIVERSES]
UNIVERSE_CODES = {label: code for code, label in UNIVERSES}


MIN_FIELDS = "code,name,price"
CONCISE_FIELDS = "code,name,price,change_pct,volume,amount_wan,total_mv_wan"
EQUITY_FIELDS = (
    "code,name,price,total_share,total_mv_wan,float_share,float_mv,"
    "amount_wan,amount_yuan"
)
ORDER_BOOK_FIELDS = (
    "code,name,price,change_pct,bid1,bid2,bid3,bid4,bid5,"
    "ask1,ask2,ask3,ask4,ask5,bid1_vol,bid2_vol,bid3_vol,bid4_vol,"
    "bid5_vol,ask1_vol,ask2_vol,ask3_vol,ask4_vol,ask5_vol"
)
FUNDAMENTAL_FIELDS = (
    "code,name,price,pe_ttm,pb,eps,roe,net_profit_yoy,book_value_per_share,"
    "main_net_flow_wan,super_large_net_flow_wan,medium_net_flow_wan,"
    "small_net_flow_wan,turnover_rate,volume_ratio"
)
STOCK_DETAIL_FIELDS = (
    "code,name,price,change_pct,change_amt,pre_close,open,high,low,"
    "volume,amount_wan,turnover_rate,volume_ratio,bid1,ask1,bid1_vol,"
    "ask1_vol,pe_ttm,pb,total_share,total_mv_wan,float_share,float_mv,industry_name"
)
STOCK_OVERVIEW_FIELDS = (
    "code,name,price,change_pct,change_amt,pre_close,open,high,low,amplitude,"
    "volume,amount_wan,turnover_rate,volume_ratio,bid1,ask1,bid1_vol,ask1_vol,"
    "pe_ttm,pb,total_share,total_mv_wan,float_share,float_mv,outer_vol,inner_vol,"
    "change_pct_3d,change_pct_6d,turnover_3d,turnover_6d,eps,roe,list_date,industry_name"
)
OPTION_DETAIL_FIELDS = (
    "code,name,price,change_pct,change_amt,pre_close,open,high,low,volume,"
    "amount_wan,opt_price,open_interest,remain_days,strike,unit_size,delta,"
    "gamma,vega,theta,amount_yuan,leverage,contract"
)

FIELD_PRESETS = [
    ("简洁字段组", CONCISE_FIELDS),
    ("股票详情（推荐）", STOCK_DETAIL_FIELDS),
    ("最小稳定字段", MIN_FIELDS),
    ("行情摘要", "code,name,price,change_pct,change_amt,volume,amount_wan,turnover_rate,volume_ratio"),
    ("股本与市值", EQUITY_FIELDS),
    ("盘口五档", ORDER_BOOK_FIELDS),
    ("资金与财务", FUNDAMENTAL_FIELDS),
    ("股票扩展信息（页数调小）", STOCK_OVERVIEW_FIELDS),
    ("期权详情", OPTION_DETAIL_FIELDS),
]


FIELD_LABELS = {
    "code": "代码",
    "name": "名称",
    "price": "最新价",
    "change_pct": "涨跌幅",
    "change_amt": "涨跌额",
    "pre_close": "昨收",
    "open": "开盘",
    "high": "最高",
    "low": "最低",
    "amplitude": "振幅",
    "volume": "成交量",
    "tick_vol": "现手量",
    "amount_wan": "成交额（万元）",
    "amount": "成交金额",
    "turnover_rate": "换手率",
    "volume_ratio": "量比",
    "speed_3min": "3 分钟涨速",
    "bid1": "买一价",
    "ask1": "卖一价",
    "bid1_vol": "买一量",
    "ask1_vol": "卖一量",
    "pe_ttm": "TTM 市盈率",
    "pb": "市净率",
    "total_share": "总股本（股）",
    "total_mv_wan": "总市值（万元）",
    "float_share": "流通股本",
    "float_mv": "流通市值",
    "outer_vol": "外盘量",
    "inner_vol": "内盘量",
    "change_pct_3d": "3 日涨跌幅",
    "change_pct_6d": "6 日涨跌幅",
    "turnover_3d": "3 日换手率",
    "turnover_6d": "6 日换手率",
    "eps": "每股收益",
    "roe": "净资产收益率",
    "list_date": "上市日期",
    "industry_name": "行业",
    "opt_price": "期权价",
    "open_interest": "持仓量",
    "remain_days": "剩余天数",
    "strike": "行权价",
    "unit_size": "合约单位",
    "delta": "Delta",
    "gamma": "Gamma",
    "vega": "Vega",
    "theta": "Theta",
    "amount_yuan": "成交额（元）",
    "leverage": "杠杆率",
    "contract": "合约描述",
}
FIELD_LABELS.update(
    {
        "net_profit_yoy": "净利润同比",
        "book_value_per_share": "每股净资产",
        "change_pct_3d_alt": "3 日涨跌幅（扩展）",
        "change_pct_5d": "5 日涨跌幅",
        "change_pct_10d": "10 日涨跌幅",
        "main_net_flow_wan": "主力净流额（万元）",
        "main_net_flow_auction_wan": "集合竞价主力净流额（万元）",
        "super_large_inflow_wan": "超大单流入（万元）",
        "super_large_outflow_wan": "超大单流出（万元）",
        "super_large_net_flow_wan": "超大单净流额（万元）",
        "super_large_net_ratio": "超大单净比",
        "medium_inflow_wan": "中单流入（万元）",
        "medium_outflow_wan": "中单流出（万元）",
        "medium_net_flow_wan": "中单净流额（万元）",
        "medium_net_ratio": "中单净比",
        "small_inflow_wan": "小单流入（万元）",
        "small_outflow_wan": "小单流出（万元）",
        "small_net_flow_wan": "小单净流额（万元）",
        "small_net_ratio": "小单净比",
        "sector_leader_name": "板块领涨股",
        "sector_for_sale_count": "板块在售家数",
        "sector_total_count": "板块总家数",
        "sector_rise_count": "板块涨家数",
        "sector_fall_count": "板块跌家数",
        "bid2": "买二价",
        "bid3": "买三价",
        "bid4": "买四价",
        "bid5": "买五价",
        "ask2": "卖二价",
        "ask3": "卖三价",
        "ask4": "卖四价",
        "ask5": "卖五价",
        "bid2_vol": "买二量",
        "bid3_vol": "买三量",
        "bid4_vol": "买四量",
        "bid5_vol": "买五量",
        "ask2_vol": "卖二量",
        "ask3_vol": "卖三量",
        "ask4_vol": "卖四量",
        "ask5_vol": "卖五量",
        "sector_leader_code": "板块领涨股代码",
        "speed_5min": "5 分钟涨速",
        "order_ratio": "委比",
        "inner_outer_ratio": "内外比",
        "average_price": "均价",
        "limit_up": "涨停价",
        "limit_down": "跌停价",
        "margin_financing": "融资融券",
        "security_type": "品种类型",
        "consecutive_up_days": "连涨天数",
        "change_pct_month": "本月涨跌幅",
        "change_pct_year": "本年涨跌幅",
        "change_pct_1m": "近 1 月涨跌幅",
        "change_pct_1y": "近 1 年涨跌幅",
    }
)

FIELD_ID_TO_NAME = {
    "1": "code",
    "2": "name",
    "3": "price",
    "4": "change_pct",
    "5": "change_amt",
    "6": "bid1",
    "7": "ask1",
    "8": "industry_name",
    "9": "volume",
    "10": "tick_vol",
    "11": "amount_wan",
    "12": "pe_ttm",
    "13": "speed_3min",
    "14": "turnover_rate",
    "15": "volume_ratio",
    "16": "pre_close",
    "17": "open",
    "18": "high",
    "19": "low",
    "20": "amplitude",
    "21": "pb",
    "22": "total_share",
    "23": "total_mv_wan",
    "24": "float_share",
    "25": "float_mv",
    "26": "outer_vol",
    "27": "inner_vol",
    "28": "change_pct_3d",
    "29": "change_pct_6d",
    "30": "turnover_3d",
    "31": "turnover_6d",
    "32": "eps",
    "33": "roe",
    "34": "list_date",
    "157": "bid1_vol",
    "162": "ask1_vol",
    "181": "opt_price",
    "195": "open_interest",
    "196": "remain_days",
    "197": "strike",
    "199": "unit_size",
    "200": "delta",
    "201": "gamma",
    "202": "vega",
    "203": "theta",
    "247": "amount",
    "293": "amount_yuan",
    "316": "leverage",
    "320": "contract",
}
FIELD_ID_TO_NAME.update(
    {
        "37": "net_profit_yoy",
        "39": "book_value_per_share",
        "69": "change_pct_3d_alt",
        "73": "change_pct_5d",
        "77": "change_pct_10d",
        "78": "main_net_flow_wan",
        "79": "main_net_flow_auction_wan",
        "80": "super_large_inflow_wan",
        "81": "super_large_outflow_wan",
        "82": "super_large_net_flow_wan",
        "83": "super_large_net_ratio",
        "84": "medium_inflow_wan",
        "85": "medium_outflow_wan",
        "86": "medium_net_flow_wan",
        "87": "medium_net_ratio",
        "88": "small_inflow_wan",
        "89": "small_outflow_wan",
        "90": "small_net_flow_wan",
        "91": "small_net_ratio",
        "92": "sector_leader_name",
        "93": "sector_for_sale_count",
        "95": "sector_total_count",
        "96": "sector_rise_count",
        "97": "sector_fall_count",
        "98": "bid2",
        "99": "bid3",
        "100": "bid4",
        "101": "bid5",
        "102": "ask2",
        "103": "ask3",
        "104": "ask4",
        "105": "ask5",
        "158": "bid2_vol",
        "159": "bid3_vol",
        "160": "bid4_vol",
        "161": "bid5_vol",
        "163": "ask2_vol",
        "164": "ask3_vol",
        "165": "ask4_vol",
        "166": "ask5_vol",
        "171": "sector_leader_code",
        "173": "speed_5min",
        "176": "order_ratio",
        "177": "inner_outer_ratio",
        "183": "average_price",
        "186": "limit_up",
        "187": "limit_down",
        "209": "margin_financing",
        "239": "security_type",
        "240": "consecutive_up_days",
        "241": "change_pct_month",
        "242": "change_pct_year",
        "243": "change_pct_1m",
        "244": "change_pct_1y",
    }
)

ALL_KNOWN_FIELD_IDS = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 37, 39, 69,
    73, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92,
    93, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 157, 158, 159,
    160, 161, 162, 163, 164, 165, 166, 171, 173, 176, 177, 181, 183, 186,
    187, 195, 196, 197, 199, 200, 201, 202, 203, 209, 239, 240, 241, 242,
    243, 244, 247, 293, 316, 320,
)
ALL_KNOWN_FIELDS = ",".join(FIELD_ID_TO_NAME[str(field_id)] for field_id in ALL_KNOWN_FIELD_IDS)
ALL_KNOWN_PRESET = "全部已知字段（建议每页100）"
FIELD_PRESETS.append((ALL_KNOWN_PRESET, ALL_KNOWN_FIELDS))
FIELD_PRESET_LABELS = [label for label, _fields in FIELD_PRESETS]


DETAIL_FIELD_LABELS = {
    "date": "日期",
    "time": "时间",
    "open_price": "开盘",
    "high_price": "最高",
    "low_price": "最低",
    "close_price": "收盘",
    "average_price": "均价",
    "volume": "成交量",
    "amount": "成交额",
    "trade_count": "成交笔数",
    "outside_volume": "外盘量",
    "inside_volume": "内盘量",
    "open_interest": "持仓量",
    "current_open_interest": "当前持仓",
    "total_buy_order": "买委托量",
    "total_sell_order": "卖委托量",
    "iopv": "IOPV",
    "red_value": "红值",
    "blue_value": "蓝值",
    "iopv4": "IOPV4",
    "money_trend": "今日资金趋势",
    "money_trend_3d": "3 日资金趋势",
    "money_trend_new_3d": "新 3 日资金趋势",
    "money_trend_5d": "5 日资金趋势",
    "money_trend_20d": "20 日资金趋势",
    "money_trend_60d": "60 日资金趋势",
    "main_net_amount": "主力净额",
    "main_buy_amount": "主力买入",
    "main_sell_amount": "主力卖出",
    "super_net_amount": "超大单净额",
    "big_net_amount": "大单净额",
    "mid_net_amount": "中单净额",
    "small_net_amount": "小单净额",
    "in_super_net_amount": "超大单流入",
    "in_big_net_amount": "大单流入",
    "in_mid_net_amount": "中单流入",
    "in_small_net_amount": "小单流入",
    "out_super_net_amount": "超大单流出",
    "out_big_net_amount": "大单流出",
    "out_mid_net_amount": "中单流出",
    "out_small_net_amount": "小单流出",
    "in_rank": "流入排名",
    "price": "价格",
    "volume_mismatch": "量差",
    "position_change": "仓差",
    "direction": "方向",
    "property_name": "性质",
}

MONEY_CARD_FIELDS = (
    ("主力净额", "main_net_amount", UP),
    ("今日趋势", "money_trend", CYAN),
    ("5 日趋势", "money_trend_5d", PURPLE),
    ("20 日趋势", "money_trend_20d", AMBER),
    ("超大单净额", "super_net_amount", UP),
    ("大单净额", "big_net_amount", CYAN),
    ("中单净额", "mid_net_amount", FLAT),
    ("小单净额", "small_net_amount", DOWN),
)

HISTORY_COLUMNS = (
    "time",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "average_price",
    "volume",
    "amount",
    "trade_count",
    "outside_volume",
    "inside_volume",
)
TRADE_COLUMNS = (
    "time", "price", "volume", "volume_mismatch", "position_change",
    "direction", "property_name",
)
TRADE_AUTO_LOAD_LIMIT = 10_000


class D4RequestError(RuntimeError):
    """可直接显示给用户的 D4 请求错误。"""


@dataclass
class PageResult:
    total: int
    rows: list[dict]
    skip: int
    requested_count: int


@dataclass
class AllResult:
    total: int
    rows: list[dict]
    pages: int
    cancelled: bool


@dataclass
class KlineResult:
    code: str
    rows: list[dict]
    requested_count: int
    period: int
    fq: int


@dataclass
class DetailResult:
    endpoint: str
    code: str
    payload: dict[str, Any]


@dataclass
class TradePageResult:
    detail: DetailResult
    request_time: int


@dataclass
class TradeAllResult:
    code: str
    payload: dict[str, Any]
    rows: list[dict]
    pages: int
    has_more: bool
    cancelled: bool
    truncated: bool


def _request_json(
    base_url: str,
    path: str,
    params: dict[str, Any],
    timeout: float,
    label: str,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + path
    query = urlencode({key: value for key, value in params.items() if value is not None and value != ""})
    request = Request(
        f"{endpoint}?{query}" if query else endpoint,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = json.loads(response.read().decode(charset))
    except HTTPError as exc:
        raise D4RequestError(f"{label}失败（HTTP {exc.code}）") from exc
    except (URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, TimeoutError):
            raise D4RequestError(f"{label}超时") from exc
        raise D4RequestError("无法连接本地数据服务") from exc
    except json.JSONDecodeError as exc:
        raise D4RequestError(f"{label}返回的内容不是合法 JSON") from exc

    if not isinstance(payload, dict):
        raise D4RequestError(f"{label}返回格式错误：顶层不是 JSON 对象")
    if payload.get("error"):
        raise D4RequestError(f"{label}返回错误：{payload.get('error')}")
    return payload


def fetch_page(
    base_url: str,
    universe: str,
    skip: int,
    count: int,
    fields: str,
    timeout: float,
    sort: int = 0,
    order: int = 0,
    category: int = 0,
) -> PageResult:
    """请求一页品种列表，不在这里修改 GUI。"""
    payload = _request_json(
        base_url,
        "/d4/l1/instrument_list",
        {
            "universe": universe,
            "skip": skip,
            "count": count,
            "fields": fields,
            "sort": sort,
            "order": order,
            "category": category,
        },
        timeout,
        "列表请求",
    )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise D4RequestError("列表返回格式错误：缺少 rows 数组")
    try:
        total = int(payload.get("total", 0))
    except (TypeError, ValueError) as exc:
        raise D4RequestError("列表返回格式错误：total 不是数字") from exc
    return PageResult(
        total=max(0, total),
        rows=[row for row in rows if isinstance(row, dict)],
        skip=skip,
        requested_count=count,
    )


def fetch_kline(
    base_url: str,
    code: str,
    period: int,
    count: int,
    fq: int,
    timeout: float,
) -> KlineResult:
    """请求 D4 K 线列表，不在这里修改 GUI。"""
    payload = _request_json(
        base_url,
        "/d4/l1/kline",
        {"code": code, "period": period, "count": count, "fq": fq},
        timeout,
        "K 线请求",
    )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise D4RequestError("K 线返回格式错误：缺少 rows 数组")
    return KlineResult(
        code=str(payload.get("code") or code),
        rows=[row for row in rows if isinstance(row, dict)],
        requested_count=count,
        period=period,
        fq=fq,
    )


def fetch_money_flow(
    base_url: str,
    code: str,
    market: str,
    fields: str,
    timeout: float,
) -> DetailResult:
    payload = _request_json(
        base_url,
        "/d4/l1/money_flow",
        {"code": code, "market": market, "fields": fields},
        timeout,
        "资金摘要请求",
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise D4RequestError("资金摘要返回格式错误：缺少 data 对象")
    return DetailResult("/d4/l1/money_flow", str(payload.get("code") or code), payload)


def fetch_minute_history(
    base_url: str,
    code: str,
    market: str,
    fields: str,
    request_time: int,
    timeout: float,
) -> DetailResult:
    payload = _request_json(
        base_url,
        "/d4/l1/minute_history",
        {
            "code": code,
            "market": market,
            "fields": fields,
            "request_time": request_time,
        },
        timeout,
        "分钟历史请求",
    )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise D4RequestError("分钟历史返回格式错误：缺少 rows 数组")
    return DetailResult("/d4/l1/minute_history", str(payload.get("code") or code), payload)


def fetch_minute_trades(
    base_url: str,
    code: str,
    market: str,
    request_time: int,
    timeout: float,
) -> DetailResult:
    payload = _request_json(
        base_url,
        "/d4/l1/minute_trades",
        {"code": code, "market": market, "request_time": request_time},
        timeout,
        "分时成交请求",
    )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise D4RequestError("分时成交返回格式错误：缺少 rows 数组")
    return DetailResult("/d4/l1/minute_trades", str(payload.get("code") or code), payload)


def _trade_row_key(row: dict[str, Any]) -> tuple[str, ...]:
    """生成成交行的稳定键，用于去掉游标查询带来的边界重复行。"""
    return tuple(str(row.get(column, "")) for column in TRADE_COLUMNS)


def merge_trade_rows(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int]:
    """合并连续的分时成交页，只去掉两页之间的连续重叠前缀。"""
    incoming = [row for row in incoming if isinstance(row, dict)]
    if not existing:
        return list(incoming), len(incoming)
    if not incoming:
        return list(existing), 0

    existing_keys = [_trade_row_key(row) for row in existing]
    incoming_keys = [_trade_row_key(row) for row in incoming]
    overlap = 0
    max_overlap = min(len(existing_keys), len(incoming_keys))
    for size in range(max_overlap, 0, -1):
        if existing_keys[-size:] == incoming_keys[:size]:
            overlap = size
            break
    appended = incoming[overlap:]
    return list(existing) + appended, len(appended)


def _trade_cursor(payload: dict[str, Any], rows: list[dict]) -> int | None:
    if "next_request_time" in payload:
        value = payload.get("next_request_time")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    values: list[int] = []
    for row in rows:
        try:
            values.append(int(row.get("time")))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _payload_int(payload: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return max(0, int(payload.get(key, default)))
    except (TypeError, ValueError):
        return default


def _trade_page_can_continue(payload: dict[str, Any], raw_count: int,
                             loaded_count: int) -> bool:
    if raw_count <= 0:
        return False
    service_has_more = payload.get("has_more")
    if isinstance(service_has_more, bool):
        return service_has_more
    data_count = _payload_int(payload, "data_count")
    max_count = _payload_int(payload, "max_count")
    if data_count and loaded_count >= data_count:
        return False
    return max_count > 0 and raw_count >= max_count


def fetch_minute_trades_all(
    base_url: str,
    code: str,
    market: str,
    request_time: int,
    timeout: float,
    seed_rows: list[dict] | None = None,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    max_rows: int = TRADE_AUTO_LOAD_LIMIT,
) -> TradeAllResult:
    """连续读取分时成交页并在本地合并，界面只需要一次点击。"""
    if max_rows <= 0:
        raise ValueError("分时成交汇总上限必须大于 0")

    rows = [row for row in (seed_rows or []) if isinstance(row, dict)]
    cursor = int(request_time)
    pages = 0
    payload: dict[str, Any] = {}
    has_more = False
    truncated = False
    seen_cursors: set[int] = set()

    while True:
        if cancelled and cancelled():
            return TradeAllResult(
                code=code, payload=payload, rows=rows, pages=pages,
                has_more=True, cancelled=True, truncated=False,
            )
        if len(rows) >= max_rows:
            truncated = True
            has_more = True
            break
        if cursor in seen_cursors:
            break
        seen_cursors.add(cursor)

        page = fetch_minute_trades(base_url, code, market, cursor, timeout)
        payload = page.payload
        raw_rows = [row for row in payload.get("rows", []) if isinstance(row, dict)]
        rows, new_count = merge_trade_rows(rows, raw_rows)
        pages += 1
        if progress:
            progress(
                f"分时成交已加载 {len(rows):,} 条 · 第 {pages} 次请求 · "
                f"本次新增 {new_count:,} 条"
            )

        if not _trade_page_can_continue(payload, len(raw_rows), len(rows)):
            has_more = False
            break
        next_cursor = _trade_cursor(payload, raw_rows)
        if next_cursor is None or next_cursor == cursor or new_count <= 0:
            has_more = False
            break
        if not is_option_trade_code(code) and next_cursor <= cursor:
            has_more = False
            break
        cursor = next_cursor
        has_more = True

    return TradeAllResult(
        code=str(payload.get("code") or code),
        payload=payload,
        rows=rows[:max_rows],
        pages=pages,
        has_more=has_more,
        cancelled=bool(cancelled and cancelled()),
        truncated=truncated,
    )


def normalize_kline_code(value: str) -> str:
    return str(value or "").strip().upper()


def is_option_trade_code(value: str) -> bool:
    code = str(value or "").strip().upper()
    return (len(code) == 10 and code.startswith("SO") and code[2:].isdigit())


def normalize_option_detail_code(value: str) -> str:
    code = str(value or "").strip().upper()
    if is_option_trade_code(code):
        return code
    if len(code) == 8 and code.isdigit():
        return "SO" + code
    raise ValueError("期权成交代码请输入 SO 加 8 位合约号")


def normalize_detail_code(value: str, market: str = "") -> str:
    """详情接口只接受市场前缀加 6 位代码。"""
    code = str(value or "").strip().upper()
    if len(code) == 8 and code[:2] in {"SH", "SZ", "BJ"} and code[2:].isdigit():
        return code
    if len(code) != 6 or not code.isdigit():
        raise ValueError("详情代码请输入 6 位数字，或 SH/SZ/BJ 加 6 位代码")

    normalized_market = str(market or "").strip().upper()
    if normalized_market in {"自动", "AUTO", ""}:
        normalized_market = "SH" if code[0] in {"5", "6"} else "SZ"
    if normalized_market in {"1", "SSE"}:
        normalized_market = "SH"
    if normalized_market in {"0", "SZSE"}:
        normalized_market = "SZ"
    if normalized_market not in {"SH", "SZ", "BJ"}:
        raise ValueError("市场必须选择自动、SH、SZ 或 BJ")
    return normalized_market + code


def format_integer(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value if value is not None else "")
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.6f}".rstrip("0").rstrip(".")


def format_time_value(value: Any) -> str:
    text = str(value or "")
    if text.isdigit():
        if 4 <= len(text) <= 6:
            text = text.zfill(6)
        if len(text) == 6:
            return f"{text[:2]}:{text[2:4]}:{text[4:]}"
        if len(text) == 8:
            return f"{text[:2]}:{text[2:4]}:{text[4:6]}.{text[6:]}"
        if len(text) == 9:
            return f"{text[:2]}:{text[2:4]}:{text[4:6]}.{text[6:]}"
    return text


class D4Gui:
    def __init__(self, root: tk.Tk, base_url: str, timeout: float) -> None:
        self.root = root
        self.timeout = timeout
        self.root.title("D4 · 品种与历史数据工作台")
        self.root.geometry("1680x1020")
        self.root.minsize(1180, 760)
        self.root.configure(background=BACKGROUND)

        self.base_url_var = tk.StringVar(value=base_url)
        self.timeout_var = tk.StringVar(value=str(int(timeout)))
        self.universe_var = tk.StringVar(value=UNIVERSE_LABELS[0])
        self.preset_var = tk.StringVar(value="股票详情（推荐）")
        self.fields_var = tk.StringVar(value=STOCK_DETAIL_FIELDS)
        self.field_count_var = tk.StringVar(value="0 个字段")
        self.skip_var = tk.StringVar(value="0")
        self.count_var = tk.StringVar(value="300")
        self.filter_var = tk.StringVar()

        self.status_var = tk.StringVar(value="准备就绪 · 选择条件后开始查询")
        self.active_job_var = tk.StringVar(value="待命")
        self.summary_var = tk.StringVar(value="尚未查询列表")
        self.total_stat_var = tk.StringVar(value="—")
        self.page_stat_var = tk.StringVar(value="—")
        self.loaded_stat_var = tk.StringVar(value="—")
        self.header_status_var = tk.StringVar(value="LOCAL  ·  READY")

        self.selected_code_var = tk.StringVar(value="—")
        self.selected_name_var = tk.StringVar(value="尚未选择品种")
        self.selected_price_var = tk.StringVar(value="—")
        self.selected_change_var = tk.StringVar(value="—")
        self.selected_hint_var = tk.StringVar(value="查询列表后选择一行，可打开右侧历史工作区")

        self.detail_code_var = tk.StringVar(value="SZ000001")
        self.detail_market_var = tk.StringVar(value="自动")
        self.detail_fields_var = tk.StringVar(value="")
        self.history_request_time_var = tk.StringVar(value="0")
        self.trade_request_time_var = tk.StringVar(value="0")

        self.kline_code_var = tk.StringVar(value="000001")
        self.kline_period_var = tk.StringVar(value=KLINE_PERIOD_LABELS[0])
        self.kline_fq_var = tk.StringVar(value=KLINE_FQ_LABELS[0])
        self.kline_count_var = tk.StringVar(value="100")
        self.kline_summary_var = tk.StringVar(value="选择品种后加载历史 K 线")
        self.kline_status_var = tk.StringVar(value="K 线工作区待命")

        self.money_summary_var = tk.StringVar(value="选择品种后读取资金摘要")
        self.history_summary_var = tk.StringVar(value="选择品种后读取分钟历史")
        self.trade_summary_var = tk.StringVar(value="选择品种后读取分时成交")
        self.money_status_var = tk.StringVar(value="资金摘要工作区待命")
        self.history_status_var = tk.StringVar(value="分钟历史工作区待命")
        self.trade_status_var = tk.StringVar(value="分时成交工作区待命")

        self.privacy_mode = False
        self.current_skip = 0
        self.current_rows: list[dict] = []
        self.current_total = 0
        self.last_page_size = 300
        self.selected_row: dict[str, Any] | None = None
        self.kline_rows: list[dict] = []
        self.money_data: dict[str, Any] = {}
        self.history_rows: list[dict] = []
        self.trade_rows: list[dict] = []
        self.trade_code = ""
        self.trade_next_request_time = 0
        self.trade_available_count = 0
        self.trade_max_count = 0
        self.trade_loaded_pages = 0
        self.trade_has_more = False
        self.busy = False
        self.cancel_event = threading.Event()
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.tree_columns: list[str] = []
        self.row_by_item: dict[str, dict] = {}
        self.privacy_button: tk.Button | None = None
        self.detail_buttons: list[ttk.Button] = []

        self._build_style()
        self.fields_var.trace_add("write", self._on_fields_changed)
        self.filter_var.trace_add("write", self._on_filter_changed)
        self._on_fields_changed()
        self._build_header()
        self._build_body()
        self._build_statusbar()
        self._update_navigation()

        self.root.after(50, self._drain_worker_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Control-c>", self._copy_selected)
        self.root.bind("<Control-Return>", lambda _event: self.query_current_page())

    # ── 构建界面 ─────────────────────────────────────────────────────────

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BACKGROUND)
        style.configure("Workspace.TFrame", background=SURFACE)
        style.configure("Sidebar.TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=SURFACE, foreground=TEXT, font=FONT_UI)
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=FONT_SMALL)
        style.configure("Sidebar.TLabel", background=BACKGROUND, foreground=TEXT, font=FONT_UI)
        style.configure("SidebarMuted.TLabel", background=BACKGROUND, foreground=MUTED, font=FONT_SMALL)
        style.configure("Treeview", background=SURFACE_3, fieldbackground=SURFACE_3,
                        foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, rowheight=31, font=FONT_UI)
        style.configure("Treeview.Heading", background=SURFACE_2, foreground=CYAN,
                        bordercolor=BORDER, font=FONT_UI_BOLD, padding=(8, 7))
        style.map("Treeview", background=[("selected", "#214f75")],
                  foreground=[("selected", WHITE)])
        style.configure("TLabelframe", background=SURFACE, foreground=MUTED,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.configure("TLabelframe.Label", background=SURFACE, foreground=CYAN,
                        font=FONT_UI_BOLD)
        style.configure("TButton", background=SURFACE_2, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        padding=(10, 7), font=FONT_UI)
        style.map("TButton", background=[("active", "#2a4b6e"), ("pressed", "#356589"),
                                         ("disabled", "#111b2a")],
                  foreground=[("disabled", DIM)])
        style.configure("Accent.TButton", background=CYAN, foreground="#06111f",
                        bordercolor=CYAN, padding=(12, 7), font=FONT_UI_BOLD)
        style.map("Accent.TButton", background=[("active", "#96ecff"), ("pressed", "#22b8df")],
                  foreground=[("disabled", "#506b7c")])
        style.configure("Soft.TButton", background=CYAN_DARK, foreground=CYAN,
                        bordercolor=BORDER_BRIGHT, padding=(9, 6), font=FONT_UI_BOLD)
        style.map("Soft.TButton", background=[("active", "#1b5673"), ("pressed", "#246887")])
        style.configure("TEntry", fieldbackground=INPUT, foreground=TEXT,
                        insertcolor=CYAN, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, padding=(6, 5))
        style.configure("TCombobox", fieldbackground=INPUT, foreground=TEXT,
                        background=SURFACE_2, arrowcolor=CYAN, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", INPUT)],
                  foreground=[("readonly", TEXT)])
        style.configure("TNotebook", background=SURFACE, borderwidth=0,
                        tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=SURFACE_2, foreground=MUTED,
                        padding=(18, 9), font=FONT_UI_BOLD)
        style.map("TNotebook.Tab", background=[("selected", CYAN), ("active", "#2b496b")],
                  foreground=[("selected", "#06111f"), ("active", TEXT)])
        style.configure("Horizontal.TProgressbar", background=CYAN, troughcolor=SURFACE_3,
                        bordercolor=BORDER, lightcolor=CYAN, darkcolor=CYAN)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=TOPBAR, height=78)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        title_box = tk.Frame(header, bg=TOPBAR)
        title_box.grid(row=0, column=0, sticky="nsw", padx=(24, 18), pady=12)
        tk.Label(title_box, text="d4", bg=TOPBAR, fg=CYAN,
                 font=("Consolas", 22, "bold")).pack(side="left", padx=(0, 12))
        text_box = tk.Frame(title_box, bg=TOPBAR)
        text_box.pack(side="left")
        tk.Label(text_box, text="品种与历史数据", bg=TOPBAR, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        tk.Label(text_box, text="READ-ONLY MARKET WORKSPACE  /  HTTP", bg=TOPBAR,
                 fg=MUTED, font=FONT_MONO_SMALL).pack(anchor="w", pady=(2, 0))

        tk.Label(header, text="列表 · K 线 · 资金 · 分钟数据", bg=TOPBAR,
                 fg=DIM, font=FONT_SMALL).grid(row=0, column=1, sticky="w", padx=10)

        right = tk.Frame(header, bg=TOPBAR)
        right.grid(row=0, column=2, sticky="nse", padx=22, pady=16)
        self.privacy_button = tk.Button(
            right, text="隐藏中文名", command=self._toggle_privacy,
            bg=CYAN_DARK, activebackground="#1b5b78", fg=CYAN,
            activeforeground=WHITE, relief="flat", bd=0, padx=10, pady=5,
            font=FONT_UI_BOLD, cursor="hand2",
        )
        self.privacy_button.pack(side="right", padx=(12, 0))
        tk.Label(right, textvariable=self.header_status_var, bg="#102b3b", fg=CYAN,
                 padx=11, pady=5, font=("Consolas", 9, "bold")).pack(side="right")
        tk.Frame(header, bg=CYAN, height=2).grid(row=1, column=0, columnspan=3, sticky="ew")

    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=BACKGROUND)
        body.grid(row=1, column=0, sticky="nsew")
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=318, weight=0)
        body.grid_columnconfigure(1, minsize=700, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self._build_sidebar(body)
        tk.Frame(body, bg=BORDER, width=1).grid(row=0, column=0, sticky="nse")
        self._build_workspace(body)

    def _build_sidebar(self, parent: tk.Frame) -> None:
        outer = tk.Frame(parent, bg=BACKGROUND)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(outer, bg=BACKGROUND, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.sidebar_canvas = canvas

        content = tk.Frame(canvas, bg=BACKGROUND)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", self._sidebar_wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

        self.sidebar_content = content
        self._build_connection_section(content)
        self._build_list_query_section(content)
        self._build_paging_section(content)
        self._build_selected_section(content)
        self._build_detail_section(content)
        self._build_tips_section(content)

    def _sidebar_wheel(self, event) -> None:
        self.sidebar_canvas.yview_scroll(int(-event.delta / 120), "units")

    @staticmethod
    def _make_sidebar_card(parent: tk.Frame, title: str, subtitle: str = "") -> tk.Frame:
        card = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", padx=12, pady=(10, 0))
        head = tk.Frame(card, bg=SURFACE)
        head.pack(fill="x", padx=12, pady=(10, 5))
        tk.Label(head, text=title, bg=SURFACE, fg=TEXT, font=FONT_UI_BOLD).pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(
                side="right"
            )
        body = tk.Frame(card, bg=SURFACE)
        body.pack(fill="x", padx=12, pady=(0, 11))
        return body

    @staticmethod
    def _make_field_label(parent: tk.Frame, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=SURFACE, fg=MUTED, font=FONT_SMALL)

    def _build_connection_section(self, parent: tk.Frame) -> None:
        body = self._make_sidebar_card(parent, "数据服务", "本地只读")
        self._make_field_label(body, "服务地址").pack(anchor="w")
        ttk.Entry(body, textvariable=self.base_url_var).pack(fill="x", pady=(3, 8))
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill="x")
        self._make_field_label(row, "超时（秒）").pack(side="left")
        ttk.Entry(row, textvariable=self.timeout_var, width=8).pack(side="right")
        tk.Label(body, text="不会自动请求；所有网络操作由按钮触发。",
                 bg=SURFACE, fg=DIM, font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(8, 0))

    def _build_list_query_section(self, parent: tk.Frame) -> None:
        body = self._make_sidebar_card(parent, "市场列表", "查询条件")
        self._make_field_label(body, "品种池").pack(anchor="w")
        self.universe_box = ttk.Combobox(
            body, textvariable=self.universe_var, values=UNIVERSE_LABELS,
            state="readonly", height=16,
        )
        self.universe_box.pack(fill="x", pady=(3, 8))

        self._make_field_label(body, "字段预设").pack(anchor="w")
        self.preset_box = ttk.Combobox(
            body, textvariable=self.preset_var, values=FIELD_PRESET_LABELS,
            state="readonly", height=16,
        )
        self.preset_box.pack(fill="x", pady=(3, 5))
        self.preset_box.bind("<<ComboboxSelected>>", self._on_preset_selected)

        field_head = tk.Frame(body, bg=SURFACE)
        field_head.pack(fill="x", pady=(2, 3))
        self._make_field_label(field_head, "列表字段（逗号分隔）").pack(side="left")
        tk.Label(field_head, textvariable=self.field_count_var, bg=SURFACE,
                 fg=CYAN, font=FONT_SMALL).pack(side="right")
        ttk.Entry(body, textvariable=self.fields_var).pack(fill="x")

        quick = tk.Frame(body, bg=SURFACE)
        quick.pack(fill="x", pady=(8, 0))
        for text, label in (
            ("常用", "股票详情（推荐）"),
            ("精简", "最小稳定字段"),
            ("盘口", "盘口五档"),
            ("全字段", ALL_KNOWN_PRESET),
        ):
            ttk.Button(
                quick, text=text, style="Soft.TButton",
                command=lambda preset=label: self._select_field_group(preset),
            ).pack(side="left", expand=True, fill="x", padx=2)

    def _build_paging_section(self, parent: tk.Frame) -> None:
        body = self._make_sidebar_card(parent, "读取控制", "分页与汇总")
        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill="x")
        left = tk.Frame(row, bg=SURFACE)
        left.pack(side="left", fill="x", expand=True, padx=(0, 5))
        right = tk.Frame(row, bg=SURFACE)
        right.pack(side="left", fill="x", expand=True, padx=(5, 0))
        self._make_field_label(left, "跳过").pack(anchor="w")
        ttk.Entry(left, textvariable=self.skip_var).pack(fill="x", pady=(3, 0))
        self._make_field_label(right, "每页条数").pack(anchor="w")
        ttk.Entry(right, textvariable=self.count_var).pack(fill="x", pady=(3, 0))

        primary = tk.Frame(body, bg=SURFACE)
        primary.pack(fill="x", pady=(10, 5))
        self.query_button = ttk.Button(
            primary, text="查询当前页", command=self.query_current_page, style="Accent.TButton"
        )
        self.query_button.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self.all_button = ttk.Button(
            primary, text="读取全部", command=self.read_all, style="Soft.TButton"
        )
        self.all_button.pack(side="left", expand=True, fill="x", padx=(3, 0))

        navigation = tk.Frame(body, bg=SURFACE)
        navigation.pack(fill="x")
        self.first_button = ttk.Button(navigation, text="首页", command=self.first_page)
        self.first_button.pack(side="left", expand=True, fill="x", padx=(0, 2))
        self.previous_button = ttk.Button(navigation, text="上一页", command=self.previous_page)
        self.previous_button.pack(side="left", expand=True, fill="x", padx=2)
        self.next_button = ttk.Button(navigation, text="下一页", command=self.next_page)
        self.next_button.pack(side="left", expand=True, fill="x", padx=2)
        self.cancel_button = ttk.Button(navigation, text="取消", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", expand=True, fill="x", padx=(2, 0))

    def _build_selected_section(self, parent: tk.Frame) -> None:
        body = self._make_sidebar_card(parent, "当前选择", "行点击 / 双击")
        code_row = tk.Frame(body, bg=SURFACE)
        code_row.pack(fill="x")
        tk.Label(code_row, textvariable=self.selected_code_var, bg=SURFACE, fg=CYAN,
                 font=("Consolas", 16, "bold")).pack(side="left")
        tk.Label(code_row, textvariable=self.selected_price_var, bg=SURFACE, fg=TEXT,
                 font=("Consolas", 14, "bold")).pack(side="right")
        tk.Label(body, textvariable=self.selected_name_var, bg=SURFACE, fg=TEXT,
                 font=FONT_UI_BOLD, anchor="w").pack(fill="x", pady=(3, 0))
        change_row = tk.Frame(body, bg=SURFACE)
        change_row.pack(fill="x", pady=(3, 7))
        self.selected_change_label = tk.Label(
            change_row, textvariable=self.selected_change_var,
            bg=SURFACE, fg=FLAT, font=FONT_MONO
        )
        self.selected_change_label.pack(side="left")
        tk.Label(change_row, text="  ·  ", bg=SURFACE, fg=DIM, font=FONT_SMALL).pack(side="left")
        tk.Label(change_row, textvariable=self.selected_hint_var, bg=SURFACE, fg=MUTED,
                 font=("Microsoft YaHei UI", 8), anchor="w", wraplength=215,
                 justify="left").pack(side="left", fill="x", expand=True)

        buttons = tk.Frame(body, bg=SURFACE)
        buttons.pack(fill="x")
        for text, command in (
            ("K 线", self.query_kline),
            ("资金", self.query_money_flow),
            ("分钟历史", self.query_minute_history),
            ("分时成交", self.query_minute_trades),
        ):
            button = ttk.Button(buttons, text=text, command=command, style="Soft.TButton")
            button.pack(side="left", expand=True, fill="x", padx=2)
            self.detail_buttons.append(button)

    def _build_detail_section(self, parent: tk.Frame) -> None:
        body = self._make_sidebar_card(parent, "详情参数", "可手动输入")
        self._make_field_label(body, "详情代码").pack(anchor="w")
        ttk.Entry(body, textvariable=self.detail_code_var).pack(fill="x", pady=(3, 7))

        row = tk.Frame(body, bg=SURFACE)
        row.pack(fill="x")
        self._make_field_label(row, "市场").pack(side="left")
        ttk.Combobox(
            row, textvariable=self.detail_market_var, values=("自动", "SH", "SZ", "BJ"),
            state="readonly", width=8,
        ).pack(side="right")

        self._make_field_label(body, "详情字段（可选 ID）").pack(anchor="w", pady=(8, 0))
        ttk.Entry(body, textvariable=self.detail_fields_var).pack(fill="x", pady=(3, 2))
        tk.Label(
            body, text="留空使用接口默认字段；资金/分钟历史支持字段 ID。",
            bg=SURFACE, fg=DIM, font=("Microsoft YaHei UI", 8), anchor="w",
            wraplength=245, justify="left",
        ).pack(fill="x")

    def _build_tips_section(self, parent: tk.Frame) -> None:
        body = self._make_sidebar_card(parent, "使用提示", "D4")
        tips = (
            "• 选中列表行后，右侧工作区会保留该品种。\n"
            "• 双击列表行可直接加载 K 线。\n"
            "• 期权和其他非股票品种支持列表/K 线；详情接口需要 6 位股票代码。\n"
            "• 价格与详情数值保留服务端精度，不做未经确认的统一换算。"
        )
        tk.Label(body, text=tips, bg=SURFACE, fg=MUTED, font=("Microsoft YaHei UI", 8),
                 justify="left", anchor="w", wraplength=250).pack(fill="x")

    def _build_workspace(self, parent: tk.Frame) -> None:
        workspace = tk.Frame(parent, bg=SURFACE)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_rowconfigure(3, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        top = tk.Frame(workspace, bg=SURFACE)
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(17, 7))
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text="数据工作台", bg=SURFACE, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(top, textvariable=self.summary_var, bg=SURFACE, fg=MUTED,
                 font=FONT_SMALL).grid(row=1, column=0, sticky="w", pady=(3, 0))
        tk.Label(top, text="HTTP · READ ONLY", bg=SURFACE, fg=DIM,
                 font=FONT_MONO_SMALL).grid(row=0, column=1, rowspan=2, sticky="e")

        stats = tk.Frame(workspace, bg=SURFACE)
        stats.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        for column in range(3):
            stats.grid_columnconfigure(column, weight=1)
        self._make_stat_card(stats, "品种总数", self.total_stat_var, CYAN).grid(
            row=0, column=0, sticky="ew", padx=(0, 5)
        )
        self._make_stat_card(stats, "当前页范围", self.page_stat_var, PURPLE).grid(
            row=0, column=1, sticky="ew", padx=5
        )
        self._make_stat_card(stats, "当前展示", self.loaded_stat_var, UP).grid(
            row=0, column=2, sticky="ew", padx=(5, 0)
        )

        self._build_selected_strip(workspace)

        tabs = ttk.Notebook(workspace)
        tabs.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.workspace_tabs = tabs
        self._build_list_tab(tabs)
        self._build_kline_tab(tabs)
        self._build_money_tab(tabs)
        self._build_history_tab(tabs)
        self._build_trade_tab(tabs)

    @staticmethod
    def _make_stat_card(parent: tk.Frame, title: str, variable: tk.StringVar, color: str) -> tk.Frame:
        card = tk.Frame(parent, bg=SURFACE_3, highlightthickness=1, highlightbackground=BORDER)
        tk.Frame(card, bg=color, width=4).pack(side="left", fill="y")
        content = tk.Frame(card, bg=SURFACE_3)
        content.pack(side="left", fill="both", expand=True)
        tk.Label(content, text=title, bg=SURFACE_3, fg=MUTED,
                 font=FONT_SMALL).pack(anchor="w", padx=12, pady=(7, 0))
        tk.Label(content, textvariable=variable, bg=SURFACE_3, fg=TEXT,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=12, pady=(0, 7))
        return card

    def _build_selected_strip(self, parent: tk.Frame) -> None:
        strip = tk.Frame(parent, bg=SURFACE_2, highlightthickness=1, highlightbackground=BORDER)
        strip.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        strip.grid_columnconfigure(1, weight=1)
        tk.Label(strip, text="当前品种", bg=SURFACE_2, fg=MUTED,
                 font=FONT_SMALL).grid(row=0, column=0, rowspan=2, sticky="w", padx=(14, 10), pady=10)
        tk.Label(strip, textvariable=self.selected_code_var, bg=SURFACE_2, fg=CYAN,
                 font=("Consolas", 14, "bold")).grid(row=0, column=1, sticky="w", pady=(8, 0))
        tk.Label(strip, textvariable=self.selected_name_var, bg=SURFACE_2, fg=TEXT,
                 font=FONT_UI_BOLD).grid(row=1, column=1, sticky="w", pady=(0, 8))
        tk.Label(strip, textvariable=self.selected_price_var, bg=SURFACE_2, fg=TEXT,
                 font=("Consolas", 13, "bold")).grid(row=0, column=2, rowspan=2, sticky="e", padx=12)
        self.selected_strip_change_label = tk.Label(
            strip, textvariable=self.selected_change_var, bg=SURFACE_2, fg=FLAT,
            font=FONT_MONO
        )
        self.selected_strip_change_label.grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 14))

    def _build_list_tab(self, tabs: ttk.Notebook) -> None:
        panel = ttk.Frame(tabs, style="Workspace.TFrame", padding=10)
        tabs.add(panel, text="市场列表")
        self.list_panel = panel
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        toolbar = tk.Frame(panel, bg=SURFACE)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.grid_columnconfigure(1, weight=1)
        tk.Label(toolbar, text="列表结果", bg=SURFACE, fg=TEXT,
                 font=FONT_UI_BOLD).grid(row=0, column=0, sticky="w")
        filter_box = tk.Frame(toolbar, bg=SURFACE_3,
                              highlightthickness=1, highlightbackground=BORDER)
        filter_box.grid(row=0, column=1, sticky="ew", padx=(15, 8))
        tk.Label(filter_box, text="⌕", bg=SURFACE_3, fg=CYAN,
                 font=("Segoe UI Symbol", 13)).pack(side="left", padx=(8, 3))
        ttk.Entry(filter_box, textvariable=self.filter_var).pack(
            side="left", fill="x", expand=True, padx=(0, 5), pady=4
        )
        ttk.Button(filter_box, text="清除", command=lambda: self.filter_var.set("")).pack(
            side="right", padx=4, pady=3
        )
        self.list_toolbar_status_var = tk.StringVar(value="输入代码、名称或行业进行本地筛选")
        tk.Label(toolbar, textvariable=self.list_toolbar_status_var, bg=SURFACE,
                 fg=MUTED, font=FONT_SMALL).grid(row=0, column=2, sticky="e")
        self.copy_button = ttk.Button(toolbar, text="复制选中行", command=self._copy_selected)
        self.copy_button.grid(row=0, column=3, sticky="e", padx=(10, 0))

        table_frame = tk.Frame(panel, bg=SURFACE_3, highlightthickness=1, highlightbackground=BORDER)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table_frame, columns=("message",), show="headings", selectmode="browse")
        self.tree.heading("message", text="数据")
        self.tree.column("message", width=650, anchor="w")
        self.tree.tag_configure("up", foreground=UP)
        self.tree.tag_configure("down", foreground=DOWN)
        self.tree.tag_configure("flat", foreground=FLAT)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self.tree.bind("<Double-1>", self._load_selected_kline)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")

    def _build_kline_tab(self, tabs: ttk.Notebook) -> None:
        panel = ttk.Frame(tabs, style="Workspace.TFrame", padding=10)
        tabs.add(panel, text="K 线")
        self.kline_panel = panel
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        controls = tk.Frame(panel, bg=SURFACE)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._make_workspace_label(controls, "代码").pack(side="left")
        ttk.Entry(controls, textvariable=self.kline_code_var, width=13).pack(side="left", padx=(5, 14))
        self._make_workspace_label(controls, "周期").pack(side="left")
        ttk.Combobox(controls, textvariable=self.kline_period_var,
                     values=KLINE_PERIOD_LABELS, state="readonly", width=10).pack(side="left", padx=(5, 14))
        self._make_workspace_label(controls, "复权").pack(side="left")
        ttk.Combobox(controls, textvariable=self.kline_fq_var,
                     values=KLINE_FQ_LABELS, state="readonly", width=10).pack(side="left", padx=(5, 14))
        self._make_workspace_label(controls, "条数").pack(side="left")
        ttk.Entry(controls, textvariable=self.kline_count_var, width=8).pack(side="left", padx=(5, 14))
        self.kline_button = ttk.Button(controls, text="加载 K 线",
                                       command=self.query_kline, style="Accent.TButton")
        self.kline_button.pack(side="left")
        ttk.Label(panel, textvariable=self.kline_summary_var, style="Muted.TLabel",
                  anchor="w").grid(row=1, column=0, sticky="ew", pady=(0, 7))

        panes = tk.Frame(panel, bg=SURFACE)
        panes.grid(row=2, column=0, sticky="nsew")
        panes.grid_rowconfigure(1, weight=1)
        panes.grid_columnconfigure(0, weight=1)
        self.kline_canvas = tk.Canvas(panes, height=255, background=SURFACE_3,
                                      highlightthickness=1, highlightbackground=BORDER)
        self.kline_canvas.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.kline_canvas.bind("<Configure>", lambda _event: self._draw_kline_chart())
        kline_box = self._make_tree(panes, height=10)
        self.kline_tree = kline_box.tree  # type: ignore[attr-defined]
        kline_box.grid(row=1, column=0, sticky="nsew")
        self._configure_tree(
            self.kline_tree,
            ("date", "open", "high", "low", "close", "volume", "amount", "turnover", "turnover_real"),
            {
                "date": "日期/时间", "open": "开盘", "high": "最高", "low": "最低",
                "close": "收盘", "volume": "成交量", "amount": "成交额",
                "turnover": "换手", "turnover_real": "实际换手",
            },
        )
        self.kline_tree.tag_configure("up", foreground=UP)
        self.kline_tree.tag_configure("down", foreground=DOWN)
        self.kline_tree.tag_configure("flat", foreground=FLAT)
        ttk.Label(panel, textvariable=self.kline_status_var, style="Muted.TLabel",
                  anchor="w").grid(row=3, column=0, sticky="ew", pady=(6, 0))

    def _build_money_tab(self, tabs: ttk.Notebook) -> None:
        panel = ttk.Frame(tabs, style="Workspace.TFrame", padding=10)
        tabs.add(panel, text="资金摘要")
        self.money_panel = panel
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        controls = self._make_detail_controls(
            panel, self.money_summary_var, self.query_money_flow, "加载资金摘要"
        )
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self.money_card_frame = tk.Frame(panel, bg=SURFACE)
        self.money_card_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            self.money_card_frame.grid_columnconfigure(column, weight=1)
        tk.Label(panel, text="字段明细", bg=SURFACE, fg=TEXT,
                 font=FONT_UI_BOLD, anchor="w").grid(row=2, column=0, sticky="ew", pady=(0, 5))
        money_box = self._make_tree(panel, height=12)
        self.money_tree = money_box.tree  # type: ignore[attr-defined]
        money_box.grid(row=3, column=0, sticky="nsew")
        self._configure_tree(self.money_tree, ("field", "value"),
                             {"field": "业务字段", "value": "返回值"})
        self.money_tree.tag_configure("up", foreground=UP)
        self.money_tree.tag_configure("down", foreground=DOWN)
        self.money_tree.tag_configure("flat", foreground=FLAT)
        ttk.Label(panel, textvariable=self.money_status_var, style="Muted.TLabel",
                  anchor="w").grid(row=4, column=0, sticky="ew", pady=(6, 0))

    def _build_history_tab(self, tabs: ttk.Notebook) -> None:
        panel = ttk.Frame(tabs, style="Workspace.TFrame", padding=10)
        tabs.add(panel, text="分钟历史")
        self.history_panel = panel
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        controls = tk.Frame(panel, bg=SURFACE)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._make_workspace_label(controls, "代码").pack(side="left")
        ttk.Entry(controls, textvariable=self.detail_code_var, width=13).pack(side="left", padx=(5, 12))
        self._make_workspace_label(controls, "请求游标").pack(side="left")
        ttk.Entry(controls, textvariable=self.history_request_time_var, width=12).pack(
            side="left", padx=(5, 12)
        )
        self.history_button = ttk.Button(controls, text="加载分钟历史",
                                          command=self.query_minute_history, style="Accent.TButton")
        self.history_button.pack(side="left")
        ttk.Label(panel, textvariable=self.history_summary_var, style="Muted.TLabel",
                  anchor="w").grid(row=1, column=0, sticky="ew", pady=(0, 7))
        history_box = self._make_tree(panel, height=16)
        self.history_tree = history_box.tree  # type: ignore[attr-defined]
        history_box.grid(row=2, column=0, sticky="nsew")
        self._configure_tree(
            self.history_tree, HISTORY_COLUMNS,
            {column: DETAIL_FIELD_LABELS.get(column, column) for column in HISTORY_COLUMNS},
        )
        self.history_tree.tag_configure("up", foreground=UP)
        self.history_tree.tag_configure("down", foreground=DOWN)
        self.history_tree.tag_configure("flat", foreground=FLAT)
        ttk.Label(panel, textvariable=self.history_status_var, style="Muted.TLabel",
                  anchor="w").grid(row=3, column=0, sticky="ew", pady=(6, 0))

    def _build_trade_tab(self, tabs: ttk.Notebook) -> None:
        panel = ttk.Frame(tabs, style="Workspace.TFrame", padding=10)
        tabs.add(panel, text="分时成交")
        self.trade_panel = panel
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        controls = tk.Frame(panel, bg=SURFACE)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._make_workspace_label(controls, "代码").pack(side="left")
        ttk.Entry(controls, textvariable=self.detail_code_var, width=13).pack(side="left", padx=(5, 12))
        self._make_workspace_label(controls, "游标").pack(side="left")
        ttk.Entry(controls, textvariable=self.trade_request_time_var, width=12).pack(
            side="left", padx=(5, 12)
        )
        self.trade_button = ttk.Button(controls, text="加载分时成交",
                                        command=self.query_minute_trades, style="Accent.TButton")
        self.trade_button.pack(side="left", padx=(0, 5))
        self.trade_more_button = ttk.Button(
            controls, text="加载更多", command=self.load_more_minute_trades,
            style="Soft.TButton",
        )
        self.trade_more_button.pack(side="left", padx=(0, 5))
        self.trade_all_button = ttk.Button(
            controls, text="加载到底", command=self.load_all_minute_trades,
            style="Soft.TButton",
        )
        self.trade_all_button.pack(side="left")
        ttk.Label(panel, textvariable=self.trade_summary_var, style="Muted.TLabel",
                  anchor="w").grid(row=1, column=0, sticky="ew", pady=(0, 7))
        self.trade_card_frame = tk.Frame(panel, bg=SURFACE)
        self.trade_card_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            self.trade_card_frame.grid_columnconfigure(column, weight=1)
        trade_box = self._make_tree(panel, height=15)
        self.trade_tree = trade_box.tree  # type: ignore[attr-defined]
        trade_box.grid(row=3, column=0, sticky="nsew")
        self._configure_tree(
            self.trade_tree, TRADE_COLUMNS,
            {column: DETAIL_FIELD_LABELS.get(column, column) for column in TRADE_COLUMNS},
        )
        self.trade_tree.tag_configure("buy", foreground=UP)
        self.trade_tree.tag_configure("sell", foreground=DOWN)
        self.trade_tree.tag_configure("unknown", foreground=FLAT)
        ttk.Label(panel, textvariable=self.trade_status_var, style="Muted.TLabel",
                  anchor="w").grid(row=4, column=0, sticky="ew", pady=(6, 0))

    @staticmethod
    def _make_workspace_label(parent: tk.Frame, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=SURFACE, fg=MUTED, font=FONT_SMALL)

    def _make_detail_controls(
        self,
        parent: ttk.Frame,
        summary_var: tk.StringVar,
        command: Callable[[], None],
        button_text: str,
    ) -> tk.Frame:
        controls = tk.Frame(parent, bg=SURFACE)
        self._make_workspace_label(controls, "代码").pack(side="left")
        ttk.Entry(controls, textvariable=self.detail_code_var, width=13).pack(side="left", padx=(5, 14))
        ttk.Label(controls, textvariable=summary_var, style="Muted.TLabel").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(controls, text=button_text, command=command, style="Accent.TButton").pack(side="right")
        return controls

    @staticmethod
    def _make_tree(parent: tk.Misc, height: int = 10) -> tk.Frame:
        frame = tk.Frame(parent, bg=SURFACE_3, highlightthickness=1, highlightbackground=BORDER)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, show="headings", selectmode="browse", height=height)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.tree = tree  # type: ignore[attr-defined]
        return frame

    def _configure_tree(
        self,
        tree: ttk.Treeview,
        columns: tuple[str, ...] | list[str],
        headings: dict[str, str],
    ) -> None:
        columns = tuple(columns)
        tree.configure(columns=columns, displaycolumns=columns)
        for column in columns:
            tree.heading(column, text=headings.get(column, column))
            tree.column(
                column,
                width=self._detail_column_width(column),
                minwidth=75,
                anchor="w",
                stretch=False,
            )

    def _build_statusbar(self) -> None:
        statusbar = tk.Frame(self.root, bg=TOPBAR, height=29)
        statusbar.grid(row=2, column=0, sticky="ew")
        statusbar.grid_propagate(False)
        tk.Label(statusbar, text="●", bg=TOPBAR, fg=CYAN, font=FONT_SMALL).pack(
            side="left", padx=(18, 5)
        )
        tk.Label(statusbar, textvariable=self.status_var, bg=TOPBAR, fg=TEXT,
                 font=FONT_SMALL, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(statusbar, textvariable=self.active_job_var, bg=TOPBAR, fg=MUTED,
                 font=FONT_MONO_SMALL).pack(side="right", padx=18)

    # ── 树表和显示 ────────────────────────────────────────────────────────

    def _on_fields_changed(self, *_args) -> None:
        tokens = [token.strip() for token in self.fields_var.get().split(",") if token.strip()]
        self.field_count_var.set(f"{len(tokens)} 个字段")

    def _on_filter_changed(self, *_args) -> None:
        if hasattr(self, "tree"):
            self._render_rows(self.current_rows)

    def _select_field_group(self, label: str) -> None:
        self.preset_var.set(label)
        self._apply_preset()

    def _on_preset_selected(self, _event=None) -> None:
        self._apply_preset()

    def _apply_preset(self) -> None:
        selected = self.preset_var.get()
        for label, fields in FIELD_PRESETS:
            if label == selected:
                self.fields_var.set(fields)
                if label == ALL_KNOWN_PRESET:
                    self.count_var.set("100")
                    self.status_var.set("已应用全部已知字段；每页已调整为 100 条。")
                else:
                    self.status_var.set(f"已应用字段预设：{label}。")
                return

    def _selected_universe(self) -> str:
        return UNIVERSE_CODES.get(self.universe_var.get().strip(), UNIVERSES[0][0])

    def _read_timeout(self) -> float:
        try:
            value = float(self.timeout_var.get().strip())
        except ValueError as exc:
            raise ValueError("超时必须是数字") from exc
        if value <= 0:
            raise ValueError("超时必须大于 0")
        return max(1.0, value)

    def _read_options(self) -> tuple[str, str, int, int, float]:
        base_url = self.base_url_var.get().strip()
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("本地地址必须以 http:// 或 https:// 开头")
        fields = self.fields_var.get().strip()
        if not fields or not any(token.strip() for token in fields.split(",")):
            raise ValueError("列表字段不能为空")
        try:
            skip = int(self.skip_var.get().strip())
            count = int(self.count_var.get().strip())
        except ValueError as exc:
            raise ValueError("跳过和每页条数必须是整数") from exc
        if skip < 0:
            raise ValueError("跳过不能小于 0")
        if count <= 0:
            raise ValueError("每页条数必须大于 0")
        if count > 1000:
            self.status_var.set("提示：单页建议不超过 1000 条；字段越多越应调小。")
        return base_url, fields, skip, count, self._read_timeout()

    def _read_detail_options(self, allow_option: bool = False) -> tuple[str, str, str, float]:
        base_url = self.base_url_var.get().strip()
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("本地地址必须以 http:// 或 https:// 开头")
        raw_code = self.detail_code_var.get()
        raw_upper = str(raw_code or "").strip().upper()
        if allow_option and (raw_upper.startswith("SO") or
                             (len(raw_upper) == 8 and raw_upper.isdigit())):
            code = normalize_option_detail_code(raw_upper)
        else:
            code = normalize_detail_code(raw_code, self.detail_market_var.get())
        self.detail_code_var.set(code)
        return base_url, code, self.detail_fields_var.get().strip(), self._read_timeout()

    def _read_request_time(self, variable: tk.StringVar,
                           allow_negative: bool = False) -> int:
        try:
            value = int(variable.get().strip() or "0")
        except ValueError as exc:
            raise ValueError("请求游标必须是整数") from exc
        if value < 0 and not allow_negative:
            raise ValueError("请求游标不能小于 0")
        return value

    def _render_rows(self, rows: list[dict]) -> None:
        query = self.filter_var.get().strip().casefold()
        render_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if query:
                searchable = " ".join(str(row.get(key, "")) for key in ("code", "1", "name", "industry_name"))
                if query not in searchable.casefold():
                    continue
            render_rows.append((row, dict(row)))

        columns: list[str] = []
        row_keys = {str(key) for _original, view in render_rows for key in view}
        for token in (token.strip() for token in self.fields_var.get().split(",")):
            if not token:
                continue
            field_name = FIELD_ID_TO_NAME.get(token, token)
            if not row_keys or field_name in row_keys or token in FIELD_ID_TO_NAME:
                if field_name not in columns:
                    columns.append(field_name)
        for _original, view in render_rows:
            for key in view:
                key = str(key)
                if key not in columns:
                    columns.append(key)

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.row_by_item.clear()

        if not columns:
            columns = ["message"]
            self.tree.configure(columns=columns, displaycolumns=columns)
            self.tree.heading("message", text="数据")
            self.tree.column("message", width=650, anchor="w")
            self.tree.insert("", "end", values=("当前没有数据，请先查询列表。",))
            self.tree_columns = columns
            self.list_toolbar_status_var.set("暂无列表数据")
            return

        self.tree_columns = columns
        self.tree.configure(columns=columns, displaycolumns=columns)
        for column in columns:
            self.tree.heading(column, text=self._column_heading(column))
            self.tree.column(column, width=self._column_width(column), minwidth=75,
                             anchor="w", stretch=False)

        for original, view in render_rows:
            values = [self._display_value(view.get(column, ""), column) for column in columns]
            item = self.tree.insert("", "end", values=values, tags=(self._change_tag(original),))
            self.row_by_item[item] = original

        self.list_toolbar_status_var.set(
            f"显示 {len(render_rows):,} / {len(rows):,} 条"
            + (" · 本地筛选" if query else "")
        )
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
            self._on_row_selected()

    def _render_dynamic_tree(
        self,
        tree: ttk.Treeview,
        rows: list[dict],
        preferred: tuple[str, ...] = (),
        row_tag: Callable[[dict], str] | None = None,
    ) -> None:
        actual_rows = [row for row in rows if isinstance(row, dict)]
        keys = {str(key) for row in actual_rows for key in row}
        columns = [column for column in preferred if column in keys]
        for row in actual_rows:
            for key in row:
                key = str(key)
                if key not in columns:
                    columns.append(key)
        for item in tree.get_children():
            tree.delete(item)
        if not columns:
            columns = ["message"]
            self._configure_tree(tree, tuple(columns), {"message": "数据"})
            tree.insert("", "end", values=("当前没有数据。",))
            return
        self._configure_tree(
            tree, tuple(columns),
            {column: DETAIL_FIELD_LABELS.get(column, FIELD_LABELS.get(column, column))
             for column in columns},
        )
        for row in actual_rows:
            values = [self._format_detail_value(row.get(column), column) for column in columns]
            tag = row_tag(row) if row_tag else ""
            tree.insert("", "end", values=values, tags=(tag,) if tag else ())

    def _render_money_table(self) -> None:
        for item in self.money_tree.get_children():
            self.money_tree.delete(item)
        for key, value in self.money_data.items():
            tag = self._number_tag(value)
            self.money_tree.insert(
                "", "end",
                values=(DETAIL_FIELD_LABELS.get(key, key), self._format_detail_value(value, key)),
                tags=(tag,),
            )

    def _render_money_cards(self) -> None:
        for child in self.money_card_frame.winfo_children():
            child.destroy()
        for index, (title, key, color) in enumerate(MONEY_CARD_FIELDS):
            card = tk.Frame(self.money_card_frame, bg=SURFACE_3,
                            highlightthickness=1, highlightbackground=BORDER)
            card.grid(row=index // 4, column=index % 4, sticky="ew",
                      padx=(0 if index % 4 == 0 else 4, 4 if index % 4 < 3 else 0),
                      pady=(0 if index < 4 else 6, 0))
            tk.Frame(card, bg=color, width=3).pack(side="left", fill="y")
            content = tk.Frame(card, bg=SURFACE_3)
            content.pack(side="left", fill="both", expand=True)
            tk.Label(content, text=title, bg=SURFACE_3, fg=MUTED,
                     font=FONT_SMALL).pack(anchor="w", padx=9, pady=(6, 0))
            value = self.money_data.get(key, "—")
            tk.Label(content, text=self._format_detail_value(value, key),
                     bg=SURFACE_3, fg=TEXT, font=("Consolas", 12, "bold")).pack(
                         anchor="w", padx=9, pady=(0, 6)
                     )

    def _render_trade_cards(self, payload: dict[str, Any], loaded_count: int | None = None) -> None:
        for child in self.trade_card_frame.winfo_children():
            child.destroy()
        cards = (
            ("服务上限", format_integer(payload.get("max_count", 0))),
            ("可用数据", format_integer(payload.get("data_count", 0))),
            ("当前已加载", format_integer(
                loaded_count if loaded_count is not None else payload.get("count", 0)
            )),
        )
        for index, (title, value) in enumerate(cards):
            card = tk.Frame(self.trade_card_frame, bg=SURFACE_3,
                            highlightthickness=1, highlightbackground=BORDER)
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 5, 0))
            tk.Label(card, text=title, bg=SURFACE_3, fg=MUTED,
                     font=FONT_SMALL).pack(anchor="w", padx=12, pady=(7, 0))
            tk.Label(card, text=value, bg=SURFACE_3,
                     fg=TEXT, font=("Consolas", 14, "bold")).pack(anchor="w", padx=12, pady=(0, 7))

    # ── 异步请求 ─────────────────────────────────────────────────────────

    def _start_worker(
        self,
        worker: Callable[[], object],
        on_success: Callable[[object], None],
        job_label: str,
    ) -> None:
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        self.active_job_var.set(f"请求中 · {job_label}")
        self.header_status_var.set("LOCAL  ·  BUSY")
        self._update_navigation()

        def run() -> None:
            try:
                result = worker()
            except Exception as exc:
                self.worker_queue.put(("error", str(exc)))
            else:
                self.worker_queue.put(("success", (on_success, result)))

        threading.Thread(target=run, name="d4-gui-worker", daemon=True).start()

    def _drain_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "progress":
                    self.status_var.set(str(payload))
                elif kind == "error":
                    self._worker_failed(str(payload))
                elif kind == "success":
                    on_success, result = payload
                    self._worker_succeeded(on_success, result)
        except queue.Empty:
            pass
        try:
            if self.root.winfo_exists():
                self.root.after(50, self._drain_worker_queue)
        except tk.TclError:
            pass

    def _worker_succeeded(self, on_success: Callable[[object], None], result: object) -> None:
        self.busy = False
        self.active_job_var.set("完成")
        self.header_status_var.set("LOCAL  ·  READY")
        self._update_navigation()
        on_success(result)

    def _worker_failed(self, message: str) -> None:
        self.busy = False
        self.active_job_var.set("失败")
        self.header_status_var.set("LOCAL  ·  READY")
        self._update_navigation()
        self.status_var.set("请求失败：" + message)
        messagebox.showerror("D4 请求失败", message, parent=self.root)

    # ── 列表请求 ─────────────────────────────────────────────────────────

    def query_current_page(self) -> None:
        try:
            base_url, fields, skip, count, timeout = self._read_options()
        except ValueError as exc:
            messagebox.showwarning("参数检查", str(exc), parent=self.root)
            return
        universe = self._selected_universe()
        self.status_var.set(f"正在读取 {self.universe_var.get()} · 从第 {skip:,} 条开始 ...")
        self.workspace_tabs.select(self.list_panel)
        self._start_worker(
            lambda: fetch_page(base_url, universe, skip, count, fields, timeout),
            self._show_page,
            "市场列表",
        )

    def first_page(self) -> None:
        if self.busy:
            return
        self.skip_var.set("0")
        self.query_current_page()

    def previous_page(self) -> None:
        if self.busy or self.current_skip <= 0:
            return
        try:
            base_url, fields, _skip, count, timeout = self._read_options()
        except ValueError as exc:
            messagebox.showwarning("参数检查", str(exc), parent=self.root)
            return
        new_skip = max(0, self.current_skip - self.last_page_size)
        self.skip_var.set(str(new_skip))
        self.status_var.set(f"正在读取第 {new_skip:,} 条开始的数据 ...")
        self._start_worker(
            lambda: fetch_page(base_url, self._selected_universe(), new_skip, count, fields, timeout),
            self._show_page,
            "上一页",
        )

    def next_page(self) -> None:
        if self.busy or not self.current_rows:
            return
        next_skip = self.current_skip + len(self.current_rows)
        if self.current_total and next_skip >= self.current_total:
            return
        try:
            base_url, fields, _skip, count, timeout = self._read_options()
        except ValueError as exc:
            messagebox.showwarning("参数检查", str(exc), parent=self.root)
            return
        self.skip_var.set(str(next_skip))
        self.status_var.set(f"正在读取第 {next_skip:,} 条开始的数据 ...")
        self._start_worker(
            lambda: fetch_page(base_url, self._selected_universe(), next_skip, count, fields, timeout),
            self._show_page,
            "下一页",
        )

    def read_all(self) -> None:
        try:
            base_url, fields, _skip, count, timeout = self._read_options()
        except ValueError as exc:
            messagebox.showwarning("参数检查", str(exc), parent=self.root)
            return

        universe = self._selected_universe()
        self.status_var.set(f"正在分页读取 {self.universe_var.get()}，可点击“取消”停止 ...")

        def worker() -> AllResult:
            rows_by_code: dict[str, dict] = {}
            rows_without_code: list[dict] = []
            total = 0
            skip = 0
            pages = 0
            while not self.cancel_event.is_set():
                page = fetch_page(base_url, universe, skip, count, fields, timeout)
                total = page.total
                pages += 1
                for row in page.rows:
                    identity = self._row_identity(row)
                    if identity is None:
                        rows_without_code.append(row)
                    else:
                        rows_by_code[identity] = row
                self.worker_queue.put((
                    "progress",
                    f"已读取 {len(rows_by_code) + len(rows_without_code):,} 条 · "
                    f"源端 {total:,} 条 · 第 {pages} 页",
                ))
                if not page.rows:
                    break
                skip += len(page.rows)
                if total and skip >= total:
                    break
            rows = list(rows_by_code.values()) + rows_without_code
            return AllResult(total, rows, pages, self.cancel_event.is_set())

        self._start_worker(worker, self._show_all, "读取全部")

    def cancel(self) -> None:
        if self.busy:
            self.cancel_event.set()
            self.status_var.set("正在停止，等待当前请求返回 ...")

    def _show_page(self, result: object) -> None:
        assert isinstance(result, PageResult)
        self.current_skip = result.skip
        self.current_rows = result.rows
        self.current_total = result.total
        self.last_page_size = result.requested_count
        self.skip_var.set(str(result.skip))
        self._render_rows(result.rows)
        end = result.skip + len(result.rows) - 1 if result.rows else result.skip - 1
        page_text = f"{result.skip:,}～{end:,}" if result.rows else "无数据"
        self.summary_var.set(
            f"{self.universe_var.get()} · 记录 {page_text} · 返回 {len(result.rows):,} 条"
        )
        self._set_stats(result.total, page_text, len(result.rows))
        self.status_var.set("当前页读取完成 · 选择一行查看历史数据")
        self._update_navigation()

    def _show_all(self, result: object) -> None:
        assert isinstance(result, AllResult)
        self.current_skip = 0
        self.current_rows = result.rows
        self.current_total = result.total
        self.last_page_size = len(result.rows) or self.last_page_size
        self.skip_var.set("0")
        self._render_rows(result.rows)
        self.summary_var.set(
            f"{self.universe_var.get()} · 已汇总 {len(result.rows):,} 条 · 共读取 {result.pages} 页"
        )
        self._set_stats(result.total, "全部", len(result.rows))
        self.status_var.set(
            "读取被取消，已显示已收到的数据。" if result.cancelled else "全部读取完成。"
        )
        self._update_navigation()

    # ── 详情请求 ─────────────────────────────────────────────────────────

    def _detail_base(self, allow_option: bool = False) -> tuple[str, str, str, float] | None:
        try:
            return self._read_detail_options(allow_option=allow_option)
        except ValueError as exc:
            messagebox.showwarning("详情参数检查", str(exc), parent=self.root)
            return None

    def query_kline(self) -> None:
        base_url = self.base_url_var.get().strip()
        if not base_url.startswith(("http://", "https://")):
            messagebox.showwarning("K 线参数检查", "本地地址必须以 http:// 或 https:// 开头", parent=self.root)
            return
        code = normalize_kline_code(self.kline_code_var.get())
        qualified = len(code) == 8 and code[:2] in {"SH", "SZ", "BJ"} and code[2:].isdigit()
        option_qualified = len(code) == 10 and code[:2] == "SO" and code[2:].isdigit()
        option_bare = len(code) == 8 and code.isdigit()
        if not ((len(code) == 6 and code.isdigit()) or qualified or option_qualified or option_bare):
            messagebox.showwarning(
                "K 线参数检查",
                "K 线代码请输入 6 位数字、SH/SZ/BJ 加 6 位，或 SO 加 8 位期权合约号",
                parent=self.root,
            )
            return
        try:
            period = int(next(value for value, label in KLINE_PERIODS
                              if label == self.kline_period_var.get().strip()))
            fq = next(value for value, label in KLINE_FQ_OPTIONS
                      if label == self.kline_fq_var.get().strip())
            count = int(self.kline_count_var.get().strip())
            timeout = self._read_timeout()
        except (ValueError, StopIteration):
            messagebox.showwarning("K 线参数检查", "周期、复权、条数和超时必须有效", parent=self.root)
            return
        if count <= 0 or count > 1000:
            messagebox.showwarning("K 线参数检查", "K 线条数必须在 1 到 1000 之间", parent=self.root)
            return
        self.kline_code_var.set(code)
        self.workspace_tabs.select(self.kline_panel)
        self.kline_status_var.set(f"正在读取 {code} 的 K 线 ...")
        self._start_worker(
            lambda: fetch_kline(base_url, code, period, count, fq, timeout),
            self._show_kline,
            "K 线",
        )

    def query_money_flow(self) -> None:
        options = self._detail_base()
        if options is None:
            return
        base_url, code, fields, timeout = options
        self.workspace_tabs.select(self.money_panel)
        self.money_summary_var.set(f"{code} · 正在读取")
        self.money_status_var.set("资金摘要请求进行中 ...")
        self._start_worker(
            lambda: fetch_money_flow(base_url, code, self.detail_market_var.get(), fields, timeout),
            self._show_money_flow,
            "资金摘要",
        )

    def query_minute_history(self) -> None:
        options = self._detail_base()
        if options is None:
            return
        try:
            request_time = self._read_request_time(self.history_request_time_var)
        except ValueError as exc:
            messagebox.showwarning("分钟历史参数检查", str(exc), parent=self.root)
            return
        base_url, code, fields, timeout = options
        self.workspace_tabs.select(self.history_panel)
        self.history_summary_var.set(f"{code} · 正在读取")
        self.history_status_var.set("分钟历史请求进行中 ...")
        self._start_worker(
            lambda: fetch_minute_history(
                base_url, code, self.detail_market_var.get(), fields, request_time, timeout
            ),
            self._show_minute_history,
            "分钟历史",
        )

    def query_minute_trades(self) -> None:
        options = self._detail_base(allow_option=True)
        if options is None:
            return
        base_url, code, _fields, timeout = options
        option_code = is_option_trade_code(code)
        try:
            raw_cursor = self.trade_request_time_var.get().strip()
            # Keep the existing stock default of 0, but make a fresh option
            # query open on the newest page as the mobile page does.
            if option_code and raw_cursor in {"", "0"}:
                request_time = -1
            else:
                request_time = self._read_request_time(
                    self.trade_request_time_var, allow_negative=option_code
                )
        except ValueError as exc:
            messagebox.showwarning("分时成交参数检查", str(exc), parent=self.root)
            return
        self.trade_request_time_var.set(str(request_time))
        market = self.detail_market_var.get()
        self.trade_code = code
        self.trade_next_request_time = request_time
        self.trade_available_count = 0
        self.trade_max_count = 0
        self.trade_loaded_pages = 0
        self.trade_has_more = True
        self.trade_rows = []
        self.workspace_tabs.select(self.trade_panel)
        self.trade_summary_var.set(f"{code} · 正在读取")
        self.trade_status_var.set("分时成交请求进行中 ...")
        self._start_worker(
            lambda: TradePageResult(
                fetch_minute_trades(
                    base_url, code, market, request_time, timeout
                ),
                request_time,
            ),
            self._show_minute_trades,
            "分时成交",
        )

    def load_more_minute_trades(self) -> None:
        if self.busy or not self.trade_has_more:
            return
        options = self._detail_base(allow_option=True)
        if options is None:
            return
        base_url, code, _fields, timeout = options
        market = self.detail_market_var.get()
        if code != self.trade_code or not self.trade_rows:
            messagebox.showinfo(
                "分时成交",
                "请先点击“加载分时成交”，再继续加载当前品种。",
                parent=self.root,
            )
            return

        request_time = self.trade_next_request_time
        self.workspace_tabs.select(self.trade_panel)
        self.trade_status_var.set(
            f"正在加载更多 · 已有 {len(self.trade_rows):,} 条 · 游标 {request_time} ..."
        )
        self._start_worker(
            lambda: TradePageResult(
                fetch_minute_trades(
                    base_url, code, market, request_time, timeout
                ),
                request_time,
            ),
            self._append_minute_trades,
            "更多分时成交",
        )

    def load_all_minute_trades(self) -> None:
        if self.busy:
            return
        options = self._detail_base(allow_option=True)
        if options is None:
            return
        base_url, code, _fields, timeout = options
        market = self.detail_market_var.get()
        if code == self.trade_code and self.trade_rows:
            seed_rows = list(self.trade_rows)
            request_time = self.trade_next_request_time
        else:
            try:
                option_code = is_option_trade_code(code)
                raw_cursor = self.trade_request_time_var.get().strip()
                if option_code and raw_cursor in {"", "0"}:
                    request_time = -1
                else:
                    request_time = self._read_request_time(
                        self.trade_request_time_var, allow_negative=option_code
                    )
            except ValueError as exc:
                messagebox.showwarning("分时成交参数检查", str(exc), parent=self.root)
                return
            seed_rows = []
            self.trade_code = code
            self.trade_next_request_time = request_time
            self.trade_available_count = 0
            self.trade_max_count = 0
            self.trade_loaded_pages = 0
            self.trade_has_more = True
            self.trade_rows = []

        self.workspace_tabs.select(self.trade_panel)
        self.trade_summary_var.set(f"{code} · 正在加载到底")
        self.trade_status_var.set(
            f"正在连续读取分时成交 · 已有 {len(seed_rows):,} 条 · 最多 {TRADE_AUTO_LOAD_LIMIT:,} 条 ..."
        )

        def worker() -> TradeAllResult:
            return fetch_minute_trades_all(
                base_url,
                code,
                market,
                request_time,
                timeout,
                seed_rows=seed_rows,
                progress=lambda message: self.worker_queue.put(("progress", message)),
                cancelled=self.cancel_event.is_set,
                max_rows=TRADE_AUTO_LOAD_LIMIT,
            )

        self._start_worker(worker, self._show_all_minute_trades, "加载到底")

    def _show_kline(self, result: object) -> None:
        assert isinstance(result, KlineResult)
        self.kline_rows = result.rows
        period_label = next(
            (label for value, label in KLINE_PERIODS if value == str(result.period)),
            str(result.period),
        )
        self.kline_summary_var.set(
            f"{result.code} · {period_label} · {len(result.rows):,} 根 · "
            f"{self._kline_range_text(result.rows)}"
        )
        self.kline_status_var.set("K 线加载完成 · 红色为上涨，绿色为下跌")
        self._render_kline_rows()

    def _show_money_flow(self, result: object) -> None:
        assert isinstance(result, DetailResult)
        data = result.payload.get("data")
        self.money_data = data if isinstance(data, dict) else {}
        self._render_money_cards()
        self._render_money_table()
        self.money_summary_var.set(f"{result.code} · {len(self.money_data):,} 项摘要数据")
        self.money_status_var.set("资金摘要加载完成 · 数值保留服务端精度")
        self.status_var.set("资金摘要读取完成")

    def _show_minute_history(self, result: object) -> None:
        assert isinstance(result, DetailResult)
        rows = result.payload.get("rows")
        self.history_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        payload = result.payload
        self.history_summary_var.set(
            f"{result.code} · 返回 {len(self.history_rows):,} 条 · "
            f"数据总数 {format_integer(payload.get('data_total', 0))}"
        )
        self._render_dynamic_tree(
            self.history_tree, self.history_rows, HISTORY_COLUMNS,
            row_tag=self._history_change_tag,
        )
        self.history_status_var.set(
            f"分钟历史加载完成 · 集合数据 {format_integer(payload.get('collection_total', 0))} · "
            f"盘后数据 {format_integer(payload.get('after_market_total', 0))}"
        )
        self.status_var.set("分钟历史读取完成")

    def _apply_trade_page(self, detail: DetailResult, requested_cursor: int,
                          replace: bool) -> None:
        rows = detail.payload.get("rows")
        raw_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        if replace:
            self.trade_rows = list(raw_rows)
            new_count = len(raw_rows)
        else:
            self.trade_rows, new_count = merge_trade_rows(self.trade_rows, raw_rows)

        self.trade_code = detail.code
        self.trade_available_count = _payload_int(detail.payload, "data_count")
        self.trade_max_count = _payload_int(detail.payload, "max_count")
        self.trade_loaded_pages += 1
        next_cursor = _trade_cursor(detail.payload, raw_rows)
        if next_cursor is not None:
            self.trade_next_request_time = next_cursor
            self.trade_request_time_var.set(str(next_cursor))

        service_has_more = detail.payload.get("has_more")
        self.trade_has_more = _trade_page_can_continue(
            detail.payload, len(raw_rows), len(self.trade_rows)
        )
        if not raw_rows or (not replace and new_count <= 0):
            self.trade_has_more = False
        if next_cursor is None or (
            not isinstance(service_has_more, bool) and
            requested_cursor > 0 and next_cursor <= requested_cursor
        ):
            self.trade_has_more = False

        self._render_dynamic_tree(
            self.trade_tree, self.trade_rows, TRADE_COLUMNS,
            row_tag=self._trade_tag,
        )
        self._render_trade_cards(detail.payload, len(self.trade_rows))
        available_text = (
            f" / 可用 {self.trade_available_count:,} 条"
            if self.trade_available_count else ""
        )
        self.trade_summary_var.set(
            f"{detail.code} · 已加载 {len(self.trade_rows):,} 条{available_text} · "
            f"本次新增 {new_count:,} 条"
        )
        if self.trade_has_more:
            self.trade_status_var.set(
                f"本次返回 {len(raw_rows):,} 条 · 还可继续加载 · 下一游标 {self.trade_next_request_time}"
            )
        elif self.trade_available_count and len(self.trade_rows) >= self.trade_available_count:
            self.trade_status_var.set(
                f"已加载到底 · 共 {len(self.trade_rows):,} 条 · 共请求 {self.trade_loaded_pages} 次"
            )
        elif not raw_rows or (not replace and new_count <= 0):
            self.trade_status_var.set("没有更多数据 · 服务端游标没有产生新记录")
        else:
            self.trade_status_var.set(
                f"当前已到末尾 · 本次返回 {len(raw_rows):,} 条 · 共请求 {self.trade_loaded_pages} 次"
            )
        self.status_var.set("分时成交读取完成")
        self._update_navigation()

    def _show_minute_trades(self, result: object) -> None:
        if isinstance(result, TradePageResult):
            self._apply_trade_page(result.detail, result.request_time, replace=True)
            return
        assert isinstance(result, DetailResult)
        self._apply_trade_page(result, self.trade_next_request_time, replace=True)

    def _append_minute_trades(self, result: object) -> None:
        if isinstance(result, TradePageResult):
            self._apply_trade_page(result.detail, result.request_time, replace=False)
            return
        assert isinstance(result, DetailResult)
        self._apply_trade_page(result, self.trade_next_request_time, replace=False)

    def _show_all_minute_trades(self, result: object) -> None:
        assert isinstance(result, TradeAllResult)
        self.trade_code = result.code
        self.trade_rows = result.rows
        self.trade_available_count = _payload_int(result.payload, "data_count")
        self.trade_max_count = _payload_int(result.payload, "max_count")
        self.trade_loaded_pages += result.pages
        next_cursor = _trade_cursor(result.payload, self.trade_rows)
        if next_cursor is not None:
            self.trade_next_request_time = next_cursor
            self.trade_request_time_var.set(str(next_cursor))
        self.trade_has_more = result.has_more

        self._render_dynamic_tree(
            self.trade_tree, self.trade_rows, TRADE_COLUMNS,
            row_tag=self._trade_tag,
        )
        self._render_trade_cards(result.payload, len(self.trade_rows))
        available_text = (
            f" / 可用 {self.trade_available_count:,} 条"
            if self.trade_available_count else ""
        )
        self.trade_summary_var.set(
            f"{result.code} · 已加载 {len(self.trade_rows):,} 条{available_text} · "
            f"本次新增请求 {result.pages} 次"
        )
        if result.cancelled:
            self.trade_status_var.set(
                f"已停止 · 当前保留 {len(self.trade_rows):,} 条已收到记录"
            )
        elif result.truncated:
            self.trade_status_var.set(
                f"已达到本地上限 {TRADE_AUTO_LOAD_LIMIT:,} 条 · 服务端可能仍有更多"
            )
        elif result.has_more:
            self.trade_status_var.set(
                f"已加载 {len(self.trade_rows):,} 条 · 仍可继续点击“加载更多”"
            )
        else:
            self.trade_status_var.set(
                f"已加载到底 · 共 {len(self.trade_rows):,} 条 · 共请求 {self.trade_loaded_pages} 次"
            )
        self.status_var.set("分时成交加载到底完成")
        self._update_navigation()

    # ── 选中品种与绘图 ───────────────────────────────────────────────────

    def _on_row_selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.row_by_item.get(selection[0])
        if row is None:
            return
        self.selected_row = row
        code = self._row_identity(row) or ""
        name = self._display_value(row.get("name", ""), "name")
        self.selected_code_var.set(code or "—")
        self.selected_name_var.set(name or "未提供名称")
        self.selected_price_var.set(self._display_value(row.get("price", ""), "price") or "—")
        change = row.get("change_pct")
        change_text = self._display_value(change, "change_pct") if change is not None else "—"
        self.selected_change_var.set(f"涨跌 {change_text}")
        self.selected_change_label.configure(fg=self._change_color(row))
        self.selected_strip_change_label.configure(fg=self._change_color(row))
        if code:
            self.kline_code_var.set(normalize_kline_code(code))
            self.detail_code_var.set(code)
        stock_capable = self._is_detail_code(code)
        self.selected_hint_var.set(
            "可打开 K 线与四类详情工作区" if stock_capable else "当前品种可打开 K 线；详情需要股票代码"
        )
        self._update_navigation()

    def _load_selected_kline(self, _event=None) -> None:
        if not self.tree.selection():
            return
        self.query_kline()

    @staticmethod
    def _is_detail_code(code: str) -> bool:
        text = str(code or "").upper()
        if len(text) == 8 and text[:2] in {"SH", "SZ", "BJ"}:
            return text[2:].isdigit()
        return len(text) == 6 and text.isdigit()

    @staticmethod
    def _row_identity(row: dict[str, Any]) -> str | None:
        for key in ("code", "1"):
            value = row.get(key)
            if value is not None and str(value) != "":
                return str(value)
        return None

    @staticmethod
    def _change_tag(row: dict[str, Any]) -> str:
        try:
            value = float(row.get("change_pct"))
        except (TypeError, ValueError):
            return "flat"
        return "up" if value > 0 else "down" if value < 0 else "flat"

    @staticmethod
    def _change_color(row: dict[str, Any]) -> str:
        tag = D4Gui._change_tag(row)
        return UP if tag == "up" else DOWN if tag == "down" else FLAT

    @staticmethod
    def _number_tag(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "flat"
        return "up" if number > 0 else "down" if number < 0 else "flat"

    @staticmethod
    def _history_change_tag(row: dict[str, Any]) -> str:
        try:
            open_value = float(row.get("open_price"))
            close_value = float(row.get("close_price"))
        except (TypeError, ValueError):
            return "flat"
        return "up" if close_value > open_value else "down" if close_value < open_value else "flat"

    @staticmethod
    def _trade_tag(row: dict[str, Any]) -> str:
        direction = str(row.get("direction", "")).lower()
        return "buy" if direction == "buy" else "sell" if direction == "sell" else "unknown"

    def _display_value(self, value: Any, column: str = "") -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            return f"对象（{len(value)} 项）"
        if isinstance(value, list):
            return f"列表（{len(value)} 项）"
        text = str(value)
        return display_name(text, self.privacy_mode) if is_name_field(column) else text

    def _format_detail_value(self, value: Any, column: str = "") -> str:
        if value is None:
            return ""
        if column == "time":
            return format_time_value(value)
        if column == "direction":
            return {"buy": "买", "sell": "卖", "aggregate": "集合",
                    "unknown": "未知"}.get(
                str(value).lower(), str(value)
            )
        if column == "property":
            return str(value)
        if column == "date":
            text = str(value)
            if len(text) == 8 and text.isdigit():
                return f"{text[:4]}-{text[4:6]}-{text[6:]}"
            return text
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, (int, float)):
            return format_integer(value)
        return self._display_value(value, column)

    @staticmethod
    def _column_heading(column: str) -> str:
        return FIELD_LABELS.get(column, column)

    @staticmethod
    def _column_width(column: str) -> int:
        if column in {"code", "price", "change_pct", "change_amt", "pre_close",
                      "open", "high", "low", "bid1", "ask1"}:
            return 112
        if column in {"name", "industry_name", "contract"}:
            return 190
        return 135

    @staticmethod
    def _detail_column_width(column: str) -> int:
        if column in {"time", "date"}:
            return 125
        if column in {"direction"}:
            return 95
        if column in {"field"}:
            return 200
        if column in {"value", "amount"}:
            return 150
        return 120

    def _render_kline_rows(self) -> None:
        for item in self.kline_tree.get_children():
            self.kline_tree.delete(item)
        for row in self.kline_rows:
            values = [
                self._format_kline_cell(row, column)
                for column in ("date", "open", "high", "low", "close",
                               "volume", "amount", "turnover", "turnover_real")
            ]
            self.kline_tree.insert("", "end", values=values, tags=(self._kline_change_tag(row),))
        self._draw_kline_chart()

    def _draw_kline_chart(self) -> None:
        canvas = getattr(self, "kline_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        rows = self.kline_rows[-100:]
        if not rows or width < 80 or height < 80:
            canvas.create_text(width / 2, height / 2, text="选择品种后加载 K 线",
                               fill=DIM, font=FONT_UI_BOLD)
            return

        quotes = []
        for row in rows:
            try:
                values = tuple(self._kline_price(row.get(key))
                               for key in ("open", "high", "low", "close"))
                volume = float(row.get("volume") or 0)
            except (TypeError, ValueError):
                continue
            if any(value is None for value in values):
                continue
            quotes.append((values, max(0.0, volume)))
        if not quotes:
            canvas.create_text(width / 2, height / 2, text="暂无可绘制数据",
                               fill=DIM, font=FONT_UI_BOLD)
            return

        left, right, top, bottom = 18, 70, 18, 30
        volume_height = max(28, int(height * 0.14))
        chart_bottom = height - bottom - volume_height
        lows = [item[0][2] for item in quotes]
        highs = [item[0][1] for item in quotes]
        low_value = min(lows)
        high_value = max(highs)
        margin = max((high_value - low_value) * 0.08, 0.01)
        low_value -= margin
        high_value += margin
        value_range = max(high_value - low_value, 0.01)

        def y(value: float) -> float:
            return top + (high_value - value) / value_range * max(1, chart_bottom - top)

        for index in range(5):
            ratio = index / 4
            line_y = top + ratio * max(1, chart_bottom - top)
            price = high_value - ratio * value_range
            canvas.create_line(left, line_y, width - right, line_y, fill="#1a2c42")
            canvas.create_text(width - right + 8, line_y, text=f"{price:.2f}",
                               fill=MUTED, anchor="w", font=FONT_MONO_SMALL)

        step = (width - left - right) / max(1, len(quotes) - 1)
        candle_width = max(3.0, min(12.0, step * 0.6))
        max_volume = max((item[1] for item in quotes), default=1.0) or 1.0
        for index, ((open_value, high_row, low_row, close_value), volume) in enumerate(quotes):
            x = left + index * step
            color = UP if close_value > open_value else DOWN if close_value < open_value else FLAT
            canvas.create_line(x, y(high_row), x, y(low_row), fill=color, width=1)
            body_top = y(max(open_value, close_value))
            body_bottom = y(min(open_value, close_value))
            if body_bottom - body_top < 2:
                body_bottom = body_top + 2
            canvas.create_rectangle(
                x - candle_width / 2, body_top, x + candle_width / 2, body_bottom,
                outline=color, fill=color if close_value != open_value else SURFACE_3,
            )
            volume_top = height - bottom - volume / max_volume * volume_height
            canvas.create_rectangle(x - candle_width / 2, volume_top,
                                    x + candle_width / 2, height - bottom,
                                    fill=color, outline="")

        canvas.create_text(left, height - 11,
                           text=self._format_kline_date(self.kline_rows[-len(quotes)].get("date")),
                           fill=MUTED, anchor="w", font=FONT_MONO_SMALL)
        canvas.create_text(width - right, height - 11,
                           text=self._format_kline_date(self.kline_rows[-1].get("date")),
                           fill=MUTED, anchor="e", font=FONT_MONO_SMALL)
        canvas.create_text(left, 5, text="D4 · HISTORICAL K-LINE",
                           fill="#31516d", anchor="nw", font=FONT_MONO_SMALL)

    @staticmethod
    def _format_kline_cell(row: dict, column: str) -> str:
        value = row.get(column)
        if value is None:
            return ""
        if column == "date":
            return D4Gui._format_kline_date(value)
        if column in {"open", "high", "low", "close"}:
            price = D4Gui._kline_price(value)
            return "" if price is None else f"{price:.4f}"
        if column in {"volume", "amount"}:
            return format_integer(value)
        return str(value)

    @staticmethod
    def _kline_price(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        # D4 K 线 OHLC 使用 1/10000 价格精度；保留小数输入兼容服务端变化。
        return number / 10000.0 if abs(number) > 100 else number

    @staticmethod
    def _format_kline_date(value: Any) -> str:
        text = str(value or "")
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:]}"
        if len(text) == 10 and text.isdigit():
            return f"20{text[:2]}-{text[2:4]}-{text[4:6]} {text[6:8]}:{text[8:]}"
        return text

    @staticmethod
    def _kline_range_text(rows: list[dict]) -> str:
        if not rows:
            return "暂无数据"
        return (
            f"{D4Gui._format_kline_date(rows[0].get('date'))} → "
            f"{D4Gui._format_kline_date(rows[-1].get('date'))}"
        )

    @staticmethod
    def _kline_change_tag(row: dict) -> str:
        open_value = D4Gui._kline_price(row.get("open"))
        close_value = D4Gui._kline_price(row.get("close"))
        if open_value is None or close_value is None:
            return "flat"
        return "up" if close_value > open_value else "down" if close_value < open_value else "flat"

    def _set_stats(self, total: int, page_text: str, loaded: int) -> None:
        self.total_stat_var.set(f"{total:,}")
        self.page_stat_var.set(page_text)
        self.loaded_stat_var.set(f"{loaded:,}")

    def _update_navigation(self) -> None:
        normal = "normal" if not self.busy else "disabled"
        for button in (
            self.first_button, self.query_button, self.all_button,
            self.kline_button, self.history_button, self.trade_button,
        ):
            button.configure(state=normal)
        self.trade_more_button.configure(
            state="normal"
            if not self.busy and self.trade_has_more and self.detail_code_var.get().strip().upper() == self.trade_code
            else "disabled"
        )
        can_start_trade_all = (
            not self.busy
            and (self.trade_has_more or not self.trade_rows
                 or self.detail_code_var.get().strip().upper() != self.trade_code)
        )
        self.trade_all_button.configure(
            state="normal" if can_start_trade_all else "disabled"
        )
        self.previous_button.configure(
            state="normal" if not self.busy and self.current_skip > 0 else "disabled"
        )
        can_next = bool(self.current_rows) and (
            not self.current_total or self.current_skip + len(self.current_rows) < self.current_total
        )
        self.next_button.configure(state="normal" if not self.busy and can_next else "disabled")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        detail_enabled = "normal" if not self.busy and self._is_detail_code(
            self.selected_code_var.get()
        ) else "disabled"
        for button in self.detail_buttons[1:]:
            button.configure(state=detail_enabled)
        self.detail_buttons[0].configure(
            state="normal" if not self.busy and bool(self.kline_code_var.get().strip()) else "disabled"
        )

    def _copy_selected(self, _event=None):
        if not hasattr(self, "tree"):
            return "break"
        selection = self.tree.selection()
        row = self.row_by_item.get(selection[0]) if selection else None
        if row is None:
            self.status_var.set("请先在列表中选择一行")
            return "break"
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(json.dumps(row, ensure_ascii=False, indent=2))
            self.status_var.set("已复制选中行 JSON")
        except tk.TclError:
            self.status_var.set("复制失败：系统剪贴板不可用")
        return "break"

    def _toggle_privacy(self) -> None:
        self.privacy_mode = not self.privacy_mode
        if self.privacy_button is not None:
            self.privacy_button.configure(text="恢复中文名" if self.privacy_mode else "隐藏中文名")
        self._render_rows(self.current_rows)
        self._render_money_table()

    def _close(self) -> None:
        self.cancel_event.set()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="D4 用户侧证券数据工作台")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="本地程序地址，默认: %(default)s",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="单次请求超时时间（秒），默认: %(default)s",
    )
    args = parser.parse_args()

    root = tk.Tk()
    D4Gui(root, args.base_url, max(1.0, args.timeout))
    root.mainloop()


if __name__ == "__main__":
    main()
