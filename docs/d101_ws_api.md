# D101 本地 d101 实时行情 WebSocket 接口

## 1. 文档定位

本文是 D101 的用户侧开发文档，目标是让没有接触过本项目的新手，仅凭本文就能完成一个可用的行情客户端。

本文只描述本机 `data_interface` 提供给调用方的接口契约：

- 本地 WebSocket 地址；
- 订阅命令和退订命令；
- 服务端返回的 JSON 结构；
- 字段名称、数据类型和常用换算；
- Python、JavaScript 客户端示例；
- 断线、缺字段、空值和异常处理方法；
- 本地联调和验收清单。

本文不会描述，也不要求调用方了解：

- 任何外部数据服务的名称、域名、IP、端口或网络拓扑；
- 账号、密码、签名、内部认证信息或配置内容；
- 本地代理与数据服务之间的内部二进制包、压缩细节和连接参数；
- 任何不能作为用户侧 API 契约使用的内部实现细节。

客户端只应该连接本机 D101 WebSocket，不应该绕过本地程序连接其他地址。

---

## 2. D101 是什么

D101 是本地代理提供的 d101 实时行情 WebSocket 接口。

它的工作关系如下：

```text
你的 Python / JavaScript / C++ 程序
              │
              │ WebSocket + JSON
              ▼
ws://127.0.0.1:8080/d101
              │
              │ 本地代理内部处理
              ▼
        实时行情数据
```

调用方只需要处理 WebSocket 文本帧和 JSON，不需要处理底层 传输、压缩或二进制协议。

D101 当前包含两类命令：

| `type` | 用途 | 推荐程度 |
|---|---|---|
| `snapshot` | 多只资产的实时快照和后续变化推送 | 稳定、推荐使用 |
| `market_event` | 盘口异动事件；支持当前数据和按游标查询当日历史 | 按本文说明使用 |

K 线不属于 D101。需要 K 线时使用 D4 HTTP 接口：`GET /d4/l1/kline`。

`market_event` 已由当前 D101 服务端开放。它不需要 `codes` 股票数组：返回的是服务端发现的异动事件，客户端通过返回行中的 `code` 判断涉及的股票。

---

## 3. 开始前的准备

### 3.1 启动本地程序

先启动：

```text
data_interface.exe
```

默认本地代理端口为 `8080`。如果你的部署修改了本地端口，应以实际部署端口替换本文示例中的 `8080`。

### 3.2 检查 D101 是否可用

用浏览器或命令行访问：

```text
GET http://127.0.0.1:8080/d101/info
```

成功示例：

```json
{
  "status": "ready",
  "format": "json",
  "max_stocks": 6000,
  "max_fields": 255,
  "max_request_stocks": 65535
}
```

字段含义：

| 字段 | 含义 |
|---|---|
| `status` | D101 服务状态；`ready` 表示可以建立 WebSocket 订阅 |
| `format` | WebSocket 推送的公共数据格式；当前为 JSON |
| `max_stocks` | 单条底层行情连接的代码容量；超过时服务端在同一条客户端命令内部按代码分批 |
| `max_fields` | 单个 `snapshot` 订阅命令最多请求的字段数量；公共上限为 255，当前完整字段目录为 203 个 |
| `max_request_stocks` | 一条客户端 `snapshot` 命令允许携带/展开的代码总数上限；当前为 65535 |

如果返回 HTTP `403`，说明当前登录账号没有 D101 使用权限。如果连接失败，通常是程序未启动、端口不对或本机防火墙拦截。

### 3.3 安装 Python 依赖

Python 示例使用 `websocket-client`：

```powershell
python -m pip install websocket-client
```

验证安装：

```powershell
python -c "import websocket; print(websocket.__version__)"
```

### 3.4 运行图形测试器

随附的 Tkinter 测试器可以直接验证 D101 的快照和盘口异动：

```powershell
python .\d101_gui.py --url ws://127.0.0.1:8080/d101
```

启动后，快照 TAB 默认处于“市场池”模式，会订阅下拉框选中的全市场。要测试单个或混合品种，请点击“自定义代码”，在代码输入框中使用逗号、分号或空格分隔代码，再点击“连接”。输入框会自动补齐常见格式，例如 `90007351`、`jmm` 和 `MO2609-P-7000`；美股代码需要显式写交易所前缀，例如 `NASDAQ|GSUN`。

字段选择在“请求字段”一栏中完成。GUI 默认使用“省带宽·基础行情（推荐）”，请求身份、精度、低频参考基线、品种单位元数据，以及最新价、最高/最低价、均价、成交量等必要原始值；默认不请求成交额、现手、现手方向和盘口这些可本地推导或高频变化字段。“常用行情·统计字段”会增加常用统计值；“自定义字段”可以逐项勾选；“全部 203 字段（单命令）”只建议用于协议核对或抓取原始样本。全部字段会在一条 `snapshot` 命令中发送；代码超过单条底层连接的 6000 只容量时，由服务端在命令内部按代码分批，客户端仍只保持一条 WebSocket 连接。

行情表的列头使用字段目录中的中文语义名称；字段设置窗口显示中文含义和正式 JSON 字段名，用户或 AI agent 不需要接触内部实现细节。
字段筛选支持中文含义、JSON 字段名、大小写差异、全半角差异以及带空格的输入；筛选后会自动回到结果列表顶部。

不要为了显示涨跌幅、涨跌额、振幅、实体涨幅、开盘/昨收比、5/20 日及月年涨幅、现价均价差和成交额就额外请求它们：当行中已有对应价格基线、均价和成交量时，GUI 会在本地计算这些确定性指标。成交额计算前会按 `decimal_num` 还原均价，并按品种成交单位换算；指数或未知单位不伪造金额，必须精确核对时再请求 `amount`。面向 AI agent 的客户端也应先选择任务需要的最小字段集合，再逐步增加字段；字段数量越多、资产数量越大、变化越频繁，WebSocket 流量和解析压力越大。

---

## 4. 最小可运行示例

下面的程序会：

1. 连接 D101；
2. 订阅两只股票；
3. 读取欢迎消息、连接消息和行情消息；
4. 打印每一行行情；
5. 收到 `Ctrl+C` 后退订并关闭连接。

保存为 `d101_quick_start.py`：

```python
import json
import sys
import websocket


URL = "ws://127.0.0.1:8080/d101"


def main() -> None:
    ws = websocket.create_connection(URL, timeout=15)
    try:
        command = {
            "type": "snapshot",
            "seq": 1,
            "enable": 1,
            "codes": ["SZ000001", "SH600000"],
            # 包含 code 非常重要，客户端才能用 code 作为缓存键。
            "fields": [
                # 先请求低频基线和必要动态值；派生指标、成交额可在本地计算。
                "code", "name", "decimal_num", "display_decimal_num",
                "price", "pre_close", "high", "low", "open_price", "avg_price", "volume",
                "last_month_price", "last_year_price", "prev_19_price", "prev_249_price", "prev4_price",
                "limit_up_price", "limit_down_price", "volume_unit_flag", "stock_type",
                "contract_type", "trade_date", "market", "net_inflow",
            ],
        }
        ws.send(json.dumps(command, ensure_ascii=False))

        while True:
            message = json.loads(ws.recv())
            for item in message.get("list", []):
                item_type = item.get("type")

                if item_type == "info":
                    print("INFO:", item)
                    continue

                if item_type == "error":
                    print("ERROR:", item, file=sys.stderr)
                    continue

                if item_type != "snapshot":
                    print("OTHER:", item)
                    continue

                for row in item.get("data", []):
                    print(
                        row.get("code"),
                        row.get("name"),
                        "raw_price=", row.get("price"),
                        "raw_volume=", row.get("volume"),
                        "raw_amount=", row.get("amount"),
                    )
    except KeyboardInterrupt:
        # 退订不是关闭连接的必要条件，但可以让服务端尽快清理订阅。
        try:
            ws.send(json.dumps({"type": "snapshot", "enable": 0}))
        except Exception:
            pass
    finally:
        ws.close()


if __name__ == "__main__":
    main()
```

