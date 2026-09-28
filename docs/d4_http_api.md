# D4 证券品种与历史数据 API

本文面向第一次调用 D4 的用户。看完后，你应该能够：

1. 请求一页股票或其他证券品种；
2. 看懂返回的 JSON；
3. 用 Python、PowerShell 或 JavaScript 翻页读取整个品种池；
4. 在字段较多时正确处理不完整响应。

D4 是本地 HTTP 接口。调用方只需要发送 HTTP 请求并解析 JSON，不需要处理内部连接和二进制细节。

## 1. 开始前准备

先启动本地程序并完成登录。默认 HTTP 端口是 `8080`；如果你的程序使用了其他端口，把下面示例中的 `8080` 替换成实际端口。

D4 的完整地址是：

```text
http://127.0.0.1:8080/d4/l1/instrument_list
```

这是一个 `GET` 接口，所有请求参数都写在 URL 的查询参数中。

## 2. 第一个请求：读取 3 只股票

### 2.1 浏览器或任何 HTTP 工具

```text
http://127.0.0.1:8080/d4/l1/instrument_list?universe=cn_hsj_stock&skip=0&count=3&fields=code,name,price
```

### 2.2 PowerShell

```powershell
$url = 'http://127.0.0.1:8080/d4/l1/instrument_list?universe=cn_hsj_stock&skip=0&count=3&fields=code%2Cname%2Cprice'
$result = Invoke-RestMethod -Uri $url -Method Get
$result | ConvertTo-Json -Depth 6
```

### 2.3 Python

```python
import requests

url = "http://127.0.0.1:8080/d4/l1/instrument_list"
params = {
    "universe": "cn_hsj_stock",
    "skip": 0,
    "count": 3,
    "fields": "code,name,price",
}

response = requests.get(url, params=params, timeout=30)
response.raise_for_status()
result = response.json()

if "error" in result:
    raise RuntimeError(result["error"])

print("品种总数:", result["total"])
print("本次返回:", result["count"])
for row in result["rows"]:
    print(row["code"], row.get("name"), row.get("price"))
```

### 2.4 成功返回示例

```json
{
  "total": 5559,
  "count": 3,
  "rows": [
    {"code": "SZ000001", "name": "平安银行", "price": 1141},
    {"code": "SZ000002", "name": "万  科Ａ", "price": 308},
    {"code": "SZ000006", "name": "深振业Ａ", "price": 706}
  ]
}
```

这个响应表示：当前品种池共有 `5559` 条，本次请求返回了其中 `3` 条；实际数据在 `rows` 数组中。

## 3. 请求参数

所有参数都是可选的。第一次调用建议只填写 `universe`、`skip`、`count` 和 `fields`。

| 参数 | 类型 | 默认值 | 是否必填 | 说明 |
|---|---|---:|:---:|---|
| `universe` | string | `cn_hsj_stock` | 否 | 要读取的业务品种池，见下一节 |
| `skip` | integer | `0` | 否 | 跳过多少条记录；第一页必须是 `0` |
| `count` | integer | `300` | 否 | 本页最多请求多少条；基础字段建议从 `1000` 开始，字段较多时改小 |
| `fields` | string | 服务端默认字段 | 否 | 需要返回的字段，使用逗号分隔的字段名或字段 ID |
| `sort` | integer | `0` | 否 | 排序方式；`0` 为默认代码顺序，初学者保持 `0` |
| `order` | integer | `0` | 否 | 排序方向；`0` 升序，`1` 降序 |
| `category` | integer | `0` | 否 | 兼容参数；查询上表中的业务品种池时通常保持 `0` |

### 参数写法示例

只请求代码、名称、最新价：

```text
?universe=cn_hsj_stock&skip=0&count=1000&fields=code,name,price
```

也可以使用字段 ID：

```text
?universe=cn_hsj_stock&skip=0&count=1000&fields=1,2,3
```

如果使用 Python `requests` 或 JavaScript `URLSearchParams`，不需要手动处理逗号和中文的 URL 编码。

## 4. `universe` 品种池

数量会随着上市、退市和列表状态变化，程序必须使用响应中的 `total`，不要把下表数量写死。

