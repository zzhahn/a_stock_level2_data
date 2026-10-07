# D201 实时行情 WebSocket 接口

本文是一份可以照着做的入门手册。读完后，你应该能够：

1. 安装 Python 依赖并检查本地服务是否可连接；
2. 订阅一只股票的盘口、逐笔委托或逐笔成交；
3. 正确解析每条消息中的全部数据；
4. 将最新行情保存到自己的程序或文件中；
5. 处理断线、错误、退订和程序退出。

接口地址是本机地址，服务程序必须先启动并完成登录：

```text
ws://127.0.0.1:8080/d201
```

协议是 WebSocket，消息内容是 UTF-8 JSON 文本。D201 只负责提供行情数据，不负责替你保存数据、计算策略或下单。

## 为什么本地 WebSocket 通常响应较快

可以把数据链路简单理解为：

```text
你的 Python / JavaScript / C++ 程序
          │  WebSocket + JSON
          ▼
    127.0.0.1:8080/d201
          │  本地服务程序
          ▼
       实时行情数据
```

这里的 `127.0.0.1` 表示“当前这台电脑”。你的程序和本地服务程序之间通过一条已经建立的长连接通信：程序订阅一次，后续有变化时服务主动推送，不需要每次先重新建立连接、再轮询询问。因此，客户端从本地服务收到数据的这一段路径较短，适合实时策略、监控和行情展示。

但“本地”不等于“完全没有网络延迟”，也不代表每条行情都保证零延迟。行情还要经过数据网络到达本地服务；实际收到时间会受到网络质量、行情活动量、服务程序处理速度、电脑负载以及开盘时短时积压影响。本文所说的低延迟，主要是指你的程序访问本地服务这一段开销较小。

如果把 WebSocket 改成“每隔一秒发一次普通请求”，就可能漏掉两次请求之间的变化，也会增加反复连接和等待的开销。实时程序应保持连接、订阅后持续读取消息，并在断线后按退避策略重连。

### 和常见行情接入方式相比

客户常见的接入方式大致有三种：

| 方式 | 数据怎么到达程序 | 常见问题 | 本地 WebSocket 的差异 |
|---|---|---|---|
| 定时 HTTP 轮询 | 程序每隔一段时间主动询问一次 | 请求间隔内发生的变化可能要等下一次才能看到；频繁请求还会产生重复开销 | 建立一次连接后由服务主动推送变化 |
| 程序直接连接远程行情接口 | 客户程序自己处理远程连接、登录、协议和重连 | 网络、权限、协议解析、断线恢复都要由客户自己维护 | 本地程序只处理 `ws://127.0.0.1:8080/...` 和 JSON，接入工作更简单 |
| 本地 WebSocket | 客户程序连接本机服务，服务负责接收并转换行情 | 仍然受外部网络和行情线路状态影响 | 本机这一段距离短、连接持久、消息格式统一，适合实时接收 |

因此，本接口的主要优势不是承诺“任何情况下都比所有产品快”，而是把复杂的数据连接工作放在本地服务程序中处理，让客户程序获得一条短的、持续推送的 JSON 通道。对于策略程序来说，通常可以少写协议解析、登录管理和断线处理代码，更容易稳定运行。

## 1. 先理解四个概念

| 概念 | 含义 |
|---|---|
| 连接 | 你的程序与本地服务之间的一条 WebSocket 通道 |
| 请求 | 你发给服务的一组 JSON 命令 |
| 订阅 | `enable=1`，服务持续推送数据 |
| 查询 | `enable=2`，服务返回一次数据；并非所有数据类型都支持 |

行情代码必须是 8 个字符：市场前缀加 6 位数字。例如 `SZ002177`、`SH600519`。代码要大写，不要写成 `002177`，也不要加空格或点号。

## 2. 第一次运行：从安装到看到行情

### 2.1 检查前提

在运行客户端前确认：

- 本地服务程序已经启动；
- 服务程序已经登录，并且当前账号有对应数据权限；
- 本机 `8080` 端口没有被防火墙或其他程序拦截；
- 当前股票代码有效且当时有行情。

### 2.2 安装 Python 和依赖

打开 PowerShell 或命令提示符，执行：

```bash
python --version
python -m pip install websocket-client
```

如果电脑上有多个 Python，建议始终用同一个 `python` 执行安装和运行脚本。安装失败时先执行 `python -m pip --version`，确认 pip 与 Python 属于同一套环境。

### 2.3 最小可运行程序

将下面内容保存为 `d201_first.py`，再执行 `python d201_first.py`。程序订阅一只股票的十档盘口，收到数据后打印买一价和卖一价。