运行：

```powershell
python .\d101_quick_start.py
```

注意：`recv()` 收到的是一条 WebSocket 消息，不一定只包含一条行情，也不一定包含行情。必须遍历 `message["list"]`。

---

## 5. WebSocket 连接和消息外壳

### 5.1 连接地址

```text
ws://127.0.0.1:8080/d101
```

D101 使用 WebSocket 文本帧。所有命令都发送 JSON 文本，所有正常返回也都是 JSON 文本。

### 5.2 连接成功后的第一条消息

当前实现通常先发送：

```json
{
  "ts": 1786000000000,
  "list": [
    {
      "type": "info",
      "msg": "d101 WebSocket已连接"
    }
  ]
}
```

客户端不要依赖中文 `msg` 文本做业务判断。判断连接状态时，可以识别 `type == "info"`，并把其他字段当作诊断信息保存或显示。

### 5.3 通用消息结构

所有消息都使用下面的外壳：

```json
{
  "ts": 1786000000000,
  "list": [
    {
      "type": "snapshot",
      "data": []
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts` | integer | 本地代理生成的 Unix 毫秒时间戳；表示代理发出消息的时间，不一定是每只股票的成交时间 |
| `list` | array | 消息项目数组；一次 WebSocket 接收可能包含多个项目 |
| `list[].type` | string | 项目类型，常见为 `info`、`error`、`snapshot`、`market_event` |
| `list[].data` | array | 行情数据项目；`info`、`error` 通常没有此字段 |

正确的分发代码应该类似：

```python
for item in message.get("list", []):
    if item.get("type") == "snapshot":
        handle_snapshot(item.get("data", []))
    elif item.get("type") == "market_event":
        handle_market_event(item.get("data", []))
    elif item.get("type") == "info":
        handle_info(item)
    elif item.get("type") == "error":
        handle_error(item)
```

不要把一条 WebSocket 消息直接当成一行数据，也不要假设 `list` 永远只有一个元素。

### 5.4 `info` 项目

订阅成功后常见的连接提示：

```json
{
  "type": "info",
  "id": "snapshot_1",
  "msg": "connected"
}
```

`id` 是本地代理为本次订阅生成的连接标识。它由 `type` 和 `seq` 组成，例如 `snapshot_1`、`market_event_2`。

### 5.5 `error` 项目

错误消息示例：

```json
{
  "type": "error",
  "msg": "codes required and must be array"
}
```

错误项目只表示这一条命令没有建立成功，不一定表示 WebSocket 必须关闭。客户端应记录错误并继续处理后续项目。

---

## 6. 命令格式

### 6.1 单条命令或命令数组

服务端同时接受单个对象和数组。

单条命令：

```json
{
  "type": "snapshot",
  "codes": ["SZ000001"],
  "enable": 1
}
```

推荐使用数组，便于一次发送多条命令：

```json
[
  {
    "type": "snapshot",
    "seq": 1,
    "codes": ["SZ000001", "SH600000"],
    "fields": [
      "code", "name", "decimal_num", "display_decimal_num", "price", "pre_close",
      "avg_price", "volume", "volume_unit_flag"
    ]
  },
  {
    "type": "market_event",
    "seq": 2,
    "mode": 1,
    "count": 100
  }
]
```

### 6.2 通用命令字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---:|---|
| `type` | string | 是 | 无 | `snapshot` 或 `market_event` |
| `enable` | integer | 否 | `1` | `1` 表示订阅；`0` 表示退订 |
| `seq` | integer | 否 | 自动递增 | 本地订阅序号，建议使用 `1~65535` 且同一 WebSocket 内不重复 |

当前 D101 只定义 `enable=1` 和 `enable=0`。`market_event` 的“持续/单次”含义由 `mode` 表示，不要把 `enable=2` 当成单次查询。

### 6.3 `snapshot` 订阅命令

最小命令：

```json
{
  "type": "snapshot",
  "codes": ["SZ000001", "SH600519", "SO10011007"]
}
```

完整多资产订阅命令（用于原始字段对照，不是生产默认集合）：

```json
{
  "type": "snapshot",
  "seq": 10,
  "enable": 1,
  "codes": [
    "SZ000001",
    "SH600519",
    "SO10011007",
    "ZO90007323",
    "HKDL|00700",
    "NASDAQ|AAPL",
    "SHFE|brm",
    "DCE|jmm",
    "SF040131",
    "CFFEXOPTION|MO2609-P-7000"
  ],
  "fields": [
    "code", "name", "decimal_num", "price", "high", "low", "pre_close", "open_price", "avg_price",
    "volume", "amount", "change_pct", "change_amt", "turnover_ratio", "real_turnover_ratio",
    "market_value", "float_market_value", "amplitude", "volume_ratio",
    "bid1_price", "bid2_price", "bid3_price", "bid4_price", "bid5_price",
    "ask1_price", "ask2_price", "ask3_price", "ask4_price", "ask5_price",
    "bid1_vol", "ask1_vol",
    "inner_vol", "outer_vol",
    "limit_up_price", "limit_down_price",
    "change_pct_5d", "change_pct_10d",
    "dynamic_pe", "ttm_pe", "pb_ratio", "dividend_yield"
  ]
}
```

上面的多资产示例为了对照服务端原始值，特意包含了 `amount`、涨跌类、统计类和多档盘口；常驻监控应改用下方的最小字段方案，或直接使用 GUI 的“省带宽·基础行情”。

#### 字段怎么选：先少请求，再按需增加

`fields` 是“服务端需要返回的原始字段”列表，不是越长越好。服务端按字段变化推送增量：低频字段主要增加首帧和偶尔的元数据更新，高频字段会随着行情频繁进入消息。因此应把低频基线和必要动态字段放入默认集合，把现手、盘口和统计字段按业务需要增加。建议按下面的层次选择：

| 场景 | 建议字段 | 说明 |
|---|---|---|
| 只看最新价 | `code,name,decimal_num,display_decimal_num,price,pre_close` | 最小价格集合；涨跌额和涨跌幅可本地计算 |
| 价格与累计成交 | 在上面增加 `high,low,open_price,avg_price,volume,volume_unit_flag,float_share` | 振幅、成交额和换手率可本地计算；金额需按品种单位换算 |
| GUI 默认模式 | 身份、精度、日内/历史参考价、股本/单位元数据、最新价/高低价/今开/均价/成交量 | 当前默认 28 个原始字段；不含 `amount`、现手、盘口 |
| 需要现手方向 | 增加 `tick_vol,buy_sell_flag` | 现手数量和方向是高频字段；方向原始枚举仍应保留 |
| 做一级盘口 | 增加 `bid1_price,bid1_vol,ask1_price,ask1_vol` | 只请求买一、卖一，不要为了看一级盘口请求买二至买五 |
| 需要某个统计值 | 只增加该字段 | 例如确实需要量比时再增加 `volume_ratio` |
| 协议核对/原始采样 | 全部 203 个正式字段 | GUI 一条命令请求；不建议作为常驻生产订阅 |

以下字段可以在客户端由基础值计算，GUI 默认不请求其服务端原始值：

```text
change_pct             = (price - pre_close) / pre_close × 10000
change_amt             = price - pre_close
amplitude              = (high - low) / pre_close × 10000
body_change_pct        = (price - open_price) / open_price × 10000
open_pre_ratio         = open_price / pre_close × 10000
price_avg_diff         = price - avg_price
this_month_pct         = (price - last_month_price) / last_month_price × 10000
this_year_pct          = (price - last_year_price) / last_year_price × 10000
change_pct_20d         = (price - prev_19_price) / prev_19_price × 10000
change_pct_recent_year = (price - prev_249_price) / prev_249_price × 10000
change_pct_5d          = (price - prev4_price) / prev4_price × 10000
amount                 ≈ volume × (avg_price / 10**decimal_num) × 品种成交单位换算因子
turnover_ratio         ≈ volume / float_share × 成交量单位换算因子
real_turnover_ratio    ≈ volume / free_float_market_share × 成交量单位换算因子
inner_outer_ratio      ≈ inner_vol / outer_vol × 100
order_buy_sell_diff    = order_buy_volume - order_sell_volume
```

