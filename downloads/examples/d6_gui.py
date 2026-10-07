#!/usr/bin/env python3
"""d6 Tkinter 行情大屏。

这个面板把 d6 的多类行情能力组织成一个大屏工作区：

* 市场总览：指数、涨跌分布、情绪、板块、异动和股票排行；
* 个股详情：实时行情、逐笔成交、分时、盘前竞价、个股资金和 K 线；
* 行情排行、资金专题、异动监控、资讯数据：按业务切换并按需请求；
* 接口中心：从本地 catalog 动态加载全部 HTTP 接口，保留通用调用能力。

网络请求在后台线程执行，Tk 只在主线程批量刷新。运行前安装：

    python -m pip install websocket-client
"""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import re
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from privacy_display import display_name, is_name_field

try:
    import websocket
except ImportError:  # pragma: no cover - 运行时由界面提示安装
    websocket = None  # type: ignore[assignment]


HTTP_BASE = "http://127.0.0.1:8080/d6/market/v1"
WS_URL = "ws://127.0.0.1:8080/d6/market/ws/quote"
CATALOG_URL = "http://127.0.0.1:8080/d6/market/catalog"
DEFAULT_CODE = "SZ300052"
KLINE_PERIODS = (
    ("1分", "MIN1"),
    ("5分", "MIN5"),
    ("15分", "MIN15"),
    ("30分", "MIN30"),
    ("60分", "MIN60"),
    ("日K", "DAY"),
    ("周K", "WEEK"),
    ("月K", "MONTH"),
)
KLINE_PERIOD_LABELS = {period: label for label, period in KLINE_PERIODS}
TRADE_PAGE_SIZE = 80
TRADE_MAX_ROWS = 5000


def normalize_display_text(value: Any) -> str:
    """统一用户界面文本的空白和换行。"""
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())

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
FONT_BIG = ("Microsoft YaHei UI", 18, "bold")
FONT_WATERMARK = ("Microsoft YaHei UI", 24, "bold")

SOURCE_META = {
    "HTTP": ("#5aa7ff", "#153b5a"),
    "WS": ("#31c48d", "#164836"),
}

TABLE_PRIORITIES = {
    "stock/anomalies": [
        "alarmTime", "symbol", "name", "lastPx", "priceSnapshot", "pxChangeRate",
        "pxChangeRateSnapshot", "typeName", "displayData", "sector.name", "sector.pxChangeRate",
    ],
    "limit/monitor": [
        "time", "symbol", "name", "lastPx", "type", "pxChangeRate", "min5Chgpct",
        "market", "listedSector", "limitType", "is*ST", "isST",
    ],
    "limit/list": [
        "symbol", "name", "lastPx", "pxChangeRate", "market", "listedSector", "limitType",
        "upLimitType", "upType", "sector.name", "sector.pxChangeRate", "netTurnover",
    ],
    "sector/anomaly": [
        "datetime", "prodCode", "prodName", "lastPx", "pxChangeRate", "platePxChangeRate",
        "state", "typeDirection", "netFundFlow", "riseFirstGrp", "fallFirstGrp", "marketStocks",
    ],
    "sector/quote": [
        "ProdName", "ProdCode", "HqTypeCode", "PxChangeRate", "RiseCount", "FallCount",
        "FlatCount", "UpLimitNum", "DownLimitNum", "BusinessBalance", "Fundflow", "RiseFirstGrp", "FallFirstGrp",
    ],
    "margin/": [
        "TradingDay", "SecuCode", "SecuAbbr", "ClosePrice", "UpDownRatio", "FinanceValue",
        "FinancePureValue", "SecurityValue", "SecurityPureValue", "FinaInTotalRatio",
    ],
    "chip/distribution": [
        "tradeDate", "chipSummary.meanPrice", "chipSummary.winRatio", "chipSummary.costL90",
        "chipSummary.costH90", "chipSummary.jzd90", "chipSummary.shapes", "items",
    ],
}

# d6 响应中常见的业务枚举。表格显示业务含义，原码集中保留在字段字典中。
ENUM_MAPS = {
    "listedSector": {0: "全部", 1: "沪市主板", 2: "深市主板", 3: "科创板", 4: "创业板", 5: "北交所"},
    "limitType": {-1: "跌停", 0: "非涨跌停", 1: "涨停"},
    "boardType": {0: "普通板", 1: "一字板"},
    "BiddingLimitType": {0: "无竞价涨停标记", 1: "有竞价涨停标记"},
    "market": {"sh": "上海", "sz": "深圳", "bj": "北交所", "hk": "港股", "us": "美股", "all": "全市场"},
    "marketid": {0: "深圳", 1: "上海", 118: "港股", 156: "纳斯达克", 158: "美股其他市场"},
    "xsfx": {1: "卖", 2: "买", "卖": "卖", "买": "买"},
    "tradetype": {0: "成交"},
    "upDownType": {"up": "上涨/涨停", "down": "下跌/跌停"},
    "direction": {"up": "上涨/买入", "down": "下跌/卖出"},
    "typeDirection": {"up": "上涨/买入", "down": "下跌/卖出"},
    "STType": {0: "默认不过滤"},
    "tradingType": {0: "全部"},
    "sortFlag": {True: "启用排序", False: "不排序", "true": "启用排序", "false": "不排序"},
    "category": {"gang": "席位/营业部排行", "public": "公开异动"},
    "is*ST": {False: "否", True: "是"},
    "isST": {False: "否", True: "是"},
    "isDragon": {False: "否", True: "是"},
    "plateTypeCode": {"hy": "行业板块", "gn": "概念板块", "fg": "风格板块"},
    "hqTypeCode": {
        "HY": "行业板块", "GN": "概念板块", "FG": "风格板块",
        "XBHS.HY": "行业板块", "XBHS.GN": "概念板块", "XBHS.DY": "地域板块",
    },
    "HqTypeCode": {
        "HY": "行业板块", "GN": "概念板块", "FG": "风格板块",
        "XBHS.HY": "行业板块", "XBHS.GN": "概念板块", "XBHS.DY": "地域板块",
    },
    "plateCategory": {"XBHS.HY": "行业板块", "XBHS.GN": "概念板块", "XBHS.DY": "地域板块"},
    "stateCode": {23: "快速拉升", 24: "快速下挫", 31: "走强", 35: "快速反弹"},
    "display": {True: "显示", False: "隐藏", "true": "显示", "false": "隐藏"},
    "tradeStatus": {"": "正常交易"},
}

LIMIT_EVENT_TYPES = {
    0: "普通/无板事件",
    1: "涨停封板",
    2: "打开涨停/炸板",
    4: "跌停封板",
    8: "打开跌停/撬板",
}

STOCK_ANOMALY_TYPES = {
    37: "大笔买入",
    38: "大笔卖出",
}

DICTIONARY_ROWS = [
    ("数据来源", "HTTP", "查询数据"),
    ("数据来源", "WS", "实时推送"),
    ("listedSector", "0", "全部"),
    ("listedSector", "1", "沪市主板"),
    ("listedSector", "2", "深市主板"),
    ("listedSector", "3", "科创板"),
    ("listedSector", "4", "创业板"),
    ("listedSector", "5", "北交所（若服务返回）"),
    ("limitType", "-1 / 0 / 1", "跌停 / 非涨跌停 / 涨停"),
    ("limit/monitor.type（请求）", "0", "默认全部口径；这是请求筛选值"),
    ("type（涨跌停异动）", "1 / 2 / 4 / 8", "涨停封板 / 打开涨停（炸板）/ 跌停封板 / 打开跌停（撬板）"),
    ("boardType", "0 / 1", "普通板 / 一字板"),
    ("BiddingLimitType", "0 / 1", "无竞价涨停标记 / 有竞价涨停标记"),
    ("market", "sh / sz / bj / hk", "上海 / 深圳 / 北交所 / 港股"),
    ("marketid", "0 / 1 / 118 / 156 / 158", "深圳 / 上海 / 港股 / 纳斯达克 / 美股其他市场"),
    ("xsfx", "1 / 2", "卖 / 买"),
    ("tradetype", "0", "成交"),
    ("upDownType", "up / down", "上涨/涨停 / 下跌/跌停"),
    ("direction / typeDirection", "up / down", "上涨/买入 / 下跌/卖出"),
    ("STType", "0", "默认不过滤特殊处理股票"),
    ("tradingType", "0", "全部交易类型"),
    ("sortFlag", "true / false", "启用排序 / 不排序"),
    ("category", "gang / public", "席位/营业部排行 / 公开异动"),
    ("is* / will*", "false / true", "否 / 是"),
    ("stock/anomalies.typeCode", "37 / 38", "大笔买入 / 大笔卖出"),
    ("typeCode", "*.HY / *.GN / *.FG", "行业板块 / 概念板块 / 风格板块"),
]

FIELD_LABELS = {
    "symbol": "代码",
    "SecuCode": "代码",
    "Market_Symbol": "代码",
    "Prod_code": "代码",
    "ProdCode": "代码",
    "name": "名称",
    "SecuAbbr": "名称",
    "Prod_name": "名称",
    "ProdName": "名称",
    "market": "市场",
    "Last_px": "现价",
    "LastPrice": "现价",
    "lastPx": "现价",
    "newprice": "现价",
    "yclose": "昨收",
    "open": "开盘",
    "high": "最高",
    "low": "最低",
    "close": "收盘",
    "junj": "均价",
    "amount": "成交额",
    "volume": "成交量",
    "xianl": "成交量",
    "xsfx": "方向",
    "direction": "方向",
    "typeDirection": "方向",
    "category": "分类",
    "tradenum": "笔数",
    "tradetype": "类型",
    "unmatchvol": "未匹配量",
    "flag": "标记",
    "Px_change_rate": "涨跌幅",
    "PxChangeRate": "涨跌幅",
    "pxChangeRate": "涨跌幅",
    "px_change_rate": "涨跌幅",
    "Business_balance": "成交额",
    "Business_amount": "成交量",
    "Turnover_ratio": "换手率",
    "Exchange_Symbol": "市场",
    "Amplitude": "振幅",
    "BusinessAmount": "成交量",
    "BusinessAmountIn": "主买量",
    "BusinessAmountOut": "主卖量",
    "BusinessBalance": "成交额",
    "CurrentAmount": "当前额",
    "Day2ClosePx": "前日收盘",
    "Day2turnoverRatio": "前日换手",
    "DownLimitNum": "跌停数",
    "DynPbRate": "动态市净率",
    "FallCount": "下跌数",
    "Fundflow": "资金流",
    "HighPx": "最高",
    "LowPx": "最低",
    "Min5": "近5分钟",
    "OpenPrice": "开盘",
    "PeRate": "市盈率",
    "PreClosePx": "昨收",
    "Preclose_px": "昨收",
    "Open_px": "开盘",
    "High_px": "最高",
    "Low_px": "最低",
    "PxChange": "涨跌额",
    "RiseCount": "上涨数",
    "RiseFirstGrp": "领涨股",
    "FallFirstGrp": "领跌股",
    "MemberCount": "成分数",
    "MainFundFlowRatio": "主力占比",
    "is*ST": "风险标记",
    "isST": "ST标记",
    "limitType": "涨跌停方向",
    "listedSector": "板块类型",
    "min5Chgpct": "5分钟涨跌",
    "tradingDay": "交易日",
    "time": "时间",
    "type": "类型/状态",
    "InstrumentID": "代码",
    "InstrumentName": "名称",
    "LastPrice": "现价",
    "PreClosePrice": "昨收",
    "RiseCount": "上涨",
    "FallCount": "下跌",
    "FlatCount": "平盘",
    "upLimit": "涨停",
    "downLimit": "跌停",
    "FlowMainNetIn": "主力净流入",
    "MainFundFlowRatio": "主力占比",
    "TradingDay": "交易日",
    "Tradingday": "交易日",
    "BiddingLimitType": "竞价状态",
    "boardType": "板型",
    "typeCode": "板块编码",
    "HqTypeCode": "板块类型",
    "marketid": "市场编号",
    "isDragon": "龙虎标记",
    "upLimitType": "涨停形态",
    "flag": "扩展标记",
    # 来源数据中的统计、异动、板块和嵌套对象字段。
    "code": "编码",
    "message": "提示",
    "status": "状态",
    "state": "状态",
    "stateCode": "状态编码",
    "display": "显示",
    "count": "数量",
    "total": "总数",
    "totalNumber": "总数",
    "infos": "明细",
    "data": "数据",
    "items": "项目",
    "tradeDate": "交易日",
    "chipSummary": "筹码摘要",
    "meanPrice": "持仓均价",
    "vMaxPrice": "最大筹码价",
    "winRatio": "获利比例",
    "zc": "支撑位",
    "zl": "阻力位",
    "costL70": "70%成本下沿",
    "costH70": "70%成本上沿",
    "jzd70": "70%集中度",
    "costL90": "90%成本下沿",
    "costH90": "90%成本上沿",
    "jzd90": "90%集中度",
    "shapes": "筹码形态",
    "shapesDetail": "形态详情",
    "shapesQuShi": "形态趋势",
    "shapeSummary": "形态摘要",
    "price": "价格",
    "rows": "行数据",
    "records": "记录",
    "list": "列表",
    "currentTime": "当前时间",
    "updateTime": "更新时间",
    "datetime": "时间",
    "alarmTime": "异动时间",
    "quoteTime": "行情时间",
    "displayData": "展示数据",
    "priceSnapshot": "触发价格",
    "pxChangeRateSnapshot": "触发涨跌幅",
    "typeName": "异动名称",
    "typeDirection": "异动方向",
    "tradeStatus": "交易状态",
    "countUp": "上涨数量",
    "countDown": "下跌数量",
    "countFlat": "平盘数量",
    "countUpLimit": "涨停数量",
    "countDownLimit": "跌停数量",
    "countUpBoard": "涨停板数",
    "countDownBoard": "跌停板数",
    "countUpBrokenBoard": "涨停开板数",
    "countDownBrokenBoard": "跌停开板数",
    "countBrokenBoard": "开板总数",
    "openBoardProfit": "开板收益",
    "openUpBoardProfit": "开涨停收益",
    "openDownBoardProfit": "开跌停收益",
    "preTodayProfit": "昨日收益",
    "prodCode": "板块代码",
    "prodName": "板块名称",
    "plateCategory": "板块分类",
    "platePxChangeRate": "板块涨跌幅",
    "sector": "所属板块",
    "maxCorrGnSector": "最相关板块",
    "relationReason": "关联原因",
    "corr": "相关度",
    "marketStocks": "板块成分股",
    "achievementStocks": "强势股",
    "popularityStocks": "人气股",
    "relatedStocks": "相关股票",
    "riseFirstGrp": "领涨股",
    "fallFirstGrp": "领跌股",
    "netFundFlow": "资金净流入",
    "netTurnover": "净成交额",
    "FlowMainNetIn": "主力净流入",
    "FinanceValue": "融资余额",
    "SecurityValue": "融券余额",
    "ExchangeID": "市场编号",
    "WAvgPx": "成交均价",
    "wAvgPx": "成交均价",
    "biddingPxChangeRate": "竞价涨跌幅",
    "boardType": "板型",
    "brokenBoard": "开板标记",
    "BusinessAmount": "成交量",
    "CirculationAmount": "流通股本",
    "circulationValue": "流通市值",
    "businessBalance": "成交额",
    "UpDownLimitAmount": "涨跌停成交量",
    "LimitShareMax": "涨停最大量",
    "LimitShareDownMax": "跌停最大量",
    "limitShare": "封单量",
    "countContBoard": "连续涨停板数",
    "countContLimit": "连续涨停数",
    "HistoryCountContLimit": "历史连续涨停数",
    "historyDropStop": "历史跌停次数",
    "HistoryDownType": "历史跌停形态",
    "HistoryUpType": "历史涨停形态",
    "downBrokenBoardTime": "跌停开板时间",
    "upBrokenBoardTime": "涨停开板时间",
    "firstUpTime": "首次涨停时间",
    "latestDownTime": "最近跌停时间",
    "latestUpTime": "最近涨停时间",
    "downPx": "跌停价",
    "upPx": "涨停价",
    "downType": "跌停统计",
    "upType": "涨停统计",
    "dragonNetIn": "龙虎榜净流入",
    "dragonReason": "龙虎榜说明",
    "upReason": "涨停原因",
    "upLimitType": "涨停形态",
    "turnoverRatio": "换手率",
    "issuePrice": "发行价",
    "listedDate": "上市日期",
    "peRate": "市盈率",
    "pbRate": "市净率",
    "staticPeRate": "静态市盈率",
    "ttmPeRate": "滚动市盈率",
    # K 线及通用行情字段。
    "Open": "开盘",
    "High": "最高",
    "Low": "最低",
    "Close": "收盘",
    "Volume": "成交量",
    "Amount": "成交额",
    "PreClose": "昨收",
    "PreSettlement": "昨结",
    "SettlementPrice": "结算价",
    "OpenInterest": "持仓量",
    "TickCount": "成交笔数",
    "AfterTradeAmount": "盘后成交额",
    "AfterTradeVolume": "盘后成交量",
    "TradingDay": "交易日",
    "Time": "时间",
    "Period": "周期",
    "ReqID": "请求编号",
    "servicetype": "服务类型",
    "StartID": "起始编号",
    "EndID": "结束编号",
    # 个股实时帧中的盘口字段。
    "bidGrp": "买方队列",
    "offerGrp": "卖方队列",
    "entrustPx": "委托价",
    "entrustVol": "委托量",
    "totalEntrustAmount": "委托总量",
    "totalEntrustBalance": "委托总额",
    "businessAmount": "成交量",
    "businessAmountIn": "主买量",
    "businessAmountOut": "主卖量",
    "businessBalance": "成交额",
    "sharesPerHand": "每手股数",
    "preClosePx": "昨收",
    "currentPx": "现价",
}


# 其它专题接口字段，集中维护，避免每个面板各写一套英文转中文逻辑。
FIELD_LABELS.update({
    "ALimit": "A股涨跌幅",
    "APrice": "A股价格",
    "ASymbol": "A股代码",
    "Amarket": "A股市场",
    "Appreciation": "溢价率",
    "CValue": "担保资产价值",
    "Classes": "映射类别",
    "DRCJJME": "当日成交额",
    "DRYE": "当日余额",
    "DRZJLR": "当日资金净流入",
    "DZ": "对照值",
    "Diff": "差额",
    "DynaData": "动态数据",
    "FiSecuValuestr": "融资融券余额文本",
    "FiSecudiff": "融资融券差额",
    "FiSecudiffAdd": "融资融券差额增量",
    "FiSecudiffRatio": "融资融券差额比例",
    "FinaInTVRatio": "融资成交占比",
    "FinaInTVRatiostr": "融资成交占比文本",
    "FinaInTotalstr": "融资余额文本",
    "HLimit": "港股涨跌幅",
    "HPrice": "港股价格",
    "HSymbol": "港股代码",
    "Hmarket": "港股市场",
    "LCG": "领涨股",
    "LCGCode": "领涨股代码",
    "LCGZDF": "领涨股涨跌幅",
    "LCGmarket": "领涨股市场",
    "LSZJLR": "历史资金净流入",
    "MCCJE": "卖出成交额",
    "MRCJE": "买入成交额",
    "Pv": "市值",
    "Rzrqdif": "融资融券差额",
    "SSEChange": "上证指数变动",
    "SSEChangePrecent": "上证指数涨跌幅",
    "Source": "来源",
    "StaticData": "静态数据",
    "StatisticsData": "统计数据",
    "Timestamp": "时间戳",
    "abnormalDes": "异动说明",
    "announcementLink": "公告链接",
    "applyMaxOnline": "网上申购上限",
    "averageStaticPE": "平均静态市盈率",
    "bps": "每股净资产",
    "content": "内容",
    "contentList": "内容列表",
    "currency": "币种",
    "dataTimestamp": "数据时间戳",
    "day5Vol": "5日成交量",
    "eps": "每股收益",
    "epsTtm": "滚动每股收益",
    "epsYear": "年度每股收益",
    "finQuarter": "财报季度",
    "flat": "平盘数量",
    "fiveHyRanking": "5日行业排名",
    "holdBestN": "持仓前N名",
    "imageUrl": "图片地址",
    "industry": "行业",
    "intro": "简介",
    "ipoProceeds": "新股募资额",
    "ipoTitle": "新股发行标题",
    "key": "关键字",
    "minTime": "最小时间",
    "neeqMakerCount": "做市商数量",
    "onNum": "上榜数量",
    "onNumIn": "上榜买入数量",
    "onNumOut": "上榜卖出数量",
    "plannedProceeds": "计划募资额",
    "positiveDetail": "利好详情",
    "positiveIntroduction": "利好简介",
    "ratingDivide": "评级分布",
    "saleSum": "卖出总额",
    "entrustDiff": "委托差额",
    "isPERatio": "市盈率标记",
    "olBefPutBack": "网下回拨量",
    "sectorList": "板块列表",
    "sentiment": "市场情绪",
    "stockList": "股票列表",
    "tags": "标签",
    "timesBB": "炸板次数",
    "todayHyRanking": "今日行业排名",
    "todayMarketRanking": "今日市场排名",
    "title": "标题",
    "tradeDay": "交易日",
    "willSubs": "拟申购",
})


# 通用字段词典：接口新增字段即使还没有专门条目，也尽量生成中文列名。
FIELD_TOKEN_LABELS = {
    "code": "代码",
    "symbol": "代码",
    "name": "名称",
    "market": "市场",
    "exchange": "市场",
    "id": "编号",
    "number": "编号",
    "no": "编号",
    "price": "价格",
    "px": "价格",
    "change": "变动",
    "rate": "比例",
    "pct": "比例",
    "percent": "百分比",
    "amount": "金额",
    "balance": "金额",
    "volume": "数量",
    "vol": "数量",
    "share": "股数",
    "shares": "股数",
    "count": "数量",
    "time": "时间",
    "date": "日期",
    "day": "日期",
    "type": "类型",
    "status": "状态",
    "state": "状态",
    "direction": "方向",
    "category": "分类",
    "board": "板",
    "sector": "板块",
    "plate": "板块",
    "limit": "涨跌停",
    "up": "上涨",
    "down": "下跌",
    "buy": "买",
    "sell": "卖",
    "bid": "买",
    "offer": "卖",
    "open": "开盘",
    "high": "最高",
    "low": "最低",
    "close": "收盘",
    "pre": "前值",
    "current": "当前",
    "last": "最新",
    "first": "首次",
    "latest": "最近",
    "main": "主力",
    "net": "净",
    "flow": "流入",
    "fund": "资金",
    "turnover": "成交",
    "ratio": "比例",
    "value": "数值",
    "total": "总计",
    "history": "历史",
    "reason": "原因",
    "desc": "说明",
    "description": "说明",
    "message": "提示",
    "flag": "标记",
    "tag": "标签",
    "rank": "排行",
    "trade": "交易",
    "trading": "交易",
    "issue": "发行",
    "listed": "上市",
    "bidding": "竞价",
    "broken": "开板",
    "cont": "连续",
    "grp": "分组",
    "snapshot": "快照",
    "display": "展示",
    "relation": "关联",
    "corr": "相关",
    "stock": "股票",
    "finance": "融资",
    "security": "融券",
    "settlement": "结算",
    "interest": "持仓",
    "tick": "成交笔数",
    "after": "盘后",
    "period": "周期",
    "start": "起始",
    "end": "结束",
    "request": "请求",
    "service": "服务",
}


def humanize_field_name(key: str) -> str:
    """将未进入专用字典的英文/驼峰字段转换成可读中文列名。"""
    leaf = str(key).rsplit(".", 1)[-1]
    if leaf in FIELD_LABELS:
        return FIELD_LABELS[leaf]
    if leaf.lower() in {str(name).lower() for name in FIELD_LABELS}:
        for name, label in FIELD_LABELS.items():
            if leaf.lower() == str(name).lower():
                return label
    if leaf in {"is*ST", "isST"}:
        return "风险标记"
    if leaf == "*":
        return "标记"

    # 保留数字片段（例如 min5），把 camelCase 和下划线统一成 token。
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", leaf)
    text = re.sub(r"([A-Za-z])(\d)", r"\1 \2", text)
    text = re.sub(r"(\d)([A-Za-z])", r"\1 \2", text)
    tokens = [token for token in re.split(r"[_\-\s.]+", text) if token]
    labels: list[str] = []
    unknown: list[str] = []
    for token in tokens:
        lowered = token.lower()
        label = FIELD_TOKEN_LABELS.get(lowered)
        if label:
            if not labels or labels[-1] != label:
                labels.append(label)
        elif token.isdigit():
            labels.append(token)
        else:
            unknown.append(token)
    if labels:
        return "".join(labels)
    # 不能臆测陌生字段含义；表头使用中性业务文案。
    return "其他字段"