```python
import json
import websocket

URL = "ws://127.0.0.1:8080/d201"
CODE = "SZ002177"

ws = websocket.create_connection(URL, timeout=10)
try:
    request = [{
        "type": "buysell",
        "code": CODE,
        "enable": 1,
        "buyLevels": 10,
        "sellLevels": 10,
    }]
    ws.send(json.dumps(request, separators=(",", ":")))

    while True:
        message = json.loads(ws.recv())
        for item in message.get("list", []):
            if item.get("type") == "error":
                print("服务错误：", item.get("msg"))
                continue
            if item.get("type") != "buysell":
                continue

            data = item.get("data") or {}
            if data.get("code") != CODE:
                continue
            buy_prices = data.get("buyPrice", [])
            sell_prices = data.get("sellPrice", [])
            buy1 = buy_prices[0] / 1000 if buy_prices else None
            sell1 = sell_prices[0] / 1000 if sell_prices else None
            print(f"{CODE} 买一={buy1} 卖一={sell1}")
finally:
    ws.close()
```

看到类似 `SZ002177 买一=... 卖一=...` 即表示连接、订阅、JSON 解析都成功。按 `Ctrl+C` 结束程序即可。

### 2.4 直接运行示例

示例合集已提供多股票盘口示例：[`d201_buysell_batch_repro.py`](../examples/d201_buysell_batch_repro.py)。它为每只股票建立一个连接，并把统计结果写入 JSON 文件：

```bash
python -m pip install websocket-client
python d201_buysell_batch_repro.py --seconds 15
```

首次验证建议只运行 15 秒。确认 `收到行情的股票` 数量正常后，再调整股票列表和运行时间。

## 3. 连接、心跳和关闭

服务端地址固定为 `ws://127.0.0.1:8080/d201`。`127.0.0.1` 表示本机，不是远程服务器地址。

服务端大约每 30 秒发送一次 WebSocket Ping 控制帧。常用库会自动回复 Pong，Python 的 `websocket-client`、浏览器 JavaScript WebSocket 通常不需要你额外写心跳代码。自己实现 WebSocket 协议时必须回复 Ping，否则连接可能在约 60 秒后断开。

结束订阅时先发送退订命令，再关闭连接：

```python
ws.send(json.dumps([{
    "type": "buysell",
    "code": "SZ002177",
    "enable": 0,
}]))
ws.close()
```

程序异常退出时来不及退订也没关系，连接关闭后订阅会随连接消失；长期运行程序仍建议在 `finally` 中关闭连接。

## 4. 请求格式

### 4.1 永远发送数组

即使只有一个命令，也必须把命令放在数组中：

```json
[{"type":"buysell","code":"SZ002177","enable":1}]
```

一次可以发送多个命令：

```json
[
  {"type":"buysell","code":"SZ002177","enable":1,"buyLevels":10,"sellLevels":10},
  {"type":"trade","code":"SZ002177","enable":1,"count":60},
  {"type":"entrust","code":"SZ002177","enable":1,"count":150}
]
```

### 4.2 通用字段

| 字段 | 类型 | 必填 | 取值和说明 |
|---|---:|:---:|---|
| `type` | string | 是 | `holoqueue`、`price`、`entrust`、`trade`、`buysell`、`thousand` |
| `code` | string | 是 | 8 位代码，如 `SZ002177` |
| `enable` | int | 是 | `1` 订阅，`0` 退订，`2` 单次查询；仅支持查询的数据类型才能使用 `2` |
| `userParam` | int | 否 | `0~65535` 的自定义标识，响应中原样返回 |

`enable=0` 时仍应填写与订阅相同的 `type` 和 `code`，专属参数可以省略。

> **重要：`count` 请使用默认值，不要随意填写。** `count` 是单次底层请求/推送的记录数，不是“我要获取的全部数据量”。服务端省略字段时的默认值是：`trade=60`、`entrust=150`。新手程序建议直接删除 `count` 字段，让服务使用默认值；`count=5000` 不是有效的“获取更多数据”写法，可能被限制、截断或导致请求异常。需要更多历史数据时，应使用历史分页/序号继续请求，而不是把 `count` 改成很大的数。

> **UI 提醒：** 主测试页面的 `count` 输入框目前默认预填 `60`，所以直接点击发送时，`entrust` 会明确发送 `count=60`；这不是“省略字段后的服务端默认值”。若想使用服务端默认值，请在自己写的程序中删除 `count`；若从 UI 复制 `entrust` 命令，建议手动改为 `150`。专用 d201 看板按 `entrust=150`、`trade=60` 发送。