计算时要先按 `decimal_num` 把价格转换到同一显示单位；百分比公式乘以 `10000` 才是 D101 原始值，界面显示时再按字段规则除以 `100`。成交额和换手率的换算首先读取 `volume_unit_flag`：`0` 按股/份乘 1，`1` 按手乘 100；特殊合约再按合约乘数处理。GUI 当前支持 A股/ETF、中金所期权、`DCE|jmm` 和美股等已确认样本；指数或未知单位不自行生成金额。由于均价有精度限制，本地成交额是估算值；若必须核对服务端原始计算结果，可以在“自定义字段”中勾选 `amount`，或直接选择全部字段。

`prev_19_price`（前 19 日参考价）正是 `change_pct_20d` 的基准；同理，`prev4_price`、`last_month_price`、`last_year_price`、`prev_249_price` 分别作为 5 日、本月、本年和近一年涨幅的基准。换手率只有在股本字段和资产成交单位有效时才计算；上面只列出当前已验证的计算，不能据此推测 3/10/60 日的其他统计或资金指标口径。

在 GUI 的“自定义字段”中直接勾选本地派生字段时，面板会自动补入该字段所需的原始依赖；默认方案不会因为可选的内外盘或委托统计而请求这些高频依赖。

单条 `snapshot` 命令最多 255 个字段，当前目录的完整 203 个字段可以一次请求。代码数量以 6000 只为单条底层行情连接的容量参考；超过时服务端在同一条命令内部按代码分批，客户端不需要拆字段、发送多条订阅命令或为字段批次新建连接。例如：

```python
all_fields = load_d101_field_names()  # 完整字段目录中的 203 个正式名称
command = {
    "type": "snapshot",
    "seq": 1,
    "enable": 1,
    "codes": ["SZ000001", "IS932000"],
    "fields": all_fields,
}
ws.send(json.dumps(command, ensure_ascii=False))
```

`code` 是客户端合并增量的身份字段，必须保留。服务端只在需要时按代码容量创建底层连接并把结果汇总到当前 WebSocket；普通客户端不应把底层代码批次当成多份行情，也不需要为字段或代码批次自行新建连接。

也可以让服务端生成品种池，不必由客户端先下载代码列表：

```json
{
  "type": "snapshot",
  "universe": "cn_hsj_stock",
  "fields": [
    "code", "name", "decimal_num", "display_decimal_num", "price", "pre_close",
    "avg_price", "volume", "volume_unit_flag"
  ]
}
```

当前支持的业务品种池：

| `universe` | 内容 | 当前联调参考数量 |
|---|---|---:|
| `cn_hs_stock` | 沪深 A股，不含北交所 | 5218 |
| `cn_hsj_stock` | 沪深京 A股，包含北交所 | 5559 |
| `cn_sh_stock` | 上海 A股 | 2317 |
| `cn_sz_stock` | 深圳 A股 | 2901 |
| `cn_bse_stock` | 北交所股票 | 341 |
| `cn_star_stock` | 科创板股票 | 616 |
| `cn_sh_b_stock` | 上海 B 股 | 41 |
| `cn_sz_b_stock` | 深圳 B 股 | 38 |
| `cn_index` | 沪深京指数 | 43 |
| `cn_fund` | 沪深基金集合，包含 ETF、LOF、普通基金和 REIT | 2461 |
| `cn_sh_fund` | 上海基金 | 1344 |
| `cn_sz_fund` | 深圳基金 | 1117 |
| `cn_reit` | REIT | 93 |
| `cn_sh_bond` | 上海债券 | 22822 |
| `cn_sz_bond` | 深圳债券 | 19689 |
| `cn_option` | 沪深期权合并集合，包含 `SO` 和 `ZO` | 1110 |
| `cn_etf_option` | ETF 期权子集（当前列表为 `SO`） | 666 |
| `cn_option_call` | 期权认购子集（当前列表为 `SO`） | 333 |
| `cn_option_put` | 期权认沽子集（当前列表为 `SO`） | 333 |
| `cn_cffex_index_futures` | 中金所股指期货当前合约 | 动态 |
| `cn_cffex_treasury_futures` | 中金所国债期货当前合约 | 动态 |
| `cn_cffex_futures` | 中金所期货当前合约合并集合 | 动态 |

`cn_index` 返回的是带市场命名空间的规范代码。中证 2000 在实时列表和 D101 全推
中的代码是 `IS932000`（名称为“中证2000”）；`SH932000`、`SZ932000` 和裸
`932000` 不作为该列表的规范代码。

表中数量只是当前联调参考，会随上市、退市和列表状态变化；客户端应以实际收到的 `code` 为准，不要把表中数量写死。首次联调可加 `"limit": 10`，正式推送省略 `limit` 或使用 `0`。`cn_fund` 不是 ETF 专属集合，当前没有单独公开的 ETF 基金池名称。

字段说明：

`fields` 只使用返回 JSON 的正式语义字段名。字段名区分大小写，推荐直接复制本文字段表中的 `JSON 键`；服务端负责把语义字段名映射到内部数据通道。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `codes` | string[] | 与 `universe` 二选一 | 资产代码数组；适合自定义股票池或混合品种 |
| `universe` | string | 与 `codes` 二选一 | 服务端生成的业务品种池；使用上表中的名称 |
| `limit` | integer | 否 | 使用 `universe` 时的数量上限；`0` 表示全部，联调可设为 `10` |
| `fields` | string[] | 否 | 字段名称数组；省略时使用默认字段 |
| `seq` | integer | 否 | 用于区分同一 WebSocket 上的多个 `snapshot` 订阅 |

#### 支持的资产代码格式（多品种支持）

D101 自选股通道原生支持全品种金融资产订阅，代码格式规则如下：

| 产品类别 | 代码格式规则 | 示例代码 | 标的说明 |
|:---|:---|:---|:---|
| **A股股票** | 市场标识 (2位) + 6位代码 | `SH600519`, `SZ300750` | 贵州茅台、宁德时代 |
| **大盘指数** | 市场标识 (2位) + 6位代码 | `SH000001`, `SZ399001` | 上证指数、深证成指 |
| **ETF / 基金 / 债券** | 市场标识 (2位) + 6位代码 | `SZ159915`, `SZ128036` | 创业板ETF、可转债 |
| **上海 ETF / 股票期权** | `SO` + 8位期权合约 ID | `SO10011007`, `SO10012277` | 500ETF购9月7613A 等 |
| **深圳 ETF / 股票期权** | `ZO` + 8位期权合约 ID | `ZO90007323`, `ZO90007351` | 创业板 ETF 期权等 |
| **港股 / 港股通** | `HKDL\|` + 5位代码 | `HKDL\|00700`, `HKDL\|09988` | 腾讯控股、阿里巴巴 |
| **美股** | 交易所名称 + `\|` + 股票Symbol | `NASDAQ\|AAPL`, `NYSE\|BABA` | 苹果、阿里巴巴 |
| **国内商品期货** | 交易所代码 + `\|` + 品种合约 | `SHFE\|brm`, `DCE\|i2409` | 丁二烯橡胶主力、铁矿主力 |
| **中金所股指期货** | `SF` + 6位代码 | `SF040131`, `SF040001` | IF当月连续、IF连续 |
| **中金所期权** | `CFFEXOPTION\|` + 合约字符串 | `CFFEXOPTION\|MO2609-P-7000` | MO 期权 |

图形测试器还提供以下便捷输入转换；直接调用 WebSocket 的程序建议发送右侧的规范代码：

