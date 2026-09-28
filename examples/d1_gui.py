#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""达塔接口 d1 用户侧市场数据工作台（Tkinter）。

这个示例按“首页盯盘 → 行情 → 涨停 → 题材 → 复盘 → 个股 → 资讯”的
业务路径组织 d1 能力。它只依赖 Python 标准库，所有请求在后台线程
执行，界面只展示整理后的业务字段，不展示原始报文、请求路由或内部
兼容信息。

运行：

    python d1_gui.py
    python d1_gui.py --base-url http://127.0.0.1:8080

d1 服务需要先在本机启动并完成授权。没有服务时仍可打开并浏览完整界面，
数据区会保持“暂无数据”，不会用虚构行情冒充真实返回。
"""

from __future__ import annotations

import argparse
import json
import math
import queue
import re
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import date, timedelta
from tkinter import ttk
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from privacy_display import display_name, is_name_field


# ── 视觉系统：白底、橙色主色、红涨绿跌，适合用户侧示例 ────────────────

BG = "#f3f4f6"
SURFACE = "#ffffff"
ORANGE = "#ff5a00"
ORANGE_DARK = "#e94800"
ORANGE_SOFT = "#fff0e9"
RED = "#ed3f3f"
GREEN = "#159447"
BLUE = "#397ff0"
PURPLE = "#8769dc"
TEAL = "#1aa39a"
GOLD = "#d99515"
TEXT = "#2b2f35"
TEXT_SOFT = "#60656d"
MUTED = "#969ba3"
LINE = "#e6e8ec"
PALE = "#f5f6f8"

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TINY = ("Microsoft YaHei UI", 8)
FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")
FONT_NUMBER = ("Segoe UI", 17, "bold")
FONT_MONO = ("Consolas", 10)


FormFactory = Callable[[str, str], dict[str, str]]


@dataclass(frozen=True)
class QueryPreset:
    """一个用户可理解的业务查询，不把技术字段暴露给界面。"""

    key: str
    label: str
    category: str
    path: str
    form_factory: FormFactory
    description: str = ""


def _latest_completed_quarter(day: str) -> str:
    """Return the latest completed quarter end accepted by the holdings API."""

    try:
        selected = date.fromisoformat(day)
    except ValueError:
        return day
    quarter_start_month = ((selected.month - 1) // 3) * 3 + 1
    quarter_start = date(selected.year, quarter_start_month, 1)
    next_quarter_month = quarter_start_month + 3
    if next_quarter_month > 12:
        next_quarter = date(selected.year + 1, 1, 1)
    else:
        next_quarter = date(selected.year, next_quarter_month, 1)
    quarter_end = next_quarter - timedelta(days=1)
    if selected < quarter_end:
        quarter_end = quarter_start - timedelta(days=1)
    return quarter_end.isoformat()


def _default_query_day() -> date:
    """Start historical panels on the last completed weekday."""

    selected = date.today() - timedelta(days=1)
    while selected.weekday() >= 5:
        selected -= timedelta(days=1)
    return selected


def _expand_form(template: dict[str, str], stock: str, day: str) -> dict[str, str]:
    """把内部模板转换为请求表单；模板不会被渲染到用户界面。"""

    pure_stock = re.sub(r"^(SH|SZ|BJ)", "", stock.upper())
    result: dict[str, str] = {}
    for key, value in template.items():
        if value == "$stock":
            result[key] = stock
        elif value == "$pure_stock":
            result[key] = pure_stock
        elif value == "$day":
            result[key] = day
        elif value == "$quarter":
            result[key] = _latest_completed_quarter(day)
        else:
            result[key] = value
    return result


def _factory(template: dict[str, str]) -> FormFactory:
    return lambda stock, day, template=template: _expand_form(template, stock, day)


def _preset(
    key: str,
    label: str,
    category: str,
    path: str,
    template: dict[str, str],
    description: str = "",
) -> QueryPreset:
    return QueryPreset(key, label, category, path, _factory(template), description)


# d1 公开业务入口的友好注册表。页面只使用 key，路径和表单只在后台请求时使用。
PRESETS: tuple[QueryPreset, ...] = (
    _preset("index_sh", "上证指数", "指数行情", "/d1/hq", {"a": "GetZsTrend", "c": "StockL2Data", "StockID": "SH000001"}),
    _preset("index_sz", "深证成指", "指数行情", "/d1/hq", {"a": "GetZsTrend", "c": "StockL2Data", "StockID": "SZ399001"}),
    _preset("index_cy", "创业板指", "指数行情", "/d1/hq", {"a": "GetZsTrend", "c": "StockL2Data", "StockID": "SZ399006"}),
    _preset("index_bj", "北证50", "指数行情", "/d1/hq", {"a": "GetZsTrend", "c": "StockL2Data", "StockID": "BJ899050"}),
    _preset("global_index", "全球市场", "指数行情", "/d1/hq", {"a": "GlobalCommon", "c": "GlobalIndex", "View": "1,2,3,4,5,6"}),
    _preset("market_mood", "市场情绪", "市场概况", "/d1/hq", {"a": "MoodNumCount", "c": "MarketMood"}),
    _preset("market_trend", "涨跌趋势", "市场概况", "/d1/his", {"a": "ChangeStatistics", "c": "HisHomeDingPan", "st": "100", "Index": "0"}),
    _preset("market_detail", "涨跌停明细", "市场概况", "/d1/his", {"a": "GetNum", "c": "HisHomeDingPan", "Day": "$day", "Is_st": "1", "FilterMotherboard": "0", "FilterGem": "0", "FilterTIB": "0", "Filter": "0"}),
    _preset("market_capacity", "市场容量", "市场概况", "/d1/his", {"a": "MarketCapacity", "c": "HisHomeDingPan", "Type": "0", "Date": "$day"}),
    _preset("overview_rank", "权重表现", "行情排行", "/d1/hq", {"a": "WeightPerformanceList", "c": "HomeDingPan", "Order": "1", "st": "20", "Index": "0", "Type": "2"}),
    _preset("market_radar", "市场雷达", "异动监控", "/d1/his", {"a": "Radar", "c": "HisHomeDingPan", "st": "30", "Index": "0", "Date": "$day"}),
    _preset("sector_rank", "板块排行", "行情排行", "/d1/his", {"a": "RealRankingInfo", "c": "ZhiShuRanking", "Order": "1", "st": "30", "Index": "0", "Date": "$day", "Type": "2", "ZSType": "6"}),
    _preset("sector_rank_live", "实时板块", "行情排行", "/d1/hq", {"a": "RealRankingInfo", "c": "ZhiShuRanking", "Order": "1", "st": "30", "RStart": "0925", "Index": "0", "REnd": "1315", "Type": "1", "ZSType": "7"}),
    _preset("limit_pool", "涨停池", "涨停复盘", "/d1/hq", {"a": "GetPlateInfo", "c": "DailyLimitResumption", "st": "100", "Index": "0"}),
    _preset("limit_history", "历史涨停复盘", "涨停复盘", "/d1/his", {"a": "GetPlateInfo", "c": "HisLimitResumption", "st": "100", "Index": "0", "Date": "$day"}),
    _preset("limit_performance", "涨停表现", "涨停复盘", "/d1/his", {"a": "ZhangTingExpression", "c": "HisHomeDingPan", "Day": "$day"}),
    _preset("topic_core", "异动板块", "题材板块", "/d1/his", {"a": "GetYTFP_BKHX", "c": "FuPanLa", "Date": "$day"}),
    _preset("topic_points", "题材点位", "题材板块", "/d1/hq", {"a": "GetPoint", "c": "ConceptionPoint"}),
    _preset("topic_news", "题材资讯", "题材板块", "/d1/lhb", {"a": "InfoGR", "c": "Theme"}),
    _preset("emotion_fast", "情绪快线", "情绪资金", "/d1/his", {"a": "GetPMSL_KQXY", "c": "FuPanLa", "Date": "$day"}),
    _preset("emotion_flow", "资金日期", "情绪资金", "/d1/his", {"a": "GetMoneyDate", "c": "Emotion", "st": "30", "index": "0"}),
    _preset("capital_detail", "资金明细", "情绪资金", "/d1/his", {"a": "GetMoneyDetail", "c": "Emotion", "Day": "$day"}),
    _preset("connect_rank", "通道个股排行", "情绪资金", "/d1/hq", {"a": "GetRankingGP", "c": "StockSHGT", "Order": "1", "st": "20", "Index": "0", "Type": "2", "DEnd": "$day", "DStart": "$day"}),
    _preset("connect_flow", "通道资金", "情绪资金", "/d1/lhb", {"a": "GetNXZJ", "c": "LongHuBang"}),
    _preset("index_overview", "指数列表", "指数行情", "/d1/lhb", {"a": "NewGetList", "c": "Index"}),
    _preset("index_kline", "指数K线", "指数行情", "/d1/his", {"a": "GetZhiShuKLine", "c": "ZhiShuKLine", "st": "630", "Index": "0", "Type": "d", "StockID": "SH000001"}),
    _preset("global_kline", "全球K线", "指数行情", "/d1/hq", {"a": "GetDayKLineGlobal", "c": "StockLineData", "st": "120", "Index": "0", "LeiX": "4", "Type": "d", "StockID": "HSI"}),
    _preset("hot_money", "游资动向", "情绪资金", "/d1/lhb", {"a": "YouZiDongXiangByList", "c": "Index", "Time": ""}),
    _preset("institution", "机构持仓", "情绪资金", "/d1/his", {"a": "StockHoldingFund", "c": "InstitutionalPositionsInfo", "st": "25", "Index": "0", "Type": "0", "StockID": "$pure_stock", "Season": "$quarter"}),
    _preset("stock_quote", "个股行情", "个股详情", "/d1/hq", {"a": "GetZsTrend", "c": "StockL2Data", "StockID": "$pure_stock"}),
    _preset("stock_detail", "个股详情", "个股详情", "/d1/lhb", {"a": "GetNewOneStockInfo", "c": "Stock", "Type": "0", "Time": "", "StockID": "$pure_stock"}),
    _preset("stock_chart", "个股图表", "个股详情", "/d1/lhb", {"a": "GetStockChart", "c": "Stock", "StockID": "$pure_stock", "Index": "0", "st": "530"}),
    _preset("stock_kline", "个股K线", "个股详情", "/d1/lhb", {"a": "GetStockChart", "c": "Stock", "StockID": "$pure_stock", "Index": "0", "st": "530"}),
    _preset("stock_order", "委托队列", "个股详情", "/d1/hq", {"a": "GetWeiTuo", "c": "StockL2Data", "st": "25", "Tur": "30", "Type": "0", "Vol": "500", "StockID": "$pure_stock"}),
    _preset("stock_limit", "涨跌停价格", "个股详情", "/d1/hq", {"a": "GetStockPercentTurnoverTen", "c": "StockL2Data", "StockID": "$pure_stock"}),
    _preset("stock_news", "个股资讯", "资讯数据", "/d1/article", {"a": "GetListByID", "c": "PCNewsFlash", "LastID": "0", "st": "20", "Type": "0"}),
    _preset("news_list", "资讯快讯", "资讯数据", "/d1/article", {"a": "GetList", "c": "PCNewsFlash", "st": "20", "Type": "0", "NewsID": "1697724", "Index": "0"}),
    _preset("news_column", "专栏消息", "资讯数据", "/d1/article", {"a": "GetInfo", "c": "ForumsMsgColumn", "ColumnID": "14", "st": "30", "Index": "0", "Select": "0,1,2", "PreIndex": "0"}),
    _preset("company_profile", "公司概况", "F10资料", "/d1/article", {"a": "GetIndex", "c": "StockF10Basic", "StockID": "$pure_stock"}),
    _preset("company_notice", "公司公告", "F10资料", "/d1/his", {"a": "CompanyNewsReportList", "c": "CompanyNotice", "st": "25", "Type": "8", "StockID": "$pure_stock", "Index": "0"}),
    _preset("reports", "研报列表", "F10资料", "/d1/his", {"a": "ResearchFieldList", "c": "CompanyNotice", "st": "25", "Index": "0", "Type": "2", "StockID": "$pure_stock"}),
    _preset("calendar", "交易日历", "工具能力", "/d1/his", {"a": "GetHoliday", "c": "YiDongKanPan"}),
    _preset("watchlist", "自选状态", "工具能力", "/d1/hq", {"a": "UpdateState", "c": "UserSelectStock"}),
    _preset("feature_search", "功能搜索", "工具能力", "/d1/lhb", {"a": "FuncList", "c": "Search"}),
)

PRESET_BY_KEY = {item.key: item for item in PRESETS}


# 能力中心保留 d1 目录的业务视角，点击任意条目即可进入对应查询。
# 同类入口可以共享展示方案，但主页面使用的入口均独立绑定。
CAPABILITY_ROWS: tuple[tuple[str, str, str], ...] = (
    ("市场总览", "核心指数快照", "index_sh"), ("市场总览", "全球市场摘要", "global_index"),
    ("市场总览", "市场情绪数量", "market_mood"), ("市场总览", "市场容量", "market_capacity"),
    ("市场总览", "涨跌趋势", "market_trend"), ("市场总览", "大盘涨跌停明细", "market_detail"),
    ("市场总览", "市场雷达", "market_radar"), ("市场总览", "权重表现", "overview_rank"),
    ("市场总览", "涨停表现", "limit_performance"), ("市场总览", "指数实时摘要", "index_overview"),
    ("历史复盘", "历史个股排行", "overview_rank"), ("历史复盘", "历史涨停复盘", "limit_history"),
    ("历史复盘", "历史打板列表", "limit_history"), ("历史复盘", "历史涨幅明细", "market_detail"),
    ("历史复盘", "历史每日涨跌趋势", "market_trend"), ("历史复盘", "大盘复盘", "market_detail"),
    ("历史复盘", "市场容量复盘", "market_capacity"), ("历史复盘", "急速回撤", "market_radar"),
    ("历史复盘", "权重表现复盘", "overview_rank"), ("历史复盘", "涨跌停统计", "market_detail"),
    ("历史复盘", "涨停池历史记录", "limit_history"), ("历史复盘", "情绪面快线", "emotion_fast"),
    ("行情排行", "实时板块排行", "sector_rank_live"), ("行情排行", "历史板块排行", "sector_rank"),
    ("行情排行", "权重表现列表", "overview_rank"), ("行情排行", "指数列表", "index_overview"),
    ("行情排行", "指数历史K线", "index_kline"), ("行情排行", "全球市场K线", "global_kline"),
    ("行情排行", "指数趋势", "index_sh"), ("行情排行", "指数趋势窄幅", "index_sh"),
    ("行情排行", "个股实时排行", "overview_rank"), ("行情排行", "个股排行标签", "overview_rank"),
    ("题材板块", "异动板块核心", "topic_core"), ("题材板块", "题材点位", "topic_points"),
    ("题材板块", "题材资讯", "topic_news"), ("题材板块", "板块排行", "sector_rank"),
    ("题材板块", "子板块信息", "sector_rank"), ("题材板块", "板块信息全景", "sector_rank"),
    ("题材板块", "概念直播", "topic_news"), ("题材板块", "最强风口K线", "sector_rank"),
    ("题材板块", "板块分时直播", "topic_points"), ("题材板块", "板块资讯", "topic_news"),
    ("情绪资金", "市场情绪", "market_mood"), ("情绪资金", "情绪买卖力度", "emotion_fast"),
    ("情绪资金", "资金明细", "capital_detail"), ("情绪资金", "通道个股排行", "connect_rank"),
    ("情绪资金", "通道资金总计", "connect_flow"), ("情绪资金", "通道资金趋势", "emotion_flow"),
    ("情绪资金", "游资动向", "hot_money"), ("情绪资金", "机构持仓", "institution"),
    ("情绪资金", "北向资金列表", "connect_flow"), ("情绪资金", "南向资金列表", "connect_flow"),
    ("个股详情", "个股行情", "stock_quote"), ("个股详情", "个股详情", "stock_detail"),
    ("个股详情", "个股图表", "stock_chart"), ("个股详情", "个股K线", "stock_kline"),
    ("个股详情", "委托队列", "stock_order"), ("个股详情", "涨跌停价格", "stock_limit"),
    ("个股详情", "个股资讯", "stock_news"), ("个股详情", "自选状态", "watchlist"),
    ("个股详情", "所属板块", "sector_rank"), ("个股详情", "涨停基因", "limit_performance"),
    ("F10资料", "大事提醒", "company_notice"), ("F10资料", "分红送配", "company_profile"),
    ("F10资料", "公司概况", "company_profile"), ("F10资料", "公司新闻报告", "company_notice"),
    ("F10资料", "公司新闻列表", "company_notice"), ("F10资料", "研报列表", "reports"),
    ("F10资料", "机构持仓日期", "institution"), ("F10资料", "基金持仓", "institution"),
    ("F10资料", "机构持仓明细", "institution"), ("F10资料", "公司公告", "company_notice"),
    ("资讯数据", "资讯快讯", "news_list"), ("资讯数据", "按序加载资讯", "stock_news"),
    ("资讯数据", "专栏消息", "news_column"), ("资讯数据", "精选列表", "news_list"),
    ("资讯数据", "聚焦消息", "news_list"), ("资讯数据", "主题资讯", "topic_news"),
    ("工具能力", "交易日历", "calendar"), ("工具能力", "功能搜索", "feature_search"),
    ("工具能力", "自选股刷新", "watchlist"), ("工具能力", "自选状态", "watchlist"),
    ("工具能力", "系统功能开关", "feature_search"), ("工具能力", "榜单更新列表", "overview_rank"),
    ("全球与现货", "全部全球指数", "global_index"), ("全球与现货", "全球指数搜索", "global_index"),
    ("全球与现货", "外围市场变动", "global_index"), ("全球与现货", "现货列表", "global_index"),
    ("全球与现货", "现货分组", "global_index"), ("全球与现货", "现货历史分组", "global_kline"),
    ("全球与现货", "现货文章", "news_list"), ("全球与现货", "海外指数趋势", "global_kline"),
    ("扩展数据", "机构K线", "institution"), ("扩展数据", "机构日列表", "institution"),
    ("扩展数据", "营业部列表", "hot_money"), ("扩展数据", "龙虎榜股票列表", "overview_rank"),
    ("扩展数据", "榜单状态", "overview_rank"), ("扩展数据", "异动趋势", "market_radar"),
    ("扩展数据", "顶部消息", "news_list"), ("扩展数据", "业务状态", "feature_search"),
    ("龙虎榜与榜单", "机构K线排行", "institution"), ("龙虎榜与榜单", "机构明细列表", "institution"),
    ("龙虎榜与榜单", "营业部排行", "hot_money"), ("龙虎榜与榜单", "榜单更新", "overview_rank"),
    ("龙虎榜与榜单", "个股榜单详情", "stock_detail"), ("龙虎榜与榜单", "榜单资金流向", "capital_detail"),
    ("指数专题", "指数文章标题", "news_list"), ("指数专题", "指数综合信息", "index_overview"),
    ("指数专题", "父板块代码", "sector_rank"), ("指数专题", "指数板块列表", "index_overview"),
    ("指数专题", "指数实时排行", "sector_rank_live"), ("指数专题", "指数板块全景", "sector_rank"),
    ("公告与资料", "公司新闻报告", "company_notice"), ("公告与资料", "公告筛选列表", "company_notice"),
    ("公告与资料", "公告正文摘要", "company_notice"), ("公告与资料", "研报列表", "reports"),
    ("公告与资料", "研报导出记录", "reports"), ("公告与资料", "大事提醒", "company_notice"),
    ("用户与系统", "功能列表", "feature_search"), ("用户与系统", "应用消息", "news_list"),
    ("用户与系统", "版本信息", "feature_search"), ("用户与系统", "功能开关", "feature_search"),
    ("用户与系统", "自选股状态", "watchlist"), ("用户与系统", "自选股刷新", "watchlist"),
    ("扩展数据", "委托队列汇总", "stock_order"), ("扩展数据", "涨跌停换手分档", "stock_limit"),
    ("全球与现货", "现货全量", "global_index"), ("行情排行", "指数板块配置", "sector_rank"),
)


FIELD_LABELS: dict[str, str] = {
    "day": "交易日", "date": "日期", "time": "时间", "tradingday": "交易日",
    "code": "代码", "stockid": "标的", "stock_id": "标的", "symbol": "标的",
    "name": "名称", "prodname": "名称", "prod_name": "名称", "stock_name": "名称",
    "price": "价格", "last": "最新价", "lastpx": "最新价", "last_px": "最新价",
    "newprice": "最新价", "curprice": "最新价", "close": "收盘", "closeprice": "收盘",
    "open": "开盘", "high": "最高", "low": "最低", "preclose": "昨收",
    "change": "涨跌额", "pxchange": "涨跌额", "increaseamount": "涨跌额",
    "change_pct": "涨跌幅", "changepercent": "涨跌幅", "increase_rate": "涨跌幅",
    "pxchangerate": "涨跌幅", "px_change_rate": "涨跌幅", "rate": "涨跌幅",
    "volume": "成交量", "vol": "成交量", "amount": "成交额", "turnover": "成交额",
    "turnoverrate": "换手率", "turnover_ratio": "换手率", "ztjs": "涨停家数",
    "df_num": "跌停家数", "dfnum": "跌停家数", "lbgd": "连板高度", "strong": "市场强度",
    "change_rate": "涨跌幅", "score": "强度", "state": "状态", "concept": "题材",
    "plate_code": "板块代码", "plate_name": "板块", "stock_code": "代码",
    "news_id": "消息编号", "id": "编号", "reason": "题材/原因",
    "tip": "市场提示", "message": "提示", "msg": "提示", "errmsg": "提示",
    "total": "总数", "count": "数量", "number": "数量", "status": "状态",
    "category": "分类", "type": "类型", "zf": "涨跌幅", "content": "内容",
    "content2": "补充说明", "plate_type": "板块类型", "fz": "涨幅", "jme": "净额",
    "mrje": "买入额", "mcje": "卖出额", "fengkou": "封单", "circulation": "流通市值",
    "buyin": "买入金额", "joinnum": "参与数量", "amplitude": "振幅", "capitalization": "市值",
    "pb": "破板", "fxb": "炸板", "title": "标题", "subject": "主题", "summary": "摘要",
}

RECORD_KEYS = ("info", "list", "stocklist", "rows", "data", "items", "records", "result", "stocks", "values", "List", "StockList")
DATE_KEYS = {"day", "date", "tradingday", "trading_day", "marketdate", "time"}
BLOCKED_VALUE_KEYS = {"errcode", "errorcode", "ttag", "traceid", "t"}
LIMIT_ROW_FIELDS: tuple[str | None, ...] = (
    "stock_code", "stock_name", None, None, "change_pct", None, None, None,
    None, None, None, "concept", "amount", None, "turnover_rate",
    "total_market_cap", "limit_text", None, "seal_amount", "price", "volume",
    "change_speed", "amount_dup", None, None, None, None, "change_pct_dup",
    None, None, None, None,
)
POSITIONAL_FIELDS: dict[str, tuple[str | None, ...]] = {
    "emotion_fast": ("stock_code", "stock_name", "change_rate", "score", "reason", "state", "concept"),
}


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text in {"—", "-", "null", "None"}:
        return False
    text = text.replace("亿", "").replace("万", "")
    try:
        return math.isfinite(float(text))
    except (TypeError, ValueError):
        return False


def _number(value: Any) -> float | None:
    if not _is_number(value):
        return None
    try:
        text = str(value).strip().replace(",", "").replace("%", "")
        multiplier = 1.0
        if "亿" in text:
            multiplier = 100000000.0
        elif "万" in text:
            multiplier = 10000.0
        return float(text.replace("亿", "").replace("万", "")) * multiplier
    except (TypeError, ValueError):
        return None


def _clip(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_text(value: Any, limit: int = 80) -> str:
    """只允许业务摘要进入控件，链接/HTML/协议文本不直接渲染。"""

    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return "—"
        return f"{value:g}" if isinstance(value, float) else str(value)
    if isinstance(value, dict):
        for key in ("name", "Name", "prodName", "prod_name", "symbol", "code", "StockID"):
            if key in value and value[key] not in (None, ""):
                return _clip(str(value[key]), 36)
        return f"对象（{len(value)}项）"
    if isinstance(value, (list, tuple)):
        return f"列表（{len(value)}项）"
    text = re.sub(r"<[^>]+>", " ", str(value)).strip()
    if re.search(r"(?:https?|wss?)://|(?:[a-z0-9-]+\.)+(?:com|cn|net|org)(?:/|$)", text, re.I):
        return "链接"
    return _clip(text, limit) or "—"


def _friendly_scalar(key: str, value: Any) -> str:
    return _safe_text(value, 120 if key.lower() in {"content", "content2", "message", "tip", "summary"} else 80)


def _normalize_row(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        row: dict[str, Any] = {}
        for key, value in item.items():
            lowered = str(key).lower()
            if lowered in BLOCKED_VALUE_KEYS:
                continue
            row[str(key)] = _friendly_scalar(str(key), value)
        return row or {"_value": "对象"}
    if isinstance(item, (list, tuple)):
        return {f"_field_{index + 1}": _friendly_scalar("", value) for index, value in enumerate(item)}
    return {"_value": _friendly_scalar("", item)}


def _positioned_rows(items: Any, fields: tuple[str | None, ...]) -> list[dict[str, Any]]:
    """Give array-shaped business records stable names before table rendering."""

    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            rows.append(_normalize_row(item))
            continue
        if not isinstance(item, (list, tuple)):
            continue
        row = {
            field: item[index]
            for index, field in enumerate(fields)
            if field and index < len(item)
        }
        if row:
            rows.append(_normalize_row(row))
    return rows


def _field_map_records(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Use the server-supplied names for positional arrays when available."""

    field_map = next(
        (child for key, child in value.items() if str(key).lower() == "field_map"),
        None,
    )
    if not isinstance(field_map, dict):
        return []
    source_by_name = {str(key).lower(): child for key, child in value.items()}
    for source_name, fields in field_map.items():
        if not isinstance(fields, list) or not any(isinstance(field, str) and field for field in fields):
            continue
        source = source_by_name.get(str(source_name).lower())
        if not isinstance(source, list) or not source:
            continue
        rows = _positioned_rows(source, tuple(field if isinstance(field, str) else None for field in fields))
        if rows:
            return rows
    return []