### 4.3 六种数据类型

#### `buysell`：盘口快照

首次订阅通常会返回当前盘口，之后在盘口变化时推送。参数：

| 参数 | 默认 | 说明 |
|---|---:|---|
| `buyLevels` | 2 | 买盘档位，范围 1~10 |
| `sellLevels` | 2 | 卖盘档位，范围 1~10 |

新手最适合先使用 `buysell`，因为它直接给出各档价格和数量。

#### `trade`：逐笔成交

实时推送每笔成交；查询历史时可用 `enable=2`。

| 参数 | 默认 | 说明 |
|---|---:|---|
| `count` | **60** | 单次请求/推送最多记录数；正数顺序，负数倒序。**建议删除此字段使用默认值，不要填写 5000 等大数** |
| `timeOfDay` | 0 | 历史查询时间，格式 `HHmmss`，如 `150000` |
| `seqPos` | 0 | 历史查询起始成交序号 |

#### `entrust`：逐笔委托

实时推送新委托和撤单；查询历史时可用 `enable=2`。

| 参数 | 默认 | 说明 |
|---|---:|---|
| `count` | **150** | 单次请求/推送最多记录数；正数顺序，负数倒序。**建议删除此字段使用默认值，不要填写 5000 等大数** |
| `history` | 0 | `0` 实时，`1` 历史；负数查询时服务会自动按历史处理 |
| `orderId` | 0 | 历史查询起始委托号 |

#### `holoqueue`：全息队列

实时返回多个价位及每个价位前若干排队明细，数据量较大。

| 参数 | 默认 | 说明 |
|---|---:|---|
| `subDisplayCount` | 6 | 每个价位最多返回的子记录数，范围 1~6 |

#### `price`：指定价位排队变化

盯住某个买价或卖价，推送该价位排队变化。

| 参数 | 默认 | 说明 |
|---|---:|---|
| `direction` | 0 | `0` 买盘，`1` 卖盘 |
| `priceCent` | 0 | 请求价位单位为“元×1000”；7.95 元写 `7950`，`0` 表示不限价位 |

### 4.4 `price` 请求字段到底怎么填

下面是一条完整请求。它表示：持续观察 `SZ002177` 的买盘 7.95 元价位，每次发生变化就推送。

```json
[{"type":"price","code":"SZ002177","enable":1,
  "direction":0,"priceCent":7950,"userParam":1001}]
```

逐字段解释：

| 字段 | 本例值 | 小白理解 |
|---|---:|---|
| `type` | `price` | 选择“单个价位排队变化”这个功能 |
| `code` | `SZ002177` | 要观察哪只股票；必须是市场前缀+6位数字 |
| `enable` | `1` | `1` 开始持续推送；`0` 停止；`2` 查询一次历史数据 |
| `direction` | `0` | `0` 观察买盘，`1` 观察卖盘 |
| `priceCent` | `7950` | 观察的价格。这里的 7950 是 7.950 元×1000，不是 7950 元 |
| `userParam` | `1001` | 你自己的编号，服务会原样返回；不用时可省略 |

#### `direction` 和 `priceCent` 的组合

- `direction=0, priceCent=7950`：买盘 7.95 元；
- `direction=1, priceCent=7950`：卖盘 7.95 元；
- `priceCent=0`：不锁定某一个价位，按该方向接收可用的价位变化；第一次使用建议填写具体价位，便于理解；
- 请求时 `priceCent` 的单位始终是“元×1000”。例如 10.23 元传 `10230`，0.85 元传 `850`。

退订时至少保留 `type`、`code`、`enable`、`direction` 和 `priceCent`，这样服务能准确找到要停止的订阅：

```json
[{"type":"price","code":"SZ002177","enable":0,
  "direction":0,"priceCent":7950}]
```

> `price` 的请求单位和响应单位很容易混淆：请求 `priceCent=7950` 表示 7.95 元；响应 `data.price=7950` 也表示 7.95 元，但响应换算仍应按“厘÷1000”。不要套用其他方法的“分÷100”。

#### `thousand`：千档深度

定期推送更完整的深度快照，数据量通常大于 `buysell`。

| 参数 | 默认 | 说明 |
|---|---:|---|
| `downLimit` | 0 | 跌停价过滤值，单位为厘；`0` 不限制 |
| `upLimit` | 0 | 涨停价过滤值，单位为厘；`0` 不限制 |

## 5. 响应格式：必须遍历 `list`