| 输入框可输入 | 实际发送的规范代码 | 说明 |
|---|---|---|
| `90007351` | `ZO90007351` | 9 开头的八位期权 ID 按深圳期权处理 |
| `10010971` | `SO10010971` | 其余常见八位期权 ID 按上海期权处理 |
| `jmm` | `DCE\|jmm` | 裸小写 1~3 位品种名按国内商品期货连续合约处理 |
| `MO2609-P-7000` | `CFFEXOPTION\|MO2609-P-7000` | 中金所期权合约 |
| `GSUN` | `GSUN` | 裸美股代码有市场歧义，不能自动猜测；请写 `NASDAQ\|GSUN` |

代码 ID 与名称来自实时品种列表，可能随换月、挂牌和合约状态变化。不要把名称与代码硬编码绑定；例如要找某个当前执行价的期权，应以当前返回的 `code`、`name` 配对为准。

约束：

- `codes` 和 `universe` 必须二选一，不能同时填写；
- `codes` 不能为空；`universe` 必须使用本文列出的业务名称；
- 单个 `snapshot` 订阅使用一条客户端 WebSocket 和一条订阅命令；代码数量不超过 `6000` 只时对应一条底层行情连接；
- 超过 `6000` 只时，服务端在当前命令内部按代码分批，不要求客户端拆分字段或新建连接；
- 单条命令的 `fields` 最多 `255` 个字段，当前完整字段目录的 203 个字段可以一次请求；
- 字段名必须使用返回 JSON 中的键名，例如 `code`、`price`、`volume`；
- 建议字段名不重复；
- 自定义字段列表中必须包含 `code`，这样客户端才能正确关联资产；
- 如果字段列表中包含未确认的字段，可能出现缺行、空值或字段无法解释；生产程序只使用本文列出的字段。

容量说明：当前服务端按每条底层行情连接 6000 只控制代码容量；单条客户端 `snapshot` 命令最多展开 65535 只代码，超过 6000 时由服务端内部按代码分批。字段越多，消息越大；生产环境建议使用 GUI 的省带宽方案或经过筛选的字段组合。无论是否发生代码分批，客户端都只保持一条 WebSocket、发送一条订阅命令，并按 `code` 合并增量行情；不应为了字段批次增加连接数。

### 6.4 服务端默认字段列表

省略 `fields` 时，当前服务端使用以下 35 个字段名（名称按当前目录）。自定义请求必须使用字段目录中的规范名；历史别名仅作临时迁移兼容，后续版本可能取消支持：

```text
code, name, industry_name, pre_close, total_share, float_share,
prev_day_change_pct, prev_day_volume, high_60d, auction_unmatched_volume,
limit_up_price, limit_down_price, avg_price, open_price, first_limit_time,
last_limit_time, limit_up_days_legacy, limit_up_open_count,
yearly_limit_up_days, price, high, low, volume, tick_vol, bid1_price,
bid1_vol, ask1_price, ask1_vol, net_inflow, volume_ratio,
increase_rate_2min, increase_rate_3min, increase_rate_5min,
change_pct_5d, turnover_ratio_6d
```

默认字段中包含一些无数据时会返回哨兵值的字段，例如涨停相关时间、涨停打开次数等。客户端必须按照“无效值处理”章节处理它们，不能把哨兵值直接当作真实业务数据。

注意：GUI 不依赖服务端默认值，而是默认明确发送“省带宽·基础行情”字段。默认集合以低频基线和必要动态值为主，省略可本地计算的成交额/涨跌类字段以及现手、盘口等高频字段。GUI 的“常用行情·统计字段”“自定义字段”和“全部 203 字段（单命令）”均会在连接前显示预计请求字段数。

### 6.5 退订命令

退订全部 `snapshot` 订阅：

```json
{
  "type": "snapshot",
  "enable": 0
}
```

退订成功后通常收到：

```json
{
  "ts": 1786000000000,
  "list": [
    {
      "type": "info",
      "msg": "unsubscribed snapshot"
    }
  ]
}
```

当前退订按 `type` 批量处理，不支持只退订某一个股票而保留同类型的其他股票。若需要完全隔离不同订阅，使用多个 WebSocket 连接。

### 6.6 `market_event` 盘口异动命令

`market_event` 返回的是异动事件行，不是按股票代码订阅的快照。因此请求中不需要也不应该依赖 `codes`；服务端返回哪只股票发生事件，由返回行的 `code` 字段决定。

#### 6.6.1 获取当前页并持续接收

第一页使用 `mode=1`，不传游标：

```json
{
  "type": "market_event",
  "seq": 1,
  "mode": 1,
  "count": 100,
  "enable": 1
}
```

含义：

| 字段 | 类型 | 说明 |
|---|---|---|
| `mode` | integer | `1` 表示当前/持续模式；省略时默认为 `1` |
| `count` | integer | 请求数量；`mode=1` 时使用正数，默认 `100` |
| `seq` | integer | 本地请求序号；同一 WebSocket 内不要重复 |
| `enable` | integer | `1` 建立请求；`0` 退订全部 `market_event` 请求 |

异动类型由 D101 内部转译为中性名称和方向，用户不需要也不能传递底层类型编号；服务端使用当前版本的完整异动目录。

第一页在客户端内部可以把游标初始化为 `time=0、seq=0`，但不要把这个空游标作为 `mode=2` 的历史查询发送。实际可用的第一页请求就是上面的 `mode=1`、不传 `cursor`。

#### 6.6.2 根据游标查询上一页历史

收到第一页后，取 `data` 数组最后一行的 `time` 和 `seq`，两个值必须成对保存。下一页示例：

```json
{
  "type": "market_event",
  "seq": 2,
  "mode": 2,
  "count": -20,
  "cursor": {
    "time": 145452,
    "seq": 15442
  },
  "enable": 1
}
```

字段规则：

- `mode=2` 表示单次历史页请求；
- `cursor.time` 是 `HHMMSS` 整数，例如 `145452` 表示 `14:54:52`，不是 Unix 时间戳；
- `cursor.seq` 是与该时间对应的事件序号；不能只传时间或只传序号；
- `count` 在协议层表示向前查询的数量，因此推荐发送负数，例如 `-20`、`-100`；D101 也兼容发送正数并自动转换为负数；
- 下一页必须使用上一页实际返回的最后一行游标，不能自行把时间或序号改成近似值；
- 每个历史页使用不同的顶层 `seq`，而 `cursor.seq` 是数据游标，两者用途不同。

如果上一页最后一行是：

```json
{"time": 145452, "seq": 15442, "code": "SZ300689", "type_name": "火箭发射", "info": "..."}
```

下一页就应使用 `"cursor": {"time": 145452, "seq": 15442}`。收到空数组时，表示当前游标之前没有更多可返回记录，客户端应停止翻页，不要高频重试。

#### 6.6.3 `market_event` 返回字段

服务端已经把底层异动类型转译为可直接展示的 `type_name` 和 `type_color`，不向用户暴露底层类型编号。`info` 仍保持原样，不拆成新的业务字段：

| 字段 | 类型 | 含义 | 使用方式 |
|---|---|---|---|
| `code` | string | 发生异动的股票代码 | 作为股票关联键 |
| `time` | integer | 事件发生时间，格式为 `HHMMSS` | 与 `seq` 组成游标 |
| `seq` | integer | 事件序号 | 与 `time` 组成游标 |
| `type_name` | string | 异动类型的中性名称 | 直接用于界面展示；无法识别时为“未知异动” |
| `type_color` | integer | 类型颜色标志 | `0=红色`，`1=绿色`；未知类型不返回此字段 |
| `info` | string | 异动附加信息 | 原样保存；不要假定逗号分隔内容永远是固定字段 |

响应结构示例：

```json
{
  "ts": 1786000000123,
  "list": [
    {
      "type": "market_event",
      "data": [
        {
          "code": "SH600000",
          "info": "4.580000,199300,4.58000,0.100962",
          "seq": 15529,
          "time": 145637,
          "type_name": "大笔买入",
          "type_color": 0
        }
      ]
    }
  ]
}
```

#### 6.6.4 分页伪代码

