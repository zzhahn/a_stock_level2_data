# D6 市场数据接口

## 概述

D6 是一套面向程序调用的股票行情数据接口。客户只需要连接本地数据服务，就可以用统一的 HTTP 和 WebSocket 方式获取股票行情、K 线、资金流向、涨跌排行、板块数据、公告研报、融资融券以及实时推送等数据。

如果你是第一次使用，可以按下面的顺序理解：

- HTTP 接口适合查询一次性数据，使用 GET 查询参数或 POST JSON 请求体。
- WebSocket 适合持续接收实时行情，连接后发送 JSON 订阅消息。
- 调用方不需要处理复杂鉴权、签名或数据服务地址，只面向本地 D6 接口编程。
- 本文每个接口都给出了用途、参数含义、可复制请求和响应数据位置，照着示例即可开始开发。

常用入口是：

```text
HTTP： http://127.0.0.1:8080/d6/market/v1
WS：   ws://127.0.0.1:8080/d6/market/ws/quote
```

> 本文只描述 D6 对外提供的接口，不要求调用方了解数据服务的具体来源。
>
> 版本：2026-08-05　|　HTTP 接口：56 个　|　WebSocket 通道：1 个

## 1. 快速开始

### 1.1 本地地址

默认代理地址为：

```text
http://127.0.0.1:8080
```

所有 HTTP 行情接口都使用下面的前缀：

```text
http://127.0.0.1:8080/d6/market/v1
```

例如，查询股票行情排序：

```bash
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/quote/stocks/rank?en_hq_type_code=XSHG.ESA%2CXSHE.ESA%2CXSHG.KSH&sort_field_name=px_change_rate&sort_type=1&pageNo=1&pageSize=20"
```

### 1.2 调用前提

- d6 产品需要已经授权。未授权时，目录和参数说明仍可查看，但真正请求数据会返回 HTTP `403`。
- 调用方不需要自行计算签名，也不需要在请求中填写 Token。代理会自动完成必要的请求处理。
- GET 接口使用 URL 查询参数；POST 接口使用 `application/json` 请求体。
- 返回内容为 JSON。除本地错误外，数据字段保持接口原有的大小写和嵌套结构，不要依赖示例以外不存在的字段。
- 交易日、行情时段和标的是否有数据，取决于实际市场状态；盘前、午间、盘后可能返回空数组或空数据。

### 1.3 目录与 OpenAPI

以下两个地址不需要 d6 授权，可用于程序启动时读取接口目录：

```text
GET http://127.0.0.1:9527/api/catalog
GET http://127.0.0.1:8080/d6/market/openapi.json
```

其中 `/api/catalog` 是管理端提供的统一目录，`legacy` 节点包含 d1-d4 与实时通道，`market` 节点包含 d6 行情 HTTP/WS 方法。8080 只负责实际行情请求和 WebSocket 连接，不再作为页面目录来源。

目录中的字段说明和示例应优先于本文中的旧代码片段；本文是便于客户阅读和复制的固定版本。

### 1.4 POST 请求示例

#### K 线

```bash
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/kline" ^
  -X POST ^
  -H "Content-Type: application/json" ^
  --data-raw "{\"Market\":\"SZ\",\"Inst\":\"300052\",\"Period\":\"DAY\",\"ReqID\":1,\"servicetype\":\"KLINE\",\"StartID\":0,\"EndID\":-1}"
```

PowerShell、bash 或 Git Bash 可以直接使用更易读的单引号 JSON：

```bash
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/kline" -X POST \
  -H "Content-Type: application/json" \
  --data-raw '{"Market":"SZ","Inst":"300052","Period":"DAY","ReqID":1,"servicetype":"KLINE","StartID":0,"EndID":-1}'
```

上面这条是“最新 K 线快照”，当前返回一条是正常行为；`StartID` 和 `EndID` 是快照请求参数，不承担历史分页。要获取多条日/周/月 K 线或 1/5/15/30/60 分钟 K 线，请使用历史序列接口：

```bash
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/kline/history?market=SZ&inst=300052&period=MIN5&startTime=0&endTime=2524579200&limit=1200"
```

历史接口返回数组在 `KlineData[]`，`limit` 传 50 的正整数倍即可；常用周期为 `MIN1`、`MIN5`、`MIN15`、`MIN30`、`MIN60`、`DAY`、`WEEK`、`MONTH`。

#### 公告筛选

```bash
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/news/announcements/filter" -X POST \
  -H "Content-Type: application/json" \
  --data-raw '{"searchTp":0,"pageNo":1,"pageSize":20,"title":"","level1":"","level2":"","range":1,"dateTp":2,"sentiment":0,"optionStock":[]}'
```

### 1.5 零基础接入顺序

第一次接入建议严格按下面顺序做，先确认环境，再写业务逻辑：

1. 启动客户端，并确认代理端口是 `8080`。如果客户修改过端口，把下面所有示例中的 `8080` 换成实际端口。
2. 在客户端登录并开通 d6。目录可以在未授权时查看，但数据请求需要授权。
3. 用浏览器打开 `http://127.0.0.1:9527/api/catalog`。如果能看到包含 `legacy` 和 `market` 两个节点的 JSON，说明统一目录已加载；再用下面的行情请求测试 8080 执行链路。
4. 用下面这条最简单的 GET 请求测试链路：

   ```text
   http://127.0.0.1:8080/d6/market/v1/market/sentiment
   ```

5. 再测试一个 POST 请求，例如 K 线。POST 的 JSON 必须是合法 JSON，字段名大小写必须保持不变。
6. 确认能拿到 JSON 后，再把示例代码中的 `print` 或 `console.log` 换成自己的数据库、缓存或页面逻辑。

### 1.6 地址、路径和参数怎么拼

把接口地址拆成三部分就不会混淆：

```text
代理地址                 接口路径                         查询参数
http://127.0.0.1:8080 + /d6/market/v1/market/sentiment + （没有）
```

有查询参数时，参数放在 `?` 后面，多个参数用 `&` 连接：

```text
http://127.0.0.1:8080/d6/market/v1/capital/flow/history?symbol=000001&market=sh&limit=10
```

程序中不要手工拼接未编码的中文、空格、括号和逗号，应该使用语言自带的 URL 编码函数。Python 使用 `urllib.parse.urlencode`，JavaScript 使用 `URLSearchParams`。

目录中的“查询参数”都是可选参数。未填写的参数由接口使用默认口径；如果业务要明确传空字符串，也要把这个参数传出去，例如 `tradeDay=`。

### 1.7 参数类型和股票代码规则

HTTP 查询参数最终都是文本，下面的“数字”和“布尔值”在 URL 中都会变成字符；JSON 请求体才保留数字、布尔值和数组类型。

| 场景 | 正确示例 | 说明 |
|---|---|---|
| K 线市场 | `Market: "SZ"` | K 线请求体使用大写 `SZ`/`SH`。 |
| K 线证券代码 | `Inst: "300052"` | 只填代码，不带市场前缀。 |
| 普通查询市场 | `market=sh` | 多数 GET 接口使用小写 `sh`/`sz`/`all`。 |
| 基本面证券代码 | `symbol=sh000001` | 这个接口要求市场前缀和代码连在一起。 |
| WebSocket 个股 | `oldmarketcode: "sz", code: "300052"` | 市场和代码分开。 |
| 涨跌方向 | `upDownType=up` | `up` 表示上涨/涨停，`down` 表示下跌/跌停。 |
| 日期 | `2026-08-05` | 格式固定为 `YYYY-MM-DD`。 |
| 报告期 | `1785923618` | `reportDate` 是秒级时间戳，不是毫秒。 |
| JSON 布尔值 | `true` | 不要写成字符串 `"true"`。 |
| JSON 数组 | `[]` 或 `["000001"]` | 不要把数组写成逗号分隔的普通字符串。 |

同一个含义在不同接口中可能有不同字段名和大小写。例如 `pageNo`、`pageNum`、`page` 不能互相替换，必须按对应接口的表格填写。

### 1.8 可直接运行的 Python 示例（零额外依赖）

下面的程序只使用 Python 标准库，不需要安装第三方包。保存为 `d6_demo.py` 后运行 `python d6_demo.py` 即可。

```python
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8080"


class ApiError(RuntimeError):
    def __init__(self, status, result):
        self.status = status
        self.result = result
        super().__init__(f"HTTP {status}：{result}")


def call_api(method, path, query=None, body=None, timeout=15):
    """调用 d6 HTTP 接口，返回已经解析的 Python 对象。"""
    url = BASE_URL.rstrip("/") + path
    if query:
        # None 表示不发送；空字符串会被保留为 key=。
        query = {key: value for key, value in query.items() if value is not None}
        if query:
            url += "?" + urlencode(query)

    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    request = Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            text = response.read().decode("utf-8")
    except HTTPError as error:
        # 403 等错误也可能带 JSON，先把响应读出来再判断。
        status = error.code
        text = error.read().decode("utf-8", errors="replace")
    except URLError as error:
        raise RuntimeError(f"无法连接 {BASE_URL}，请确认客户端和端口：{error}") from error

    try:
        result = json.loads(text) if text else None
    except json.JSONDecodeError as error:
        raise RuntimeError(f"接口返回的不是合法 JSON：{text[:200]}") from error

    if status == 403:
        raise ApiError(status, f"d6 未授权或已过期：{result}")
    if status >= 400:
        raise ApiError(status, result)
    return result


def main():
    # 示例 1：无参数 GET。
    sentiment = call_api("GET", "/d6/market/v1/market/sentiment")
    print("市场情绪：", json.dumps(sentiment, ensure_ascii=False, indent=2))

    # 示例 2：带查询参数 GET。
    ranking = call_api(
        "GET",
        "/d6/market/v1/quote/stocks/rank",
        query={
            "en_hq_type_code": "XSHG.ESA,XSHE.ESA,XSHG.KSH",
            "sort_field_name": "px_change_rate",
            "sort_type": "1",
            "pageNo": "1",
            "pageSize": "20",
        },
    )
    rows = (ranking.get("data") or {}).get("Stocks", [])
    print("行情排行条数：", len(rows))
    for row in rows[:3]:
        print(row)

    # 示例 3：POST JSON。
    kline = call_api(
        "POST",
        "/d6/market/v1/kline",
        body={
            "Market": "SZ",
            "Inst": "300052",
            "Period": "DAY",
            "ReqID": 1,
            "servicetype": "KLINE",
            "StartID": 0,
            "EndID": -1,
        },
    )
    bars = (kline.get("QuoteData") or {}).get("KlineData", [])
    print("K 线条数：", len(bars))
    if bars:
        print("最新一条 K 线：", bars[0])

    # 示例 4：历史分钟 K 线。limit 传正整数，数组在 KlineData。
    history = call_api(
        "GET",
        "/d6/market/v1/kline/history",
        query={
            "market": "SZ",
            "inst": "300052",
            "period": "MIN5",
            "startTime": 0,
            "endTime": 2524579200,
            "limit": 1200,
        },
    )
    history_bars = history.get("KlineData") or []
    print("历史分钟 K 线条数：", len(history_bars))
    if history_bars:
        print("第一条：", history_bars[0])
        print("最后一条：", history_bars[-1])


if __name__ == "__main__":
    main()
```