| `universe` | 内容 | 代码示例 |
|---|---|---|
| `cn_hs_stock` | 沪深 A股，不含北交所 | `SH600000`、`SZ000001` |
| `cn_hsj_stock` | 沪深京 A股，包含北交所 | `SH600000`、`SZ920000` |
| `cn_sh_stock` | 上海 A股 | `SH600000` |
| `cn_sz_stock` | 深圳 A股 | `SZ000001` |
| `cn_bse_stock` | 北交所股票 | `SZ920000` |
| `cn_star_stock` | 科创板股票 | `SH688001` |
| `cn_sh_b_stock` | 上海 B 股 | `SH900901` |
| `cn_sz_b_stock` | 深圳 B 股 | `SZ200011` |
| `cn_index` | 沪深指数 | `SH000001`、`SZ399001` |
| `cn_fund` | 沪深基金集合，包含 ETF、LOF、普通基金和 REIT | `SZ158000` |
| `cn_sh_fund` | 上海基金 | `SH501001` |
| `cn_sz_fund` | 深圳基金 | `SZ158000` |
| `cn_reit` | REIT | `SZ180101` |
| `cn_sh_bond` | 上海债券 | `SH010706` |
| `cn_sz_bond` | 深圳债券 | `SZ100706` |
| `cn_option` | 期权合并集合 | `SO10010971` |
| `cn_etf_option` | ETF 期权 | `SO10010971` |
| `cn_option_call` | 期权认购 | `SO10010971` |
| `cn_option_put` | 期权认沽 | `SO10010980` |

注意：`cn_fund` 是基金混合集合，不是 ETF 专属集合。当前没有单独公开的 ETF 基金池名称。

## 5. `fields` 字段

### 5.1 推荐字段组合

| 用途 | `fields` |
|---|---|
| 只获取代码 | `code` 或 `1` |
| 获取代码和名称 | `code,name` 或 `1,2` |
| 获取列表和最新价 | `code,name,price` 或 `1,2,3` |
| 获取常用行情 | `code,name,price,change_pct,volume,amount_wan` |
| 获取股票市值和股本 | `code,name,price,total_share,total_mv_wan,float_share,float_mv` |

程序通常应该显式传 `fields`，这样返回字段稳定、响应更小，也更容易维护。无论请求哪些字段，都建议保留 `code`，否则客户端无法可靠地按品种更新数据。

### 5.2 常用字段表

下面的字段可以直接写名称，也可以写对应 ID。返回 JSON 中的键名使用“字段名”列。

| ID | 字段名 | JSON 类型 | 含义 |
|---:|---|---|---|
| 1 | `code` | string | 品种代码 |
| 2 | `name` | string | 品种名称 |
| 3 | `price` | number | 最新价 |
| 4 | `change_pct` | number | 当日涨跌幅 |
| 5 | `change_amt` | number | 当日涨跌额 |
| 6 | `bid1` | number | 买一价 |
| 7 | `ask1` | number | 卖一价 |
| 8 | `industry_name` | string | 行业名称 |
| 9 | `volume` | number | 成交量 |
| 10 | `tick_vol` | number | 现手量 |
| 11 | `amount_wan` | number | 成交额，万元口径 |
| 12 | `pe_ttm` | number | TTM 市盈率 |
| 13 | `speed_3min` | number | 近 3 分钟涨速 |
| 14 | `turnover_rate` | number | 换手率 |
| 15 | `volume_ratio` | number | 量比 |
| 16 | `pre_close` | number | 昨收价 |
| 17 | `open` | number | 开盘价 |
| 18 | `high` | number | 最高价 |
| 19 | `low` | number | 最低价 |
| 20 | `amplitude` | number | 振幅 |
| 21 | `pb` | number | 市净率 |
| 22 | `total_share` | number | 总股本的列表表示；服务端按参考客户端规则解码，大股数可能带量化步进 |
| 23 | `total_mv_wan` | number | 总市值，万元口径 |
| 24 | `float_share` | number | 流通股本；股票列表中为 8 字节整数 |
| 25 | `float_mv` | number | 流通市值 |
| 26 | `outer_vol` | number | 外盘量 |
| 27 | `inner_vol` | number | 内盘量 |
| 28 | `change_pct_3d` | number | 近 3 日涨跌幅 |
| 29 | `change_pct_6d` | number | 近 6 日涨跌幅 |
| 30 | `turnover_3d` | number | 近 3 日换手率 |
| 31 | `turnover_6d` | number | 近 6 日换手率 |
| 32 | `eps` | number | 每股收益 |
| 33 | `roe` | number | 净资产收益率 |
| 34 | `list_date` | number | 上市日期，通常为 `YYYYMMDD` |