```python
import json


def request_first_page(ws):
    ws.send(json.dumps({
        "type": "market_event",
        "seq": 1,
        "mode": 1,
        "count": 100,
        "enable": 1,
    }))


def request_previous_page(ws, last_row, request_seq):
    ws.send(json.dumps({
        "type": "market_event",
        "seq": request_seq,
        "mode": 2,
        "count": -100,
        "cursor": {
            "time": last_row["time"],
            "seq": last_row["seq"],
        },
        "enable": 1,
    }))
```

客户端处理响应时，应先遍历 `message["list"]`，再遍历 `item["data"]`。拿游标时使用同一页最后一条完整记录，并同时读取 `time` 和 `seq`；不要使用消息外壳的 `ts` 代替事件时间。

---

## 7. `snapshot` 行情响应

### 7.1 响应示例

下面是经过脱敏的结构示例，数值仅用于说明格式：

```json
{
  "ts": 1786000000123,
  "list": [
    {
      "type": "snapshot",
      "data": [
        {
          "code": "SZ000001",
          "name": "示例股票",
          "price": 1125,
          "high": 1150,
          "low": 1118,
          "pre_close": 1144,
          "volume": 1511510,
          "amount": 1703942517,
          "change_pct": -166,
          "turnover_ratio": 78,
          "market_value": 218316579727.0,
          "float_market_value": 218313007346.0,
          "bid1_price": 1124,
          "bid1_vol": 76,
          "ask1_price": 1125,
          "ask1_vol": 2840,
          "volume_ratio": 88
        }
      ]
    }
  ]
}
```

当前服务端不会在外层额外提供可靠的 `snapshot`/`update` 标志，因此客户端应该统一按照“部分更新”方式处理：

1. 看到一行中的 `code`，先找到该股票的缓存；
2. 只更新这一行实际出现的字段；
3. 行中没有出现的字段保留旧值；
4. 行中明确出现且值为 `null` 的字段，表示本次该字段无有效值；
5. 永远不要因为字段缺失就把旧字段清零。

### 7.2 为什么一条消息可能少股票

以下情况都可能导致一次 `data` 数组少于订阅股票数量：

- 某只股票当前没有可用行情；
- 行情服务正在切换或重连；
- 数据服务响应只携带了部分股票；
- 某字段对某只股票没有定义；
- 网络或交易状态导致这一次没有推送该股票。

这不是客户端解析错误。客户端应该按 `code` 独立维护缓存，不要按订阅数组下标对齐。

### 7.3 字段缺失和 `null` 的区别

```json
{
  "code": "SZ000001",
  "price": 1125
}
```

表示本次只提供了 `code` 和 `price`，其他字段保持缓存旧值。

```json
{
  "code": "SZ000001",
  "price": null
}
```

表示本次明确返回了 `price`，但当前没有有效价格。客户端应将该字段标记为无效，而不是把 `null` 当作 `0`。

### 7.4 代码作为缓存键

推荐的数据结构：

```python
latest_by_code: dict[str, dict] = {}

for row in rows:
    code = row.get("code")
    if not code:
        continue
    latest_by_code.setdefault(code, {}).update(row)
```

如果自定义 `fields` 时不请求字段 `code`，服务端返回行可能没有 `code`。这种情况下无法可靠地将多股票数据合并到缓存，因此生产程序应始终请求 `code`。

---

## 8. 字段类型和换算规则

### 8.1 JSON 类型

D101 最终返回 JSON，因此客户端看到的值类型只有：

| JSON 类型 | 说明 |
|---|---|
| string | 股票代码、股票名称、行业名称、文字描述 |
| number | 价格、数量、金额、比例、时间、标志值 |
| null | 没有有效值，或原始数据是 NaN/无穷值 |

这些值在 JSON 中统一表现为 `number`。Python 可以直接使用整数/浮点数；JavaScript 当前常用字段都在安全范围内，但处理未知字段时不要假设任意大整数一定能保持精度。

### 8.2 常用正式字段表

下表是当前 D101 用户侧最常用的正式字段。`raw` 表示 JSON 中收到的原始数值；D101 不会自动把价格、比例和数量转换成人类显示单位。

完整的 203 个正式字段、含义、单位和换算规则见[完整行情字段目录](d101_fields.md)。没有统一显示换算的字段保留原始值，客户端按字段语义处理。

| 字段名 | 类型 | 含义 | 常用换算 | 可信度 |
|---|---|---|---|---|
| `code` | string | 资产代码 | 不换算 | 高 |
| `name` | string | 资产名称 | 不换算 | 高 |
| `decimal_num` | number | 当前行价格小数位指数 | 不换算；价格除数为 `10 ** decimal_num` | 高 |
| `display_decimal_num` | number | 显示精度提示 | 不参与价格除法 | 高 |
| `price` | number | 最新价 | `raw / 10 ** decimal_num` | 高 |
| `high` | number | 当日最高价 | 与 `price` 缩放相同 | 高 |
| `low` | number | 当日最低价 | 与 `price` 缩放相同 | 高 |
| `open_price` | number | 开盘价 | 与 `price` 缩放相同 | 高 |
| `pre_close` | number | 前收盘价 | 与 `price` 缩放相同 | 高 |
| `avg_price` | number | 当日均价 | 与 `price` 缩放相同 | 高 |
| `change_amt` | number | 当日涨跌额 | `raw / 10 ** decimal_num` | 高 |
| `change_pct` | number | 当日涨跌幅 | `raw / 100` % | 高 |
| `volume` | number | 累计成交量 | 原始数量；单位由资产类型和 `volume_unit_flag` 决定 | 高 |
| `tick_vol` | number | 现手成交量 | 原始数量；与 `buy_sell_flag` 配对 | 高 |
| `buy_sell_flag` | number | 现手成交方向/状态 | 原始数值：`0=无方向`、`1=卖`、`2=买`、`3=未知`、`4=竞价` | 高 |
| `amount` | number | 累计成交额 | 原值透传；股票样本通常为元 | 中 |
| `total_share` | number | 总股本 | 原值透传 | 中 |
| `float_share` | number | 流通股本 | 原值透传 | 高 |
| `turnover_ratio` | number | 换手率 | `raw / 100` % | 高 |
| `real_turnover_ratio` | number | 换手率(实际) | `raw / 100` % | 高 |
| `market_value` | number | 总市值 | 原值通常按金额单位使用 | 高 |
| `float_market_value` | number | 流通市值 | 原值通常按金额单位使用 | 高 |
| `amplitude` | number | 振幅 | `raw / 100` % | 高 |
| `body_change_pct` | number | 实体涨幅 | `raw / 100` % | 高 |
| `bid1_price` | number | 买一价 | 与 `price` 缩放相同 | 高 |
| `bid1_vol` | number | 买一委托量 | 股票单位为手; 期权单位为张 | 高 |
| `bid2_price` | number | 买二价 | 与 `price` 缩放相同 | 高 |
| `bid3_price` | number | 买三价 | 与 `price` 缩放相同 | 高 |
| `bid4_price` | number | 买四价 | 与 `price` 缩放相同 | 高 |
| `bid5_price` | number | 买五价 | 与 `price` 缩放相同 | 高 |
| `ask1_price` | number | 卖一价 | 与 `price` 缩放相同 | 高 |
| `ask1_vol` | number | 卖一委托量 | 股票单位为手; 期权单位为张 | 高 |
| `ask2_price` | number | 卖二价 | 与 `price` 缩放相同 | 高 |
| `ask3_price` | number | 卖三价 | 与 `price` 缩放相同 | 高 |
| `ask4_price` | number | 卖四价 | 与 `price` 缩放相同 | 高 |
| `ask5_price` | number | 卖五价 | 与 `price` 缩放相同 | 高 |
| `inner_vol` | number | 内盘成交量 | 股票单位为手 | 高 |
| `outer_vol` | number | 外盘成交量 | 股票单位为手 | 高 |
| `order_buy_volume` / `order_sell_volume` | number | 委买量 / 委卖量 | 原值透传；单位由 `volume_unit_flag` 与资产类型决定 | 中 |
| `order_buy_sell_ratio` | number | 委比 | `raw / 100` % | 中 |
| `order_buy_sell_diff` | number | 委差 | 原值透传；单位由 `volume_unit_flag` 与资产类型决定 | 中 |
| `limit_up_price` | number | 涨停价 | 与 `price` 缩放相同 | 高 |
| `limit_down_price` | number | 跌停价 | 与 `price` 缩放相同 | 高 |
| `volume_ratio` | number | 量比 | `raw / 100` 倍 | 高 |
| `inner_outer_ratio` | number | 内外盘比 | `raw / 100` 倍 | 高 |
| `auction_volume_ratio` | number | 竞昨量比 | `raw / 100` 倍 | 高 |
| `auction_pre_volume_ratio` | number | 竞昨成交比 | `raw / 100` 倍 | 高 |
| `net_inflow` | number | 主力净流入 | 股票资金流样本约为万元；换算元可用 `raw × 10000` | 中 |
| `increase_rate_1min` / `increase_rate_2min` | number | 1/2 分钟涨速 | `raw / 100` % | 高 |
| `increase_rate_3min` / `increase_rate_4min` / `increase_rate_5min` | number | 3/4/5 分钟涨速 | `raw / 100` % | 高 |
| `change_pct_3d` / `change_pct_5d` / `change_pct_6d` / `change_pct_10d` | number | 多日涨幅 | `raw / 100` % | 高 |
| `high_60d` | number | 近 60 日最高价 | 与 `price` 缩放相同 | 高 |
| `dynamic_pe` | number | 动态市盈率 | `raw / 100` | 高 |
| `static_pe` | number | 静态市盈率 | `raw / 100` | 高 |
| `ttm_pe` | number | TTM 市盈率 | `raw / 100` | 高 |
| `pe_ratio` / `pb_ratio` / `ps_ratio` | number | 通用市盈率 / 市净率 / 市销率 | `raw / 100` | 高 |
| `dividend_yield` | number | 股息率 | `raw / 100` % | 高 |
| `auction_change_pct` / `auction_turnover_ratio` | number | 竞价涨幅 / 竞价换手率 | `raw / 100` % | 高 |
| `after_hours_volume` / `after_hours_amount` | number | 盘后成交量 / 成交额 | 原值透传 | 中 |
| `post_order_buy_volume` / `post_order_sell_volume` | number | 盘后委买量 / 委卖量 | 原值透传 | 中 |
| `trade_date` | number | 交易日期 | `YYYYMMDD` 整数 | 高 |
| `industry_name` | string | 行业/板块名称 | 不换算 | 高 |
| `limit_up_days` | string | 几天几板文本 | 原值透传 | 高 |
| `consecutive_limit_up_days` | number | 连板天数 | 原值透传 | 高 |
| `limit_up_days_legacy` | string | 旧版几天几板文本 | 原值透传 | 低 |
| `limit_up_open_count` | number | 涨停打开次数 | 无有效数据时按无效值处理 | 高 |
| `yearly_limit_up_days` | number | 年内涨停天数 | 无有效数据时按无效值处理 | 高 |