FIELD_DICTIONARY_ROWS = [("字段映射", raw, meaning) for raw, meaning in sorted(FIELD_LABELS.items())]


def _enum_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return int(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def enum_meaning(key: str, value: Any, context: str = "") -> str | None:
    """返回业务枚举含义；未知值不进入用户界面。"""
    leaf = str(key).rsplit(".", 1)[-1]
    if value in (None, ""):
        return None
    if isinstance(value, bool) and (leaf.startswith("is") or leaf.startswith("will")):
        return "是" if value else "否"
    if leaf in {"is*ST", "isST", "isDragon"}:
        bool_value = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes"}
        return ENUM_MAPS[leaf].get(bool_value)
    mapping = ENUM_MAPS.get(leaf)
    if mapping:
        normalized = str(value).lower() if isinstance(value, str) else value
        if leaf in {"market", "plateTypeCode", "hqTypeCode"}:
            normalized = str(value).lower()
            if leaf == "hqTypeCode":
                mapping = {str(k).lower(): v for k, v in mapping.items()}
        else:
            normalized = _enum_number(value) if _enum_number(value) is not None else value
        if normalized in mapping:
            return mapping[normalized]
    if leaf == "typeCode":
        if any(token in str(context).lower() for token in ("stock/anomalies", "stock\\anomalies", "stock_anomal")):
            normalized = _enum_number(value)
            if normalized in STOCK_ANOMALY_TYPES:
                return STOCK_ANOMALY_TYPES[normalized]
        text = str(value).upper()
        if text.endswith(".HY"):
            return "行业板块"
        if text.endswith(".GN"):
            return "概念板块"
        if text.endswith(".FG"):
            return "风格板块"
    if leaf == "type" and any(token in str(context).lower() for token in ("limit", "anomaly", "异动")):
        normalized = _enum_number(value)
        return LIMIT_EVENT_TYPES.get(normalized)
    return None


def format_enum_value(key: str, value: Any, context: str = "") -> str | None:
    meaning = enum_meaning(key, value, context)
    leaf = str(key).rsplit(".", 1)[-1]
    context_lower = str(context).lower()
    enum_field = leaf in ENUM_MAPS or leaf == "typeCode" or (leaf == "type" and any(token in context_lower for token in ("limit", "anomaly", "异动")))
    if meaning is None:
        return "其他" if enum_field else None
    if isinstance(value, bool):
        return meaning
    return meaning


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt_number(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "—"
    number = as_float(value, float("nan"))
    if number != number:
        return str(value)
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f}亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.2f}万"
    if number == int(number):
        return str(int(number))
    return f"{number:.{digits}f}"


def fmt_percent(value: Any, assume_fraction: bool = False) -> str:
    number = as_float(value, float("nan"))
    if number != number:
        return "—"
    if assume_fraction or abs(number) <= 1.0:
        number *= 100
    return f"{number:+.2f}%"


def value_ci(data: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data:
            return data[key]
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return default


def flatten_dict(value: Any, prefix: str = "", depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix or "值": value}
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict) and depth < 1:
            result.update(flatten_dict(item, name, depth + 1))
        elif isinstance(item, (dict, list)):
            # 保留结构，交给表格的中文摘要格式化器处理；这里直接转 JSON 会丢掉字段含义。
            result[name] = item
        else:
            result[name] = item
    return result


def records_from(value: Any) -> list[dict[str, Any]]:
    """从不统一的 JSON 外壳中提取可展示的记录数组。"""
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return value
        for item in value:
            found = records_from(item)
            if found:
                return found
        return []
    if not isinstance(value, dict):
        return []
    for key in ("data", "Stocks", "plate", "rows", "items", "list", "records", "KlineData"):
        if key in value:
            found = records_from(value[key])
            if found:
                return found
    for item in value.values():
        if isinstance(item, (dict, list)):
            found = records_from(item)
            if found:
                return found
    # 接口常见的“统计信息 + 空列表”外壳不能当成一条业务记录展示。
    collection_keys = ("data", "Stocks", "plate", "rows", "items", "list", "records", "infos", "KlineData")
    present = [key for key in collection_keys if key in value]
    if present and all(value.get(key) in (None, [], {}) for key in present):
        return []
    return [value] if value else []


def normalize_records(value: Any) -> list[dict[str, Any]]:
    rows = records_from(value)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        flat = flatten_dict(row)
        normalized.append(flat if flat else {"值": row})
    return normalized


def empty_payload_message(payload: Any) -> str:
    """给空响应一个可操作的说明，而不是让用户看到空白表格。"""
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if data is None:
            return "暂无数据 · 接口 data 为空"
        if data in ([], {}):
            return "暂无数据 · 接口返回空结果"
        if isinstance(data, dict):
            for key in ("infos", "rows", "items", "list", "records", "plate", "KlineData"):
                if key in data and data.get(key) in (None, [], {}):
                    return f"暂无数据 · {public_label(key)}为空"
    if payload in (None, [], {}):
        return "暂无数据 · 接口返回空结果"
    return "暂无数据 · 当前筛选条件没有记录"


def date_text(value: Any) -> str | None:
    """把交易日字段统一成 YYYY-MM-DD。"""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 100000000000:
            number /= 1000
        if number > 100000000:
            try:
                return time.strftime("%Y-%m-%d", time.localtime(number))
            except (OverflowError, OSError, ValueError):
                return None
    text = str(value).strip()
    match = re.match(r"^(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else None


def datetime_text(value: Any) -> str:
    """把毫秒/秒时间戳显示成用户可读的本地时间。"""
    number = as_float(value, float("nan"))
    if number == number and number > 100000000:
        timestamp = number / 1000 if number > 100000000000 else number
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except (OverflowError, OSError, ValueError):
            pass
    return str(value) if value not in (None, "") else "—"


def clock_text(value: Any) -> str:
    """显示当天异动时间，保持业务页面的 HH:MM:SS 形式。"""
    rendered = datetime_text(value)
    return rendered[11:] if len(rendered) >= 19 and rendered[10] == " " else rendered


def latest_trading_day(payload: Any) -> str | None:
    candidates: list[str] = []
    if isinstance(payload, dict):
        raw_data = payload.get("data")
        if isinstance(raw_data, list):
            for item in raw_data:
                rendered = date_text(item)
                if rendered:
                    candidates.append(rendered)
    for row in normalize_records(payload):
        for key, value in row.items():
            if str(key).rsplit(".", 1)[-1].lower() in {"tradingday", "trading_day", "marketdate", "date"}:
                rendered = date_text(value)
                if rendered:
                    candidates.append(rendered)
    return max(candidates) if candidates else None


def market_code(value: str) -> tuple[str, str]:
    text = value.strip().upper().replace(".", "")
    if text[:2] in {"SH", "SZ", "HK", "US"}:
        return text[:2].lower(), text[2:]
    if text.isdigit() and len(text) == 6:
        return ("sh" if text.startswith(("5", "6", "9")) else "sz"), text
    return "sz", text


def endpoint_key(spec: dict[str, Any]) -> str:
    return f"{spec.get('method', 'GET')} {spec.get('path', '')}"


def public_endpoint_name(spec: dict[str, Any], index: int = 0) -> str:
    """把目录中的接口显示成业务名称，不把内部路径渲染到用户界面。"""
    name = normalize_display_text(spec.get("name", ""))
    if not name or "/" in name or "://" in name:
        return f"数据方法 {index + 1}"
    if not any("\u4e00" <= character <= "\u9fff" for character in name):
        return humanize_field_name(name)
    return name


def public_payload_summary(value: Any) -> str:
    """给接口调试区提供摘要，避免把原始响应报文直接显示给用户。"""
    if isinstance(value, list):
        return f"请求完成 · 返回 {len(value)} 条业务数据"
    if isinstance(value, dict):
        rows = records_from(value)
        if rows:
            return f"请求完成 · 返回 {len(rows)} 条业务数据"
        return "请求完成 · 当前没有可展示的数据"
    return "请求完成 · 当前没有可展示的数据"


def public_label(key: str, context: str = "") -> str:
    leaf = key.split(".")[-1]
    context_lower = str(context).lower()
    key_lower = str(key).lower()
    if any("\u4e00" <= character <= "\u9fff" for character in leaf):
        return leaf
    if key_lower.startswith("sector."):
        sector_labels = {
            "name": "所属板块",
            "market": "板块市场",
            "symbol": "板块代码",
            "typecode": "板块类型",
            "lastpx": "板块现价",
            "pxchangerate": "板块涨跌幅",
        }
        if leaf.lower() in sector_labels:
            return sector_labels[leaf.lower()]
    if key_lower.startswith("maxcorrgnsector."):
        related_labels = {
            "name": "相关板块",
            "market": "相关板块市场",
            "symbol": "相关板块代码",
            "typecode": "相关板块类型",
            "corr": "相关度",
            "relationreason": "关联原因",
        }
        if leaf.lower() in related_labels:
            return related_labels[leaf.lower()]
    if leaf == "type" and any(token in context_lower for token in ("limit", "anomaly", "异动")):
        return "异动类型"
    if leaf.lower() == "typecode" and any(token in context_lower for token in ("stock/anomalies", "stock\\anomalies", "stock_anomal")):
        return "异动类型"
    return FIELD_LABELS.get(leaf, FIELD_LABELS.get(key, humanize_field_name(leaf)))


def _clip_text(value: Any, limit: int = 54) -> str:
    text = normalize_display_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_scalar_value(key: str, value: Any, context: str = "", mask_names: bool = False) -> str:
    """格式化一个叶子值，复杂对象由 format_complex_value 负责。"""
    if value is None or value == "":
        return "—"
    if mask_names and is_name_field(key):
        return display_name(_clip_text(value), True)
    enum_value = format_enum_value(key, value, context)
    if enum_value is not None:
        return enum_value
    leaf = str(key).rsplit(".", 1)[-1]
    lowered = leaf.lower()
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "time" in lowered or lowered in {"tradingday", "trading_day", "listeddate"}:
            number = as_float(value, float("nan"))
            if number == number and number > 100000000:
                timestamp = number / 1000 if number > 100000000000 else number
                try:
                    date_format = "%Y-%m-%d %H:%M:%S" if "time" in lowered else "%Y-%m-%d"
                    return time.strftime(date_format, time.localtime(timestamp))
                except (OverflowError, OSError, ValueError):
                    return str(value)
            return str(value)
        if any(token in lowered for token in ("code", "symbol", "date", "id")):
            return str(value)
        if any(token in lowered for token in ("rate", "percent", "pct", "change_rate", "changerate")):
            number = as_float(value)
            if "sector/quote" in str(context).lower() and lowered in {"pxchangerate", "min5"}:
                number /= 100
            if abs(number) <= 1:
                number *= 100
            return f"{number:+.2f}%"
        return fmt_number(value)
    if isinstance(value, str) and ("time" in lowered or lowered in {"tradingday", "trading_day", "listeddate"}):
        number = as_float(value, float("nan"))
        if number == number and number > 100000000:
            timestamp = number / 1000 if number > 100000000000 else number
            try:
                date_format = "%Y-%m-%d %H:%M:%S" if "time" in lowered else "%Y-%m-%d"
                return time.strftime(date_format, time.localtime(timestamp))
            except (OverflowError, OSError, ValueError):
                return str(value)
    return _clip_text(value)


def format_complex_value(key: str, value: Any, context: str = "", mask_names: bool = False) -> str:
    """把嵌套对象/数组压成有字段含义的摘要，避免表格直接显示 JSON。"""
    if isinstance(value, dict):
        preferred = (
            "name", "prodName", "symbol", "market", "typeCode", "state", "stateCode",
            "countBoard", "countDays", "rate", "lastPx", "pxChangeRate", "issuePrice",
            "listedDate", "corr", "relationReason",
        )
        ordered = list(preferred) + [str(child_key) for child_key in value]
        seen: set[str] = set()
        parts: list[str] = []
        for child_key in ordered:
            if child_key in seen or child_key not in value:
                continue
            seen.add(child_key)
            child_value = value[child_key]
            if child_value is None or child_value == "":
                continue
            if isinstance(child_value, (dict, list)):
                rendered = format_complex_value(child_key, child_value, context, mask_names)
            else:
                rendered = _format_scalar_value(child_key, child_value, context, mask_names)
            if rendered in {"", "—"}:
                continue
            parts.append(f"{public_label(child_key, context)}：{rendered}")
            if len(parts) >= 6:
                break
        return "；".join(parts) if parts else "无内容"
    if isinstance(value, list):
        if not value:
            return "空列表"
        summaries: list[str] = []
        for item in value[:4]:
            if isinstance(item, dict):
                # 股票数组优先直接显示股票名称，盘口数组再显示其关键字段。
                identity_key = next((candidate for candidate in ("name", "prodName", "symbol", "state", "typeName") if value_ci(item, candidate) not in (None, "")), None)
                identity = value_ci(item, identity_key) if identity_key else None
                if identity not in (None, ""):
                    identity_text = _clip_text(identity, 24)
                    if mask_names and identity_key and is_name_field(identity_key):
                        identity_text = display_name(identity_text, True)
                    summaries.append(identity_text)
                else:
                    summaries.append(_clip_text(format_complex_value(key, item, context, mask_names), 44))
            else:
                summaries.append(_clip_text(_format_scalar_value(key, item, context, mask_names), 24))
        suffix = "、".join(summaries)
        return f"{len(value)}项" + (f"：{suffix}" if suffix else "")
    return _format_scalar_value(key, value, context, mask_names)


class D6HttpClient:
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        self.events = events
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="d6-http")

    def request(
        self,
        tag: str,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> None:
        if self.closed:
            return
        self.executor.submit(self._run, tag, method.upper(), url, params or {}, body)

    def _run(self, tag: str, method: str, url: str, params: dict[str, Any], body: Any) -> None:
        try:
            if params:
                separator = "&" if "?" in url else "?"
                url = url + separator + urlencode(
                    {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in params.items()}
                )
            data = None
            headers = {"Accept": "application/json"}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            request = Request(url, data=data, headers=headers, method=method)
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8", "replace")
                status = int(response.status)
            try:
                payload: Any = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            self.events.put(("http", {"tag": tag, "ok": True, "status": status, "data": payload, "url": url}))
        except HTTPError as error:
            raw = error.read().decode("utf-8", "replace") if error.fp else str(error)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            self.events.put(("http", {"tag": tag, "ok": False, "status": error.code, "data": payload, "url": url}))
        except (URLError, OSError, TimeoutError, ValueError) as error:
            self.events.put(("http", {"tag": tag, "ok": False, "status": 0, "error": str(error), "url": url}))

    def close(self) -> None:
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)


class D6WebSocket:
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        self.events = events
        self.url = ""
        self.app: Any = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.send_lock = threading.Lock()

    def start(self, url: str) -> bool:
        if websocket is None:
            self.events.put(("ws_state", "missing"))
            return False
        self.stop()
        self.url = url
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="d6-ws", daemon=True)
        self.thread.start()
        return True

    def _run(self) -> None:
        if websocket is None:
            return
        while not self.stop_event.is_set():
            self.app = websocket.WebSocketApp(
                self.url,
                on_open=lambda _ws: self.events.put(("ws_state", "open")),
                on_message=lambda _ws, message: self._message(message),
                on_error=lambda _ws, error: self.events.put(("ws_error", str(error))),
                on_close=lambda _ws, code, reason: self.events.put(("ws_state", f"closed:{code or ''}")),
            )
            try:
                self.app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as error:  # pragma: no cover - depends on client/network
                self.events.put(("ws_error", str(error)))
            if not self.stop_event.is_set():
                self.stop_event.wait(1.5)

    def _message(self, message: str) -> None:
        try:
            value: Any = json.loads(message)
        except json.JSONDecodeError:
            value = message
        self.events.put(("ws_message", value))

    def send(self, value: dict[str, Any]) -> bool:
        with self.send_lock:
            app = self.app
            if app is None or app.sock is None or not app.sock.connected:
                return False
            try:
                app.send(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
                return True
            except Exception as error:
                self.events.put(("ws_error", str(error)))
                return False

    def stop(self) -> None:
        self.stop_event.set()
        app = self.app
        if app is not None:
            try:
                app.close()
            except Exception:
                pass
        if self.thread and self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=1.2)
        self.thread = None
        self.app = None


class DataTable(tk.Frame):
    def __init__(self, parent: tk.Widget, title: str, max_rows: int = 120, source: str = "HTTP", context: str = "", show_header: bool = True) -> None:
        super().__init__(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.max_rows = max_rows
        self.source = source.upper()
        self.context = context
        self.title_var = tk.StringVar(value=title)
        self.count_var = tk.StringVar(value="0 条")
        self._rows: list[dict[str, Any]] = []
        self._columns: list[str] | None = None
        self._empty_message = "暂无数据"
        self._on_scroll_bottom: Any = None
        self._scroll_check_after: str | None = None
        if show_header:
            head = tk.Frame(self, bg=TOP, height=28)
            head.pack(fill="x")
            head.pack_propagate(False)
            tk.Label(head, textvariable=self.title_var, bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w").pack(side="left", padx=8)
            tk.Label(head, textvariable=self.count_var, bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="right", padx=8)
            source_fg, source_bg = SOURCE_META.get(self.source, (MUTED, PANEL_ALT))
            tk.Label(head, text=self.source, bg=source_bg, fg=source_fg, font=FONT_TINY, padx=5, pady=1).pack(side="right", padx=(4, 0))
        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, show="headings", selectmode="browse", style="D6.Treeview")

        def scroll_y_command(*args: Any) -> None:
            self.tree.yview(*args)
            self._check_scroll_bottom()

        scroll_y = ttk.Scrollbar(body, orient="vertical", command=scroll_y_command)
        scroll_x = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._copy_selected)

        def schedule_scroll_check(_event: tk.Event) -> None:
            # yview 在鼠标/键盘事件的默认处理后才会更新，延迟到 idle
            # 可以同时覆盖滚轮、键盘翻页和 Linux 的 Button-4/5。
            if self._scroll_check_after is None:
                try:
                    self._scroll_check_after = self.after_idle(self._check_scroll_bottom)
                except tk.TclError:
                    self._scroll_check_after = None

        self.tree.bind("<MouseWheel>", schedule_scroll_check, add="+")
        self.tree.bind("<Button-4>", schedule_scroll_check, add="+")
        self.tree.bind("<Button-5>", schedule_scroll_check, add="+")
        self.tree.bind("<KeyRelease>", schedule_scroll_check, add="+")
        self.tree.tag_configure("up", foreground=RED)
        self.tree.tag_configure("down", foreground=GREEN)
        self.tree.tag_configure("normal", foreground=TEXT)

    def _check_scroll_bottom(self) -> None:
        self._scroll_check_after = None
        callback = self._on_scroll_bottom
        if callback is None:
            return
        try:
            first, last = self.tree.yview()
            # 只有确实有可滚动内容且用户已经到达底部时才触发；程序
            # set_rows() 不会调用这个检查，避免首帧自动连发分页请求。
            if float(first) > 0.0 and float(last) >= 0.999:
                callback()
        except (tk.TclError, TypeError, ValueError):
            return

    def set_context(self, context: str) -> None:
        self.context = context

    def refresh_rows(self) -> None:
        """Repaint cached rows after a display-only setting changes."""

        self._render_rows(self._rows, self._columns, self._empty_message)

    def _copy_selected(self, _event: tk.Event) -> None:
        item = self.tree.focus()
        if not item:
            return
        values = self.tree.item(item, "values")
        self.clipboard_clear()
        self.clipboard_append("\t".join(str(value) for value in values))

    def set_rows(
        self,
        rows: list[dict[str, Any]],
        columns: list[str] | None = None,
        empty_message: str = "暂无数据",
    ) -> None:
        self._rows = [dict(row) if isinstance(row, dict) else row for row in rows]
        self._columns = list(columns) if columns is not None else None
        self._empty_message = empty_message
        self._render_rows(self._rows, self._columns, self._empty_message)

    def _render_rows(
        self,
        rows: list[dict[str, Any]],
        columns: list[str] | None,
        empty_message: str,
    ) -> None:
        rows = rows[: self.max_rows]
        is_empty = not rows
        if is_empty:
            rows = [{"状态": empty_message}]
            columns = ["状态"]
        if columns is None:
            keys: list[str] = []
            hidden_columns = {"direction", "typeDirection"} if "stock/anomalies" in self.context.lower() else set()
            default_priority = [
                "symbol", "SecuCode", "Market_Symbol", "name", "SecuAbbr", "Prod_name", "market",
                "limitType", "listedSector", "type", "boardType", "BiddingLimitType",
                "typeCode", "plateTypeCode", "hqTypeCode", "direction", "typeDirection", "category",
                "xsfx", "tradetype", "STType", "tradingType",
            ]
            priority = default_priority
            for marker, preferred in TABLE_PRIORITIES.items():
                if marker in self.context.lower():
                    priority = preferred + [key for key in default_priority if key not in preferred]
                    break
            for key in priority:
                if key not in hidden_columns and any(key in row for row in rows):
                    keys.append(key)
            for row in rows:
                for key in row:
                    if key not in hidden_columns and key not in keys:
                        keys.append(key)
            columns = keys[:12] or ["状态"]

        current_columns = list(self.tree["columns"])
        columns_changed = current_columns != list(columns)
        if columns_changed:
            self.tree.configure(columns=columns)
            for column in columns:
                self.tree.heading(column, text=public_label(column, self.context), anchor="center")
                width = 86 if column in {"symbol", "SecuCode", "Market_Symbol"} else 112
                if column.lower() in {"name", "secuabbr", "prod_name", "prodname"}:
                    width = 130
                if column in {"limitType", "listedSector", "boardType", "typeCode", "plateTypeCode", "hqTypeCode", "STType", "tradingType"}:
                    width = 150
                if column in {"type", "BiddingLimitType", "upLimitType"}:
                    width = 190
                if "time" in column.lower() or column.lower() in {"datetime", "tradingday", "date"}:
                    width = max(width, 150)
                if column.lower() in {"alarmtime", "quotetime", "updatetime"}:
                    width = max(width, 210)
                if column in {"时间", "异动时间", "行情时间", "更新时间"}:
                    width = max(width, 210)
                if column in {"displayData", "typeName", "sector.name"}:
                    width = max(width, 125)
                if column in {"板块", "板块名称", "代表个股", "个股涨跌幅", "类型", "所属板块", "异动类型", "异动数量", "异动时价格", "异动时涨跌幅", "板块涨跌幅"}:
                    width = max(width, 135)
                if column in {"领涨股", "领跌股"}:
                    width = max(width, 220)
                if len(public_label(column, self.context)) >= 7:
                    width = max(width, 145)
                self.tree.column(column, width=width, minwidth=55, anchor="e")

        existing_children = list(self.tree.get_children())
        saved_selection = self.tree.selection()
        saved_yview = self.tree.yview()

        if columns_changed or is_empty or (len(existing_children) == 1 and self.tree.item(existing_children[0], "values") == (empty_message,)):
            self.tree.delete(*existing_children)
            for index, row in enumerate(rows):
                row_iid = str(row.get("_iid") or f"row_{index}")
                values = [self._format_cell(key, row.get(key)) for key in columns]
                tag = self._row_tag(row)
                self.tree.insert("", "end", iid=row_iid, values=values, tags=(tag,))
            if saved_selection:
                valid_sel = [s for s in saved_selection if self.tree.exists(s)]
                if valid_sel:
                    self.tree.selection_set(valid_sel)
            if saved_yview and saved_yview[0] > 0.01:
                self.tree.yview_moveto(saved_yview[0])
        else:
            uses_stable_iids = any("_iid" in row for row in rows)
            if uses_stable_iids:
                existing_set = set(existing_children)
                target_iids: list[str] = []
                for index, row in enumerate(rows):
                    row_iid = str(row.get("_iid") or f"row_{index}")
                    target_iids.append(row_iid)
                    values = [self._format_cell(key, row.get(key)) for key in columns]
                    tag = self._row_tag(row)
                    if row_iid in existing_set:
                        curr_vals = self.tree.item(row_iid, "values")
                        curr_tags = self.tree.item(row_iid, "tags")
                        if tuple(str(v) for v in curr_vals) != tuple(str(v) for v in values):
                            self.tree.item(row_iid, values=values)
                        if tuple(curr_tags) != (tag,):
                            self.tree.item(row_iid, tags=(tag,))
                    else:
                        self.tree.insert("", index, iid=row_iid, values=values, tags=(tag,))
                        existing_set.add(row_iid)
                target_set = set(target_iids)
                for item in existing_children:
                    if item not in target_set:
                        self.tree.delete(item)
                # 新成交通常只会插入顶部，分页历史只会追加底部；对异常
                # 顺序变化也用 move 修正，避免 delete + insert 破坏焦点。
                for index, row_iid in enumerate(target_iids):
                    if self.tree.index(row_iid) != index:
                        self.tree.move(row_iid, "", index)
            else:
                common_len = min(len(existing_children), len(rows))
                for i in range(common_len):
                    item = existing_children[i]
                    row = rows[i]
                    values = [self._format_cell(key, row.get(key)) for key in columns]
                    tag = self._row_tag(row)
                    curr_vals = self.tree.item(item, "values")
                    curr_tags = self.tree.item(item, "tags")
                    if tuple(str(v) for v in curr_vals) != tuple(str(v) for v in values):
                        self.tree.item(item, values=values)
                    if tuple(curr_tags) != (tag,):
                        self.tree.item(item, tags=(tag,))
                if len(rows) > len(existing_children):
                    for i in range(len(existing_children), len(rows)):
                        row = rows[i]
                        row_iid = str(row.get("_iid") or f"row_{i}")
                        values = [self._format_cell(key, row.get(key)) for key in columns]
                        tag = self._row_tag(row)
                        self.tree.insert("", "end", iid=row_iid, values=values, tags=(tag,))
                elif len(rows) < len(existing_children):
                    for item in existing_children[len(rows):]:
                        self.tree.delete(item)

            if saved_selection:
                valid_sel = [s for s in saved_selection if self.tree.exists(s)]
                if valid_sel and set(valid_sel) != set(self.tree.selection()):
                    self.tree.selection_set(valid_sel)
            if saved_yview:
                if saved_yview[1] >= 0.999:
                    self.tree.yview_moveto(1.0)
                elif saved_yview[0] <= 0.001:
                    self.tree.yview_moveto(0.0)
                else:
                    curr_yview = self.tree.yview()
                    if abs(curr_yview[0] - saved_yview[0]) > 0.01:
                        self.tree.yview_moveto(saved_yview[0])

        new_count = "暂无数据" if is_empty else f"{len(rows)} 条"
        if self.count_var.get() != new_count:
            self.count_var.set(new_count)

    def _format_cell(self, key: str, value: Any) -> str:
        privacy_enabled = bool(getattr(self.winfo_toplevel(), "_privacy_mode_enabled", False))
        if isinstance(value, (dict, list)):
            return format_complex_value(key, value, self.context, privacy_enabled)
        return _format_scalar_value(key, value, self.context, privacy_enabled)

    @staticmethod
    def _row_tag(row: dict[str, Any]) -> str:
        for key, value in row.items():
            lowered = str(key).lower()
            if key in {"涨跌幅", "板块涨跌幅", "异动时涨跌幅", "涨跌"}:
                try:
                    number = float(str(value).replace("%", "").replace("+", ""))
                except (TypeError, ValueError):
                    number = 0
                if number > 0:
                    return "up"
                if number < 0:
                    return "down"
            if any(token in lowered for token in ("change_rate", "changerate", "pxchange", "updown")):
                number = as_float(value, 0)
                if number > 0:
                    return "up"
                if number < 0:
                    return "down"
            if lowered in {"xsfx", "direction", "方向"}:
                if str(value) in {"2", "买", "buy", "B"}:
                    return "up"
                if str(value) in {"1", "卖", "sell", "S"}:
                    return "down"
        return "normal"

    def set_payload(self, payload: Any) -> None:
        rows = normalize_records(payload)
        self.set_rows(rows, empty_message=empty_payload_message(payload) if not rows else "暂无数据")