每次 `recv()` 收到的是一帧 JSON，不一定只包含一条行情：

```json
{
  "list": [
    {"type":"buysell","data":{"code":"SZ002177", "buyPrice":[7950] }},
    {"type":"trade","data":{"code":"SZ002177", "count":1}}
  ],
  "ts": 1777900000000
}
```

正确处理方式是：

1. 先解析整帧 JSON；
2. 取出 `list`，确认它是数组；
3. 遍历 `list` 中每一项；
4. 根据 `item["type"]` 分发；
5. 从 `item["data"]` 读取具体字段。

订阅确认或错误可能不是行情数据，例如：

```json
{"msg":"已订阅 buysell SZ002177","ts":1777900000000}
```

不要对所有消息都直接执行 `item["data"]["code"]`；先判断字段是否存在，否则确认消息会导致程序崩溃。

## 6. 数据结构

### 6.1 `buysell`

```json
{
  "code":"SZ002177", "buyTotalLevels":5, "buyLevelCount":2,
  "buyPrice":[7950,7940], "buyVolume":[1651,2486],
  "sellTotalLevels":5, "sellLevelCount":2,
  "sellPrice":[796,797], "sellVolume":[1200,1500]
}
```

买盘和卖盘都是平行数组：同一索引的价格、数量、金额属于同一档。主要字段：

| 字段 | 说明 |
|---|---|
| `code` | 股票代码 |
| `buyPrice` / `sellPrice` | 价格数组，单位厘，除以 1000 得元 |
| `buyVolume` / `sellVolume` | 各档委托量；UI 字段说明标为手数 | 原始值保留整数；d201 看板当前按金额格式化函数展示 |
| `buyAmount` / `sellAmount` | 金额数组，单位为分·手 |
| `buyLevelCount` / `sellLevelCount` | 本次实际返回的档位数 |
| `totalBuyVolume` / `totalSellVolume` | 返回范围内的总手数 |
| `totalBuyAmount` / `totalSellAmount` | 返回范围内的总金额 |

### 6.2 `trade`

```json
{
  "code":"SZ002177", "totalCount":60, "count":2,
  "time":[150000,150001], "seq":[253,254],
  "price":[795,796], "volume":[1,2],
  "buyOrderId":[60406924,60406925], "sellOrderId":[60458168,60460720]
}
```

字段为平行数组，索引 `i` 的各字段共同描述第 `i` 笔成交：`time` 时间 `HHmmss`，`seq` 成交序号，`price` 价格（分），`volume` 成交量（手），`active` 主动标志，`status` 状态码，`buySize`/`sellSize` 大单标志，`buyAmount`/`sellAmount` 金额（万）。

### 6.3 `entrust`

字段同样是平行数组：`time` 时间 `HHmmss`，`orderId` 委托号，`price` 价格（分），`volume` 委托量（手），`amount` 金额，`priceType` 报价类型，`size` 大小标志，`direction` `0` 买、`1` 卖。

```json
{"code":"SZ002177","count":2,"time":[145959,145959],"orderId":[60544210,60543597],"price":[795,795],"volume":[224,10],"direction":[0,0]}
```

### 6.4 `holoqueue`

顶层包含 `code`、`levelCount` 和 `levels`。每个 `levels` 项包含：`direction`（0 买、1 卖）、`price`（分）、`volume`（手）、`amount`、`bigOrder`、`queueCount`、`displayCnt` 和 `records`。`records` 按队列顺序排列，记录字段为 `volume`、`id`、`amount`、`bigOrder`、`status`。

`changeType=1` 表示替换价位，`removePrice` 是被移除的价位；`changeType=2` 表示更新价位。不要把 `displayCnt` 当成该价位的总排队笔数，完整笔数应看 `queueCount`。

### 6.5 `price`

主要字段：`isFirst`（1=含总量的首包/首段，0=增量）、`direction`、`price`、`totalVolume`、`totalAmount`、`totalCount`、`curCount`、`seq`、`records`。`records` 中每条记录有 `volume`、`id`、`amount`、`bigOrder`、`status`。

特别注意：`price` 请求参数 `priceCent` 按“元×1000”传入；响应中的 `price` 也是厘，换算元时除以 1000。D201 不同方法的价格单位不同：以本页“单位换算速查”和 UI 实际显示规则为准，不能把所有价格统一除以 100。

#### 6.5.1 一个完整的 `price` 响应