历史版本可能存在名称或口径差异；新程序必须使用字段目录中的规范 JSON 字段名。历史别名仅用于临时迁移，后续版本可能不再支持，不能作为稳定接口依赖。`decimal_num` 是价格精度元数据，`financing_flag` 是独立的融资融券标志；`net_share`、`float_share`、`float_a_share` 是三个不同字段；`increase_rate_1min`、`increase_rate_2min` 等按名称区分分钟口径。公共客户端不需要知道底层编号。

### 8.3 跨资产价格与单位精度换算规则

价格和价格差字段统一使用**同一行情行中的 `decimal_num`**，而不是按代码前缀写死除数。这样股票、指数、基金、期权、商品期货和美股都能使用同一规则；当前样本中，期权行通常给出 4 位精度，指数/股票行可给出 2 或 3 位精度。

百分数类字段（涨跌幅、换手率、涨速、封成比等）按字段目录使用 `raw / 100`；无量纲比值（量比、内外盘比、竞昨量比、竞昨成交比和估值比值）也按目录使用 `raw / 100`，但显示时不加百分号。成交量、委托量、股本和金额不使用价格小数位缩放：股票样本的成交量/现手/盘口量为手，期权样本为张；`volume_unit_flag` 是单位标志，仍需结合资产类型解释。金额和股本保留原始单位，不能看到数值后全局除以 100。

推荐客户端保留 `raw`，并使用以下行内换算函数生成显示值：

```python
def divide_price(row: dict, field: str):
    value = row.get(field)
    digits = row.get("decimal_num")
    if value is None or digits is None:
        return None
    return value / (10 ** int(digits))


def divide_percent(row: dict, field: str):
    value = row.get(field)
    return None if value is None else value / 100.0
```

不要用 `display_decimal_num` 替代 `decimal_num`，也不要按资产名称猜测价格除数。服务端响应始终保留原始字段值；GUI 只在显示层按上述规则生成计算值。

### 8.4 无效值和哨兵值

客户端至少要处理以下值：

| 形式 | 处理方式 |
|---|---|
| JSON `null` | 视为没有有效值 |
| 空字符串 `""` | 视为没有文字值 |
| `2147483647` | 部分未提供的数值字段可能使用该值作为占位值；不要直接展示为真实业务数据 |
| `255` | 部分统计字段可能使用该值作为未提供占位值；请结合字段语义处理 |
| `0` | 可能是真实的 0，也可能表示暂无数据，必须结合字段语义判断 |
| 缺少键 | 本次没有提供该字段；增量更新时保留缓存旧值 |

`0` 不能全局当作无效值。例如成交量为 0、涨跌幅为 0 都可能是真实数据。

---

## 9. 用户侧字段处理说明

客户端只需要处理 D101 返回的 JSON，不需要了解内部协议或字段编码。请按下面规则消费行情行：

- 按 JSON 键名读取字段，不要依赖对象字段顺序；
- 对 `null`、空字符串、缺少键和无效占位值做好兼容；
- 对目录之外的字段不要建立业务依赖；字段出现、消失或变成 `null` 时都应安全处理。

字段在请求中有名称顺序，但返回结果是 JSON 对象。客户端必须按语义键名读取：

```python
price = row.get("price")
```

不要写成“第 1 个 JSON 值就是价格”。

---

## 10. 完整字段目录与字段选择

D101 当前提供 203 个正式 JSON 字段；完整字段名、中文含义、单位和换算规则请直接查看[完整行情字段目录](d101_fields.md)。用户侧只使用目录中的语义字段名，未登记字段不会作为公共字段开放。

`tick_vol`（现手）是现手数量，`buy_sell_flag` 是对应的成交方向/状态。现手数量不以负数表示方向；`inner_vol`、`outer_vol` 分别是累计内盘、外盘成交量。D101 没有逐笔成交时间字段；WebSocket 外层 `ts` 是服务端发送时间，不是逐笔成交时间。`buy_sell_flag` 的取值为 `0=无方向`、`1=卖`、`2=买`、`3=未知`、`4=竞价`；响应保留原始数值，更大值按未知处理。沪深股票/ETF 的 `tick_vol` 单位为手，不能用负号判断方向。

服务端已经把原始数值还原为 JSON number。客户端不应把所有 number 统一按同一个除数处理，应按字段目录中的语义和换算规则处理。

---

## 11. K 线接口边界

K 线不是 D101 WebSocket 命令。D101 只负责实时行情快照和盘口异动；不要向
`/d101` 发送 `type: "kline"`，服务端会拒绝该命令。

需要日、周、月或分钟 K 线时，请调用 D4 的 HTTP 接口：

```text
GET http://127.0.0.1:8080/d4/l1/kline?code=SZ000001&period=7&count=100&fq=18
```

完整的请求参数、返回字段和示例见 [`d4_http_api.md`](d4_http_api.md)。

---

## 12. Python 生产级客户端示例

下面的示例包含：