### 5.3 扩展字段

这些字段主要用于盘口或期权品种，使用前建议先用少量记录测试。

| ID | 字段名 | JSON 类型 | 含义 |
|---:|---|---|---|
| 157 | `bid1_vol` | number | 买一量 |
| 162 | `ask1_vol` | number | 卖一量 |
| 181 | `opt_price` | number | 期权相关价格 |
| 195 | `open_interest` | number | 持仓量 |
| 196 | `remain_days` | number | 剩余天数 |
| 197 | `strike` | number | 行权价 |
| 199 | `unit_size` | number | 合约单位 |
| 200 | `delta` | number | Delta |
| 201 | `gamma` | number | Gamma |
| 202 | `vega` | number | Vega |
| 203 | `theta` | number | Theta |
| 247 | `amount` | number | 成交金额字段 |
| 293 | `amount_yuan` | number | 成交额，元口径；具体品种未提供时可能为 0 |
| 316 | `leverage` | number | 杠杆率 |
| 320 | `contract` | string | 合约描述 |

### 5.4 数值精度

D4 返回 JSON 数字，但不会把所有品种和字段统一转换成“元”或统一的小数位。股票、债券、基金和期权的价格精度可能不同；程序应先按 number 保存，不要在通用代码中把所有数字统一除以 `100` 或 `1000`。

如果只是获取代码和名称，可以使用 `fields=code,name`，不需要处理价格精度。

股票列表中的股本/市值字段需要按各自口径处理：`price` 通常是价格的放大整数，`total_mv_wan` 和 `float_mv` 的单位是万元，`total_share` 和 `float_share` 是股数。以股票列表为例，页面常见的“总市值（亿）”可用 `total_mv_wan / 10000` 换算；“总股本/流通股本（亿股）”可用对应股数字段 `/ 100000000` 换算。

字段 ID `22` 的业务含义已经用 d6 全市场数据和参考 App 详情响应交叉确认是总股本的列表表示。服务端会先按参考客户端规则解码，再返回 `total_share`；调用方不需要处理原始槽位，也不要把它当作有符号整数。

列表协议为了把大股数压进固定槽位，会丢弃大数的低位，因此大股数返回值可能按 16、256 或 4096 股为步进。它不能恢复详情接口中额外提供的全部低位；不要用总市值除以价格自行伪造精确股本。需要精确详情值时，应使用提供精确股本的详情接口。

历史客户端继续使用字段 ID `22` 或名称 `total_share` 均可，响应键统一为 `total_share`。

如果省略 `fields`，服务端会使用默认字段集合。默认字段可能随着服务端升级增加，正式程序建议显式指定字段。

### 5.5 K 线列表

D4 同时提供股票、ETF、基金、指数、债券、REIT 及期权等已支持品种的 K 线列表接口：

```text
GET /d4/l1/kline?code=SZ000001&period=7&count=100&fq=18
```

完整地址示例：

```text
http://127.0.0.1:8080/d4/l1/kline?code=SZ000001&period=7&count=100&fq=18
```

期权示例：