```json
{
  "userParam":1001,
  "code":"SZ002177",
  "direction":0,
  "price":7950,
  "isFirst":1,
  "totalVolume":2486,
  "totalAmount":1973884,
  "totalCount":112,
  "seq":0,
  "curCount":3,
  "records":[
    {"volume":30,"id":60386336,"amount":23820,"bigOrder":0,"status":0},
    {"volume":10,"id":60386337,"amount":7950,"bigOrder":1,"status":64},
    {"volume":5,"id":60386338,"amount":3975,"bigOrder":0,"status":64}
  ]
}
```

顶层字段逐项解释：

| 字段 | 含义 | 什么时候使用 |
|---|---|---|
| `userParam` | 你的订阅编号 | 同一连接订阅多个价位时，用它区分来源 |
| `code` | 股票代码 | 写入缓存时建议作为股票键 |
| `direction` | `0` 买、`1` 卖 | 与请求方向对应 |
| `price` | 被观察的价位，单位厘 | 除以 1000 得元；本例是 7.95 元 |
| `isFirst` | `1` 表示本段包含总量信息，`0` 表示增量段 | `isFirst=1` 可能连续出现多段，不能每段都清空本地数据 |
| `totalVolume` | 首段提供的该价位总剩余手数 | 只有首个 `isFirst=1` 才用于建立基线；增量包不要拿它覆盖当前总量 |
| `totalAmount` | 首段提供的该价位总金额原始值 | 只有首个 `isFirst=1` 才用于建立基线；保留整数即可 |
| `totalCount` | 首段提供的该价位总排队笔数 | 只有首个 `isFirst=1` 才用于建立基线 |
| `seq` | 全量快照中第一条记录在队列中的位置 | 用于把快照记录放到正确位置；不是成交序号 |
| `curCount` | 本条消息中 `records` 的条数 | 应等于 `len(records)`；以实际数组长度为准 |
| `records` | 委托队列记录 | 首次是队列片段，之后是发生变化的记录 |

记录字段逐项解释：

| 字段 | 含义 | 小白应该怎么理解 |
|---|---|---|
| `volume` | 这笔委托当前剩余的手数 | 增量消息里它是“变化后的剩余量”，不是本次减少量 |
| `id` | 委托号 | 同一价位内识别是哪一笔委托；处理更新和撤单时靠它定位旧记录 |
| `amount` | 这笔委托对应的金额原始值 | 适合原样保存；展示金额时使用接口单位，不能把它当作“元”直接打印 |
| `bigOrder` | 大单标志 | `0` 普通委托，非 0 表示大单标志；不要把它当成买卖方向 |
| `status` | 这次记录为什么出现或发生了什么变化 | 使用分类集合判断；未知值原样记录 |

#### 6.5.2 `isFirst`：首段、分段和增量消息的区别

同一次订阅通常按下面顺序工作：

```text
订阅成功
    ↓
isFirst=1：给出总量，并开始发送当前队列记录
    ↓
可能继续收到 isFirst=1：队列太长时分段补齐记录
    ↓
isFirst=0：发送新增、成交减少或撤单减少
```

处理规则：

1. 第一个 `isFirst=1`：读取 `totalVolume`、`totalAmount`、`totalCount`，建立总量基线，并把收到的 `records` 放入本地缓存。
2. 后续 `isFirst=1`：继续把记录按 `id` 合并到当前缓存；不要再次清空。UI 就是这样处理“首包分段”的。
3. 收到 `isFirst=0` 且状态是新增：把新记录追加到队尾，并把 `volume`、`amount` 加到总量。
4. 收到 `isFirst=0` 且状态是成交或撤单：按 `id` 找到旧记录，用“新值-旧值”更新总量；若新 `volume=0`，从本地队列删除。
5. 增量包里的 `totalVolume`、`totalAmount` 可能为 0，不能拿它们覆盖本地总量；UI 会根据新旧记录的差值维护总手和总金额。
6. 如果程序只收到增量、没有任何 `isFirst=1`，本地队列没有可靠基线，应重新订阅或重连。

#### 6.5.3 `status` 状态码完整解释

UI 对 `status` 的确定解释只有四类。它把状态值显示为：0 不显示；新增显示 `+`；成交后剩余显示 `T`；撤单或数量归零时清除。UI 同时明确提示：状态值可能是位标志组合，精确编码规律待确认。因此文档只把数值按“已确认的分类集合”解释，不把单个数字擅自解释成具体买卖方向。