- 自动重连；
- 自定义字段；
- 按股票代码合并增量；
- `null` 和缺字段处理；
- 指数换算；
- 错误日志；
- 关闭前退订。

保存为 `d101_client.py`：

```python
from __future__ import annotations

import json
import logging
import time
from typing import Any

import websocket


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

URL = "ws://127.0.0.1:8080/d101"

# 下面是“需要服务端原始统计字段”的较完整示例；普通监控请从最小字段集合开始，
# 不要因为客户端要显示涨跌幅、涨跌额、振幅或成交额，就额外请求可本地计算的字段。
# 这里保留 amount 是为了演示如何核对服务端精确原始成交额；普通监控可以删除它。
# code 必须保留，否则多资产返回行可能无法关联到资产。
FIELDS = [
    "code", "name",
    "price", "high", "low", "pre_close", "volume", "amount",
    "change_pct", "turnover_ratio", "market_value", "float_market_value", "amplitude",
    "bid1_price", "bid1_vol", "ask1_price", "ask1_vol",
    "change_pct_5d", "limit_up_price", "limit_down_price", "volume_ratio",
    "prev_day_change_pct", "prev_day_volume", "high_60d", "open_price", "avg_price",
]

CODES = ["SZ000001", "SH600000", "SZ300750"]


def safe_div(value: Any, divisor: float) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / divisor
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def price_divisor(row: dict[str, Any]) -> int:
    """使用行内 `decimal_num`；没有元数据时仅作兼容回退。"""
    try:
        digits = int(row.get("decimal_num"))
    except (TypeError, ValueError):
        code = str(row.get("code") or "").upper()
        digits = 4 if code.startswith(("SO", "ZO", "CFFEXOPTION|")) else 2
    return 10 ** digits if 0 <= digits <= 9 else 100


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    """保留 raw 字段，同时增加少量显示字段。"""
    result = dict(row)
    divisor = price_divisor(row)
    result["price_yuan"] = safe_div(row.get("price"), divisor)
    result["high_yuan"] = safe_div(row.get("high"), divisor)
    result["low_yuan"] = safe_div(row.get("low"), divisor)
    result["pre_close_yuan"] = safe_div(row.get("pre_close"), divisor)
    result["change_pct_display"] = safe_div(row.get("change_pct"), 100)
    result["amplitude_display"] = safe_div(row.get("amplitude"), 100)
    return result


class D101Client:
    def __init__(self, url: str, codes: list[str], fields: list[str]) -> None:
        self.url = url
        self.codes = codes
        self.fields = fields
        self.latest: dict[str, dict[str, Any]] = {}
        self.seq = 1
        self.ws: websocket.WebSocket | None = None

    def command(self) -> dict[str, Any]:
        command = {
            "type": "snapshot",
            "seq": self.seq,
            "enable": 1,
            "codes": self.codes,
            "fields": self.fields,
        }
        self.seq = (self.seq % 65535) + 1
        return command

    def handle_item(self, item: dict[str, Any]) -> None:
        item_type = item.get("type")

        if item_type == "info":
            logging.info("info: %s", item)
            return

        if item_type == "error":
            logging.error("server error: %s", item)
            return

        if item_type != "snapshot":
            logging.info("other item: %s", item)
            return

        data = item.get("data")
        if not isinstance(data, list):
            logging.warning("snapshot item has no data array: %s", item)
            return

        for raw_row in data:
            if not isinstance(raw_row, dict):
                continue
            code = raw_row.get("code")
            if not isinstance(code, str) or not code:
                logging.warning("skip row without code: %s", raw_row)
                continue

            # 增量推送可能只携带变化字段，所以必须 update，不能整体覆盖。
            merged = self.latest.setdefault(code, {})
            merged.update(raw_row)
            display = normalize(merged)
            logging.info(
                "%s price=%s change=%s%% volume=%s",
                code,
                display.get("price_yuan"),
                display.get("change_pct_display"),
                display.get("volume"),
            )

    def run_once(self) -> None:
        self.ws = websocket.create_connection(self.url, timeout=30)
        try:
            self.ws.send(json.dumps(self.command(), ensure_ascii=False))
            while True:
                text = self.ws.recv()
                message = json.loads(text)
                if not isinstance(message, dict):
                    logging.warning("message is not an object: %r", message)
                    continue
                for item in message.get("list", []):
                    if isinstance(item, dict):
                        self.handle_item(item)
        finally:
            try:
                self.ws.send(json.dumps({"type": "snapshot", "enable": 0}))
            except Exception:
                pass
            self.ws.close()
            self.ws = None

    def run_forever(self) -> None:
        delay = 1.0
        while True:
            try:
                self.run_once()
                delay = 1.0
            except KeyboardInterrupt:
                logging.info("stopped")
                return
            except Exception as exc:
                logging.warning("D101 disconnected: %s", exc)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    D101Client(URL, CODES, FIELDS).run_forever()
```

### 12.1 这个示例为什么不整体替换缓存

假设缓存中已有：

```json
{
  "code": "SZ000001",
  "price": 1125,
  "high": 1150,
  "volume": 1511510
}
```

下一条只推送：

```json
{
  "code": "SZ000001",
  "price": 1126
}
```

如果使用：

```python
latest[code] = row
```

就会丢失 `high` 和 `volume`。正确做法是：

```python
latest.setdefault(code, {}).update(row)
```

---

## 13. JavaScript 浏览器示例

```html
<!doctype html>
<meta charset="utf-8">
<pre id="output">connecting...</pre>
<script>
const output = document.getElementById('output');
const latest = new Map();
const ws = new WebSocket('ws://127.0.0.1:8080/d101');

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'snapshot',
    seq: 1,
    enable: 1,
    codes: ['SZ000001', 'SH600000'],
    fields: [
      'code', 'name', 'price', 'high', 'low', 'pre_close', 'volume', 'amount',
      'change_pct', 'turnover_ratio', 'market_value', 'float_market_value',
      'bid1_price', 'bid1_vol', 'ask1_price', 'ask1_vol', 'volume_ratio'
    ]
  }));
};

ws.onmessage = event => {
  const message = JSON.parse(event.data);
  for (const item of message.list || []) {
    if (item.type === 'info') {
      output.textContent += `\nINFO ${JSON.stringify(item)}`;
      continue;
    }
    if (item.type === 'error') {
      output.textContent += `\nERROR ${JSON.stringify(item)}`;
      continue;
    }
    if (item.type !== 'snapshot') continue;

    for (const row of item.data || []) {
      if (!row.code) continue;
      const old = latest.get(row.code) || {};
      const merged = {...old, ...row};
      latest.set(row.code, merged);

      const price = merged.price == null ? null : merged.price / 10;
      output.textContent = `${merged.code} ${merged.name || ''} price=${price}\n` +
        JSON.stringify(merged, null, 2);
    }
  }
};

ws.onerror = event => {
  output.textContent += `\nWebSocket error: ${event.type}`;
};

window.addEventListener('beforeunload', () => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'snapshot', enable: 0}));
    ws.close();
  }
});
</script>
```

浏览器示例使用 `Number` 保存 JSON 数字。对于未来新增的极大整数，若业务要求绝对精确，应在协议层增加字符串字段或使用支持大数的 JSON 解析器。

---

## 14. 断线和重连

### 14.1 本地 WebSocket 断开

客户端应在以下情况重连：

- `recv()` 抛出连接关闭异常；
- `onclose` 触发；
- 连接建立后长时间没有任何消息；
- 本地程序重启。

推荐退避时间：

```text
1 秒 → 2 秒 → 4 秒 → 8 秒 → 16 秒 → 30 秒封顶
```

每次重新建立 WebSocket 后都要重新发送订阅命令。订阅不会跨 WebSocket 连接自动继承。

### 14.2 数据长时间没有变化

“没有新消息”不一定是断线：

- 行情没有变化时，服务端可能不重复发送完全相同的数据；
- 非交易时段推送可能很少；
- 某只股票暂时没有有效数据。

客户端应区分：

- WebSocket 是否仍然打开；
- 最近一次收到任意消息的时间；
- 最近一次收到某只股票行情的时间。