运行时最常见的结果：

- 正常：打印 JSON、排行条数或 K 线条数。
- `d6 未授权或已过期`：程序已经连到代理，但账号没有 d6 权限。
- `无法连接`：客户端未启动、端口不对，或代理服务尚未运行。
- K 线条数为 `0`：请求格式可能正确，但当前标的/周期暂无数据；先打印完整响应确认。

### 1.9 可直接运行的 JavaScript 示例

浏览器、Node.js 18+ 都可以使用下面的 HTTP 写法。Node.js 18+ 自带 `fetch`，不需要安装包。

```javascript
const BASE_URL = "http://127.0.0.1:8080";

async function callApi(method, path, query = {}, body = undefined) {
  const url = new URL(BASE_URL + path);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }

  const options = {
    method,
    headers: { Accept: "application/json" },
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  const text = await response.text();
  let result;
  try {
    result = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`返回内容不是 JSON：${text.slice(0, 200)}`);
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${JSON.stringify(result)}`);
  }
  return result;
}

async function main() {
  const result = await callApi(
    "GET",
    "/d6/market/v1/capital/flow/history",
    { symbol: "000001", market: "sh", limit: 10 },
  );
  console.log(result);

  const kline = await callApi("POST", "/d6/market/v1/kline", {}, {
    Market: "SZ",
    Inst: "300052",
    Period: "DAY",
    ReqID: 1,
    servicetype: "KLINE",
    StartID: 0,
    EndID: -1,
  });
  console.log(kline.QuoteData?.KlineData ?? []);

  const history = await callApi(
    "GET",
    "/d6/market/v1/kline/history",
    {
      market: "SZ",
      inst: "300052",
      period: "MIN5",
      startTime: 0,
      endTime: 2524579200,
      limit: 1200,
    },
  );
  console.log(history.KlineData ?? []);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
```

### 1.10 如何读取响应

普通 GET 接口通常这样读取：

```python
result = call_api("GET", "/d6/market/v1/market/sentiment")
status_code = result.get("code", result.get("Code"))
message = result.get("message", result.get("Message", result.get("msg", "")))
if status_code in (-1, "-1") or message:
    print("接口提示：", message or status_code)
data = result.get("data")
```

如果 `data` 是数组：

```python
for item in result.get("data") or []:
    print(item)
```

如果 `data` 是对象：

```python
data = result.get("data") or {}
rows = data.get("infos") or data.get("list") or []
```

不同接口的列表字段不统一，文档每个接口的“响应”一行会标出常见位置。常见列表位置如下：

| 接口类型 | 常见读取位置 |
|---|---|
| 连续涨跌停、涨跌停列表、涨跌排行 | `data.infos` |
| 龙虎榜、公告、业绩、融资融券部分接口 | `data.list` |
| 板块实时行情 | `data.plate` |
| 沪深股票行情排序 | `data.Stocks` |
| 研报列表 | `data.data` |
| K 线 | `QuoteData.KlineData` |
| 其他未列稳定字段的接口 | 先打印完整 `data`，再按实际 JSON 取值 |

字段缺失、数组为空或 `data=null` 不一定是错误，可能是当前时间没有数据。生产代码要使用 `.get()`、可选链或空值判断。

### 1.11 Windows 终端中文显示

接口响应是 UTF-8。如果程序拿到的 JSON 正确但 Windows 终端显示成乱码，通常是终端代码页问题，不是接口数据损坏。

命令提示符可先执行：

```bat
chcp 65001
```

PowerShell 可执行：

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONIOENCODING = "utf-8"
```

程序内部仍应明确按 UTF-8 解码；Python 示例中的 `decode("utf-8")` 不要改成 GBK。

## 2. 统一响应和错误

### 2.1 普通 HTTP 响应

大多数接口的响应外层为：

```json
{
  "code": 1,
  "message": "",
  "data": {}
}
```

上面只是普通接口的示意。实际接口的成功码并不统一，可能出现数字或字符串形式的 `0`、`1`、`200`、`0000`；有的无数据响应甚至只返回 `code/message`。因此不要在所有接口中写死 `code == 0` 才算成功：先判断 HTTP 状态，再查看 `message`、`data` 和本文标出的数据位置。

`data` 可能是对象、数组、`null` 或接口专用结构。部分错误响应使用 `msg/reason` 而不是 `message`，程序读取时应兼容这几个字段。

K 线接口使用专用外层：

```json
{
  "Code": 0,
  "Message": "",
  "ReqID": 1,
  "QuoteData": {
    "KlineData": []
  }
}
```

### 2.2 常见错误

| HTTP 状态 | 响应示例 | 含义 |
|---:|---|---|
| 200 | 业务 JSON | 代理已处理请求；仍需检查 JSON 中的 `code/message/data`，200 不代表一定有数据 |
| 403 | `{"code":-1,"message":"行情 API 产品未授权"}` | d6 尚未授权或授权已失效 |
| 404 | JSON 错误对象 | 路径或请求方法不在公开行情目录中 |
| 其他 4xx | 以实际响应为准 | 请求参数、请求方法或本地服务状态异常；不要只依赖状态码文字 |

无数据是正常情况的一种表现，例如：

```json
{"code":-1,"msg":"处理失败","reason":"no such data"}
```

另一个接口可能返回：

```json
{"code":"0004","message":"Not Fund Related Split or Envidends or ..."}
```

这类响应是“当前条件没有可返回数据”或接口专用业务提示，不要把它当成网络连接失败。生产程序应记录完整 JSON，并根据业务决定显示“暂无数据”还是提示用户调整日期、市场或标的。

## 3. WebSocket 实时行情

### 3.1 连接地址

```text
ws://127.0.0.1:8080/d6/market/ws/quote
```

如果代理通过 HTTPS/WSS 方式对外提供服务，将地址中的 `ws://` 换成 `wss://`。连接成功后，发送 JSON 消息；每条消息都使用 `Header` 和 `Body` 两层结构。

连接示例（JavaScript）：

```javascript
const ws = new WebSocket("ws://127.0.0.1:8080/d6/market/ws/quote");

ws.onopen = () => {
  ws.send(JSON.stringify({
    Header: { No: 0, MsgType: 201 },
    Body: {
      key: { oldmarketcode: "sz", code: "300052" },
      level: 2
    }
  }));
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log(message);
};
```

### 3.2 市场编号

| `marketid` | 市场 |
|---:|---|
| `1` | 上海 |
| `0` | 深圳 |
| `118` | 港股 |
| `156` | 纳斯达克 |
| `158` | 美股其他市场 |

个股订阅中的 `oldmarketcode` 使用 `sh` 或 `sz`；`code` 只填写证券代码，不带市场前缀。

### 3.3 消息类型

#### 2001：指数/列表实时行情

适合一次订阅多个指数或证券，并接收列表数据。

```json
{
  "Header": { "No": 0, "MsgType": 2001 },
  "Body": {
    "info": {
      "paramtype": 2,
      "stockid": [
        { "marketid": 1, "code": "000001" },
        { "marketid": 0, "code": "399001" }
      ]
    },
    "sortfield": 0,
    "order": true,
    "end": 3,
    "respfield": [10, 11, 96, 97, 98]
  }
}
```

常见响应位置：`Body.info`、`Body.totalnum`、`Body.data[].base`、`Body.data[].newprice`、`Body.data[].yclose`、`Body.data[].szjs`、`Body.data[].xdjs`、`Body.data[].ppjs`。

#### 201：个股实时快照/订阅

```json
{
  "Header": { "No": 0, "MsgType": 201 },
  "Body": {
    "key": { "oldmarketcode": "sz", "code": "300052" },
    "level": 2
  }
}
```

常见响应位置：`Body.key`、`Body.hq`；`hq` 中通常包括 `newprice`、`yclose`、`open`、`high`、`low`、`mmp`、`amount`、`volume`、`zhangdief` 等字段。

#### 501：个股盘口推送

```json
{
  "Header": { "No": 9, "MsgType": 501 },
  "Body": {
    "key": { "oldmarketcode": "sz", "code": "300052" },
    "pushflag": true,
    "timestamp": true,
    "nopushjh": true
  }
}
```

常见响应位置：`Body.key`、`Body.hq`、`Body.mmp`，以及买卖五档、涨跌停等盘口字段。

#### 504：个股扩展行情推送

```json
{
  "Header": { "No": 10, "MsgType": 504 },
  "Body": {
    "key": { "oldmarketcode": "sz", "code": "300052" },
    "pushflag": true,
    "timestamp": true
  }
}
```

常见响应位置：`Body.key` 及扩展行情字段。实时通道未授权时也可以在面板中查看和复制示例，但真正连接会被拒绝。

### 3.4 Python WebSocket 示例

Python 需要先安装一个 WebSocket 客户端库：

```bash
python -m pip install websockets
```

下面的程序连接后订阅一只股票的实时快照，并持续打印收到的消息。关闭程序时按 `Ctrl+C`。

```python
import asyncio
import json
import websockets

WS_URL = "ws://127.0.0.1:8080/d6/market/ws/quote"


async def main():
    async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws:
        command = {
            "Header": {"No": 0, "MsgType": 201},
            "Body": {
                "key": {"oldmarketcode": "sz", "code": "300052"},
                "level": 2,
            },
        }
        await ws.send(json.dumps(command, ensure_ascii=False))
        async for text in ws:
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                print("收到非 JSON 消息：", text)
                continue
            print(json.dumps(message, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("已停止")
```

生产程序需要在连接断开后重新连接并重新发送订阅命令。建议等待 1 秒、2 秒、4 秒逐步重试，并设置最大等待时间；不要在连接失败时高速死循环。

### 3.5 WebSocket 未授权和断线怎么判断

- `onopen` 或 `async with connect` 成功，只表示本地 WebSocket 握手成功。
- 收到 `code=-1` 或连接马上关闭时，打印完整消息和关闭原因。
- d6 未授权时，目录和示例仍可查看，但 WebSocket 真正连接会被拒绝。
- 网络断开后，重新建立连接时要重新发送 `Header/Body` 订阅消息；服务器不会替客户保存断线前的订阅状态。

## 4. HTTP 接口索引

| 编号 | 分类 | 方法 | 路径 | 用途 |
|---:|---|:---:|---|---|
| 01 | K 线 | POST | `/d6/market/v1/kline` | 个股日/周/月 K 线 |
| 02 | 技术分析 | GET | `/d6/market/v1/analysis/technical` | 指数/个股技术分析 |
| 03 | 龙虎榜 | GET | `/d6/market/v1/capital/dragon-tiger/trend` | 龙虎榜趋势线 |
| 04 | 龙虎榜 | GET | `/d6/market/v1/capital/dragon-tiger/sales-rank` | 席位销售排行 |
| 05 | 龙虎榜 | GET | `/d6/market/v1/capital/dragon-tiger/stock-flow` | 个股资金排行 |
| 06 | 资金流向 | GET | `/d6/market/v1/capital/flow/history` | 个股历史净流入 |
| 07 | 资金流向 | GET | `/d6/market/v1/capital/flow/snapshot` | 个股实时资金快照 |
| 08 | 资金流向 | GET | `/d6/market/v1/capital/flow/index-minute` | 指数分时资金流 |
| 09 | 沪深港通 | GET | `/d6/market/v1/connect/active-rank` | 活跃股票排行 |
| 10 | 沪深港通 | GET | `/d6/market/v1/connect/flow-minute` | 资金分时概况 |
| 11 | 沪深港通 | GET | `/d6/market/v1/connect/flow-history` | 周期资金历史 |
| 12 | 沪深港通 | GET | `/d6/market/v1/connect/net-flow-minute` | 净流入分时 |
| 13 | 大宗交易 | GET | `/d6/market/v1/trade/block-list` | 大宗交易列表 |
| 14 | 资金流向 | GET | `/d6/market/v1/capital/flow/period-rank` | 周期资金排行 |
| 15 | 个股诊断 | GET | `/d6/market/v1/stock/diagnosis-hot` | 个股诊断热搜 |
| 16 | 涨跌停 | GET | `/d6/market/v1/limit/continuous` | 连续涨跌停股票 |
| 17 | 市场情绪 | GET | `/d6/market/v1/market/sentiment` | 市场情绪指标 |
| 18 | 涨跌停 | GET | `/d6/market/v1/stock/secondary-anomaly` | 二次异动股票 |
| 19 | 涨跌统计 | GET | `/d6/market/v1/limit/distribution` | 全市场涨跌分布 |
| 20 | 涨跌统计 | GET | `/d6/market/v1/limit/monitor` | 涨跌停监控 |
| 21 | 涨跌统计 | GET | `/d6/market/v1/limit/trend-minute` | 涨跌停趋势分时 |
| 22 | 盘口资金 | GET | `/d6/market/v1/capital/scramble-rank` | 盘口抢筹排行 |
| 23 | 涨跌停 | GET | `/d6/market/v1/limit/list` | 涨停/跌停列表 |
| 24 | 涨跌排行 | GET | `/d6/market/v1/rank/change` | 股票涨跌幅排行 |
| 25 | 涨跌排行 | GET | `/d6/market/v1/rank/stocks` | 沪深京 A 股排行 |
| 26 | 研报公告 | GET | `/d6/market/v1/news/research-reports` | 上市公司研报 |
| 27 | 研报公告 | POST | `/d6/market/v1/news/announcements/filter` | 公告筛选 |
| 28 | 新股数据 | GET | `/d6/market/v1/news/ipo` | 新股申购发行 |
| 29 | 业绩数据 | GET | `/d6/market/v1/news/performance/announcements` | 业绩公告 |
| 30 | 业绩数据 | GET | `/d6/market/v1/news/performance/summary` | 业绩预告汇总 |
| 31 | 搜索 | GET | `/d6/market/v1/search/hot-stocks` | 热门股票搜索 |
| 32 | 板块异动 | GET | `/d6/market/v1/sector/anomaly/current` | 板块异动信号 |
| 33 | 板块行情 | GET | `/d6/market/v1/sector/capital-rank` | 行业板块资金排行 |
| 34 | 板块行情 | GET | `/d6/market/v1/sector/leader-rank` | 板块涨跌和龙头排行 |
| 35 | 板块行情 | GET | `/d6/market/v1/sector/change-rank` | 行业/概念涨跌排行 |
| 36 | 个股异动 | POST | `/d6/market/v1/stock/anomalies` | 个股异动监控 |
| 37 | 指数行情 | GET | `/d6/market/v1/quote/overview/change` | 沪深涨跌幅概览 |
| 38 | 指数行情 | GET | `/d6/market/v1/quote/index/major` | 主要指数行情 |
| 39 | 指数行情 | GET | `/d6/market/v1/quote/index/capital` | 指数资金概览 |
| 40 | 个股行情 | GET | `/d6/market/v1/stock/fundamentals` | 基本面与盘口摘要 |
| 41 | 跨市场行情 | GET | `/d6/market/v1/quote/cross-market/hk-a` | 港股映射沪深行情 |
| 42 | 市场行情 | GET | `/d6/market/v1/quote/market/overview` | 市场概览资金快照 |
| 43 | 跨市场行情 | GET | `/d6/market/v1/quote/cross-market/ah` | AH 股比价列表 |
| 44 | 市场行情 | GET | `/d6/market/v1/quote/stocks/rank` | 沪深股票行情排序 |
| 45 | 交易日历 | GET | `/d6/market/v1/market/trading-days` | 交易日历 |
| 46 | 板块行情 | GET | `/d6/market/v1/sector/quote` | 板块实时行情 |
| 47 | 板块行情 | GET | `/d6/market/v1/sector/style` | 风格板块列表 |
| 48 | 融资融券 | GET | `/d6/market/v1/margin/summary` | 融资融券汇总 |
| 49 | 融资融券 | GET | `/d6/market/v1/margin/top-five` | 融资融券前五名 |
| 50 | 融资融券 | GET | `/d6/market/v1/margin/difference` | 融资融券差额曲线 |
| 51 | 融资融券 | GET | `/d6/market/v1/margin/stock/detail` | 个股融资融券明细 |
| 52 | 融资融券 | GET | `/d6/market/v1/margin/stock/history` | 个股融资融券历史 |
| 53 | 融资融券 | GET | `/d6/market/v1/margin/curve` | 融资融券分时曲线 |
| 54 | 个股行情 | GET | `/d6/market/v1/stock/adjustment` | 个股复权基础信息 |
| 55 | K 线 | GET | `/d6/market/v1/kline/history` | 个股历史 K 线；支持分钟、日、周、月周期 |
| 56 | 筹码分析 | GET | `/d6/market/v1/stock/chip/distribution` | 个股按交易日筹码分布 |

## 4.1 56 个接口的可复制请求

下面的 GET 命令可以直接复制到 Windows PowerShell、Windows 命令提示符或 bash。Windows 下请写 `curl.exe`，不要省略 `.exe`，否则 PowerShell 可能把 `curl` 解释成另一个命令。

这些是“先跑通”的默认请求。需要筛选时，再按照第 5 节的参数表修改；URL 中的 `&` 不能删除。

```text
# 01 个股 K 线（POST）
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/kline" -X POST -H "Content-Type: application/json" --data-raw "{\"Market\":\"SZ\",\"Inst\":\"300052\",\"Period\":\"DAY\",\"ReqID\":1,\"servicetype\":\"KLINE\",\"StartID\":0,\"EndID\":-1}"

# 02 技术分析
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/analysis/technical"
# 03 龙虎榜趋势线
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/dragon-tiger/trend"
# 04 龙虎榜席位销售排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/dragon-tiger/sales-rank?category=gang&tradeDay=&sortField=netSum&sortType=down&pageNum=1&pageSize=5&stockSize=-1"
# 05 龙虎榜个股资金排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/dragon-tiger/stock-flow?tradeDay=&sortField=netSum&sortType=down&pageNum=1&pageSize=5"
# 06 个股历史净流入
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/flow/history?symbol=111111&market=sh&limit=4"
# 07 个股实时资金流快照
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/flow/snapshot?symbol=111111&market=sh"
# 08 指数分时资金流
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/flow/index-minute?code=000000&market=all"
# 09 北向活跃股票排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/connect/active-rank?hsgtType=1"
# 10 北向资金分时概况
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/connect/flow-minute"
# 11 北向资金周期历史
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/connect/flow-history?period=day&offset=20"
# 12 沪深港通净流入分时
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/connect/net-flow-minute"
# 13 A 股大宗交易列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/trade/block-list?pageNo=1&pageSize=20&sort=-tradingDay"
# 14 板块周期资金排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/flow/period-rank?code=HSA&period=one&sortField=mainNetTurnover&sortType=down&pageNo=1&pageSize=3"
# 15 个股诊断热搜
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/stock/diagnosis-hot"
# 16 连续涨跌停股票
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/limit/continuous?listedSector=0&STType=0&upDownType=up&tradingType=0&sortField=countContLimit&pageNum=1&pageSize=10"
# 17 市场情绪指标
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/market/sentiment"
# 18 二次异动股票列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/stock/secondary-anomaly?listedSector=0&STType=0&upDownType=up&tradingType=0&pageNum=1&pageSize=10"
# 19 全市场涨跌分布
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/limit/distribution"
# 20 涨跌停监控统计
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/limit/monitor?STType=0&type=0"
# 21 涨跌停趋势分时
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/limit/trend-minute"
# 22 盘口抢筹排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/capital/scramble-rank?sortField=amount&sortType=desc&limit=5"
# 23 涨停/跌停股票列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/limit/list?listedSector=0&STType=0&upDownType=up&tradingType=0&sortField=upType&pageNum=1&pageSize=10"
# 24 股票涨跌幅排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/rank/change?listedSector=0&STType=0&upDownType=up&tradingType=0&sortField=upType&pageNum=1&pageSize=10"
# 25 沪深京 A 股行情排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/rank/stocks?listedSector=0&pageNum=1&pageSize=20&sortField=pxChangeRate&sortType=0"
# 26 上市公司研报列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/news/research-reports?from=2026-02-06&to=2026-08-05&pageNo=0&pageSize=50"
# 27 公告筛选（POST）
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/news/announcements/filter" -X POST -H "Content-Type: application/json" --data-raw "{\"searchTp\":0,\"pageNo\":1,\"pageSize\":20,\"title\":\"\",\"level1\":\"\",\"level2\":\"\",\"range\":1,\"dateTp\":2,\"sentiment\":0,\"optionStock\":[]}"
# 28 新股申购发行列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/news/ipo?listedSector=0&pageNum=1&pageSize=10&sortField=onlineStartDate&sortType=0"
# 29 业绩公告列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/news/performance/announcements?pageNo=1&pageSize=10&sector=0&sort=-publishTime&reportDate=1785923618"
# 30 业绩预告汇总
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/news/performance/summary?sector=0"
# 31 热门股票搜索
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/search/hot-stocks"
# 32 板块当前异动信号
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/sector/anomaly/current?page=1&pageSize=-1"
# 33 行业板块资金排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/sector/capital-rank?count=5&plateTypeCode=hy"
# 34 板块涨跌及龙头排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/sector/leader-rank?count=8"
# 35 行业/概念板块涨跌排行
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/sector/change-rank?count=5&plateTypeCode=hy"
# 36 个股异动监控（POST）
curl.exe -i "http://127.0.0.1:8080/d6/market/v1/stock/anomalies" -X POST -H "Content-Type: application/json" --data-raw "{\"limit\":10}"
# 37 沪深涨跌幅概览
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/overview/change"
# 38 沪深主要指数行情
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/index/major"
# 39 沪深指数资金概览
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/index/capital"
# 40 A 股基本面与盘口摘要
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/stock/fundamentals?symbol=sh000001"
# 41 港股映射沪深行情
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/cross-market/hk-a?Classes=HK2SH&Type=Business_balance"
# 42 市场概览资金快照
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/market/overview?MarketType=%28MarketType%3D1%29"
# 43 AH 股比价列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/cross-market/ah?pageNo=0&pageSize=50&types=Ratio&sort=DESC"
# 44 沪深股票行情排序
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/quote/stocks/rank?en_hq_type_code=XSHG.ESA%2CXSHE.ESA%2CXSHG.KSH&sort_field_name=px_change_rate&sort_type=1&pageNo=1&pageSize=20"
# 45 交易日历
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/market/trading-days?limit=366&market=sh"
# 46 板块实时行情列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/sector/quote?hqTypeCode=HY&sortFlag=true&sortFields=pxChangeRate&pageNum=1&pageSize=10"
# 47 风格板块列表
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/sector/style"
# 48 融资融券汇总
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/margin/summary?market=&date=2026-08-05"
# 49 融资融券前五名
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/margin/top-five?date=2026-08-05&market="
# 50 融资融券差额曲线
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/margin/difference?market=&date=2026-08-05"
# 51 个股融资融券明细
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/margin/stock/detail?pageSize=100&date=2026-08-05&market="
# 52 个股融资融券历史
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/margin/stock/history?market="
# 53 融资融券分时曲线
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/margin/curve?market=sh"
# 54 个股复权基础信息
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/stock/adjustment?market=sh&instrucode=000001"
# 55 个股历史 K 线（5 分钟）
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/kline/history?market=SZ&inst=300052&period=MIN5&startTime=0&endTime=2524579200&limit=1200"
# 56 个股筹码分布（近 100 天）
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/stock/chip/distribution?symbol=001202&market=sz&powerType=1"
```

## 4.2 响应数据应该从哪里取

下面是每个接口最常见的取数位置。`result` 表示完整 JSON；普通接口先取 `result.data`，K 线例外。接口无数据时，数组可能为空，或者只返回 `code/message`。

| 编号 | 成功数据位置 | 典型数据形状 |
|---:|---|---|
| 01 | `result.QuoteData.KlineData` | K 线数组 |
| 02 | `result.data` | 技术分析对象 |
| 03 | `result.data[]` | 龙虎榜趋势数组 |
| 04 | `result.data.list` | 席位排行数组 |
| 05 | `result.data.list` | 个股资金排行数组 |
| 06 | `result.data[]` | 历史资金数组 |
| 07 | `result.data` | 实时资金对象 |
| 08 | `result.data[]` | 指数分时数组 |
| 09 | `result.data.info` | 活跃股票数组 |
| 10 | `result.data[]` | 资金分时数组 |
| 11 | `result.data.list` | 周期历史数组 |
| 12 | `result.data[]` | 净流入分时数组 |
| 13 | `result.data.list` | 大宗交易数组 |
| 14 | `result.data.list` | 周期排行数组 |
| 15 | `result.data[]` | 热搜股票数组 |
| 16 | `result.data.infos` | 连续涨跌停数组 |
| 17 | `result.data` | 市场情绪对象 |
| 18 | `result.data.infos` | 二次异动数组 |
| 19 | `result.data` | 涨跌分布对象 |
| 20 | `result.data[]` | 涨跌停监控数组 |
| 21 | `result.data[]` | 涨跌停趋势数组 |
| 22 | `result.data.list` | 抢筹排行数组 |
| 23 | `result.data.infos` | 涨停/跌停数组 |
| 24 | `result.data.infos` | 涨跌幅排行数组 |
| 25 | `result.data.infos` | 股票排行数组 |
| 26 | `result.data.data` | 研报数组 |
| 27 | `result.data.list` | 公告数组 |
| 28 | `result.data.ipoList` | 新股数组 |
| 29 | `result.data.list` | 业绩公告数组 |
| 30 | `result.data[]` | 业绩汇总数组 |
| 31 | `result.data[]` | 热门股票数组 |
| 32 | `result.data[]` | 板块异动数组 |
| 33 | `result.data.upList`、`downList` | 上涨/下跌板块数组 |
| 34 | `result.data.upList`、`downList` | 上涨/下跌板块数组 |
| 35 | `result.data.upList`、`downList` | 上涨/下跌板块数组 |
| 36 | `result.data[]` | 个股异动数组 |
| 37 | `result.data` | 按市场键分组的指数概览对象 |
| 38 | `result.data.updownspeedMAIN.*` | 各市场指数数组 |
| 39 | `result.data.NetbiginMAIN.*` | 各市场资金数组 |
| 40 | `result.data` | 基本面对象 |
| 41 | `result.data[]` | 跨市场行情数组 |
| 42 | `result.data[]` | 市场概览数组 |
| 43 | `result.data.ParityRatioahs` | AH 比价数组 |
| 44 | `result.data.Stocks` | 股票行情数组 |
| 45 | `result.data[]` | 交易日时间戳数组 |
| 46 | `result.data.plate` | 板块行情数组 |
| 47 | `result.data[]` | 风格板块数组 |
| 48 | `result.data` | 融资融券汇总对象 |
| 49 | `result.data[]` | 融资融券前五名数组；无数据时可能返回错误提示 |
| 50 | `result.data[]` | 融资融券差额数组 |
| 51 | `result.data[]` | 个股融资融券明细；无数据时可能为 `null` |
| 52 | `result.data[]` | 个股融资融券历史数组 |
| 53 | `result.data[]` | 融资融券分时数组 |
| 54 | `result.data` | 复权基础对象；无数据时可能只有提示字段 |
| 55 | `result.KlineData` | 历史 K 线数组；每项是一根 K 线 |
| 56 | `result.data[]` | 按交易日排列的筹码数组；摘要在 `chipSummary`，价格分布在 `items` |

例如 44 号接口的取值代码是：

```python
result = call_api(
    "GET",
    "/d6/market/v1/quote/stocks/rank",
    query={"pageNo": 1, "pageSize": 20},
)
stocks = (result.get("data") or {}).get("Stocks") or []
for stock in stocks:
    print(stock)
```

例如 33 号接口同时读取上涨和下跌板块：

```python
data = result.get("data") or {}
up_list = data.get("upList") or []
down_list = data.get("downList") or []
```

## 4.3 常见返回字段怎么理解

下面是跨接口经常出现的字段的“通常含义”。它不是强制 schema；同名字段在不同数据集中的精度、单位和空值规则仍应以实际 JSON 为准。

| 字段 | 通常含义 | 编程注意 |
|---|---|---|
| `symbol` / `Symbol` | 证券或标的代码 | 注意有的接口带市场前缀，有的接口不带。 |
| `market` / `Market` | 市场标识 | 可能是 `sh`/`sz`，也可能是市场名称或编号。 |
| `name` / `Name` | 股票、板块或标的名称 | 可能为空，不要作为唯一主键。 |
| `lastPx` / `Last_px` | 最新价 | 先判断是否为 `null` 或空字符串。 |
| `pxChange` | 价格变动值 | 与涨跌幅不是同一个字段。 |
| `pxChangeRate` / `Px_change_rate` | 涨跌幅 | 单位和是否已经乘以 100 以实际返回为准。 |
| `open` / `Open`、`high` / `High`、`low` / `Low`、`close` / `Close` | 开高低收 | K 线字段通常首字母大写，其他接口可能小写。 |
| `Volume` / `volume` | 成交量 | 不同接口单位可能不同，计算前请保留原始值。 |
| `Amount` / `amount` | 成交额 | 不同接口单位可能不同。 |
| `tradeDay` / `TradingDay` | 交易日 | 可能是日期字符串，也可能是 Unix 秒级时间戳。 |
| `Time` / `minTime` / `time` | 时间或分钟时间 | K 线和实时序列常使用秒级时间戳或时间文本。 |
| `count` / `total` | 数量或总条数 | 有些分页接口只返回其中一个。 |
| `list` / `infos` / `data` | 列表容器 | 这三个名字不能互换，以 4.2 表格为准。 |
| `upList` / `downList` | 上涨/下跌列表 | 主要出现在板块排行。 |
| `ReqID` | 请求编号 | K 线响应会原样回显，便于异步匹配。 |
| `code` / `Code` | 业务状态或结果编码 | 大小写和成功值并不统一，不能只判断等于 0。 |
| `message` / `Message` / `msg` / `reason` | 接口提示或错误原因 | 记录完整内容，尤其是无数据时。 |

时间戳转换示例：

```python
from datetime import datetime


def timestamp_to_text(value):
    if value is None:
        return ""
    value = int(value)
    # 本文接口中的交易时间通常是秒；如果自己的数据明显超过 10^12，才按毫秒处理。
    if value > 10**12:
        value //= 1000
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


print(timestamp_to_text(1785859200))
```

## 5. HTTP 接口详情

下面的参数均为可选参数；未列参数的接口直接请求路径即可。表格中的“默认/示例”是面板当前采用的可用示例，程序接入时可以按业务需要替换。

### 01. 个股 K 线数据

`POST /d6/market/v1/kline`　—　个股最新 K 线快照；当前接口按设计返回最新一条。需要多条历史 K 线或分钟 K 线，请使用下方 55 号接口。

请求体字段：

| 字段 | 默认/示例 | 说明 |
|---|---|---|
| `Market` | `SZ` | 市场代码：`SZ` 深圳，`SH` 上海。 |
| `Inst` | `300052` | 证券代码，不带市场前缀。 |
| `Period` | `DAY` | 最新快照周期：`DAY` 日线、`WEEK` 周线、`MONTH` 月线。分钟周期请使用历史接口。 |
| `ReqID` | `1` | 调用方请求编号，原样回显，便于匹配请求。 |
| `servicetype` | `KLINE` | 服务类型，K 线使用 `KLINE`。 |
| `StartID` | `0` | 快照参数，通常保持 `0`；不用于历史分页。 |
| `EndID` | `-1` | 快照参数，通常保持 `-1`；不用于历史分页。 |

请求示例：

```json
{"Market":"SZ","Inst":"300052","Period":"DAY","ReqID":1,"servicetype":"KLINE","StartID":0,"EndID":-1}
```

响应示例：

```json
{
  "Code": "0000",
  "Message": "ok",
  "ReqID": 1,
  "QuoteData": {
    "KlineData": [
      {
        "TradingDay": 1785859200,
        "Time": 1785859200,
        "Open": 11.74,
        "High": 12.18,
        "Low": 11.62,
        "Close": 11.82,
        "Volume": 50122650,
        "Amount": 592703844
      }
    ]
  }
}
```

响应外层为 `Code`、`Message`、`ReqID`、`QuoteData`；K 线数组位于 `QuoteData.KlineData[]`，当前通常只有一条最新记录。常见字段为 `TradingDay`、`Time`、`Open`、`High`、`Low`、`Close`、`Volume`、`Amount`；返回中还可能出现 `TickCount`、`AfterTradeVolume`、`AfterTradeAmount`、`PreClose`、`SettlementPrice` 等扩展字段。

### 02. 指数/个股技术分析

`GET /d6/market/v1/analysis/technical`　—　指数或个股技术分析数据。

参数：无固定参数。

响应：`code,message,data`；`data` 通常为对象，常见字段为 `card_list`、`dataExt`、`ext`、`market`、`name`、`noData`、`picExt`、`reply`、`replyList`、`symbol`。

### 03. 龙虎榜趋势线

`GET /d6/market/v1/capital/dragon-tiger/trend`　—　龙虎榜趋势线数据。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，常见字段为 `buySum`、`netSum`、`onNum`、`onNumIn`、`onNumOut`、`saleSum`、`tradingDay`。

### 04. 龙虎榜席位销售排行

`GET /d6/market/v1/capital/dragon-tiger/sales-rank`　—　龙虎榜营业部或席位销售排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `category` | `gang` | 分类；`gang` 表示席位/营业部排行口径。 |
| `tradeDay` | 空 | 交易日；空字符串使用最新可用交易日。 |
| `sortField` | `netSum` | 排序字段；`netSum` 表示净额。 |
| `sortType` | `down` | 排序方向；`down` 表示从高到低。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `5` | 每页/最多返回条数。 |
| `stockSize` | `-1` | 关联股票数量限制；`-1` 表示不限制。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `buyAmount`、`dataState`、`list`、`netAmount`、`onNum`、`pageCount`、`saleAmount`、`tradingDay`。

### 05. 龙虎榜个股资金排行

`GET /d6/market/v1/capital/dragon-tiger/stock-flow`　—　龙虎榜个股资金流向排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `tradeDay` | 空 | 交易日；空字符串使用最新可用交易日。 |
| `sortField` | `netSum` | 排序字段，按净额排行。 |
| `sortType` | `down` | `down` 从高到低。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `5` | 每页/最多返回条数。 |

响应：`code,message,data`；常见字段为 `buyAmount`、`dataState`、`list`、`netAmount`、`onNum`、`pageCount`、`saleAmount`、`tradingDay`。

### 06. 个股历史净流入

`GET /d6/market/v1/capital/flow/history`　—　查询标的历史净流入资金。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `symbol` | `111111` | 标的代码，通常为 6 位数字。 |
| `market` | `sh` | 市场：常见 `sh`、`sz`、`all`。 |
| `limit` | `4` | 最多返回条数。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `netTurnover`、`tradeDay`。

### 07. 个股实时资金流快照

`GET /d6/market/v1/capital/flow/snapshot`　—　单个标的实时资金流快照。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `symbol` | `111111` | 标的代码，通常为 6 位数字。 |
| `market` | `sh` | 市场：常见 `sh`、`sz`、`all`。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `RatioMain`、`Status`、`fiveHyRanking`、`hyTotal`、`industry`、`largeTurnoverIn`、`largeTurnoverOut`、`lastPx`、`littleTurnoverIn`、`littleTurnoverOut`、`mainTurnoverIn`、`mainTurnoverOut`、`market`、`marketTotal`、`mediumTurnoverIn`、`mediumTurnoverOut`、`minTime`、`name`、`netTurnover`、`prevDayNetTurnover`、`pxChangeRate`、`superTurnoverIn`、`superTurnoverOut`、`symbol`、`todayHyRanking`、`todayMarketRanking`、`tradeDay`。

### 08. 指数分时资金流

`GET /d6/market/v1/capital/flow/index-minute`　—　查询指数分时资金流。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `code` | `000000` | 标的或指数代码，按该接口的数据口径传递。 |
| `market` | `all` | 市场：常见 `sh`、`sz`、`all`。 |

响应：`code,message,data`；`data` 可能为对象、数组或 `null`，字段以实际数据为准。

### 09. 北向活跃股票排行

`GET /d6/market/v1/connect/active-rank`　—　北向或南向活跃股票排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `hsgtType` | `1` | 沪深港通方向编码；不同方向请以实际业务枚举为准。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`info`、`latestTradingDay`、`latestUpdateTime`。

### 10. 北向资金分时概况

`GET /d6/market/v1/connect/flow-minute`　—　沪深港通资金分时概况。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，常见字段为 `isTradeDay`、`isTradeTime`、`minTime`、`northNetFlow`、`sh2hkNetFlow`、`sz2hkNetFlow`。

### 11. 北向资金周期历史

`GET /d6/market/v1/connect/flow-history`　—　沪深港通周期资金历史。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `period` | `day` | 统计周期；`day` 表示日维度。 |
| `offset` | `20` | 向前取数的天数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `fiveNetFlow`、`list`、`sixtyNetFlow`、`twentyNetFlow`、`updateTime`。

### 12. 沪深港通净流入分时

`GET /d6/market/v1/connect/net-flow-minute`　—　沪深港通净流入分时数据。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，常见字段为 `hgtNetFlow`、`isTradeDay`、`isTradeTime`、`minTime`、`northNetFlow`、`sgtNetFlow`。

### 13. A 股大宗交易列表

`GET /d6/market/v1/trade/block-list`　—　大宗交易股票列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `pageNo` | `1` | 页码；以实际接口页码口径为准。 |
| `pageSize` | `20` | 每页/最多返回条数。 |
| `sort` | `-tradingDay` | 排序表达式；示例按交易日倒序。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `list`、`total`。

### 14. 板块周期资金排行

`GET /d6/market/v1/capital/flow/period-rank`　—　板块或市场周期资金排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `code` | `HSA` | 标的或指数代码，按接口数据口径传递。 |
| `period` | `one` | 资金统计周期；`one` 表示当日/单周期。 |
| `sortField` | `mainNetTurnover` | 排序字段；表示主力净流入。 |
| `sortType` | `down` | 排序方向；`down` 降序，`up` 升序。 |
| `pageNo` | `1` | 页码。 |
| `pageSize` | `3` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 可能为对象、数组或 `null`，字段以实际数据为准。

### 15. 个股诊断热搜

`GET /d6/market/v1/stock/diagnosis-hot`　—　个股诊断热搜。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，常见字段为 `lastPx`、`market`、`name`、`pxChangeRate`、`symbol`、`totalScore`。

### 16. 连续涨跌停股票

`GET /d6/market/v1/limit/continuous`　—　连续涨停或跌停股票列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `listedSector` | `0` | 上市板块筛选；`0` 表示全部。 |
| `STType` | `0` | 特殊处理股票筛选；`0` 按默认口径不过滤。 |
| `upDownType` | `up` | `up` 上涨/涨停，`down` 下跌/跌停。 |
| `tradingType` | `0` | 交易类型；`0` 表示全部。 |
| `sortField` | `countContLimit` | 连续次数排序字段。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `10` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`infos`。

### 17. 市场情绪指标

`GET /d6/market/v1/market/sentiment`　—　市场情绪指标。

参数：无固定参数。

响应：`code,message,data`；`data` 为对象，常见字段为 `fiveBoardContinueRate`、`fourBoardContinueRate`、`highBoardContinueRate`、`highestContinueBoardBoardStock`、`highestSpaceBoardStock`、`threeBoardContinueRate`、`twoBoardContinueRate`、`upLimit`、`upRate`。

### 18. 二次异动股票列表

`GET /d6/market/v1/stock/secondary-anomaly`　—　二次涨跌或异动股票列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `listedSector` | `0` | 上市板块筛选；`0` 表示全部。 |
| `STType` | `0` | 特殊处理股票筛选；`0` 按默认口径不过滤。 |
| `upDownType` | `up` | `up` 上涨/涨停，`down` 下跌/跌停。 |
| `tradingType` | `0` | 交易类型；`0` 表示全部。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `10` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`infos`。

### 19. 全市场涨跌分布

`GET /d6/market/v1/limit/distribution`　—　全市场涨跌分布统计。

参数：无固定参数。

响应：`code,message,data`；`data` 可能为对象、数组或 `null`，字段以实际数据为准。

### 20. 涨跌停监控统计

`GET /d6/market/v1/limit/monitor`　—　涨跌停监控统计。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `STType` | `0` | 特殊处理股票筛选；`0` 按默认口径不过滤。 |
| `type` | `0` | 监控类型编码；`0` 为默认全部口径。 |

响应：`code,message,data`；`data` 可能为对象、数组或 `null`，字段以实际数据为准。

### 21. 涨跌停趋势分时

`GET /d6/market/v1/limit/trend-minute`　—　涨跌停趋势分钟序列。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，字段以实际数据为准。

### 22. 盘口抢筹排行

`GET /d6/market/v1/capital/scramble-rank`　—　盘口抢筹或争夺排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `sortField` | `amount` | 排序字段；`amount` 表示金额。 |
| `sortType` | `desc` | 排序方向；`desc` 表示降序。 |
| `limit` | `5` | 最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `list`、`tradingDay`。

### 23. 涨停/跌停股票列表

`GET /d6/market/v1/limit/list`　—　涨停或跌停股票列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `listedSector` | `0` | 上市板块筛选；`0` 表示全部。 |
| `STType` | `0` | 特殊处理股票筛选；`0` 按默认口径不过滤。 |
| `upDownType` | `up` | `up` 上涨/涨停，`down` 下跌/跌停。 |
| `tradingType` | `0` | 交易类型；`0` 表示全部。 |
| `sortField` | `upType` | `upType` 上涨，`downType` 下跌。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `10` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`infos`。

### 24. 股票涨跌幅排行

`GET /d6/market/v1/rank/change`　—　股票涨跌幅排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `listedSector` | `0` | 上市板块筛选；`0` 表示全部。 |
| `STType` | `0` | 特殊处理股票筛选；`0` 按默认口径不过滤。 |
| `upDownType` | `up` | `up` 上涨/涨停，`down` 下跌/跌停。 |
| `tradingType` | `0` | 交易类型；`0` 表示全部。 |
| `sortField` | `upType` | `upType` 上涨，`downType` 下跌。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `10` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`infos`。

### 25. 沪深京 A 股行情排行

`GET /d6/market/v1/rank/stocks`　—　沪深京 A 股行情排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `listedSector` | `0` | 上市板块筛选；`0` 表示全部。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `20` | 每页/最多返回条数。 |
| `sortField` | `pxChangeRate` | 排序字段。 |
| `sortType` | `0` | 排序方向或类型编码。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`infos`。

### 26. 上市公司研报列表

`GET /d6/market/v1/news/research-reports`　—　上市公司研报列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `from` | `2026-02-06` | 起始日期，格式 `YYYY-MM-DD`。 |
| `to` | `2026-08-05` | 结束日期，格式 `YYYY-MM-DD`。 |
| `pageNo` | `0` | 页码；以实际接口页码口径为准。 |
| `pageSize` | `50` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`data`。

### 27. 公告掘金筛选

`POST /d6/market/v1/news/announcements/filter`　—　公告筛选列表。

请求体字段：

| 字段 | 默认/示例 | 说明 |
|---|---|---|
| `searchTp` | `0` | 公告搜索类型。 |
| `pageNo` | `1` | 公告页码，从 1 开始。 |
| `pageSize` | `20` | 每页公告数。 |
| `title` | `""` | 公告标题关键词；空字符串不筛选。 |
| `level1` | `""` | 一级公告分类；空字符串为全部。 |
| `level2` | `""` | 二级公告分类；空字符串为全部。 |
| `range` | `1` | 公告时间范围编码。 |
| `dateTp` | `2` | 公告日期类型。 |
| `sentiment` | `0` | 公告情绪筛选；`0` 表示全部。 |
| `optionStock` | `[]` | 自选股代码数组；空数组表示全部股票。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `companyCnt`、`list`、`noticeCnt`。

### 28. 新股申购发行列表

`GET /d6/market/v1/news/ipo`　—　新股申购及发行列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `listedSector` | `0` | 上市板块筛选；`0` 表示全部。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `10` | 每页/最多返回条数。 |
| `sortField` | `onlineStartDate` | 排序字段。 |
| `sortType` | `0` | 排序方向或类型编码。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `count`、`ipoList`。

### 29. 业绩公告列表

`GET /d6/market/v1/news/performance/announcements`　—　业绩公告列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `pageNo` | `1` | 页码；以实际接口页码口径为准。 |
| `pageSize` | `10` | 每页/最多返回条数。 |
| `sector` | `0` | 行业/板块筛选；`0` 表示全部。 |
| `sort` | `-publishTime` | 排序表达式；示例按发布时间倒序。 |
| `reportDate` | `1785923618` | 报告期秒级时间戳；请按目标报告期替换。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `list`、`total`。

### 30. 业绩预告汇总

`GET /d6/market/v1/news/performance/summary`　—　业绩预告或报告汇总。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `sector` | `0` | 行业/板块筛选；`0` 表示全部。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `key`、`value`。

### 31. 热门股票搜索

`GET /d6/market/v1/search/hot-stocks`　—　股票热搜词和热门股票。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，常见字段为 `Exchange`、`Market`、`Name`、`Pv`、`Symbol`。

### 32. 板块当前异动信号

`GET /d6/market/v1/sector/anomaly/current`　—　当前板块异动信号。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `page` | `1` | 页码。 |
| `pageSize` | `-1` | 每页/最多返回条数；以实际数据量为准。 |

响应：`code,message,data`；`data` 可能为对象、数组或 `null`，字段以实际数据为准。

### 33. 行业板块资金排行

`GET /d6/market/v1/sector/capital-rank`　—　板块资金流向排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `count` | `5` | 返回的板块/排行条数。 |
| `plateTypeCode` | `hy` | 板块类型；`hy` 表示行业板块。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `downList`、`upList`。

### 34. 板块涨跌及龙头排行

`GET /d6/market/v1/sector/leader-rank`　—　板块涨跌幅排行及龙头股。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `count` | `8` | 返回的板块/排行条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `downList`、`upList`。

### 35. 行业/概念板块涨跌排行

`GET /d6/market/v1/sector/change-rank`　—　行业或概念板块涨跌排行。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `count` | `5` | 返回的板块/排行条数。 |
| `plateTypeCode` | `hy` | 板块类型；`hy` 表示行业板块。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `downList`、`upList`。

### 36. 个股异动监控

`POST /d6/market/v1/stock/anomalies`　—　个股异动监控列表。

请求体字段：

| 字段 | 默认/示例 | 说明 |
|---|---|---|
| `limit` | `10` | 最多返回异动条数。 |
| `startTime` | — | 异动时间起点，按页面使用的时间格式传递。 |
| `endTime` | — | 异动时间终点，按页面使用的时间格式传递。 |
| `asc` | — | 是否按时间升序。 |
| `stocks` | — | 股票代码数组；空数组表示全部。 |
| `categories` | — | 异动分类数组；空数组表示全部。 |

请求示例：

```json
{"limit":10}
```

响应：`code,message,data`；`data` 可能为对象、数组或 `null`，字段以实际数据为准。

### 37. 沪深涨跌幅概览

`GET /d6/market/v1/quote/overview/change`　—　沪深涨跌幅概览。

参数：无固定参数。

响应：`code,message,data`；`data` 为对象，字段以实际数据为准。

### 38. 沪深主要指数行情

`GET /d6/market/v1/quote/index/major`　—　沪深主要指数行情。

参数：无固定参数。

响应：`code,message,data`；`data` 为对象，常见字段为 `updownspeedMAIN.SH`、`updownspeedMAIN.SHSZ`、`updownspeedMAIN.SZ`。

### 39. 沪深指数资金概览

`GET /d6/market/v1/quote/index/capital`　—　沪深指数资金概览。

参数：无固定参数。

响应：`code,message,data`；`data` 为对象，常见字段为 `NetbiginMAIN.SH`、`NetbiginMAIN.SHSZ`、`NetbiginMAIN.SZ`。

### 40. A 股基本面与盘口摘要

`GET /d6/market/v1/stock/fundamentals`　—　股票基本面摘要。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `symbol` | `sh000001` | 带市场前缀的证券代码，例如 `sh000001`。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `amplitude`、`bidGrp`、`bps`、`businessAmount`、`businessAmountAm`、`businessAmountIn`、`businessAmountOut`、`businessBalance`、`businessBalanceAm`、`businessCount`、`circulationAmount`、`circulationValue`、`currentAmount`、`dataTimestamp`、`downPx`、`dynPbRate`、`entrustDiff`、`entrustRate`、`eps`、`epsTtm`、`epsYear`、`finEndDate`、`finQuarter`、`highPx`、`hqTypeCode`、`ipoPrice`、`issueDate`、`lastPx`、`lowPx`、`marketDate`、`marketValue`、`openPrice`、`peRate`、`preClosePx`、`prodCode`、`prodName`、`pxChange`、`pxChangeRate`、`sharesPerHand`、`totalBidTurnover`、`totalBuyAmount`、`totalOfferTurnover`、`totalSellAmount`、`totalShares`、`tradeStatus`、`turnoverRatio`、`upPx`、`volRatio`、`w52HighPx`、`w52LowPx`、`wAvgPx`。

### 41. 港股映射沪深行情

`GET /d6/market/v1/quote/cross-market/hk-a`　—　港股映射沪深市场行情。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `Classes` | `HK2SH` | 映射类别；`HK2SH` 表示港股映射沪深。 |
| `Type` | `Business_balance` | 映射指标；`Business_balance` 表示业务余额口径。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `Business_balance`、`Classes`、`Last_px`、`Market_Symbol`、`Market_value`、`Pe_rate`、`Prod_name`、`Px_change_rate`、`Turnover_ratio`。

### 42. 市场概览资金快照

`GET /d6/market/v1/quote/market/overview`　—　市场股票列表和资金概览。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `MarketType` | `(MarketType=1)` | 市场类型表达式；按目标市场口径传递。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `Business_amount`、`DRCJJME`、`DRYE`、`DRZJLR`、`DetailDate`、`HistoryPrice`、`LCG`、`LCGCode`、`LCGZDF`、`LCGmarket`、`LSZJLR`、`MCCJE`、`MRCJE`、`MarketType`、`SSEChange`、`SSEChangePrecent`。

### 43. AH 股比价列表

`GET /d6/market/v1/quote/cross-market/ah`　—　AH 股比价列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `pageNo` | `0` | 页码；以实际接口页码口径为准。 |
| `pageSize` | `50` | 每页/最多返回条数。 |
| `types` | `Ratio` | 返回类型；`Ratio` 表示比价。 |
| `sort` | `DESC` | 排序方向；`DESC` 表示降序。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `ParityRatioahs`、`Total`。

### 44. 沪深股票行情排序

`GET /d6/market/v1/quote/stocks/rank`　—　沪深股票行情排序。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `en_hq_type_code` | `XSHG.ESA,XSHE.ESA,XSHG.KSH` | 行情市场集合，多个值用逗号分隔。 |
| `sort_field_name` | `px_change_rate` | 行情字段名；表示涨跌幅。 |
| `sort_type` | `1` | 行情排序类型编码。 |
| `pageNo` | `1` | 页码；以实际接口页码口径为准。 |
| `pageSize` | `20` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `Stocks`、`Total`。

### 45. 交易日历

`GET /d6/market/v1/market/trading-days`　—　查询交易日历。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `limit` | `366` | 最多返回条数。 |
| `market` | `sh` | 市场：常见 `sh`、`sz`、`all`。 |

响应：`code,message,data`；`data` 为数组，具体日期字段以实际数据为准。

### 46. 板块实时行情列表

`GET /d6/market/v1/sector/quote`　—　板块行情列表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `hqTypeCode` | `HY` | 行情板块类型；`HY` 表示行业板块。 |
| `sortFlag` | `true` | 是否启用排序；`true` 启用。 |
| `sortFields` | `pxChangeRate` | 板块排序字段；表示涨跌幅。 |
| `pageNum` | `1` | 页码，从 1 开始。 |
| `pageSize` | `10` | 每页/最多返回条数。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `counts`、`plate`。

### 47. 风格板块列表

`GET /d6/market/v1/sector/style`　—　风格板块列表。

参数：无固定参数。

响应：`code,message,data`；`data` 为数组，常见字段为 `imageUrl`、`lastPx`、`market`、`name`、`positiveDetail`、`positiveIntroduction`、`pxChangeRate`、`riseFirstGrp`、`symbol`、`typeCode`、`updateTime`。

### 48. 融资融券汇总

`GET /d6/market/v1/margin/summary`　—　融资融券汇总表。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `market` | 空 | 市场过滤；空字符串表示全部市场，`sh` 表示上海口径。 |
| `date` | 当天 | 交易日期，格式 `YYYY-MM-DD`。 |

响应：`code,message,data`；`data` 为对象，常见字段为 `FiSecuValue`、`FiSecuValuestr`、`FiSecudiff`、`FiSecudiffAdd`、`FiSecudiffRatio`、`FinaInTVRatio`、`FinaInTVRatiostr`、`FinanceValue`、`FinanceValueDiff`、`FinanceValueDiffstr`、`FinanceValuestr`、`SecurityValue`、`SecurityValueDiff`、`SecurityValueDiffstr`、`SecurityValuestr`、`TradingDay`。

### 49. 融资融券前五名

`GET /d6/market/v1/margin/top-five`　—　融资融券前五名。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `date` | 当天 | 交易日期，格式 `YYYY-MM-DD`。 |
| `market` | 空 | 市场过滤；空字符串表示全部市场，`sh` 表示上海口径。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `ClosePrice`、`ClosePricediv`、`ClosePricedivstr`、`ClosePricestr`、`FinaInTotal`、`FinaInTotalstr`、`Market`、`PrevClosePrice`、`Ratio`、`SecuAbbr`、`SecuCode`、`TradingDay`。

### 50. 融资融券差额曲线

`GET /d6/market/v1/margin/difference`　—　融资融券差额曲线。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `market` | 空 | 市场过滤；空字符串表示全部市场，`sh` 表示上海口径。 |
| `date` | 当天 | 交易日期，格式 `YYYY-MM-DD`。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `Change`、`ClosePrice`、`Diff`、`DiffRatio`、`FinaInTotalRatio`、`FinanceSecurityValue`、`FinanceValue`、`Ratio`、`Rzrqdif`、`SecurityValue`、`Tradingday`。

### 51. 个股融资融券明细

`GET /d6/market/v1/margin/stock/detail`　—　个股融资融券明细。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `pageSize` | `100` | 每页/最多返回条数。 |
| `date` | 当天 | 交易日期，格式 `YYYY-MM-DD`。 |
| `market` | 空 | 市场过滤；空字符串表示全部市场，`sh` 表示上海口径。 |

响应：`code,message,data`；`data` 为数组或 `null`，常见字段为 `CValue`、`ClosePrice`、`FinaInTotalRatio`、`FinanceBuyValue`、`FinancePureValue`、`FinanceRefundValue`、`FinanceSecurityDiffValue`、`FinanceSecurityValue`、`FinanceValue`、`InnerCode`、`SecuAbbr`、`SecuCode`、`SecuMarket`、`SecurityPureValue`、`SecurityRefundVolume`、`SecuritySellVolume`、`SecurityValue`、`SecurityVolume`、`TradingDay`、`UpDownRatio`。

### 52. 个股融资融券历史

`GET /d6/market/v1/margin/stock/history`　—　个股融资融券历史。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `market` | 空 | 市场过滤；空字符串表示全部市场，`sh` 表示上海口径。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `ClosePrice`、`FinaInTotalRatio`、`FinanceBuyValue`、`FinancePureValue`、`FinanceRefundValue`、`FinanceSecurityDiffValue`、`FinanceSecurityValue`、`FinanceValue`、`SecurityPureValue`、`SecurityRefundVolume`、`SecuritySellVolume`、`SecurityValue`、`SecurityVolume`、`TradingDay`、`UpDownRatio`。

### 53. 融资融券分时曲线

`GET /d6/market/v1/margin/curve`　—　融资融券分时曲线。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `market` | `sh` | 市场过滤；常见 `sh`、`sz`、`all`。 |

响应：`code,message,data`；`data` 为数组，常见字段为 `FinanceValue`、`SecurityValue`、`TradingDay`。

### 54. 个股复权基础信息

`GET /d6/market/v1/stock/adjustment`　—　股票复权或复牌基础信息。

| 参数 | 默认/示例 | 说明 |
|---|---|---|
| `market` | `sh` | 市场代码：`sh` 上海，`sz` 深圳。 |
| `instrucode` | `000001` | 证券代码，不含 `sh`/`sz` 前缀。 |

响应：`code,message,data`；`data` 为对象，字段以实际数据为准。

### 55. 个股历史 K 线

`GET /d6/market/v1/kline/history`　—　返回多根历史 K 线，支持分钟、日、周、月周期。

这是获取 K 线序列的接口。上一节的 `POST /kline` 是最新快照接口，返回一条最新 K 线；不要用 `StartID`、`EndID` 去给快照接口做历史分页。

请求参数：

| 参数 | 默认/示例 | 是否必填 | 说明 |
|---|---|---|---|
| `market` | `SZ` | 否 | 市场代码：`SZ` 深圳，`SH` 上海。 |
| `inst` | `300052` | 否 | 证券代码，不带市场前缀。 |
| `period` | `MIN5` | 否 | 周期：`MIN1` 1 分钟、`MIN5` 5 分钟、`MIN15` 15 分钟、`MIN30` 30 分钟、`MIN60` 60 分钟、`DAY` 日线、`WEEK` 周线、`MONTH` 月线。 |
| `startTime` | `0` | 否 | 起始 Unix 秒时间戳；`0` 表示不限制起点。代理会自动按整分钟向下对齐。 |
| `endTime` | `2524579200` | 否 | 结束 Unix 秒时间戳；默认取到当前可用数据，代理会自动按整分钟向下对齐。 |
| `limit` | `1200` | 否 | 返回条数，传 50 的正整数倍；常用 `50`、`100`、`200`、`1200`。 |

最简单的 5 分钟 K 线请求：

```bash
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/kline/history?market=SZ&inst=300052&period=MIN5&startTime=0&endTime=2524579200&limit=1200"
```

30 分钟 K 线只需要修改 `period`：

```bash
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/kline/history?market=SZ&inst=300052&period=MIN30&startTime=0&endTime=2524579200&limit=200"
```

Python 读取：

```python
history = call_api(
    "GET",
    "/d6/market/v1/kline/history",
    query={
        "market": "SZ",
        "inst": "300052",
        "period": "MIN5",
        "startTime": 0,
        "endTime": 2524579200,
        "limit": 1200,
    },
)
bars = history.get("KlineData") or []
for bar in bars:
    timestamp = bar.get("Time")
    close = bar.get("Close")
    print(timestamp, close)
```

成功响应的关键结构：

```json
{
  "Code": 0,
  "Msg": "Success",
  "KlineData": [
    {
      "TradingDay": 1785859200,
      "Time": 1785893700,
      "Open": 11.74,
      "High": 12.18,
      "Low": 11.68,
      "Close": 11.86,
      "Volume": 9909600,
      "Amount": 117968156,
      "PreClose": 12.05,
      "SettlementPrice": 0
    }
  ],
  "MinData": null,
  "StatisticsData": null,
  "LongPeriodKlineData": null,
  "Expire": 0
}
```

按 `KlineData[]` 的顺序读取即可；每一项是一根 K 线。时间字段是 Unix 秒时间戳，转换为本地时间后再展示。分钟 K 线的 `Time` 是该根 K 线的时间点，`TradingDay` 是所属交易日。返回中可能出现 `PreSettlement`、`AfterTradeVolume`、`AfterTradeAmount`、`OpenInterest`、`AvePrice` 等扩展字段，解析程序应忽略无法识别的字段。

注意事项：

- `limit` 是“最多返回多少根”，不是页码；必须传 50 的正整数倍，先用 `1200` 验证链路，再按需要改成 `50`、`100`、`200` 等。
- 如果需要按日期缩小范围，传 Unix 秒时间戳，例如当天 00:00:00 和次日 00:00:00；传入带秒的时间也可以，代理会自动向下对齐到整分钟。
- 非交易时段、停牌标的或尚未生成数据时，`KlineData` 可能为空。
- `MIN1`、`MIN5`、`MIN15`、`MIN30`、`MIN60` 是字符串周期，不要传 `0`、`1`、`3` 等数字。

### 56. 个股筹码分布

`GET /d6/market/v1/stock/chip/distribution`　—　返回个股近一段时间内按交易日变化的筹码摘要和价格分布。

请求参数：

| 参数 | 默认/示例 | 是否必填 | 说明 |
|---|---|---|---|
| `symbol` | `001202` | 否 | 证券代码，不带市场前缀。 |
| `market` | `sz` | 否 | 市场代码：`sh` 上海，`sz` 深圳。 |
| `startTime` | 最近约 100 天 | 否 | 起始 Unix 毫秒时间戳；省略时由代理取最近约 100 天。 |
| `powerType` | `1` | 否 | 筹码统计口径；`1` 为页面默认口径。 |

最简单的请求：

```bash
curl.exe -G "http://127.0.0.1:8080/d6/market/v1/stock/chip/distribution?symbol=001202&market=sz&powerType=1"
```

成功响应的关键结构：

```json
{
  "code": 1,
  "message": "操作成功",
  "data": [
    {
      "tradeDate": 1785859200000,
      "chipSummary": {
        "meanPrice": 12.34,
        "lastPrice": 12.56,
        "winRatio": 63.21,
        "costL70": 11.80,
        "costH70": 13.10,
        "jzd70": 10.52,
        "costL90": 11.20,
        "costH90": 13.80,
        "jzd90": 17.34,
        "shapes": "示例形态"
      },
      "items": [
        {"price": 12.30, "volume": 125000}
      ]
    }
  ]
}
```

`data[]` 的每项对应一个交易日；`chipSummary` 用于摘要卡片，`items[]` 用于绘制价格—筹码量分布。`winRatio`、`jzd70` 和 `jzd90` 按百分比数值返回。`d6_gui.py` 已将该接口放在个股 K 线右侧，鼠标移动到不同 K 线时会按交易日切换对应分布。

## 6. 接入建议

- 生产程序应把 `code`、`message` 和 HTTP 状态一起记录；不要只判断 HTTP `200`。
- 分页接口建议保留 `pageNo/pageNum`、`pageSize`、`total/count`，并按实际返回数量停止翻页。
- 交易日相关接口建议先取交易日历，再请求指定日期；日期没有数据时不要把空结果当成网络故障。
- 实时接口建议使用单独的 WebSocket 连接管理重连、心跳和断线后的重新订阅；`Header.No` 可用于标识客户端消息序号。
- JSON 字段可能随数据类型增加，解析时保留未知字段，避免使用固定字段集合导致兼容性问题。

## 7. 小白最容易写错的几个地方

### 7.1 分页不要混用 `page`、`pageNo` 和 `pageNum`

这三个名字是三个不同的请求字段：

| 字段 | 文档中出现的接口 | 常见起始值 |
|---|---|---:|
| `page` | 板块当前异动 | `1` |
| `pageNo` | 大宗交易、研报、公告相关、AH 比价、股票行情排序等 | 以该接口表格为准，可能是 `0` 或 `1` |
| `pageNum` | 龙虎榜、涨跌停、排行、新股、板块、公告绩效等 | `1` |

`pageSize` 表示一次最多取多少条；它不是页码。不要把 `pageSize=20` 当成“第 20 页”。

通用 Python 分页写法如下。只对确实返回 `total` 或 `count` 的接口使用总数判断；没有总数字段时，用“本页为空”停止。

```python
def fetch_pages(path, page_key="pageNum", page_size=20, fixed_query=None):
    fixed_query = dict(fixed_query or {})
    all_rows = []

    for page in range(1, 1001):  # 防止服务异常时无限循环
        query = dict(fixed_query)
        query[page_key] = page
        query["pageSize"] = page_size
        result = call_api("GET", path, query=query)
        data = result.get("data") or {}

        # 不同接口的数组键不同，按实际接口选择。
        rows = data.get("infos") or data.get("list") or data.get("data") or []
        if not isinstance(rows, list) or not rows:
            break
        all_rows.extend(rows)

        total = data.get("total") or data.get("count")
        if isinstance(total, int) and len(all_rows) >= total:
            break
        if len(rows) < page_size:
            break

    return all_rows


rows = fetch_pages(
    "/d6/market/v1/rank/change",
    page_key="pageNum",
    page_size=10,
    fixed_query={
        "listedSector": "0",
        "STType": "0",
        "upDownType": "up",
        "tradingType": "0",
        "sortField": "upType",
    },
)
print("总行数：", len(rows))
```

### 7.2 重试要区分网络错误和业务错误

建议重试：连接超时、连接被关闭、HTTP `502/503/504`。

不要自动重试：HTTP `403`（没有权限）、HTTP `404`（路径错误）、JSON 参数错误。否则程序会重复发送错误请求，还会让客户误以为接口不稳定。

简单的 Python 重试包装：

```python
import time
from urllib.error import URLError


def call_with_retry(method, path, query=None, body=None, attempts=3):
    for index in range(attempts):
        try:
            return call_api(method, path, query=query, body=body)
        except ApiError as error:
            if error.status not in (502, 503, 504) or index == attempts - 1:
                raise
        except URLError:
            if index == attempts - 1:
                raise
        except RuntimeError as error:
            # call_api 对连接错误给了可读提示；只重试这一类错误。
            if not str(error).startswith("无法连接") or index == attempts - 1:
                raise
        time.sleep(2 ** index)
```

### 7.3 日期和报告期时间戳

`date`、`from`、`to` 使用日期文本；`reportDate` 使用 Unix 秒级时间戳。Python 转换方式：

```python
from datetime import date, datetime, timezone

today_text = date.today().isoformat()  # 例如 2026-08-05
report_date_seconds = int(datetime(2026, 8, 5, tzinfo=timezone.utc).timestamp())

result = call_api(
    "GET",
    "/d6/market/v1/news/performance/announcements",
    query={
        "pageNo": 1,
        "pageSize": 10,
        "sector": 0,
        "sort": "-publishTime",
        "reportDate": report_date_seconds,
    },
)
```

如果只是查询当天融资融券，直接传 `date.today().isoformat()`；如果接口返回空数组，先检查当天是不是交易日。

### 7.4 先打印完整 JSON，再写字段映射

不要一上来就写死 `data[0]["price"]`。第一步应该是：

```python
result = call_api("GET", "/d6/market/v1/sector/style")
print(json.dumps(result, ensure_ascii=False, indent=2))
```

确认实际层级后再读取。例如：

```python
for item in result.get("data") or []:
    name = item.get("name")
    change_rate = item.get("pxChangeRate")
    print(name, change_rate)
```

### 7.5 最小接入检查表

上线前逐项确认：

- [ ] 代理地址和端口不是写死到业务代码中，能够通过配置修改。
- [ ] GET 参数使用 URL 编码，POST 请求头包含 `Content-Type: application/json`。
- [ ] HTTP 状态码、JSON `code`、JSON `message` 都有日志。
- [ ] `data` 为 `null`、数组为空、字段缺失时不会让程序崩溃。
- [ ] 分页使用接口自己的 `page/pageNo/pageNum`，没有统一替换。
- [ ] 交易日期和报告期时间戳没有混用。
- [ ] WebSocket 断开后会重新连接并重新发送订阅消息。
- [ ] 日志中不要打印账号密码、授权信息或完整敏感配置。