def _find_records(value: Any, depth: int = 0) -> list[dict[str, Any]]:
    """兼容 d1 常见返回形态，统一转换为适合表格的行。"""

    if depth > 6:
        return []
    if isinstance(value, list):
        if not value:
            return []
        return [_normalize_row(item) for item in value]
    if not isinstance(value, dict):
        return [_normalize_row(value)] if value not in (None, "") else []

    # Several d1 responses carry a user-friendly parallel result such as
    # ``list_named``/``info_named`` next to the original positional array.
    for key, child in value.items():
        if str(key).lower().endswith("_named") and isinstance(child, (list, dict)):
            rows = _find_records(child, depth + 1)
            if rows:
                return rows
    mapped_rows = _field_map_records(value)
    if mapped_rows:
        return mapped_rows

    lowered = {str(key).lower(): child for key, child in value.items()}
    for key in RECORD_KEYS:
        child = lowered.get(key.lower())
        if isinstance(child, (list, dict)):
            rows = _find_records(child, depth + 1)
            if rows:
                return rows
    scalar_keys = [key for key, child in value.items() if not isinstance(child, (dict, list, tuple))]
    if len(scalar_keys) >= 2:
        return [_normalize_row(value)]
    for child in value.values():
        if isinstance(child, (dict, list)):
            rows = _find_records(child, depth + 1)
            if rows and (len(rows) > 1 or any(len(row) > 1 for row in rows)):
                return rows
    return [_normalize_row(value)]