| `status` | 中文含义 | 方向 | 记录中的 `volume` |
|---:|---|---|---|
| `0` | 无状态/初始排队记录 | 由上下文决定 | 当前剩余量 |
| `4, 12, 64, 192` | 新增 | 方向由 `direction` 和上下文确定 | 新委托进入队列时的量 |
| `1, 9, 16, 128, 144` | 成交 | 方向由 `direction` 和上下文确定 | 成交后的剩余量 |
| `2, 32` | 撤单 | 方向由 `direction` 和上下文确定 | 撤单后的剩余量；为 0 时清除 |

UI 对这三类状态的显示是：新增显示 `+`，成交后剩余显示 `T`，撤单不显示文字并在数量归零时移除记录。UI 还提示这些值可能是位标志组合，单个数字的精确编码规律待确认，所以不要在业务程序里写“4 一定是卖、64 一定是买”这样的硬编码。

实际编程时直接使用集合判断最安全：

```python
NEW_ORDER = {4, 12, 64, 192}
PARTIAL_FILL = {1, 9, 16, 128, 144}
CANCEL = {2, 32}

def event_name(status: int) -> str:
    if status in NEW_ORDER:
        return "new_order"
    if status in PARTIAL_FILL:
        return "partial_fill"
    if status in CANCEL:
        return "cancel"
    if status == 0:
        return "snapshot_or_unchanged"
    return "unknown"
```

几个最容易犯错的例子：

- 旧记录 `volume=100`，新记录 `volume=70`，状态属于“成交”集合：不是新增 70 手，而是减少 30 手，剩余 70 手；
- 旧记录 `volume=20`，新记录 `volume=0`，状态属于“撤单”集合：该委托已经没有剩余量，应从本地队列删除；
- 状态属于“新增”集合且 `volume=50`：新增 50 手委托；具体买卖方向看 `direction`，不要从状态数字猜。

#### 6.5.4 用 Python 维护单个价位队列

下面的代码展示核心逻辑。它不连接服务，只负责把收到的 `price.data` 合并为当前队列，适合直接放进自己的 WebSocket 程序：

```python
NEW_ORDER = {4, 12, 64, 192}
PARTIAL_FILL = {1, 9, 16, 128, 144}
CANCEL = {2, 32}

class PriceQueue:
    def __init__(self):
        self.records = []          # 按收到顺序保存字典；用 id 找记录
        self.by_id = {}
        self.total_volume = 0
        self.total_amount = 0
        self.total_count = 0
        self.ready = False

    def apply(self, data: dict):
        if data.get("isFirst") == 1:
            # 首个 isFirst=1 建立基线；后续 isFirst=1 可能只是分段补发。
            if not self.ready:
                self.total_volume = int(data.get("totalVolume", 0))
                self.total_amount = int(data.get("totalAmount", 0))
                self.total_count = int(data.get("totalCount", 0))
                self.ready = True
            for incoming in data.get("records", []):
                if int(incoming.get("volume", 0)) == 0:
                    continue
                order_id = int(incoming.get("id", 0))
                old = self.by_id.get(order_id)
                if old is None:
                    record = dict(incoming)
                    self.records.append(record)
                    self.by_id[order_id] = record
                else:
                    old.update(incoming)
            return

        if not self.ready:
            raise RuntimeError("尚未收到 isFirst=1，不能安全应用增量")

        for incoming in data.get("records", []):
            order_id = int(incoming.get("id", 0))
            new_volume = int(incoming.get("volume", 0))
            new_amount = int(incoming.get("amount", 0))

            if int(incoming.get("status", 0)) in NEW_ORDER:
                record = dict(incoming)
                self.records.append(record)
                self.by_id[order_id] = record
                self.total_volume += new_volume
                self.total_amount += new_amount
                self.total_count += 1
                continue

            old = self.by_id.get(order_id)
            if old is None:
                continue  # 本地起点不完整时，无法安全更新这笔委托

            old_volume = int(old.get("volume", 0))
            old_amount = int(old.get("amount", 0))
            self.total_volume += new_volume - old_volume
            self.total_amount += new_amount - old_amount
            if new_volume == 0:
                self.records.remove(old)
                del self.by_id[order_id]
                self.total_count = max(0, self.total_count - 1)
            else:
                old.update(incoming)

    def active_records(self):
        return list(self.records)
```

这段代码与 UI 的处理方式一致：首个 `isFirst=1` 建立基线，后续 `isFirst=1` 按 `id` 合并分段记录，`isFirst=0` 按新旧 `volume`/`amount` 差值维护汇总。真实程序还应定期检查本地总量与下一次首段总量是否一致。

### 6.6 `thousand`

```json
{"code":"SZ002177","totalCount":153,"curCount":2,"records":[{"price":7950,"volume":1651,"direction":0}]}
```