```text
http://127.0.0.1:8080/d4/l1/kline?code=SO10011007&period=7&count=100&fq=18
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `code` | string | 无 | 股票、ETF、基金、指数、债券等使用 6 位数字，或带市场前缀的 `SH`/`SZ`/`BJ` 加 6 位，例如 `000001`、`SZ000001`、`SH510300`；期权使用 `SO` 加 8 位合约号，例如 `SO10011007`，也接受不带 `SO` 的 8 位合约号；必填。列表接口取得的代码建议原样保留前缀 |
| `market` | string | 自动 | 六位代码可填 `SH`、`SZ`、`BJ`，也可填 `1`/`0`；仅在代码没有市场前缀且存在歧义时使用。期权代码不需要此参数 |
| `period` | integer | `7` | `7` 日 K、`8` 周 K、`9` 月 K；`1`、`2`、`3`、`4`、`5` 分别为 1 分钟、5 分钟、15 分钟、30 分钟、60 分钟 |
| `count` | integer | `100` | 请求 K 线根数，建议先从 `100` 开始 |
| `fq` | integer | `18` | `18` 前复权、`0` 不复权、`9` 后复权 |

成功响应示例：

```json
{
  "code": "000001",
  "list_date": 20101203,
  "count": 2,
  "rows": [
    {
      "date": 20260820,
      "open": 112000,
      "high": 114000,
      "low": 111900,
      "close": 114000,
      "volume": 1183578,
      "amount": 1338932697,
      "turnover": 61,
      "turnover_real": 145
    }
  ]
}
```

`rows` 中每一项就是一根 K 线。当前服务返回的 OHLC 使用固定精度整数，GUI 会按价格精度还原后显示；成交量、成交额和换手字段按响应值展示。期权合约的 OHLC 也使用相同的 K 线记录结构，`SO10011007` 的 `close=3508` 对应界面价格 `0.3508`。调用方应保留整数精度，不要把所有字段统一当成价格处理。

期权响应中的 `list_date` 目前可能为 `0`；这只表示该品种没有提供上市日期字段，不影响 `rows` 中 K 线的有效性。

### 5.6 详情资金摘要与分钟数据

D4 还提供个股详情页使用的三类数据。它们与 K 线一样属于详情/历史数据，D101 不承载这些请求：

```text
GET /d4/l1/money_flow?code=SZ300750
GET /d4/l1/minute_history?code=SZ300750
GET /d4/l1/minute_trades?code=SZ300750
GET /d4/l1/minute_trades?code=SO10011009
```

`money_flow` 返回一条资金摘要，默认覆盖今日趋势、3/5/20/60 日趋势、主力及超大/大/中/小单净额、流入/流出分项和排名字段。`minute_history` 返回分钟表；默认字段是时间、开高低收、均价、成交量、成交额、委托量和委托差等详情页常用字段。`minute_trades` 返回一次 HTTP 查询得到的分时成交表，服务端不会保持推送连接。

三个接口都接受 `code` 和 `market`；`fields` 只用于前两个字段可选的详情表，`request_time` 用于分钟历史或分时成交的请求游标：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `code` | string | 无 | 资金摘要/分钟历史使用 `SH`/`SZ`/`BJ` 加 6 位代码；分时成交还支持 `SO` 加 8 位合约号；六位代码也可配合 `market` 使用；必填 |
| `market` | string | 自动 | 六位代码的市场，可填 `SH`、`SZ`、`BJ`、`1` 或 `0` |
| `fields` | string | 接口默认集合 | `money_flow`、`minute_history` 的可选业务字段集合；`minute_trades` 不接受此参数 |
| `request_time` | integer | `0` | 股票分时成交/分钟历史保持 `0` 首次查询；期权分时成交首次使用 `-1` 获取最新一页，后续使用响应中的 `next_request_time` |
| `count` | integer | `61` | 仅期权分时成交使用，每页 1～200 条；服务端返回的 `next_request_time` 可直接作为下一次请求游标 |

资金摘要示例：

```json
{
  "code": "SZ300750",
  "data": {
    "date": 20260906,
    "money_trend": 120,
    "money_trend_5d": 1300,
    "main_net_amount": 99050000,
    "super_net_amount": 42000000,
    "big_net_amount": 31000000,
    "mid_net_amount": -8000000,
    "small_net_amount": -64000000,
    "in_rank": 5
  }
}
```

分钟数据示例：

```json
{
  "code": "SZ300750",
  "data_total": 286,
  "collection_total": 15,
  "after_market_total": 30,
  "count": 1,
  "rows": [
    {"time": 93000, "close_price": 8900, "volume": 100, "amount": 50000}
  ]
}
```

分时成交示例：

```json
{
  "code": "SZ300750",
  "max_count": 200,
  "data_count": 2,
  "count": 2,
  "rows": [
    {"time": 93000, "price": 8900, "volume": 100, "volume_mismatch": -3, "direction": "buy"},
    {"time": 93100, "price": 8910, "volume": 120, "volume_mismatch": 0, "direction": "sell"}
  ]
}
```

期权分时成交的响应会额外返回仓差、方向、性质和翻页游标：

```json
{
  "code": "SO10011009",
  "max_count": 61,
  "data_count": 0,
  "position": 1876,
  "next_request_time": 1754,
  "has_more": true,
  "count": 2,
  "rows": [
    {"time": 145531, "price": 437, "volume": 17, "position_change": 0,
     "direction": "sell", "trade_type": 2, "property": "short_switch", "property_name": "空换"},
    {"time": 150000, "price": 432, "volume": 2, "position_change": 1,
     "direction": "sell", "trade_type": 2, "property": "short_open", "property_name": "空开"}
  ]
}
```

期权首次请求使用 `request_time=-1`；将响应的 `next_request_time` 原样带到下一次请求即可继续向更早的成交翻页。`position_change` 是仓差，`property_name` 对应页面中的多开、空开、多换、空换、双开、双平等性质；价格和成交量仍保留服务端整数精度。

示例数值仅用于说明结构。详情接口保留协议整数精度；金额、价格和成交量的实际显示单位由字段类型及客户端精度规则决定，不要把所有整数统一除以同一个倍率。`direction` 已经是业务方向文本；无法判断方向时返回 `unknown`。当前未开放持续推送；本接口只提供单次 HTTP 查询。

## 6. 返回值说明

### 6.1 成功响应

```json
{
  "total": 5559,
  "count": 2,
  "rows": [
    {
      "code": "SZ000001",
      "name": "平安银行",
      "price": 1141
    },
    {
      "code": "SZ000002",
      "name": "万  科Ａ",
      "price": 308
    }
  ]
}
```

| 返回字段 | 类型 | 说明 |
|---|---|---|
| `total` | integer | 当前品种池总数量；翻页时用它判断是否读完 |
| `count` | integer | 本次实际返回的记录数 |
| `rows` | array | 当前页数据；每个元素是一个对象 |
| `rows[].code` | string | 品种代码；建议作为客户端缓存的主键 |
| `rows[]` 的其他键 | 取决于 `fields` | 请求了什么字段，行对象就返回对应键名 |

`count` 应与 `rows.length` 一致，但客户端仍建议以实际 `rows.length` 为准。最后一页的记录数通常小于请求的 `count`，这是正常现象。

### 6.2 错误响应

HTTP 请求可能已经成功到达本地程序，但 JSON 仍可能包含 `error`：

```json
{
  "error": "unsupported universe"
}
```

程序必须先检查 `error`，再读取 `total` 和 `rows`。常见错误如下：

| 错误或现象 | 原因 | 处理方式 |
|---|---|---|
| `unsupported universe` | `universe` 拼写错误或不在支持列表 | 复制本文第 4 节的名称 |
| `request failed` | 列表服务暂时没有返回 | 稍后重试，避免高频重试 |
| 列表解析失败 | 本次返回无法解析 | 减小 `count`，并使用 `fields=1,2,3` 重试 |
| `rows` 为空 | 已到末页，或当前品种池暂时没有记录 | 先检查 `total` 和 `skip` |
| `rows` 少于 `count` | 到达末页或列表在翻页期间发生变化 | 按实际 `rows.length` 推进 `skip` |
| 行中没有 `code` | 请求字段中没有包含 `code` | 把 `code` 加入 `fields` |
| 字段较多时返回不完整 | 单页数据过大或字段组合不稳定 | 减少字段，或把 `count` 调为 `500`、`200` |

## 7. 完整分页程序（Python）

下面的程序读取整个沪深京股票池，保留代码、名称和最新价，并按代码去重。它可以直接保存为 `read_d4.py` 运行。

```python
from __future__ import annotations