def _ci_value(mapping: dict[str, Any], *names: str, default: Any = None) -> Any:
    lowered = {str(key).lower(): value for key, value in mapping.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, ""):
            return lowered[name.lower()]
    return default


def _deep_find(value: Any, names: Iterable[str], depth: int = 0) -> Any:
    if depth > 6:
        return None
    wanted = {name.lower() for name in names}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in wanted and child not in (None, "", [], {}):
                return child
        for child in value.values():
            if isinstance(child, (dict, list, tuple)):
                found = _deep_find(child, wanted, depth + 1)
                if found not in (None, "", [], {}):
                    return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = _deep_find(child, wanted, depth + 1)
            if found not in (None, "", [], {}):
                return found
    return None


def _trend_point(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        price = _ci_value(item, "price", "last", "lastPx", "last_px", "close")
        if _number(price) is not None:
            return {"price": price, "time": _ci_value(item, "time", "Time")}
    elif isinstance(item, (list, tuple)) and len(item) > 1 and _number(item[1]) is not None:
        return {"time": item[0], "price": item[1]}
    return {}


def _trend_last_point(payload: Any) -> dict[str, Any]:
    trend = _deep_find(payload, ("trend",))
    if isinstance(trend, list):
        for item in reversed(trend):
            point = _trend_point(item)
            if point:
                return point
    return {}


def _trend_first_point(payload: Any) -> dict[str, Any]:
    trend = _deep_find(payload, ("trend",))
    if isinstance(trend, list):
        for item in trend:
            point = _trend_point(item)
            if point:
                return point
    return {}


def _market_snapshot(payload: Any) -> dict[str, Any]:
    """Extract the quote snapshot that trend-shaped d1 responses actually carry."""

    point = _trend_last_point(payload); first_point = _trend_first_point(payload)
    def direct(names: tuple[str, ...]) -> Any:
        direct = _ci_value(payload, *names) if isinstance(payload, dict) else None
        return direct if direct not in (None, "") else None

    def value(names: tuple[str, ...]) -> Any:
        direct_value = direct(names)
        return direct_value if direct_value not in (None, "") else _deep_find(payload, names)

    price = direct(("price", "last", "lastPx", "last_px", "newPrice", "curPrice", "close"))
    if _number(price) is None:
        price = point.get("price")
    if _number(price) is None:
        price = _deep_find(payload, ("price", "last", "lastPx", "last_px", "newPrice", "curPrice", "close"))
    preclose = value(("preclose_px", "preclose", "preclosePrice", "pre_price"))
    change = value(("change_pct", "changePercent", "increase_rate", "pxChangeRate", "rate"))
    if change in (None, ""):
        current_number = _number(price)
        preclose_number = _number(preclose)
        if current_number is not None and preclose_number not in (None, 0):
            change = f"{(current_number - preclose_number) / preclose_number * 100:.4f}%"
    return {
        "price": price,
        "change": change,
        "open": value(("open", "openPrice")) or first_point.get("price"),
        "high": value(("high", "highPrice", "hprice")),
        "low": value(("low", "lowPrice", "lprice")),
        "preclose": preclose,
        "code": value(("StockID", "stockid", "code", "symbol")),
        "name": value(("name", "prodName", "prod_name", "stock_name")),
    }


def _limit_pool_records(payload: Any) -> list[dict[str, Any]]:
    """Flatten limit-pool groups so the table contains stocks, not opaque groups."""

    groups = _deep_find(payload, ("list",))
    if not isinstance(groups, list):
        return []
    rows: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_code = _ci_value(group, "ZSCode", "plate_code")
        group_name = _ci_value(group, "ZSName", "plate_name")
        group_reason = _ci_value(group, "TCExplain", "reason")
        stocks = _ci_value(group, "StockList", "stocklist")
        if not isinstance(stocks, list):
            stocks = []
        for item in stocks:
            if isinstance(item, dict):
                raw = dict(item)
            elif isinstance(item, (list, tuple)):
                raw = {
                    field: item[index]
                    for index, field in enumerate(LIMIT_ROW_FIELDS)
                    if field and index < len(item)
                }
            else:
                continue
            raw["plate_code"] = group_code
            raw["plate_name"] = group_name
            raw["reason"] = _ci_value(raw, "concept", "limit_text", "reason") or group_reason
            rows.append(_normalize_row(raw))
        if not stocks:
            rows.append(_normalize_row({
                "plate_code": group_code,
                "plate_name": group_name,
                "reason": group_reason,
                "count": _ci_value(group, "num", "count"),
            }))
    return rows


def _topic_news_records(payload: Any) -> list[dict[str, Any]]:
    listing = _deep_find(payload, ("List", "list"))
    if not isinstance(listing, dict):
        return []
    rows: list[dict[str, Any]] = []
    for stock_code, items in listing.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                rows.append(_normalize_row({
                    "stock_code": stock_code,
                    "news_id": _ci_value(item, "ID", "id"),
                    "title": _ci_value(item, "Name", "name", "title"),
                }))
    return rows


def _document_records(payload: Any) -> list[dict[str, Any]]:
    listing = _deep_find(payload, ("List", "list"))
    if not isinstance(listing, list) or not any(isinstance(item, str) for item in listing):
        return []
    rows: list[dict[str, Any]] = []
    for item in listing:
        if not isinstance(item, str):
            continue
        prefix = re.split(r"https?://", item, maxsplit=1, flags=re.IGNORECASE)[0].rstrip("_")
        parts = prefix.split("_")
        row: dict[str, Any] = {}
        if parts:
            row["id"] = parts[0]
        if len(parts) > 1:
            row["time"] = parts[1]
        if len(parts) > 2:
            row["title"] = "_".join(parts[2:-1] if len(parts) > 3 else parts[2:])
        rows.append(_normalize_row(row or {"title": "资料记录"}))
    return rows


def _records_for_key(key: str, payload: Any) -> list[dict[str, Any]]:
    if key in {"limit_pool", "limit_history"}:
        rows = _limit_pool_records(payload)
        if rows:
            return rows
    if key == "topic_news":
        rows = _topic_news_records(payload)
        if rows:
            return rows
    fields = POSITIONAL_FIELDS.get(key)
    if fields:
        items = _deep_find(payload, ("List", "list"))
        rows = _positioned_rows(items, fields)
        if rows:
            return rows
    if key in {"company_notice", "reports"}:
        rows = _document_records(payload)
        if rows:
            return rows
    return _find_records(payload)


def _field_label(key: str, index: int = 0) -> str:
    lowered = key.lower()
    if key == "_value":
        return "数据"
    if key.startswith("_field_"):
        return f"字段 {key.rsplit('_', 1)[-1]}"
    if lowered in FIELD_LABELS:
        return FIELD_LABELS[lowered]
    if any("\u4e00" <= char <= "\u9fff" for char in key):
        return _clip(key, 14)
    return f"字段 {index + 1}"


def _row_key(rows: list[dict[str, Any]], aliases: Iterable[str]) -> str | None:
    keys = {str(key).lower(): str(key) for row in rows for key in row}
    for alias in aliases:
        if alias.lower() in keys:
            return keys[alias.lower()]
    return None


def _row_value(row: dict[str, Any], aliases: Iterable[str], default: Any = "—") -> Any:
    value = _ci_value(row, *tuple(aliases), default=None)
    return default if value in (None, "") else value


def _date_label(row: dict[str, Any], index: int) -> str:
    value = _row_value(row, DATE_KEYS, default=None)
    if value not in (None, "", "—"):
        text = str(value)
        return text[5:10] if len(text) >= 10 and text[4] == "-" else _clip(text, 10)
    return str(index + 1)


def _series_for_rows(rows: list[dict[str, Any]]) -> tuple[list[str], list[tuple[str, str, list[float | None]]]]:
    """从趋势列表中选取业务字段，用于通用趋势图。"""

    if len(rows) < 2:
        return [], []
    labels = [_date_label(row, index) for index, row in enumerate(rows)]
    hints: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("ztjs", "up_limit", "count_up_limit"), "涨停家数", RED),
        (("df_num", "dfnum", "down_limit", "count_down_limit"), "跌停家数", GREEN),
        (("lbgd", "height"), "连板高度", GOLD),
        (("strong", "emotion", "score"), "市场强度", PURPLE),
        (("close", "closeprice", "lastpx", "last_px", "price", "y"), "价格", BLUE),
        (("pxchangerate", "px_change_rate", "change_pct", "changepercent", "rate", "increase_rate"), "涨跌幅", ORANGE),
    )
    series: list[tuple[str, str, list[float | None]]] = []
    used: set[str] = set()
    for aliases, label, color in hints:
        key = _row_key(rows, aliases)
        if not key or key in used:
            continue
        values = [_number(row.get(key)) for row in rows]
        if sum(value is not None for value in values) >= 2:
            series.append((label, color, values))
            used.add(key)
        if len(series) >= 3:
            break
    if not series:
        ignored = DATE_KEYS | {"code", "stockid", "symbol", "name", "_value"}
        for key in {key for row in rows for key in row}:
            if key.lower() in ignored:
                continue
            values = [_number(row.get(key)) for row in rows]
            if sum(value is not None for value in values) >= 2:
                series.append((_field_label(key, len(series)), (BLUE, PURPLE)[len(series) % 2], values))
            if len(series) >= 2:
                break
    return labels, series


def _summary_message(payload: Any) -> str:
    value = _deep_find(payload, ("tip", "message", "msg", "description", "content"))
    if isinstance(value, str) and value.strip():
        return _safe_text(value, 150)
    return "数据已按业务字段整理；没有可展示的摘要时，明细区仍可查看返回记录。"