`records[].price` 单位为厘，除以 1000 得元；`volume` 单位为手，`direction` 为 `0` 买盘、`1` 卖盘。

### 6.7 其他输出字段字典

#### `buysell` 的字段

`buysell` 不返回 `records`，而是把每一档拆成多个平行数组。数组下标必须一一对应：`buyPrice[2]`、`buyVolume[2]`、`buyAmount[2]` 是同一个买盘档位。

| 字段 | 含义 |
|---|---|
| `flag` | 数据标志位；一般原样保存，业务不要用它判断买卖 |
| `totalBuyLevels` / `totalSellLevels` | 服务端可用的买/卖档总数 |
| `buyLevelCount` / `sellLevelCount` | 本次实际返回的档位数 |
| `buyPrice` / `sellPrice` | 各档价格，单位厘；买盘通常从高到低，卖盘通常从低到高 |
| `buyVolume` / `sellVolume` | 各档委托总量，UI 字段说明标为手数 | d201 看板当前通过金额格式化函数显示；客户端应保留原始整数 |
| `buySeq` / `sellSeq` | 各档序号或服务内部位置；只做原样保存，不当作委托号 |
| `buyField4` / `sellField4` | 原始协议标志字段；没有明确业务需求时原样保存 |
| `buyAmount` / `sellAmount` | 各档金额原始值，与队列金额使用同一量纲 |
| `totalBuyVolume` / `totalSellVolume` | 返回档位范围内的买/卖总手数 |
| `totalBuyAmount` / `totalSellAmount` | 返回档位范围内的买/卖总金额 |

#### `trade` 的字段

`trade` 也是平行数组，索引 `i` 表示同一笔成交。`count` 是本次数组长度，`totalCount` 是服务端当时知道的总成交笔数，二者不能混为一谈。这里的 `count` 仍然只是单次消息大小，不代表服务端只保存这么多成交。

| 字段 | 含义 |
|---|---|
| `time[i]` | 成交时间，格式 `HHmmss`，如 `093001` |
| `seq[i]` | 成交流水号；用于去重和检查是否漏数据 |
| `price[i]` | 成交价，分 |
| `volume[i]` | 本笔成交量，手 |
| `buyOrderId[i]` / `sellOrderId[i]` | 买方/卖方委托号 |
| `buyVolume[i]` / `sellVolume[i]` | 买方/卖方相关数量，手 |
| `active[i]` | 主动方向标志；不同市场状态可能有 0 或其他值，需保留原值 |
| `status[i]` | 成交状态原始值；没有稳定业务解释时不要擅自映射 |
| `buySize[i]` / `sellSize[i]` | 买方/卖方大小或大单标志 |
| `buyAmount[i]` / `sellAmount[i]` | 买方/卖方金额，单位万 |

#### `entrust` 的字段

`entrust` 的每一个数组长度通常等于 `count`，但程序必须以实际数组长度为准。`count` 不要填写 5000；要获取更多历史委托，应根据序号分页。第 `i` 个元素共同描述第 `i` 笔委托：

| 字段 | 含义 |
|---|---|
| `time[i]` | 委托时间，`HHmmss` |
| `orderId[i]` | 委托流水号；可用作该笔委托的唯一识别值 |
| `price[i]` | 委托价格，分 |
| `volume[i]` | 委托数量，手 |
| `amount[i]` | 委托金额原始值 |
| `priceType[i]` | 报价类型原始值；没有具体业务映射时保留数字 |
| `size[i]` | 大小标志原始值 |
| `direction[i]` | `0` 买，`1` 卖 |

#### `holoqueue` 的字段

`holoqueue.levels` 是“价位数组”，每个价位又有 `records` 排队明细：

| 字段 | 含义 |
|---|---|
| `changeType` | `0` 删除价位，`1` 替换价位，`2` 更新价位 |
| `direction` | `0` 买，`1` 卖 |
| `removePrice` | 只有替换价位时有意义，表示被移除的旧价位；单位分 |
| `price` | 当前价位，分 |
| `volume` | 当前价位所有委托总手数 |
| `amount` | 当前价位总金额原始值 |
| `bigOrder` | 当前价位是否包含大单标志 |
| `queueCount` | 当前价位实际排队总笔数 |
| `displayCnt` | 本次实际展示的明细笔数，不是总排队笔数 |
| `records[].volume` | 某笔排队委托的手数 |
| `records[].id` | 某笔排队委托号 |
| `records[].amount` | 某笔排队金额原始值 |
| `records[].bigOrder` | 该笔是否大单 |
| `records[].status` | 该笔事件状态，解释方式与 `price.records[].status` 相同 |