class D6Gui:
    def __init__(self, root: tk.Tk, http_base: str = HTTP_BASE, ws_url: str = WS_URL, code: str = DEFAULT_CODE) -> None:
        self.root = root
        self.http_base = http_base.rstrip("/")
        self.ws_url = ws_url
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.http = D6HttpClient(self.events)
        self.ws = D6WebSocket(self.events)
        self.catalog: dict[str, Any] = {}
        self.endpoints: list[dict[str, Any]] = []
        self.endpoint_by_path: dict[str, dict[str, Any]] = {}
        self.http_data: dict[str, Any] = {}
        self.live: dict[str, Any] = {}
        self._live_dirty_types: set[int] = set()
        self.latest_trading_day: str | None = None
        self.message_count = 0
        self.last_message_at = 0.0
        self.render_pending = False
        self.closed = False
        self.refresh_after: str | None = None
        self.privacy_mode = False
        self.root._privacy_mode_enabled = False
        self.code_var = tk.StringVar(value=code)
        self.limit_distribution_data: dict[str, Any] = {}
        self.limit_trend_data: list[dict[str, Any]] = []
        self.capital_flow_data: list[dict[str, Any]] = []
        self.stock_chip_days: list[dict[str, Any]] = []
        self.stock_chip_selected: dict[str, Any] | None = None
        self.stock_chip_selected_date: str | None = None
        self.stock_trades: list[dict[str, Any]] = []
        self._trade_rows_by_key: dict[tuple, dict[str, Any]] = {}
        self._trade_seen_keys: set[tuple] = set()
        self._trade_loading: bool = False
        self._trade_has_more: bool = True
        self._trade_requested_num: int = TRADE_PAGE_SIZE
        self._trade_symbol: str = ""
        self._trade_request_no: int = 5
        self._trade_pending_no: int | None = None
        self._trade_pending_num: int | None = None
        self._trade_generation: int = 0
        self._trade_request_generations: dict[int, int] = {}
        self._last_intraday_draw_sig: Any = None
        self.trend_hover_index: dict[str, int | None] = {"limit": None, "change": None, "capital": None}
        self.capital_flow_title_var = tk.StringVar(value="主力净流入")
        self.stock_chip_status_var = tk.StringVar(value="等待筹码数据")
        self.stock_chip_date_var = tk.StringVar(value="—")
        self.stock_chip_summary_var = tk.StringVar(value="移动鼠标到 K 线上查看对应交易日")
        self.status_var = tk.StringVar(value="未连接")
        self.message_var = tk.StringVar(value="0")
        self.updated_var = tk.StringVar(value="—")
        self.tab_status_var = tk.StringVar(value="等待市场数据")
        self.raw_response: tk.Text | None = None

        self.root.title("d6 · 市场行情大屏")
        self.root.geometry("1920x1080")
        self.root.minsize(1360, 760)
        self.root.configure(bg=BG)
        if self.root.tk.call("tk", "windowingsystem") == "win32":
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build_style()
        self._build_topbar()
        self._build_tabs()
        self.root.after(60, self._poll_events)
        self.root.after(180, self._load_catalog)
        self.root.after(700, self.connect)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("D6.TNotebook", background=BG, borderwidth=0)
        style.configure("D6.TNotebook.Tab", background=TOP, foreground=MUTED, padding=(13, 7), font=FONT_CN)
        style.map("D6.TNotebook.Tab", background=[("selected", PANEL_ALT)], foreground=[("selected", GOLD)])
        style.configure("D6.Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=22, borderwidth=0, font=FONT_SMALL)
        style.configure("D6.Treeview.Heading", background=TOP, foreground=MUTED, relief="flat", borderwidth=0, font=FONT_TINY)
        style.map("D6.Treeview", background=[("selected", "#274566")], foreground=[("selected", WHITE)])
        style.configure("D6.Vertical.TScrollbar", background="#33425a", troughcolor=BG, bordercolor=BG, arrowcolor=MUTED, relief="flat")
        style.configure("D6.TCombobox", fieldbackground=INPUT, background=INPUT, foreground=TEXT, arrowcolor=MUTED)

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg=TOP, height=46)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        tk.Label(bar, text="达塔接口", bg=TOP, fg=GOLD, font=("Microsoft YaHei UI", 11, "bold")).pack(
            side="left", padx=(14, 8)
        )
        tk.Label(bar, text="d6", bg=TOP, fg=RED, font=("Consolas", 18, "bold")).pack(side="left", padx=(0, 10))
        tk.Label(bar, text="市场行情大屏", bg=TOP, fg=TEXT, font=FONT_CN).pack(side="left", padx=(0, 16))
        tk.Label(
            bar,
            text="d6\ndata interface",
            bg=TOP,
            fg="#29445e",
            justify="right",
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(side="right", padx=(0, 14), pady=5)
        tk.Button(bar, text="刷新总览", command=self.refresh_overview, bg="#245c45", activebackground="#31815d", fg=WHITE, relief="flat", bd=0, padx=9, pady=4, font=FONT_SMALL).pack(side="left", padx=(0, 14))
        tk.Button(bar, text="字段字典", command=self.show_dictionary, bg="#463766", activebackground="#604d8c", fg=WHITE, relief="flat", bd=0, padx=9, pady=4, font=FONT_SMALL).pack(side="left", padx=(0, 8))
        self.privacy_button = tk.Button(bar, text="隐藏中文名", command=self._toggle_privacy, bg="#4a3f24", activebackground="#6b5a31", fg=GOLD, activeforeground=WHITE, relief="flat", bd=0, padx=9, pady=4, font=FONT_SMALL)
        self.privacy_button.pack(side="left", padx=(0, 10))
        tk.Label(bar, text="HTTP 查询", bg=SOURCE_META["HTTP"][1], fg=SOURCE_META["HTTP"][0], font=FONT_TINY, padx=5, pady=2).pack(side="left", padx=(0, 4))
        tk.Label(bar, text="WS 全推", bg=SOURCE_META["WS"][1], fg=SOURCE_META["WS"][0], font=FONT_TINY, padx=5, pady=2).pack(side="left", padx=(0, 10))
        tk.Label(bar, textvariable=self.status_var, bg=TOP, fg=MUTED, font=FONT_TINY, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(bar, text="消息", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(8, 3))
        tk.Label(bar, textvariable=self.message_var, bg=TOP, fg=CYAN, font=FONT_TINY).pack(side="left", padx=(0, 12))
        tk.Label(bar, text="更新", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, 3))
        tk.Label(bar, textvariable=self.updated_var, bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, 14))

    def _iter_data_tables(self, widget: tk.Widget):
        for child in widget.winfo_children():
            if isinstance(child, DataTable):
                yield child
            yield from self._iter_data_tables(child)

    def _toggle_privacy(self) -> None:
        self.privacy_mode = not self.privacy_mode
        self.root._privacy_mode_enabled = self.privacy_mode
        self.privacy_button.configure(text="恢复中文名" if self.privacy_mode else "隐藏中文名")
        for table in self._iter_data_tables(self.root):
            table.refresh_rows()
        sentiment = self.http_data.get("sentiment")
        if sentiment is not None:
            self._render_sentiment(sentiment)
        live = getattr(self, "live", None)
        if live:
            self._render_live()
        fundamentals = self.http_data.get("stock_fundamentals")
        if fundamentals is not None:
            self._apply_stock_fundamentals(fundamentals)

    @staticmethod
    def _draw_watermark(canvas: tk.Canvas, width: int | None = None, height: int | None = None) -> None:
        """在图表背景层绘制固定视口的产品水印。"""
        width = max(1, width or canvas.winfo_width())
        height = max(1, height or canvas.winfo_height())
        for fraction in (0.34, 0.72):
            canvas.create_text(
                width / 2,
                height * fraction,
                text="d6\ndata interface",
                anchor="center",
                justify="center",
                fill="#16283b",
                font=FONT_WATERMARK,
            )

    def show_dictionary(self) -> None:
        existing = getattr(self, "dictionary_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            return
        window = tk.Toplevel(self.root)
        self.dictionary_window = window
        window.title("d6 业务字典")
        window.geometry("980x620")
        window.configure(bg=BG)
        window.transient(self.root)
        tk.Label(window, text="业务字典 · 只显示用户可读含义", bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Label(window, text="用于解释页面中的字段、分类和状态；复杂对象在业务表格中显示中文摘要。", bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w", padx=12, pady=8).pack(fill="x")
        body = tk.Frame(window, bg=PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tree = ttk.Treeview(body, columns=("meaning",), show="headings", style="D6.Treeview")
        tree.heading("meaning", text="业务含义")
        tree.column("meaning", width=900, minwidth=320, anchor="w")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=tree.yview, style="D6.Vertical.TScrollbar")
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        for _field, _raw, meaning in DICTIONARY_ROWS + FIELD_DICTIONARY_ROWS:
            tree.insert("", "end", values=(normalize_display_text(meaning),))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self.root, style="D6.TNotebook")
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.overview_tab = tk.Frame(self.tabs, bg=BG)
        self.stock_tab = tk.Frame(self.tabs, bg=BG)
        self.rank_tab = tk.Frame(self.tabs, bg=BG)
        self.capital_tab = tk.Frame(self.tabs, bg=BG)
        self.activity_tab = tk.Frame(self.tabs, bg=BG)
        self.news_tab = tk.Frame(self.tabs, bg=BG)
        self.kline_tab = tk.Frame(self.tabs, bg=BG)
        self.api_tab = tk.Frame(self.tabs, bg=BG)
        for tab, title in ((self.overview_tab, "市场总览"), (self.stock_tab, "个股详情"), (self.rank_tab, "行情排行"), (self.capital_tab, "资金专题"), (self.activity_tab, "异动监控"), (self.news_tab, "资讯数据"), (self.kline_tab, "K线分析"), (self.api_tab, "接口中心")):
            self.tabs.add(tab, text=title)
        self._build_overview_tab()
        self._build_stock_tab()
        self._build_generic_tab(self.rank_tab, "行情排行", ["quote/stocks/rank", "rank/change", "sector/quote", "sector/leader-rank", "sector/change-rank", "sector/capital-rank"])
        self._build_generic_tab(self.capital_tab, "资金专题", ["capital/flow/snapshot", "capital/flow/history", "capital/flow/period-rank", "capital/flow/index-minute", "connect/active-rank", "connect/flow-minute", "connect/flow-history", "connect/net-flow-minute", "capital/dragon-tiger/trend", "capital/dragon-tiger/sales-rank", "capital/dragon-tiger/stock-flow", "trade/block-list", "margin/summary", "margin/top-five", "margin/difference", "margin/curve", "stock/chip/distribution"])
        self._build_generic_tab(self.activity_tab, "异动监控", ["limit/distribution", "limit/monitor", "limit/trend-minute", "limit/continuous", "limit/list", "stock/secondary-anomaly", "stock/anomalies", "sector/anomaly/current", "capital/scramble-rank"])
        self._build_generic_tab(self.news_tab, "资讯数据", ["news/research-reports", "news/announcements/filter", "news/ipo", "news/performance/announcements", "news/performance/summary", "stock/diagnosis-hot", "market/trading-days", "quote/cross-market/hk-a", "quote/cross-market/ah"])
        self._build_kline_tab()
        self._build_api_tab()

    @staticmethod
    def _panel(parent: tk.Widget, title: str, row: int, column: int, rowspan: int = 1, columnspan: int = 1) -> tk.Frame:
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        frame.grid(row=row, column=column, rowspan=rowspan, columnspan=columnspan, sticky="nsew", padx=3, pady=3)
        tk.Label(frame, text=title, bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w", padx=8, pady=5).pack(fill="x")
        return frame

    def _build_overview_tab(self) -> None:
        tab = self.overview_tab
        for column, weight in enumerate((1, 1, 1, 1, 1, 1)):
            tab.grid_columnconfigure(column, weight=weight, uniform="overview")
        for row, weight in enumerate((3, 2, 4)):
            tab.grid_rowconfigure(row, weight=weight)
        breadth = self._panel(tab, "市场强弱概览", 0, 0, 1, 4)
        chart_host = tk.Frame(breadth, bg=PANEL)
        chart_host.pack(fill="both", expand=True, padx=4, pady=4)
        for column in range(4):
            chart_host.grid_columnconfigure(column, weight=1, uniform="market_chart")
        chart_host.grid_rowconfigure(0, weight=1)
        trend_box = tk.Frame(chart_host, bg=PANEL)
        trend_box.grid(row=0, column=0, sticky="nsew", padx=(2, 3))
        change_box = tk.Frame(chart_host, bg=PANEL)
        change_box.grid(row=0, column=1, sticky="nsew", padx=3)
        capital_box = tk.Frame(chart_host, bg=PANEL)
        capital_box.grid(row=0, column=2, sticky="nsew", padx=3)
        distribution_box = tk.Frame(chart_host, bg=PANEL)
        distribution_box.grid(row=0, column=3, sticky="nsew", padx=(3, 2))
        tk.Label(trend_box, text="涨跌停趋势", bg=PANEL, fg=GOLD, font=FONT_TITLE, anchor="w").pack(fill="x", padx=5, pady=(2, 0))
        tk.Label(change_box, text="涨跌趋势", bg=PANEL, fg=GOLD, font=FONT_TITLE, anchor="w").pack(fill="x", padx=5, pady=(2, 0))
        tk.Label(capital_box, textvariable=self.capital_flow_title_var, bg=PANEL, fg=GOLD, font=FONT_TITLE, anchor="w").pack(fill="x", padx=5, pady=(2, 0))
        tk.Label(capital_box, text="单位：亿元", bg=PANEL, fg=MUTED, font=FONT_TINY, anchor="e").place(relx=1.0, x=-5, y=5, anchor="ne")
        tk.Label(distribution_box, text="涨跌分布", bg=PANEL, fg=GOLD, font=FONT_TITLE, anchor="w").pack(fill="x", padx=5, pady=(2, 0))
        self.trend_canvas = tk.Canvas(trend_box, bg=PANEL, highlightthickness=0, height=160)
        self.trend_canvas.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.change_trend_canvas = tk.Canvas(change_box, bg=PANEL, highlightthickness=0, height=160)
        self.change_trend_canvas.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.capital_flow_canvas = tk.Canvas(capital_box, bg=PANEL, highlightthickness=0, height=160)
        self.capital_flow_canvas.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.distribution_canvas = tk.Canvas(distribution_box, bg=PANEL, highlightthickness=0, height=160)
        self.distribution_canvas.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self.trend_canvas.bind("<Configure>", lambda _event: self._draw_market_charts())
        self.change_trend_canvas.bind("<Configure>", lambda _event: self._draw_market_charts())
        self.capital_flow_canvas.bind("<Configure>", lambda _event: self._draw_market_charts())
        self.distribution_canvas.bind("<Configure>", lambda _event: self._draw_market_charts())
        self.trend_canvas.bind("<Motion>", lambda event: self._on_trend_motion(event, "limit"))
        self.trend_canvas.bind("<Leave>", lambda _event: self._on_trend_leave("limit"))
        self.change_trend_canvas.bind("<Motion>", lambda event: self._on_trend_motion(event, "change"))
        self.change_trend_canvas.bind("<Leave>", lambda _event: self._on_trend_leave("change"))
        self.capital_flow_canvas.bind("<Motion>", lambda event: self._on_trend_motion(event, "capital"))
        self.capital_flow_canvas.bind("<Leave>", lambda _event: self._on_trend_leave("capital"))
        index_panel = self._panel(tab, "主要指数 · 实时全推", 0, 4, 1, 1)
        self.index_table = DataTable(index_panel, "主要指数", max_rows=8, source="WS", context="index", show_header=False)
        self.index_table.pack(fill="both", expand=True, padx=5, pady=5)
        sentiment = self._panel(tab, "市场情绪", 0, 5, 1, 1)
        self.sentiment_text = tk.Label(sentiment, text="等待数据", bg=PANEL, fg=TEXT, justify="left", anchor="nw", font=FONT_CN)
        self.sentiment_text.pack(fill="both", expand=True, padx=10, pady=10)
        sector_panel = self._panel(tab, "板块强弱排行", 1, 0, 1, 3)
        self.sector_table = DataTable(sector_panel, "板块强弱排行", max_rows=30, source="HTTP", context="/sector/quote", show_header=False)
        self.sector_table.pack(fill="both", expand=True, padx=5, pady=5)
        activity_panel = self._panel(tab, "个股异动", 1, 3, 1, 3)
        self.activity_table = DataTable(activity_panel, "个股异动", max_rows=30, source="HTTP", context="/stock/anomalies", show_header=False)
        self.activity_table.pack(fill="both", expand=True, padx=5, pady=5)
        rank_panel = self._panel(tab, "股票行情大表格", 2, 0, 1, 6)
        self.rank_table = DataTable(rank_panel, "股票行情大表格", max_rows=300, source="HTTP", context="/quote/stocks/rank", show_header=False)
        self.rank_table.pack(fill="both", expand=True, padx=5, pady=5)

    def _build_stock_tab(self) -> None:
        tab = self.stock_tab
        # 左侧放两张图，右侧保留两条完整的纵向栏：行情报价、分时成交。
        tab.grid_columnconfigure(0, weight=5, uniform="stock_detail")
        tab.grid_columnconfigure(1, weight=2, uniform="stock_detail")
        tab.grid_columnconfigure(2, weight=2, uniform="stock_detail")
        tab.grid_rowconfigure(1, weight=4, minsize=270)
        tab.grid_rowconfigure(2, weight=5, minsize=340)
        tab.grid_rowconfigure(3, weight=2, minsize=130)
        toolbar = tk.Frame(tab, bg=TOP, height=36)
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew", padx=3, pady=3)
        toolbar.grid_propagate(False)
        tk.Label(toolbar, text="个股详情", bg=TOP, fg=GOLD, font=FONT_TITLE).pack(side="left", padx=(8, 12))
        tk.Label(toolbar, text="代码", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(0, 4))
        self.code_entry = tk.Entry(toolbar, textvariable=self.code_var, width=11, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=BLUE, font=FONT)
        self.code_entry.pack(side="left", padx=(0, 5), pady=6, ipady=3)
        self.code_entry.bind("<Return>", lambda _event: self.subscribe_stock())
        tk.Button(toolbar, text="订阅个股", command=self.subscribe_stock, bg="#214b72", activebackground="#326995", fg=WHITE, relief="flat", bd=0, padx=9, pady=4, font=FONT_SMALL).pack(side="left", padx=(0, 16))
        tk.Label(toolbar, text="实时行情 · 逐笔成交 · 1分钟分时 · 盘前竞价 · HTTP 五档/K线", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left")
        self.stock_status = tk.Label(toolbar, text="等待 WebSocket", bg=TOP, fg=MUTED, font=FONT_TINY)
        self.stock_status.pack(side="right", padx=8)

        intraday_panel = self._panel(tab, "分时走势 · 1分钟实时全推", 1, 0)
        intraday_toolbar = tk.Frame(intraday_panel, bg=PANEL_ALT, height=28)
        intraday_toolbar.pack(fill="x", padx=4, pady=(3, 0))
        intraday_toolbar.pack_propagate(False)
        self.stock_intraday_range_var = tk.StringVar(value="1D")
        self.stock_intraday_range_buttons: dict[str, tk.Button] = {}
        for label, range_key in (("盘前", "PRE"), ("一天", "1D"), ("二天", "2D"), ("三天", "3D"), ("四天", "4D"), ("五天", "5D")):
            button = tk.Button(
                intraday_toolbar,
                text=label,
                command=lambda value=range_key: self._set_stock_intraday_range(value),
                bg="#244e76" if range_key == "1D" else INPUT,
                activebackground="#326995",
                fg=WHITE if range_key == "1D" else TEXT,
                relief="flat",
                bd=0,
                padx=8,
                pady=2,
                font=FONT_TINY,
            )
            button.pack(side="left", padx=(2, 0), pady=3)
            self.stock_intraday_range_buttons[range_key] = button
        self.stock_intraday_status = tk.Label(intraday_toolbar, text="当日分时", bg=PANEL_ALT, fg=MUTED, font=FONT_TINY)
        self.stock_intraday_status.pack(side="right", padx=6)
        intraday_host = tk.Frame(intraday_panel, bg=PANEL)
        intraday_host.pack(fill="both", expand=True, padx=3, pady=3)
        self.stock_intraday_canvas = tk.Canvas(intraday_host, bg=PANEL, highlightthickness=0)
        self.stock_intraday_canvas.place(relx=0, rely=0, relwidth=1, relheight=0.80)
        self.stock_intraday_volume_canvas = tk.Canvas(intraday_host, bg=PANEL, highlightthickness=0)
        self.stock_intraday_volume_canvas.place(relx=0, rely=0.80, relwidth=1, relheight=0.20)
        self.stock_intraday_canvas.bind("<Configure>", lambda _event: self._draw_stock_intraday())
        self.stock_intraday_volume_canvas.bind("<Configure>", lambda _event: self._draw_stock_intraday())
        self.stock_intraday_canvas.bind("<Motion>", self._on_stock_intraday_motion)
        self.stock_intraday_canvas.bind("<Leave>", self._clear_stock_intraday_hover)
        self.stock_intraday_rows: list[dict[str, Any]] = []
        self.stock_intraday_current_rows: list[dict[str, Any]] = []
        self.stock_intraday_premarket_rows: list[dict[str, Any]] = []
        self.stock_intraday_history_rows: list[dict[str, Any]] = []
        self.stock_intraday_empty_text = "等待分时全推"
        self.stock_yclose = float("nan")
        self.stock_intraday_hover_x: int | None = None

        quote_panel = self._panel(tab, "行情报价", 1, 1, 2, 1)
        identity = tk.Frame(quote_panel, bg=PANEL_ALT, height=84)
        identity.pack(fill="x", padx=4, pady=(3, 2))
        identity.pack_propagate(False)
        identity.grid_rowconfigure(0, weight=1)
        identity.grid_rowconfigure(1, weight=1)
        identity.grid_columnconfigure(0, weight=2)
        identity.grid_columnconfigure(1, weight=2)
        identity.grid_columnconfigure(2, weight=1)
        identity.grid_columnconfigure(3, weight=1)
        name_box = tk.Frame(identity, bg=PANEL_ALT)
        name_box.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=(8, 4), pady=3)
        self.stock_name_label = tk.Label(name_box, text="等待订阅", bg=PANEL_ALT, fg=TEXT, font=("Microsoft YaHei UI", 13, "bold"), anchor="w")
        self.stock_name_label.pack(anchor="w")
        self.stock_code_label = tk.Label(name_box, text=DEFAULT_CODE, bg=PANEL_ALT, fg=MUTED, font=FONT_TINY, anchor="w")
        self.stock_code_label.pack(anchor="w", pady=(1, 0))
        self.stock_current_label = tk.Label(identity, text="—", bg=PANEL_ALT, fg=TEXT, font=("Consolas", 14, "bold"), anchor="w")
        self.stock_current_label.grid(row=0, column=2, sticky="w", padx=3)
        self.stock_change_label = tk.Label(identity, text="—", bg=PANEL_ALT, fg=MUTED, font=("Consolas", 10, "bold"), anchor="w")
        self.stock_change_label.grid(row=0, column=3, sticky="w", padx=3)
        self.stock_summary_vars: dict[str, tk.StringVar] = {
            "开盘": tk.StringVar(value="—"),
            "最高": tk.StringVar(value="—"),
            "最低": tk.StringVar(value="—"),
            "成交额": tk.StringVar(value="—"),
        }
        for column, label in enumerate(("开盘", "最高", "最低", "成交额")):
            box = tk.Frame(identity, bg=PANEL_ALT)
            box.grid(row=1, column=column, sticky="nsew", padx=2, pady=2)
            tk.Label(box, text=label, bg=PANEL_ALT, fg=MUTED, font=FONT_TINY).pack(anchor="w", padx=4, pady=(1, 0))
            tk.Label(box, textvariable=self.stock_summary_vars[label], bg=PANEL_ALT, fg=TEXT, font=("Consolas", 9, "bold")).pack(anchor="w", padx=4, pady=(0, 1))

        order_view = tk.Frame(quote_panel, bg=PANEL)
        order_view.pack(fill="both", expand=True, padx=3, pady=3)
        order_view.grid_columnconfigure(0, weight=1)
        order_view.grid_rowconfigure(1, weight=1)
        summary_bar = tk.Frame(order_view, bg=PANEL_ALT, height=38)
        summary_bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(1, 2))
        summary_bar.grid_propagate(False)
        self.stock_order_summary_vars: dict[str, tk.StringVar] = {
            "委比": tk.StringVar(value="—"),
            "委差": tk.StringVar(value="—"),
            "买额": tk.StringVar(value="—"),
            "卖额": tk.StringVar(value="—"),
        }
        for index, label in enumerate(("委比", "委差", "买额", "卖额")):
            summary_bar.grid_columnconfigure(index, weight=1)
            box = tk.Frame(summary_bar, bg=PANEL_ALT)
            box.grid(row=0, column=index, sticky="nsew", padx=1)
            tk.Label(box, text=label, bg=PANEL_ALT, fg=MUTED, font=FONT_TINY).pack(anchor="w", padx=3, pady=(4, 0))
            value_color = RED if label in {"买额"} else GREEN if label in {"卖额"} else TEXT
            tk.Label(box, textvariable=self.stock_order_summary_vars[label], bg=PANEL_ALT, fg=value_color, font=("Consolas", 9, "bold")).pack(anchor="w", padx=3, pady=(0, 3))
        self.stock_order_table = DataTable(order_view, "五档委托", max_rows=10, source="HTTP", context="/stock/fundamentals", show_header=False)
        self.stock_order_table.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 4))

        kline_panel = self._panel(tab, "K线 · 历史行情", 2, 0)
        kline_toolbar = tk.Frame(kline_panel, bg=PANEL_ALT, height=29)
        kline_toolbar.pack(fill="x", padx=4, pady=(3, 0))
        kline_toolbar.pack_propagate(False)
        self.stock_kline_period_var = tk.StringVar(value="DAY")
        self.stock_kline_buttons: dict[str, tk.Button] = {}
        for label, period in KLINE_PERIODS:
            button = tk.Button(
                kline_toolbar,
                text=label,
                command=lambda value=period: self._request_stock_kline(value),
                bg="#244e76" if period == "DAY" else INPUT,
                activebackground="#284b70",
                fg=WHITE if period == "DAY" else TEXT,
                relief="flat",
                bd=0,
                padx=7,
                pady=2,
                font=FONT_TINY,
            )
            button.pack(side="left", padx=(2, 0), pady=3)
            self.stock_kline_buttons[period] = button
        self.stock_kline_status = tk.Label(kline_toolbar, text="等待历史 K 线", bg=PANEL_ALT, fg=MUTED, font=FONT_TINY)
        self.stock_kline_status.pack(side="right", padx=6)
        kline_host = tk.Frame(kline_panel, bg=PANEL)
        kline_host.pack(fill="both", expand=True, padx=3, pady=3)
        kline_host.grid_rowconfigure(0, weight=1)
        kline_host.grid_columnconfigure(0, weight=7, minsize=470)
        kline_host.grid_columnconfigure(1, weight=3, minsize=235)

        price_host = tk.Frame(kline_host, bg=PANEL)
        price_host.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self.stock_kline_canvas = tk.Canvas(price_host, bg=PANEL, highlightthickness=0)
        self.stock_kline_canvas.place(relx=0, rely=0, relwidth=1, relheight=0.80)
        self.stock_kline_volume_canvas = tk.Canvas(price_host, bg=PANEL, highlightthickness=0)
        self.stock_kline_volume_canvas.place(relx=0, rely=0.80, relwidth=1, relheight=0.20)
        self.stock_kline_canvas.bind("<Configure>", lambda _event: self._draw_stock_kline())
        self.stock_kline_volume_canvas.bind("<Configure>", lambda _event: self._draw_stock_kline())
        self.stock_kline_canvas.bind("<Motion>", self._on_stock_kline_motion)
        self.stock_kline_canvas.bind("<Leave>", self._clear_stock_kline_hover)
        self.stock_kline_rows: list[dict[str, Any]] = []
        self.stock_kline_hover_x: int | None = None

        chip_host = tk.Frame(kline_host, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
        chip_host.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        chip_toolbar = tk.Frame(chip_host, bg=TOP, height=27)
        chip_toolbar.pack(fill="x")
        chip_toolbar.pack_propagate(False)
        tk.Label(chip_toolbar, text="筹码分布", bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w").pack(side="left", padx=7)
        tk.Label(chip_toolbar, textvariable=self.stock_chip_status_var, bg=TOP, fg=MUTED, font=FONT_TINY, anchor="e").pack(side="right", padx=6)
        tk.Label(
            chip_host,
            textvariable=self.stock_chip_date_var,
            bg=PANEL_ALT,
            fg=GOLD,
            font=("Microsoft YaHei UI", 12, "bold"),
            anchor="w",
            padx=8,
            pady=3,
        ).pack(fill="x")
        chip_body = tk.Frame(chip_host, bg=PANEL_ALT)
        chip_body.pack(fill="both", expand=True, padx=2, pady=(2, 0))
        chip_body.grid_rowconfigure(0, weight=1)
        chip_body.grid_columnconfigure(0, weight=3, minsize=190)
        chip_body.grid_columnconfigure(1, weight=2, minsize=150)
        self.stock_chip_canvas = tk.Canvas(chip_body, bg=PANEL, highlightthickness=0)
        self.stock_chip_canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        self.stock_chip_summary = tk.Label(
            chip_body,
            textvariable=self.stock_chip_summary_var,
            bg=PANEL_ALT,
            fg=TEXT,
            justify="left",
            anchor="nw",
            font=FONT_TINY,
            height=9,
            padx=6,
            pady=6,
            wraplength=190,
        )
        self.stock_chip_summary.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        self.stock_chip_canvas.bind("<Configure>", lambda _event: self._draw_stock_chip())

        trade_panel = self._panel(tab, "分时成交 · 实时全推", 1, 2, 2, 1)
        self.stock_trade_status_var = tk.StringVar(value="等待成交数据")
        trade_foot = tk.Frame(trade_panel, bg=PANEL_ALT, height=22)
        trade_foot.pack(fill="x", side="bottom", padx=4, pady=(0, 3))
        trade_foot.pack_propagate(False)
        self.stock_trade_status_label = tk.Label(trade_foot, textvariable=self.stock_trade_status_var, bg=PANEL_ALT, fg=MUTED, font=FONT_TINY)
        self.stock_trade_status_label.pack(side="left", padx=6)
        self.stock_trade_table = DataTable(trade_panel, "分时成交", max_rows=TRADE_MAX_ROWS, source="WS", context="trade", show_header=False)
        self.stock_trade_table._on_scroll_bottom = self._on_trade_scroll_bottom
        self.stock_trade_table.pack(fill="both", expand=True, padx=5, pady=(5, 2))

        anomaly_panel = self._panel(tab, "个股异动", 3, 0, 1, 3)
        self.stock_anomaly_table = DataTable(anomaly_panel, "个股异动", max_rows=15, source="HTTP", context="/stock/anomalies", show_header=False)
        self.stock_anomaly_table.pack(fill="both", expand=True, padx=5, pady=5)

    def _build_generic_tab(self, tab: tk.Frame, title: str, paths: list[str]) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        bar = tk.Frame(tab, bg=TOP, height=42)
        bar.grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        bar.grid_propagate(False)
        tk.Label(bar, text=title, bg=TOP, fg=GOLD, font=FONT_TITLE).pack(side="left", padx=8)
        button = tk.Button(bar, text="一键全显", command=lambda: self._generic_query_all(title), bg="#245c45", activebackground="#31815d", fg=WHITE, relief="flat", bd=0, padx=12, pady=4, font=FONT_SMALL)
        button.pack(side="left", padx=(4, 10), pady=5)
        status = tk.Label(bar, text=f"{len(paths)} 个方法 · 页面内同时展示", bg=TOP, fg=MUTED, font=FONT_TINY)
        status.pack(side="right", padx=8)

        viewport = tk.Frame(tab, bg=BG)
        viewport.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 3))
        viewport.grid_rowconfigure(0, weight=1)
        viewport.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview, style="D6.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        grid_frame = tk.Frame(canvas, bg=BG)
        canvas_window = canvas.create_window((0, 0), window=grid_frame, anchor="nw")

        columns = 4 if len(paths) >= 10 else 3
        for column in range(columns):
            grid_frame.grid_columnconfigure(column, weight=1, uniform=f"{title}-panel")
        panels: list[dict[str, Any]] = []
        for index, path in enumerate(paths):
            row, column = divmod(index, columns)
            table = DataTable(grid_frame, f"数据方法 {index + 1}", max_rows=12 if len(paths) >= 10 else 18, source="HTTP", context=path)
            table.tree.configure(height=6 if len(paths) >= 10 else 8)
            table.grid(row=row, column=column, sticky="nsew", padx=3, pady=3)
            panels.append({"path": path, "table": table, "spec": None})
        for row in range((len(paths) + columns - 1) // columns):
            grid_frame.grid_rowconfigure(row, weight=1, minsize=155 if len(paths) >= 10 else 190)

        def update_scrollregion(_event: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_canvas(event: tk.Event) -> None:
            # 宽度跟随视口；高度只在目标值变化时更新，避免 Windows Tk Configure 反馈循环。
            requested_height = grid_frame.winfo_reqheight()
            target_height = max(event.height, requested_height)
            current_height = as_float(canvas.itemcget(canvas_window, "height"), 0)
            if abs(current_height - target_height) > 1:
                canvas.itemconfigure(canvas_window, width=event.width, height=target_height)
            else:
                canvas.itemconfigure(canvas_window, width=event.width)
            update_scrollregion()

        grid_frame.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", resize_canvas)

        def mousewheel(event: tk.Event) -> None:
            canvas.yview_scroll(-1 * int(event.delta / 120 or -1), "units")

        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", mousewheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

        self.generic_views = getattr(self, "generic_views", {})
        self.generic_views[title] = {
            "tab": tab,
            "paths": paths,
            "panels": panels,
            "status": status,
            "specs": [],
            "canvas": canvas,
            "loaded_once": False,
            "pending": 0,
            "completed": 0,
        }

    def _build_kline_tab(self) -> None:
        tab = self.kline_tab
        tab.grid_columnconfigure(0, weight=3)
        tab.grid_columnconfigure(1, weight=2)
        tab.grid_rowconfigure(1, weight=2)
        tab.grid_rowconfigure(2, weight=1)
        bar = tk.Frame(tab, bg=TOP, height=42)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=3, pady=3)
        bar.grid_propagate(False)
        tk.Label(bar, text="K线分析", bg=TOP, fg=GOLD, font=FONT_TITLE).pack(side="left", padx=8)
        tk.Label(bar, text="代码", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(18, 4))
        self.kline_code_var = tk.StringVar(value=DEFAULT_CODE)
        tk.Entry(bar, textvariable=self.kline_code_var, width=11, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT).pack(side="left", padx=3, pady=8, ipady=3)
        tk.Label(bar, text="级别", bg=TOP, fg=MUTED, font=FONT_TINY).pack(side="left", padx=(12, 4))
        self.kline_period = tk.StringVar(value="DAY")
        self.kline_period_buttons: dict[str, tk.Button] = {}
        period_bar = tk.Frame(bar, bg=TOP)
        period_bar.pack(side="left", padx=2, pady=5)
        for label, period in KLINE_PERIODS:
            button = tk.Button(
                period_bar,
                text=label,
                command=lambda value=period: self._select_kline_period(value),
                bg="#244e76" if period == "DAY" else INPUT,
                activebackground="#284b70",
                fg=WHITE if period == "DAY" else TEXT,
                activeforeground=WHITE,
                relief="flat",
                bd=0,
                padx=6,
                pady=2,
                font=FONT_TINY,
            )
            button.pack(side="left", padx=(1, 0))
            self.kline_period_buttons[period] = button
        tk.Button(bar, text="加载", command=self.load_kline, bg="#245c45", activebackground="#31815d", fg=WHITE, relief="flat", bd=0, padx=12, pady=4, font=FONT_SMALL).pack(side="left", padx=6)
        chart_panel = self._panel(tab, "价格走势", 1, 0)
        self.kline_canvas = tk.Canvas(chart_panel, bg=PANEL, highlightthickness=0)
        self.kline_canvas.pack(fill="both", expand=True, padx=8, pady=8)
        kline_table_panel = self._panel(tab, "K线数据", 1, 1)
        self.kline_table = DataTable(kline_table_panel, "K线数据", max_rows=120, source="HTTP", context="/kline", show_header=False)
        self.kline_table.pack(fill="both", expand=True, padx=5, pady=5)
        raw_panel = self._panel(tab, "数据状态", 2, 0, 1, 2)
        self.kline_raw = tk.Text(raw_panel, bg="#07101b", fg=CYAN, relief="flat", bd=0, font=FONT_TINY, wrap="none", height=5)
        self.kline_raw.pack(fill="both", expand=True, padx=6, pady=6)
        self.kline_raw.configure(state="disabled")
        self.kline_canvas.bind("<Configure>", lambda _event: self._draw_kline())

    def _build_api_tab(self) -> None:
        tab = self.api_tab
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=3)
        tab.grid_rowconfigure(0, weight=1)
        left = tk.Frame(tab, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        tk.Label(left, text="HTTP · 全部 d6 接口", bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w", padx=8, pady=5).pack(fill="x")
        tk.Label(left, text="实时数据：个股详情页持续更新报价、分时、盘前和成交", bg=PANEL_ALT, fg=SOURCE_META["WS"][0], font=FONT_TINY, anchor="w", padx=8, pady=4).pack(fill="x")
        self.api_tree = ttk.Treeview(left, show="tree", style="D6.Treeview")
        api_scroll = ttk.Scrollbar(left, orient="vertical", command=self.api_tree.yview, style="D6.Vertical.TScrollbar")
        self.api_tree.configure(yscrollcommand=api_scroll.set)
        self.api_tree.pack(side="left", fill="both", expand=True)
        api_scroll.pack(side="right", fill="y")
        self.api_tree.bind("<<TreeviewSelect>>", self._api_selected)
        right = tk.Frame(tab, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew", padx=3, pady=3)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self.api_title = tk.Label(right, text="选择左侧接口", bg=TOP, fg=GOLD, font=FONT_TITLE, anchor="w", padx=8, pady=7)
        self.api_title.grid(row=0, column=0, sticky="ew")
        tool = tk.Frame(right, bg=PANEL_ALT)
        tool.grid(row=1, column=0, sticky="ew")
        tool.grid_columnconfigure(1, weight=1)
        tk.Label(tool, text="业务参数", bg=PANEL_ALT, fg=MUTED, font=FONT_TINY).grid(row=0, column=0, padx=8, pady=5, sticky="w")
        self.api_query = tk.Entry(tool, state="readonly", bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT_SMALL)
        self.api_query.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        tk.Button(tool, text="发送请求", command=self.api_send, bg="#245c45", activebackground="#31815d", fg=WHITE, relief="flat", bd=0, padx=12, pady=3, font=FONT_SMALL).grid(row=0, column=2, padx=7, pady=4)
        body = tk.PanedWindow(right, orient="vertical", bg=BORDER, sashwidth=4, bd=0)
        body.grid(row=2, column=0, sticky="nsew")
        self.api_body = tk.Text(body, bg="#07101b", fg=CYAN, insertbackground=TEXT, relief="flat", bd=0, font=FONT_TINY, wrap="none")
        self.api_response = tk.Text(body, bg="#050a11", fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, font=FONT_TINY, wrap="none")
        self.api_body.configure(state="disabled")
        body.add(self.api_body, minsize=100)
        body.add(self.api_response, minsize=180)
        self.api_selected_spec: dict[str, Any] | None = None
        self.api_query_payload: dict[str, Any] = {}
        self.api_body_payload: Any = {}

    def _load_catalog(self) -> None:
        self.http.request("catalog", "GET", CATALOG_URL)

    def _api_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if path.startswith("/d6/market/v1/"):
            origin = self.http_base.split("/d6/market/v1", 1)[0]
            return origin + path
        return self.http_base.rstrip("/") + "/" + path.lstrip("/")

    def connect(self) -> None:
        self.status_var.set("连接实时行情…")
        if not self.ws.start(self.ws_url):
            self.status_var.set("缺少 websocket-client，请执行 python -m pip install websocket-client")
        self.refresh_overview()
        # 默认标的也提前加载 HTTP 详情，打开“个股详情”时不需要再点一次订阅按钮。
        self.load_stock_http()

    def refresh_overview(self) -> None:
        requests = (
            ("distribution", "/limit/distribution", {}),
            ("limit_trend", "/limit/trend-minute", {}),
            ("capital_flow_trend", "/capital/flow/index-minute", {}),
            ("sentiment", "/market/sentiment", {}),
            ("trading_days", "/market/trading-days", {"limit": 30, "market": "sh"}),
            ("stock_rank", "/quote/stocks/rank", {
                "en_hq_type_code": "XSHG.ESA,XSHE.ESA,XSHG.KSH",
                "sort_field_name": "px_change_rate",
                "sort_type": "1",
                "pageNo": 1,
                "pageSize": 300,
            }),
            ("sector_quote", "/sector/quote", {"hqTypeCode": "HY", "sortFlag": "true", "sortFields": "pxChangeRate", "pageNum": 1, "pageSize": 30}),
        )
        self.status_var.set("加载市场总览…")
        for tag, path, params in requests:
            self.http.request(tag, "GET", self._api_url(path), params=params)
        # “个股异动”是独立的 POST 列表，不是涨跌停监控统计。
        self.http.request(
            "stock_anomalies",
            "POST",
            self._api_url("/stock/anomalies"),
            body={"limit": 30, "asc": False, "stocks": [], "categories": []},
        )
        if self.refresh_after is None and not self.closed:
            self.refresh_after = self.root.after(30000, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        self.refresh_after = None
        if not self.closed:
            self.refresh_overview()

    def subscribe_stock(self) -> None:
        self.kline_code_var.set(self.code_var.get().strip().upper())
        self.tabs.select(self.stock_tab)
        self._set_stock_intraday_range("1D", request=False)
        market, code = market_code(self.code_var.get())
        self._reset_trade_state(f"{market}{code}")
        connected = self.ws.send(self._ws_message(201))
        if not connected:
            self.stock_status.configure(text="WebSocket 未连接", fg=RED)
        else:
            self._send_trade_request(TRADE_PAGE_SIZE)
            for message_type in (501, 504):
                self.ws.send(self._ws_message(message_type))
            self.stock_status.configure(text=f"已订阅 {self.code_var.get().strip().upper()}", fg=GREEN)
        # HTTP 详情不依赖 WS，先把页面主体填满；全推连接成功后由 _render_live 继续刷新。
        self.load_stock_http()

    def _ws_message(self, message_type: int) -> dict[str, Any]:
        market, code = market_code(self.code_var.get())
        market_id = 1 if market == "sh" else 0
        key = {"oldmarketcode": market, "code": code}
        if message_type == 2001:
            return {"Header": {"No": 0, "MsgType": 2001}, "Body": {"info": {"paramtype": 2, "stockid": [{"marketid": 1, "code": "000001"}, {"marketid": 0, "code": "399001"}, {"marketid": 0, "code": "399006"}]}, "sortfield": 0, "order": True, "end": 3, "respfield": [10, 11, 96, 97, 98]}}
        if message_type == 801:
            request_no = self._next_trade_request_no()
            self._trade_request_generations[request_no] = self._trade_generation
            return {"Header": {"No": request_no, "MsgType": 801}, "Body": {"key": key, "num": self._trade_requested_num, "timestamp": True}}
        if message_type == 501:
            return {"Header": {"No": 9, "MsgType": 501}, "Body": {"key": key, "pushflag": True, "timestamp": True, "nopushjh": True}}
        if message_type == 504:
            return {"Header": {"No": 10, "MsgType": 504}, "Body": {"key": key, "pushflag": True, "timestamp": True}}
        return {"Header": {"No": 0, "MsgType": 201}, "Body": {"key": key, "level": 2, "marketid": market_id}}

    def _reset_trade_state(self, symbol: str | None = None) -> None:
        """切换标的或重连时清掉旧成交，避免旧响应串入新标的。"""
        self._trade_generation += 1
        market, code = market_code(self.code_var.get())
        self._trade_symbol = symbol or f"{market}{code}"
        self.stock_trades.clear()
        self._trade_rows_by_key.clear()
        self._trade_seen_keys.clear()
        self._trade_loading = False
        self._trade_has_more = True
        self._trade_requested_num = TRADE_PAGE_SIZE
        self._trade_pending_no = None
        self._trade_pending_num = None
        for message_type in (201, 501, 504, 801):
            self.live.pop(message_type, None)
        self._live_dirty_types.difference_update({201, 501, 504, 801})
        self._last_intraday_draw_sig = None
        if hasattr(self, "stock_trade_status_var"):
            self.stock_trade_status_var.set("等待成交数据")
            self.stock_trade_status_label.configure(fg=MUTED)
            self.stock_trade_table.set_rows([], empty_message="等待成交数据")

    @staticmethod
    def _trade_key_part(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _trade_dedup_key(row: dict[str, Any]) -> tuple:
        sequence = value_ci(row, "seq", "sequence", "tradeSequence", "trade_seq", "id", "no", default=None)
        if sequence not in (None, ""):
            return ("sequence", D6Gui._trade_key_part(sequence))
        return (
            "fields",
            D6Gui._trade_key_part(value_ci(row, "time", "Time", default="")),
            D6Gui._trade_key_part(value_ci(row, "newprice", "newPrice", "price", default="")),
            D6Gui._trade_key_part(value_ci(row, "xianl", "volume", default="")),
            D6Gui._trade_key_part(value_ci(row, "xsfx", "direction", default="")),
            D6Gui._trade_key_part(value_ci(row, "tradenum", default="")),
            D6Gui._trade_key_part(value_ci(row, "tradetype", default="")),
        )

    @staticmethod
    def _trade_sort_key(row: dict[str, Any]) -> tuple:
        raw_time = value_ci(row, "time", "Time", default="")
        t_val = as_float(raw_time, float("nan"))
        if t_val != t_val:
            match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?", str(raw_time))
            if match:
                fraction = f"0.{match.group(4)}" if match.group(4) else "0"
                t_val = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3) or 0) + float(fraction)
            else:
                t_val = 0.0
        seq_val = as_float(value_ci(row, "seq", "sequence", "tradeSequence", "id", "no", "tradenum"), 0.0)
        return (t_val, seq_val)

    def _next_trade_request_no(self) -> int:
        self._trade_request_no += 1
        if self._trade_request_no > 2_000_000_000:
            self._trade_request_no = 1
        return self._trade_request_no

    def _ws_connected(self) -> bool:
        app = getattr(self.ws, "app", None)
        sock = getattr(app, "sock", None)
        return bool(getattr(sock, "connected", False))

    def _set_trade_status(self, text: str, color: str = MUTED) -> None:
        self.stock_trade_status_var.set(text)
        self.stock_trade_status_label.configure(fg=color)

    def _send_trade_request(self, requested_num: int) -> bool:
        if self.closed or self._trade_loading or not self._ws_connected():
            return False
        market, code = market_code(self.code_var.get())
        if not code:
            return False
        request_no = self._next_trade_request_no()
        self._trade_requested_num = max(TRADE_PAGE_SIZE, int(requested_num))
        self._trade_pending_no = request_no
        self._trade_pending_num = self._trade_requested_num
        self._trade_request_generations[request_no] = self._trade_generation
        self._trade_loading = True
        request = {
            "Header": {"No": request_no, "MsgType": 801},
            "Body": {
                "key": {"oldmarketcode": market, "code": code},
                "num": self._trade_requested_num,
                "timestamp": True,
            },
        }
        if not self.ws.send(request):
            self._trade_pending_no = None
            self._trade_pending_num = None
            self._trade_loading = False
            self._set_trade_status("成交加载失败 · 请重连", RED)
            return False
        self._set_trade_status(
            "正在加载历史成交…" if self._trade_requested_num > TRADE_PAGE_SIZE else "加载成交…",
            GOLD,
        )
        return True

    def _on_trade_scroll_bottom(self) -> None:
        if self._trade_loading or not self._trade_has_more or self.closed:
            return
        if not self._ws_connected():
            return
        self._send_trade_request(self._trade_requested_num + TRADE_PAGE_SIZE)

    def load_stock_http(self) -> None:
        market, code = market_code(self.code_var.get())
        # 筹码接口一次返回多个交易日；悬停 K 线时只在本地切换日期，避免每根 K 线重复请求。
        self.stock_chip_days = []
        self.stock_chip_selected = None
        self.stock_chip_selected_date = None
        self.stock_kline_rows = []
        self.stock_kline_hover_x = None
        self.stock_chip_status_var.set("加载中…")
        self.stock_chip_date_var.set("—")
        self.stock_chip_summary_var.set("正在加载近 100 个交易日的筹码分布")
        self._draw_stock_chip()
        for tag, path, params in (
            ("stock_fundamentals", "/stock/fundamentals", {"symbol": f"{market}{code}"}),
            ("stock_margin", "/margin/stock/detail", {"market": market, "pageSize": 20}),
        ):
            self.http.request(tag, "GET", self._api_url(path), params=params)
        self.http.request(
            "stock_chip",
            "GET",
            self._api_url("/stock/chip/distribution"),
            params={
                "symbol": code,
                "market": market,
                "startTime": int(time.time() * 1000) - 100 * 24 * 60 * 60 * 1000,
                "powerType": 1,
            },
        )
        self._request_stock_kline(self.stock_kline_period_var.get() or "DAY")
        # 个股详情只显示当前标的的异动；接口本身返回全市场列表，客户端按代码收敛。
        self.http.request(
            "stock_anomalies",
            "POST",
            self._api_url("/stock/anomalies"),
            body={"limit": 100, "asc": False, "stocks": [], "categories": []},
        )

    def _set_stock_intraday_range(self, range_key: str, request: bool = True) -> None:
        range_key = range_key.upper()
        if range_key not in {"PRE", "1D", "2D", "3D", "4D", "5D"}:
            range_key = "1D"
        self.stock_intraday_range_var.set(range_key)
        for key, button in self.stock_intraday_range_buttons.items():
            active = key == range_key
            button.configure(bg="#244e76" if active else INPUT, fg=WHITE if active else TEXT)
        if range_key == "PRE":
            rows = self._combined_stock_intraday_rows()
            self.stock_intraday_rows = rows
            premarket_count = len(self.stock_intraday_premarket_rows)
            regular_count = len(self.stock_intraday_current_rows)
            self.stock_intraday_status.configure(
                text=f"盘前竞价 + 当日 · {premarket_count} + {regular_count} 点" if rows else "等待盘前与当日分时",
                fg=GREEN if rows else MUTED,
            )
            self.stock_intraday_empty_text = "等待盘前竞价 + 当日分时"
            self._draw_stock_intraday()
            return
        if range_key == "1D":
            self.stock_intraday_status.configure(text="当日分时", fg=GREEN)
            self.stock_intraday_empty_text = "等待分时全推"
            self.stock_intraday_rows = list(self.stock_intraday_current_rows)
            self._draw_stock_intraday()
            return
        if not request:
            self.stock_intraday_status.configure(text=f"{range_key} 等待数据", fg=MUTED)
            self.stock_intraday_rows = []
            self._draw_stock_intraday()
            return
        market, code = market_code(self.code_var.get())
        self.stock_intraday_status.configure(text=f"加载 {range_key}…", fg=MUTED)
        self.stock_intraday_empty_text = "等待历史分时"
        self.http.request(
            "stock_intraday_history",
            "GET",
            self._api_url("/kline/history"),
            params={
                "market": market.upper(),
                "inst": code,
                "period": "MIN1",
                "startTime": 0,
                "endTime": 2524579200,
                "limit": 1200,
            },
        )

    def _combined_stock_intraday_rows(self) -> list[dict[str, Any]]:
        """原页面的“盘前”视图：竞价段后紧接当日常规分时，中间留一段断线。"""
        premarket = [dict(row, session="premarket") for row in self.stock_intraday_premarket_rows]
        regular = [dict(row, session="regular") for row in self.stock_intraday_current_rows]
        if premarket and regular:
            return premarket + [{
                "time": "",
                "close": None,
                "junj": None,
                "volume": 0,
                "session": "separator",
            }] + regular
        return premarket or regular

    def _request_stock_kline(self, period: str = "DAY") -> None:
        market, code = market_code(self.code_var.get())
        period = period.upper()
        self.stock_kline_period_var.set(period)
        for key, button in getattr(self, "stock_kline_buttons", {}).items():
            active = key == period
            button.configure(bg="#244e76" if active else INPUT, fg=WHITE if active else TEXT)
        period_label = KLINE_PERIOD_LABELS.get(period, period)
        self.stock_kline_status.configure(text=f"加载 {period_label}…", fg=MUTED)
        self.http.request(
            "stock_kline",
            "GET",
            self._api_url("/kline/history"),
            params={
                "market": market.upper(),
                "inst": code,
                "period": period,
                "startTime": 0,
                "endTime": 2524579200,
                "limit": 100,
            },
        )

    def _poll_events(self) -> None:
        if self.closed:
            return
        processed = 0
        while processed < 160:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if kind == "http":
                self._on_http(payload)
            elif kind == "ws_state":
                self._on_ws_state(str(payload))
            elif kind == "ws_error":
                self._on_ws_error(str(payload))
            elif kind == "ws_message":
                self._on_ws_message(payload)
        if self.render_pending:
            self.render_pending = False
            dirty_types = set(self._live_dirty_types)
            self._live_dirty_types.clear()
            self._render_live(dirty_types)
        self.root.after(60, self._poll_events)

    def _on_http(self, result: dict[str, Any]) -> None:
        tag = str(result.get("tag"))
        if result.get("ok"):
            self.http_data[tag] = result.get("data")
            self.updated_var.set(time.strftime("%H:%M:%S"))
            self._apply_http_result(tag, result.get("data"))
            if tag == "catalog":
                self.status_var.set("接口目录已加载，等待实时行情")
            elif tag.startswith("generic:"):
                parts = tag.split(":", 2)
                group = parts[1]
                view = self.generic_views.get(group)
                if view and len(parts) == 3:
                    try:
                        index = int(parts[2])
                    except ValueError:
                        index = -1
                    if 0 <= index < len(view["panels"]):
                        panel = view["panels"][index]
                        if panel.get("path") == "sector/anomaly/current":
                            panel["table"].set_rows(
                                self._sector_anomaly_rows(result.get("data")),
                                columns=["时间", "板块名称", "类型", "涨幅", "代表个股", "个股涨跌幅"],
                            )
                        else:
                            panel["table"].set_payload(result.get("data"))
                    view["completed"] += 1
                    view["status"].configure(text=f"已更新 {view['completed']}/{view['pending']} 个方法 · {time.strftime('%H:%M:%S')}", fg=GREEN)
            elif tag == "api":
                self._set_text(self.api_response, public_payload_summary(result.get("data")))
            elif tag == "kline":
                self._apply_kline(result.get("data"))
        else:
            status = result.get("status")
            message = f"请求失败（HTTP {status}）" if status else "数据服务未响应"
            self.status_var.set(message)
            if tag.startswith("generic:"):
                parts = tag.split(":", 2)
                group = parts[1]
                view = self.generic_views.get(group)
                if view:
                    if len(parts) == 3:
                        try:
                            index = int(parts[2])
                        except ValueError:
                            index = -1
                        if 0 <= index < len(view["panels"]):
                            view["panels"][index]["table"].set_rows([{"状态": message}])
                        view["completed"] += 1
                    view["status"].configure(text=f"{message} · 已完成 {view['completed']}/{view['pending']}", fg=RED)
            elif tag == "api":
                self._set_text(self.api_response, message)
            elif tag == "stock_chip":
                self.stock_chip_status_var.set(message)
                self.stock_chip_date_var.set("—")
                self.stock_chip_summary_var.set("当前标的暂无筹码分布")
                self._draw_stock_chip()

    def _apply_http_result(self, tag: str, payload: Any) -> None:
        if tag == "catalog":
            self._apply_catalog(payload)
        elif tag == "distribution":
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            self.limit_distribution_data = data
            self._draw_market_charts()
        elif tag == "limit_trend":
            data = payload.get("data", []) if isinstance(payload, dict) else []
            self.limit_trend_data = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
            self._draw_market_charts()
        elif tag == "capital_flow_trend":
            data = payload.get("data", []) if isinstance(payload, dict) else []
            self.capital_flow_data = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
            self._draw_market_charts()
        elif tag == "sentiment":
            self._render_sentiment(payload)
        elif tag == "trading_days":
            latest = latest_trading_day(payload)
            if latest and latest != self.latest_trading_day:
                self.latest_trading_day = latest
                self.status_var.set(f"交易日历已同步：{latest}")
                # 若用户在日历返回前打开了专题页，用最新交易日重新请求一次。
                for group, view in self.generic_views.items():
                    if view.get("loaded_once"):
                        self._generic_query_all(group)
        elif tag == "stock_rank":
            rows = self._overview_rows(payload)
            total = value_ci(payload.get("data"), "Total", "total", default=None) if isinstance(payload, dict) else None
            if total not in (None, ""):
                self.rank_table.title_var.set(f"股票行情大表格 · 全市场 {total} 只 · 涨幅前 {len(rows)} 条")
            self.rank_table.set_rows(rows, columns=[
                "Market_Symbol", "Prod_name", "Exchange_Symbol", "Last_px", "Px_change_rate",
                "Px_change", "Business_amount", "Business_balance", "Amplitude", "Turnover_ratio",
                "Vol_ratio", "Market_value",
            ])
        elif tag == "sector_quote":
            self.sector_table.set_rows(self._sector_rows(payload), columns=[
                "板块", "类型", "涨跌幅", "上涨", "下跌", "平盘", "涨停", "跌停",
                "成交额", "主力净流入", "领涨股", "领跌股",
            ])
        elif tag == "stock_anomalies":
            self.activity_table.set_rows(self._activity_rows(payload), columns=[
                "时间", "代码", "名称", "最新价", "异动时价格", "涨跌幅", "异动时涨跌幅",
                "异动类型", "异动数量", "所属板块", "板块涨跌幅",
            ])
            self._update_stock_anomaly_table(payload)
        elif tag == "stock_fundamentals":
            self._apply_stock_fundamentals(payload)
        elif tag == "stock_flow":
            # 资金流已集中到“资金专题”页，个股详情右侧保持单一行情报价栏。
            pass
        elif tag == "stock_kline":
            self._apply_stock_kline(payload)
        elif tag == "stock_chip":
            self._apply_stock_chip(payload)
        elif tag == "stock_intraday_history":
            self._apply_stock_intraday_history(payload)

    def _render_sentiment(self, payload: Any) -> None:
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}
        highest_raw = value_ci(data.get("highestContinueBoardBoardStock"), "name", default="—")
        highest = display_name(highest_raw or "—", self.privacy_mode)
        days = value_ci(data.get("highestContinueBoardBoardStock"), "countContLimit", default="—")
        space_raw = value_ci(data.get("highestSpaceBoardStock"), "name", default="—")
        space = display_name(space_raw or "—", self.privacy_mode)
        self.sentiment_text.configure(
            text=(
                f"涨停家数：{data.get('upLimit', '—')}\n"
                f"涨停成功率：{fmt_percent(data.get('upRate'), True)}\n"
                f"最高连板：{highest}  {days} 板\n"
                f"空间龙头：{space}\n"
                f"二板晋级：{fmt_percent(data.get('twoBoardContinueRate'), True)}\n"
                f"三板晋级：{fmt_percent(data.get('threeBoardContinueRate'), True)}"
            ),
            fg=TEXT,
        )

    def _apply_stock_fundamentals(self, payload: Any) -> None:
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if isinstance(data, list):
            data = next((item for item in data if isinstance(item, dict)), {})
        if not isinstance(data, dict):
            return

        def stock_price(value: Any) -> float | None:
            number = as_float(value, float("nan"))
            if number != number:
                return None
            # 基本面接口的价格为整数分，已验证 10560 表示 105.60。
            return number / 100 if abs(number) >= 100 else number

        def stock_rate(value: Any) -> float | None:
            number = as_float(value, float("nan"))
            if number != number:
                return None
            # 149 表示 1.49%，小数版本则直接按比例处理。
            if abs(number) > 1:
                number /= 10000
            return number

        market, code = market_code(self.code_var.get())
        name = value_ci(data, "prodName", "name", default="等待订阅")
        self.stock_name_label.configure(text=display_name(name or "等待订阅", self.privacy_mode))
        self.stock_code_label.configure(text=f"{market.upper()}{code} · HTTP 五档 / 实时快照")
        preclose = stock_price(value_ci(data, "preClosePx", "preclose", "yclose"))
        if preclose is not None:
            self.stock_yclose = preclose
        current = stock_price(value_ci(data, "lastPx", "lastPrice", "newprice"))
        rate = stock_rate(value_ci(data, "pxChangeRate", "changeRate"))
        if current is not None:
            color = RED if (rate is None or rate >= 0) else GREEN
            self.stock_current_label.configure(text=f"{current:,.2f}", fg=color)
            self.stock_change_label.configure(text=fmt_percent(rate, True) if rate is not None else "—", fg=color)

        for key, fields in {
            "开盘": ("openPrice", "open", "OpenPrice"),
            "最高": ("highPx", "high", "HighPrice"),
            "最低": ("lowPx", "low", "LowPrice"),
        }.items():
            value = stock_price(value_ci(data, *fields))
            self.stock_summary_vars[key].set(f"{value:,.2f}" if value is not None else "—")
        turnover = value_ci(data, "businessBalance", "BusinessBalance", "amount")
        self.stock_summary_vars["成交额"].set(fmt_number(turnover))

        shares_per_hand = as_float(value_ci(data, "sharesPerHand", default=100), 100) or 100
        order_rows: list[dict[str, Any]] = []

        def append_order(direction: str, level: int, item: Any) -> None:
            if not isinstance(item, dict):
                return
            raw_price = value_ci(item, "entrustPx", "price", "pricePx")
            price = stock_price(raw_price)
            total = as_float(value_ci(item, "totalEntrustAmount", "entrustAmount", "volume"), float("nan"))
            if price is None or total != total:
                return
            hands = total / shares_per_hand
            order_rows.append({
                "方向": direction,
                "档位": f"{direction}{level}",
                "价格": f"{price:,.2f}",
                "数量": f"{hands:,.0f}手",
                "金额": fmt_number(price * total),
            })

        offers = value_ci(data, "offerGrp", "offerGroup", default=[])
        bids = value_ci(data, "bidGrp", "bidGroup", default=[])
        if isinstance(offers, list):
            for index, item in enumerate(reversed(offers[-5:]), start=1):
                append_order("卖", 6 - index, item)
        if isinstance(bids, list):
            for index, item in enumerate(bids[:5], start=1):
                append_order("买", index, item)
        self.stock_order_table.set_rows(order_rows, columns=["方向", "档位", "价格", "数量", "金额"], empty_message="暂无五档数据")
        # 右侧报价栏是独立窄列，五档必须在一屏内完整看到金额，禁止横向滚动才能看到后两列。
        for index, width in enumerate((42, 48, 72, 76, 86), start=1):
            if index <= len(self.stock_order_table.tree["columns"]):
                self.stock_order_table.tree.column(f"#{index}", width=width, minwidth=width, stretch=False)

        entrust_rate = as_float(value_ci(data, "entrustRate", default=float("nan")), float("nan"))
        if entrust_rate == entrust_rate and abs(entrust_rate) > 1:
            entrust_rate /= 10000
        entrust_diff = as_float(value_ci(data, "entrustDiff", default=float("nan")), float("nan"))
        buy_amount = as_float(value_ci(data, "totalBidTurnover", "totalBidAmount"), float("nan"))
        sell_amount = as_float(value_ci(data, "totalOfferTurnover", "totalOfferAmount"), float("nan"))
        self.stock_order_summary_vars["委比"].set(fmt_percent(entrust_rate, True) if entrust_rate == entrust_rate else "—")
        self.stock_order_summary_vars["委差"].set(f"{entrust_diff / shares_per_hand:,.0f}手" if entrust_diff == entrust_diff else "—")
        self.stock_order_summary_vars["买额"].set(fmt_number(buy_amount) if buy_amount == buy_amount and buy_amount else "—")
        self.stock_order_summary_vars["卖额"].set(fmt_number(sell_amount) if sell_amount == sell_amount and sell_amount else "—")

    def _apply_stock_intraday_history(self, payload: Any) -> None:
        rows: Any = payload.get("KlineData", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = records_from(rows)
        source_rows = [row for row in rows if isinstance(row, dict)]
        range_key = self.stock_intraday_range_var.get().upper()
        if range_key == "PRE":
            # 盘前不是历史 K 线的 09:30 前过滤，而是竞价全推。
            # 即使旧的历史请求空返回，也不能覆盖当前的“竞价 + 当日”视图。
            self.stock_intraday_rows = self._combined_stock_intraday_rows()
            premarket_count = len(self.stock_intraday_premarket_rows)
            regular_count = len(self.stock_intraday_current_rows)
            self.stock_intraday_status.configure(
                text=f"盘前竞价 + 当日 · {premarket_count} + {regular_count} 点" if self.stock_intraday_rows else "等待盘前与当日分时",
                fg=GREEN if self.stock_intraday_rows else MUTED,
            )
            self.stock_intraday_empty_text = "等待盘前竞价 + 当日分时"
            self._draw_stock_intraday()
            return
        if not source_rows:
            self.stock_intraday_rows = []
            self.stock_intraday_status.configure(text="暂无历史分时", fg=MUTED)
            self.stock_intraday_empty_text = "暂无历史分时"
            self._draw_stock_intraday()
            return

        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in source_rows:
            day = date_text(value_ci(row, "TradingDay", "tradingDay", "Date"))
            timestamp = as_float(value_ci(row, "Time", "time"), float("nan"))
            if day is None and timestamp == timestamp:
                day = date_text(timestamp)
            day = day or "未知日期"
            grouped.setdefault(day, []).append(row)
        days = sorted(grouped)
        selected: list[dict[str, Any]] = []
        count = int(range_key[0]) if range_key[:1].isdigit() else 1
        selected_days = set(days[-count:])
        selected = [row for day in days if day in selected_days for row in grouped[day]]
        self.stock_intraday_status.configure(text=f"{count}日分时 · {len(selected)} 根", fg=GREEN if selected else MUTED)
        self.stock_intraday_empty_text = "暂无历史分时"

        normalized: list[dict[str, Any]] = []
        multi_day = len({date_text(value_ci(row, "TradingDay", "tradingDay", "Date")) or "" for row in selected}) > 1
        for row in selected:
            timestamp = as_float(value_ci(row, "Time", "time"), float("nan"))
            clock = time.strftime("%H:%M", time.localtime(timestamp)) if timestamp == timestamp and timestamp > 100000000 else str(value_ci(row, "Time", "time", default="—"))
            day = date_text(value_ci(row, "TradingDay", "tradingDay", "Date")) or (date_text(timestamp) if timestamp == timestamp else "")
            average = as_float(value_ci(row, "AvePrice", "junj"), float("nan"))
            normalized.append({
                "time": f"{day[5:]} {clock}" if multi_day and len(day) >= 10 else clock,
                "close": as_float(value_ci(row, "Close", "close"), float("nan")),
                "junj": average if average == average else None,
                "volume": as_float(value_ci(row, "Volume", "volume"), 0),
                "amount": as_float(value_ci(row, "Amount", "amount"), 0),
            })
        self.stock_intraday_history_rows = normalized
        self.stock_intraday_rows = normalized
        self._draw_stock_intraday()

    def _update_stock_anomaly_table(self, payload: Any) -> None:
        all_rows = self._activity_rows(payload)
        _market, code = market_code(self.code_var.get())
        code = code.upper()
        matched: list[dict[str, Any]] = []
        for row in all_rows:
            raw_code = str(row.get("代码", "")).upper().replace(".", "")
            if raw_code == code or raw_code.endswith(code):
                matched.append(row)
        self.stock_anomaly_table.set_rows(
            matched[:15],
            columns=["时间", "异动类型", "异动数量", "涨跌幅"],
            empty_message="当前标的暂无异动",
        )

    def _apply_stock_kline(self, payload: Any) -> None:
        rows: Any = payload.get("KlineData", []) if isinstance(payload, dict) else []
        if not rows and isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                rows = data.get("KlineData", data.get("data", []))
            elif isinstance(data, list):
                rows = data
        if not isinstance(rows, list):
            rows = records_from(rows)
        self.stock_kline_rows = [row for row in rows if isinstance(row, dict)][-120:]
        period = self.stock_kline_period_var.get() or "DAY"
        period_label = KLINE_PERIOD_LABELS.get(period, period)
        self.stock_kline_status.configure(text=f"{period_label} · {len(self.stock_kline_rows)} 根", fg=GREEN if self.stock_kline_rows else MUTED)
        self._draw_stock_kline()

    def _apply_stock_chip(self, payload: Any) -> None:
        data: Any = payload.get("data", []) if isinstance(payload, dict) else payload
        if isinstance(data, dict):
            if isinstance(data.get("data"), list):
                data = data["data"]
            elif isinstance(data.get("items"), list) and value_ci(data, "tradeDate", "TradingDay") is not None:
                data = [data]
            else:
                data = data.get("rows") or data.get("list") or data.get("items") or []
        if not isinstance(data, list):
            data = []
        self.stock_chip_days = [row for row in data if isinstance(row, dict)]
        self.stock_chip_days.sort(key=lambda row: date_text(value_ci(row, "tradeDate", "TradingDay", "date")) or "")
        self.stock_chip_selected = None
        self.stock_chip_selected_date = None
        if not self.stock_chip_days:
            self.stock_chip_status_var.set("暂无数据")
            self.stock_chip_date_var.set("—")
            self.stock_chip_summary_var.set("当前标的暂无筹码分布")
            self._draw_stock_chip()
            return
        self.stock_chip_status_var.set(f"{len(self.stock_chip_days)} 个交易日")
        kline_entries = self._stock_kline_entries()
        target_date = kline_entries[-1]["date"] if kline_entries else None
        self._set_stock_chip_for_date(target_date)

    def _stock_kline_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for source in getattr(self, "stock_kline_rows", []):
            if not isinstance(source, dict):
                continue
            values = [as_float(value_ci(source, key, key.lower()), float("nan")) for key in ("Open", "High", "Low", "Close")]
            if any(value != value for value in values):
                continue
            raw_date = value_ci(source, "TradingDay", "Date", "Time", default="—")
            entries.append({
                "open": values[0], "high": values[1], "low": values[2], "close": values[3],
                "volume": as_float(value_ci(source, "Volume", "volume"), 0),
                "date": date_text(raw_date) or str(raw_date),
            })
        return entries

    def _chip_day_for_date(self, date_value: Any = None) -> dict[str, Any] | None:
        if not self.stock_chip_days:
            return None
        target = date_text(date_value)
        dated = [
            (date_text(value_ci(day, "tradeDate", "TradingDay", "date")), day)
            for day in self.stock_chip_days
        ]
        if target:
            for day_date, day in dated:
                if day_date == target:
                    return day
            earlier = [(day_date, day) for day_date, day in dated if day_date and day_date <= target]
            if earlier:
                return earlier[-1][1]
        return self.stock_chip_days[-1]

    def _set_stock_chip_for_date(self, date_value: Any = None) -> None:
        day = self._chip_day_for_date(date_value)
        if day is None:
            self.stock_chip_status_var.set("等待数据")
            self.stock_chip_date_var.set("—")
            self.stock_chip_summary_var.set("移动鼠标到 K 线上查看对应交易日")
            self._draw_stock_chip()
            return
        selected_date = date_text(value_ci(day, "tradeDate", "TradingDay", "date")) or "未知日期"
        self.stock_chip_selected = day
        self.stock_chip_selected_date = selected_date
        self.stock_chip_date_var.set(selected_date)
        items = value_ci(day, "items", default=[])
        item_count = len(items) if isinstance(items, list) else 0
        summary = value_ci(day, "chipSummary", default={})
        if not isinstance(summary, dict):
            summary = {}

        def chip_price(value: Any) -> str:
            number = as_float(value, float("nan"))
            return f"{number:,.2f}" if number == number else "—"

        win_ratio = as_float(value_ci(summary, "winRatio"), float("nan"))
        win_text = f"{win_ratio:.2f}%" if win_ratio == win_ratio else "—"
        shape = str(value_ci(summary, "shapes", "shapesDetail", default="—") or "—")
        self.stock_chip_status_var.set(f"{item_count} 档")
        self.stock_chip_summary_var.set(
            f"获利比例 {win_text}\n"
            f"持仓均价 {chip_price(value_ci(summary, 'meanPrice'))}\n"
            f"阻力位 {chip_price(value_ci(summary, 'zl'))}\n"
            f"支撑位 {chip_price(value_ci(summary, 'zc'))}\n"
            f"90%成本 {chip_price(value_ci(summary, 'costL90'))}-{chip_price(value_ci(summary, 'costH90'))}\n"
            f"集中度 {chip_price(value_ci(summary, 'jzd90'))}%\n"
            f"70%成本 {chip_price(value_ci(summary, 'costL70'))}-{chip_price(value_ci(summary, 'costH70'))}\n"
            f"集中度 {chip_price(value_ci(summary, 'jzd70'))}%\n"
            f"形态 {shape}"
        )
        self._draw_stock_chip()

    def _draw_stock_chip(self) -> None:
        canvas = getattr(self, "stock_chip_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(220, canvas.winfo_width())
        height = max(170, canvas.winfo_height())
        self._draw_watermark(canvas, width, height)
        day = self.stock_chip_selected
        if not isinstance(day, dict):
            canvas.create_text(width / 2, height / 2, text="等待筹码分布", fill=MUTED, font=FONT_SMALL)
            return
        items = value_ci(day, "items", default=[])
        if not isinstance(items, list):
            items = []
        rows: list[tuple[float, float]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            price = as_float(value_ci(item, "price", "Price"), float("nan"))
            volume = as_float(value_ci(item, "volume", "Volume"), float("nan"))
            if price == price and volume == volume and volume >= 0:
                rows.append((price, volume))
        if not rows:
            canvas.create_text(width / 2, height / 2, text="该交易日暂无分布明细", fill=MUTED, font=FONT_SMALL)
            return
        rows.sort(key=lambda item: item[0])
        left, right, top, bottom = 58, 10, 22, 18
        plot_width = max(50, width - left - right)
        plot_height = max(40, height - top - bottom)
        low_price = rows[0][0]
        high_price = rows[-1][0]
        price_padding = max((high_price - low_price) * 0.04, 0.02)
        low_price -= price_padding
        high_price += price_padding
        volume_max = max((volume for _, volume in rows), default=1.0) or 1.0

        def y_for(price: float) -> float:
            return top + plot_height * (high_price - price) / (high_price - low_price or 1)

        for step in range(5):
            fraction = step / 4
            y = top + plot_height * fraction
            value = high_price - (high_price - low_price) * fraction
            canvas.create_line(left, y, width - right, y, fill="#1c2a3d")
            canvas.create_text(left - 5, y, text=f"{value:.2f}", fill=MUTED, font=FONT_TINY, anchor="e")
        canvas.create_text(left + 2, 5, text="价格 / 筹码量", fill=TEXT, font=FONT_TINY, anchor="nw")

        summary = value_ci(day, "chipSummary", default={})
        summary = summary if isinstance(summary, dict) else {}
        last_price = as_float(value_ci(summary, "lastPrice"), float("nan"))
        mean_price = as_float(value_ci(summary, "meanPrice"), float("nan"))
        for price, volume in rows:
            y = y_for(price)
            bar_width = plot_width * volume / volume_max
            if last_price == last_price:
                color = BLUE if price > last_price else RED
            else:
                color = CYAN
            row_height = max(2.0, plot_height / max(1, len(rows)) * 0.72)
            canvas.create_rectangle(left, y - row_height / 2, left + max(1.0, bar_width), y + row_height / 2, fill=color, outline="")

        center_price = mean_price if mean_price == mean_price else last_price
        if center_price == center_price and low_price <= center_price <= high_price:
            center_y = y_for(center_price)
            canvas.create_line(left, center_y, width - right, center_y, fill=GOLD, dash=(4, 2))
            canvas.create_text(width - right, center_y - 2, text=f"均价 {center_price:.2f}", fill=GOLD, font=FONT_TINY, anchor="e")
        canvas.create_text(width - right, height - 3, text=f"最大量 {fmt_number(volume_max)}", fill=MUTED, font=FONT_TINY, anchor="se")

    @staticmethod
    def _chart_points(values: list[float | None], left: float, top: float, plot_width: float, plot_height: float, minimum: float, maximum: float) -> list[float]:
        span = maximum - minimum or 1
        result: list[float] = []
        for index, value in enumerate(values):
            if value is None:
                continue
            x = left + plot_width * index / max(1, len(values) - 1)
            y = top + plot_height * (maximum - value) / span
            result.extend((x, y))
        return result

    def _draw_stock_intraday(self) -> None:
        canvas = getattr(self, "stock_intraday_canvas", None)
        volume_canvas = getattr(self, "stock_intraday_volume_canvas", None)
        if canvas is None or volume_canvas is None:
            return
        canvas.delete("all")
        volume_canvas.delete("all")
        self._draw_watermark(canvas)
        rows = [row for row in getattr(self, "stock_intraday_rows", []) if isinstance(row, dict)]
        values = []
        averages = []
        for row in rows:
            close = as_float(value_ci(row, "close", "Close"), float("nan"))
            average = as_float(value_ci(row, "junj", "Junj"), float("nan"))
            values.append(close if close == close else None)
            averages.append(average if average == average else None)
        if not any(value is not None for value in values):
            empty_text = getattr(self, "stock_intraday_empty_text", "等待分时全推")
            canvas.create_text(max(200, canvas.winfo_width() / 2), max(50, canvas.winfo_height() / 2), text=empty_text, fill=MUTED, font=FONT_SMALL)
            volume_canvas.create_text(max(200, volume_canvas.winfo_width() / 2), max(25, volume_canvas.winfo_height() / 2), text="成交量", fill=MUTED, font=FONT_TINY)
            return
        all_values = [value for value in values + averages if value is not None]
        minimum, maximum = min(all_values), max(all_values)
        padding = max((maximum - minimum) * 0.10, max(abs(maximum), 1) * 0.001)
        minimum -= padding
        maximum += padding
        width = max(420, canvas.winfo_width())
        height = max(130, canvas.winfo_height())
        left, right, top, bottom = 50, 52, 20, 24
        plot_width = max(20, width - left - right)
        plot_height = max(20, height - top - bottom)
        for step in range(5):
            fraction = step / 4
            y = top + plot_height * fraction
            value = maximum - (maximum - minimum) * fraction
            canvas.create_line(left, y, width - right, y, fill="#1c2a3d")
            canvas.create_text(left - 6, y, text=f"{value:.2f}", fill=MUTED, font=FONT_TINY, anchor="e")
            if self.stock_yclose == self.stock_yclose and self.stock_yclose:
                rate = value / self.stock_yclose - 1
                canvas.create_text(width - right + 5, y, text=f"{rate:+.2%}", fill=RED if rate >= 0 else GREEN, font=FONT_TINY, anchor="w")
        canvas.create_text(left + 3, 5, text="现价", fill=BLUE, font=FONT_TINY, anchor="nw")
        if any(value is not None for value in averages):
            canvas.create_text(left + 42, 5, text="均价", fill=GOLD, font=FONT_TINY, anchor="nw")

        def draw_series(series: list[float | None], color: str) -> None:
            segment: list[float] = []
            for index, value in enumerate(series):
                if value is None:
                    if len(segment) >= 4:
                        canvas.create_line(*segment, fill=color, width=1.2)
                    segment = []
                    continue
                x = left + plot_width * index / max(1, len(series) - 1)
                y = top + plot_height * (maximum - value) / (maximum - minimum or 1)
                segment.extend((x, y))
            if len(segment) >= 4:
                canvas.create_line(*segment, fill=color, width=1.2)

        draw_series(values, BLUE)
        draw_series(averages, GOLD)
        label_indices = [index for index, row in enumerate(rows) if str(value_ci(row, "time", default="")).strip()]
        if not label_indices:
            label_indices = [0, len(rows) - 1]
        positions = sorted(set([label_indices[0], label_indices[-1]] + [label_indices[int(step * (len(label_indices) - 1) / 4)] for step in range(1, 4)]))
        for index in positions:
            if not 0 <= index < len(rows):
                continue
            x = left + plot_width * index / max(1, len(rows) - 1)
            canvas.create_line(x, top, x, top + plot_height, fill="#172437", dash=(2, 4))
            canvas.create_text(x, height - 5, text=str(value_ci(rows[index], "time", default="")), fill=MUTED, font=FONT_TINY, anchor="s")

        volume_values = [as_float(value_ci(row, "volume", "Volume"), 0) for row in rows]
        volume_width = max(420, volume_canvas.winfo_width())
        volume_height = max(34, volume_canvas.winfo_height())
        vleft, vright, vtop, vbottom = 50, 52, 4, 16
        vplot_width = max(20, volume_width - vleft - vright)
        vplot_height = max(10, volume_height - vtop - vbottom)
        volume_max = max(volume_values + [1])
        volume_canvas.create_line(vleft, vtop + vplot_height, volume_width - vright, vtop + vplot_height, fill="#1c2a3d")
        volume_canvas.create_text(vleft - 6, vtop + 3, text="量", fill=MUTED, font=FONT_TINY, anchor="e")
        for index, volume in enumerate(volume_values):
            if str(value_ci(rows[index], "session", default="")) == "separator":
                continue
            x = vleft + vplot_width * index / max(1, len(volume_values) - 1)
            bar_width = max(1, vplot_width / max(1, len(volume_values)) * 0.72)
            close = values[index]
            previous = values[index - 1] if index else close
            flag = as_int(value_ci(rows[index], "unmatchflag", "flag"), 0)
            if flag:
                color = RED if flag == 1 else GREEN
            else:
                color = RED if close is not None and previous is not None and close >= previous else GREEN
            bar_height = vplot_height * max(0, volume) / volume_max
            volume_canvas.create_rectangle(x - bar_width / 2, vtop + vplot_height - bar_height, x + bar_width / 2, vtop + vplot_height, fill=color, outline="")
        volume_canvas.create_text(volume_width - vright, volume_height - 4, text=fmt_number(max(volume_values)), fill=MUTED, font=FONT_TINY, anchor="se")
        hover_x = getattr(self, "stock_intraday_hover_x", None)
        if hover_x is not None:
            hover_event = type("StockHoverEvent", (), {"x": hover_x})()
            self._on_stock_intraday_motion(hover_event)

    def _clear_stock_intraday_hover(self, _event: tk.Event | None = None) -> None:
        canvas = getattr(self, "stock_intraday_canvas", None)
        self.stock_intraday_hover_x = None
        if canvas is not None:
            canvas.delete("stock_intraday_hover")

    def _on_stock_intraday_motion(self, event: tk.Event) -> None:
        canvas = getattr(self, "stock_intraday_canvas", None)
        rows = getattr(self, "stock_intraday_rows", [])
        if canvas is None or not rows:
            return
        self.stock_intraday_hover_x = int(event.x)
        width = max(420, canvas.winfo_width())
        height = max(130, canvas.winfo_height())
        left, right, top, bottom = 50, 52, 20, 24
        plot_width = max(20, width - left - right)
        index = round((max(left, min(width - right, event.x)) - left) / plot_width * max(1, len(rows) - 1))
        index = max(0, min(len(rows) - 1, index))
        row = rows[index]
        close = as_float(value_ci(row, "close", "Close"), float("nan"))
        if close != close:
            # 盘前与当日分时之间的断点不参与悬浮计算，取最近的真实点。
            for distance in range(1, len(rows)):
                candidates = (index - distance, index + distance)
                valid = next((candidate for candidate in candidates if 0 <= candidate < len(rows)), None)
                if valid is None:
                    continue
                candidate_close = as_float(value_ci(rows[valid], "close", "Close"), float("nan"))
                if candidate_close == candidate_close:
                    index = valid
                    row = rows[index]
                    close = candidate_close
                    break
        average = as_float(value_ci(row, "junj", "Junj"), float("nan"))
        if close != close:
            return
        all_values = []
        for item in rows:
            for key in ("close", "Close", "junj", "Junj"):
                value = as_float(value_ci(item, key), float("nan"))
                if value == value:
                    all_values.append(value)
        if not all_values:
            return
        minimum, maximum = min(all_values), max(all_values)
        padding = max((maximum - minimum) * 0.10, max(abs(maximum), 1) * 0.001)
        minimum -= padding
        maximum += padding
        x = left + plot_width * index / max(1, len(rows) - 1)
        y = top + (height - top - bottom) * (maximum - close) / (maximum - minimum or 1)
        time_text = str(value_ci(row, "time", default="—"))
        average_text = f"{average:,.2f}" if average == average else "—"
        details_lines = [f"{time_text}", f"现价  {close:,.2f}"]
        if average == average:
            details_lines.append(f"均价  {average_text}")
        if value_ci(row, "unmatchvol", "UnmatchVolume") not in (None, ""):
            details_lines.append(f"匹配量 {fmt_number(value_ci(row, 'volume', 'Volume'))}")
            details_lines.append(f"未匹配 {fmt_number(value_ci(row, 'unmatchvol', 'UnmatchVolume'))}")
        else:
            details_lines.append(f"成交量 {fmt_number(value_ci(row, 'volume', 'Volume'))}")
        details = "\n".join(details_lines)
        box_width, box_height = 170, 18 + 16 * len(details_lines)
        box_x = x + 12 if x < width - box_width - 20 else x - box_width - 12
        box_y = max(top + 4, min(height - box_height - 4, y - box_height / 2))
        canvas.delete("stock_intraday_hover")
        canvas.create_line(x, top, x, height - bottom, fill=GOLD, dash=(3, 3), tags="stock_intraday_hover")
        canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=BLUE, outline=WHITE, tags="stock_intraday_hover")
        canvas.create_rectangle(box_x, box_y, box_x + box_width, box_y + box_height, fill="#18283b", outline=GOLD, tags="stock_intraday_hover")
        canvas.create_text(box_x + 8, box_y + 7, text=details, fill=WHITE, font=FONT_TINY, anchor="nw", justify="left", tags="stock_intraday_hover")

    def _clear_stock_kline_hover(self, _event: tk.Event | None = None) -> None:
        canvas = getattr(self, "stock_kline_canvas", None)
        self.stock_kline_hover_x = None
        if canvas is not None:
            canvas.delete("stock_kline_hover")

    def _on_stock_kline_motion(self, event: tk.Event) -> None:
        canvas = getattr(self, "stock_kline_canvas", None)
        if canvas is None:
            return
        self.stock_kline_hover_x = int(event.x)
        entries = self._stock_kline_entries()
        if not entries:
            return
        width = max(520, canvas.winfo_width())
        height = max(190, canvas.winfo_height())
        left, right, top, bottom = 52, 12, 22, 24
        plot_width = max(20, width - left - right)
        slot = plot_width / max(1, len(entries))
        index = int((max(left, min(width - right, event.x)) - left) / max(1, slot))
        index = max(0, min(len(entries) - 1, index))
        entry = entries[index]
        self._set_stock_chip_for_date(entry["date"])
        minimum = min(item["low"] for item in entries)
        maximum = max(item["high"] for item in entries)
        padding = max((maximum - minimum) * 0.08, max(abs(maximum), 1) * 0.002)
        minimum -= padding
        maximum += padding
        x = left + slot * (index + 0.5)
        y = top + (height - top - bottom) * (maximum - entry["close"]) / (maximum - minimum or 1)
        details = (
            f"{entry['date']}\n"
            f"开 {entry['open']:,.2f}  高 {entry['high']:,.2f}\n"
            f"低 {entry['low']:,.2f}  收 {entry['close']:,.2f}\n"
            f"成交量 {fmt_number(entry['volume'])}"
        )
        box_width, box_height = 178, 72
        box_x = x + 12 if x < width - box_width - 20 else x - box_width - 12
        box_y = max(top + 4, min(height - box_height - 4, y - box_height / 2))
        canvas.delete("stock_kline_hover")
        canvas.create_line(x, top, x, height - bottom, fill=GOLD, dash=(3, 3), tags="stock_kline_hover")
        canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=GOLD, outline=WHITE, tags="stock_kline_hover")
        canvas.create_rectangle(box_x, box_y, box_x + box_width, box_y + box_height, fill="#18283b", outline=GOLD, tags="stock_kline_hover")
        canvas.create_text(box_x + 8, box_y + 7, text=details, fill=WHITE, font=FONT_TINY, anchor="nw", justify="left", tags="stock_kline_hover")

    def _draw_stock_kline(self) -> None:
        canvas = getattr(self, "stock_kline_canvas", None)
        volume_canvas = getattr(self, "stock_kline_volume_canvas", None)
        if canvas is None or volume_canvas is None:
            return
        canvas.delete("all")
        volume_canvas.delete("all")
        self._draw_watermark(canvas)
        entries = self._stock_kline_entries()
        if not entries:
            canvas.create_text(max(200, canvas.winfo_width() / 2), max(50, canvas.winfo_height() / 2), text="等待历史 K 线", fill=MUTED, font=FONT_SMALL)
            volume_canvas.create_text(max(200, volume_canvas.winfo_width() / 2), max(25, volume_canvas.winfo_height() / 2), text="成交量", fill=MUTED, font=FONT_TINY)
            self._draw_stock_chip()
            return
        width = max(520, canvas.winfo_width())
        height = max(190, canvas.winfo_height())
        left, right, top, bottom = 52, 12, 22, 24
        plot_width = max(20, width - left - right)
        plot_height = max(30, height - top - bottom)
        minimum = min(entry["low"] for entry in entries)
        maximum = max(entry["high"] for entry in entries)
        padding = max((maximum - minimum) * 0.08, max(abs(maximum), 1) * 0.002)
        minimum -= padding
        maximum += padding
        for step in range(5):
            fraction = step / 4
            y = top + plot_height * fraction
            value = maximum - (maximum - minimum) * fraction
            canvas.create_line(left, y, width - right, y, fill="#1c2a3d")
            canvas.create_text(left - 6, y, text=f"{value:.2f}", fill=MUTED, font=FONT_TINY, anchor="e")
        canvas.create_text(left + 3, 6, text="历史 K 线", fill=TEXT, font=FONT_TINY, anchor="nw")

        def y_for(value: float) -> float:
            return top + plot_height * (maximum - value) / (maximum - minimum or 1)

        slot = plot_width / max(1, len(entries))
        body_width = max(2, min(10, slot * 0.58))
        for index, entry in enumerate(entries):
            x = left + slot * (index + 0.5)
            up = entry["close"] >= entry["open"]
            color = RED if up else GREEN
            canvas.create_line(x, y_for(entry["high"]), x, y_for(entry["low"]), fill=color)
            body_top = y_for(max(entry["open"], entry["close"]))
            body_bottom = y_for(min(entry["open"], entry["close"]))
            if body_bottom - body_top < 1:
                body_bottom = body_top + 1
            canvas.create_rectangle(x - body_width / 2, body_top, x + body_width / 2, body_bottom, fill=color if up else PANEL, outline=color)

        positions = sorted(set([0, len(entries) - 1] + [int(index * (len(entries) - 1) / 4) for index in range(1, 4)]))
        for index in positions:
            x = left + slot * (index + 0.5)
            label = entries[index]["date"]
            if len(label) > 10:
                label = label[:10]
            canvas.create_text(x, height - 5, text=label, fill=MUTED, font=FONT_TINY, anchor="s")

        volume_values = [max(0, entry["volume"]) for entry in entries]
        volume_width = max(520, volume_canvas.winfo_width())
        volume_height = max(34, volume_canvas.winfo_height())
        vleft, vright, vtop, vbottom = 52, 12, 4, 16
        vplot_width = max(20, volume_width - vleft - vright)
        vplot_height = max(10, volume_height - vtop - vbottom)
        volume_max = max(volume_values + [1])
        volume_canvas.create_line(vleft, vtop + vplot_height, volume_width - vright, vtop + vplot_height, fill="#1c2a3d")
        volume_canvas.create_text(vleft - 6, vtop + 3, text="量", fill=MUTED, font=FONT_TINY, anchor="e")
        for index, volume in enumerate(volume_values):
            x = vleft + vplot_width * (index + 0.5) / max(1, len(volume_values))
            bar_width = max(2, min(10, vplot_width / max(1, len(volume_values)) * 0.58))
            color = RED if entries[index]["close"] >= entries[index]["open"] else GREEN
            bar_height = vplot_height * volume / volume_max
            volume_canvas.create_rectangle(x - bar_width / 2, vtop + vplot_height - bar_height, x + bar_width / 2, vtop + vplot_height, fill=color, outline="")
        volume_canvas.create_text(volume_width - vright, volume_height - 4, text=fmt_number(volume_max), fill=MUTED, font=FONT_TINY, anchor="se")
        hover_x = getattr(self, "stock_kline_hover_x", None)
        if hover_x is not None:
            hover_event = type("StockKlineHoverEvent", (), {"x": hover_x})()
            self._on_stock_kline_motion(hover_event)
        elif self.stock_chip_selected_date is None:
            self._set_stock_chip_for_date(entries[-1]["date"])
        else:
            self._draw_stock_chip()

    @staticmethod
    def _index_ws_rows(payload: Any) -> list[dict[str, Any]]:
        """把 2001 全推的指数对象转换成真正的指数表。"""
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            base = item.get("base") or {}
            if not isinstance(base, dict):
                continue
            precise = max(0, as_int(base.get("precise"), 0))
            divisor = 10 ** precise
            last_raw = as_float(value_ci(item, "newprice", "newPrice"), float("nan"))
            pre_raw = as_float(value_ci(item, "yclose", "YClose"), float("nan"))
            last = last_raw / divisor if last_raw == last_raw else float("nan")
            preclose = pre_raw / divisor if pre_raw == pre_raw else float("nan")
            change = last / preclose - 1 if preclose == preclose and preclose else float("nan")
            market = str(value_ci(base, "oldmarketcode", "ExchangeID", default=""))
            price_text = f"{last:,.2f}" if last == last else "—"
            diff_text = f"{last - preclose:+,.2f}" if last == last and preclose == preclose else "—"
            rows.append({
                "名称": value_ci(base, "name", "InstrumentName", default="—"),
                "代码": value_ci(base, "code", "InstrumentID", default="—"),
                "市场": enum_meaning("market", market) or market or "—",
                "现价": price_text,
                "涨跌额": diff_text,
                "涨跌幅": fmt_percent(change, True) if change == change else "—",
                "上涨": value_ci(item, "szjs", default="—"),
                "下跌": value_ci(item, "xdjs", default="—"),
                "平盘": value_ci(item, "ppjs", default="—"),
            })
        return rows

    @staticmethod
    def _index_rows(payload: Any) -> list[dict[str, Any]]:
        """兼容旧 HTTP 响应；首屏不再把这个个股排行当成指数。"""
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        rows: list[dict[str, Any]] = []
        if not isinstance(data, dict):
            return rows
        for group, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items[:6]:
                if not isinstance(item, dict):
                    continue
                static = (item.get("StaticData") or [{}])[0]
                dyna = (item.get("DynaData") or [{}])[0]
                stats = (item.get("StatisticsData") or [{}])[0]
                last = value_ci(dyna, "LastPrice", "lastPrice")
                preclose = value_ci(stats, "PreClosePrice", "preClosePrice")
                change = ((as_float(last) / as_float(preclose) - 1) if as_float(preclose) else 0)
                rows.append({"名称": value_ci(static, "InstrumentName", default=group), "代码": value_ci(static, "InstrumentID", default="—"), "现价": fmt_number(last), "涨跌幅": fmt_percent(change, True)})
        return rows

    @staticmethod
    def _sector_rows(payload: Any) -> list[dict[str, Any]]:
        """把板块行情原始字段整理成“板块身份 + 强弱指标”表。"""
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        plates = data.get("plate", []) if isinstance(data, dict) else []
        if not isinstance(plates, list):
            return []

        def scaled_percent(value: Any) -> str:
            number = as_float(value, float("nan"))
            return f"{number / 100:+.2f}%" if number == number else "—"

        def group_text(value: Any) -> str:
            if not isinstance(value, list) or not value:
                return "—"
            result: list[str] = []
            for member in value[:3]:
                if not isinstance(member, dict):
                    continue
                name = value_ci(member, "ProdName", "name", default="—")
                change = scaled_percent(value_ci(member, "PxChangeRate", "pxChangeRate"))
                result.append(f"{name} {change}")
            return "、".join(result) if result else "—"

        type_map = {"XBHS.HY": "行业板块", "XBHS.GN": "概念板块", "XBHS.DY": "地域板块"}
        rows: list[dict[str, Any]] = []
        for plate in plates:
            if not isinstance(plate, dict):
                continue
            raw_type = str(value_ci(plate, "HqTypeCode", "hqTypeCode", default=""))
            rows.append({
                "板块": value_ci(plate, "ProdName", "prodName", default="—"),
                "类型": type_map.get(raw_type.upper(), raw_type or "—"),
                "涨跌幅": scaled_percent(value_ci(plate, "PxChangeRate", "pxChangeRate")),
                "上涨": value_ci(plate, "RiseCount", default="—"),
                "下跌": value_ci(plate, "FallCount", default="—"),
                "平盘": value_ci(plate, "FlatCount", default="—"),
                "涨停": value_ci(plate, "UpLimitNum", default="—"),
                "跌停": value_ci(plate, "DownLimitNum", default="—"),
                "成交额": fmt_number(value_ci(plate, "BusinessBalance", default=None)),
                "主力净流入": fmt_number(value_ci(plate, "Fundflow", "netFundFlow", default=None)),
                "领涨股": group_text(value_ci(plate, "RiseFirstGrp", "riseFirstGrp", default=[])),
                "领跌股": group_text(value_ci(plate, "FallFirstGrp", "fallFirstGrp", default=[])),
            })
        return rows

    @staticmethod
    def _activity_rows(payload: Any) -> list[dict[str, Any]]:
        """按业务字段展示真正的个股异动，而不是涨跌停统计。"""
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sector = item.get("sector") or {}
            if not isinstance(sector, dict):
                sector = {}
            px_change = value_ci(item, "pxChangeRate", "Px_change_rate")
            snapshot_change = value_ci(item, "pxChangeRateSnapshot", "Px_change_rate_snapshot")
            sector_change = value_ci(sector, "pxChangeRate", "Px_change_rate")
            type_code = value_ci(item, "typeCode", default="")
            type_name = value_ci(item, "typeName", default="") or enum_meaning("typeCode", type_code, "stock/anomalies") or "—"
            rows.append({
                "时间": datetime_text(value_ci(item, "alarmTime", "quoteTime")),
                "代码": value_ci(item, "symbol", default="—"),
                "名称": value_ci(item, "name", default="—"),
                "最新价": value_ci(item, "lastPx", default="—"),
                "异动时价格": value_ci(item, "priceSnapshot", default="—"),
                "涨跌幅": fmt_percent(px_change, True),
                "异动时涨跌幅": fmt_percent(snapshot_change, True),
                "异动类型": type_name,
                "异动数量": value_ci(item, "displayData", default="—"),
                "所属板块": value_ci(sector, "name", default="—"),
                "板块涨跌幅": fmt_percent(sector_change, True),
            })
        return rows

    @staticmethod
    def _sector_anomaly_rows(payload: Any) -> list[dict[str, Any]]:
        """按业务页面的六列展示板块异动，内部方向码只参与挑选代表个股。"""
        data = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return []

        def sector_percent(value: Any) -> str:
            number = as_float(value, float("nan"))
            # 板块异动接口的 platePxChangeRate 是百分比的百分之一，327 表示 3.27%。
            return f"{number / 100:+.2f}%" if number == number else "—"

        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            direction = str(value_ci(item, "typeDirection", default="")).lower()
            group_keys = ("fallFirstGrp", "riseFirstGrp") if direction == "down" else ("riseFirstGrp", "fallFirstGrp")
            representative: dict[str, Any] = {}
            for group_key in group_keys:
                group = value_ci(item, group_key, default=[])
                if isinstance(group, list):
                    representative = next((member for member in group if isinstance(member, dict)), {})
                if representative:
                    break
            state = value_ci(item, "state", default=None)
            if state in (None, ""):
                state = enum_meaning("stateCode", value_ci(item, "stateCode"), "sector/anomaly/current")
            rows.append({
                "时间": clock_text(value_ci(item, "datetime", "updateTime")),
                "板块名称": value_ci(item, "prodName", "name", default="—"),
                "类型": state or "—",
                "涨幅": sector_percent(value_ci(item, "platePxChangeRate", "pxChangeRate")),
                "代表个股": value_ci(representative, "name", "prodName", default="—"),
                "个股涨跌幅": fmt_percent(value_ci(representative, "pxChangeRate", "Px_change_rate"), True),
            })
        return rows

    @staticmethod
    def _overview_rows(payload: Any) -> list[dict[str, Any]]:
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return []
        stocks = data.get("Stocks")
        if isinstance(stocks, list):
            return [row for row in stocks if isinstance(row, dict)][:300]
        rows: list[dict[str, Any]] = []
        for value in data.values():
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
        return rows[:300]

    def _draw_market_charts(self) -> None:
        self._draw_limit_trend()
        self._draw_change_trend()
        self._draw_capital_flow_trend()
        self._draw_change_distribution()

    def _draw_limit_trend(self) -> None:
        canvas = self.trend_canvas
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        self._draw_watermark(canvas, width, height)
        rows = self.limit_trend_data[-240:]
        if not rows:
            canvas.create_text(width / 2, height / 2, text="等待趋势数据", fill=MUTED, font=FONT_SMALL)
            return
        left, right, top, bottom = 38, 12, 26, 26
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        up_values = [as_int(value_ci(row, "countUpLimit", "CountUpLimit")) for row in rows]
        down_values = [as_int(value_ci(row, "countDownLimit", "CountDownLimit")) for row in rows]
        maximum = max(up_values + down_values + [1])
        for step in range(5):
            value = maximum * step / 4
            y = top + plot_height - plot_height * step / 4
            canvas.create_line(left, y, width - right, y, fill=BORDER, width=1)
            canvas.create_text(left - 6, y, text=str(round(value)), fill=MUTED, font=FONT_TINY, anchor="e")

        def points(values: list[int]) -> list[float]:
            if len(values) == 1:
                return [left + plot_width / 2, top + plot_height - plot_height * values[0] / maximum]
            result: list[float] = []
            for index, value in enumerate(values):
                result.extend((left + plot_width * index / (len(values) - 1), top + plot_height - plot_height * value / maximum))
            return result

        up_points = points(up_values)
        down_points = points(down_values)
        canvas.create_line(*up_points, fill=RED, width=2, smooth=True)
        canvas.create_line(*down_points, fill=GREEN, width=2, smooth=True)
        latest_up = up_values[-1]
        latest_down = down_values[-1]
        canvas.create_text(width - right, 8, text=f"涨停 {latest_up}", fill=RED, font=FONT_TINY, anchor="ne")
        canvas.create_text(width - right - 62, 8, text=f"跌停 {latest_down}", fill=GREEN, font=FONT_TINY, anchor="ne")
        tick_count = min(5, len(rows))
        for index in range(tick_count):
            row_index = round((len(rows) - 1) * index / max(1, tick_count - 1))
            x = left + plot_width * row_index / max(1, len(rows) - 1)
            label = clock_text(value_ci(rows[row_index], "time", "datetime"))[:5]
            canvas.create_text(x, height - 7, text=label, fill=MUTED, font=FONT_TINY, anchor="s")
        self._draw_trend_hover(
            canvas,
            rows,
            self.trend_hover_index.get("limit"),
            left,
            right,
            top,
            bottom,
            maximum,
            [("涨停", up_values, RED), ("跌停", down_values, GREEN)],
        )

    def _draw_change_trend(self) -> None:
        canvas = self.change_trend_canvas
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        self._draw_watermark(canvas, width, height)
        rows = self.limit_trend_data[-240:]
        if not rows:
            canvas.create_text(width / 2, height / 2, text="等待趋势数据", fill=MUTED, font=FONT_SMALL)
            return
        left, right, top, bottom = 38, 12, 26, 26
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        up_values = [as_int(value_ci(row, "countUp", "CountUp")) for row in rows]
        down_values = [as_int(value_ci(row, "countDown", "CountDown")) for row in rows]
        maximum = max(up_values + down_values + [1])
        for step in range(5):
            value = maximum * step / 4
            y = top + plot_height - plot_height * step / 4
            canvas.create_line(left, y, width - right, y, fill=BORDER, width=1)
            canvas.create_text(left - 6, y, text=str(round(value)), fill=MUTED, font=FONT_TINY, anchor="e")

        def points(values: list[int]) -> list[float]:
            if len(values) == 1:
                return [left + plot_width / 2, top + plot_height - plot_height * values[0] / maximum]
            result: list[float] = []
            for index, value in enumerate(values):
                result.extend((left + plot_width * index / (len(values) - 1), top + plot_height - plot_height * value / maximum))
            return result

        canvas.create_line(*points(down_values), fill=GREEN, width=2, smooth=True)
        canvas.create_line(*points(up_values), fill=RED, width=2, smooth=True)
        latest_up = up_values[-1]
        latest_down = down_values[-1]
        canvas.create_text(width - right, 8, text=f"上涨 {latest_up}", fill=RED, font=FONT_TINY, anchor="ne")
        canvas.create_text(width - right - 72, 8, text=f"下跌 {latest_down}", fill=GREEN, font=FONT_TINY, anchor="ne")
        tick_count = min(5, len(rows))
        for index in range(tick_count):
            row_index = round((len(rows) - 1) * index / max(1, tick_count - 1))
            x = left + plot_width * row_index / max(1, len(rows) - 1)
            label = clock_text(value_ci(rows[row_index], "time", "datetime"))[:5]
            canvas.create_text(x, height - 7, text=label, fill=MUTED, font=FONT_TINY, anchor="s")
        self._draw_trend_hover(
            canvas,
            rows,
            self.trend_hover_index.get("change"),
            left,
            right,
            top,
            bottom,
            maximum,
            [("上涨", up_values, RED), ("平盘", [as_int(value_ci(row, "countFlat", "CountFlat")) for row in rows], MUTED), ("下跌", down_values, GREEN)],
        )

    def _draw_capital_flow_trend(self) -> None:
        canvas = self.capital_flow_canvas
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        self._draw_watermark(canvas, width, height)
        rows = self.capital_flow_data[-240:]
        if not rows:
            self.capital_flow_title_var.set("主力净流入")
            canvas.create_text(width / 2, height / 2, text="等待资金趋势数据", fill=MUTED, font=FONT_SMALL)
            return
        left, right, top, bottom = 38, 12, 26, 26
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        values = [as_float(value_ci(row, "netFlow", "NetFlow"), 0.0) / 100000000 for row in rows]
        maximum = max([abs(value) for value in values] + [1.0])
        latest = values[-1]
        self.capital_flow_title_var.set(f"沪深两市主力净流入：{latest:+.0f}亿")
        for step in range(5):
            value = maximum * (step - 2) / 2
            y = top + plot_height * (2 - step) / 4
            canvas.create_line(left, y, width - right, y, fill=BORDER, width=1)
            canvas.create_text(left - 6, y, text=str(round(value)), fill=MUTED, font=FONT_TINY, anchor="e")

        points: list[float] = []
        for index, value in enumerate(values):
            points.extend((left + plot_width * index / max(1, len(values) - 1), top + plot_height / 2 - plot_height * value / (2 * maximum)))
        canvas.create_line(*points, fill=RED, width=2, smooth=True)
        tick_count = min(5, len(rows))
        for index in range(tick_count):
            row_index = round((len(rows) - 1) * index / max(1, tick_count - 1))
            x = left + plot_width * row_index / max(1, len(rows) - 1)
            label = clock_text(value_ci(rows[row_index], "minTime", "time", "datetime"))[:5]
            canvas.create_text(x, height - 7, text=label, fill=MUTED, font=FONT_TINY, anchor="s")
        self._draw_capital_flow_hover(canvas, rows, self.trend_hover_index.get("capital"), left, right, top, bottom, maximum, values)

    @staticmethod
    def _draw_capital_flow_hover(
        canvas: tk.Canvas,
        rows: list[dict[str, Any]],
        index: int | None,
        left: int,
        right: int,
        top: int,
        bottom: int,
        maximum: float,
        values: list[float],
    ) -> None:
        if index is None or not rows:
            return
        index = max(0, min(len(rows) - 1, index))
        width = max(300, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        x = left + plot_width * index / max(1, len(rows) - 1)
        y = top + plot_height / 2 - plot_height * values[index] / (2 * max(maximum, 1.0))
        canvas.create_line(x, top, x, height - bottom, fill=GOLD, dash=(3, 3), width=1)
        canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=RED, outline=WHITE, width=1)
        lines = [
            f"时间  {clock_text(value_ci(rows[index], 'minTime', 'time', 'datetime'))}",
            f"净流入  {values[index]:+.2f}亿",
        ]
        tooltip_width = 142
        tooltip_height = 10 + len(lines) * 16
        box_x = x + 10 if x + 10 + tooltip_width <= width - right else x - tooltip_width - 10
        box_x = max(left + 2, box_x)
        box_y = top + 5
        canvas.create_rectangle(box_x, box_y, box_x + tooltip_width, box_y + tooltip_height, fill="#17263a", outline=GOLD, width=1)
        for line_index, line in enumerate(lines):
            canvas.create_text(box_x + 8, box_y + 7 + line_index * 16, text=line, fill=TEXT, font=FONT_TINY, anchor="w")

    def _on_trend_motion(self, event: tk.Event, kind: str) -> None:
        rows = self.capital_flow_data[-240:] if kind == "capital" else self.limit_trend_data[-240:]
        if not rows:
            return
        canvas = {"limit": self.trend_canvas, "change": self.change_trend_canvas, "capital": self.capital_flow_canvas}[kind]
        width = max(300, canvas.winfo_width())
        left, right = 38, 12
        plot_width = max(10, width - left - right)
        x = min(max(float(event.x), left), width - right)
        index = round((x - left) / plot_width * max(1, len(rows) - 1))
        index = max(0, min(len(rows) - 1, index))
        if self.trend_hover_index.get(kind) == index:
            return
        self.trend_hover_index[kind] = index
        if kind == "limit":
            self._draw_limit_trend()
        elif kind == "change":
            self._draw_change_trend()
        else:
            self._draw_capital_flow_trend()

    def _on_trend_leave(self, kind: str) -> None:
        if self.trend_hover_index.get(kind) is None:
            return
        self.trend_hover_index[kind] = None
        if kind == "limit":
            self._draw_limit_trend()
        elif kind == "change":
            self._draw_change_trend()
        else:
            self._draw_capital_flow_trend()

    @staticmethod
    def _draw_trend_hover(
        canvas: tk.Canvas,
        rows: list[dict[str, Any]],
        index: int | None,
        left: int,
        right: int,
        top: int,
        bottom: int,
        maximum: int,
        series: list[tuple[str, list[int], str]],
    ) -> None:
        if index is None or not rows:
            return
        index = max(0, min(len(rows) - 1, index))
        width = max(300, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        x = left + plot_width * index / max(1, len(rows) - 1)
        canvas.create_line(x, top, x, height - bottom, fill=GOLD, dash=(3, 3), width=1)
        for _label, values, color in series:
            value = values[index]
            y = top + plot_height - plot_height * value / max(1, maximum)
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=WHITE, width=1)
        lines = [f"时间  {clock_text(value_ci(rows[index], 'time', 'datetime'))}"]
        lines.extend(f"{label}  {values[index]}" for label, values, _color in series)
        tooltip_width = max(132, min(205, max(len(line) for line in lines) * 8 + 18))
        tooltip_height = 10 + len(lines) * 16
        box_x = x + 10
        if box_x + tooltip_width > width - right:
            box_x = x - tooltip_width - 10
        box_x = max(left + 2, box_x)
        box_y = top + 5
        canvas.create_rectangle(box_x, box_y, box_x + tooltip_width, box_y + tooltip_height, fill="#17263a", outline=GOLD, width=1)
        for line_index, line in enumerate(lines):
            canvas.create_text(box_x + 8, box_y + 7 + line_index * 16, text=line, fill=TEXT, font=FONT_TINY, anchor="w")

    def _draw_change_distribution(self) -> None:
        canvas = self.distribution_canvas
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        height = max(120, canvas.winfo_height())
        self._draw_watermark(canvas, width, height)
        data = self.limit_distribution_data
        bins = (
            ("跌停", "downLimit", GREEN), ("<-7%", "downLt7", GREEN), ("-7~-5%", "down75", GREEN),
            ("-5~-2%", "down52", GREEN), ("-2~0%", "down20", GREEN), ("0", "flat", MUTED),
            ("0~2%", "up02", RED), ("2~5%", "up25", RED), ("5~7%", "up57", RED),
            (">7%", "upGt7", RED), ("涨停", "upLimit", RED),
        )
        values = [as_int(data.get(key)) for _, key, _ in bins]
        if not any(values):
            canvas.create_text(width / 2, height / 2, text="等待分布数据", fill=MUTED, font=FONT_SMALL)
            return
        left, right, top, bottom = 28, 8, 28, 34
        plot_width = max(10, width - left - right)
        plot_height = max(10, height - top - bottom)
        maximum = max(values + [1])
        for step in range(3):
            value = maximum * step / 2
            y = top + plot_height - plot_height * step / 2
            canvas.create_line(left, y, width - right, y, fill=BORDER, width=1)
            canvas.create_text(left - 5, y, text=str(round(value)), fill=MUTED, font=FONT_TINY, anchor="e")
        slot = plot_width / len(bins)
        bar_width = max(8, slot * 0.62)
        for index, ((label, _key, color), value) in enumerate(zip(bins, values)):
            center = left + slot * (index + 0.5)
            bar_height = plot_height * value / maximum
            canvas.create_rectangle(center - bar_width / 2, top + plot_height - bar_height, center + bar_width / 2, top + plot_height, fill=color, outline="")
            canvas.create_text(center, top + plot_height - bar_height - 4, text=str(value), fill=color, font=FONT_TINY, anchor="s")
            display_label = label.replace("~", "~\n")
            canvas.create_text(center, height - 7, text=display_label, fill=MUTED, font=FONT_TINY, anchor="s")
        canvas.create_text(width - right, 8, text=f"上涨 {as_int(data.get('up'))}", fill=RED, font=FONT_TINY, anchor="ne")
        canvas.create_text(width - right - 72, 8, text=f"下跌 {as_int(data.get('down'))}", fill=GREEN, font=FONT_TINY, anchor="ne")

    def _on_ws_state(self, state: str) -> None:
        if state == "missing":
            self.status_var.set("缺少 websocket-client，请执行 python -m pip install websocket-client")
            self.stock_status.configure(text="缺少 websocket-client", fg=RED)
        elif state == "open":
            self.status_var.set("WebSocket 已连接")
            self.stock_status.configure(text="实时连接已建立", fg=GREEN)
            # 长连接重连后旧 801 响应可能仍在队列中，必须使其失效，
            # 再以当前标的重新建立快照和分页游标。
            market, code = market_code(self.code_var.get())
            self._reset_trade_state(f"{market}{code}")
            self.ws.send(self._ws_message(2001))
            self.ws.send(self._ws_message(201))
            self._send_trade_request(TRADE_PAGE_SIZE)
            for message_type in (501, 504):
                self.ws.send(self._ws_message(message_type))
        elif state.startswith("closed"):
            self._trade_loading = False
            self._trade_pending_no = None
            self._trade_pending_num = None
            self._update_trade_status()
            self.stock_status.configure(text="WebSocket 已断开", fg=MUTED)

    def _on_ws_error(self, message: str) -> None:
        self.status_var.set("实时数据连接异常")
        self.stock_status.configure(text="实时连接异常", fg=RED)
        self._trade_loading = False
        self._trade_pending_no = None
        self._trade_pending_num = None
        self._update_trade_status()

    def _merge_trade_rows(self, rows: list[dict[str, Any]]) -> tuple[int, bool]:
        """把快照/增量成交合并到同一份模型，返回新增数和是否发生变化。"""
        new_count = 0
        changed = False
        for source in rows:
            if not isinstance(source, dict):
                continue
            row = dict(source)
            key = self._trade_dedup_key(row)
            previous = self._trade_rows_by_key.get(key)
            if previous is None:
                self._trade_rows_by_key[key] = row
                new_count += 1
                changed = True
            elif previous != row:
                merged = dict(previous)
                merged.update(row)
                self._trade_rows_by_key[key] = merged
                changed = True
        if changed:
            self.stock_trades = sorted(self._trade_rows_by_key.values(), key=self._trade_sort_key, reverse=True)
            self._trade_seen_keys = set(self._trade_rows_by_key)
        return new_count, changed

    def _trade_message_matches_current_symbol(self, body: dict[str, Any]) -> bool:
        key = body.get("key") or {}
        msg_market = str(value_ci(key, "oldmarketcode", "market", default="")).lower()
        msg_code = str(value_ci(key, "code", default="")).lower()
        current_market, current_code = market_code(self.code_var.get())
        return (
            not msg_code
            or msg_code == current_code.lower()
            and (not msg_market or msg_market == current_market.lower())
        )

    def _update_trade_status(self) -> None:
        if self._trade_loading:
            return
        if not self.stock_trades:
            self._set_trade_status("暂无分时成交")
        elif self._trade_has_more:
            self._set_trade_status(f"共 {len(self.stock_trades)} 条 · 滚动加载历史")
        else:
            self._set_trade_status(f"已加载全部（共 {len(self.stock_trades)} 条）")

    def _on_ws_message(self, message: Any) -> None:
        if not isinstance(message, dict):
            return
        header = message.get("Header") or message.get("header") or {}
        body = message.get("Body") or message.get("body") or {}
        message_type = as_int(value_ci(header, "MsgType", "msgType", default=0))
        self.message_count += 1
        self.last_message_at = time.time()
        self.message_var.set(str(self.message_count))
        self.updated_var.set(time.strftime("%H:%M:%S"))
        if message_type == 504 and isinstance(body, dict):
            # 504 是盘前竞价的 10 秒快照。pushflag 版本可能分批到达，不能只保留最后一帧。
            previous = self.live.get(504)
            previous_rows = records_from(previous.get("data", [])) if isinstance(previous, dict) else []
            current_rows = records_from(body.get("data", []))
            merged: dict[str, dict[str, Any]] = {}
            for row in previous_rows + current_rows:
                if not isinstance(row, dict):
                    continue
                timestamp = value_ci(row, "time", "Time", default="")
                merged[str(timestamp)] = row
            if merged:
                body = dict(body)
                body["data"] = [merged[key] for key in sorted(merged, key=lambda item: as_float(item, 0))]
        elif message_type == 801 and isinstance(body, dict):
            if not self._trade_message_matches_current_symbol(body):
                # 重连/换股后迟到的旧响应不能污染当前标的。
                return
            incoming_rows = records_from(body.get("data", []))
            pending_no = self._trade_pending_no
            pending_num = self._trade_pending_num or self._trade_requested_num
            response_no = as_int(value_ci(header, "No", "no", default=-1), -1)
            response_generation = self._trade_request_generations.get(response_no)
            if response_generation is not None and response_generation != self._trade_generation:
                # A response from before reconnect belongs to the old request generation.
                return
            is_pending_response = pending_no is not None and response_no == pending_no
            new_count, _changed = self._merge_trade_rows(incoming_rows)
            if is_pending_response:
                self._trade_pending_no = None
                self._trade_pending_num = None
                self._trade_loading = False
                # 801 的 num 是“返回条数”而不是页码。请求更大的
                # num 会带回更早成交；无新增或不足 requested_num 即到头。
                self._trade_has_more = bool(incoming_rows) and len(incoming_rows) >= pending_num and new_count > 0
                self._update_trade_status()
            elif not self._trade_loading:
                self._update_trade_status()
            body = dict(body)
            body["data"] = self.stock_trades
        self.live[message_type] = body
        self.live["raw"] = message
        self._live_dirty_types.add(message_type)
        self.render_pending = True

    def _live_feed_key(self) -> dict[str, Any]:
        for message_type in (201, 501, 801, 504):
            body = self.live.get(message_type, {})
            if isinstance(body, dict) and isinstance(body.get("key"), dict):
                return body["key"]
        return {}

    def _render_stock_trade_table(self, price_unit: float | None = None) -> None:
        """只更新成交表发生变化的行，不触碰个股详情其它控件。"""
        if price_unit is None:
            price_unit = as_float(value_ci(self._live_feed_key(), "unit"), 1) or 1
        trade_view: list[dict[str, Any]] = []
        for source in self.stock_trades:
            row = dict(source)
            raw_time = value_ci(row, "time", "Time", default="—")
            time_number = as_float(raw_time, float("nan"))
            if time_number == time_number and time_number > 100000000:
                row["time"] = time.strftime("%H:%M:%S", time.localtime(time_number))
            else:
                row["time"] = str(raw_time)
            price = value_ci(row, "newprice", "newPrice", "price")
            price_number = as_float(price, float("nan"))
            if price_number == price_number:
                divisor = price_unit
                if divisor > 1 and abs(price_number) >= divisor:
                    price = price_number / divisor
            volume = value_ci(row, "xianl", "volume")
            tradenum = value_ci(row, "tradenum")
            direction = value_ci(row, "xsfx", default="")
            if direction not in (None, ""):
                direction = {1: "卖", 2: "买"}.get(as_int(direction), str(direction))
            dedup_key = self._trade_dedup_key(source)
            row_iid = "t_" + hashlib.sha1(repr(dedup_key).encode("utf-8")).hexdigest()
            trade_view.append({
                "_iid": row_iid,
                "时间": row.get("time", "—"),
                "成交价": fmt_number(price),
                "成交量": fmt_number(volume),
                "笔数": fmt_number(tradenum),
                # 不展示该辅助字段，但让 DataTable 继续按买卖方向着色。
                "xsfx": direction,
            })
        self.stock_trade_table.set_rows(
            trade_view,
            columns=["时间", "成交价", "成交量", "笔数"],
            empty_message="暂无成交数据",
        )
        for index, width in enumerate((84, 70, 76, 54), start=1):
            if index <= len(self.stock_trade_table.tree["columns"]):
                self.stock_trade_table.tree.column(f"#{index}", width=width, minwidth=width, stretch=False)

    def _update_stock_feed_status(self) -> None:
        feeds = [
            name for name, present in (
                ("行情", bool(self.live.get(201))),
                ("分时", bool(records_from(self.live.get(501, {}).get("data", []))) if isinstance(self.live.get(501), dict) else False),
                ("盘前", bool(records_from(self.live.get(504, {}).get("data", []))) if isinstance(self.live.get(504), dict) else False),
                ("成交", bool(self.stock_trades)),
            ) if present
        ]
        if feeds:
            feed_text = "全推 " + " · ".join(feeds)
            if self.stock_status.cget("text") != feed_text or self.stock_status.cget("fg") != GREEN:
                self.stock_status.configure(text=feed_text, fg=GREEN)

    def _render_live(self, dirty_types: set[int] | None = None) -> None:
        # 一个轮询周期内可能收到多条 TCP 推送，合并 dirty 类型后只刷新
        # 被消息影响的区域；不再因 501/504 推送重写成交表。
        if dirty_types is None:
            dirty_types = {2001, 201, 501, 504, 801}
        if 2001 in dirty_types:
            index_rows = self._index_ws_rows(self.live.get(2001, {}))
            if index_rows:
                self.index_table.set_rows(index_rows, columns=[
                    "名称", "代码", "市场", "现价", "涨跌额", "涨跌幅", "上涨", "下跌", "平盘",
                ])
        stock_dirty = dirty_types.intersection({201, 501, 504})
        if not stock_dirty:
            if 801 in dirty_types:
                self._render_stock_trade_table()
                self._update_stock_feed_status()
            return

        hq_body = self.live.get(201, {})
        quote: dict[str, Any] = {}
        if isinstance(hq_body, dict):
            candidate = hq_body.get("hq")
            if isinstance(candidate, dict):
                quote = candidate
            elif hq_body:
                quote = hq_body

        bar_body = self.live.get(501, {})
        bar_rows = records_from(bar_body.get("data", [])) if isinstance(bar_body, dict) else []
        latest_bar = bar_rows[-1] if bar_rows else {}
        feed_key = {}
        for body in (hq_body, bar_body, self.live.get(801, {}), self.live.get(504, {})):
            if isinstance(body, dict) and isinstance(body.get("key"), dict):
                feed_key = body["key"]
                break
        price_unit = as_float(value_ci(feed_key, "unit"), 1) or 1

        def choose(*values: Any) -> Any:
            for value in values:
                if value not in (None, ""):
                    return value
            return None

        def live_price(value: Any, average: bool = False) -> Any:
            if value in (None, ""):
                return None
            number = as_float(value, float("nan"))
            if number != number:
                return value
            divisor = price_unit * (10 if average else 1)
            # 501/801/504 使用整数价格；HTTP 或部分 201 版本可能已经是小数。
            if divisor > 1 and abs(number) >= divisor:
                return number / divisor
            return number

        def feed_time(value: Any, with_seconds: bool) -> str:
            number = as_float(value, float("nan"))
            if number == number and number > 100000000:
                return time.strftime("%H:%M:%S" if with_seconds else "%H:%M", time.localtime(number))
            return str(value)

        def display_rows(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
            displayed: list[dict[str, Any]] = []
            for source in rows:
                row = dict(source)
                if "time" in row:
                    row["time"] = feed_time(row["time"], kind in {"trade", "extended"})
                if kind == "bar":
                    for field in ("open", "high", "low", "close"):
                        if field in row:
                            row[field] = live_price(row[field])
                    if "junj" in row:
                        row["junj"] = live_price(row["junj"], average=True)
                    for field in ("amount", "volume"):
                        if field in row:
                            row[field] = as_float(row[field])
                elif kind == "trade":
                    if "newprice" in row:
                        row["newprice"] = live_price(row["newprice"])
                    if "xianl" in row:
                        row["xianl"] = as_float(row["xianl"])
                    if "tradenum" in row:
                        row["tradenum"] = as_float(row["tradenum"])
                    if "xsfx" in row:
                        row["xsfx"] = {1: "卖", 2: "买"}.get(as_int(row["xsfx"]), str(row["xsfx"]))
                    if "tradetype" in row:
                        row["tradetype"] = "成交" if as_int(row["tradetype"]) == 0 else str(row["tradetype"])
                elif kind == "extended":
                    if "price" in row:
                        row["price"] = live_price(row["price"])
                    for field in ("volume", "unmatchvol", "flag"):
                        if field in row:
                            row[field] = as_float(row[field])
                elif kind == "quote":
                    for field in ("newprice", "newPrice", "LastPrice", "lastPx", "Last_px", "yclose", "YClose", "PreClosePrice", "preclose", "high", "HighPrice", "highPrice", "low", "LowPrice", "lowPrice"):
                        if field in row:
                            row[field] = live_price(row[field])
                    for field in ("amount", "Business_balance", "businessBalance", "volume", "Business_amount", "businessAmount"):
                        if field in row:
                            row[field] = as_float(row[field])
                displayed.append(row)
            return displayed

        price = choose(
            live_price(value_ci(quote, "newprice", "newPrice", "LastPrice", "lastPx", "Last_px")),
            live_price(value_ci(latest_bar, "close", "Close", "LastPrice")),
        )
        yclose = choose(
            live_price(value_ci(quote, "yclose", "YClose", "PreClosePrice", "preclose")),
            live_price(value_ci(latest_bar, "preclose", "PreClose", "yclose", "YClose")),
        )
        if yclose in (None, ""):
            # 501 在部分服务版本返回的是分钟线，没有昨收字段；开盘价是可解释的保底基准。
            yclose = live_price(value_ci(bar_rows[0], "open", "Open", "OpenPrice")) if bar_rows else None
        price_number = as_float(price, float("nan"))
        yclose_number = as_float(yclose, float("nan"))
        has_change = price_number == price_number and yclose_number == yclose_number and yclose_number != 0
        change = price_number / yclose_number - 1 if has_change else 0

        amount = value_ci(quote, "amount", "Business_balance", "businessBalance")
        volume = value_ci(quote, "volume", "Business_amount", "businessAmount")
        if amount in (None, "") and bar_rows:
            amount = sum(as_float(value_ci(row, "amount", "Amount")) for row in bar_rows)
        if volume in (None, "") and bar_rows:
            volume = sum(as_float(value_ci(row, "volume", "Volume")) for row in bar_rows)
        high = live_price(value_ci(quote, "high", "HighPrice", "highPrice"))
        low = live_price(value_ci(quote, "low", "LowPrice", "lowPrice"))
        if high in (None, "") and bar_rows:
            high_values = [as_float(live_price(value_ci(row, "high", "High")), float("nan")) for row in bar_rows]
            high_values = [value for value in high_values if value == value]
            high = max(high_values) if high_values else None
        if low in (None, "") and bar_rows:
            low_values = [as_float(live_price(value_ci(row, "low", "Low")), float("nan")) for row in bar_rows]
            low_values = [value for value in low_values if value == value]
            low = min(low_values) if low_values else None

        price_color = RED if change >= 0 else GREEN
        stock_name = choose(value_ci(feed_key, "name", "prodName"), value_ci(quote, "name", "prodName"))
        market, code = market_code(self.code_var.get())
        if stock_name not in (None, ""):
            target_name = display_name(stock_name, self.privacy_mode)
            if self.stock_name_label.cget("text") != target_name:
                self.stock_name_label.configure(text=target_name)
        target_code_text = f"{market.upper()}{code} · 实时行情 · 分时 · 盘前 · 成交"
        if self.stock_code_label.cget("text") != target_code_text:
            self.stock_code_label.configure(text=target_code_text)
        price_text = fmt_number(price)
        if self.stock_current_label.cget("text") != price_text or self.stock_current_label.cget("fg") != price_color:
            self.stock_current_label.configure(text=price_text, fg=price_color)
        change_text = fmt_percent(change, True) if has_change else "—"
        if self.stock_change_label.cget("text") != change_text or self.stock_change_label.cget("fg") != price_color:
            self.stock_change_label.configure(text=change_text, fg=price_color)
        if yclose_number == yclose_number:
            self.stock_yclose = yclose_number
        open_price = live_price(value_ci(quote, "open", "OpenPrice", "openPrice"))
        if open_price in (None, "") and bar_rows:
            open_price = live_price(value_ci(bar_rows[0], "open", "Open"))
        for k, v in (("开盘", fmt_number(open_price)), ("最高", fmt_number(high)), ("最低", fmt_number(low)), ("成交额", fmt_number(amount))):
            if self.stock_summary_vars[k].get() != v:
                self.stock_summary_vars[k].set(v)

        extended_body = self.live.get(504, {})
        extended_rows = records_from(extended_body.get("data", [])) if isinstance(extended_body, dict) else []
        displayed_premarket = display_rows(extended_rows[:60], "extended")
        premarket_rows: list[dict[str, Any]] = []
        for row in displayed_premarket:
            price_value = as_float(value_ci(row, "price"), float("nan"))
            if price_value != price_value:
                continue
            premarket_rows.append({
                "time": value_ci(row, "time", default="—"),
                "close": price_value,
                "junj": None,
                "volume": as_float(value_ci(row, "volume"), 0),
                "unmatchvol": as_float(value_ci(row, "unmatchvol"), 0),
                "unmatchflag": as_int(value_ci(row, "flag"), 0),
                "session": "premarket",
            })
        self.stock_intraday_premarket_rows = premarket_rows
        displayed_bars = display_rows(bar_rows[-241:], "bar")
        for row in displayed_bars:
            row["session"] = "regular"
        self.stock_intraday_current_rows = displayed_bars
        active_intraday_range = self.stock_intraday_range_var.get().upper()
        if active_intraday_range == "PRE":
            self.stock_intraday_rows = self._combined_stock_intraday_rows()
            premarket_count = len(self.stock_intraday_premarket_rows)
            regular_count = len(self.stock_intraday_current_rows)
            intraday_status_text = f"盘前竞价 + 当日 · {premarket_count} + {regular_count} 点" if self.stock_intraday_rows else "等待盘前与当日分时"
            intraday_status_fg = GREEN if self.stock_intraday_rows else MUTED
            if self.stock_intraday_status.cget("text") != intraday_status_text or self.stock_intraday_status.cget("fg") != intraday_status_fg:
                self.stock_intraday_status.configure(text=intraday_status_text, fg=intraday_status_fg)
            self.stock_intraday_empty_text = "等待盘前竞价 + 当日分时"
            intraday_sig = ("PRE", len(self.stock_intraday_rows), self.stock_intraday_rows[-1].get("close") if self.stock_intraday_rows else None, self.stock_yclose)
            if intraday_sig != getattr(self, "_last_intraday_draw_sig", None):
                self._last_intraday_draw_sig = intraday_sig
                self._draw_stock_intraday()
        elif active_intraday_range == "1D":
            self.stock_intraday_rows = displayed_bars
            if self.stock_intraday_status.cget("text") != "当日分时":
                self.stock_intraday_status.configure(text="当日分时", fg=GREEN)
            intraday_sig = ("1D", len(self.stock_intraday_rows), self.stock_intraday_rows[-1].get("close") if self.stock_intraday_rows else None, self.stock_yclose)
            if intraday_sig != getattr(self, "_last_intraday_draw_sig", None):
                self._last_intraday_draw_sig = intraday_sig
                self._draw_stock_intraday()

        if 801 in dirty_types:
            self._render_stock_trade_table(price_unit)
        self._update_stock_feed_status()

    def _apply_catalog(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        self.catalog = payload
        endpoints = payload.get("endpoints") or (payload.get("market") or {}).get("endpoints") or []
        self.endpoints = [item for item in endpoints if isinstance(item, dict)]
        self.endpoint_by_path = {str(item.get("path", "")): item for item in self.endpoints}
        self._fill_generic_panels()
        self._fill_api_tree()

    def _spec_for_path(self, path_fragment: str) -> dict[str, Any]:
        suffix = "/d6/market/v1/" + path_fragment.lstrip("/")
        return self.endpoint_by_path.get(suffix, {"method": "GET", "path": suffix, "name": path_fragment})

    def _fill_generic_panels(self) -> None:
        for group, view in getattr(self, "generic_views", {}).items():
            specs = [self._spec_for_path(path) for path in view["paths"]]
            view["specs"] = specs
            for index, (panel, spec) in enumerate(zip(view["panels"], specs)):
                panel["spec"] = spec
                panel["table"].title_var.set(public_endpoint_name(spec, index))
                panel["table"].set_context(str(spec.get("path", panel["path"])))
            view["status"].configure(text=f"{len(specs)} 个方法 · 页面内同时展示 · 点击一键全显", fg=MUTED)

    def _fill_api_tree(self) -> None:
        self.api_tree.delete(*self.api_tree.get_children())
        groups: dict[str, str] = {}
        for index, spec in enumerate(self.endpoints):
            category = normalize_display_text(spec.get("category") or "行情数据")
            if "/" in category or "://" in category:
                category = "行情数据"
            parent = groups.get(category)
            if parent is None:
                parent = self.api_tree.insert("", "end", text=category, open=True)
                groups[category] = parent
            self.api_tree.insert(parent, "end", text=public_endpoint_name(spec, index), values=(endpoint_key(spec),))

    def _tab_changed(self, _event: tk.Event) -> None:
        current = self.tabs.tab(self.tabs.select(), "text")
        self.tab_status_var.set(current)
        view = getattr(self, "generic_views", {}).get(current)
        if view and view["specs"] and not view["loaded_once"]:
            view["loaded_once"] = True
            self._generic_query_all(current)

    def _generic_query_all(self, group: str) -> None:
        view = self.generic_views.get(group)
        if not view:
            return
        if not view["specs"]:
            view["status"].configure(text="接口目录尚未加载", fg=GOLD)
            return
        view["pending"] = len(view["specs"])
        view["completed"] = 0
        view["status"].configure(text=f"正在加载 {view['pending']} 个方法…", fg=GOLD)
        for index in range(len(view["specs"])):
            self._generic_query_one(group, index)

    def _generic_query_one(self, group: str, index: int) -> None:
        view = self.generic_views.get(group)
        if not view or index < 0 or index >= len(view["specs"]):
            return
        spec = view["specs"][index]
        params: dict[str, Any] = {}
        spec_path = str(spec.get("path") or "").lower()
        query_names = {str(item.get("name") or "") for item in spec.get("query", [])}
        for item in spec.get("query", []):
            name = str(item.get("name") or "")
            if not name:
                continue
            lowered = name.lower()
            # 目录里的日期默认值可能是生成目录时的旧日期，实际请求始终取最近交易日。
            if lowered in {"date", "tradingday", "trading_day"}:
                params[name] = self.latest_trading_day or time.strftime("%Y-%m-%d")
                continue
            if item.get("default") not in (None, ""):
                default = item.get("default")
                if isinstance(default, str) and default.startswith("("):
                    continue
                params[name] = default
            else:
                market, code = market_code(self.code_var.get())
                if lowered in {"symbol", "code", "stockcode", "secu_code", "instrucode", "instrumentid"}:
                    params[name] = code
                elif lowered in {"market", "oldmarketcode", "marketcode"}:
                    # 融资融券接口的 market 不是证券代码市场筛选：空值代表全量，
                    # 误传 SZ 会让“个股融资融券明细”返回 data=null。
                    if "/margin/" not in spec_path:
                        params[name] = market
                elif lowered in {"date", "tradingday", "trading_day"}:
                    params[name] = self.latest_trading_day or time.strftime("%Y-%m-%d")
        # 只给目录声明过分页参数的接口补分页值；向所有接口盲发 pageNo/pageSize
        # 会让无分页接口返回空数据或纯文本错误。
        if "pageSize" in query_names:
            params.setdefault("pageSize", 30)
        if "pageNo" in query_names:
            params.setdefault("pageNo", 1)
        body = None
        if spec.get("body", {}).get("example") is not None:
            body = spec["body"]["example"]
        self.http.request(f"generic:{group}:{index}", spec.get("method", "GET"), self._api_url(spec.get("path", "")), params=params, body=body)

    def _api_selected(self, _event: tk.Event) -> None:
        selection = self.api_tree.selection()
        if not selection:
            return
        values = self.api_tree.item(selection[0], "values")
        if not values:
            return
        key = values[0]
        self.api_selected_spec = next((spec for spec in self.endpoints if endpoint_key(spec) == key), None)
        if not self.api_selected_spec:
            return
        spec = self.api_selected_spec
        endpoint_index = next((index for index, item in enumerate(self.endpoints) if item is spec), 0)
        self.api_title.configure(text=f"HTTP · {public_endpoint_name(spec, endpoint_index)}")
        query: dict[str, Any] = {}
        for item in spec.get("query", []):
            name = item.get("name")
            if not name:
                continue
            if str(name).lower() in {"date", "tradingday", "trading_day"}:
                query[name] = self.latest_trading_day or time.strftime("%Y-%m-%d")
            else:
                query[name] = item.get("default", "")
        self.api_query.configure(state="normal")
        self.api_query.delete(0, "end")
        self.api_query.insert(0, f"已准备 {len(query)} 项业务参数")
        self.api_query.configure(state="readonly")
        self.api_query_payload = query
        body = spec.get("body", {}).get("example", {}) if isinstance(spec.get("body"), dict) else {}
        self.api_body_payload = body
        self._set_text(self.api_body, "请求内容已按本地业务目录准备。\n点击发送请求即可执行。")
        self._set_text(self.api_response, "本地业务数据方法\n\n参数已按当前目录填充，可直接发送请求。")

    def api_send(self) -> None:
        spec = self.api_selected_spec
        if not spec:
            self._set_text(self.api_response, "请先从左侧选择一个接口")
            return
        query = self.api_query_payload
        body = self.api_body_payload
        self._set_text(self.api_response, "请求中…")
        self.http.request("api", spec.get("method", "GET"), self._api_url(spec.get("path", "")), params=query, body=body if spec.get("method") == "POST" else None)

    def _select_kline_period(self, period: str) -> None:
        period = period.upper()
        self.kline_period.set(period)
        for key, button in self.kline_period_buttons.items():
            active = key == period
            button.configure(bg="#244e76" if active else INPUT, fg=WHITE if active else TEXT)
        self.load_kline()

    def load_kline(self) -> None:
        market, code = market_code(self.kline_code_var.get())
        period = self.kline_period.get().upper()
        self.kline_period.set(period)
        for key, button in getattr(self, "kline_period_buttons", {}).items():
            active = key == period
            button.configure(bg="#244e76" if active else INPUT, fg=WHITE if active else TEXT)
        body = {"Market": market.upper(), "Inst": code, "Period": period, "ReqID": 1, "servicetype": "KLINE", "StartID": 0, "EndID": -1}
        self._set_text(self.kline_raw, "正在加载 K 线数据…")
        self.http.request("kline", "POST", self._api_url("/kline"), body=body)

    def _apply_kline(self, payload: Any) -> None:
        rows = []
        if isinstance(payload, dict):
            quote = payload.get("QuoteData") or payload.get("quoteData") or {}
            rows = quote.get("KlineData") or quote.get("klineData") or [] if isinstance(quote, dict) else []
        normalized = normalize_records(rows)
        self.kline_table.set_rows(normalized)
        self.live["kline_rows"] = rows
        self._set_text(self.kline_raw, public_payload_summary(normalized))
        self._draw_kline()

    def _draw_kline(self) -> None:
        canvas = getattr(self, "kline_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(200, canvas.winfo_width())
        height = max(150, canvas.winfo_height())
        self._draw_watermark(canvas, width, height)
        rows = self.live.get("kline_rows") or []
        if not rows:
            canvas.create_text(width / 2, height / 2, text="加载 K 线后显示走势", fill=DIM, font=FONT_CN)
            return
        closes: list[float] = []
        for row in rows:
            if isinstance(row, dict):
                closes.append(as_float(value_ci(row, "Close", "close", "ClosePrice", "closePrice", "LastPrice"), 0))
            elif isinstance(row, list) and row:
                closes.append(as_float(row[-1], 0))
        closes = [value for value in closes if value]
        if len(closes) < 2:
            canvas.create_text(width / 2, height / 2, text="K 线字段暂不足以绘图", fill=DIM, font=FONT_CN)
            return
        lo, hi = min(closes), max(closes)
        span = hi - lo or 1
        left, right, top, bottom = 42, width - 18, 18, height - 30
        points = []
        step = (right - left) / max(1, len(closes) - 1)
        for index, value in enumerate(closes):
            x = left + index * step
            y = bottom - (value - lo) / span * (bottom - top)
            points.extend((x, y))
        canvas.create_line(*points, fill=CYAN, width=2, smooth=True)
        canvas.create_text(left - 6, top, text=fmt_number(hi), fill=MUTED, anchor="e", font=FONT_TINY)
        canvas.create_text(left - 6, bottom, text=fmt_number(lo), fill=MUTED, anchor="e", font=FONT_TINY)
        canvas.create_text(right, bottom + 8, text=str(len(closes)) + " 根", fill=DIM, anchor="e", font=FONT_TINY)

    @staticmethod
    def _set_text(widget: tk.Text | None, text: str) -> None:
        if widget is None:
            return
        was_disabled = str(widget.cget("state")) == "disabled"
        if was_disabled:
            widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if was_disabled:
            widget.configure(state="disabled")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.refresh_after is not None:
            try:
                self.root.after_cancel(self.refresh_after)
            except tk.TclError:
                pass
        self.ws.stop()
        self.http.close()
        self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="d6 Tkinter 市场行情大屏")
    parser.add_argument("--http", default=HTTP_BASE, help=f"HTTP 基础地址，默认 {HTTP_BASE}")
    parser.add_argument("--ws", default=WS_URL, help=f"WebSocket 地址，默认 {WS_URL}")
    parser.add_argument("--code", default=DEFAULT_CODE, help=f"默认股票代码，默认 {DEFAULT_CODE}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = tk.Tk()
    D6Gui(root, args.http, args.ws, args.code)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