不要仅因为某只股票几秒没有更新就立刻重连整个连接。

### 14.3 重连后的缓存

重连后第一批数据应视为新的基线快照：

```python
latest.clear()
```

然后重新接收数据。若业务必须区分“重连前旧数据”和“重连后新数据”，请为缓存增加连接代次或本地时间戳。

---

## 15. 错误处理对照表

| 现象 | 可能原因 | 客户端处理 |
|---|---|---|
| WebSocket connection refused | 本地程序未启动或端口错误 | 启动程序，确认 `/d101/info` |
| `/d101/info` 返回 403 | 当前账号没有 D101 权限 | 登录并开通对应权限 |
| WebSocket 刚连接就关闭 | 权限不足或本地程序正在退出 | 查看本地程序状态，不要循环高频重连 |
| `Invalid JSON` | 发送的文本不是合法 JSON | 使用 `json.dumps` 或 `JSON.stringify` |
| `type required and must be string` | 缺少 `type` 或类型不是字符串 | 检查命令结构 |
| `codes required and must be array` | `snapshot` 未提供 `universe`，且 `codes` 缺失或不是数组 | 添加非空 `codes` 数组，或改用本文列出的 `universe` |
| `codes must not be empty` | 股票数组为空 | 至少传一只股票 |
| `fields must be array if present` | `fields` 不是数组 | 改为字段名数组，或删除 `fields` 使用默认字段 |
| `unknown field name: ...` | `fields` 中包含未登记的字段名 | 使用本文字段表中的正式语义字段名 |
| `fields items must be field-name strings` | `fields` 中出现了非字符串值 | 改为字符串语义字段名 |
| `market_event mode must be 1 or 2` | `market_event.mode` 不是支持的模式 | 当前/持续请求使用 `mode=1`，历史分页使用 `mode=2` |
| `market_event mode=1 requires a positive count` | 当前模式使用了负数条数 | `mode=1` 改用正数 `count` |
| `market_event mode=2 requires cursor.time (HHMMSS) and cursor.seq from the previous page` | 历史请求缺少成对游标，或游标无效 | 使用上一页最后一行的 `time` 和 `seq`；第一页改用 `mode=1` |
| `market_event cursor must be an object` | `cursor` 不是 JSON 对象 | 使用 `{"cursor":{"time":145452,"seq":15442}}` |
| `snapshot_1 exists` | 同一连接重复使用 `seq=1` | 换一个 `seq` 或退订后再订阅 |
| 只有 `info` 没有 `data` | 订阅尚未建立、无行情或服务端重连 | 等待并记录后续消息 |
| `data` 少于股票数 | 本次只返回部分股票 | 按 `code` 合并，不按数组下标对齐 |
| 某个值为 `null` | 无数据或原始特殊值 | 按空值处理，不转成 0 |
| 数值明显错位 | 请求了目录之外的字段或字段类型不匹配 | 只使用正式字段；删除非正式字段 |

---

## 16. 联调步骤

### 16.1 先测本地 HTTP

```powershell
Invoke-WebRequest -UseBasicParsing `
  -Uri "http://127.0.0.1:8080/d101/info"
```

确认返回 JSON，并且 `max_stocks`、`max_fields` 存在。

### 16.2 再测最小 WebSocket

先只请求一个股票和四个字段：

```json
{
  "type": "snapshot",
  "seq": 1,
  "codes": ["SZ000001"],
  "fields": ["code", "name", "price", "change_pct"]
}
```

确认：

- 能收到 `info`；
- 能收到 `type == "snapshot"`；
- `data` 是数组；
- 每行有 `code`；
- `price`、`change_pct` 是 number 或 null。

### 16.3 再增加字段

建议按照下面顺序增加：

```text
code,name
→ price,high,low,pre_close
→ volume,amount
→ change_pct,turnover_ratio,amplitude,volume_ratio
→ bid1_price,bid1_vol,ask1_price,ask1_vol
→ change_pct_5d,limit_up_price,limit_down_price,prev_day_change_pct,prev_day_volume,high_60d,open_price,avg_price
```

每次增加一组后确认：

- 行数没有异常减少；
- JSON 仍能正常解析；
- 行中没有大面积缺失；
- 价格、数量、比例的换算符合预期。

不要第一次就把目录之外的字段名发送给生产程序。字段上限是数量上限，不代表任意字段名都可用。

### 16.4 测试增量合并

在测试程序里人工构造两条数据：

```json
{"code":"SZ000001","price":1125,"high":1150}
```

和：

```json
{"code":"SZ000001","price":1126}
```

最终缓存必须仍然包含 `high=1150`，这可以验证客户端没有错误地覆盖缓存。

---

## 17. 生产使用建议

### 必做

- 始终遍历 `list`；
- 始终按 `code` 关联股票；
- 始终保留原始值；
- 按任务选择最小 `fields` 集合；能由已收到的基础值计算的指标，不要重复请求；
- 对 `null`、空字符串、缺失键和哨兵值做判断；
- 增量消息使用合并更新；
- 断线后重新订阅；
- 记录最近收包时间和最后错误；
- 限制自己的重连频率；
- 遇到未知 JSON 字段时忽略而不是崩溃。

### 不要做

- 不要按数组下标关联股票；
- 不要把一条 WebSocket 消息当作一条行情；
- 不要把缺失键当作 0；
- 不要把 `null` 当作 0；
- 不要把所有字段统一除以 10 或 100；
- 不要依赖 JSON 键的顺序；
- 不要请求未确认字段后直接用于交易策略；
- 不要把“全部 203 字段”作为常驻订阅默认值；只有字段核对、原始采样或确有业务需要时才请求；
- 不要在客户端保存或转发任何账号凭证；
- 不要绕过本地 D101 连接外部地址。

---

## 18. 版本兼容策略

D101 未来可能增加字段，但已有字段的 JSON 键应保持兼容。客户端建议遵循：

1. 对象读取使用 `get`/可选字段，不要要求所有字段都存在；
2. 忽略未知键；
3. 不依赖 `list` 中项目顺序；
4. 不依赖 `info.msg` 的具体文字；
5. 只有在字段表中有明确说明的键才用于策略计算；
6. 将字段映射放在单独配置或常量表中，方便升级；
7. 保留 `raw` 和 `normalized` 两套值，便于发现单位变化。

推荐在启动时打印客户端自身支持的字段集合：

```python
print("D101 fields:", FIELDS)
```

当服务端新增字段时，旧客户端不请求它也能继续工作；当服务端新增 JSON 键时，旧客户端忽略即可。

---

## 19. 最终验收清单

一个可以交付的 D101 客户端至少应通过以下检查：

- [ ] 能检查 `/d101/info`；
- [ ] 能连接 `ws://127.0.0.1:8080/d101`；
- [ ] 能处理连接欢迎消息；
- [ ] 能发送 `snapshot` 订阅命令；
- [ ] `fields` 中包含字段 `code`；
- [ ] 能遍历 `list` 和 `data`；
- [ ] 能按 `code` 建立股票缓存；
- [ ] 能合并只包含部分字段的增量数据；
- [ ] 能处理 `null` 和缺少字段；
- [ ] 能正确把价格 raw 值转换为显示价格；
- [ ] 能处理错误项目而不崩溃；
- [ ] 能发送退订命令；
- [ ] WebSocket 断开后能退避重连；
- [ ] 重连后会重新发送订阅；
- [ ] 不依赖任何外部地址、内部凭证或隐藏配置；
- [ ] 不把未确认字段直接用于生产策略。

完成以上项目后，Python、JavaScript、Go、Java、C# 或 C++ 客户端都可以按照同一份 D101 用户侧契约实现。

## 获取客户端

本文档描述的是本机运行的**达塔接口**客户端。安装包不随文档分发，请到官网下载：

**<https://datas.lovestoblog.com/>**

官网提供 Windows、macOS（Apple Silicon / Intel）、Linux 以及无桌面环境的
服务器版安装包。