class D1Client:
    """后台 HTTP 客户端；只把本地 d1 请求结果送回 Tk 主线程。"""

    def __init__(self, events: queue.Queue[tuple[int, str, dict[str, Any]]], timeout: float = 18.0) -> None:
        self.events = events
        self.timeout = timeout

    def request(self, base_url: str, preset: QueryPreset, stock: str, day: str, generation: int = 0) -> None:
        def worker() -> None:
            started = time.perf_counter()
            try:
                url = base_url.rstrip("/") + preset.path
                form = preset.form_factory(stock, day)
                request = Request(
                    url,
                    data=urlencode(form).encode("utf-8"),
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                    payload = None if not raw.strip() else json.loads(raw)
                    result = {"ok": True, "payload": payload, "elapsed": time.perf_counter() - started, "status": response.status}
            except HTTPError as exc:
                result = {"ok": False, "error": f"本地服务返回状态 {exc.code}", "elapsed": time.perf_counter() - started}
            except (URLError, TimeoutError, OSError):
                result = {"ok": False, "error": "无法连接本地 d1 服务，请确认地址和服务状态", "elapsed": time.perf_counter() - started}
            except (ValueError, UnicodeError):
                result = {"ok": False, "error": "服务返回内容暂时无法整理，请稍后重试", "elapsed": time.perf_counter() - started}
            self.events.put((generation, preset.key, result))

        threading.Thread(target=worker, name=f"d1-query-{preset.key}", daemon=True).start()


class ScrollPage(tk.Frame):
    """带窄滚动条的业务页，窗口缩小时仍能访问下面的模块。"""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=BG)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="D1.Vertical.TScrollbar")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._fit_width)
        self.canvas.bind("<Enter>", lambda _event: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _event: self.canvas.unbind_all("<MouseWheel>"))

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class D1Gui:
    NAV = ("home", "quotes", "limits", "topics", "replay", "stock", "news", "capabilities")
    NAV_LABELS = {
        "home": "首页", "quotes": "行情", "limits": "涨停", "topics": "题材",
        "replay": "复盘", "stock": "个股", "news": "资讯", "capabilities": "能力中心",
    }

    def __init__(self, root: tk.Tk, base_url: str) -> None:
        self.root = root
        self.root.title("达塔接口 · d1 市场数据工作台")
        self.root.geometry("1480x920")
        self.root.minsize(1100, 680)
        self.root.configure(bg=BG)
        self.root.grid_rowconfigure(3, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        self.base_url_var = tk.StringVar(value=base_url)
        self.stock_var = tk.StringVar(value="SH600519")
        self.date_var = tk.StringVar(value=_default_query_day().isoformat())
        self.status_var = tk.StringVar(value="准备就绪")
        self.updated_var = tk.StringVar(value="—")
        self.active_page = "home"
        self.privacy_mode = False
        self.active_capability: tuple[str, str, str] | None = None
        self.page_frames: dict[str, ScrollPage] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.generation = 0
        self.pending: set[str] = set()
        self.loaded_pages: set[str] = set()
        self.events: queue.Queue[tuple[int, str, dict[str, Any]]] = queue.Queue()
        self.client = D1Client(self.events)

        self.index_cards: dict[str, list[dict[str, Any]]] = {}
        self.metric_vars: dict[str, tk.StringVar] = {}
        self.tables: dict[str, ttk.Treeview] = {}
        self.canvases: dict[str, tk.Canvas] = {}
        self.preview_text: tk.Text | None = None
        self.capability_tree: ttk.Treeview | None = None
        self.capability_title_var = tk.StringVar(value="选择一项业务能力")
        self.capability_desc_var = tk.StringVar(value=f"d1 将 {len(CAPABILITY_ROWS)} 项业务能力按市场、个股、资讯和工具重新整理。")
        self.capability_status_var = tk.StringVar(value="尚未发起查询")
        self.query_button: tk.Button | None = None
        self.stock_name_var = tk.StringVar(value="等待行情")
        self.stock_price_var = tk.StringVar(value="—")
        self.stock_change_var = tk.StringVar(value="—")
        self.stock_code_var = tk.StringVar(value="SH600519")
        self.stock_metrics: dict[str, tk.StringVar] = {}

        self._build_style()
        self._build_header()
        self._build_pages()
        self._show_page("home", refresh=False)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.bind("<Return>", lambda _event: self._search_stock())
        self.root.after(80, self._poll_events)
        self.root.after(140, lambda: self.refresh_page("home"))

    # ── 基础控件 ─────────────────────────────────────────────────────────

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("D1.Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT_SOFT, rowheight=27, borderwidth=0, relief="flat", font=FONT_SMALL)
        style.configure("D1.Treeview.Heading", background="#f5f6f8", foreground=TEXT_SOFT, borderwidth=0, relief="flat", padding=(7, 5), font=FONT_BOLD)
        style.map("D1.Treeview", background=[("selected", ORANGE_SOFT)], foreground=[("selected", ORANGE_DARK)])
        style.configure("D1.Vertical.TScrollbar", background="#e1e4e8", troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)
        style.configure("D1.Horizontal.TScrollbar", background="#e1e4e8", troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)

    @staticmethod
    def _card(parent: tk.Widget, title: str, accent: str = ORANGE, subtitle: str = "") -> tk.Frame:
        frame = tk.Frame(parent, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, bd=0)
        header = tk.Frame(frame, bg=SURFACE, height=35)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Frame(header, bg=accent, width=3).pack(side="left", fill="y")
        tk.Label(header, text=title, bg=SURFACE, fg=TEXT, font=FONT_BOLD, anchor="w").pack(side="left", padx=(9, 2))
        if subtitle:
            tk.Label(header, text=subtitle, bg=SURFACE, fg=MUTED, font=FONT_TINY, anchor="e").pack(side="right", padx=9)
        return frame

    def _build_header(self) -> None:
        top = tk.Frame(self.root, bg=ORANGE, height=62)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        brand = tk.Frame(top, bg=ORANGE)
        brand.pack(side="left", padx=22)
        tk.Label(brand, text="达塔接口", bg=ORANGE, fg=SURFACE, font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        tk.Label(brand, text="d1", bg=SURFACE, fg=ORANGE_DARK, font=("Segoe UI", 15, "bold"), padx=7, pady=1).pack(side="left", padx=(10, 10))
        tk.Label(brand, text="市场数据工作台", bg=ORANGE, fg=SURFACE, font=("Microsoft YaHei UI", 13)).pack(side="left")

        search = tk.Frame(top, bg=ORANGE)
        search.pack(side="right", padx=18)
        tk.Label(search, text="标的", bg=ORANGE, fg="#ffe3d5", font=FONT_SMALL).pack(side="left", padx=(0, 5))
        self.stock_entry = tk.Entry(search, textvariable=self.stock_var, width=13, relief="flat", bg=SURFACE, fg=TEXT, insertbackground=TEXT, font=FONT_MONO, justify="center")
        self.stock_entry.pack(side="left", ipady=5, padx=(0, 5))
        self.stock_entry.bind("<Return>", lambda _event: self._search_stock())
        tk.Button(search, text="查个股", command=self._search_stock, bg="#fff6f1", fg=ORANGE_DARK, activebackground=SURFACE, relief="flat", bd=0, padx=11, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="left")

        nav = tk.Frame(self.root, bg=SURFACE, height=43, highlightbackground=LINE, highlightthickness=1)
        nav.grid(row=1, column=0, sticky="ew")
        nav.grid_propagate(False)
        for key in self.NAV:
            button = tk.Button(nav, text=self.NAV_LABELS[key], command=lambda value=key: self._show_page(value), bg=SURFACE, fg=TEXT_SOFT, activebackground=SURFACE, activeforeground=ORANGE, relief="flat", bd=0, padx=18, pady=8, font=FONT_BOLD, cursor="hand2")
            button.pack(side="left", padx=(10 if key == "home" else 0, 0))
            self.nav_buttons[key] = button
        tk.Label(nav, text="d1 业务视图 · 只读", bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(side="right", padx=18)

        toolbar = tk.Frame(self.root, bg=SURFACE, height=47, highlightbackground=LINE, highlightthickness=1)
        toolbar.grid(row=2, column=0, sticky="ew")
        toolbar.grid_propagate(False)
        tk.Label(toolbar, text="服务地址", bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(20, 6), pady=9)
        tk.Entry(toolbar, textvariable=self.base_url_var, width=29, relief="flat", bg="#f5f6f8", fg=TEXT_SOFT, insertbackground=TEXT, highlightbackground=LINE, highlightthickness=1, font=FONT_MONO).pack(side="left", ipady=4, pady=7, padx=(0, 14))
        tk.Label(toolbar, text="交易日", bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(0, 6))
        tk.Entry(toolbar, textvariable=self.date_var, width=12, relief="flat", bg="#f5f6f8", fg=TEXT_SOFT, insertbackground=TEXT, highlightbackground=LINE, highlightthickness=1, font=FONT_MONO).pack(side="left", ipady=4, pady=7, padx=(0, 14))
        self.query_button = tk.Button(toolbar, text="刷新当前页", command=self.refresh_current, bg=ORANGE, fg=SURFACE, activebackground=ORANGE_DARK, relief="flat", bd=0, padx=13, pady=5, font=FONT_BOLD, cursor="hand2")
        self.query_button.pack(side="left", padx=(0, 6))
        tk.Button(toolbar, text="清空视图", command=self.clear_current, bg="#f5f6f8", fg=TEXT_SOFT, activebackground=ORANGE_SOFT, relief="flat", bd=0, padx=11, pady=5, font=FONT_SMALL, cursor="hand2").pack(side="left")
        self.privacy_button = tk.Button(toolbar, text="隐藏中文名", command=self._toggle_privacy, bg="#fff6f1", fg=ORANGE_DARK, activebackground=ORANGE_SOFT, relief="flat", bd=0, padx=11, pady=5, font=FONT_SMALL, cursor="hand2")
        self.privacy_button.pack(side="left", padx=(7, 0))
        tk.Label(toolbar, textvariable=self.status_var, bg=SURFACE, fg=ORANGE_DARK, font=FONT_SMALL).pack(side="right", padx=(8, 8))
        tk.Label(toolbar, text="更新", bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(side="right", padx=(8, 2))
        tk.Label(toolbar, textvariable=self.updated_var, bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(side="right", padx=(0, 20))

    def _build_pages(self) -> None:
        host = tk.Frame(self.root, bg=BG)
        host.grid(row=3, column=0, sticky="nsew", padx=10, pady=(8, 0))
        host.grid_rowconfigure(0, weight=1)
        host.grid_columnconfigure(0, weight=1)
        self.page_host = host
        builders = {"home": self._build_home, "quotes": self._build_quotes, "limits": self._build_limits, "topics": self._build_topics, "replay": self._build_replay, "stock": self._build_stock, "news": self._build_news, "capabilities": self._build_capabilities}
        for key in self.NAV:
            page = ScrollPage(host)
            page.grid(row=0, column=0, sticky="nsew")
            page.inner.grid_columnconfigure(0, weight=1)
            builders[key](page.inner)
            self.page_frames[key] = page

    def _table(self, parent: tk.Widget, key: str, *, height: int = 9) -> ttk.Treeview:
        host = tk.Frame(parent, bg=SURFACE)
        host.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        host.grid_rowconfigure(0, weight=1)
        host.grid_columnconfigure(0, weight=1)
        tree = ttk.Treeview(host, show="headings", style="D1.Treeview", selectmode="browse", height=height)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(host, orient="vertical", command=tree.yview, style="D1.Vertical.TScrollbar")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(host, orient="horizontal", command=tree.xview, style="D1.Horizontal.TScrollbar")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.tag_configure("even", background=SURFACE)
        tree.tag_configure("odd", background="#fbfbfc")
        self.tables[key] = tree
        return tree

    def _set_table(self, tree: ttk.Treeview, rows: list[dict[str, Any]], columns: list[tuple[tuple[str, ...], str, int]] | None = None, limit: int = 300) -> None:
        tree.delete(*tree.get_children())
        if not rows:
            tree.configure(columns=("status",))
            tree.heading("status", text="状态", anchor="w")
            tree.column("status", width=180, minwidth=120, stretch=False, anchor="w")
            tree.insert("", "end", values=("暂无数据",), tags=("even",))
            return
        if columns is None:
            keys: list[str] = []
            for row in rows:
                for key in row:
                    if (key.startswith("_") and key != "_value") or key.lower() in BLOCKED_VALUE_KEYS:
                        continue
                    if key not in keys:
                        keys.append(key)
            columns = [((key,), _field_label(key, index), 116) for index, key in enumerate(keys[:12])]
        actual_columns: list[tuple[str, str, int]] = []
        for aliases, title, width in columns:
            key = _row_key(rows, aliases)
            if key:
                actual_columns.append((key, title, width))
        if not actual_columns:
            # Positional responses are still real data even when a particular
            # endpoint has no named schema. Keep those values visible instead
            # of replacing the whole block with a misleading empty state.
            fallback_keys: list[str] = []
            for row in rows:
                for key in row:
                    if key.lower() in BLOCKED_VALUE_KEYS or key in fallback_keys:
                        continue
                    if key.startswith("_") and key not in {"_value"} and not key.startswith("_field_"):
                        continue
                    fallback_keys.append(key)
            if fallback_keys:
                actual_columns = [
                    (key, _field_label(key, index), 116)
                    for index, key in enumerate(fallback_keys[:12])
                ]
            else:
                tree.configure(columns=("status",))
                tree.heading("status", text="状态", anchor="w")
                tree.column("status", width=180, minwidth=120, stretch=False, anchor="w")
                tree.insert("", "end", values=("暂无可展示字段",), tags=("even",))
                return
        ids = [f"col_{index}" for index in range(len(actual_columns))]
        tree.configure(columns=ids)
        for identifier, (_key, title, width) in zip(ids, actual_columns):
            tree.heading(identifier, text=title, anchor="w")
            tree.column(identifier, width=width, minwidth=70, stretch=False, anchor="w")
        for index, row in enumerate(rows[:limit]):
            values = []
            for key, _title, _width in actual_columns:
                value = _safe_text(_row_value(row, (key,), default="—"), 110)
                if self.privacy_mode and is_name_field(key):
                    value = display_name(value, True)
                values.append(value)
            tree.insert("", "end", values=values, tags=("even" if index % 2 == 0 else "odd",))

    def _metric_card(self, parent: tk.Widget, key: str, title: str, accent: str, *, width: int = 120) -> tk.Frame:
        frame = tk.Frame(parent, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, width=width, height=72)
        frame.pack_propagate(False)
        tk.Frame(frame, bg=accent, height=3).pack(fill="x")
        tk.Label(frame, text=title, bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=11, pady=(7, 0))
        variable = tk.StringVar(value="—")
        self.metric_vars[key] = variable
        tk.Label(frame, textvariable=variable, bg=SURFACE, fg=TEXT, font=FONT_NUMBER, anchor="w").pack(anchor="w", padx=11, pady=(0, 5))
        return frame

    # ── 首页 ─────────────────────────────────────────────────────────────

    def _build_index_strip(self, parent: tk.Widget) -> tk.Frame:
        strip = tk.Frame(parent, bg=BG)
        definitions = (("index_sh", "上证指数", "SH000001"), ("index_sz", "深证成指", "SZ399001"), ("index_cy", "创业板指", "SZ399006"), ("index_bj", "北证50", "BJ899050"))
        for index, (key, name, code) in enumerate(definitions):
            card = tk.Frame(strip, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=83)
            card.pack(side="left", fill="x", expand=True, padx=(0 if index == 0 else 7, 0))
            card.pack_propagate(False)
            top = tk.Frame(card, bg=SURFACE)
            top.pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(top, text=name, bg=SURFACE, fg=TEXT, font=FONT_BOLD).pack(side="left")
            tk.Label(top, text=code, bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(side="right")
            values: dict[str, Any] = {"price": tk.StringVar(value="—"), "change": tk.StringVar(value="—")}
            body = tk.Frame(card, bg=SURFACE)
            body.pack(fill="x", padx=12)
            tk.Label(body, textvariable=values["price"], bg=SURFACE, fg=RED, font=("Segoe UI", 16, "bold")).pack(side="left")
            change_label = tk.Label(body, textvariable=values["change"], bg=SURFACE, fg=RED, font=FONT_BOLD)
            change_label.pack(side="left", padx=(12, 0))
            values["change_label"] = change_label
            self.index_cards.setdefault(key, []).append(values)
        return strip

    def _build_home(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=4); page.grid_columnconfigure(1, weight=3); page.grid_columnconfigure(2, weight=3)
        page.grid_rowconfigure(2, weight=2, minsize=220); page.grid_rowconfigure(3, weight=2, minsize=220)
        strip = self._build_index_strip(page); strip.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        left = self._card(page, "市场温度", ORANGE, "市场情绪 · 涨跌家数 · 涨跌停")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8))
        mood = tk.Frame(left, bg=SURFACE); mood.pack(fill="x", padx=12, pady=(4, 4))
        self.home_mood_label = tk.Label(mood, text="等待数据", bg=SURFACE, fg=ORANGE_DARK, font=("Microsoft YaHei UI", 22, "bold"), anchor="w"); self.home_mood_label.pack(side="left")
        self.home_mood_tip = tk.Label(mood, text="—", bg=SURFACE, fg=MUTED, font=FONT_SMALL, anchor="w", wraplength=180, justify="left"); self.home_mood_tip.pack(side="left", padx=(13, 0))
        breadth = tk.Frame(left, bg=SURFACE); breadth.pack(fill="x", padx=12, pady=(3, 10))
        self.home_breadth_vars = {key: tk.StringVar(value="—") for key in ("up", "flat", "down", "limit_up", "limit_down")}
        for key, title, color in (("up", "上涨", RED), ("flat", "平盘", MUTED), ("down", "下跌", GREEN), ("limit_up", "涨停", RED), ("limit_down", "跌停", GREEN)):
            cell = tk.Frame(breadth, bg=SURFACE); cell.pack(side="left", fill="x", expand=True)
            tk.Label(cell, text=title, bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(); tk.Label(cell, textvariable=self.home_breadth_vars[key], bg=SURFACE, fg=color, font=FONT_BOLD).pack()
        middle = self._card(page, "涨跌分布", BLUE, "盘面结构"); middle.grid(row=1, column=1, sticky="nsew", padx=(0, 7), pady=(0, 8))
        self.canvases["home_breadth"] = tk.Canvas(middle, bg=SURFACE, highlightthickness=0, height=100); self.canvases["home_breadth"].pack(fill="both", expand=True, padx=7, pady=(0, 7)); self.canvases["home_breadth"].bind("<Configure>", lambda _event: self._draw_breadth("home_breadth"))
        hot = self._card(page, "市场主线", PURPLE, "热点与板块"); hot.grid(row=1, column=2, sticky="nsew", pady=(0, 8))
        self.home_hot_text = tk.Text(hot, width=24, height=5, bg=SURFACE, fg=TEXT_SOFT, relief="flat", bd=0, font=FONT, wrap="word"); self.home_hot_text.pack(fill="both", expand=True, padx=11, pady=(0, 8)); self.home_hot_text.insert("1.0", "等待题材与板块数据\n刷新后在这里显示市场主线。"); self.home_hot_text.configure(state="disabled")
        trend = self._card(page, "涨跌停趋势", RED, "历史 100 个交易日"); trend.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=(0, 7), pady=(0, 8))
        self.canvases["home_trend"] = tk.Canvas(trend, bg=SURFACE, highlightthickness=0, height=220); self.canvases["home_trend"].pack(fill="both", expand=True, padx=7, pady=(0, 7)); self.canvases["home_trend"].bind("<Configure>", lambda _event: self._draw_trend("home_trend", "market_trend"))
        radar = self._card(page, "市场异动", ORANGE, "按时间整理"); radar.grid(row=2, column=2, sticky="nsew", pady=(0, 8)); self._table(radar, "home_radar", height=7)
        rank = self._card(page, "权重表现", TEAL, "市场排行"); rank.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=(0, 7), pady=(0, 8)); self._table(rank, "home_rank", height=7)
        news = self._card(page, "资讯快讯", GOLD, "最新业务消息"); news.grid(row=3, column=2, sticky="nsew", pady=(0, 8)); self._table(news, "home_news", height=7)

    # ── 行情 ─────────────────────────────────────────────────────────────

    def _build_quotes(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=3); page.grid_columnconfigure(1, weight=2); page.grid_rowconfigure(3, weight=2, minsize=255); page.grid_rowconfigure(4, weight=2, minsize=235)
        strip = self._build_index_strip(page); strip.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        filter_bar = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=38); filter_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8)); filter_bar.grid_propagate(False)
        for index, label in enumerate(("A股", "全球", "板块", "指数", "资金")):
            tk.Button(filter_bar, text=label, command=self.refresh_current, bg=ORANGE_SOFT if index == 0 else SURFACE, fg=ORANGE_DARK if index == 0 else TEXT_SOFT, relief="flat", bd=0, padx=14, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="left", padx=(8 if index == 0 else 0, 0), pady=4)
        tk.Label(filter_bar, text="点击表格行可继续用当前标的查询", bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(side="right", padx=12)
        stats = tk.Frame(page, bg=BG); stats.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for index, (key, title, accent) in enumerate((("quote_up", "上涨家数", RED), ("quote_down", "下跌家数", GREEN), ("quote_limit_up", "涨停家数", RED), ("quote_limit_down", "跌停家数", GREEN), ("quote_amount", "成交额", BLUE))):
            self._metric_card(stats, key, title, accent).pack(side="left", fill="x", expand=True, padx=(0 if index == 0 else 7, 0))
        rank = self._card(page, "实时排行", ORANGE, "20 条"); rank.grid(row=3, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self._table(rank, "quotes_rank", height=9)
        sector = self._card(page, "板块强弱", PURPLE, "按涨跌幅"); sector.grid(row=3, column=1, sticky="nsew", pady=(0, 8)); self._table(sector, "quotes_sector", height=9)
        chart = self._card(page, "市场趋势", BLUE, "返回数据自动绘图"); chart.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(0, 8)); self.canvases["quotes_trend"] = tk.Canvas(chart, bg=SURFACE, highlightthickness=0, height=200); self.canvases["quotes_trend"].pack(fill="both", expand=True, padx=7, pady=(0, 7)); self.canvases["quotes_trend"].bind("<Configure>", lambda _event: self._draw_trend("quotes_trend", "market_trend"))

    # ── 涨停 ─────────────────────────────────────────────────────────────

    def _build_limits(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=3); page.grid_columnconfigure(1, weight=2); page.grid_rowconfigure(2, weight=2, minsize=255); page.grid_rowconfigure(3, weight=2, minsize=230)
        title = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=50); title.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)); title.grid_propagate(False)
        tk.Label(title, text="涨停复盘", bg=SURFACE, fg=TEXT, font=FONT_TITLE).pack(side="left", padx=14, pady=8); tk.Label(title, text="涨停池 · 历史复盘 · 封板结构", bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=8); tk.Button(title, text="刷新涨停数据", command=self.refresh_current, bg=ORANGE_SOFT, fg=ORANGE_DARK, relief="flat", bd=0, padx=11, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="right", padx=12, pady=7)
        stats = tk.Frame(page, bg=BG); stats.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for index, (key, title_text, accent) in enumerate((("limit_up", "涨停", RED), ("limit_down", "跌停", GREEN), ("limit_natural", "自然涨停", ORANGE), ("limit_broken", "破板", GOLD), ("limit_blast", "炸板", PURPLE), ("limit_rate", "破板率", BLUE))):
            self._metric_card(stats, key, title_text, accent).pack(side="left", fill="x", expand=True, padx=(0 if index == 0 else 6, 0))
        trend = self._card(page, "涨跌停走势", RED, "红涨绿跌"); trend.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self.canvases["limits_trend"] = tk.Canvas(trend, bg=SURFACE, highlightthickness=0, height=220); self.canvases["limits_trend"].pack(fill="both", expand=True, padx=7, pady=(0, 7)); self.canvases["limits_trend"].bind("<Configure>", lambda _event: self._draw_trend("limits_trend", "market_trend"))
        pool = self._card(page, "涨停池", ORANGE, "点击标的可切换个股"); pool.grid(row=2, column=1, sticky="nsew", pady=(0, 8)); tree = self._table(pool, "limits_pool", height=8); tree.bind("<<TreeviewSelect>>", self._select_code_from_tree)
        detail = self._card(page, "历史明细", BLUE, "指定交易日"); detail.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 8)); self._table(detail, "limits_detail", height=8)

    # ── 题材 ─────────────────────────────────────────────────────────────

    def _build_topics(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=3); page.grid_columnconfigure(1, weight=2); page.grid_rowconfigure(1, weight=2, minsize=260); page.grid_rowconfigure(2, weight=2, minsize=245)
        head = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=53); head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)); head.grid_propagate(False)
        tk.Label(head, text="题材板块", bg=SURFACE, fg=TEXT, font=FONT_TITLE).pack(side="left", padx=14, pady=9); tk.Label(head, text="热点主线 · 异动板块 · 题材点位", bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=8); tk.Button(head, text="刷新题材", command=self.refresh_current, bg=ORANGE_SOFT, fg=ORANGE_DARK, relief="flat", bd=0, padx=11, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="right", padx=12, pady=8)
        core = self._card(page, "异动板块核心", PURPLE, "日期：当前交易日"); core.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self._table(core, "topics_core", height=9)
        points = self._card(page, "题材点位", ORANGE, "热度与强弱"); points.grid(row=1, column=1, sticky="nsew", pady=(0, 8)); self._table(points, "topics_points", height=9)
        sector = self._card(page, "板块排行", TEAL, "强弱排序"); sector.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self._table(sector, "topics_sector", height=9)
        news = self._card(page, "题材资讯", GOLD, "相关消息"); news.grid(row=2, column=1, sticky="nsew", pady=(0, 8)); self._table(news, "topics_news", height=9)

    # ── 复盘 ─────────────────────────────────────────────────────────────

    def _build_replay(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=3); page.grid_columnconfigure(1, weight=2); page.grid_rowconfigure(2, weight=2, minsize=250); page.grid_rowconfigure(3, weight=2, minsize=240)
        head = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=53); head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)); head.grid_propagate(False)
        tk.Label(head, text="复盘工作台", bg=SURFACE, fg=TEXT, font=FONT_TITLE).pack(side="left", padx=14, pady=9); tk.Label(head, text="输入交易日后刷新，所有区块都使用同一日期", bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=8); tk.Button(head, text="刷新复盘", command=self.refresh_current, bg=ORANGE, fg=SURFACE, relief="flat", bd=0, padx=12, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="right", padx=12, pady=8)
        stats = tk.Frame(page, bg=BG); stats.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for index, (key, title, accent) in enumerate((("replay_strong", "市场强度", PURPLE), ("replay_up", "涨停家数", RED), ("replay_down", "跌停家数", GREEN), ("replay_height", "连板高度", ORANGE), ("replay_tip", "复盘提示", GOLD))):
            self._metric_card(stats, key, title, accent).pack(side="left", fill="x", expand=True, padx=(0 if index == 0 else 6, 0))
        trend = self._card(page, "情绪趋势", PURPLE, "涨停 · 跌停 · 强度"); trend.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self.canvases["replay_trend"] = tk.Canvas(trend, bg=SURFACE, highlightthickness=0, height=220); self.canvases["replay_trend"].pack(fill="both", expand=True, padx=7, pady=(0, 7)); self.canvases["replay_trend"].bind("<Configure>", lambda _event: self._draw_trend("replay_trend", "market_trend"))
        detail = self._card(page, "当日明细", RED, "涨跌停结构"); detail.grid(row=2, column=1, sticky="nsew", pady=(0, 8)); self._table(detail, "replay_detail", height=8)
        emotion = self._card(page, "情绪资金", TEAL, "买卖力度与资金日期"); emotion.grid(row=3, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self._table(emotion, "replay_emotion", height=8)
        radar = self._card(page, "复盘雷达", ORANGE, "异动摘要"); radar.grid(row=3, column=1, sticky="nsew", pady=(0, 8)); self._table(radar, "replay_radar", height=8)

    # ── 个股 ─────────────────────────────────────────────────────────────

    def _build_stock(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=3); page.grid_columnconfigure(1, weight=1); page.grid_rowconfigure(2, weight=2, minsize=300); page.grid_rowconfigure(3, weight=2, minsize=245)
        quote = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=94); quote.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)); quote.grid_propagate(False)
        identity = tk.Frame(quote, bg=SURFACE); identity.pack(side="left", padx=15, pady=11); tk.Label(identity, textvariable=self.stock_name_var, bg=SURFACE, fg=TEXT, font=FONT_TITLE, anchor="w").pack(anchor="w"); tk.Label(identity, textvariable=self.stock_code_var, bg=SURFACE, fg=MUTED, font=FONT_SMALL, anchor="w").pack(anchor="w", pady=(2, 0))
        tk.Label(quote, textvariable=self.stock_price_var, bg=SURFACE, fg=RED, font=("Segoe UI", 25, "bold")).pack(side="left", padx=(15, 0), pady=11); self.stock_change_label = tk.Label(quote, textvariable=self.stock_change_var, bg=SURFACE, fg=RED, font=("Segoe UI", 13, "bold")); self.stock_change_label.pack(side="left", padx=(12, 0), pady=11)
        metrics = tk.Frame(quote, bg=SURFACE); metrics.pack(side="right", fill="y", padx=15, pady=10)
        for key, title in (("open", "今开"), ("high", "最高"), ("low", "最低"), ("amount", "成交额"), ("turnover", "换手"), ("market_value", "市值")):
            cell = tk.Frame(metrics, bg=SURFACE); cell.pack(side="left", padx=8); tk.Label(cell, text=title, bg=SURFACE, fg=MUTED, font=FONT_TINY).pack(); variable = tk.StringVar(value="—"); self.stock_metrics[key] = variable; tk.Label(cell, textvariable=variable, bg=SURFACE, fg=TEXT_SOFT, font=FONT_BOLD).pack(pady=(4, 0))
        mode = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=38); mode.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8)); mode.grid_propagate(False)
        self.stock_mode = tk.StringVar(value="分时")
        self.stock_mode_buttons: dict[str, tk.Button] = {}
        for index, label in enumerate(("分时", "日K", "五档", "资金", "题材", "公告")):
            button = tk.Button(mode, text=label, command=lambda value=label: self._set_stock_mode(value), bg=ORANGE_SOFT if index == 0 else SURFACE, fg=ORANGE_DARK if index == 0 else TEXT_SOFT, relief="flat", bd=0, padx=14, pady=5, font=FONT_BOLD, cursor="hand2")
            button.pack(side="left", padx=(8 if index == 0 else 0, 0), pady=4)
            self.stock_mode_buttons[label] = button
        chart = self._card(page, "个股走势", ORANGE, "日K / 图表数据"); chart.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self.canvases["stock_chart"] = tk.Canvas(chart, bg=SURFACE, highlightthickness=0, height=250); self.canvases["stock_chart"].pack(fill="both", expand=True, padx=7, pady=(0, 7)); self.canvases["stock_chart"].bind("<Configure>", lambda _event: self._draw_stock_chart())
        book = self._card(page, "五档 / 队列", BLUE, "委托摘要"); book.grid(row=2, column=1, sticky="nsew", pady=(0, 8)); self._table(book, "stock_book", height=9)
        detail = self._card(page, "个股业务明细", TEAL, "详情 · 资金 · 资讯"); detail.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 8)); tree = self._table(detail, "stock_detail", height=8); tree.bind("<<TreeviewSelect>>", self._select_code_from_tree)

    # ── 资讯 ─────────────────────────────────────────────────────────────

    def _build_news(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, weight=3); page.grid_columnconfigure(1, weight=2); page.grid_rowconfigure(1, weight=3, minsize=360); page.grid_rowconfigure(2, weight=2, minsize=235)
        head = tk.Frame(page, bg=SURFACE, highlightbackground=LINE, highlightthickness=1, height=53); head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)); head.grid_propagate(False)
        tk.Label(head, text="资讯中心", bg=SURFACE, fg=TEXT, font=FONT_TITLE).pack(side="left", padx=14, pady=9); tk.Label(head, text="快讯 · 专栏 · 题材资讯 · 个股资料", bg=SURFACE, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=8); tk.Button(head, text="刷新资讯", command=self.refresh_current, bg=ORANGE_SOFT, fg=ORANGE_DARK, relief="flat", bd=0, padx=11, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="right", padx=12, pady=8)
        listing = self._card(page, "最新快讯", ORANGE, "按时间排序"); listing.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); tree = self._table(listing, "news_list", height=13); tree.bind("<<TreeviewSelect>>", self._show_news_preview)
        preview = self._card(page, "消息预览", GOLD, "只展示业务摘要"); preview.grid(row=1, column=1, sticky="nsew", pady=(0, 8)); self.preview_text = tk.Text(preview, bg=SURFACE, fg=TEXT_SOFT, relief="flat", bd=0, wrap="word", font=FONT); self.preview_text.pack(fill="both", expand=True, padx=13, pady=(0, 10)); self.preview_text.insert("1.0", "选择左侧资讯后在这里查看摘要。\n\n原始链接、请求细节和内部字段不会直接显示。"); self.preview_text.configure(state="disabled")
        topic = self._card(page, "题材资讯", PURPLE, "关联内容"); topic.grid(row=2, column=0, sticky="nsew", padx=(0, 7), pady=(0, 8)); self._table(topic, "news_topic", height=8)
        company = self._card(page, "个股资料", TEAL, "由顶部标的驱动"); company.grid(row=2, column=1, sticky="nsew", pady=(0, 8)); self._table(company, "news_company", height=8)

    # ── 能力中心 ─────────────────────────────────────────────────────────

    def _build_capabilities(self, page: tk.Frame) -> None:
        page.grid_columnconfigure(0, minsize=245, weight=0); page.grid_columnconfigure(1, weight=1); page.grid_rowconfigure(0, weight=1)
        left = self._card(page, "d1 能力目录", ORANGE, f"{len(CAPABILITY_ROWS)} 项"); left.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        search = tk.Frame(left, bg=SURFACE); search.pack(fill="x", padx=9, pady=(0, 6)); search_var = tk.StringVar(); entry = tk.Entry(search, textvariable=search_var, bg="#f5f6f8", fg=TEXT, relief="flat", highlightbackground=LINE, highlightthickness=1, font=FONT_SMALL); entry.pack(fill="x", ipady=4)
        self.capability_tree = ttk.Treeview(left, show="tree", style="D1.Treeview", selectmode="browse"); self.capability_tree.pack(fill="both", expand=True, padx=7, pady=(0, 8)); self.capability_tree.bind("<<TreeviewSelect>>", self._on_capability_selected); self.capability_tree_data: dict[str, tuple[str, str, str]] = {}; self._fill_capability_tree(""); search_var.trace_add("write", lambda *_args: self._fill_capability_tree(search_var.get()))
        right = tk.Frame(page, bg=BG); right.grid(row=0, column=1, sticky="nsew", pady=(0, 8)); right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(2, weight=1)
        detail = self._card(right, "业务能力", BLUE, "按当前标的 / 日期查询"); detail.grid(row=0, column=0, sticky="ew", pady=(0, 8)); tk.Label(detail, textvariable=self.capability_title_var, bg=SURFACE, fg=TEXT, font=FONT_TITLE, anchor="w").pack(side="left", padx=13, pady=10); tk.Button(detail, text="查询此项", command=self._run_capability, bg=ORANGE, fg=SURFACE, activebackground=ORANGE_DARK, relief="flat", bd=0, padx=12, pady=5, font=FONT_BOLD, cursor="hand2").pack(side="right", padx=12, pady=9); tk.Label(detail, textvariable=self.capability_desc_var, bg=SURFACE, fg=MUTED, font=FONT_SMALL, anchor="w", justify="left").pack(fill="x", padx=13, pady=(0, 10))
        result_head = self._card(right, "业务结果", TEAL, "不展示原始响应"); result_head.grid(row=1, column=0, sticky="ew", pady=(0, 8)); tk.Label(result_head, textvariable=self.capability_status_var, bg=SURFACE, fg=MUTED, font=FONT_SMALL, anchor="w").pack(side="left", padx=13, pady=(0, 9))
        body = self._card(right, "明细列表", GREEN, "字段已转为业务名称"); body.grid(row=2, column=0, sticky="nsew", pady=(0, 8)); self._table(body, "capability_result", height=16)

    def _fill_capability_tree(self, query: str) -> None:
        if self.capability_tree is None:
            return
        self.capability_tree.delete(*self.capability_tree.get_children()); self.capability_tree_data.clear(); query = query.strip().lower(); groups: dict[str, str] = {}
        for group, label, spec_key in CAPABILITY_ROWS:
            if query and query not in group.lower() and query not in label.lower():
                continue
            parent = groups.get(group)
            if parent is None:
                parent = self.capability_tree.insert("", "end", text=group, open=True); groups[group] = parent
            item = self.capability_tree.insert(parent, "end", text=label, values=(spec_key,)); self.capability_tree_data[item] = (group, label, spec_key)

    # ── 页面切换、请求和事件 ─────────────────────────────────────────────

    def _show_page(self, page: str, refresh: bool = True) -> None:
        if page not in self.page_frames:
            return
        self.active_page = page; self.page_frames[page].tkraise()
        for key, button in self.nav_buttons.items():
            button.configure(bg=ORANGE_SOFT if key == page else SURFACE, fg=ORANGE_DARK if key == page else TEXT_SOFT)
        if refresh and page not in self.loaded_pages:
            self.refresh_page(page)

    def _validate_inputs(self) -> bool:
        base_url = self.base_url_var.get().strip(); day = self.date_var.get().strip()
        if not re.match(r"^https?://", base_url, re.IGNORECASE):
            self.status_var.set("地址格式不正确"); return False
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            self.status_var.set("日期格式不正确"); return False
        return True

    def _page_queries(self, page: str) -> tuple[str, ...]:
        common = ("index_sh", "index_sz", "index_cy", "index_bj")
        return {"home": common + ("market_mood", "market_trend", "market_detail", "market_capacity", "overview_rank", "market_radar", "topic_core", "sector_rank", "news_list"), "quotes": common + ("market_mood", "market_detail", "market_capacity", "market_trend", "overview_rank", "sector_rank"), "limits": ("market_trend", "market_detail", "limit_pool", "limit_history", "limit_performance"), "topics": ("topic_core", "topic_points", "topic_news", "sector_rank"), "replay": ("market_trend", "market_detail", "emotion_fast", "emotion_flow", "market_radar"), "stock": ("stock_quote", "stock_detail", "stock_chart", "stock_order", "stock_news"), "news": ("news_list", "topic_news", "company_profile", "company_notice"), "capabilities": ()}.get(page, ())

    def refresh_current(self) -> None:
        if self.active_page == "capabilities": self._run_capability()
        else: self.refresh_page(self.active_page)

    def refresh_page(self, page: str) -> None:
        if not self._validate_inputs(): return
        keys = self._page_queries(page)
        if not keys: self.status_var.set("选择左侧能力后查询"); return
        self.generation += 1; generation = self.generation; self.pending = set(keys); self.loaded_pages.add(page)
        if self.query_button is not None: self.query_button.configure(state="disabled", text="加载中…")
        self.status_var.set(f"正在加载 {len(keys)} 个业务区块…"); self.updated_var.set("请求中")
        base_url = self.base_url_var.get().strip(); stock = self.stock_var.get().strip().upper(); day = self.date_var.get().strip()
        for key in keys:
            preset = PRESET_BY_KEY.get(key)
            if preset is not None: self.client.request(base_url, preset, stock, day, generation)

    def _poll_events(self) -> None:
        try:
            while True:
                generation, key, result = self.events.get_nowait()
                if generation != self.generation: continue
                self.pending.discard(key); self.results[key] = result; self._render_result(key, result)
                if not self.pending:
                    if self.query_button is not None: self.query_button.configure(state="normal", text="刷新当前页")
                    current = [self.results.get(item) for item in self._page_queries(self.active_page)]
                    self.status_var.set("已更新" if all(item and item.get("ok") for item in current) else "部分区块需要检查"); self.updated_var.set(time.strftime("%H:%M:%S"))
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    def _render_result(self, key: str, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            if key == "news_list" and self.preview_text is not None: self._set_preview(str(result.get("error", "资讯暂不可用")))
            if self.active_page == "capabilities" and self.active_capability and self.active_capability[2] == key: self.capability_status_var.set(str(result.get("error", "查询失败")))
            return
        payload = result.get("payload")
        if key.startswith("index_"): self._render_index(key, payload)
        business_keys = {"market_mood", "market_detail", "market_trend", "market_capacity", "overview_rank", "market_radar", "news_list", "limit_pool", "limit_history", "limit_performance", "topic_core", "topic_points", "topic_news", "sector_rank", "sector_rank_live", "emotion_fast", "emotion_flow", "capital_detail", "connect_rank", "connect_flow", "stock_quote", "stock_detail", "stock_chart", "stock_kline", "stock_order", "stock_news", "company_profile", "company_notice", "reports", "calendar", "watchlist", "feature_search", "index_overview", "index_kline", "global_kline", "global_index", "hot_money", "institution"}
        if key in business_keys: self._render_business(key, payload)
        if self.active_page == "capabilities" and self.active_capability and self.active_capability[2] == key:
            self.capability_status_var.set(f"已完成 · {_summary_message(payload)}"); self._set_table(self.tables["capability_result"], _records_for_key(key, payload))

    def _render_index(self, key: str, payload: Any) -> None:
        cards = self.index_cards.get(key, []); snapshot = _market_snapshot(payload); change = snapshot["change"]; price = snapshot["price"]
        for card in cards:
            card["price"].set(_safe_text(price)); card["change"].set(_rate_text(change)); label = card.get("change_label")
            if isinstance(label, tk.Label): label.configure(fg=_value_color(change))
        if self.active_page == "capabilities" and self.active_capability and self.active_capability[2] == key: self._set_table(self.tables["capability_result"], _find_records(payload))

    def _render_business(self, key: str, payload: Any) -> None:
        rows = _records_for_key(key, payload)
        if key == "market_mood":
            source = _deep_find(payload, ("list",)); source = source if isinstance(source, dict) else payload if isinstance(payload, dict) else {}
            up = _deep_find(source, ("up", "rise", "countUp", "up_count", "SZJS")); down = _deep_find(source, ("down", "fall", "countDown", "down_count", "XDJS")); limit_up = _deep_find(source, ("ZT", "zt", "up_limit", "ZTJS")); limit_down = _deep_find(source, ("DT", "dt", "down_limit", "DTJS")); balance = _deep_find(source, ("bl", "balance", "breadth"))
            if hasattr(self, "home_mood_label"):
                mood = f"涨跌比 {_safe_text(balance)}" if balance not in (None, "") else "市场情绪"
                tip = f"上涨 {_safe_text(up)} · 下跌 {_safe_text(down)}\n涨停 {_safe_text(limit_up)} · 跌停 {_safe_text(limit_down)}"
                self.home_mood_label.configure(text=mood); self.home_mood_tip.configure(text=tip)
            self._render_breadth(payload)
            for metric_key, value in (("quote_up", up), ("quote_down", down), ("quote_limit_up", limit_up), ("quote_limit_down", limit_down)):
                if metric_key in self.metric_vars and value not in (None, ""):
                    self.metric_vars[metric_key].set(_safe_text(value))
        if key in {"market_detail", "limit_pool", "limit_performance", "limit_history"}: self._render_limit_metrics(payload)
        if key == "market_trend":
            for canvas_key in ("home_trend", "quotes_trend", "limits_trend", "replay_trend"):
                if canvas_key in self.canvases: self._draw_trend(canvas_key, key)
        if key == "market_detail":
            self._render_breadth(payload)
            if "replay_detail" in self.tables: self._set_table(self.tables["replay_detail"], rows, [(("ZT", "zt", "up_limit"), "涨停", 90), (("DT", "dt", "down_limit"), "跌停", 90), (("FYZ", "fyz"), "自然涨停", 100), (("QB", "qb"), "曾跌停", 90), (("PB", "pb"), "破板", 90), (("FXB", "fxb"), "炸板", 90), (("JJZZ", "jjzz"), "竞价涨停", 100)])
            source = _deep_find(payload, ("nums",)); source = source if isinstance(source, dict) else payload if isinstance(payload, dict) else {}
            for metric_key, aliases in (("quote_up", ("up", "rise", "countUp", "up_count", "SZJS")), ("quote_down", ("down", "fall", "countDown", "down_count", "XDJS")), ("quote_limit_up", ("ZT", "zt", "up_limit", "ZTJS")), ("quote_limit_down", ("DT", "dt", "down_limit", "DTJS"))):
                value = _deep_find(source, aliases)
                if metric_key in self.metric_vars and value not in (None, ""): self.metric_vars[metric_key].set(_safe_text(value))
        if key == "market_capacity" and "quote_amount" in self.metric_vars:
            self.metric_vars["quote_amount"].set(_safe_text(_deep_find(payload, ("amount", "turnover", "s_zrtj", "last"))))
        if key == "overview_rank":
            columns = [(("StockID", "stockid", "code", "ID", "plate_code"), "代码", 92), (("Name", "name", "prodName", "plate_name"), "名称", 110), (("CurPrice", "price", "lastPx", "last_px"), "现价", 90), (("ChangePercent", "increase_rate", "pxChangeRate", "rate", "change_pct"), "涨跌幅", 92), (("Turnover", "turnover", "amount"), "成交额", 108)]
            for table_key in ("home_rank", "quotes_rank"):
                if table_key in self.tables: self._set_table(self.tables[table_key], rows, columns)
        if key == "market_radar":
            columns = [(("time", "Time"), "时间", 70), (("stockid", "StockID", "code"), "代码", 82), (("stock_name", "Name", "name"), "名称", 105), (("status", "LBstatus", "type"), "状态", 90), (("zf", "rate", "change"), "涨跌幅", 90), (("content", "content2", "tip"), "异动摘要", 230)]
            for table_key in ("home_radar", "replay_radar"):
                if table_key in self.tables: self._set_table(self.tables[table_key], rows, columns)
        if key == "news_list":
            columns = [(("time", "Time", "date"), "时间", 76), (("title", "Title", "name", "subject"), "标题", 260), (("category", "type", "column"), "分类", 90), (("content", "message", "summary"), "摘要", 260)]
            for table_key in ("home_news", "news_list"):
                if table_key in self.tables: self._set_table(self.tables[table_key], rows, columns)
            if rows and self.preview_text is not None: self._set_preview(_summary_message(payload))
        if key in {"limit_pool", "limit_history", "limit_performance"}:
            columns = [(("StockID", "stockid", "code", "ID", "stock_code"), "代码", 92), (("Name", "name", "prodName", "stock_name"), "名称", 110), (("zf", "change", "rate", "increase_rate", "change_pct"), "涨跌幅", 90), (("ZT", "zt", "state", "status", "limit_text"), "状态", 90), (("reason", "content", "tip", "TCExplain", "concept"), "题材/原因", 220)]
            if key == "limit_pool" and "limits_pool" in self.tables: self._set_table(self.tables["limits_pool"], rows, columns)
            if key == "limit_history" and "limits_detail" in self.tables: self._set_table(self.tables["limits_detail"], rows, columns)
        if key in {"topic_core", "topic_points", "topic_news"}:
            table_key = {"topic_core": "topics_core", "topic_points": "topics_points", "topic_news": "topics_news"}[key]
            if table_key in self.tables: self._set_table(self.tables[table_key], rows)
            if key == "topic_news" and "news_topic" in self.tables: self._set_table(self.tables["news_topic"], rows)
            if key == "topic_core" and hasattr(self, "home_hot_text"):
                lines = []
                for row in rows[:6]:
                    name = _row_value(row, ("name", "Name", "ZSName", "prodName", "plate_name"), default="题材")
                    rate = _row_value(row, ("increase_rate", "ChangePercent", "pxChangeRate", "rate", "zf"), default="—")
                    lines.append(f"{display_name(_safe_text(name, 20), self.privacy_mode)}  {_rate_text(rate) if rate != '—' else '—'}")
                self._set_home_hot("\n".join(lines) if lines else "暂无题材数据\n刷新后在这里显示市场主线。")
        if key in {"sector_rank", "sector_rank_live"}:
            columns = [(("ZSName", "name", "prodName", "plate_name"), "板块", 135), (("increase_rate", "pxChangeRate", "rate", "change", "change_pct"), "涨跌幅", 90), (("ztjs", "up_limit", "count", "stock_count"), "数量", 75), (("content", "leader", "stock_name"), "领涨/说明", 210)]
            for table_key in ("quotes_sector", "topics_sector"):
                if table_key in self.tables: self._set_table(self.tables[table_key], rows, columns)
            if hasattr(self, "home_hot_text") and rows:
                lines = []
                for row in rows[:5]:
                    name = _row_value(row, ("ZSName", "name", "prodName", "plate_name"), default="板块")
                    rate = _row_value(row, ("increase_rate", "pxChangeRate", "rate", "change"), default="—")
                    lines.append(f"{display_name(_safe_text(name, 20), self.privacy_mode)}  {_rate_text(rate) if rate != '—' else '—'}")
                self._set_home_hot("\n".join(lines))
        if key in {"emotion_fast", "emotion_flow", "capital_detail", "connect_rank", "connect_flow"} and "replay_emotion" in self.tables: self._set_table(self.tables["replay_emotion"], rows)
        if key == "stock_quote": self._render_stock_quote(payload)
        if key in {"stock_detail", "stock_chart", "stock_kline", "stock_order", "stock_news"}:
            # The page has one detail table and one order-book table. Do not
            # let a chart payload or an empty news response erase a real
            # detail result that arrived from another request.
            if key == "stock_detail" and "stock_detail" in self.tables:
                useful = any(set(row) - {"tag"} for row in rows)
                tree = self.tables["stock_detail"]
                if useful or not tree.get_children():
                    self._set_table(tree, rows); self.stock_detail_has_useful = useful
            if key == "stock_news" and rows and "stock_detail" in self.tables and not getattr(self, "stock_detail_has_useful", False): self._set_table(self.tables["stock_detail"], rows)
            if key == "stock_order" and "stock_book" in self.tables: self._set_table(self.tables["stock_book"], rows, [(("price", "Price", "px"), "价格", 90), (("volume", "Volume", "vol", "amount"), "数量", 90), (("type", "side", "direction"), "方向", 90), (("status",), "状态", 90)])
            if key in {"stock_chart", "stock_kline"}: self._draw_stock_chart()
        if key in {"company_profile", "company_notice", "reports"} and "news_company" in self.tables:
            # The news page shares one table for profile/notice data. Notices
            # are the useful list view, so a late profile response must not
            # erase them; a profile can still populate an otherwise empty table.
            tree = self.tables["news_company"]
            if rows and (key in {"company_notice", "reports"} or not tree.get_children()): self._set_table(tree, rows)
        if key in {"index_overview", "global_index", "index_kline", "global_kline", "hot_money", "institution", "calendar", "watchlist", "feature_search"} and "capability_result" in self.tables and self.active_page == "capabilities": self._set_table(self.tables["capability_result"], rows)

    def _render_limit_metrics(self, payload: Any) -> None:
        nums = _deep_find(payload, ("nums",)); source = nums if isinstance(nums, dict) else payload
        aliases = {"limit_up": ("ZT", "zt", "up_limit", "countUpLimit"), "limit_down": ("DT", "dt", "down_limit", "countDownLimit"), "limit_natural": ("FYZ", "fyz", "natural"), "limit_broken": ("PB", "pb", "broken"), "limit_blast": ("FXB", "fxb", "blast")}
        for key, names in aliases.items():
            value = _deep_find(source, names)
            if key in self.metric_vars and value not in (None, ""): self.metric_vars[key].set(_safe_text(value))
        up = _number(_deep_find(source, aliases["limit_up"])); broken = _number(_deep_find(source, aliases["limit_broken"])); rate = broken / (up + broken) * 100 if up is not None and broken is not None and up + broken else None
        if rate is None: rate = _number(_deep_find(source, ("ZBL", "break_rate", "broken_rate")))
        if "limit_rate" in self.metric_vars and rate is not None: self.metric_vars["limit_rate"].set(f"{rate:.2f}%")
        for key, names in (("replay_up", aliases["limit_up"]), ("replay_down", aliases["limit_down"]), ("replay_height", ("lbgd", "height")), ("replay_strong", ("strong", "score"))):
            value = _deep_find(payload, names)
            if key in self.metric_vars and value not in (None, ""): self.metric_vars[key].set(_safe_text(value))
        tip = _deep_find(payload, ("tip", "message"))
        if "replay_tip" in self.metric_vars and tip not in (None, ""): self.metric_vars["replay_tip"].set(_safe_text(tip, 28))

    def _render_breadth(self, payload: Any) -> None:
        sources: list[dict[str, Any]] = []
        for name in ("nums", "list"):
            source = _deep_find(payload, (name,))
            if isinstance(source, dict): sources.append(source)
        if isinstance(payload, dict): sources.append(payload)

        def find(names: tuple[str, ...]) -> Any:
            for source in sources:
                value = _deep_find(source, names)
                if value not in (None, ""):
                    return value
            return None

        values = {
            "up": find(("up", "rise", "countUp", "up_count", "SZJS")),
            "flat": find(("flat", "ping", "countFlat", "flat_count", "PJJS", "PSJS")),
            "down": find(("down", "fall", "countDown", "down_count", "XDJS")),
            "limit_up": find(("ZT", "zt", "up_limit", "ZTJS")),
            "limit_down": find(("DT", "dt", "down_limit", "DTJS")),
        }
        if hasattr(self, "home_breadth_vars"):
            for key, value in values.items():
                if value not in (None, ""):
                    self.home_breadth_vars[key].set(_safe_text(value))
            self.home_breadth_data = [_number(self.home_breadth_vars[key].get()) or 0 for key in ("up", "flat", "down")]
            self._draw_breadth("home_breadth")

    def _render_stock_quote(self, payload: Any) -> None:
        snapshot = _market_snapshot(payload)
        code = snapshot["code"] or self.stock_var.get().strip().upper()
        stock_name = _safe_text(snapshot["name"], 30) if snapshot["name"] not in (None, "") else f"标的 {code}"
        self.stock_name_var.set(display_name(stock_name, self.privacy_mode))
        self.stock_code_var.set(_safe_text(code, 18))
        price = snapshot["price"]; change = snapshot["change"]
        self.stock_price_var.set(_safe_text(price)); self.stock_change_var.set(_rate_text(change)); self.stock_change_label.configure(fg=_value_color(change))
        metric_values = {
            "open": snapshot["open"], "high": snapshot["high"], "low": snapshot["low"],
            "amount": _deep_find(payload, ("amount", "turnover", "Turnover")),
            "turnover": _deep_find(payload, ("turnoverRate", "turnover_rate", "TurnoverRatio")),
            "market_value": _deep_find(payload, ("marketValue", "circulation", "Capitalization")),
        }
        for key, value in metric_values.items(): self.stock_metrics[key].set(_safe_text(value))

    # ── 绘图 ─────────────────────────────────────────────────────────────

    def _draw_breadth(self, canvas_key: str) -> None:
        canvas = self.canvases.get(canvas_key)
        if canvas is None: return
        canvas.delete("all"); width, height = max(200, canvas.winfo_width()), max(80, canvas.winfo_height()); values = getattr(self, "home_breadth_data", [])
        if not values or sum(values) <= 0: canvas.create_text(width / 2, height / 2, text="等待市场宽度数据", fill=MUTED, font=FONT_SMALL); return
        labels = (("上涨", RED), ("平盘", MUTED), ("下跌", GREEN)); maximum = max(values + [1]); base = height - 25; slot = max(36, width / max(1, len(values)))
        for index, value in enumerate(values):
            x = slot * (index + 0.5); bar_h = (height - 48) * value / maximum; color = labels[index][1]; canvas.create_rectangle(x - 17, base - bar_h, x + 17, base, fill=color, outline=""); canvas.create_text(x, base - bar_h - 8, text=str(int(value)), fill=color, font=FONT_SMALL); canvas.create_text(x, height - 8, text=labels[index][0], fill=MUTED, font=FONT_TINY)

    def _draw_trend(self, canvas_key: str, data_key: str) -> None:
        canvas = self.canvases.get(canvas_key)
        if canvas is None: return
        canvas.delete("all"); width, height = max(300, canvas.winfo_width()), max(150, canvas.winfo_height()); result = self.results.get(data_key, {}); rows = _find_records(result.get("payload")) if result.get("ok") else []; labels, series = _series_for_rows(rows[-120:])
        if not series: canvas.create_text(width / 2, height / 2, text="查询后在这里显示趋势图", fill=MUTED, font=FONT_SMALL); return
        left, right, top, bottom = 48, 18, 28, 25; plot_width = max(80, width - left - right); plot_height = max(60, height - top - bottom); all_values = [value for _label, _color, values in series for value in values if value is not None]; low, high = min(all_values), max(all_values)
        if math.isclose(low, high): padding = abs(high) * 0.08 or 1; low, high = low - padding, high + padding
        for step in range(5):
            fraction = step / 4; y = top + plot_height * fraction; value = high - (high - low) * fraction; canvas.create_line(left, y, width - right, y, fill=LINE); canvas.create_text(left - 7, y, text=_axis_text(value), anchor="e", fill=MUTED, font=FONT_TINY)
        for index, (label, color, values) in enumerate(series):
            points: list[float] = []
            for point_index, value in enumerate(values):
                if value is None:
                    if len(points) >= 4: canvas.create_line(*points, fill=color, width=2, smooth=True)
                    points = []; continue
                x = left + plot_width * point_index / max(1, len(values) - 1); y = top + plot_height * (high - value) / (high - low); points.extend((x, y))
            if len(points) >= 4: canvas.create_line(*points, fill=color, width=2, smooth=True)
            lx = left + index * 105; canvas.create_rectangle(lx, 8, lx + 9, 17, fill=color, outline=""); canvas.create_text(lx + 14, 12, text=label, anchor="w", fill=TEXT_SOFT, font=FONT_TINY)
        if labels:
            for position in sorted(set((0, len(labels) // 2, len(labels) - 1))):
                x = left + plot_width * position / max(1, len(labels) - 1); canvas.create_text(x, height - 6, text=labels[position], anchor="s", fill=MUTED, font=FONT_TINY)

    def _draw_stock_chart(self) -> None:
        canvas = self.canvases.get("stock_chart")
        if canvas is None: return
        canvas.delete("all"); width, height = max(300, canvas.winfo_width()), max(180, canvas.winfo_height()); result = self.results.get("stock_chart", {}); result = result if result.get("ok") else self.results.get("stock_kline", {}); payload = result.get("payload") if isinstance(result, dict) else None; dates = _deep_find(payload, ("x", "date", "day")); closes = _deep_find(payload, ("y", "close", "closeprice"))
        if not isinstance(dates, list) or not isinstance(closes, list):
            rows = _find_records(payload); dates = [_date_label(row, index) for index, row in enumerate(rows)]; closes = [_number(_row_value(row, ("close", "closePrice", "last", "price"), default=None)) for row in rows]
        values: list[float] = []; labels: list[str] = []
        for index, value in enumerate(closes or []):
            if isinstance(value, (list, tuple)):
                # GetStockChart returns [open, close, high, low] for every x.
                value = value[1] if len(value) > 1 and _number(value[1]) is not None else (value[0] if value else None)
            elif isinstance(value, dict):
                value = _ci_value(value, "close", "closePrice", "last", "price")
            number = _number(value)
            if number is not None: values.append(number); labels.append(_safe_text((dates or [])[index] if index < len(dates or []) else index + 1, 10))
        if len(values) < 2: canvas.create_text(width / 2, height / 2, text="查询后在这里显示个股走势", fill=MUTED, font=FONT_SMALL); return
        left, right, top, bottom = 48, 18, 22, 25; low, high = min(values), max(values)
        if math.isclose(low, high): low, high = low - 1, high + 1
        for step in range(4):
            fraction = step / 3; y = top + (height - top - bottom) * fraction; canvas.create_line(left, y, width - right, y, fill=LINE); canvas.create_text(left - 7, y, text=_axis_text(high - (high - low) * fraction), anchor="e", fill=MUTED, font=FONT_TINY)
        points: list[float] = []; view = values[-240:]
        for index, value in enumerate(view): points.extend((left + (width - left - right) * index / max(1, len(view) - 1), top + (height - top - bottom) * (high - value) / (high - low)))
        canvas.create_line(*points, fill=ORANGE, width=2, smooth=True); canvas.create_text(width - right, 8, text=f"最新 {_safe_text(values[-1])}", anchor="ne", fill=ORANGE_DARK, font=FONT_SMALL)
        if labels: canvas.create_text(left, height - 7, text=labels[0], anchor="sw", fill=MUTED, font=FONT_TINY); canvas.create_text(width - right, height - 7, text=labels[-1], anchor="se", fill=MUTED, font=FONT_TINY)

    # ── 交互辅助 ─────────────────────────────────────────────────────────

    def _set_stock_mode(self, mode: str) -> None:
        if not hasattr(self, "stock_mode"):
            return
        self.stock_mode.set(mode)
        for label, button in self.stock_mode_buttons.items():
            button.configure(bg=ORANGE_SOFT if label == mode else SURFACE, fg=ORANGE_DARK if label == mode else TEXT_SOFT)
        if mode == "五档" and "stock_order" not in self.results:
            self.refresh_page("stock")
        elif mode == "日K":
            self._draw_stock_chart()

    def _search_stock(self) -> None:
        value = self.stock_var.get().strip().upper()
        if not value: self.status_var.set("请输入标的代码"); return
        self._show_page("stock", refresh=False); self.loaded_pages.discard("stock"); self.refresh_page("stock")

    def _select_code_from_tree(self, event: tk.Event) -> None:
        selection = event.widget.selection()
        if not selection: return
        values = event.widget.item(selection[0], "values")
        if values:
            code = str(values[0]).strip()
            if re.match(r"^(?:SH|SZ|BJ)?\d{6}$", code, re.I): self.stock_var.set(code.upper()); self._search_stock()

    def _show_news_preview(self, event: tk.Event) -> None:
        selection = event.widget.selection()
        if not selection or self.preview_text is None: return
        values = event.widget.item(selection[0], "values"); self._set_preview("\n".join(str(value) for value in values if str(value).strip()))

    def _set_preview(self, text: str) -> None:
        if self.preview_text is None: return
        self.preview_text.configure(state="normal"); self.preview_text.delete("1.0", "end"); self.preview_text.insert("1.0", _safe_text(text, 1000)); self.preview_text.configure(state="disabled")

    def _set_home_hot(self, text: str) -> None:
        if not hasattr(self, "home_hot_text"):
            return
        self.home_hot_text.configure(state="normal")
        self.home_hot_text.delete("1.0", "end")
        self.home_hot_text.insert("1.0", _safe_text(text, 500))
        self.home_hot_text.configure(state="disabled")

    def _on_capability_selected(self, _event: tk.Event) -> None:
        if self.capability_tree is None: return
        selection = self.capability_tree.selection()
        if not selection or selection[0] not in self.capability_tree_data: return
        self.active_capability = self.capability_tree_data[selection[0]]; group, label, spec_key = self.active_capability; preset = PRESET_BY_KEY.get(spec_key); self.capability_title_var.set(label); self.capability_desc_var.set(f"{group} · 使用顶部的标的和交易日作为查询条件。"); self.capability_status_var.set(f"已选择：{label} · 点击“查询此项”")
        if preset is not None: self.capability_desc_var.set(preset.description or f"{group} · 使用顶部的标的和交易日作为查询条件。")

    def _run_capability(self) -> None:
        if self.active_capability is None: self.status_var.set("请先选择一项能力"); return
        if not self._validate_inputs(): return
        _group, label, spec_key = self.active_capability; preset = PRESET_BY_KEY.get(spec_key)
        if preset is None: self.status_var.set("此能力暂不可查询"); return
        self.generation += 1; generation = self.generation; self.pending = {spec_key}; self.status_var.set(f"正在查询：{label}"); self.capability_status_var.set("请求中…"); self.loaded_pages.add("capabilities"); self.client.request(self.base_url_var.get().strip(), preset, self.stock_var.get().strip().upper(), self.date_var.get().strip(), generation)

    def _toggle_privacy(self) -> None:
        self.privacy_mode = not self.privacy_mode
        self.privacy_button.configure(text="恢复中文名" if self.privacy_mode else "隐藏中文名")
        # Re-render cached results only; privacy mode must never trigger a new request.
        for key, result in list(self.results.items()):
            self._render_result(key, result)

    def clear_current(self) -> None:
        for key in list(self.results):
            if key in self._page_queries(self.active_page): self.results.pop(key, None)
        for tree in self.tables.values(): tree.delete(*tree.get_children())
        for canvas in self.canvases.values(): canvas.delete("all"); canvas.create_text(max(100, canvas.winfo_width() / 2), max(50, canvas.winfo_height() / 2), text="暂无数据", fill=MUTED, font=FONT_SMALL)
        self.status_var.set("视图已清空"); self.updated_var.set("—")

    def _close(self) -> None:
        self.pending.clear(); self.root.destroy()


def _rate_text(value: Any) -> str:
    number = _number(value)
    if number is None: return _safe_text(value)
    return f"{number:+.2f}%"


def _value_color(value: Any) -> str:
    number = _number(value)
    if number is None: return TEXT_SOFT
    return RED if number >= 0 else GREEN


def _axis_text(value: float) -> str:
    if abs(value) >= 100000000: return f"{value / 100000000:.1f}亿"
    if abs(value) >= 10000: return f"{value / 10000:.1f}万"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="达塔接口 d1 用户侧市场数据工作台")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="本地 d1 服务地址")
    return parser.parse_args()


def main() -> int:
    args = parse_args(); root = tk.Tk(); D1Gui(root, args.base_url); root.mainloop(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