import requests


BASE_URL = "http://127.0.0.1:8080/d4/l1/instrument_list"


def read_universe(universe: str, page_size: int = 1000) -> list[dict]:
    rows_by_code: dict[str, dict] = {}
    skip = 0
    total = None

    while True:
        params = {
            "universe": universe,
            "skip": skip,
            "count": page_size,
            "fields": "code,name,price",
        }

        response = requests.get(BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        page = response.json()

        if page.get("error"):
            raise RuntimeError(f"D4 返回错误: {page['error']}")

        page_rows = page.get("rows")
        if not isinstance(page_rows, list):
            raise RuntimeError(f"D4 返回缺少 rows: {page}")

        if total is None:
            total = int(page.get("total", 0))

        for row in page_rows:
            code = row.get("code")
            if code:
                rows_by_code[code] = row

        if not page_rows:
            break

        skip += len(page_rows)
        if total is not None and skip >= total:
            break

    return list(rows_by_code.values())


if __name__ == "__main__":
    rows = read_universe("cn_hsj_stock")
    print(f"读取完成: {len(rows)} 条")
    for row in rows[:5]:
        print(row)
```

### 改读其他品种

只需要替换最后一段的名称：

```python
rows = read_universe("cn_option")
```

常用名称包括：

```text
cn_hsj_stock   沪深京股票
cn_fund        基金混合集合
cn_sh_bond     上海债券
cn_sz_bond     深圳债券
cn_option      期权合并集合
```

### 字段较多时

不要把全部字段一次性加入分页程序。先用下面的稳定组合确认流程，再逐步增加字段：

```python
"fields": "code,name,price,change_pct,volume,amount_wan"
```

如果响应不完整：

```python
rows = read_universe("cn_hsj_stock", page_size=500)
```

## 8. JavaScript 示例

浏览器或 Node.js 18+ 可以使用 `fetch`：

```javascript
const url = new URL("http://127.0.0.1:8080/d4/l1/instrument_list");
url.search = new URLSearchParams({
  universe: "cn_hsj_stock",
  skip: "0",
  count: "3",
  fields: "code,name,price",
});

const response = await fetch(url);
if (!response.ok) {
  throw new Error(`HTTP ${response.status}`);
}

const page = await response.json();
if (page.error) {
  throw new Error(page.error);
}

console.log("总数:", page.total);
for (const row of page.rows) {
  console.log(row.code, row.name, row.price);
}
```

## 9. 用户侧 Python GUI

示例合集提供了一个只读桌面展示程序：

```text
d4_gui.py
```

它使用 Python 自带的 Tkinter，不需要安装第三方包。打开 PowerShell，在示例文件所在目录运行：

```powershell
python d4_gui.py
```

如果本地端口不是 `8080`：

```powershell
python d4_gui.py --base-url http://127.0.0.1:你的端口
```

GUI 提供：

- 品种池下拉选择；
- “简洁字段组”“行情摘要”“股本 / 市值”“盘口五档”“资金 / 财务”“全部已知字段”等快捷按钮，以及“股票详情（推荐）”“最小稳定字段”“股票扩展信息”“期权详情”字段预设；也可以直接编辑字段；
- “全部已知字段”会把当前已验证的 103 个字段映射一次性放入列表，自动把每页条数调为 `100`，表格支持横向滚动；不同品种没有数据的字段会显示为空；
- 查询当前页、上一页、下一页；
- “读取全部”自动分页并按代码去重；
- 顶部显示品种总数、当前页范围和已展示数量；
- 独立的“K 线分析”工作区提供 K 线列表、周期、复权和数量选择，并绘制小型 K 线图；
- 选择列表中的品种会自动带入代码，双击品种行会切换到“K 线分析”并查询，期权合约同样适用；
- 涨跌幅为正、负、零的行分别使用不同颜色提示；
- 后台线程请求，窗口不会因为网络等待而卡住；
- 错误提示、读取进度和当前返回数量。

第一次使用建议保持默认值：`cn_hsj_stock`、字段预设“股票详情（推荐）”、每页 `300` 条。该预设包含代码、名称、价格变化、开高低、成交量额、换手率、量比、买卖一档、估值、股本、市值和行业等常用信息，共 24 个字段。

如果只需要快速浏览代码和价格，可点击“简洁字段组”或切换到“最小稳定字段”，再把每页条数改为 `1000`；如果选择“股票扩展信息”，建议把每页条数调小到 `200` 或 `300`。字段越多，单页应越保守。

## 10. 最小可用规则

如果你只想稳定地读取全市场股票代码，使用下面的请求即可：

```text
GET /d4/l1/instrument_list?universe=cn_hsj_stock&skip=0&count=1000&fields=code,name,price
```

记住四点：

1. `universe` 决定读取哪一类品种；
2. `fields` 决定每行返回哪些键；
3. `skip` 按实际返回行数递增，不要盲目按固定值递增；
4. 先检查 `error`，再使用 `rows`。

## 获取客户端

本文档描述的是本机运行的**达塔接口**客户端。安装包不随文档分发，请到官网下载：

**<https://datas.lovestoblog.com/>**

官网提供 Windows、macOS（Apple Silicon / Intel）、Linux 以及无桌面环境的
服务器版安装包。
