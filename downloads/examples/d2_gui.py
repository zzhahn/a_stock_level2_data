#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""d2 线路图表看板与能力调试器 (Python Tkinter 示例 GUI)。

启动后的主界面是市场、个股、专题和期货图表看板；最后的接口调试页保留对 D2
全量能力的浏览、配置与逐项调用能力。所有图表均使用 Tk Canvas 绘制，不依赖
matplotlib 等第三方 GUI 组件。

所有网络请求均在后台线程执行，Tkinter 界面仅在主线程更新，具备防死锁、请求取消、
超时防护与优雅退出机制。
"""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import math
import queue
import re
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError as err:
    print(f"错误: 缺少 Tkinter 图形界面支持库: {err}", file=sys.stderr)
    print("请检查当前 Python 环境是否已安装并启用 Tkinter。", file=sys.stderr)
    sys.exit(1)

# 尝试导入同目录下的隐私显示辅助模块；若作为独立文件运行则使用内置降级实现。
try:
    from privacy_display import display_name, is_name_field, mask_chinese_name
except ImportError:
    _HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
    _NAME_FIELDS = frozenset(
        {
            "name",
            "stockname",
            "stock_name",
            "prodname",
            "prod_name",
            "zsname",
            "platename",
            "plate_name",
            "sectorname",
            "sector_name",
            "industryname",
            "industry_name",
            "boardname",
            "board_name",
            "companyname",
            "company_name",
            "instrumentname",
            "secuabbr",
            "pk_name",
            "pkname",
            "security_name_abbr",
            "security_name",
            "board_name",
            "theme_name",
            "mutual_type_name",
            "leading_stock_name",
            "orgname",
            "org_name",
            "company_name",
            "板块",
            "板块名称",
            "股票名称",
            "代表个股",
            "所属板块",
            "相关板块",
            "领涨股",
            "领跌股",
            "行业",
            "名称",
        }
    )

    def mask_chinese_name(value: Any) -> str:
        text = "" if value is None else str(value)

        def replace(match: re.Match[str]) -> str:
            run = match.group(0)
            return "*" * max(1, len(run) - 1) + run[-1]

        return _HAN_RUN.sub(replace, text)

    def is_name_field(key: Any) -> bool:
        field_str = str(key or "").strip()
        leaf = field_str.rsplit(".", 1)[-1]
        normalized = leaf.lower().replace("-", "_")
        return normalized in _NAME_FIELDS or leaf in _NAME_FIELDS

    def display_name(value: Any, privacy_enabled: bool) -> str:
        text = "" if value is None else str(value)
        return mask_chinese_name(text) if privacy_enabled else text


# ==============================================================================
# 视觉设计与深色主题配置
# ==============================================================================
BG = "#080d16"
TOP = "#101827"
PANEL = "#0e1724"
PANEL_ALT = "#121f31"
INPUT = "#172337"
BORDER = "#22324a"
TEXT = "#d9e3f0"
MUTED = "#8294ad"
DIM = "#53647d"
RED = "#f05d71"
GREEN = "#31c48d"
GOLD = "#e9c445"
BLUE = "#5aa7ff"
PURPLE = "#b58cff"
CYAN = "#4ec9b0"
WHITE = "#f5f8fc"

FONT = ("Consolas", 10)
FONT_SMALL = ("Consolas", 9)
FONT_TINY = ("Consolas", 8)
FONT_CN = ("Microsoft YaHei UI", 10)
FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")
FONT_BIG = ("Microsoft YaHei UI", 15, "bold")
FONT_SECTION = ("Microsoft YaHei UI", 10, "bold")


# ==============================================================================
# 字段字典与人类可读列名映射
# ==============================================================================
FIELD_LABELS: Dict[str, str] = {
    # 常用代码与名称
    "code": "证券代码",
    "secid": "完整标识",
    "secids": "标识列表",
    "symbol": "证券代码",
    "symbol_code": "证券代码",
    "SECURITY_CODE": "证券代码",
    "SECUCODE": "完整代码",
    "SECURITY_NAME_ABBR": "证券简称",
    "SECURITY_NAME": "证券名称",
    "name": "证券名称",
    "stock_name": "股票名称",
    "market": "所属市场",
    "BOARD_CODE": "板块代码",
    "BOARD_NAME": "板块名称",
    "THEME_CODE": "主题代码",
    "THEME_NAME": "主题名称",
    "trade_date": "交易日期",
    "TRADE_DATE": "交易日期",
    "NOTICE_DATE": "公告日期",
    "REPORT_DATE": "报告期",
    "END_DATE": "截止日期",
    "date": "日期",
    "time": "时间",
    "update_time": "更新时间",
    # 价格与波动
    "price": "现价",
    "latest_price": "最新价",
    "CLOSE_PRICE": "收盘价",
    "NEW_PRICE": "最新价",
    "OPEN_PRICE": "开盘价",
    "HIGH_PRICE": "最高价",
    "LOW_PRICE": "最低价",
    "PRE_CLOSE_PRICE": "昨收价",
    "change_pct": "涨跌幅%",
    "CHANGE_RATE": "涨跌幅%",
    "CHANGE_RATE_1D": "当日涨跌幅%",
    "CHANGE": "涨跌额",
    "AMPLITUDE": "振幅%",
    "TURNOVER_RATE": "换手率%",
    # 成交与资金
    "volume": "成交量",
    "amount": "成交额",
    "DEAL_AMOUNT": "成交额",
    "DEAL_VOLUME": "成交量",
    "NET_AMOUNT": "净买额",
    "BUY_AMOUNT": "买入额",
    "SELL_AMOUNT": "卖出额",
    "dark_money_yuan": "暗盘资金(元)",
    "regular_money_yuan": "明盘资金(元)",
    "net_money_yuan": "净流入资金(元)",
    "dark_activity_pct": "暗盘活跃度%",
    "dark_inflow_count": "暗盘流入家数",
    "dark_outflow_count": "暗盘流出家数",
    "dark_inflow_ratio_pct": "暗盘流入比例%",
    "main_net_inflow": "主力净流入",
    "net_inflow": "净流入",
    # 估值与指标
    "PE": "市盈率",
    "PB": "市净率",
    "DIVIDEND_RATE": "股息率%",
    "TOTAL_MARKET_CAP": "总市值",
    "FREE_CAP": "流通市值",
    "SCORE": "评分",
    "Score": "评分",
    "RANK": "排名",
    "rank": "名次",
    "STATUS": "状态",
    "Status": "业务状态",
    "Result": "业务结果",
    "Message": "返回说明",
    # 涨跌停专题
    "LIMIT_NUMBERS": "涨停总数",
    "NATURAL_LIMIT": "自然涨停",
    "DAILY_LIMIT": "一字涨停",
    "TOUCH_LIMIT": "曾触板数",
    "SEALING_RATE": "封板率%",
    "COUNTINUS_STOCK_NUM": "连板家数",
    "MAX_CONTINUS_UPLIMITS": "连板高度",
    "UPLIMIT_NUM": "涨停家数",
    "DOWNLIMIT_NUM": "跌停家数",
    "CLOSE_LIMITUP_TIME": "封板时间",
    "LIMIT_VOLUME": "封单量",
    # 两融与质押
    "RZYE": "融资余额",
    "RQYE": "融券余额",
    "RZRQYE": "两融余额",
    "PLEDGE_RATIO": "质押比例%",
    "AVG_PLEDGE_RATIO": "行业平均质押率%",
    "WARNING_LINE": "预警线",
    "CLOSE_LINE": "平仓线",
    # 期货字段
    "variety": "期货品种",
    "contract": "期货合约",
    "variety_name": "品种名称",
    "company_name": "期货机构/席位",
    "company_code": "席位编码",
    "long_position": "多头持仓",
    "short_position": "空头持仓",
    "net_position": "净持仓",
    "position": "总持仓",
    "settlement_price": "结算价",
}

FIELD_TOKEN_LABELS: Dict[str, str] = {
    "code": "代码",
    "name": "名称",
    "price": "价格",
    "rate": "比率",
    "ratio": "比例",
    "pct": "百分比",
    "date": "日期",
    "time": "时间",
    "amount": "金额",
    "balance": "余额",
    "vol": "量",
    "volume": "量",
    "num": "数量",
    "count": "数量",
    "rank": "排名",
    "score": "得分",
    "status": "状态",
    "type": "类型",
    "change": "变动",
    "high": "最高",
    "low": "最低",
    "open": "开盘",
    "close": "收盘",
    "pre": "昨",
    "net": "净",
    "flow": "流向",
    "fund": "资金",
    "hold": "持仓",
    "total": "总",
    "limit": "涨跌停",
    "market": "市场",
    "broker": "席位",
    "org": "机构",
    "variety": "品种",
    "contract": "合约",
}


def humanize_field_name(raw_name: str) -> str:
    """将字段名称转换为易读的中文字段，优先精确匹配，未命中时按词根拼装。"""
    key = str(raw_name or "").strip()
    if not key:
        return ""
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    lower_key = key.lower()
    if lower_key in FIELD_LABELS:
        return FIELD_LABELS[lower_key]

    # 拆分大写蛇形命名，如 TOTAL_DEAL_AMOUNT
    if "_" in key:
        tokens = [t.lower() for t in key.split("_") if t]
        matched = [FIELD_TOKEN_LABELS.get(t, t) for t in tokens]
        if any(t in FIELD_TOKEN_LABELS for t in tokens):
            return "".join(matched)

    # 拆分驼峰命名，如 totalDealAmount
    camel_tokens = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z]|\b)", key)
    if camel_tokens and len(camel_tokens) > 1:
        tokens = [t.lower() for t in camel_tokens]
        matched = [FIELD_TOKEN_LABELS.get(t, t) for t in tokens]
        if any(t in FIELD_TOKEN_LABELS for t in tokens):
            return "".join(matched)

    return key


def get_field_sort_priority(field_name: str) -> int:
    """获取字段在表格中的呈现优先级，核心业务字段靠左排布。"""
    lower = field_name.lower()
    if any(k in lower for k in ("code", "symbol", "secid")):
        return 10
    if any(k in lower for k in ("name", "abbr")):
        return 20
    if any(k in lower for k in ("price", "close", "last", "现价", "收盘")):
        return 30
    if any(k in lower for k in ("change", "rate", "pct", "涨跌", "幅")):
        return 40
    if any(k in lower for k in ("amount", "balance", "money", "flow", "额", "金")):
        return 50
    if any(k in lower for k in ("volume", "vol", "share", "量", "手")):
        return 60
    if any(k in lower for k in ("date", "time", "day", "日", "时")):
        return 70
    if any(k in lower for k in ("rank", "score", "分", "名")):
        return 80
    return 100


# ==============================================================================
# 声明式能力定义与操作注册表
# ==============================================================================
@dataclass
class ParamDef:
    name: str
    label: str
    default: str = ""
    required: bool = False
    hint: str = ""
    options: Optional[List[str]] = None
    bind_to: Optional[str] = None  # 可绑定顶栏公共值: "code", "date", "pageNumber", "pageSize"


@dataclass
class Capability:
    id: str
    name: str
    category: str
    sub: str
    view_param: str = ""  # 路由维度所用参数名: "type", "view", "report" 等
    view_val: str = ""
    method: str = "POST"  # 默认使用 POST 表单，支持切换 GET
    path: str = "/d2/gc"
    description: str = ""
    params: List[ParamDef] = field(default_factory=list)
    is_compatible: bool = False
    tags: List[str] = field(default_factory=list)


# 通用分页与日期参数生成函数
def _common_paging_params() -> List[ParamDef]:
    return [
        ParamDef("pageNumber", "页码", "1", False, "从1开始", bind_to="pageNumber"),
        ParamDef("pageSize", "每页条数", "50", False, "默认50", bind_to="pageSize"),
        ParamDef("columns", "返回列集", "ALL", False, "ALL或逗号分隔列名"),
        ParamDef("filter", "高级筛选", "", False, "服务端筛选表达式"),
        ParamDef("sortColumns", "排序列", "", False, "指定排序列"),
        ParamDef("sortTypes", "排序方向", "", False, "-1降序 / 1升序"),
    ]


def build_capabilities_registry() -> List[Capability]:
    """构建全量 D2 用户侧能力注册表，覆盖基础股池、事件、期货、诊断、专题等。"""
    c_list: List[Capability] = []

    # --------------------------------------------------------------------------
    # 1. 基础股池与动态榜单
    # --------------------------------------------------------------------------
    c_list.append(
        Capability(
            id="guchi",
            name="涨跌停与炸板股池",
            category="基础股池与榜单",
            sub="guchi",
            description="当日涨停(1)、炸板(2)、跌停(3)股票池实时与历史数据。",
            params=[
                ParamDef("status", "股池状态", "1", True, "1=涨停, 2=炸板, 3=跌停", ["1", "2", "3"]),
                ParamDef("date", "查询日期", "", False, "YYYYMMDD或YYYY-MM-DD", bind_to="date"),
            ],
            tags=["股池", "涨停", "跌停", "炸板"],
        )
    )
    c_list.append(
        Capability(
            id="guchi_pc",
            name="股池长区间查询",
            category="基础股池与榜单",
            sub="guchi_pc",
            description="支持跨日期区间的股池明细查询。",
            params=[
                ParamDef("status", "股池状态", "1", False, "1=涨停, 2=炸板, 3=跌停", ["1", "2", "3"]),
                ParamDef("date", "查询日期", "", False, "基准日期", bind_to="date"),
                ParamDef("pageNumber", "页码", "1", False, "从1开始", bind_to="pageNumber"),
                ParamDef("pageSize", "每页条数", "50", False, "每页数量", bind_to="pageSize"),
            ],
        )
    )
    c_list.append(
        Capability(
            id="guchi_date",
            name="股池日期统计",
            category="基础股池与榜单",
            sub="guchi_date",
            description="按交易日统计股池数量走势。",
            params=_common_paging_params(),
        )
    )
    c_list.append(
        Capability(
            id="time",
            name="服务当前时间",
            category="基础股池与榜单",
            sub="time",
            description="获取 D2 数据端当前系统时间戳与连接心跳。",
            params=[],
        )
    )
    c_list.append(
        Capability(
            id="lhb_daily",
            name="每日龙虎榜明细",
            category="基础股池与榜单",
            sub="lhb_daily",
            description="全市场每日龙虎榜上榜个股与异动原因明细。",
            params=[
                ParamDef("date", "交易日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "每页条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["龙虎榜", "每日榜单"],
        )
    )
    c_list.append(
        Capability(
            id="lhb_inst",
            name="龙虎榜机构席位追踪",
            category="基础股池与榜单",
            sub="lhb_inst",
            description="机构专用席位在龙虎榜上的买入/卖出明细。",
            params=[
                ParamDef("date", "交易日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "每页条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["机构席位", "龙虎榜"],
        )
    )
    c_list.append(
        Capability(
            id="lhb_dept",
            name="营业部龙虎榜排行",
            category="基础股池与榜单",
            sub="lhb_dept",
            description="知名游资与券商营业部活跃度及成交金额排行。",
            params=[
                ParamDef("date", "交易日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "每页条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["营业部", "游资排行"],
        )
    )
    c_list.append(
        Capability(
            id="block_trade",
            name="大宗交易成交数据",
            category="基础股池与榜单",
            sub="block_trade",
            description="沪深京大宗交易成交价、溢价折价率、买卖双方明细。",
            params=[
                ParamDef("date", "交易日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "每页条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["大宗交易"],
        )
    )
    c_list.append(
        Capability(
            id="flow_industry",
            name="行业资金流向",
            category="基础股池与榜单",
            sub="flow_industry",
            description="按行业统计的主力净流入、超大单、大单与散户资金。",
            params=[
                ParamDef("pn", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pz", "每页条数", "50", False, "条数", bind_to="pageSize"),
                ParamDef("fid", "排序字段", "f62", False, "默认主力净流入降序"),
                ParamDef("fields", "指定返回字段", "", False, "逗号分隔字段"),
            ],
            tags=["资金流", "行业"],
        )
    )
    c_list.append(
        Capability(
            id="flow_concept",
            name="概念资金流向",
            category="基础股池与榜单",
            sub="flow_concept",
            description="按概念板块统计的主力资金净流入与涨跌表现。",
            params=[
                ParamDef("pn", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pz", "每页条数", "50", False, "条数", bind_to="pageSize"),
                ParamDef("fid", "排序字段", "f62", False, "默认主力净流入降序"),
                ParamDef("fields", "指定返回字段", "", False, "逗号分隔字段"),
            ],
            tags=["概念资金流"],
        )
    )
    c_list.append(
        Capability(
            id="flow_stock",
            name="个股资金流向排行",
            category="基础股池与榜单",
            sub="flow_stock",
            description="全市场个股主力资金流入、占比与价格涨跌幅排行。",
            params=[
                ParamDef("pn", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pz", "每页条数", "50", False, "条数", bind_to="pageSize"),
                ParamDef("fid", "排序字段", "f62", False, "默认主力净流入降序"),
                ParamDef("fields", "指定返回字段", "", False, "逗号分隔字段"),
            ],
            tags=["个股资金流"],
        )
    )
    c_list.append(
        Capability(
            id="hot_stocks",
            name="股票人气与热度排行",
            category="基础股池与榜单",
            sub="hot_stocks",
            description="市场人气股票与关注度综合排行。",
            params=[
                ParamDef("pn", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pz", "每页条数", "50", False, "条数", bind_to="pageSize"),
                ParamDef("fields", "返回字段", "", False, "可选定制字段"),
            ],
            tags=["热度", "人气股"],
        )
    )

    # --------------------------------------------------------------------------
    # 2. 公司事件与日历
    # --------------------------------------------------------------------------
    c_list.append(
        Capability(
            id="ipo_apply",
            name="新股申购日历",
            category="公司事件与日历",
            sub="ipo_apply",
            description="新股、可转债网上网下申购代码、发行价与中签率。",
            params=[
                ParamDef("date", "日期", "", False, "查询日期", bind_to="date"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["IPO", "申购"],
        )
    )
    c_list.append(
        Capability(
            id="jiejin",
            name="限售解禁明细",
            category="公司事件与日历",
            sub="jiejin",
            description="上市公司限售股解禁日期、解禁股数、占总股本比例。",
            params=[
                ParamDef("date", "解禁日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["限售解禁"],
        )
    )
    c_list.append(
        Capability(
            id="dividend",
            name="分红送转方案",
            category="公司事件与日历",
            sub="dividend",
            description="上市公司最新分红方案、除权除息日、股权登记日及派息额。",
            params=[
                ParamDef("date", "公告日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["分红", "送转"],
        )
    )
    c_list.append(
        Capability(
            id="forecast",
            name="业绩预告查询",
            category="公司事件与日历",
            sub="forecast",
            description="业绩预增、预减、扭亏、首亏公告明细与净利润变动幅度。",
            params=[
                ParamDef("date", "预告日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["业绩预告"],
        )
    )
    c_list.append(
        Capability(
            id="holder_change",
            name="股东与高管持股变动",
            category="公司事件与日历",
            sub="holder_change",
            description="控股股东、高管增持/减持记录、变动数量与成交均价。",
            params=[
                ParamDef("date", "变动日期", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["增减持", "高管变动"],
        )
    )
    c_list.append(
        Capability(
            id="holder_num",
            name="股东户数与筹码变动",
            category="公司事件与日历",
            sub="holder_num",
            description="最新一期股东户数变动、户均持股金额与筹码集中趋势。",
            params=[
                ParamDef("date", "统计截止日", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("code", "证券代码", "", False, "六位代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ],
            tags=["股东户数", "筹码集中度"],
        )
    )
    c_list.append(
        Capability(
            id="northbound",
            name="沪深港通持仓与资金",
            category="公司事件与日历",
            sub="northbound",
            description="沪股通、深股通与港股通分钟实时资金或持股汇总。",
            params=[
                ParamDef("type", "查询类型", "flow", True, "flow=实时资金流 / hold=持股汇总", ["flow", "hold"]),
                ParamDef("pageNumber", "页码", "1", False, "仅hold生效", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "仅hold生效", bind_to="pageSize"),
            ],
            tags=["互联互通", "北向资金"],
        )
    )

    # --------------------------------------------------------------------------
    # 3. 涨停专题多视图 (sub=limit_topic)
    # --------------------------------------------------------------------------
    limit_views = [
        ("dates", "可选交易日期列表", "获取涨停专题当前支持的有效交易日期。"),
        ("limit_summary", "当日涨停概况", "市场涨跌停数、自然涨停、炸板与封板率概览。"),
        ("quality_monitor", "质量涨停监控", "符合质量基因筛选的优质涨停监控序列。"),
        ("emotion", "涨停情绪序列", "连板高度、触板数、情绪指标历史走势。"),
        ("emotion_history", "历史情绪趋势", "较长跨度涨停与情绪指标走势，支持指定截止日期。"),
        ("auction_pool", "早盘竞价涨停池", "集合竞价阶段直接封涨停的个股清单。"),
        ("limit_pool", "全市场涨停池", "全市场当日封板涨停股票列表(默认核心池)。"),
        ("approaching_pool", "即将涨停池", "盘中快速拉升、接近涨停价位的个股。"),
        ("continuous_pool", "连板池", "2连板及以上连续封板的强势个股池。"),
        ("broken_pool", "炸板池", "触及涨停后被打开且未回封的股票列表。"),
        ("yesterday_pool", "昨日涨停表现", "昨日涨停个股在今日盘中的延续性表现与收益率。"),
        ("down_pool", "跌停池", "盘中封死跌停板的个股列表。"),
        ("ever_down_pool", "曾跌停打开池", "曾触及跌停后被撬开反弹的个股列表。"),
        ("history_pool", "历史涨停明细", "查看指定历史交易日的涨停明细列表。"),
        ("ladder", "连板天梯", "按连板板数从高到低排列的阶梯行情。"),
        ("multi_stock", "多板个股筛选", "支持多维度筛选条件的高阶板池。"),
        ("index_list", "指数行情摘要", "重要大盘指数涨跌停走势摘要。"),
        ("index_trend", "指数走势指标", "指数涨跌走势与强度序列。"),
        ("minute_trend", "指数板块分时", "指定指数或板块的分时走向。"),
        ("sector_summary", "强势板块概况", "领涨板块统计与涨停个股分布概况。"),
        ("sector_list", "强势板块与成分股", "涨停集中的板块及其成分个股明细。"),
        ("limit_reason", "涨停原因深度分析", "个股当日封板的核心驱动逻辑与题材分析。"),
    ]
    for v_code, v_name, v_desc in limit_views:
        p_defs = [
            ParamDef("view", "视图标识", v_code, True, "当前子视图", [v_code]),
            ParamDef("date", "日期筛选", "", False, "YYYYMMDD", bind_to="date"),
        ]
        if v_code in ("limit_reason", "history_pool"):
            p_defs.append(ParamDef("code", "证券代码", "", False, "可选指定股票", bind_to="code"))
        if v_code == "emotion_history":
            p_defs.append(ParamDef("endDate", "截止日期", "", False, "YYYYMMDD"))
        if v_code in ("index_list", "index_trend"):
            p_defs.append(ParamDef("secids", "指数列表", "1.000002,0.399002,0.899050", False, "逗号分隔"))
        if v_code == "minute_trend":
            p_defs.append(ParamDef("secid", "指数代码", "1.000001", False, "如1.000001"))
            p_defs.append(ParamDef("ndays", "天数", "1", False, "分时天数"))
            p_defs.extend([
                ParamDef("fields1", "摘要字段", "f1,f6,f8", False, "行情摘要字段集合"),
                ParamDef("fields2", "序列字段", "f51,f53", False, "分时序列字段集合"),
                ParamDef("time", "起始时刻", "930", False, "如930"),
            ])
        p_defs.extend(
            [
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "50", False, "条数", bind_to="pageSize"),
            ]
        )
        if v_code in {
            "dates", "limit_summary", "quality_monitor", "emotion", "emotion_history",
            "history_pool", "sector_summary", "sector_list",
        }:
            p_defs.extend([
                ParamDef("columns", "返回列集", "", False, "逗号分隔列名"),
                ParamDef("filter", "高级筛选", "", False, "服务端筛选表达式"),
                ParamDef("sortColumns", "排序列", "", False, "指定排序列"),
                ParamDef("sortTypes", "排序方向", "", False, "-1降序 / 1升序"),
            ])
        if v_code in {
            "limit_pool", "continuous_pool", "broken_pool", "yesterday_pool",
            "down_pool", "ladder", "multi_stock", "sector_summary", "sector_list",
        }:
            p_defs.extend([
                ParamDef("fl", "市场字段", "", False, "高级页面筛选，通常留空"),
                ParamDef("ty", "板池类型", "", False, "高级页面筛选，通常留空"),
                ParamDef("ft", "板型筛选", "", False, "高级页面筛选，通常留空"),
                ParamDef("nft", "非特殊板筛选", "", False, "高级页面筛选，通常留空"),
                ParamDef("st", "特殊处理筛选", "", False, "高级页面筛选，通常留空"),
                ParamDef("sf", "排序/筛选标记", "", False, "高级页面筛选，通常留空"),
                ParamDef("vl", "版本标记", "", False, "高级页面筛选，通常留空"),
            ])
        if v_code == "index_trend":
            p_defs.extend([
                ParamDef("time", "起始时刻", "930", False, "如930"),
                ParamDef("fields", "走势字段", "f1,f2,f3,f4,f5", False, "逗号分隔字段"),
            ])
        c_list.append(
            Capability(
                id=f"limit_topic_{v_code}",
                name=f"涨停专题·{v_name}",
                category="涨停专题多视图",
                sub="limit_topic",
                view_param="view",
                view_val=v_code,
                description=v_desc,
                params=p_defs,
                tags=["涨停专题", v_code, v_name],
            )
        )

    # --------------------------------------------------------------------------
    # 4. 个股智能诊断 (sub=diagnosis)
    # --------------------------------------------------------------------------
    diag_types = [
        ("summary", "综合评分摘要", True, "个股技术面、资金面、基本面综合评分。"),
        ("value", "估值评估摘要", True, "相对估值、绝对估值与同业对比摘要。"),
        ("trend", "趋势研判概览", True, "短期与中长期多空趋势判断。"),
        ("capital", "资金流向摘要", True, "主力大单与中散户资金博弈概览。"),
        ("market_heat", "市场热度表现", True, "个股在所属市场中的关注与搜索热度。"),
        ("market_cost", "市场成本历史序列", True, "持仓均价、筹码成本线与获利分布。"),
        ("comment", "全景综合点评", True, "AI智能综合面点评与操盘提示。"),
        ("forecast", "涨跌概率预测", True, "基于量价模型的次日涨跌概率。"),
        ("score_history", "历史评分序列", True, "过去一段时间的综合诊断分值变化。"),
        ("score_ranking_detail", "行业与市场排名", True, "在细分行业和全市场的排名位次。"),
        ("valuation_comment", "估值维度点评", True, "估值是否高估/低估的详细文字点评。"),
        ("valuation_profitability", "盈利能力分析", True, "ROE、毛利率、净利率等指标。"),
        ("valuation_growth", "成长能力评估", True, "营收与利润复合增长态势。"),
        ("valuation_level", "估值水平指标", True, "PE/PB历史百分位水平。"),
        ("valuation_special", "估值特殊指标", True, "行业特色核心财务指标。"),
        ("valuation_solvency", "偿债与营运能力", True, "资产负债率、速动比率与周转率。"),
        ("valuation_cashflow", "现金流量分析", True, "经营性现金流与收现比分析。"),
        ("capital_summary", "资金详细摘要", True, "超大单、大单成交分布明细。"),
        ("capital_flow", "个股资金趋势曲线", True, "连续交易日主力资金流动曲线。"),
        ("capital_industry", "所属行业资金流", True, "所属行业板块整体资金进出背景。"),
        ("capital_level2", "逐笔成交资金", True, "大单主买与主卖笔数统计。"),
        ("capital_winner", "龙虎榜上榜资金", True, "近期龙虎榜席位资金偏向。"),
        ("capital_margin", "两融诊断明细", True, "融资买入与融券偿还动态。"),
        ("trend_comment", "趋势研判点评", True, "均线多空排列与支撑阻力位。"),
        ("trend_energy", "趋势能量指标", True, "量能爆发与多空动能指标。"),
        ("trend_technology", "技术形态概览", True, "金叉、底背离等典型形态捕捉。"),
        ("trend_macd", "MACD指标序列", True, "MACD柱线与DIFF/DEA序列。"),
        ("trend_kdj", "KDJ指标序列", True, "KDJ超买超卖与交叉点。"),
        ("trend_rsi", "RSI指标序列", True, "RSI相对强弱历史时序。"),
        ("trend_boll", "BOLL布林带序列", True, "上轨、中轨、下轨轨道变动。"),
        ("trend_bias", "BIAS乖离率序列", True, "短中长乖离率离散度。"),
        ("trend_wr", "WR威廉指标序列", True, "威廉超买超卖震荡序列。"),
        ("sentiment_comment", "舆情综合点评", True, "正面、中性、负面新闻舆情热度。"),
        ("sentiment_list", "舆情监控列表", True, "关联公告、研报与新闻列表。"),
        ("ranking", "诊股全市场排行", False, "全市场股票综合诊断评分榜单。"),
        ("check", "诊断资格校验", True, "校验目标代码是否支持智能诊断服务。"),
    ]
    for d_type, d_name, req_code, d_desc in diag_types:
        p_defs = [
            ParamDef("type", "诊断类别", d_type, True, "当前子类型", [d_type]),
        ]
        if req_code:
            p_defs.append(ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"))
        else:
            p_defs.append(ParamDef("rankType", "排行分类", "0", False, "0~3档位", ["0", "1", "2", "3"]))
        if req_code:
            p_defs.append(ParamDef("market", "市场提示", "", False, "代码无法判断市场时填写 sh/sz/bj"))
        if d_type == "score_ranking_detail":
            p_defs.append(ParamDef("rankType", "排行分类", "1", False, "0~3档位", ["0", "1", "2", "3"]))
        if d_type == "sentiment_list":
            p_defs.extend(
                [
                    ParamDef("sentimentType", "舆情分类", "0", False, "0全部,1新闻,2公告,16研报", ["0", "1", "2", "16"]),
                    ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                    ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
                ]
            )
        c_list.append(
            Capability(
                id=f"diag_{d_type}",
                name=f"诊股·{d_name}",
                category="个股智能诊断",
                sub="diagnosis",
                view_param="type",
                view_val=d_type,
                description=d_desc,
                params=p_defs,
                tags=["诊股", "诊断", d_type],
            )
        )

    # --------------------------------------------------------------------------
    # 5. 期货持仓与成交分析 (sub=futures_analysis)
    # --------------------------------------------------------------------------
    futu_types = [
        ("varieties", "期货市场与品种列表", False, "获取全部支持的期货交易所与品种代码。"),
        ("companies", "期货机构席位列表", False, "获取全部经纪商席位代码与名称。"),
        ("contracts", "品种合约与主力映射", False, "查询品种对应的月份合约以及主力合约标识。"),
        ("market_date", "各期货市场最新交易日", False, "获取各期货交易所当前最新确认的交易日。"),
        ("position_trend", "多空持仓趋势", True, "指定合约的多头、空头与净持仓走势。"),
        ("position_history", "总持仓历史序列", True, "总持仓手数组合时间序列。"),
        ("position_detail", "多空席位持仓明细", True, "前20名主力席位持仓增减明细。"),
        ("net_position", "席位净持仓明细", True, "排名前列的净多单/净空单席位排行。"),
        ("volume_trend", "成交量与结算趋势", True, "成交手数、成交金额及结算价演变。"),
        ("volume_history", "总成交历史序列", True, "合约完整历史成交数据序列。"),
        ("volume_detail", "席位成交量明细", True, "各席位当日成交量与变动明细。"),
        ("position_distribution", "全品种净持仓分布", False, "全市场各主要品种多空集中度分布。"),
        ("kline_broker", "席位持仓合并K线", True, "标的价格K线与席位持仓量合并时序。"),
        ("kline_broker_full", "完整席位持仓K线序列", True, "包含全量历史席位K线图数据。"),
        ("broker_position", "指定席位持仓曲线", True, "单家席位在指定品种上的净多空曲线。"),
        ("broker_position_legacy", "指定席位历史净持仓", True, "单家席位历史净持仓时序。"),
        ("company_list", "品种席位多空排行", True, "某品种主要会员持仓排行清单。"),
        ("company_pay_by_variety", "席位各品种盈亏曲线", False, "指定席位在各品种上的历史盈利表现。"),
        ("variety_pay_by_broker", "品种各席位盈亏曲线", False, "指定品种在各席位间的盈利分布走势。"),
        ("variety_year_pay", "品种年度席位盈亏排行", False, "全品种年度会员席位盈亏排名。"),
        ("latest_trade_date", "期货最新交易日[兼容]", False, "兼容入口：期货最新交易日探测。"),
    ]
    for f_type, f_name, req_contract, f_desc in futu_types:
        p_defs = [
            ParamDef("type", "分析类型", f_type, True, "当前子类型", [f_type]),
            ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
        ]
        if req_contract:
            p_defs.extend(
                [
                    ParamDef("market", "市场编码", "113", False, "如113(上期所)"),
                    ParamDef("contract", "合约/品种", "rb", True, "如rb或具体合约rb2610"),
                ]
            )
        if f_type in ("kline_broker", "kline_broker_full"):
            p_defs.append(ParamDef("orgCodes", "席位代码", "0", False, "0为汇总，或具体席位代码"))
            p_defs.append(ParamDef("mainAndSlaveTransFlag", "主从合约合并", "0", False, "1=按主从合并，0=普通", ["0", "1"]))
        if f_type in ("broker_position", "broker_position_legacy"):
            p_defs.append(ParamDef("orgCode", "席位代码", "", True, "单个席位代码"))
        if f_type in ("company_pay_by_variety", "variety_pay_by_broker"):
            p_defs.extend(
                [
                    ParamDef("startDate", "起始日", "", False, "YYYYMMDD"),
                    ParamDef("endDate", "截止日", "", False, "YYYYMMDD"),
                    ParamDef("initFlag", "初始化开关", "1", False, "1为首次加载"),
                ]
            )
        if f_type in ("variety_pay_by_broker", "variety_year_pay"):
            p_defs.append(ParamDef("variety", "品种代码", "rb", False, "品种缩写如rb"))
            p_defs.append(ParamDef("market", "市场编码", "113", False, "交易所编码"))
        if f_type == "company_pay_by_variety":
            p_defs.append(ParamDef("companyCode", "席位机构代码", "", True, "席位代号"))

        c_list.append(
            Capability(
                id=f"futu_{f_type}",
                name=f"期货·{f_name}",
                category="期货持仓与成交",
                sub="futures_analysis",
                view_param="type",
                view_val=f_type,
                description=f_desc,
                params=p_defs,
                is_compatible=(f_type == "latest_trade_date"),
                tags=["期货", f_type, f_name],
            )
        )

    # --------------------------------------------------------------------------
    # 6. 暗盘资金榜 (sub=dark_market)
    # --------------------------------------------------------------------------
    dark_views = [
        ("stock", "个股暗盘资金榜", "全市场个股暗盘资金、明盘资金、主力净额及活跃度排行。"),
        ("industry", "行业板块暗盘资金榜", "各行业板块暗盘资金流入额与流入家数占比排行。"),
        ("concept", "概念板块暗盘资金榜", "各概念板块暗盘资金流入额与领涨标的排行。"),
    ]
    for d_view, d_name, d_desc in dark_views:
        c_list.append(
            Capability(
                id=f"dark_market_{d_view}",
                name=f"暗盘资金·{d_name}",
                category="暗盘资金榜单",
                sub="dark_market",
                view_param="view",
                view_val=d_view,
                description=d_desc,
                params=[
                    ParamDef("view", "榜单类型", d_view, True, "当前视图", [d_view]),
                    ParamDef("date", "交易日", "", False, "YYYYMMDD，省略为最近交易日", bind_to="date"),
                    ParamDef("page", "页码", "1", False, "1~65535", bind_to="pageNumber"),
                    ParamDef("pageSize", "每页条数", "30", False, "1~100(默认30)", bind_to="pageSize"),
                    ParamDef("sort", "排序字段", "6", False, "6=暗盘资金,7=明盘,8=净流,11=活跃度,14=涨跌幅"),
                    ParamDef("order", "排序方向", "desc", False, "desc降序 / asc升序", ["desc", "asc"]),
                    ParamDef("market", "市场筛选", "", False, "板块榜可填写90"),
                    ParamDef("datetype", "日期阶段", "", False, "行业2 / 概念3，通常留空"),
                ],
                tags=["暗盘", "资金榜", d_view],
            )
        )

    # --------------------------------------------------------------------------
    # 7. 数据中心·融资融券 (sub=rzrq)
    # --------------------------------------------------------------------------
    rzrq_types = [
        ("list", "标的明细列表", "全市场融资融券标的证券当日两融明细。"),
        ("statistics", "两融总体统计", "全市场融资买入与融券卖出余额演变。"),
        ("industry", "行业两融明细", "按申万/证监会行业划分的两融资金流向。"),
        ("industry_profile", "行业两融概况", "行业两融占总成交比例与杠杆强度。"),
        ("profile", "两融标的概况", "两融标的总体交易活跃度摘要。"),
        ("trade_profile", "交易两融全景", "包含两融占A股总成交比例的历史趋势。"),
        ("stocks", "个股两融历史", "指定单只股票的融资融券历史时序。"),
        ("etf", "ETF两融明细", "指数基金与ETF的两融余额及申赎情况。"),
        ("new_stocks", "新增两融股票", "最新一批调入融资融券标的池的股票。"),
        ("new_etf", "新增两融ETF", "最新一批调入融资融券范围的ETF。"),
        ("kline", "两融K线时序", "两融余额与标的资产价格叠加走势。"),
        ("convert_ratio", "担保品折算率", "充抵保证金有价证券折算率清单。"),
    ]
    for r_type, r_name, r_desc in rzrq_types:
        p_defs = [
            ParamDef("type", "两融类型", r_type, True, "当前子分类", [r_type]),
        ]
        if r_type in ("stocks", "etf", "convert_ratio"):
            p_defs.append(ParamDef("code", "证券代码", "000001", True, "标的代码", bind_to="code"))
        p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=f"rzrq_{r_type}",
                name=f"两融·{r_name}",
                category="两融数据中心",
                sub="rzrq",
                view_param="type",
                view_val=r_type,
                description=r_desc,
                params=p_defs,
                tags=["两融", "融资融券", r_type],
            )
        )

    # --------------------------------------------------------------------------
    # 8. 数据中心·沪深港通 (sub=hsgt)
    # --------------------------------------------------------------------------
    hsgt_types = [
        ("quota", "互联互通额度总览", "北向、南向每日可用额度与使用百分比。"),
        ("date_types", "统计周期日期列表", "支持的报表统计日期周期选项。"),
        ("deal_history", "成交历史序列", "历史各交易日北向与南向总成交额。"),
        ("stock_list", "互联互通标的列表", "全部纳入沪股通、深股通与港股通的股票。"),
        ("stock_hold", "个股持仓明细(新)", "外资在单只个股上的持仓股数与持股市值。"),
        ("stock_hold_base", "个股持仓基础表", "个股持股明细基础数据。"),
        ("stock_hold_s", "南向持股明细", "内地港股通投资者在港股标的上的持仓。"),
        ("stock_hold_etf", "ETF持股明细", "互联互通ETF品种的外资持仓明细。"),
        ("stock_hold_update", "持仓变动更新", "最近一个交易日持股增减变动排名。"),
        ("org_hold", "机构持股明细", "托管行与海外外资机构的席位持仓分解。"),
        ("org_hold_base", "机构持股基础表", "海外托管机构持股基础明细。"),
        ("org_rank", "机构持仓总排行", "各海外托管机构持股市值规模排行。"),
        ("org_rank_base", "机构排行基础表", "机构规模基础榜单。"),
        ("org_rank_date", "机构日期持仓排行", "指定日期机构持股规模榜。"),
        ("board_hold", "板块持仓明细", "北向资金在各行业与概念板块的持仓分布。"),
        ("board_hold_base", "板块持仓基础表", "板块持股基础数据。"),
        ("board_rank", "板块持仓规模排行", "外资持仓最多的重点行业板块排行。"),
        ("board_rank_base", "板块排行基础表", "板块持股市值排名。"),
        ("board_rank_date", "板块日期持仓排行", "指定日期的行业板块外资持仓榜。"),
        ("top10", "十大活跃成交股", "每日沪深港通成交金额排名前十个股。"),
        ("top10_update", "十大成交最新变动", "十大活跃成交股最新增减变动。"),
        ("hk_deal_rank", "港股通成交排行", "港股通南向资金买卖金额排行。"),
        ("etf_list", "互联互通ETF列表", "全部纳入交易的互联互通ETF代码清单。"),
        ("index_trade", "指数成交统计", "主要大盘指数在互联互通机制下的成交。"),
        ("net_inflow", "资金净流入明细", "北向与南向资金分时净买入明细。"),
        ("net_statistics", "资金净流入汇总统计", "按月、按年维度的资金净买入汇总。"),
        ("deal_amount", "成交额深度统计", "成交金额、买入与卖出总规模分解。"),
        ("all_list", "全市场标的汇总", "全量包含A股和H股的互联互通完整列表。"),
    ]
    for h_type, h_name, h_desc in hsgt_types:
        p_defs = [
            ParamDef("type", "报表类型", h_type, True, "当前子类型", [h_type]),
            ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
            ParamDef("code", "证券代码", "", False, "个股明细时填写", bind_to="code"),
        ]
        p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=f"hsgt_{h_type}",
                name=f"沪深港通·{h_name}",
                category="沪深港通数据中心",
                sub="hsgt",
                view_param="type",
                view_val=h_type,
                description=h_desc,
                params=p_defs,
                tags=["沪深港通", "北向", "南向", h_type],
            )
        )

    # --------------------------------------------------------------------------
    # 9. 数据中心·股权质押 (sub=pledge)
    # --------------------------------------------------------------------------
    pledge_types = [
        ("latest", "最新质押概况", "全市场质押股票总数、质押市值与总体质押率。"),
        ("warning", "质押预警与平仓风险", "触及预警线与平仓线的质押交易风险笔数与金额。"),
        ("industry", "行业质押分布", "按行业分类汇总的质押股数与市值占比。"),
        ("org_type", "质押主体类型分布", "券商、银行、信托等不同质押方的资金分布。"),
        ("ratio", "个股质押比例详情", "单只股票质押总股数及占总股本、流通股比例。"),
        ("ratio_rank", "个股质押比例排行", "全市场质押比例最高的上市公司排行榜。"),
        ("ledger_ratio", "大股东质押比例", "控股股东及实际控制人持股质押比例。"),
        ("details", "质押交易明细记录", "上市公司股东单笔质押公告明细。"),
        ("repo", "解质与质押式回购", "解除质押与回购交易历史记录。"),
    ]
    for p_type, p_name, p_desc in pledge_types:
        p_defs = [
            ParamDef("type", "质押类型", p_type, True, "当前子类型", [p_type]),
        ]
        if p_type in ("warning", "ratio", "details", "repo"):
            p_defs.append(ParamDef("code", "证券代码", "000001", False, "六位股票代码", bind_to="code"))
        p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=f"pledge_{p_type}",
                name=f"股权质押·{p_name}",
                category="股权质押数据中心",
                sub="pledge",
                view_param="type",
                view_val=p_type,
                description=p_desc,
                params=p_defs,
                tags=["股权质押", p_type],
            )
        )

    # --------------------------------------------------------------------------
    # 10. 数据中心·主力持仓 (sub=zlcc)
    # --------------------------------------------------------------------------
    zlcc_types = [
        ("list", "主力机构持股汇总", "基金、社保、QFII、券商等主力持股总览。"),
        ("detail", "个股主力持仓明细", "单只股票前十大流通股东及机构持股明细。"),
        ("date", "主力持股报告期列表", "支持查询的主力持仓季度报告期。"),
    ]
    for z_type, z_name, z_desc in zlcc_types:
        p_defs = [
            ParamDef("type", "持仓类型", z_type, True, "当前子类型", [z_type]),
        ]
        if z_type == "detail":
            p_defs.append(ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"))
        p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=f"zlcc_{z_type}",
                name=f"主力持仓·{z_name}",
                category="主力持仓数据中心",
                sub="zlcc",
                view_param="type",
                view_val=z_type,
                description=z_desc,
                params=p_defs,
                tags=["主力持仓", "机构持股", z_type],
            )
        )

    # --------------------------------------------------------------------------
    # 11. 数据中心·估值分析 (sub=gggz)
    # --------------------------------------------------------------------------
    gggz_types = [
        ("status", "个股估值状态", True, "当前市盈率、市净率与历史百分位估值评估。"),
        ("trend", "估值趋势变动", True, "个股估值中枢变动时序。"),
        ("scatter", "估值散点分布", True, "估值与盈利增长散点定位。"),
        ("scatter_situation", "估值散点明细", False, "估值散点的行业与个股分布明细。"),
        ("industry", "行业估值统计", False, "所属行业整体市盈率与市净率横向对比。"),
        ("industry_profile", "行业估值概况", False, "行业历史估值中位数与极端值。"),
        ("industry_rank", "行业估值排行", False, "行业市盈率高低排序。"),
        ("industry_rank5", "行业5日估值排行", False, "行业5日内估值抬升与回落排行。"),
        ("industry_detail", "行业估值明细表", False, "细分二级行业完整估值指标列表。"),
        ("undervalue", "低估值潜力股筛选", False, "低估值且业绩优良的个股清单。"),
        ("historical", "历史估值全景", True, "上市以来的完整估值走势与极端分位。"),
        ("quantile", "估值分位水平", True, "近1年、3年、5年、10年估值百分位。"),
        ("check", "估值条件校验", True, "检查证券估值指标是否处于合理区间。"),
    ]
    for g_type, g_name, req_code, g_desc in gggz_types:
        p_defs = [
            ParamDef("type", "估值类型", g_type, True, "当前子类型", [g_type]),
        ]
        if req_code:
            p_defs.append(ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"))
        p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=f"gggz_{g_type}",
                name=f"估值分析·{g_name}",
                category="估值分析数据中心",
                sub="gggz",
                view_param="type",
                view_val=g_type,
                description=g_desc,
                params=p_defs,
                tags=["估值", "PE", "PB", g_type],
            )
        )

    # --------------------------------------------------------------------------
    # 12. 数据中心·市场指标风向标 (sub=nxfxb)
    # --------------------------------------------------------------------------
    nxfxb_types = [
        ("market", "市场综合指标", "全市场多空情绪综合风向标。"),
        ("date", "指标日期序列", "市场指标历史记录有效日期列表。"),
        ("board", "板块风向标", "各行业板块多空情绪与资金合力指标。"),
        ("currency", "资金利率指标", "货币市场利率与流动性情绪监测。"),
        ("margin", "两融风向标", "融资盘做多意愿与做空对冲走势。"),
        ("turnover", "换手率风向标", "市场成交活跃度与换手热度。"),
        ("sumtval", "市场总市值序列", "A股总市值变动与宏观估值水平。"),
        ("avg_deal", "每笔平均成交", "户均成交额与单笔交易规模监测。"),
        ("fshis", "资金历史风向标", "长期资金偏好与主力博弈历史。"),
        ("theme", "热门主题投资", "市场热点主题的关注度与轮动。"),
        ("hot_theme", "高热度主题序列", "近阶段持续发酵的高热度主题。"),
        ("revalue", "估值重估走势", "低估板块估值修复与重估趋势。"),
        ("board_wheel", "板块轮动图谱", "板块轮动强度、领先与落后状态。"),
        ("sector_rotation", "行业轮动排行", "行业轮动涨幅与资金切换排行。"),
        ("mutual_stock_hold_type", "互联互通持股类别", "外资持仓按风格类别的配置结构。"),
        ("market_value", "市值结构统计", "不同市值梯队的股票数量与分布。"),
        ("stock_change", "市场涨跌分布统计", "全市场上涨、下跌与平盘家数统计。"),
        ("ipo_rise", "新股首日涨幅统计", "新股上市首日涨幅均值与中位数。"),
        ("ipo_rise_total", "新股累计表现统计", "新股上市后不同周期的累计涨幅。"),
        ("recent_lift", "近期解禁规模统计", "未来近阶段解禁压力统计。"),
        ("total_lift", "总量解禁走势", "长期全量解禁市值月度走势。"),
        ("investor", "投资者月度统计", "新增开户数与活跃投资者月度走势。"),
        ("futures_change", "期货跨期变动指标", "期货跨期价差与基差走势。"),
        ("index_picture", "指数晴雨图走势", "重要大盘指数晴雨表完整走势。"),
        ("index_picture_simple", "指数晴雨简图", "指数晴雨最新状态单行摘要。"),
    ]
    for n_type, n_name, n_desc in nxfxb_types:
        p_defs = [
            ParamDef("type", "指标类型", n_type, True, "当前子类型", [n_type]),
        ]
        if n_type in ("index_picture", "index_picture_simple"):
            p_defs.append(ParamDef("code", "指数代码", "000300.SH", False, "如000300.SH", bind_to="code"))
            p_defs.append(ParamDef("codeColumn", "代码列", "SECUCODE", False, "代码列名"))
        p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=f"nxfxb_{n_type}",
                name=f"市场指标·{n_name}",
                category="市场指标风向标",
                sub="nxfxb",
                view_param="type",
                view_val=n_type,
                description=n_desc,
                params=p_defs,
                tags=["市场指标", "风向标", n_type],
            )
        )

    # --------------------------------------------------------------------------
    # 13. 数据中心·专题报表与事件
    # --------------------------------------------------------------------------
    special_reports = [
        ("financial_report_latest", "最新业绩预告报告", "financial_report", "latest", "最新披露的上市公司季度与半年度财报摘要。"),
        ("financial_report_season", "财报季十年摘要", "financial_report", "season", "近十年各财报季度披露进度与历史统计。"),
        ("financial_report_board_summary", "财报板块汇总", "financial_report", "board_summary", "按板块汇总财报预告；需要填写页面同口径筛选表达式。"),
        ("economic_calendar", "财经日历大事件", "economic_calendar", "", "宏观经济数据发布、金融会议与重要事件日程。"),
        ("new_concept_boards", "新增概念板块及个股", "new_concept_boards", "", "市场最新挖掘建立的新概念题材及其关联股票。"),
        ("billboard_hot_money", "龙虎榜游资净买卖", "billboard_hot_money", "", "知名游资席位净买入额与涉及个股明细。"),
        ("ipo_statistics", "新股月度发行统计", "ipo_statistics", "", "各月份IPO发行家数、募资金额与平均市盈率。"),
        ("ipo_unlisted", "新股待上市日历", "ipo_unlisted", "", "已完成申购、待公布中签及待上市新股。"),
        ("ipo_today", "今日申购清单", "ipo_today", "", "当天可申购的新股、转债(无申购时可能返回空业务结果)。"),
        ("sector_rotation", "板块轮动指数榜", "sector_rotation", "", "板块轮动强度综合指标排行榜。"),
        ("board_pe_dividend", "板块估值与股息率", "board_pe_dividend", "", "各大行业板块最新市盈率与股息收益率横向对比。"),
        ("theme_hot", "热门题材关联证券", "theme_hot", "", "当前市场核心热门主题及其对应的成分证券。"),
        ("data_statistics", "市场涨跌家数统计", "data_statistics", "", "全市场上涨、下跌、平盘家数历史时序。"),
        ("billboard_brief", "龙虎榜市场摘要", "billboard_brief", "", "当日龙虎榜机构总买入、游资总买入及市场汇总。"),
        ("market_indicator_theme", "热门主题风向", "market_indicator_theme", "", "市场指标中的核心热门投资主题。"),
        ("market_indicator_date", "指标日期开闭市状态", "market_indicator_date", "", "市场指标对应的开闭市交易日状态。"),
        ("mutual_quota", "互联互通额度概览", "mutual_quota", "", "沪深港通每日额度余额及净流向。"),
        ("tfp_summary", "停复牌市场概况", "tfp", "summary", "当日停牌、复牌上市公司数量汇总。"),
        ("tfp_list", "停复牌详细清单", "tfp", "list", "停牌股票代码、名称、停牌原因与复牌时间。"),
        ("tfp_detail", "停复牌详情", "tfp", "detail", "指定日期的停牌与复牌详情数据。"),
        ("ggdq", "上市公司公告列表", "ggdq", "", "上市公司最新公告标题、类别与披露日期。"),
        ("fhsz_plan", "分红送转方案明细", "fhsz", "plan", "最新上市公司利润分配与送转预案。"),
        ("fhsz_date", "分红预计披露日期", "fhsz", "report_date", "分红方案披露日期安排。"),
        ("ipov2", "注册制新股上市表现", "ipov2", "", "注册制实施以来新股发行估值与上市涨幅表现。"),
        ("dchome_labels", "数据中心功能标签", "dchome", "labels", "数据中心全部业务功能栏目分类与标签目录。"),
        ("dchome_home", "数据中心首页核心数据", "dchome", "home", "数据中心首页推荐的核心数据与指标矩阵。"),
    ]
    for sp_id, sp_name, sp_sub, sp_type, sp_desc in special_reports:
        p_defs = []
        if sp_type:
            p_defs.append(ParamDef("type", "报表类型", sp_type, True, "当前子类型", [sp_type]))
        if sp_id in ("billboard_hot_money", "board_pe_dividend", "data_statistics", "billboard_brief", "mutual_quota", "tfp_summary", "tfp_list", "tfp_detail"):
            p_defs.append(ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"))
        if sp_id == "economic_calendar":
            p_defs.append(ParamDef("startDate", "起始日", "", False, "YYYYMMDD"))
            p_defs.append(ParamDef("endDate", "截止日", "", False, "YYYYMMDD"))
        if sp_id in ("ggdq", "fhsz_plan"):
            p_defs.append(ParamDef("code", "证券代码", "000001", False, "六位股票代码", bind_to="code"))
        if sp_id == "financial_report_board_summary":
            p_defs.append(ParamDef(
                "filter",
                "板块筛选",
                "",
                True,
                "需包含 REPORT_DATE、TYPECODE、PER_TYPE_CODE 等页面条件",
            ))
            p_defs.extend(p for p in _common_paging_params() if p.name != "filter")
        else:
            p_defs.extend(_common_paging_params())
        c_list.append(
            Capability(
                id=sp_id,
                name=f"专题·{sp_name}",
                category="专题报表与事件",
                sub=sp_sub,
                view_param="type" if sp_type else "",
                view_val=sp_type,
                description=sp_desc,
                params=p_defs,
                tags=["专题", sp_sub],
            )
        )

    # --------------------------------------------------------------------------
    # 14. 公共行情与K线 (sub=quote)
    # --------------------------------------------------------------------------
    quote_views = [
        ("stock", "单证券行情详情", "个股最新价、昨收、成交量、成交额与分时极值。"),
        ("stock_list", "分页股票行情列表", "全市场股票分批次列表行情，支持排序。"),
        ("sector_list", "板块行情列表", "行业与板块列表实时涨跌幅与成交统计。"),
        ("batch_quote", "多证券行情列表", "批量查询多只证券的实时行情数据。"),
        ("batch_quote_post", "多证券行情POST", "通过表单 POST 批量查询多只证券行情。"),
        ("trend", "分时走势序列", "单只证券日内分时价格与均价序列。"),
        ("updown_trend", "涨跌趋势序列", "盘中涨跌走势与波动时序。"),
        ("kline", "历史K线序列", "日K/周K/月K等历史K线蜡烛图数据。"),
        ("today_kline", "当日分钟K线", "当天开盘以来的分钟级K线明细。"),
        ("fund_flow_kline", "资金流K线序列", "个股主力资金历史时序K线。"),
        ("auction", "集合竞价摘要", "早盘9:15-9:25集合竞价撮合摘要。"),
        ("auction_trend", "集合竞价走势", "集合竞价匹配量与未匹配量动态变化。"),
        ("northbound_summary", "互联互通资金摘要", "北向资金实时额度与流入净值摘要。"),
        ("northbound_realtime", "互联互通实时资金", "互联互通分钟级资金流入曲线。"),
        ("northbound_block", "互联互通板块资金", "互联互通分市场/分板块实时数据。"),
    ]
    for q_view, q_name, q_desc in quote_views:
        p_defs = [
            ParamDef("view", "行情视图", q_view, True, "当前子类型", [q_view]),
        ]
        if q_view in ("stock", "trend", "updown_trend", "kline", "today_kline", "fund_flow_kline", "auction", "auction_trend"):
            p_defs.append(ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"))
            p_defs.append(ParamDef("secid", "完整标识", "", False, "如0.000001或1.600000"))
            p_defs.append(ParamDef("market", "市场提示", "", False, "sh/sz/bj/etf/fund/bond/option"))
        if q_view in ("batch_quote", "batch_quote_post"):
            p_defs.append(ParamDef("secids", "证券标识列表", "0.000001,1.600000,0.300059", True, "逗号分隔标识"))
            p_defs.append(ParamDef("fields", "返回字段", "f2,f3,f4,f5,f6,f7,f12,f14", False, "指定字段"))
        if q_view == "trend":
            p_defs.append(ParamDef("ndays", "天数", "1", False, "分时天数1~5"))
        if q_view == "kline":
            p_defs.append(ParamDef("lmt", "根数限制", "210", False, "获取K线根数"))
            p_defs.append(ParamDef("klt", "周期", "101", False, "101日K,102周K,103月K"))
            p_defs.append(ParamDef("fqt", "复权方式", "0", False, "0不复权,1前复权,2后复权"))
        if q_view in ("stock_list", "sector_list"):
            p_defs.append(ParamDef("pn", "页码", "1", False, "页码", bind_to="pageNumber"))
            p_defs.append(ParamDef("pz", "条数", "50", False, "条数", bind_to="pageSize"))
            p_defs.append(ParamDef("fields", "返回字段", "f2,f3,f4,f5,f6,f7,f12,f14", False, "指定字段"))
        c_list.append(
            Capability(
                id=f"quote_{q_view}",
                name=f"行情·{q_name}",
                category="公共行情与K线",
                sub="quote",
                view_param="view",
                view_val=q_view,
                method="POST" if q_view == "batch_quote_post" else "POST",
                description=q_desc,
                params=p_defs,
                tags=["行情", "K线", "分时", q_view],
            )
        )

    # --------------------------------------------------------------------------
    # 15. 资料与研报检索
    # --------------------------------------------------------------------------
    c_list.append(
        Capability(
            id="stock_profile_basic",
            name="个股资料·公司基本信息",
            category="资料与研报检索",
            sub="stock_profile",
            view_param="view",
            view_val="basic",
            description="上市公司公司概况、主营业务、所属行业及上市基础信息。",
            params=[
                ParamDef("view", "视图", "basic", True, "基本资料", ["basic"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageSize", "条数", "1", False, "返回条数", bind_to="pageSize"),
            ],
            tags=["资料", "F10"],
        )
    )
    c_list.append(
        Capability(
            id="stock_profile_financial",
            name="个股资料·财务主要指标",
            category="资料与研报检索",
            sub="stock_profile",
            view_param="view",
            view_val="financial",
            description="上市公司最新财务报告期、每股收益、每股净资产与营收表现。",
            params=[
                ParamDef("view", "视图", "financial", True, "财务指标", ["financial"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageSize", "条数", "1", False, "返回条数", bind_to="pageSize"),
            ],
            tags=["财务指标", "F10"],
        )
    )
    c_list.append(
        Capability(
            id="stock_profile_industry",
            name="个股资料·同业对比指标",
            category="资料与研报检索",
            sub="stock_profile",
            view_param="view",
            view_val="industry",
            description="上市公司与同行业竞争对手的核心指标横向对比。",
            params=[
                ParamDef("view", "视图", "industry", True, "同业对比", ["industry"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageSize", "条数", "1", False, "返回条数", bind_to="pageSize"),
            ],
            tags=["同业对比", "F10"],
        )
    )
    c_list.append(
        Capability(
            id="report_post_financial",
            name="白名单报表·财务POST",
            category="资料与研报检索",
            sub="report_post",
            view_param="report",
            view_val="financial",
            method="POST",
            description="白名单财务报表查询，支持表单与 JSON POST 模式。",
            params=[
                ParamDef("report", "公开报表别名", "financial", True, "白名单别名", ["financial"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageNumber", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "1", False, "条数", bind_to="pageSize"),
            ],
            tags=["报表POST", "财务"],
        )
    )
    c_list.append(
        Capability(
            id="report_post_basic",
            name="白名单报表·基本资料POST",
            category="资料与研报检索",
            sub="report_post",
            view_param="report",
            view_val="basic",
            method="POST",
            description="白名单基本资料报表查询。",
            params=[
                ParamDef("report", "公开报表别名", "basic", True, "白名单别名", ["basic"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageSize", "条数", "1", False, "条数", bind_to="pageSize"),
            ],
            tags=["报表POST", "基本资料"],
        )
    )
    c_list.append(
        Capability(
            id="report_post_industry",
            name="白名单报表·行业对比POST",
            category="资料与研报检索",
            sub="report_post",
            view_param="report",
            view_val="industry",
            method="POST",
            description="白名单行业对比报表查询。",
            params=[
                ParamDef("report", "公开报表别名", "industry", True, "白名单别名", ["industry"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageSize", "条数", "1", False, "条数", bind_to="pageSize"),
            ],
            tags=["报表POST", "行业对比"],
        )
    )
    c_list.append(
        Capability(
            id="security_search",
            name="证券代码与关键词检索",
            category="资料与研报检索",
            sub="security_search",
            description="支持股票名称、六位代码、拼音首字母进行证券检索。",
            params=[
                ParamDef("input", "搜索词", "平安银行", True, "名称/代码/拼音"),
                ParamDef("type", "证券类型", "1,2,3,4,25", False, "类型过滤集合"),
            ],
            tags=["搜索", "股票检索"],
        )
    )
    c_list.append(
        Capability(
            id="security_suggest",
            name="证券输入建议(联想)",
            category="资料与研报检索",
            sub="security_suggest",
            description="返回包含行情代码与 QuoteID 的候选项，适合输入联想。",
            params=[
                ParamDef("input", "输入词", "000001", True, "名称/代码/拼音"),
                ParamDef("count", "返回数量", "10", False, "建议数量"),
            ],
            tags=["联想", "搜索建议"],
        )
    )
    c_list.append(
        Capability(
            id="research_report_list",
            name="研究报告检索列表",
            category="资料与研报检索",
            sub="research_report",
            view_param="view",
            view_val="list",
            description="券商研究报告列表查询，支持按代码或时间范围筛选。",
            params=[
                ParamDef("view", "视图", "list", True, "列表模式", ["list"]),
                ParamDef("stock_list", "证券标识", "", False, "如0.000001或留空"),
                ParamDef("page_index", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("page_size", "条数", "20", False, "条数", bind_to="pageSize"),
                ParamDef("begin_time", "起始日期", "", False, "YYYY-MM-DD"),
                ParamDef("end_time", "截止日期", "", False, "YYYY-MM-DD"),
            ],
            tags=["研报", "研究报告"],
        )
    )
    c_list.append(
        Capability(
            id="research_report_detail",
            name="研究报告内容详情",
            category="资料与研报检索",
            sub="research_report",
            description="通过 reportId 获取单篇研究报告的正文与研究结论。",
            params=[
                ParamDef("reportId", "报告编号", "", True, "从列表中获取的报告ID"),
                ParamDef("code", "关联代码", "", False, "可选关联代码", bind_to="code"),
                ParamDef("pageNumber", "内容页", "1", False, "长文分页"),
            ],
            tags=["研报详情"],
        )
    )
    c_list.append(
        Capability(
            id="content_detail_article",
            name="正文详情·资讯文章",
            category="资料与研报检索",
            sub="content_detail",
            view_param="view",
            view_val="article",
            description="获取资讯文章详细正文文本与发布时间。",
            params=[
                ParamDef("view", "视图", "article", True, "文章正文", ["article"]),
                ParamDef("postid", "文章ID", "", True, "文章唯一编号"),
            ],
            tags=["文章正文"],
        )
    )
    c_list.append(
        Capability(
            id="content_detail_brief",
            name="正文详情·文章摘要",
            category="资料与研报检索",
            sub="content_detail",
            view_param="view",
            view_val="brief",
            description="获取文章的核心观点摘要与短评。",
            params=[
                ParamDef("view", "视图", "brief", True, "文章摘要", ["brief"]),
                ParamDef("postid", "文章ID", "", True, "文章唯一编号"),
            ],
            tags=["文章摘要"],
        )
    )
    c_list.append(
        Capability(
            id="content_detail_announcement",
            name="正文详情·公告正文",
            category="资料与研报检索",
            sub="content_detail",
            view_param="view",
            view_val="announcement",
            description="通过公告 infoCode 查询上市公司的正式公告全文。",
            params=[
                ParamDef("view", "视图", "announcement", True, "公告正文", ["announcement"]),
                ParamDef("infoCode", "公告编号", "", True, "公告唯一代码"),
                ParamDef("pageIndex", "内容页", "1", False, "分页"),
            ],
            tags=["公告正文"],
        )
    )
    c_list.append(
        Capability(
            id="content_detail_research",
            name="正文详情·研究内容",
            category="资料与研报检索",
            sub="content_detail",
            view_param="view",
            view_val="research",
            description="通过报告编号获取研究内容详情，与研究报告详情入口保持一致。",
            params=[
                ParamDef("view", "视图", "research", True, "研究内容", ["research"]),
                ParamDef("reportId", "报告编号", "", True, "从报告列表中取得的编号"),
                ParamDef("pageNumber", "内容页", "1", False, "长文分页", bind_to="pageNumber"),
            ],
            tags=["研报", "正文详情"],
        )
    )

    # --------------------------------------------------------------------------
    # 16. 辅助与兼容接口
    # --------------------------------------------------------------------------
    c_list.append(
        Capability(
            id="trade_calendar",
            name="交易日历序列",
            category="辅助与兼容接口",
            sub="trade_calendar",
            description="以指定锚定日期查询前后交易日数组序列。",
            params=[
                ParamDef("tdate", "锚定日期", "", False, "YYYYMMDD，省略为今天", bind_to="date"),
                ParamDef("delta", "偏移数量", "-20", False, "负数往前/正数往后(如-20)"),
                ParamDef("count", "数量别名", "", False, "若未填delta可用count"),
            ],
            tags=["交易日历", "交易日序列"],
        )
    )
    c_list.append(
        Capability(
            id="trade_day_status",
            name="交易日状态判定",
            category="辅助与兼容接口",
            sub="trade_day_status",
            description="查询指定日历日期是否开市交易以及下一交易日。",
            params=[
                ParamDef("date", "查询日期", "", False, "YYYYMMDD或YYYY-MM-DD", bind_to="date"),
            ],
            tags=["交易日状态"],
        )
    )
    c_list.append(
        Capability(
            id="main_force_build",
            name="主力建仓复合数据",
            category="辅助与兼容接口",
            sub="main_force_build",
            description="主力资金异动建仓复合结构，返回CHANGE_DATA数组。",
            params=[
                ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("pageSize", "条数", "50", False, "每页条数", bind_to="pageSize"),
            ],
            tags=["主力建仓"],
        )
    )
    c_list.append(
        Capability(
            id="f10_notice",
            name="个股公告资料[需参数]",
            category="辅助与兼容接口",
            sub="f10_notice",
            description="兼容入口：通过页面特定生成的 params 不透明载荷请求公告明细。",
            params=[
                ParamDef("params", "页面载荷", "", True, "必须提供页面生成的有效载荷"),
                ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
            ],
            is_compatible=True,
            tags=["公告明细", "兼容接口"],
        )
    )
    c_list.append(
        Capability(
            id="annual_report_dates",
            name="年度财报披露日程",
            category="辅助与兼容接口",
            sub="annual_report_dates",
            description="上市公司年报预计披露时间及变更历程。",
            params=[
                ParamDef("code", "证券代码", "000001", False, "六位股票代码", bind_to="code"),
                ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
            ],
            tags=["年报预约"],
        )
    )
    c_list.append(
        Capability(
            id="market_overview_change",
            name="市场总览·涨跌分布统计",
            category="辅助与兼容接口",
            sub="market_overview",
            view_param="view",
            view_val="change_statistics",
            description="各主要市场股票上涨、下跌与平盘家数统计。",
            params=[
                ParamDef("view", "视图", "change_statistics", True, "涨跌统计", ["change_statistics"]),
                ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
            ],
            tags=["市场总览", "涨跌家数"],
        )
    )
    c_list.append(
        Capability(
            id="market_overview_amount",
            name="市场总览·成交额趋势",
            category="辅助与兼容接口",
            sub="market_overview",
            view_param="view",
            view_val="intraday_amount",
            description="盘中各时点全市场累计成交金额变动趋势。",
            params=[
                ParamDef("view", "视图", "intraday_amount", True, "成交额趋势", ["intraday_amount"]),
                ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
            ],
            tags=["成交额趋势"],
        )
    )
    c_list.append(
        Capability(
            id="market_overview_bull_bear",
            name="市场总览·多空指标对象",
            category="辅助与兼容接口",
            sub="market_overview",
            view_param="view",
            view_val="bull_bear",
            description="市场总览中的多空指标对象与日期状态。",
            params=[
                ParamDef("view", "视图", "bull_bear", True, "多空指标", ["bull_bear"]),
                ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("filter", "高级筛选", "", False, "按服务支持的字段筛选"),
                ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
            ],
            tags=["市场总览", "多空指标"],
        )
    )
    c_list.append(
        Capability(
            id="hsgt_http_summary",
            name="沪深港通页面汇总[兼容]",
            category="辅助与兼容接口",
            sub="hsgt_http",
            view_param="view",
            view_val="summary",
            description="沪深港通页面级实时概览汇总。",
            params=[
                ParamDef("view", "视图", "summary", True, "页面汇总", ["summary"]),
                ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("market", "市场", "", False, "sh/sz"),
            ],
            is_compatible=True,
            tags=["互联互通页面"],
        )
    )
    c_list.append(
        Capability(
            id="hsgt_http_stock",
            name="沪深港通单证券明细[兼容]",
            category="辅助与兼容接口",
            sub="hsgt_http",
            view_param="view",
            view_val="stock_detail",
            description="单只证券在互联互通机制下的外资流入与持仓状态。",
            params=[
                ParamDef("view", "视图", "stock_detail", True, "个股明细", ["stock_detail"]),
                ParamDef("code", "证券代码", "000001", True, "六位代码", bind_to="code"),
            ],
            is_compatible=True,
            tags=["外资持股"],
        )
    )
    for h_view, h_name, h_desc in [
        ("date_tab", "可选日期列表", "沪深港通页面可选择的统计日期。"),
        ("index_chart", "指数资金图表", "沪深港通指数与资金序列图表数据。"),
        ("detail", "页面明细分页", "沪深港通页面明细分页兼容入口，可能返回空业务结果。"),
        ("ten_top_time", "前十时段摘要", "沪深港通前十活跃标的时段摘要。"),
    ]:
        h_params = [ParamDef("view", "视图", h_view, True, h_name, [h_view])]
        if h_view in ("detail",):
            h_params.extend([
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
                ParamDef("pageIndex", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("pageSize", "条数", "20", False, "条数", bind_to="pageSize"),
                ParamDef("sty", "字段样式", "", False, "页面兼容字段"),
            ])
        elif h_view == "ten_top_time":
            h_params.extend([
                ParamDef("date", "交易日", "", False, "YYYYMMDD", bind_to="date"),
                ParamDef("market", "市场", "", False, "页面市场筛选"),
            ])
        c_list.append(
            Capability(
                id=f"hsgt_http_{h_view}",
                name=f"沪深港通·{h_name}[兼容]",
                category="辅助与兼容接口",
                sub="hsgt_http",
                view_param="view",
                view_val=h_view,
                description=h_desc,
                params=h_params,
                is_compatible=True,
                tags=["互联互通页面", h_view],
            )
        )
    c_list.append(
        Capability(
            id="pledge_http_notice",
            name="股权质押公告列表[兼容]",
            category="辅助与兼容接口",
            sub="pledge_http",
            view_param="view",
            view_val="notice_list",
            description="最新股权质押公告列表页面数据。",
            params=[
                ParamDef("view", "视图", "notice_list", True, "公告列表", ["notice_list"]),
                ParamDef("pi", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("ps", "条数", "20", False, "条数", bind_to="pageSize"),
            ],
            is_compatible=True,
            tags=["质押公告"],
        )
    )
    c_list.append(
        Capability(
            id="pledge_http_chart",
            name="个股质押详情图表[兼容]",
            category="辅助与兼容接口",
            sub="pledge_http",
            view_param="view",
            view_val="pledge_chart",
            description="单只证券股权质押比例与风险走势图表数据。",
            params=[
                ParamDef("view", "视图", "pledge_chart", True, "详情图表", ["pledge_chart"]),
                ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"),
            ],
            is_compatible=True,
            tags=["质押图表"],
        )
    )
    for p_view, p_name, p_desc, needs_code, paged in [
        ("first_chart", "质押区间图", "质押比例区间图表数据。", False, False),
        ("second_chart", "主体类型图", "按质押主体类型汇总的图表数据。", False, False),
        ("third_chart", "风险区间图", "质押风险区间图表数据。", False, False),
        ("shareholder_amount", "质押股东数量", "指定证券的质押股东数量汇总。", True, False),
        ("shareholder_detail", "质押股东明细", "指定证券的质押股东明细分页。", True, True),
        ("shareholder_group", "质押股东分组", "指定证券的质押股东分组分页。", True, True),
        ("ranking_industry", "行业质押排行", "行业平均质押比例排行。", False, True),
        ("ranking_rate", "个股质押比例排行", "个股质押比例排行。", False, True),
    ]:
        p_params = [ParamDef("view", "视图", p_view, True, p_name, [p_view])]
        if needs_code:
            p_params.append(ParamDef("code", "证券代码", "000001", True, "六位股票代码", bind_to="code"))
        if paged:
            p_params.extend([
                ParamDef("pi", "页码", "1", False, "页码", bind_to="pageNumber"),
                ParamDef("ps", "条数", "20", False, "条数", bind_to="pageSize"),
            ])
        if p_view in ("ranking_industry", "ranking_rate"):
            p_params.extend([
                ParamDef("orderField", "排序字段", "", False, "留空使用页面默认排序"),
                ParamDef("orderType", "排序方向", "-1", False, "-1降序 / 1升序"),
            ])
        c_list.append(
            Capability(
                id=f"pledge_http_{p_view}",
                name=f"股权质押·{p_name}[兼容]",
                category="辅助与兼容接口",
                sub="pledge_http",
                view_param="view",
                view_val=p_view,
                description=p_desc,
                params=p_params,
                is_compatible=True,
                tags=["股权质押页面", p_view],
            )
        )

    # --------------------------------------------------------------------------
    # 17. 自定义与通用接口
    # --------------------------------------------------------------------------
    c_list.append(
        Capability(
            id="custom_query",
            name="通用自由查询 (Custom Query)",
            category="自定义与通用接口",
            sub="",
            description="用户可自由指定 sub、type/view 与任意键值参数的高级调试通道。",
            params=[
                ParamDef("sub", "业务别名(sub)", "guchi", True, "如guchi, rzrq, quote等"),
                ParamDef("type", "子类型(type)", "", False, "如适用"),
                ParamDef("view", "视图(view)", "", False, "如适用"),
                ParamDef("code", "证券代码", "", False, "如适用", bind_to="code"),
                ParamDef("date", "日期参数", "", False, "如适用", bind_to="date"),
                ParamDef("extra_params", "扩展参数", "", False, "格式: k1=v1&k2=v2"),
            ],
            tags=["通用", "自定义"],
        )
    )

    return c_list


CAPABILITIES = build_capabilities_registry()
CAPABILITY_MAP: Dict[str, Capability] = {c.id: c for c in CAPABILITIES}


# ==============================================================================
# 后台异步 HTTP 请求引擎
# ==============================================================================
@dataclass
class HttpRequestTask:
    task_id: int
    cap_id: str
    url: str
    method: str
    headers: Dict[str, str]
    body: Optional[bytes]
    timeout: float
    description: str


@dataclass
class HttpResponseResult:
    task_id: int
    cap_id: str
    status_code: int
    elapsed_ms: float
    raw_body: str
    json_data: Any
    headers: Dict[str, str]
    error: str = ""
    is_cancelled: bool = False


class NetworkEngine:
    """后台网络请求引擎，负责多线程任务派发、超时控制与任务取消。"""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="D2Worker")
        self._current_task_id = 0
        self._lock = threading.Lock()
        self._active_task_ids: Set[int] = set()
        self._closed = False

    def submit_request(
        self,
        cap_id: str,
        url: str,
        method: str,
        params: Dict[str, str],
        timeout: float,
        description: str,
        on_complete: Callable[[HttpResponseResult], None],
    ) -> int:
        with self._lock:
            if self._closed:
                return -1
            self._current_task_id += 1
            task_id = self._current_task_id
            self._active_task_ids.add(task_id)

        # 区分 GET 和 POST 参数组织
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "D2Workbench/1.0",
        }
        body: Optional[bytes] = None
        target_url = url

        clean_params = {k: str(v) for k, v in params.items() if v is not None and str(v).strip() != ""}

        if method.upper() == "GET":
            if clean_params:
                query_str = urlencode(clean_params)
                target_url = f"{url}?{query_str}" if "?" not in url else f"{url}&{query_str}"
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
            body = urlencode(clean_params).encode("utf-8")

        task = HttpRequestTask(
            task_id=task_id,
            cap_id=cap_id,
            url=target_url,
            method=method.upper(),
            headers=headers,
            body=body,
            timeout=timeout,
            description=description,
        )

        def worker():
            res = self._execute_task(task)
            with self._lock:
                is_active = task.task_id in self._active_task_ids
                self._active_task_ids.discard(task.task_id)
            if not is_active:
                res.is_cancelled = True
            on_complete(res)

        self._executor.submit(worker)
        return task_id

    def cancel_task(self, task_id: int):
        with self._lock:
            self._active_task_ids.discard(task_id)

    def cancel_all(self):
        with self._lock:
            self._active_task_ids.clear()

    def shutdown(self):
        with self._lock:
            self._closed = True
            self._active_task_ids.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _execute_task(self, task: HttpRequestTask) -> HttpResponseResult:
        start_time = time.perf_counter()
        req = Request(task.url, data=task.body, headers=task.headers, method=task.method)

        status_code = 0
        raw_body = ""
        json_data = None
        resp_headers: Dict[str, str] = {}
        error_msg = ""

        try:
            with urlopen(req, timeout=task.timeout) as resp:
                status_code = resp.status
                resp_headers = dict(resp.headers)
                content = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    raw_body = content.decode(charset, errors="replace")
                except Exception:
                    raw_body = content.decode("utf-8", errors="replace")

                try:
                    json_data = json.loads(raw_body)
                except Exception as json_err:
                    error_msg = f"响应解析失败 (非有效 JSON): {json_err}"

        except HTTPError as http_err:
            status_code = http_err.code
            resp_headers = dict(http_err.headers)
            try:
                raw_body = http_err.read().decode("utf-8", errors="replace")
                json_data = json.loads(raw_body)
            except Exception:
                pass
            error_msg = f"HTTP 错误 {http_err.code}: {http_err.reason}"
        except URLError as url_err:
            error_msg = f"网络连接失败: {url_err.reason}"
        except TimeoutError:
            error_msg = f"请求超时 (已超过 {task.timeout} 秒)"
        except Exception as generic_err:
            error_msg = f"请求异常: {generic_err}"

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return HttpResponseResult(
            task_id=task.task_id,
            cap_id=task.cap_id,
            status_code=status_code,
            elapsed_ms=elapsed_ms,
            raw_body=raw_body,
            json_data=json_data,
            headers=resp_headers,
            error=error_msg,
        )


# ==============================================================================
# 智能响应结果解析与表格展开
# ==============================================================================
def parse_d2_response_data(json_obj: Any) -> Tuple[bool, str, str, List[Dict[str, Any]], Dict[str, Any]]:
    """解析 D2 各种常见外壳包装，提取记录列表与业务状态。

    返回: (is_success, status_badge_text, shape_text, row_dicts, summary_info)
    """
    if json_obj is None:
        return False, "无有效数据", "空响应", [], {}

    is_success = True
    status_text = "成功"
    shape_text = ""
    rows: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {}

    # 1. 顶层对象包含标准业务字段
    if isinstance(json_obj, dict):
        # 提取常见业务码
        if "success" in json_obj:
            s_val = json_obj["success"]
            if s_val is False or str(s_val).lower() == "false" or s_val == 0:
                is_success = False
            msg = json_obj.get("message") or json_obj.get("msg") or json_obj.get("error") or ""
            status_text = f"success={s_val} {msg}".strip()

        if "errid" in json_obj:
            errid = json_obj["errid"]
            errmsg = json_obj.get("errmsg") or ""
            if errid != 0:
                is_success = False
            status_text = f"errid={errid} {errmsg}".strip()

        if "code" in json_obj:
            code = json_obj["code"]
            # D2 中 0 和 10000 均为合法成功码
            if code not in (0, 10000, "0", "10000"):
                is_success = False
            msg = json_obj.get("message") or json_obj.get("msg") or ""
            status_text = f"code={code} {msg}".strip()

        if "Status" in json_obj:
            stat = json_obj["Status"]
            if stat not in (0, "0"):
                is_success = False
            msg = json_obj.get("Message") or ""
            status_text = f"Status={stat} {msg}".strip()

        # 尝试定位实际承载数据的数据集
        candidate_data = None
        if "result" in json_obj and isinstance(json_obj["result"], dict):
            r_obj = json_obj["result"]
            summary["pages"] = r_obj.get("pages")
            summary["count"] = r_obj.get("count")
            summary["total"] = r_obj.get("total")
            candidate_data = r_obj.get("data") or r_obj.get("items") or r_obj.get("rows")
            if candidate_data is None and isinstance(r_obj, dict):
                # 可能是复合对象
                if "CHANGE_DATA" in r_obj:
                    candidate_data = r_obj["CHANGE_DATA"]
                else:
                    # 单对象摘要
                    candidate_data = [r_obj]

        elif "data" in json_obj:
            d_val = json_obj["data"]
            if isinstance(d_val, dict):
                # 如 data.diff 或 data.klines 或 data.tradedates
                if "diff" in d_val and isinstance(d_val["diff"], list):
                    candidate_data = d_val["diff"]
                elif "klines" in d_val and isinstance(d_val["klines"], list):
                    # 字符串数组转字典
                    candidate_data = [{"kline_raw": line} for line in d_val["klines"]]
                elif "tradedates" in d_val and isinstance(d_val["tradedates"], list):
                    candidate_data = [{"trade_date": d} for d in d_val["tradedates"]]
                elif "list" in d_val and isinstance(d_val["list"], list):
                    candidate_data = d_val["list"]
                else:
                    # 单个对象展开
                    candidate_data = [d_val]
            elif isinstance(d_val, list):
                candidate_data = d_val

        elif "Result" in json_obj:
            res_val = json_obj["Result"]
            if isinstance(res_val, list):
                candidate_data = res_val
            elif isinstance(res_val, dict):
                # 寻找内部列表，如 List / Data / Items
                inner_list = None
                for k, v in res_val.items():
                    if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                        inner_list = v
                        break
                candidate_data = inner_list if inner_list is not None else [res_val]

        elif "QuotationCodeTable" in json_obj and isinstance(json_obj["QuotationCodeTable"], dict):
            candidate_data = json_obj["QuotationCodeTable"].get("Data")

        elif "rows" in json_obj and isinstance(json_obj["rows"], list):
            candidate_data = json_obj["rows"]

        # 处理提取出的 candidate_data
        if isinstance(candidate_data, list):
            shape_text = f"列表 (共 {len(candidate_data)} 条)"
            for item in candidate_data:
                if isinstance(item, dict):
                    rows.append(item)
                else:
                    rows.append({"值": str(item)})
        elif isinstance(candidate_data, dict):
            shape_text = "单条数据对象"
            rows.append(candidate_data)
        else:
            # 顶层对象本身就是一个扁平字典
            shape_text = "键值属性集合"
            # 展平为键值对表格展示
            for k, v in json_obj.items():
                if not isinstance(v, (dict, list)):
                    rows.append({"属性字段": k, "字段中文": humanize_field_name(k), "数值内容": str(v)})

    elif isinstance(json_obj, list):
        shape_text = f"直接数组 (共 {len(json_obj)} 项)"
        for item in json_obj:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append({"数值": str(item)})

    return is_success, status_text, shape_text, rows, summary


# ==============================================================================
# GUI 核心应用主窗口
# ==============================================================================
class D2WorkbenchApp:
    def __init__(self, root: tk.Tk, args: argparse.Namespace):
        self.root = root
        self.args = args

        self.root.title("D2 线路能力工作台 — 本地数据查询与业务分析")
        self.root.geometry("1380x860")
        self.root.minsize(1080, 680)
        self.root.configure(bg=BG)

        # 内部状态变量
        self.network = NetworkEngine(max_workers=5)
        self.current_cap: Optional[Capability] = None
        self.active_task_id: int = 0
        self.current_rows: List[Dict[str, Any]] = []
        self.current_raw_json: str = ""
        self.current_summary: Dict[str, Any] = {}
        self.table_sort_column: Optional[str] = None
        self.table_sort_reverse: bool = False

        # 响应通知队列 (线程安全)
        self.resp_queue: queue.Queue[HttpResponseResult] = queue.Queue()

        # 初始化变量
        self.var_base_url = tk.StringVar(value=args.base_url)
        self.var_path = tk.StringVar(value=args.path)
        self.var_code = tk.StringVar(value=args.code)
        self.var_date = tk.StringVar(value=args.date)
        self.var_page_num = tk.StringVar(value="1")
        self.var_page_size = tk.StringVar(value="50")
        self.var_method = tk.StringVar(value="POST")
        self.var_privacy = tk.BooleanVar(value=False)
        self.var_search = tk.StringVar()
        self.var_status_indicator = tk.StringVar(value="就绪")
        self.var_latency = tk.StringVar(value="")

        # 动态参数编辑字段映射
        self.param_widgets: Dict[str, Tuple[ParamDef, tk.Widget, tk.StringVar]] = {}

        self._setup_styles()
        self._build_layout()
        self._populate_catalog()

        # 顶栏公共参数变化时立即刷新请求预览，并同步当前能力表单中的绑定字段。
        for common_var in (self.var_base_url, self.var_path, self.var_method):
            common_var.trace_add("write", lambda *_: self._update_request_preview())
        for bind_to, common_var in (
            ("code", self.var_code),
            ("date", self.var_date),
            ("pageNumber", self.var_page_num),
            ("pageSize", self.var_page_size),
        ):
            common_var.trace_add(
                "write",
                lambda *_args, key=bind_to, value_var=common_var:
                self._on_common_param_change(key, value_var.get()),
            )

        # 窗口关闭监听
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 启动队列轮询
        self.root.after(50, self._check_response_queue)

        # 默认选中第一个常用股池能力
        if CAPABILITIES:
            self.select_capability(CAPABILITIES[0].id)

    # --------------------------------------------------------------------------
    # 样式配置
    # --------------------------------------------------------------------------
    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=BG, foreground=TEXT, font=FONT_CN)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Top.TFrame", background=TOP)

        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT_CN)
        style.configure("Muted.TLabel", foreground=MUTED, font=FONT_SMALL)
        style.configure("Dim.TLabel", foreground=DIM, font=FONT_TINY)
        style.configure("Header.TLabel", foreground=WHITE, font=FONT_TITLE)
        style.configure("Big.TLabel", foreground=BLUE, font=FONT_BIG)

        # 按钮样式
        style.configure("TButton", background=PANEL_ALT, foreground=TEXT, borderwidth=1, focuscolor=BORDER, font=FONT_CN)
        style.map("TButton", background=[("active", BORDER), ("pressed", INPUT)])

        style.configure("Accent.TButton", background="#1a4675", foreground=WHITE, font=FONT_TITLE, borderwidth=1)
        style.map("Accent.TButton", background=[("active", "#2563eb"), ("pressed", "#1d4ed8")])

        style.configure("Run.TButton", background="#15803d", foreground=WHITE, font=FONT_TITLE, borderwidth=1)
        style.map("Run.TButton", background=[("active", "#16a34a"), ("pressed", "#14532d")])

        # 树状列表与表格
        style.configure(
            "Treeview",
            background=PANEL,
            foreground=TEXT,
            fieldbackground=PANEL,
            borderwidth=0,
            font=FONT,
            rowheight=24,
        )
        style.map("Treeview", background=[("selected", "#1e3a5f")], foreground=[("selected", WHITE)])

        style.configure(
            "Treeview.Heading",
            background=TOP,
            foreground=CYAN,
            font=FONT_CN,
            borderwidth=1,
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", PANEL_ALT)])

        # 输入控件与选项卡
        style.configure("TEntry", fieldbackground=INPUT, foreground=WHITE, insertcolor=WHITE)
        style.configure("TCombobox", fieldbackground=INPUT, foreground=WHITE, selectbackground=INPUT, selectforeground=WHITE)
        style.configure("TCheckbutton", background=TOP, foreground=TEXT, font=FONT_CN)
        style.map("TCheckbutton", background=[("active", TOP)])

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=[12, 5], font=FONT_CN)
        style.map("TNotebook.Tab", background=[("selected", PANEL_ALT)], foreground=[("selected", WHITE)])

        style.configure("TPanedwindow", background=BORDER)

    # --------------------------------------------------------------------------
    # 界面整体布局构建
    # --------------------------------------------------------------------------
    def _build_layout(self):
        # 1. 顶部控制栏
        self._build_top_bar()

        # 2. 中下部主体区域 (左侧目录，右侧工作区)
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=BORDER, bd=1, sashwidth=5, sashrelief=tk.FLAT)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # 左侧面板：能力目录
        left_frame = tk.Frame(main_pane, bg=PANEL, width=320)
        left_frame.pack_propagate(False)
        self._build_catalog_panel(left_frame)
        main_pane.add(left_frame, minsize=260)

        # 右侧面板：请求配置 + 结果工作区 (纵向切分)
        right_pane = tk.PanedWindow(main_pane, orient=tk.VERTICAL, bg=BORDER, bd=1, sashwidth=5, sashrelief=tk.FLAT)
        main_pane.add(right_pane, minsize=600)

        # 上部：请求编辑器
        editor_frame = tk.Frame(right_pane, bg=PANEL, height=270)
        editor_frame.pack_propagate(False)
        self._build_editor_panel(editor_frame)
        right_pane.add(editor_frame, minsize=200)

        # 下部：结果展示工作区
        workspace_frame = tk.Frame(right_pane, bg=BG)
        self._build_workspace_panel(workspace_frame)
        right_pane.add(workspace_frame, minsize=350)

    # --------------------------------------------------------------------------
    # 顶栏构建
    # --------------------------------------------------------------------------
    def _build_top_bar(self):
        top = tk.Frame(self.root, bg=TOP, height=52, bd=0)
        top.pack(fill=tk.X, side=tk.TOP)

        # 品牌中性标志
        lbl_badge = tk.Label(top, text="D2 线路工作台", bg="#1e3a8a", fg=WHITE, font=FONT_TITLE, padx=10, pady=4)
        lbl_badge.pack(side=tk.LEFT, padx=(10, 10), pady=8)

        # 首页总览按钮
        btn_home = tk.Button(
            top,
            text="🏠 能力总览",
            bg=PANEL_ALT,
            fg=CYAN,
            font=FONT_CN,
            activebackground=BORDER,
            activeforeground=WHITE,
            bd=0,
            padx=8,
            pady=3,
            command=self.show_overview_dashboard,
        )
        btn_home.pack(side=tk.LEFT, padx=(0, 15), pady=8)

        # HTTP 基址
        tk.Label(top, text="基址:", bg=TOP, fg=MUTED, font=FONT_SMALL).pack(side=tk.LEFT, padx=(2, 2))
        ent_base = tk.Entry(top, textvariable=self.var_base_url, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT, width=22)
        ent_base.pack(side=tk.LEFT, padx=(0, 8), pady=8)

        # 路径
        tk.Label(top, text="路径:", bg=TOP, fg=MUTED, font=FONT_SMALL).pack(side=tk.LEFT, padx=(2, 2))
        ent_path = tk.Entry(top, textvariable=self.var_path, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT, width=10)
        ent_path.pack(side=tk.LEFT, padx=(0, 8), pady=8)

        # 常用快速参数
        tk.Label(top, text="代码:", bg=TOP, fg=MUTED, font=FONT_SMALL).pack(side=tk.LEFT, padx=(4, 2))
        ent_code = tk.Entry(top, textvariable=self.var_code, bg=INPUT, fg=GOLD, insertbackground=WHITE, font=FONT, width=8)
        ent_code.pack(side=tk.LEFT, padx=(0, 6), pady=8)

        tk.Label(top, text="日期:", bg=TOP, fg=MUTED, font=FONT_SMALL).pack(side=tk.LEFT, padx=(4, 2))
        ent_date = tk.Entry(top, textvariable=self.var_date, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT, width=10)
        ent_date.pack(side=tk.LEFT, padx=(0, 6), pady=8)

        tk.Label(top, text="页/条:", bg=TOP, fg=MUTED, font=FONT_SMALL).pack(side=tk.LEFT, padx=(4, 2))
        ent_p = tk.Entry(top, textvariable=self.var_page_num, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT, width=3)
        ent_p.pack(side=tk.LEFT, padx=(0, 2), pady=8)
        ent_s = tk.Entry(top, textvariable=self.var_page_size, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT, width=4)
        ent_s.pack(side=tk.LEFT, padx=(0, 10), pady=8)

        # 方法切换
        cbo_method = ttk.Combobox(top, textvariable=self.var_method, values=["POST", "GET"], width=5, state="readonly")
        cbo_method.pack(side=tk.LEFT, padx=(0, 10), pady=8)

        # 发送按钮
        btn_send = tk.Button(
            top,
            text="⚡ 发送请求",
            bg="#15803d",
            fg=WHITE,
            font=FONT_TITLE,
            activebackground="#16a34a",
            activeforeground=WHITE,
            bd=0,
            padx=14,
            pady=4,
            cursor="hand2",
            command=self.execute_current_capability,
        )
        btn_send.pack(side=tk.LEFT, padx=(0, 15), pady=8)

        # 隐私显示开关
        chk_privacy = ttk.Checkbutton(
            top,
            text="🔒 隐私模式 (掩码证券名称)",
            variable=self.var_privacy,
            command=self.on_toggle_privacy,
        )
        chk_privacy.pack(side=tk.LEFT, padx=(0, 15), pady=8)

        # 右侧状态信息
        lbl_status = tk.Label(top, textvariable=self.var_status_indicator, bg=TOP, fg=GREEN, font=FONT_CN)
        lbl_status.pack(side=tk.RIGHT, padx=(5, 12))

        lbl_latency = tk.Label(top, textvariable=self.var_latency, bg=TOP, fg=MUTED, font=FONT_TINY)
        lbl_latency.pack(side=tk.RIGHT, padx=(5, 5))

    # --------------------------------------------------------------------------
    # 左侧能力目录面板
    # --------------------------------------------------------------------------
    def _build_catalog_panel(self, parent: tk.Frame):
        # 搜索输入框
        search_box = tk.Frame(parent, bg=PANEL, height=40)
        search_box.pack(fill=tk.X, padx=8, pady=(8, 4))

        tk.Label(search_box, text="🔍", bg=PANEL, fg=MUTED, font=FONT_CN).pack(side=tk.LEFT, padx=(2, 4))
        ent_search = tk.Entry(search_box, textvariable=self.var_search, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT)
        ent_search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.var_search.trace_add("write", lambda *_: self._filter_catalog())

        btn_clear = tk.Button(
            search_box,
            text="✕",
            bg=PANEL,
            fg=MUTED,
            bd=0,
            activebackground=PANEL_ALT,
            activeforeground=WHITE,
            command=lambda: self.var_search.set(""),
        )
        btn_clear.pack(side=tk.RIGHT)

        # 分类与能力目录树状控件
        tree_frame = tk.Frame(parent, bg=PANEL)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        self.catalog_tree = ttk.Treeview(
            tree_frame,
            columns=("type_desc",),
            show="tree",
            selectmode="browse",
            yscrollcommand=tree_scroll_y.set,
        )
        tree_scroll_y.config(command=self.catalog_tree.yview)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.catalog_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.catalog_tree.bind("<<TreeviewSelect>>", self._on_catalog_select)

        # 底部状态：总能力数量
        lbl_count = tk.Label(parent, text=f"已接入能力: {len(CAPABILITIES)} 项 (按分类聚合)", bg=PANEL, fg=DIM, font=FONT_TINY)
        lbl_count.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=4)

    # --------------------------------------------------------------------------
    # 中间请求编辑器面板
    # --------------------------------------------------------------------------
    def _build_editor_panel(self, parent: tk.Frame):
        # 头部说明区
        header_bar = tk.Frame(parent, bg=PANEL_ALT, height=36)
        header_bar.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.lbl_cap_title = tk.Label(header_bar, text="请选择左侧能力", bg=PANEL_ALT, fg=CYAN, font=FONT_TITLE)
        self.lbl_cap_title.pack(side=tk.LEFT, padx=8, pady=4)

        self.lbl_cap_route = tk.Label(header_bar, text="", bg=PANEL_ALT, fg=GOLD, font=FONT_SMALL)
        self.lbl_cap_route.pack(side=tk.LEFT, padx=10, pady=4)

        btn_fill_defaults = tk.Button(
            header_bar,
            text="套用默认",
            bg=INPUT,
            fg=TEXT,
            font=FONT_SMALL,
            bd=0,
            padx=8,
            pady=2,
            command=self._apply_default_params,
        )
        btn_fill_defaults.pack(side=tk.RIGHT, padx=6, pady=4)

        btn_clear_opt = tk.Button(
            header_bar,
            text="清空可选",
            bg=INPUT,
            fg=MUTED,
            font=FONT_SMALL,
            bd=0,
            padx=8,
            pady=2,
            command=self._clear_optional_params,
        )
        btn_clear_opt.pack(side=tk.RIGHT, padx=4, pady=4)

        # 简介文本
        self.lbl_cap_desc = tk.Label(parent, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, anchor="w", justify=tk.LEFT)
        self.lbl_cap_desc.pack(fill=tk.X, padx=12, pady=(0, 4))

        # 参数网格滚动区域
        canvas_container = tk.Frame(parent, bg=PANEL)
        canvas_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)

        self.param_canvas = tk.Canvas(canvas_container, bg=PANEL, highlightthickness=0)
        param_scroll_y = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL, command=self.param_canvas.yview)
        self.param_grid_frame = tk.Frame(self.param_canvas, bg=PANEL)

        self.param_grid_frame.bind(
            "<Configure>",
            lambda e: self.param_canvas.configure(scrollregion=self.param_canvas.bbox("all")),
        )
        self.param_canvas.create_window((0, 0), window=self.param_grid_frame, anchor="nw")
        self.param_canvas.configure(yscrollcommand=param_scroll_y.set)

        param_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.param_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 底部请求预览行
        preview_bar = tk.Frame(parent, bg=INPUT, height=28)
        preview_bar.pack(fill=tk.X, padx=8, pady=4)

        tk.Label(preview_bar, text="预览:", bg=INPUT, fg=DIM, font=FONT_TINY).pack(side=tk.LEFT, padx=(6, 2))
        self.lbl_preview_url = tk.Label(preview_bar, text="", bg=INPUT, fg=WHITE, font=FONT_TINY, anchor="w")
        self.lbl_preview_url.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        btn_copy_url = tk.Button(
            preview_bar,
            text="复制请求",
            bg=PANEL_ALT,
            fg=CYAN,
            font=FONT_TINY,
            bd=0,
            padx=6,
            command=self._copy_request_preview,
        )
        btn_copy_url.pack(side=tk.RIGHT, padx=4, pady=2)

    # --------------------------------------------------------------------------
    # 下方工作区面板 (卡片概览 + 表格 + 原始 JSON + 日志)
    # --------------------------------------------------------------------------
    def _build_workspace_panel(self, parent: tk.Frame):
        # 概览卡片栏
        cards_bar = tk.Frame(parent, bg=BG, height=36)
        cards_bar.pack(fill=tk.X, padx=8, pady=(4, 4))

        self.card_status = self._create_info_card(cards_bar, "业务状态", "就绪", CYAN)
        self.card_latency = self._create_info_card(cards_bar, "网络耗时", "-- ms", GREEN)
        self.card_count = self._create_info_card(cards_bar, "解析记录数", "0 行", GOLD)
        self.card_shape = self._create_info_card(cards_bar, "数据形态", "空", PURPLE)

        # 结果标签页
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        # 标签页 1: 动态数据表格
        table_tab = tk.Frame(self.notebook, bg=PANEL)
        self.notebook.add(table_tab, text=" 📊 数据表格视图 ")
        self._build_table_tab(table_tab)

        # 标签页 2: 原始 JSON
        json_tab = tk.Frame(self.notebook, bg=PANEL)
        self.notebook.add(json_tab, text=" 📜 原始 JSON 响应 ")
        self._build_json_tab(json_tab)

        # 标签页 3: 请求日志与调试
        log_tab = tk.Frame(self.notebook, bg=PANEL)
        self.notebook.add(log_tab, text=" 🩺 请求日志与诊断 ")
        self._build_log_tab(log_tab)

    def _create_info_card(self, parent: tk.Frame, title: str, init_val: str, color: str) -> tk.Label:
        card = tk.Frame(parent, bg=PANEL, padx=8, pady=2, bd=1, relief=tk.SOLID)
        card.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(card, text=title, bg=PANEL, fg=MUTED, font=FONT_TINY).pack(anchor="w")
        val_lbl = tk.Label(card, text=init_val, bg=PANEL, fg=color, font=FONT_SECTION)
        val_lbl.pack(anchor="w")
        return val_lbl

    def _build_table_tab(self, parent: tk.Frame):
        # 快捷工具栏
        tb_bar = tk.Frame(parent, bg=PANEL, height=28)
        tb_bar.pack(fill=tk.X, padx=4, pady=2)

        self.lbl_table_tip = tk.Label(tb_bar, text="双击单元格或右键复制内容 | 表头可点击升降排序", bg=PANEL, fg=DIM, font=FONT_TINY)
        self.lbl_table_tip.pack(side=tk.LEFT, padx=6)

        btn_copy_table = tk.Button(
            tb_bar,
            text="复制全表 (TSV)",
            bg=INPUT,
            fg=TEXT,
            font=FONT_TINY,
            bd=0,
            padx=8,
            command=self._copy_entire_table_tsv,
        )
        btn_copy_table.pack(side=tk.RIGHT, padx=4)

        # 表格控件与滚动条
        table_container = tk.Frame(parent, bg=PANEL)
        table_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        scroll_y = ttk.Scrollbar(table_container, orient=tk.VERTICAL)
        scroll_x = ttk.Scrollbar(table_container, orient=tk.HORIZONTAL)

        self.tree_data = ttk.Treeview(
            table_container,
            show="headings",
            selectmode="extended",
            yscrollcommand=scroll_y.set,
            xscrollcommand=scroll_x.set,
        )

        scroll_y.config(command=self.tree_data.yview)
        scroll_x.config(command=self.tree_data.xview)

        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_data.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree_data.bind("<Double-1>", self._on_tree_cell_double_click)
        self.tree_data.bind("<Button-3>", self._on_tree_context_menu)

        # 右键快捷菜单
        self.table_menu = tk.Menu(self.root, tearoff=0, bg=PANEL_ALT, fg=TEXT, activebackground="#1e3a8a", activeforeground=WHITE)
        self.table_menu.add_command(label="复制当前单元格", command=self._copy_selected_cell)
        self.table_menu.add_command(label="复制选中整行 (TSV)", command=self._copy_selected_rows_tsv)
        self.table_menu.add_separator()
        self.table_menu.add_command(label="复制全表 (TSV)", command=self._copy_entire_table_tsv)

    def _build_json_tab(self, parent: tk.Frame):
        btn_bar = tk.Frame(parent, bg=PANEL, height=28)
        btn_bar.pack(fill=tk.X, padx=4, pady=2)

        btn_copy_json = tk.Button(
            btn_bar,
            text="复制 JSON 内容",
            bg=INPUT,
            fg=CYAN,
            font=FONT_TINY,
            bd=0,
            padx=8,
            pady=2,
            command=self._copy_json_content,
        )
        btn_copy_json.pack(side=tk.RIGHT, padx=4)

        text_frame = tk.Frame(parent, bg=PANEL)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        scroll_y = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        self.txt_json = tk.Text(
            text_frame,
            bg=INPUT,
            fg=WHITE,
            insertbackground=WHITE,
            font=FONT,
            wrap=tk.NONE,
            bd=0,
            yscrollcommand=scroll_y.set,
        )
        scroll_y.config(command=self.txt_json.yview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_json.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_log_tab(self, parent: tk.Frame):
        log_frame = tk.Frame(parent, bg=PANEL)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        scroll_y = ttk.Scrollbar(log_frame, orient=tk.VERTICAL)
        self.txt_log = tk.Text(
            log_frame,
            bg=INPUT,
            fg="#93c5fd",
            insertbackground=WHITE,
            font=FONT_SMALL,
            wrap=tk.WORD,
            bd=0,
            yscrollcommand=scroll_y.set,
        )
        scroll_y.config(command=self.txt_log.yview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # --------------------------------------------------------------------------
    # 目录填充与筛选逻辑
    # --------------------------------------------------------------------------
    def _populate_catalog(self):
        self.catalog_tree.delete(*self.catalog_tree.get_children())

        # 按分类聚类
        categories: Dict[str, List[Capability]] = {}
        for cap in CAPABILITIES:
            categories.setdefault(cap.category, []).append(cap)

        for cat_name, items in categories.items():
            cat_node = self.catalog_tree.insert("", tk.END, text=f"📂 {cat_name} ({len(items)})", open=True)
            for cap in items:
                badge = f"[{cap.sub}]"
                if cap.view_val:
                    badge += f" {cap.view_val}"
                if cap.is_compatible:
                    badge += " (兼容)"
                self.catalog_tree.insert(
                    cat_node,
                    tk.END,
                    iid=cap.id,
                    text=f"  {cap.name}",
                    values=(badge,),
                )

    def _filter_catalog(self):
        kw = self.var_search.get().strip().lower()
        self.catalog_tree.delete(*self.catalog_tree.get_children())

        categories: Dict[str, List[Capability]] = {}
        for cap in CAPABILITIES:
            if not kw:
                match = True
            else:
                match = (
                    kw in cap.name.lower()
                    or kw in cap.id.lower()
                    or kw in cap.sub.lower()
                    or kw in cap.view_val.lower()
                    or kw in cap.category.lower()
                    or any(kw in t.lower() for t in cap.tags)
                )
            if match:
                categories.setdefault(cap.category, []).append(cap)

        for cat_name, items in categories.items():
            cat_node = self.catalog_tree.insert("", tk.END, text=f"📂 {cat_name} ({len(items)})", open=True)
            for cap in items:
                badge = f"[{cap.sub}]"
                if cap.view_val:
                    badge += f" {cap.view_val}"
                self.catalog_tree.insert(
                    cat_node,
                    tk.END,
                    iid=cap.id,
                    text=f"  {cap.name}",
                    values=(badge,),
                )

    def _on_catalog_select(self, event):
        sel = self.catalog_tree.selection()
        if not sel:
            return
        node_id = sel[0]
        if node_id in CAPABILITY_MAP:
            self.select_capability(node_id)

    # --------------------------------------------------------------------------
    # 选中能力与参数表单生成
    # --------------------------------------------------------------------------
    def _on_common_param_change(self, bind_to: str, value: str) -> None:
        """把顶栏公共值同步到当前能力表单中的绑定参数。"""
        for p_def, _, var in self.param_widgets.values():
            if p_def.bind_to == bind_to and var.get() != value:
                var.set(value)
        self._update_request_preview()

    def _on_param_change(self, p_def: ParamDef, var: tk.StringVar) -> None:
        """能力表单编辑绑定字段时反向更新顶栏，保持单一请求值。"""
        if p_def.bind_to:
            common_var = {
                "code": self.var_code,
                "date": self.var_date,
                "pageNumber": self.var_page_num,
                "pageSize": self.var_page_size,
            }.get(p_def.bind_to)
            if common_var is not None and common_var.get() != var.get():
                common_var.set(var.get())
        self._update_request_preview()

    def select_capability(self, cap_id: str):
        cap = CAPABILITY_MAP.get(cap_id)
        if not cap:
            return
        self.current_cap = cap

        # 更新标题与说明
        self.lbl_cap_title.config(text=f"📌 {cap.name}")
        route_text = f"sub={cap.sub}"
        if cap.view_param and cap.view_val:
            route_text += f" & {cap.view_param}={cap.view_val}"
        self.lbl_cap_route.config(text=f"[{cap.category} | {route_text}]")
        self.lbl_cap_desc.config(text=cap.description)

        # 切换推荐的请求方法
        self.var_method.set(cap.method)

        # 重建动态参数输入网格
        self._rebuild_param_grid(cap)
        self._update_request_preview()

    def _rebuild_param_grid(self, cap: Capability):
        for w in self.param_grid_frame.winfo_children():
            w.destroy()
        self.param_widgets.clear()

        row = 0
        col = 0
        max_cols = 3  # 每行三组参数

        for p_def in cap.params:
            # 获取绑定或默认值
            val = p_def.default
            if p_def.bind_to == "code" and self.var_code.get():
                val = self.var_code.get()
            elif p_def.bind_to == "date" and self.var_date.get():
                val = self.var_date.get()
            elif p_def.bind_to == "pageNumber" and self.var_page_num.get():
                val = self.var_page_num.get()
            elif p_def.bind_to == "pageSize" and self.var_page_size.get():
                val = self.var_page_size.get()

            var = tk.StringVar(value=val)
            var.trace_add(
                "write",
                lambda *_args, p=p_def, value_var=var:
                self._on_param_change(p, value_var),
            )

            p_box = tk.Frame(self.param_grid_frame, bg=PANEL, padx=6, pady=4)
            p_box.grid(row=row, column=col, sticky="w", padx=4, pady=2)

            # 标签
            req_mark = " *" if p_def.required else ""
            lbl = tk.Label(p_box, text=f"{p_def.label}{req_mark} ({p_def.name}):", bg=PANEL, fg=GOLD if p_def.required else MUTED, font=FONT_SMALL)
            lbl.pack(anchor="w")

            # 输入控件
            if p_def.options:
                ent = ttk.Combobox(p_box, textvariable=var, values=p_def.options, width=18, font=FONT)
            else:
                ent = tk.Entry(p_box, textvariable=var, bg=INPUT, fg=WHITE, insertbackground=WHITE, font=FONT, width=20)
            ent.pack(anchor="w", pady=(2, 0))

            if p_def.hint:
                tk.Label(p_box, text=p_def.hint, bg=PANEL, fg=DIM, font=FONT_TINY).pack(anchor="w")

            self.param_widgets[p_def.name] = (p_def, ent, var)

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def _apply_default_params(self):
        """将当前能力的各个参数重置为默认值或顶栏值。"""
        if not self.current_cap:
            return
        for p_name, (p_def, _, var) in self.param_widgets.items():
            val = p_def.default
            if p_def.bind_to == "code" and self.var_code.get():
                val = self.var_code.get()
            elif p_def.bind_to == "date" and self.var_date.get():
                val = self.var_date.get()
            elif p_def.bind_to == "pageNumber" and self.var_page_num.get():
                val = self.var_page_num.get()
            elif p_def.bind_to == "pageSize" and self.var_page_size.get():
                val = self.var_page_size.get()
            var.set(val)

    def _clear_optional_params(self):
        """清空所有非必填字段。"""
        for _, (p_def, _, var) in self.param_widgets.items():
            if not p_def.required:
                var.set("")

    def _collect_current_params(self) -> Dict[str, str]:
        """收集当前表单与顶栏的全部待请求参数。"""
        params: Dict[str, str] = {}
        if not self.current_cap:
            return params

        # 1. 基础路由参数
        if self.current_cap.sub:
            params["sub"] = self.current_cap.sub
        if self.current_cap.view_param and self.current_cap.view_val:
            params[self.current_cap.view_param] = self.current_cap.view_val

        # 2. 动态参数表单
        for p_name, (p_def, _, var) in self.param_widgets.items():
            v = var.get().strip()
            if v != "":
                params[p_name] = v

        # 3. 处理自由查询的扩展参数
        if "extra_params" in params:
            extra = params.pop("extra_params")
            for pair in extra.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k.strip():
                        params[k.strip()] = v.strip()

        return params

    def _update_request_preview(self):
        """实时更新底部单行请求 URL / 报文预览。"""
        if not self.current_cap:
            self.lbl_preview_url.config(text="")
            return

        base = self.var_base_url.get().strip().rstrip("/")
        path = self.var_path.get().strip()
        if not path.startswith("/"):
            path = "/" + path

        method = self.var_method.get().upper()
        params = self._collect_current_params()
        query = urlencode(params)

        if method == "GET":
            full_preview = f"GET {base}{path}?{query}" if query else f"GET {base}{path}"
        else:
            full_preview = f"POST {base}{path}  --data '{query}'"

        self.lbl_preview_url.config(text=full_preview)

    def _copy_request_preview(self):
        text = self.lbl_preview_url.cget("text")
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._set_status_log("已复制请求预览到剪贴板。")

    # --------------------------------------------------------------------------
    # 请求发起与异步回调处理
    # --------------------------------------------------------------------------
    def execute_current_capability(self):
        """发送当前能力请求，所有 I/O 均在后台线程池执行。"""
        if not self.current_cap:
            messagebox.showinfo("提示", "请先在左侧选择要调用的能力。")
            return

        base = self.var_base_url.get().strip().rstrip("/")
        path = self.var_path.get().strip()
        if not path.startswith("/"):
            path = "/" + path
        target_url = f"{base}{path}"

        method = self.var_method.get().upper()
        params = self._collect_current_params()

        # 校验必填项
        for p_name, (p_def, _, var) in self.param_widgets.items():
            if p_def.required and not var.get().strip():
                messagebox.showwarning("缺少必填参数", f"请填写必填项: {p_def.label} ({p_name})")
                return

        # 更新 UI 状态
        self.var_status_indicator.set("⏳ 请求中...")
        self.card_status.config(text="请求发送中...", fg=GOLD)
        self.card_latency.config(text="计算中...", fg=MUTED)

        desc = f"{self.current_cap.name} [{method} {self.current_cap.sub}]"
        self._log(f"\n==================================================")
        self._log(f"[{time.strftime('%H:%M:%S')}] 发起请求: {desc}")
        self._log(f"目标 URL: {target_url}")
        self._log(f"请求参数: {json.dumps(params, ensure_ascii=False)}")

        # 新请求覆盖旧请求时，旧响应只做后台收尾，不再回写当前工作区。
        if self.active_task_id:
            self.network.cancel_task(self.active_task_id)

        # 提交给网络引擎
        timeout = float(getattr(self.args, "timeout", 15))
        task_id = self.network.submit_request(
            cap_id=self.current_cap.id,
            url=target_url,
            method=method,
            params=params,
            timeout=timeout,
            description=desc,
            on_complete=self._on_request_finished_in_thread,
        )
        self.active_task_id = task_id

    def _on_request_finished_in_thread(self, res: HttpResponseResult):
        """后台线程回调，将结果投递进 UI 线程队列。"""
        self.resp_queue.put(res)

    def _check_response_queue(self):
        """主线程定时检查响应队列，更新控件。"""
        try:
            while True:
                res = self.resp_queue.get_nowait()
                self._handle_response_in_main_thread(res)
        except queue.Empty:
            pass
        finally:
            self.root.after(50, self._check_response_queue)

    def _handle_response_in_main_thread(self, res: HttpResponseResult):
        """在 Tk 主线程中安全刷新控件与表格。"""
        if res.is_cancelled or res.task_id != self.active_task_id:
            return  # 丢弃已过期的请求结果

        # 更新耗时与状态指示
        self.var_latency.set(f"耗时: {res.elapsed_ms:.1f}ms")
        self.card_latency.config(text=f"{res.elapsed_ms:.1f} ms", fg=GREEN if res.elapsed_ms < 1000 else GOLD)

        # 记录日志
        self._log(f"[{time.strftime('%H:%M:%S')}] 响应到达: HTTP {res.status_code} ({res.elapsed_ms:.1f}ms)")
        if res.error:
            self._log(f"错误信息: {res.error}")

        if res.status_code == 0 or res.error:
            self.var_status_indicator.set("❌ 错误")
            self.card_status.config(text=res.error or "网络故障", fg=RED)
            self.card_count.config(text="0 行", fg=MUTED)
            self.card_shape.config(text="异常失败", fg=RED)

            self.txt_json.delete("1.0", tk.END)
            self.txt_json.insert(tk.END, res.raw_body or f"请求失败: {res.error}")
            self._clear_table()
            return

        # 格式化展示 JSON
        self.current_raw_json = res.raw_body
        self.txt_json.delete("1.0", tk.END)
        try:
            if res.json_data is not None:
                pretty = json.dumps(res.json_data, indent=2, ensure_ascii=False)
                self.txt_json.insert(tk.END, pretty)
            else:
                self.txt_json.insert(tk.END, res.raw_body)
        except Exception:
            self.txt_json.insert(tk.END, res.raw_body)

        # 解析外壳与行数据
        is_ok, status_txt, shape_txt, rows, summary = parse_d2_response_data(res.json_data)
        self.current_rows = rows
        self.current_summary = summary

        # 更新卡片状态
        if is_ok:
            self.var_status_indicator.set("✔ 成功")
            self.card_status.config(text=f"正常 ({status_txt})", fg=CYAN)
        else:
            self.var_status_indicator.set("⚠ 业务错误")
            self.card_status.config(text=f"异常: {status_txt}", fg=RED)

        self.card_count.config(text=f"{len(rows)} 行", fg=GOLD if len(rows) > 0 else MUTED)
        self.card_shape.config(text=shape_txt or "普通结构", fg=PURPLE)

        # 刷新表格
        self._render_table_rows(rows)

    # --------------------------------------------------------------------------
    # 动态表格展示与排序
    # --------------------------------------------------------------------------
    def _clear_table(self):
        self.tree_data.delete(*self.tree_data.get_children())
        self.tree_data["columns"] = ()

    def _render_table_rows(self, rows: List[Dict[str, Any]]):
        self._clear_table()
        if not rows:
            return

        # 1. 动态推导全量列集合
        discovered_cols: Dict[str, None] = {}
        for r in rows[:100]:
            for k in r.keys():
                discovered_cols[k] = None

        col_keys = list(discovered_cols.keys())

        # 2. 按优先级重新排列列（代码、名称、现价等优先排在左侧）
        col_keys.sort(key=lambda k: (get_field_sort_priority(k), k))

        # 限制单表呈现最大列数，防止极宽报表拖慢渲染
        max_show_cols = col_keys[:60]
        self.tree_data["columns"] = max_show_cols

        privacy_on = self.var_privacy.get()

        for c_key in max_show_cols:
            cn_title = humanize_field_name(c_key)
            self.tree_data.heading(
                c_key,
                text=f"{cn_title} ({c_key})",
                command=lambda col=c_key: self._sort_table_column(col),
            )
            # 自动估算列宽
            sample_len = max(len(cn_title) * 2, len(c_key), 8)
            col_width = min(max(sample_len * 10, 80), 260)
            self.tree_data.column(c_key, width=col_width, minwidth=60, stretch=False)

        # 3. 逐行插入数据
        for idx, row in enumerate(rows):
            row_vals = []
            for c_key in max_show_cols:
                raw_val = row.get(c_key, "")
                val_str = "" if raw_val is None else str(raw_val)

                # 隐私掩码处理
                if privacy_on and is_name_field(c_key):
                    val_str = display_name(val_str, True)

                row_vals.append(val_str)

            tag = "even" if idx % 2 == 0 else "odd"
            self.tree_data.insert("", tk.END, values=row_vals, tags=(tag,))

        self.tree_data.tag_configure("even", background=PANEL)
        self.tree_data.tag_configure("odd", background=PANEL_ALT)

    def _sort_table_column(self, col: str):
        """点击表头排序。"""
        if self.table_sort_column == col:
            self.table_sort_reverse = not self.table_sort_reverse
        else:
            self.table_sort_column = col
            self.table_sort_reverse = False

        def sort_key(row_dict: Dict[str, Any]):
            v = row_dict.get(col)
            if v is None:
                return (0, "")
            # 尝试转数字排序
            try:
                num = float(str(v).replace("%", "").replace(",", ""))
                return (1, num)
            except Exception:
                return (2, str(v))

        self.current_rows.sort(key=sort_key, reverse=self.table_sort_reverse)
        self._render_table_rows(self.current_rows)

    def on_toggle_privacy(self):
        """实时切换隐私模式，无需重新发请求立即刷新表格显示。"""
        self._render_table_rows(self.current_rows)

    # --------------------------------------------------------------------------
    # 表格复制与交互菜单
    # --------------------------------------------------------------------------
    def _on_tree_cell_double_click(self, event):
        item = self.tree_data.identify_row(event.y)
        column = self.tree_data.identify_column(event.x)
        if not item or not column:
            return
        col_idx = int(column.replace("#", "")) - 1
        vals = self.tree_data.item(item, "values")
        if 0 <= col_idx < len(vals):
            cell_val = vals[col_idx]
            self.root.clipboard_clear()
            self.root.clipboard_append(cell_val)
            self._set_status_log(f"已复制单元格: {cell_val}")

    def _on_tree_context_menu(self, event):
        item = self.tree_data.identify_row(event.y)
        if item:
            if item not in self.tree_data.selection():
                self.tree_data.selection_set(item)
            self.table_menu.post(event.x_root, event.y_root)

    def _copy_selected_cell(self):
        sel = self.tree_data.selection()
        if not sel:
            return
        vals = self.tree_data.item(sel[0], "values")
        if vals:
            self.root.clipboard_clear()
            self.root.clipboard_append(vals[0])
            self._set_status_log(f"已复制首列内容: {vals[0]}")

    def _copy_selected_rows_tsv(self):
        sel = self.tree_data.selection()
        if not sel:
            return
        lines = []
        for item_id in sel:
            vals = self.tree_data.item(item_id, "values")
            lines.append("\t".join(vals))
        tsv_text = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(tsv_text)
        self._set_status_log(f"已复制选中 {len(sel)} 行到剪贴板。")

    def _copy_entire_table_tsv(self):
        cols = self.tree_data["columns"]
        if not cols:
            return
        headers = [f"{humanize_field_name(c)}({c})" for c in cols]
        lines = ["\t".join(headers)]
        for item_id in self.tree_data.get_children():
            vals = self.tree_data.item(item_id, "values")
            lines.append("\t".join(vals))
        full_tsv = "\n".join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(full_tsv)
        self._set_status_log(f"已复制全表 ({len(lines)-1} 行) 到剪贴板。")

    def _copy_json_content(self):
        if self.current_raw_json:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.current_raw_json)
            self._set_status_log("已复制原始 JSON 内容。")

    # --------------------------------------------------------------------------
    # 日志与状态辅助
    # --------------------------------------------------------------------------
    def _log(self, text: str):
        self.txt_log.insert(tk.END, text + "\n")
        self.txt_log.see(tk.END)

    def _set_status_log(self, text: str):
        self.var_status_indicator.set(text)
        self._log(f"[{time.strftime('%H:%M:%S')}] {text}")

    # --------------------------------------------------------------------------
    # 能力总览 / 首页视图
    # --------------------------------------------------------------------------
    def show_overview_dashboard(self):
        """展示能力总览与分类矩阵，并提供轻量快捷探测功能。"""
        overview_win = tk.Toplevel(self.root)
        overview_win.title("D2 线路能力总览与快捷探测")
        overview_win.geometry("960x680")
        overview_win.configure(bg=BG)

        # 头部
        top_f = tk.Frame(overview_win, bg=TOP, height=60, padx=16, pady=10)
        top_f.pack(fill=tk.X)
        tk.Label(top_f, text="D2 线路能力全景矩阵", bg=TOP, fg=WHITE, font=FONT_BIG).pack(anchor="w")
        tk.Label(
            top_f,
            text=f"本地 HTTP 端点: {self.var_base_url.get()}{self.var_path.get()} | 累计登记 {len(CAPABILITIES)} 项标准中性能力",
            bg=TOP,
            fg=MUTED,
            font=FONT_SMALL,
        ).pack(anchor="w", pady=(2, 0))

        # 分类统计与快捷入口
        body_f = tk.Frame(overview_win, bg=BG, padx=16, pady=12)
        body_f.pack(fill=tk.BOTH, expand=True)

        categories: Dict[str, List[Capability]] = {}
        for cap in CAPABILITIES:
            categories.setdefault(cap.category, []).append(cap)

        cat_grid = tk.Frame(body_f, bg=BG)
        cat_grid.pack(fill=tk.X, pady=(0, 12))

        col = 0
        row = 0
        for cat_name, items in categories.items():
            card = tk.Frame(cat_grid, bg=PANEL, padx=10, pady=8, bd=1, relief=tk.SOLID)
            card.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)

            tk.Label(card, text=cat_name, bg=PANEL, fg=CYAN, font=FONT_SECTION).pack(anchor="w")
            tk.Label(card, text=f"包含 {len(items)} 项能力", bg=PANEL, fg=GOLD, font=FONT_SMALL).pack(anchor="w", pady=(2, 4))

            # 快捷跳转
            btn_jump = tk.Button(
                card,
                text="查看目录",
                bg=INPUT,
                fg=TEXT,
                font=FONT_TINY,
                bd=0,
                padx=6,
                command=lambda cn=cat_name: self._jump_to_category(cn, overview_win),
            )
            btn_jump.pack(anchor="w")

            col += 1
            if col >= 4:
                col = 0
                row += 1

        for c_idx in range(4):
            cat_grid.columnconfigure(c_idx, weight=1)

        # 快速一键并发探测卡片区
        probe_f = tk.LabelFrame(body_f, text=" 一键并发轻量状态探测 ", bg=PANEL, fg=WHITE, font=FONT_TITLE, padx=12, pady=8)
        probe_f.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        tk.Label(
            probe_f,
            text="点击下方按钮将并发请求 4 个基础中性接口 (服务时间、交易日历、涨停股池、涨停情绪)，验证本地服务是否就绪：",
            bg=PANEL,
            fg=MUTED,
            font=FONT_SMALL,
        ).pack(anchor="w", pady=(0, 8))

        btn_run_probe = tk.Button(
            probe_f,
            text="⚡ 开始并发探测",
            bg="#15803d",
            fg=WHITE,
            font=FONT_TITLE,
            bd=0,
            padx=16,
            pady=6,
            command=lambda: self._run_lightweight_probes(probe_cards),
        )
        btn_run_probe.pack(anchor="w", pady=(0, 10))

        # 4个卡片容器
        cards_container = tk.Frame(probe_f, bg=PANEL)
        cards_container.pack(fill=tk.X)

        probe_defs = [
            ("time", "服务时间 (sub=time)"),
            ("calendar", "交易日历 (sub=trade_calendar)"),
            ("guchi", "涨停股池 (sub=guchi&status=1)"),
            ("emotion", "涨停情绪 (sub=limit_topic&view=emotion)"),
        ]

        probe_cards: Dict[str, Dict[str, tk.Label]] = {}
        for idx, (p_id, p_title) in enumerate(probe_defs):
            p_box = tk.Frame(cards_container, bg=INPUT, padx=8, pady=6, bd=1, relief=tk.SOLID)
            p_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4)

            tk.Label(p_box, text=p_title, bg=INPUT, fg=WHITE, font=FONT_SMALL).pack(anchor="w")
            lbl_stat = tk.Label(p_box, text="未检测", bg=INPUT, fg=MUTED, font=FONT_SECTION)
            lbl_stat.pack(anchor="w", pady=(4, 2))
            lbl_detail = tk.Label(p_box, text="等待执行", bg=INPUT, fg=DIM, font=FONT_TINY)
            lbl_detail.pack(anchor="w")

            probe_cards[p_id] = {"status": lbl_stat, "detail": lbl_detail}

    def _jump_to_category(self, cat_name: str, win: tk.Toplevel):
        win.destroy()
        self.var_search.set(cat_name)

    def _run_lightweight_probes(self, cards: Dict[str, Dict[str, tk.Label]]):
        """并发向本地服务发送轻量级检测探测。"""
        base = self.var_base_url.get().strip().rstrip("/")
        path = self.var_path.get().strip()
        target_url = f"{base}{path}"

        probes = [
            ("time", {"sub": "time"}),
            ("calendar", {"sub": "trade_calendar", "delta": "-5"}),
            ("guchi", {"sub": "guchi", "status": "1", "pageSize": "5"}),
            ("emotion", {"sub": "limit_topic", "view": "emotion", "pageSize": "5"}),
        ]

        for p_id, _ in probes:
            cards[p_id]["status"].config(text="请求中...", fg=GOLD)
            cards[p_id]["detail"].config(text="正在连接...")

        def execute_probe(p_id: str, query_params: Dict[str, str]):
            start_t = time.perf_counter()
            err_msg = ""
            status_code = 0
            body_json = None
            try:
                # 统一使用 POST 测试
                body_bytes = urlencode(query_params).encode("utf-8")
                req = Request(
                    target_url,
                    data=body_bytes,
                    headers={"User-Agent": "D2Probe/1.0", "Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urlopen(req, timeout=8.0) as resp:
                    status_code = resp.status
                    content = resp.read().decode("utf-8", errors="replace")
                    body_json = json.loads(content)
            except Exception as ex:
                err_msg = str(ex)

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0

            def update_ui():
                if err_msg:
                    cards[p_id]["status"].config(text="连接失败", fg=RED)
                    cards[p_id]["detail"].config(text=f"错误: {err_msg[:30]}")
                else:
                    cards[p_id]["status"].config(text=f"正常 ({elapsed_ms:.0f}ms)", fg=GREEN)
                    detail = "HTTP 200"
                    if isinstance(body_json, dict):
                        if "time" in body_json:
                            detail = f"系统时间: {body_json['time']}"
                        elif "data" in body_json:
                            detail = "数据正常返回"
                        elif "result" in body_json:
                            detail = "业务结果正常"
                    cards[p_id]["detail"].config(text=detail)

            self.root.after(0, update_ui)

        for p_id, q_params in probes:
            threading.Thread(target=execute_probe, args=(p_id, q_params), daemon=True).start()

    # --------------------------------------------------------------------------
    # 退出与资源释放
    # --------------------------------------------------------------------------
    def on_close(self):
        self.network.shutdown()
        self.root.destroy()


# ==============================================================================
# 图表优先的 D2 看板
# ==============================================================================


def _chart_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text in {"--", "-", "None", "null", "N/A", "暂无"}:
        return None
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier, text = 100000000.0, text[:-1]
    elif text.endswith("万"):
        multiplier, text = 10000.0, text[:-1]
    elif text.lower().endswith("b"):
        multiplier, text = 1000000000.0, text[:-1]
    elif text.lower().endswith("m"):
        multiplier, text = 1000000.0, text[:-1]
    text = text.rstrip("%")
    try:
        result = float(text) * multiplier
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _chart_key(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _chart_get(record: Any, aliases: List[str]) -> Any:
    if not isinstance(record, dict):
        return None
    normalized = {_chart_key(key): value for key, value in record.items()}
    for alias in aliases:
        token = _chart_key(alias)
        if token in normalized:
            return normalized[token]
    for alias in aliases:
        token = _chart_key(alias)
        if len(token) >= 3:
            for actual, value in normalized.items():
                if token in actual:
                    return value
    return None


def _chart_raw_row(value: Any) -> Dict[str, Any]:
    parts = [part.strip() for part in str(value or "").split(",")]
    row: Dict[str, Any] = {}
    if not parts:
        return row
    row["date"] = parts[0]
    for index, name in enumerate(("open", "close", "high", "low", "volume", "amount", "amplitude", "change_pct", "change", "turnover_rate"), 1):
        if index < len(parts):
            row[name] = parts[index]
    if len(parts) == 2:
        row["price"] = parts[1]
    return row


def _chart_rows(payload: Any, depth: int = 0) -> List[Dict[str, Any]]:
    if payload is None or depth > 8:
        return []
    if isinstance(payload, str):
        return [_chart_raw_row(payload)] if "," in payload else []
    if isinstance(payload, list):
        result: List[Dict[str, Any]] = []
        for value in payload:
            if isinstance(value, dict):
                result.append(value)
            elif isinstance(value, str) and "," in value:
                result.append(_chart_raw_row(value))
        return result
    if not isinstance(payload, dict):
        return []
    for name in ("trends", "klines", "diff", "rows", "items", "list", "records", "CHANGE_DATA", "data", "result", "Result", "content"):
        if name in payload:
            result = _chart_rows(payload[name], depth + 1)
            if result:
                return result
    # 期货等复合接口返回 dates + longNums/shortNums 这类并行数组，先还原为逐日记录。
    array_fields = [(key, value) for key, value in payload.items() if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value)]
    if len(array_fields) >= 2:
        length = max(len(value) for _key, value in array_fields)
        if length:
            return [
                {key: values[index] if index < len(values) else None for key, values in array_fields}
                for index in range(length)
            ]
    for value in payload.values():
        if isinstance(value, (dict, list)):
            result = _chart_rows(value, depth + 1)
            if result:
                return result
    if any(_chart_number(value) is not None for value in payload.values()):
        return [payload]
    return []


def _chart_find(payload: Any, aliases: List[str], depth: int = 0) -> Optional[float]:
    if payload is None or depth > 8:
        return None
    if isinstance(payload, dict):
        raw_value = _chart_get(payload, aliases)
        if isinstance(raw_value, list):
            for item in reversed(raw_value):
                value = _chart_number(item)
                if value is not None:
                    return value
        value = _chart_number(raw_value)
        if value is not None:
            return value
        for child in payload.values():
            value = _chart_find(child, aliases, depth + 1)
            if value is not None:
                return value
    elif isinstance(payload, list):
        for child in payload:
            value = _chart_find(child, aliases, depth + 1)
            if value is not None:
                return value
    return None


def _chart_text(payload: Any, aliases: List[str], depth: int = 0) -> str:
    if payload is None or depth > 8:
        return ""
    if isinstance(payload, dict):
        value = _chart_get(payload, aliases)
        if value not in (None, "", [], {}):
            return str(value)
        for child in payload.values():
            text = _chart_text(child, aliases, depth + 1)
            if text:
                return text
    elif isinstance(payload, list):
        for child in payload:
            text = _chart_text(child, aliases, depth + 1)
            if text:
                return text
    return ""


def _chart_series(rows: List[Dict[str, Any]], aliases: List[str], labels: Optional[List[str]] = None) -> List[Tuple[str, float]]:
    labels = labels or ["date", "trade_date", "time", "name", "industry", "industry_name", "sector_name", "code"]
    result: List[Tuple[str, float]] = []
    for index, row in enumerate(rows):
        value = _chart_number(_chart_get(row, aliases))
        if value is None:
            fallback: List[float] = []
            for key, raw in row.items():
                token = _chart_key(key)
                if any(part in token for part in ("code", "date", "time", "name", "id", "page")):
                    continue
                number = _chart_number(raw)
                if number is not None:
                    fallback.append(number)
            value = fallback[-1] if fallback else None
        if value is None:
            continue
        label = _chart_get(row, labels)
        result.append((str(label if label not in (None, "") else index + 1), value))
    return result


class D2ChartDashboard:
    """把 D2 的主要数据能力组织成图表；旧工作台作为接口调试入口保留。"""

    def __init__(self, root: tk.Tk, args: argparse.Namespace):
        self.root = root
        self.args = args
        self.base_url = args.base_url.rstrip("/")
        self.path = args.path if args.path.startswith("/") else "/" + args.path
        # 看板会同时拉取多组图表，控制并发避免把本地网关瞬间压满。
        self.network = NetworkEngine(max_workers=4)
        self.response_queue: queue.Queue[HttpResponseResult] = queue.Queue()
        self.pending: Dict[int, Tuple[str, int]] = {}
        self.payloads: Dict[str, Any] = {}
        self.errors: Dict[str, str] = {}
        self.generation = 0
        self.closed = False
        self.debug_window: Optional[tk.Toplevel] = None
        self.debug_app: Optional[D2WorkbenchApp] = None

        self.code_var = tk.StringVar(value=args.code)
        self.date_var = tk.StringVar(value=args.date)
        self.contract_var = tk.StringVar(value="rb")
        self.future_market_var = tk.StringVar(value="113")
        self.privacy_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="等待刷新")
        self.pending_var = tk.StringVar(value="0 个请求")
        self.updated_var = tk.StringVar(value="—")
        self.stock_caption_var = tk.StringVar(value="等待个股数据")
        self.diagnosis_var = tk.StringVar(value="等待诊断结果")
        self.futures_caption_var = tk.StringVar(value="等待期货数据")
        self.stat_vars: Dict[str, tk.StringVar] = {}
        self.stock_stat_vars: Dict[str, tk.StringVar] = {}
        self.radar_stat_vars: Dict[str, tk.StringVar] = {}
        self.future_stat_vars: Dict[str, tk.StringVar] = {}

        self.root.title("d2 · 数据图表看板")
        self.root.geometry("1600x980")
        self.root.minsize(1200, 720)
        self.root.configure(bg=BG)
        if self.root.tk.call("tk", "windowingsystem") == "win32":
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._setup_styles()
        self._build_topbar()
        self._build_tabs()
        self.root.after(60, self._poll_responses)
        self.root.after(260, self.refresh_all)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("D2.TNotebook", background=BG, borderwidth=0)
        style.configure("D2.TNotebook.Tab", background=TOP, foreground=MUTED, padding=(16, 8), font=FONT_CN)
        style.map("D2.TNotebook.Tab", background=[("selected", PANEL_ALT)], foreground=[("selected", GOLD)])
        style.configure("D2.TScrollbar", background="#33425a", troughcolor=BG, bordercolor=BG, arrowcolor=MUTED, relief="flat")

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg=TOP, height=54)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        tk.Label(bar, text="d2", bg=TOP, fg=RED, font=("Consolas", 22, "bold")).pack(side="left", padx=(16, 10))
        tk.Label(bar, text="数据图表看板", bg=TOP, fg=TEXT, font=FONT_BIG).pack(side="left", padx=(0, 20))
        tk.Label(bar, text="代码", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, 4))
        code = tk.Entry(bar, textvariable=self.code_var, width=10, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT)
        code.pack(side="left", padx=(0, 9), ipady=4)
        code.bind("<Return>", lambda _event: self.refresh_all())
        tk.Label(bar, text="日期", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, 4))
        date = tk.Entry(bar, textvariable=self.date_var, width=10, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT)
        date.pack(side="left", padx=(0, 10), ipady=4)
        date.bind("<Return>", lambda _event: self.refresh_all())
        tk.Button(bar, text="刷新全部图表", command=self.refresh_all, bg="#245c45", activebackground="#31815d", fg=WHITE, relief="flat", bd=0, padx=12, pady=5, font=FONT_SMALL).pack(side="left", padx=(0, 12))
        tk.Checkbutton(bar, text="隐私显示", variable=self.privacy_var, command=self._redraw_all, bg=TOP, activebackground=TOP, selectcolor=INPUT, fg=MUTED, activeforeground=TEXT, font=FONT_TINY).pack(side="left", padx=(0, 12))
        tk.Label(bar, textvariable=self.status_var, bg=TOP, fg=MUTED, font=FONT_TINY, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(bar, textvariable=self.pending_var, bg=TOP, fg=CYAN, font=FONT_TINY).pack(side="left", padx=(8, 12))
        tk.Label(bar, textvariable=self.updated_var, bg=TOP, fg=DIM, font=FONT_TINY).pack(side="left", padx=(0, 16))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self.root, style="D2.TNotebook")
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.overview_tab = tk.Frame(self.tabs, bg=BG)
        self.stock_tab = tk.Frame(self.tabs, bg=BG)
        self.radar_tab = tk.Frame(self.tabs, bg=BG)
        self.futures_tab = tk.Frame(self.tabs, bg=BG)
        self.debug_tab = tk.Frame(self.tabs, bg=BG)
        for tab, title in ((self.overview_tab, "市场总览"), (self.stock_tab, "个股分析"), (self.radar_tab, "专题雷达"), (self.futures_tab, "期货分析"), (self.debug_tab, "接口调试")):
            self.tabs.add(tab, text=title)
        self._build_overview_tab()
        self._build_stock_tab()
        self._build_radar_tab()
        self._build_futures_tab()
        self._build_debug_tab()

    @staticmethod
    def _panel(parent: tk.Widget, title: str, row: int, column: int, rowspan: int = 1, columnspan: int = 1) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        frame.grid(row=row, column=column, rowspan=rowspan, columnspan=columnspan, sticky="nsew", padx=4, pady=4)
        tk.Label(frame, text=title, bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w", padx=9, pady=6).pack(fill="x")
        return frame

    @staticmethod
    def _canvas(parent: tk.Widget, callback: Callable[[], None], height: int = 180) -> tk.Canvas:
        canvas = tk.Canvas(parent, bg=PANEL, highlightthickness=0, height=height)
        canvas.pack(fill="both", expand=True, padx=5, pady=5)
        canvas.bind("<Configure>", lambda _event: callback())
        return canvas

    def _card(self, parent: tk.Widget, label: str, variables: Dict[str, tk.StringVar], column: int) -> None:
        box = tk.Frame(parent, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
        box.grid(row=0, column=column, sticky="nsew", padx=3, pady=3)
        parent.grid_columnconfigure(column, weight=1, uniform="cards")
        variable = tk.StringVar(value="—")
        variables[label] = variable
        tk.Label(box, text=label, bg=PANEL_ALT, fg=MUTED, font=FONT_TINY, anchor="w").pack(fill="x", padx=9, pady=(8, 1))
        tk.Label(box, textvariable=variable, bg=PANEL_ALT, fg=TEXT, font=("Consolas", 16, "bold"), anchor="w").pack(fill="x", padx=9, pady=(0, 8))

    def _build_overview_tab(self) -> None:
        tab = self.overview_tab
        for column in range(4):
            tab.grid_columnconfigure(column, weight=1, uniform="overview")
        for row, weight in ((0, 0), (1, 3), (2, 3), (3, 2)):
            tab.grid_rowconfigure(row, weight=weight)
        cards = tk.Frame(tab, bg=BG)
        cards.grid(row=0, column=0, columnspan=4, sticky="ew")
        for index, label in enumerate(("市场成交额", "上涨家数", "下跌家数", "涨停家数", "跌停家数")):
            self._card(cards, label, self.stat_vars, index)
        panels = (
            ("涨跌分布 · 市场宽度", 1, 0, 2, "overview_breadth_canvas", self._draw_overview_breadth),
            ("行业资金流向 · 主力净流入", 1, 2, 2, "overview_capital_canvas", self._draw_overview_capital),
            ("涨停情绪 · 连板趋势", 2, 0, 2, "overview_emotion_canvas", self._draw_overview_emotion),
            ("盘中成交额趋势", 2, 2, 2, "overview_amount_canvas", self._draw_overview_amount),
            ("强势板块排行", 3, 0, 2, "overview_sector_canvas", self._draw_overview_sector),
            ("主要指数表现", 3, 2, 2, "overview_index_canvas", self._draw_overview_index),
        )
        for title, row, column, span, name, callback in panels:
            panel = self._panel(tab, title, row, column, 1, span)
            setattr(self, name, self._canvas(panel, callback))

    def _build_stock_tab(self) -> None:
        tab = self.stock_tab
        for column in range(4):
            tab.grid_columnconfigure(column, weight=1, uniform="stock")
        for row, weight in ((0, 0), (1, 0), (2, 2), (3, 4), (4, 2)):
            tab.grid_rowconfigure(row, weight=weight)
        toolbar = tk.Frame(tab, bg=TOP, height=42)
        toolbar.grid(row=0, column=0, columnspan=4, sticky="ew", padx=4, pady=4)
        toolbar.grid_propagate(False)
        tk.Label(toolbar, text="个股诊断与走势", bg=TOP, fg=GOLD, font=FONT_TITLE).pack(side="left", padx=10)
        tk.Label(toolbar, textvariable=self.stock_caption_var, bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=12)
        tk.Button(toolbar, text="查询当前代码", command=self.refresh_all, bg="#214b72", activebackground="#326995", fg=WHITE, relief="flat", bd=0, padx=10, pady=4, font=FONT_SMALL).pack(side="right", padx=8, pady=5)
        cards = tk.Frame(tab, bg=BG)
        cards.grid(row=1, column=0, columnspan=4, sticky="ew")
        for index, label in enumerate(("最新价", "涨跌幅", "成交额", "换手率")):
            self._card(cards, label, self.stock_stat_vars, index)
        trend = self._panel(tab, "分时走势 · 价格与均价", 2, 0, 1, 2)
        flow = self._panel(tab, "个股资金流 · 净流入", 2, 2, 1, 2)
        kline = self._panel(tab, "K线分析 · 实体 / 影线 / 成交量", 3, 0, 1, 4)
        diagnosis = self._panel(tab, "诊断结论", 4, 0, 1, 2)
        score = self._panel(tab, "综合评分与指标", 4, 2, 1, 2)
        self.stock_trend_canvas = self._canvas(trend, self._draw_stock_trend)
        self.stock_flow_canvas = self._canvas(flow, self._draw_stock_flow)
        self.stock_kline_canvas = self._canvas(kline, self._draw_stock_kline, 280)
        tk.Label(diagnosis, textvariable=self.diagnosis_var, bg=PANEL, fg=TEXT, justify="left", anchor="nw", font=FONT_CN, wraplength=560).pack(fill="both", expand=True, padx=12, pady=12)
        self.stock_score_canvas = self._canvas(score, self._draw_stock_score, 150)

    def _build_radar_tab(self) -> None:
        tab = self.radar_tab
        for column in range(4):
            tab.grid_columnconfigure(column, weight=1, uniform="radar")
        for row, weight in ((0, 0), (1, 2), (2, 2), (3, 1)):
            tab.grid_rowconfigure(row, weight=weight)
        cards = tk.Frame(tab, bg=BG)
        cards.grid(row=0, column=0, columnspan=4, sticky="ew")
        for index, label in enumerate(("涨停家数", "连板家数", "炸板家数", "跌停家数", "最高连板")):
            self._card(cards, label, self.radar_stat_vars, index)
        panels = (
            ("情绪周期趋势", 1, 0, 2, "radar_emotion_canvas", self._draw_radar_emotion),
            ("涨停池结构", 1, 2, 2, "radar_pools_canvas", self._draw_radar_pools),
            ("板块轮动", 2, 0, 2, "radar_sector_canvas", self._draw_radar_sectors),
            ("专题资金榜", 2, 2, 2, "radar_dark_canvas", self._draw_radar_dark),
        )
        for title, row, column, span, name, callback in panels:
            panel = self._panel(tab, title, row, column, 1, span)
            setattr(self, name, self._canvas(panel, callback))
        note = self._panel(tab, "专题覆盖", 3, 0, 1, 4)
        tk.Label(note, text="涨停池、连板、炸板、跌停、板块轮动、情绪曲线和专题资金榜均由 D2 真实视图驱动；接口暂不可用时保留图表结构并标出暂无数据。", bg=PANEL, fg=MUTED, font=FONT_CN, anchor="w", padx=12, pady=10).pack(fill="both", expand=True)

    def _build_futures_tab(self) -> None:
        tab = self.futures_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        for row, weight in ((0, 0), (1, 0), (2, 3), (3, 1)):
            tab.grid_rowconfigure(row, weight=weight)
        toolbar = tk.Frame(tab, bg=TOP, height=42)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        toolbar.grid_propagate(False)
        tk.Label(toolbar, text="期货持仓与成交", bg=TOP, fg=GOLD, font=FONT_TITLE).pack(side="left", padx=10)
        tk.Label(toolbar, text="市场", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(14, 4))
        tk.Entry(toolbar, textvariable=self.future_market_var, width=7, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT).pack(side="left", padx=(0, 9), ipady=3)
        tk.Label(toolbar, text="合约/品种", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, 4))
        contract = tk.Entry(toolbar, textvariable=self.contract_var, width=12, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT)
        contract.pack(side="left", padx=(0, 8), ipady=3)
        contract.bind("<Return>", lambda _event: self.refresh_all())
        tk.Button(toolbar, text="刷新期货图表", command=self.refresh_all, bg="#214b72", activebackground="#326995", fg=WHITE, relief="flat", bd=0, padx=10, pady=4, font=FONT_SMALL).pack(side="left")
        tk.Label(toolbar, textvariable=self.futures_caption_var, bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="right", padx=10)
        cards = tk.Frame(tab, bg=BG)
        cards.grid(row=1, column=0, columnspan=2, sticky="ew")
        for index, label in enumerate(("结算价", "成交量", "总持仓", "净持仓")):
            self._card(cards, label, self.future_stat_vars, index)
        position = self._panel(tab, "多空持仓趋势", 2, 0)
        volume = self._panel(tab, "成交量 / 结算价趋势", 2, 1)
        self.future_position_canvas = self._canvas(position, self._draw_future_position, 250)
        self.future_volume_canvas = self._canvas(volume, self._draw_future_volume, 250)
        note = self._panel(tab, "期货能力覆盖", 3, 0, 1, 2)
        tk.Label(note, text="当前看板展示 position_trend、volume_trend 的时序图；席位明细、品种列表、合约映射等全部能力可在接口调试页逐项调用。", bg=PANEL, fg=MUTED, font=FONT_CN, anchor="w", padx=12, pady=9).pack(fill="both", expand=True)

    def _build_debug_tab(self) -> None:
        tab = self.debug_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        intro = tk.Frame(tab, bg=TOP, height=92)
        intro.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        intro.grid_propagate(False)
        tk.Label(intro, text="接口调试中心", bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(intro, text=f"D2 已注册 {len(CAPABILITIES)} 项能力，按业务分类提供动态参数、真实请求、表格、原始 JSON 与日志；图表看板保持在前四个页签。", bg=TOP, fg=MUTED, font=FONT_CN, anchor="w").pack(side="left", padx=12)
        tk.Button(intro, text="打开完整接口工作台", command=self._open_debug_window, bg="#463766", activebackground="#604d8c", fg=WHITE, relief="flat", bd=0, padx=12, pady=5, font=FONT_SMALL).pack(side="right", padx=12, pady=26)
        body = tk.Frame(tab, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        body.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        tk.Label(body, text="所有 D2 方法仍可逐项验证", bg=PANEL, fg=TEXT, font=FONT_BIG).pack(anchor="w", padx=18, pady=(22, 8))
        tk.Label(body, text="图表看板负责把市场数据变成趋势、分布、排行和 K 线；接口工作台负责查看完整字段和调试边界参数。两者共用同一 HTTP 基址与 d2/gc 数据入口。", bg=PANEL, fg=MUTED, font=FONT_CN, justify="left", anchor="nw", wraplength=900).pack(anchor="w", padx=18, pady=(0, 20))
        category_counts: Dict[str, int] = {}
        for capability in CAPABILITIES:
            category_counts[capability.category] = category_counts.get(capability.category, 0) + 1
        for index, (category, count) in enumerate(category_counts.items()):
            tk.Label(body, text=f"{category}  ·  {count} 项", bg=PANEL_ALT if index % 2 == 0 else PANEL, fg=TEXT, font=FONT_CN, anchor="w", padx=14, pady=6).pack(fill="x", padx=18, pady=1)

    def _open_debug_window(self) -> None:
        if self.debug_window is not None and self.debug_window.winfo_exists():
            self.debug_window.deiconify()
            self.debug_window.lift()
            return
        window = tk.Toplevel(self.root)
        self.debug_window = window
        debug_args = argparse.Namespace(base_url=self.base_url, path=self.path, code=self.code_var.get(), date=self.date_var.get(), timeout=self.args.timeout)
        self.debug_app = D2WorkbenchApp(window, debug_args)

    def _request(self, key: str, sub: str, view: str = "", params: Optional[Dict[str, Any]] = None) -> None:
        request_params: Dict[str, str] = {"sub": sub}
        if view:
            request_params["view"] = view
        for name, value in (params or {}).items():
            if value is not None and str(value).strip():
                request_params[name] = str(value)
        task_id = self.network.submit_request(key, f"{self.base_url}{self.path}", "POST", request_params, float(self.args.timeout), f"图表 {key}", self._on_network_response)
        if task_id > 0:
            self.pending[task_id] = (key, self.generation)

    def _on_network_response(self, result: HttpResponseResult) -> None:
        self.response_queue.put(result)

    def _poll_responses(self) -> None:
        if self.closed:
            return
        handled = 0
        while handled < 80:
            try:
                result = self.response_queue.get_nowait()
            except queue.Empty:
                break
            handled += 1
            meta = self.pending.pop(result.task_id, None)
            if meta is None or meta[1] != self.generation or result.is_cancelled:
                continue
            key = meta[0]
            if result.error and result.json_data is None:
                self.errors[key] = result.error
            else:
                self.payloads[key] = result.json_data
                self.errors.pop(key, None)
            self._redraw_all()
        self.pending_var.set(f"{len(self.pending)} 个请求")
        if self.pending:
            self.status_var.set("正在加载 D2 图表数据…")
        elif self.payloads:
            self.status_var.set("图表数据已更新")
        self.root.after(60, self._poll_responses)

    def refresh_all(self) -> None:
        self.generation += 1
        self.network.cancel_all()
        self.pending.clear()
        self.payloads.clear()
        self.errors.clear()
        self.updated_var.set(time.strftime("更新 %H:%M:%S"))
        self.status_var.set("正在请求 D2 图表数据…")
        date = self.date_var.get().strip()
        code = self.code_var.get().strip() or "000001"
        # 日常看板优先取最近交易日，避免周末/节假日的当前日期把首屏全部变成空图。
        self._request("overview_change", "market_overview", "change_statistics", {"pageSize": 50})
        self._request("overview_amount", "market_overview", "intraday_amount", {"pageSize": 50})
        self._request("overview_flow", "flow_industry", params={"pn": 1, "pz": 20, "fid": "f62"})
        self._request("overview_emotion", "limit_topic", "emotion", {"pageSize": 40})
        self._request("overview_limit", "limit_topic", "limit_summary", {"pageSize": 20})
        self._request("overview_sector", "limit_topic", "sector_summary", {"pageSize": 20})
        self._request("overview_index", "limit_topic", "index_list", {"secids": "1.000002,0.399002,0.899050", "pageSize": 10})
        self._request("stock_quote", "quote", "stock", {"code": code})
        self._request("stock_trend", "quote", "trend", {"code": code, "ndays": 1})
        self._request("stock_kline", "quote", "kline", {"code": code, "lmt": 120, "klt": 101, "fqt": 1})
        self._request("stock_flow", "quote", "fund_flow_kline", {"code": code})
        self._request("stock_diag", "diagnosis", "summary", {"code": code})
        self._request("stock_diag_flow", "diagnosis", "capital_flow", {"code": code})
        self._request("radar_emotion", "limit_topic", "emotion_history", {"date": date, "endDate": date, "pageSize": 60})
        self._request("radar_summary", "limit_topic", "limit_summary", {"pageSize": 20})
        self._request("radar_continuous", "limit_topic", "continuous_pool", {"pageSize": 100})
        self._request("radar_broken", "limit_topic", "broken_pool", {"pageSize": 100})
        self._request("radar_down", "limit_topic", "down_pool", {"pageSize": 100})
        self._request("radar_sector", "limit_topic", "sector_summary", {"pageSize": 30})
        self._request("radar_dark", "dark_market", "industry", {"pageSize": 20, "sort": 8, "order": "desc"})
        contract = self.contract_var.get().strip() or "rb"
        market = self.future_market_var.get().strip() or "113"
        self._request("future_position", "futures_analysis", params={"type": "position_trend", "market": market, "contract": contract, "date": date})
        self._request("future_volume", "futures_analysis", params={"type": "volume_trend", "market": market, "contract": contract, "date": date})
        self._request("future_history", "futures_analysis", params={"type": "position_history", "market": market, "contract": contract, "date": date})
        self._redraw_all()

    def _redraw_all(self) -> None:
        for name in ("_draw_overview_breadth", "_draw_overview_capital", "_draw_overview_emotion", "_draw_overview_amount", "_draw_overview_sector", "_draw_overview_index", "_draw_stock_trend", "_draw_stock_flow", "_draw_stock_kline", "_draw_stock_score", "_draw_radar_emotion", "_draw_radar_pools", "_draw_radar_sectors", "_draw_radar_dark", "_draw_future_position", "_draw_future_volume"):
            getattr(self, name)()
        self._update_cards()

    def _rows(self, key: str) -> List[Dict[str, Any]]:
        return _chart_rows(self.payloads.get(key))

    def _prepare(self, canvas: tk.Canvas, key: str) -> bool:
        if self.errors.get(key):
            self._empty(canvas, "数据暂不可用", self.errors[key][:72])
            return False
        if key not in self.payloads:
            self._empty(canvas, "暂无数据", "正在等待 D2 返回" if self.pending else "点击顶部按钮刷新")
            return False
        return True

    @staticmethod
    def _empty(canvas: tk.Canvas, title: str = "暂无数据", detail: str = "点击顶部按钮刷新") -> None:
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 280), max(canvas.winfo_height(), 130)
        canvas.create_text(width / 2, height / 2 - 8, text=title, fill=MUTED, font=FONT_CN)
        canvas.create_text(width / 2, height / 2 + 17, text=detail, fill=DIM, font=FONT_TINY)

    def _line(self, canvas: tk.Canvas, series: List[Tuple[str, float]], color: str = BLUE) -> None:
        canvas.delete("all")
        if not series:
            self._empty(canvas)
            return
        width, height = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 150)
        left, right, top, bottom = 48, 18, 22, 28
        plot_w, plot_h = width - left - right, height - top - bottom
        values = [value for _label, value in series]
        lo, hi = min(values), max(values)
        pad = (hi - lo) * 0.12 if hi != lo else abs(hi) * 0.08 or 1.0
        lo, hi = lo - pad, hi + pad
        for index in range(5):
            y = top + plot_h * index / 4
            canvas.create_line(left, y, width - right, y, fill="#1a2a3d")
            canvas.create_text(left - 6, y, text=f"{hi - (hi - lo) * index / 4:.2f}", fill=DIM, font=FONT_TINY, anchor="e")
        points: List[float] = []
        for index, (_label, value) in enumerate(series):
            x = left + plot_w * index / max(1, len(series) - 1)
            y = top + (hi - value) / (hi - lo) * plot_h
            points.extend((x, y))
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=2, smooth=len(points) > 6)
        step = max(1, len(series) // 5)
        for index in range(0, len(series), step):
            x = left + plot_w * index / max(1, len(series) - 1)
            y = top + (hi - series[index][1]) / (hi - lo) * plot_h
            canvas.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=color, outline="")
            canvas.create_text(x, height - 10, text=series[index][0][-8:], fill=DIM, font=FONT_TINY)
        if points:
            canvas.create_text(width - right, top, text=f"{series[-1][1]:.2f}", fill=color, font=FONT_TINY, anchor="ne")

    def _multi(self, canvas: tk.Canvas, values: Dict[str, List[Tuple[str, float]]], colors: List[str]) -> None:
        clean = {key: series for key, series in values.items() if series}
        if not clean:
            self._empty(canvas)
            return
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 150)
        left, right, top, bottom = 48, 18, 22, 28
        plot_w, plot_h = width - left - right, height - top - bottom
        all_values = [value for series in clean.values() for _label, value in series]
        lo, hi = min(all_values), max(all_values)
        pad = (hi - lo) * 0.12 if hi != lo else abs(hi) * 0.08 or 1.0
        lo, hi = lo - pad, hi + pad
        for index in range(5):
            y = top + plot_h * index / 4
            canvas.create_line(left, y, width - right, y, fill="#1a2a3d")
            canvas.create_text(left - 6, y, text=f"{hi - (hi - lo) * index / 4:.1f}", fill=DIM, font=FONT_TINY, anchor="e")
        x_legend = left
        for color, (name, series) in zip(colors, clean.items()):
            points: List[float] = []
            for index, (_label, value) in enumerate(series):
                x = left + plot_w * index / max(1, len(series) - 1)
                y = top + (hi - value) / (hi - lo) * plot_h
                points.extend((x, y))
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2, smooth=len(points) > 6)
            canvas.create_rectangle(x_legend, 7, x_legend + 9, 16, fill=color, outline="")
            canvas.create_text(x_legend + 14, 11, text=name, fill=TEXT, font=FONT_TINY, anchor="w")
            x_legend += 72 + len(name) * 7

    def _bars(self, canvas: tk.Canvas, items: List[Tuple[str, float]], color: str = BLUE) -> None:
        canvas.delete("all")
        if not items:
            self._empty(canvas)
            return
        items = items[:14]
        width, height = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 150)
        left, right, top, bottom = 112, 22, 12, 20
        plot_w, row_h = width - left - right, (height - top - bottom) / len(items)
        maximum = max(abs(value) for _label, value in items) or 1.0
        has_negative = any(value < 0 for _label, value in items)
        zero = left + plot_w / 2 if has_negative else left
        scale = plot_w / (maximum * (2 if has_negative else 1))
        for index, (label, value) in enumerate(items):
            y = top + row_h * (index + 0.5)
            end = zero + value * scale
            fill = RED if value >= 0 else GREEN
            canvas.create_text(left - 7, y, text=display_name(label, self.privacy_var.get())[:14], fill=TEXT, font=FONT_TINY, anchor="e")
            canvas.create_rectangle(min(zero, end), y - row_h * .25, max(zero, end), y + row_h * .25, fill=color if color != BLUE else fill, outline="")
            canvas.create_text(end + (5 if value >= 0 else -5), y, text=f"{value:.2f}", fill=MUTED, font=FONT_TINY, anchor="w" if value >= 0 else "e")

    def _distribution(self, canvas: tk.Canvas, items: List[Tuple[str, float]]) -> None:
        canvas.delete("all")
        if not items:
            self._empty(canvas)
            return
        width, height = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 150)
        total = sum(max(0, value) for _label, value in items) or 1.0
        x, y, bar_w = 28, max(28, height * .35), width - 56
        colors = (RED, GOLD, DIM, BLUE, GREEN)
        cursor = x
        for index, (label, value) in enumerate(items):
            segment = bar_w * max(0, value) / total
            canvas.create_rectangle(cursor, y, cursor + segment, y + 34, fill=colors[index % len(colors)], outline="")
            if segment > 30:
                canvas.create_text(cursor + segment / 2, y + 17, text=f"{value:.0f}", fill=WHITE, font=FONT_TINY)
            cursor += segment
        for index, (label, value) in enumerate(items):
            lx = x + (index % 3) * bar_w / 3
            ly = y + 62 + (index // 3) * 24
            canvas.create_rectangle(lx, ly - 6, lx + 10, ly + 4, fill=colors[index % len(colors)], outline="")
            canvas.create_text(lx + 16, ly - 1, text=f"{label}  {value:.0f}", fill=TEXT, font=FONT_TINY, anchor="w")

    def _candles(self, canvas: tk.Canvas, rows: List[Dict[str, Any]]) -> None:
        data: List[Tuple[str, float, float, float, float, float]] = []
        for row in rows[-100:]:
            op = _chart_number(_chart_get(row, ["open", "open_price", "OPEN_PRICE"]))
            close = _chart_number(_chart_get(row, ["close", "close_price", "CLOSE_PRICE", "price", "latest_price", "f2"]))
            high = _chart_number(_chart_get(row, ["high", "high_price", "HIGH_PRICE"]))
            low = _chart_number(_chart_get(row, ["low", "low_price", "LOW_PRICE"]))
            volume = _chart_number(_chart_get(row, ["volume", "deal_volume", "DEAL_VOLUME", "f5"])) or 0.0
            if op is None or close is None:
                continue
            data.append((str(_chart_get(row, ["date", "trade_date", "time"]) or ""), op, close, high if high is not None else max(op, close), low if low is not None else min(op, close), volume))
        canvas.delete("all")
        if not data:
            self._empty(canvas)
            return
        width, height = max(canvas.winfo_width(), 420), max(canvas.winfo_height(), 230)
        left, right, top, bottom = 52, 18, 18, 38
        price_h = (height - top - bottom) * .72
        volume_top = top + price_h + 14
        hi, lo = max(item[3] for item in data), min(item[4] for item in data)
        if hi == lo:
            hi, lo = hi + 1, lo - 1
        for index in range(4):
            y = top + price_h * index / 3
            canvas.create_line(left, y, width - right, y, fill="#1a2a3d")
            canvas.create_text(left - 6, y, text=f"{hi - (hi - lo) * index / 3:.2f}", fill=DIM, font=FONT_TINY, anchor="e")
        step = (width - left - right) / len(data)
        max_volume = max(item[5] for item in data) or 1.0
        for index, (label, op, close, high, low, volume) in enumerate(data):
            x = left + step * (index + .5)
            y_high = top + (hi - high) / (hi - lo) * price_h
            y_low = top + (hi - low) / (hi - lo) * price_h
            y_op = top + (hi - op) / (hi - lo) * price_h
            y_close = top + (hi - close) / (hi - lo) * price_h
            fill = RED if close >= op else GREEN
            canvas.create_line(x, y_high, x, y_low, fill=fill)
            canvas.create_rectangle(x - max(2, step * .28), min(y_op, y_close), x + max(2, step * .28), max(y_op, y_close) + 1, fill=fill, outline=fill)
            volume_y = height - bottom - (height - bottom - volume_top) * volume / max_volume
            canvas.create_rectangle(x - max(2, step * .28), volume_y, x + max(2, step * .28), height - bottom, fill="#36516f", outline="")
            if index % max(1, len(data) // 5) == 0:
                canvas.create_text(x, height - 12, text=label[-8:], fill=DIM, font=FONT_TINY)
        canvas.create_text(width - right, volume_top - 4, text="成交量", fill=DIM, font=FONT_TINY, anchor="e")

    def _metric(self, key: str, aliases: List[str]) -> Optional[float]:
        return _chart_find(self.payloads.get(key), aliases)

    def _fmt(self, value: Optional[float], percent: bool = False) -> str:
        if value is None:
            return "—"
        if percent:
            return f"{value:.2f}%"
        if abs(value) >= 100000000:
            return f"{value / 100000000:.2f} 亿"
        if abs(value) >= 10000:
            return f"{value / 10000:.2f} 万"
        return f"{value:.2f}" if abs(value - round(value)) > .001 else f"{value:.0f}"

    def _update_cards(self) -> None:
        self.stat_vars["市场成交额"].set(self._fmt(self._metric("overview_amount", ["amount", "total_amount", "turnover", "成交额", "f6"])))
        self.stat_vars["上涨家数"].set(self._fmt(self._metric("overview_change", ["up", "up_count", "rise", "rise_count", "RISE_NUM", "RISE_NUM_HS", "上涨", "上涨家数"])))
        self.stat_vars["下跌家数"].set(self._fmt(self._metric("overview_change", ["down", "down_count", "fall", "fall_count", "DOWN_NUM", "DOWN_NUM_HS", "下跌", "下跌家数"])))
        self.stat_vars["涨停家数"].set(self._fmt(self._metric("overview_limit", ["limit_up", "limit_count", "LIMIT_NUMBERS", "uplimit_num", "UPLIMIT_NUM", "涨停", "涨停家数"])))
        self.stat_vars["跌停家数"].set(self._fmt(self._metric("overview_limit", ["limit_down", "down_limit", "LIMIT_DOWN_NUM", "downlimit_num", "DOWNLIMIT_NUM", "跌停", "跌停家数"])))
        quote = self.payloads.get("stock_quote")
        self.stock_stat_vars["最新价"].set(self._fmt(_chart_find(quote, ["price", "latest_price", "new_price", "close", "NEW_PRICE", "f2"])))
        self.stock_stat_vars["涨跌幅"].set(self._fmt(_chart_find(quote, ["change_pct", "change_rate", "CHANGE_RATE", "涨跌幅", "f3"]), True))
        self.stock_stat_vars["成交额"].set(self._fmt(_chart_find(quote, ["amount", "deal_amount", "DEAL_AMOUNT", "成交额", "f6"])))
        self.stock_stat_vars["换手率"].set(self._fmt(_chart_find(quote, ["turnover_rate", "TURNOVER_RATE", "换手率", "f8"]), True))
        summary = self.payloads.get("radar_summary") or self.payloads.get("overview_limit")
        self.radar_stat_vars["涨停家数"].set(self._fmt(_chart_find(summary, ["limit_up", "limit_count", "LIMIT_NUMBERS", "uplimit_num", "涨停家数"])))
        self.radar_stat_vars["连板家数"].set(self._fmt(_chart_find(summary, ["continuous", "continuous_count", "COUNTINUS_STOCK_NUM", "countinus_stock_num", "连板家数"])))
        self.radar_stat_vars["炸板家数"].set(self._fmt(_chart_find(summary, ["broken", "broken_count", "炸板家数"])))
        self.radar_stat_vars["跌停家数"].set(self._fmt(_chart_find(summary, ["limit_down", "down_limit", "LIMIT_DOWN_NUM", "DOWNLIMIT_NUM", "downlimit_num", "跌停家数"])))
        self.radar_stat_vars["最高连板"].set(self._fmt(_chart_find(summary, ["max_continuous", "MAX_CONTINUS_UPLIMITS", "max_continus_uplimits", "最高连板"])))
        self.future_stat_vars["结算价"].set(self._fmt(self._metric("future_volume", ["settlement_price", "settle", "price", "close", "clears", "结算价"])))
        self.future_stat_vars["成交量"].set(self._fmt(self._metric("future_volume", ["volume", "deal_volume", "totalVloumes", "top20Vloumes", "成交量"])))
        self.future_stat_vars["总持仓"].set(self._fmt(self._metric("future_position", ["position", "open_interest", "longNums", "shortNums", "总持仓"])))
        self.future_stat_vars["净持仓"].set(self._fmt(self._metric("future_position", ["net_position", "netLongs", "netShorts", "net", "净持仓"])))
        name = _chart_text(quote, ["name", "stock_name", "security_name", "SECURITY_NAME_ABBR"])
        self.stock_caption_var.set(f"{display_name(name, self.privacy_var.get()) if name else '证券'} · {self.code_var.get().strip() or '000001'}")
        self.futures_caption_var.set(f"{self.future_market_var.get().strip() or '113'} · {self.contract_var.get().strip() or 'rb'}")
        score = self._metric("stock_diag", ["score", "SCORE", "total_score", "综合评分"])
        comment = _chart_text(self.payloads.get("stock_diag"), ["message", "Message", "comment", "conclusion", "Result"])
        self.diagnosis_var.set(f"综合评分：{self._fmt(score)}\n\n{comment[:320] if comment else '诊断结果将在 D2 返回后显示。'}")

    def _distribution_items(self) -> List[Tuple[str, float]]:
        aliases = (
            ("上涨", ["up", "up_count", "rise", "rise_count", "RISE_NUM", "RISE_NUM_HS", "上涨", "上涨家数"]),
            ("平盘", ["flat", "flat_count", "平盘", "平盘家数"]),
            ("下跌", ["down", "down_count", "fall", "fall_count", "DOWN_NUM", "DOWN_NUM_HS", "下跌", "下跌家数"]),
            ("涨停", ["limit_up", "limit_count", "LIMIT_NUMBERS", "uplimit_num", "UPLIMIT_NUM", "涨停", "涨停家数"]),
            ("跌停", ["limit_down", "down_limit", "LIMIT_DOWN_NUM", "downlimit_num", "DOWNLIMIT_NUM", "跌停", "跌停家数"]),
        )
        result = [(label, value) for label, names in aliases if (value := self._metric("overview_change", names)) is not None]
        return result or _chart_series(self._rows("overview_change"), ["count", "value", "number", "num", "RISE_NUM", "DOWN_NUM", "家数", "f2"], ["name", "type", "label", "市场"])

    def _draw_overview_breadth(self) -> None:
        if hasattr(self, "overview_breadth_canvas") and self._prepare(self.overview_breadth_canvas, "overview_change"):
            self._distribution(self.overview_breadth_canvas, self._distribution_items())

    def _draw_overview_capital(self) -> None:
        if hasattr(self, "overview_capital_canvas") and self._prepare(self.overview_capital_canvas, "overview_flow"):
            items = _chart_series(self._rows("overview_flow"), ["main_net_inflow", "net_inflow", "net_amount", "f62", "f184", "主力净流入"], ["name", "industry", "industry_name", "sector_name", "板块"])
            items.sort(key=lambda item: abs(item[1]), reverse=True)
            self._bars(self.overview_capital_canvas, items, PURPLE)

    def _draw_overview_emotion(self) -> None:
        if hasattr(self, "overview_emotion_canvas") and self._prepare(self.overview_emotion_canvas, "overview_emotion"):
            self._line(self.overview_emotion_canvas, _chart_series(self._rows("overview_emotion"), ["emotion", "sentiment", "MAX_CONTINUS_UPLIMITS", "max_continuous", "max_continus_uplimits", "UPLIMIT_NUM", "limit_count", "情绪"]), GOLD)

    def _draw_overview_amount(self) -> None:
        if hasattr(self, "overview_amount_canvas") and self._prepare(self.overview_amount_canvas, "overview_amount"):
            self._line(self.overview_amount_canvas, _chart_series(self._rows("overview_amount"), ["amount", "total_amount", "turnover", "deal_amount", "成交额", "f6"]), CYAN)

    def _draw_overview_sector(self) -> None:
        if hasattr(self, "overview_sector_canvas") and self._prepare(self.overview_sector_canvas, "overview_sector"):
            items = _chart_series(self._rows("overview_sector"), ["change_pct", "change_rate", "rise_pct", "涨跌幅", "f3", "limit_count", "涨停家数"], ["name", "sector_name", "industry_name", "board_name", "板块"])
            if len(items) < 3:
                items = _chart_series(self._rows("overview_flow"), ["main_net_inflow", "net_inflow", "net_amount", "f62", "f184", "主力净流入"], ["name", "industry", "industry_name", "sector_name", "板块"])
            items.sort(key=lambda item: item[1], reverse=True)
            self._bars(self.overview_sector_canvas, items, RED)

    def _draw_overview_index(self) -> None:
        if hasattr(self, "overview_index_canvas") and self._prepare(self.overview_index_canvas, "overview_index"):
            self._bars(self.overview_index_canvas, _chart_series(self._rows("overview_index"), ["change_pct", "change_rate", "CHANGE_RATE", "涨跌幅", "f3", "change", "f4"], ["name", "index_name", "security_name", "code", "secid"]))

    def _draw_stock_trend(self) -> None:
        if hasattr(self, "stock_trend_canvas") and self._prepare(self.stock_trend_canvas, "stock_trend"):
            rows = self._rows("stock_trend")
            price = _chart_series(rows, ["price", "latest_price", "current", "close", "new_price", "f2"])
            average = _chart_series(rows, ["avg_price", "average", "均价", "f3"])
            self._multi(self.stock_trend_canvas, {"价格": price, "均价": average}, [RED, GOLD])

    def _draw_stock_flow(self) -> None:
        if hasattr(self, "stock_flow_canvas") and self._prepare(self.stock_flow_canvas, "stock_flow"):
            self._bars(self.stock_flow_canvas, _chart_series(self._rows("stock_flow"), ["main_net_inflow", "net_inflow", "net_amount", "主力净流入", "f62", "f184"], ["date", "trade_date", "time"]), PURPLE)

    def _draw_stock_kline(self) -> None:
        if hasattr(self, "stock_kline_canvas") and self._prepare(self.stock_kline_canvas, "stock_kline"):
            self._candles(self.stock_kline_canvas, self._rows("stock_kline"))

    def _draw_stock_score(self) -> None:
        if not hasattr(self, "stock_score_canvas") or not self._prepare(self.stock_score_canvas, "stock_diag"):
            return
        canvas = self.stock_score_canvas
        canvas.delete("all")
        score = self._metric("stock_diag", ["score", "SCORE", "total_score", "综合评分"])
        if score is None:
            self._empty(canvas)
            return
        width = max(canvas.winfo_width(), 300)
        score = max(0.0, min(100.0, score))
        canvas.create_text(30, 30, text=f"{score:.1f}", fill=GOLD, font=("Consolas", 27, "bold"), anchor="w")
        canvas.create_text(32, 59, text="综合评分", fill=MUTED, font=FONT_TINY, anchor="w")
        canvas.create_rectangle(32, 82, width - 24, 98, fill="#1b2a3d", outline="")
        canvas.create_rectangle(32, 82, 32 + (width - 56) * score / 100, 98, fill=GOLD if score >= 60 else GREEN, outline="")

    def _draw_radar_emotion(self) -> None:
        if hasattr(self, "radar_emotion_canvas") and self._prepare(self.radar_emotion_canvas, "radar_emotion"):
            self._line(self.radar_emotion_canvas, _chart_series(self._rows("radar_emotion"), ["emotion", "sentiment", "MAX_CONTINUS_UPLIMITS", "max_continuous", "max_continus_uplimits", "UPLIMIT_NUM", "limit_count", "情绪"]), GOLD)

    def _pool_count(self, key: str, aliases: List[str]) -> float:
        value = self._metric(key, aliases)
        return value if value is not None else float(len(self._rows(key)))

    def _draw_radar_pools(self) -> None:
        if hasattr(self, "radar_pools_canvas") and self._prepare(self.radar_pools_canvas, "radar_summary"):
            self._bars(self.radar_pools_canvas, [("涨停池", self._pool_count("radar_summary", ["limit_up", "limit_count", "LIMIT_NUMBERS", "uplimit_num", "涨停家数"])), ("连板池", self._pool_count("radar_continuous", ["count", "total", "连板家数"])), ("炸板池", self._pool_count("radar_broken", ["count", "total", "炸板家数"])), ("跌停池", self._pool_count("radar_down", ["count", "total", "跌停家数"]))], RED)

    def _draw_radar_sectors(self) -> None:
        if hasattr(self, "radar_sector_canvas") and self._prepare(self.radar_sector_canvas, "radar_sector"):
            items = _chart_series(self._rows("radar_sector"), ["change_pct", "change_rate", "rise_pct", "涨跌幅", "limit_count", "涨停家数", "f3"], ["name", "sector_name", "industry_name", "board_name", "板块"])
            if len(items) < 3:
                items = _chart_series(self._rows("overview_flow"), ["main_net_inflow", "net_inflow", "net_amount", "f62", "f184", "主力净流入"], ["name", "industry", "industry_name", "sector_name", "板块"])
            items.sort(key=lambda item: item[1], reverse=True)
            self._bars(self.radar_sector_canvas, items, RED)

    def _draw_radar_dark(self) -> None:
        if hasattr(self, "radar_dark_canvas") and self._prepare(self.radar_dark_canvas, "radar_dark"):
            items = _chart_series(self._rows("radar_dark"), ["net_money_yuan", "net_inflow", "main_net_inflow", "dark_money_yuan", "f62", "净流入"], ["name", "industry_name", "sector_name", "板块"])
            items.sort(key=lambda item: item[1], reverse=True)
            self._bars(self.radar_dark_canvas, items, PURPLE)

    def _draw_future_position(self) -> None:
        if hasattr(self, "future_position_canvas") and self._prepare(self.future_position_canvas, "future_position"):
            rows = self._rows("future_position")
            values = {"多头": _chart_series(rows, ["long_position", "longNums", "long", "多头持仓", "多单"]), "空头": _chart_series(rows, ["short_position", "shortNums", "short", "空头持仓", "空单"]), "净持仓": _chart_series(rows, ["net_position", "netLongs", "netShorts", "net", "净持仓"])}
            if not any(values.values()):
                values = {"持仓": _chart_series(rows, ["position", "open_interest", "数量", "longNums", "shortNums"])}
            self._multi(self.future_position_canvas, values, [RED, GREEN, GOLD])

    def _draw_future_volume(self) -> None:
        if hasattr(self, "future_volume_canvas") and self._prepare(self.future_volume_canvas, "future_volume"):
            rows = self._rows("future_volume")
            self._multi(self.future_volume_canvas, {"结算价": _chart_series(rows, ["settlement_price", "settle", "price", "close", "clears", "结算价"]), "成交量": _chart_series(rows, ["volume", "deal_volume", "totalVloumes", "top20Vloumes", "成交量", "交易量"])}, [BLUE, CYAN])

    def on_close(self) -> None:
        self.closed = True
        self.network.shutdown()
        self.root.destroy()


# ==============================================================================
# 命令行入口
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="D2 线路图表看板 — 市场、个股、专题与期货可视化示例 GUI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="D2 本地服务 HTTP 基址")
    parser.add_argument("--path", default="/d2/gc", help="D2 数据网关入口路径")
    parser.add_argument("--code", default="000001", help="默认证券代码")
    parser.add_argument("--date", default=time.strftime("%Y%m%d"), help="默认查询日期 (YYYYMMDD)")
    parser.add_argument("--timeout", type=float, default=15.0, help="网络请求超时时间 (秒)")

    args = parser.parse_args()

    # 启动 GUI
    root = tk.Tk()
    app = D2ChartDashboard(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