特殊清空信号：当 `changeType=1`、`removePrice` 不为 0 且当前 `price=0` 时，UI 将它解释为“清空 `removePrice` 这个价位”，而不是创建一个 0 元价位。普通程序也应先处理这个信号，再处理 `price=0` 的过滤。

## 7. 如何判断“我收到的数据是否完整”

新手程序建议每条数据都做以下检查：

```python
def check_price_data(data: dict) -> None:
    records = data.get("records") or []
    cur_count = int(data.get("curCount", 0))
    if cur_count != len(records):
        print("警告：curCount 与 records 长度不一致")
    if data.get("isFirst") == 1:
        total_count = int(data.get("totalCount", 0))
        seq = int(data.get("seq", 0))
        if seq < 0 or seq + len(records) > total_count:
            print("警告：首次快照的 seq/totalCount/records 范围异常")

def check_parallel_arrays(data: dict, names: list[str]) -> None:
    lengths = {name: len(data.get(name) or []) for name in names}
    if len(set(lengths.values())) > 1:
        print("警告：平行数组长度不一致：", lengths)
```

`check_parallel_arrays(data, ["buyPrice", "buyVolume"])` 可用于检查盘口数组；交易和委托也应做相同检查。遇到不一致时保留原始消息并记录日志，不要用 `zip` 静默截断数据。

## 8. 单位换算速查

| 数据或字段 | 原始单位 | 转成人能看懂的元 |
|---|---|---|
| `holoqueue` 的 `price`、`removePrice` | 分 | `price / 100`；看板按此显示价位 |
| `buysell` 的 `buyPrice` / `sellPrice` | 厘 | `price / 1000`；看板按此显示盘口价位 |
| `thousand` 的 `records[].price` | 厘 | `price / 1000`；看板按此显示千档价位 |
| `entrust`、`trade` 的 `price` | 分 | `price / 100` |
| `price` 请求的 `priceCent` | 元×1000 | `priceCent / 1000` |
| `price` 响应的 `price` | 厘 | `price / 1000` |
| 数量 | 手 | `手数 × 100` 股 |
| `amount`、`buyAmount` 等金额原始值 | 看板按内部金额值展示 | 看板 `fmtAmt` 使用 `原值 / 10000`，并以“万”显示 |

注意：D201 不同方法的价格单位确实不完全相同，这是 UI 实际代码的处理方式，不要为了统一而全部除以 100。金额字段建议保留原始整数；如果要与看板显示一致，使用 `原值 / 10000` 转成“万”，不要把原始值直接当作元。

## 9. 稳定运行模板

生产程序至少要做到：

```python
import json
import time
import websocket

URL = "ws://127.0.0.1:8080/d201"
REQUEST = [{"type":"buysell", "code":"SZ002177", "enable":1,
            "buyLevels":10, "sellLevels":10}]

while True:
    ws = None
    try:
        ws = websocket.create_connection(URL, timeout=10)
        ws.send(json.dumps(REQUEST))
        while True:
            message = json.loads(ws.recv())
            for item in message.get("list", []):
                if item.get("type") == "error":
                    print("服务错误：", item.get("msg"))
                elif item.get("type") == "buysell":
                    data = item.get("data") or {}
                    print("最新数据：", data.get("code"))
    except KeyboardInterrupt:
        break
    except Exception as exc:
        print("连接断开，5 秒后重连：", exc)
        time.sleep(5)
    finally:
        if ws is not None:
            ws.close()
```

断线后必须重新发送全部订阅命令。多只股票时建议按股票或业务拆分连接，并用 `data.code` 做缓存键；收到一帧消息时必须遍历完整 `list`。`trade`、`entrust` 等增量数据可用序号检查重复或缺口。

## 10. 常见问题

| 现象 | 处理方法 |
|---|---|
| `Connection refused` | 检查服务是否启动、端口是否为 8080、地址是否为 `127.0.0.1` |
| 连接成功但只有确认消息 | 检查代码格式、登录状态、数据权限和交易时段 |
| 程序提示没有 `data` | 先处理确认/错误消息，再读取 `data` |
| 只收到一部分数据 | 检查是否遍历 `list`；不要把一次 `recv()` 当成一条记录 |
| 运行约一分钟断开 | 使用支持自动 Ping/Pong 的库，或实现 Pong 回复 |
| 重连后没有行情 | 重连成功后重新发送订阅命令 |
| 价格显示大 100 倍或小 1000 倍 | 按“单位换算速查”区分分、厘和 `priceCent` |
