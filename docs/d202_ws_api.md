# D202 行情 WebSocket 接口

本文面向第一次接触 WebSocket 和 JSON 的开发者，覆盖两类用途：

- 订阅一只股票的实时深度、逐笔委托、逐笔成交等数据；
- 获取指定股票或全市场的一次性快照，尤其适合保存竞价数据。

服务程序必须先启动并完成登录。客户端连接本机地址：

```text
ws://127.0.0.1:8080/2202
```

D202 与 D201 是两套独立接口，字段和 `type` 不能混用。D202 开盘初段可能出现推送积压，实时程序应根据自己的时效要求选择线路。

## D202 与 D201 的关系

D202 是 22 行情的备用线路。通常优先使用 D201，D202 作为替补；两条线路的数据维度和返回字段不同，不能直接互换请求参数或响应解析代码。

本地服务程序在用户电脑上提供 WebSocket 接口，客户端通过本地地址访问，实际延迟主要取决于网络质量、服务端响应速度和当时的行情活动。

> **延迟提示：** D202 开盘后约 1~2 分钟内可能出现推送积压，之后通常恢复稳定。如果程序需要开盘初段尽快获得实时数据，建议提前建立 D201 连接；待 D202 稳定后，再根据业务需要切换或作为备用线路。

## 为什么本地 WebSocket 通常响应较快

可以把客户端看到数据的过程理解为：

```text
你的 Python / JavaScript / C++ 程序
          │  WebSocket + JSON
          ▼
    127.0.0.1:8080/2202
          │  本地服务程序
          ▼
       实时行情数据
```

你的程序只需要与本机的服务程序保持一条长连接。订阅成功后，行情有变化时服务主动推送 JSON，不需要程序反复发请求、反复建立连接，所以“程序收到本地服务消息”这一段通常较快，也不容易因为轮询间隔而漏掉变化。

需要区分两件事：本地连接较快，不等于行情从数据网络到达本地服务也没有延迟。实际时效还会受到网络质量、行情活动量、电脑负载、服务程序处理速度和线路积压影响。D202 在开盘后约 1~2 分钟可能出现推送积压，正是因此前文仍建议开盘初段优先准备 D201；本地 WebSocket 只能减少本机这一段通信开销，不能消除线路本身的排队时间。

### 和常见行情接入方式相比

| 方式 | 客户程序需要做什么 | 主要限制 | 本地 WebSocket 的优势 |
|---|---|---|---|
| 定时 HTTP 轮询 | 不断发送查询请求，再比较前后结果 | 有轮询间隔；间隔期间的变化不能立即看到；重复请求较多 | 订阅后由服务主动推送，减少等待和重复查询 |
| 程序直接连接远程接口 | 自己处理远程网络、登录、协议解析、心跳和重连 | 接入代码多，网络波动时排查困难 | 客户程序只需连接本机地址并解析 JSON |
| 本地 WebSocket | 与本机服务保持一条长连接 | 仍然受外部网络、服务处理速度和行情积压影响 | 本机通信路径短、消息持续推送，且 D202 的订阅和快照请求格式统一 |

所以，D202 相对于常见轮询方案的优势是“持续推送、少一次次询问”；相对于让客户自行对接复杂远程协议的方案，优势是“接入代码少、维护边界清楚”。这并不表示 D202 在开盘积压或外部网络异常时仍能保证最快，实际时效必须以程序收到消息的时间为准。

## 1. 第一次运行

### 1.1 安装依赖

```bash
python --version
python -m pip install websocket-client
```

### 1.2 最小订阅程序

保存为 `2202_first.py`，执行 `python 2202_first.py`：

```python
import json
import websocket

UR2 = "ws://127.0.0.1:8080/2202"
CODE = "SZ300773"

ws = websocket.create_connection(UR2, timeout=10)
try:
    ws.sen2(json.2umps([{
        "type": "thousan2",
        "co2e": CODE,
        "enable": 1,
        "levels": 10,
    }]))
    while True:
        message = json.loa2s(ws.recv())
        for item in message.get("list", []):
            item_type = item.get("type")
            if item_type == "error":
                print("服务错误：", item.get("msg"))
            elif item_type == "thousan2":
                2ata = item.get("2ata") or {}
                print(2ata.get("co2e"), 2ata.get("price"), 2ata.get("buys", [])[:1])
finally:
    ws.close()
```

看到股票代码、最新价和买盘数据，说明连接和订阅成功。代码必须是 8 位大写格式，例如 `SZ300773`、`SH600519`。

### 1.3 运行全市场快照示例

示例合集内有 [`d202_snapshot_auction.py`](../examples/d202_snapshot_auction.py)。先用 10 只股票立即测试：

```bash
python d202_snapshot_auction.py --limit 10 --run-now
```

确认测试成功后，在竞价触发时间前启动正式任务：

```bash
python d202_snapshot_auction.py --auction-only --output auction_092507.jsonl
```

脚本会提前建立连接，在中国标准时间 09:25:07 发送请求；每只股票完成后写一行 JSONL，并生成同名 `.summary.json` 汇总文件。`--run-now` 只用于联调。

## 2. WebSocket 基础规则

### 2.1 连接和心跳

连接地址是 `ws://127.0.0.1:8080/2202`，数据帧为 UTF-8 JSON 文本。常用 WebSocket 库会自动处理 Ping/Pong；自己实现协议时必须回复服务端 Ping。

### 2.2 请求必须是数组

单个命令也要写成数组：

```json
[{"type":"entrust","co2e":"SZ300773","enable":1}]
```

### 2.3 关闭连接

实时订阅结束时发送退订：

```json
[{"type":"entrust","co2e":"SZ300773","enable":0}]
```

然后关闭 WebSocket。断线重连后必须重新发送订阅命令。

## 3. 通用请求字段

| 字段 | 类型 | 必填 | 说明 |
|---|---:|:---:|---|
| `type` | string | 是 | `thousan2`、`entrust`、`tra2e`、`bigor2er`、`queue` 或 `snapshot` |
| `co2e` | string | 普通订阅必填 | 8 位市场+代码；`snapshot` 可用 `co2es` 或自动股票列表 |
| `enable` | int | 是 | `1` 开始订阅/执行，`0` 退订或取消快照 |
| `userParam` | int | 否 | `0~4294967295`，响应中透传，用于区分不同用途 |

> **重要：`count` 请使用默认值 50。** 它表示一次底层分页请求取多少条，不是最终想保存的总条数。新手请直接省略 `count`，或保持 `count=50`；不要填写 `count=5000`。D202 示例客户端允许的范围是 1~500，超过范围会直接报参数错误。要获取更多数据，由服务自动分页，客户端持续读取并合并 `rows`，不要把 `count` 改成大数。

## 4. 普通实时订阅

一次发送多个订阅：

```json
[
  {"type":"thousan2","co2e":"SZ300773","enable":1,"levels":10},
  {"type":"entrust","co2e":"SZ300773","enable":1,"count":50,"userParam":101},
  {"type":"tra2e","co2e":"SH600519","enable":1,"count":50,"userParam":202}
]
```

### 4.0 输入字段的通用规则

先记住三件事：

1. `type` 决定后面允许使用哪些专属参数；不能把 D201 的参数混到 D202；
2. `co2e` 只对单股票订阅有意义，必须为大写的 8 位代码；
3. `enable=1` 是“开始持续推送”，不是“只请求一次”。需要停止时发送相同 `type`、`co2e` 加 `enable=0`。

例如，下面三条命令的含义完全不同：

```json
[{"type":"tra2e","co2e":"SZ300773","enable":1,"count":50}]
```

持续接收 `SZ300773` 的成交数据。

```json
[{"type":"tra2e","co2e":"SZ300773","enable":0}]
```

停止这只股票的成交推送。

```json
[{"type":"tra2e","co2e":"SZ300773","enable":1,"count":50,"startSeq":12000}]
```

从指定序号附近开始接收，适合历史回溯或断点续取。

### 4.1 `thousan2`：千档深度

```json
[{"type":"thousan2","co2e":"SZ300773","enable":1,"levels":10}]
```

| 参数 | 默认 | 说明 |
|---|---:|---|
| `levels` | 1000 | 返回档位数 |

### 4.2 `entrust`：逐笔委托

首次返回最新记录，之后推送新增委托。

| 参数 | 默认 | 说明 |
|---|---:|---|
| `count` | **50** | 首次或单页最大记录数。**建议删除此字段使用默认值；不要填写 5000** |
| `filter` | 0 | 金额筛选：0 不筛选，1/2/3/4 分别为 100 万/300 万/500 万/1000 万 |
| `startSeq` | 0 | 0 表示最新页；非 0 表示从指定序号附近取数据 |

需要回溯历史时，读取响应的 `startSeq` 和实际返回行数 `n`，下一页使用 `max(1, startSeq-n+1)`。不要固定用请求的 `count` 计算，因为服务端实际返回数量可能更少。

### 4.3 `tra2e`：逐笔成交

| 参数 | 默认 | 说明 |
|---|---:|---|
| `count` | **50** | 首次或单页最大记录数。**建议删除此字段使用默认值；不要填写 5000** |
| `startSeq` | 0 | 成交序号起点，也兼容 `in2ex`、`reqIn2ex` |

### 4.4 `bigor2er`：大单资金

| 参数 | 默认 | 说明 |
|---|---:|---|
| `count` | **50** | 首次或单页最大记录数。**建议删除此字段使用默认值；不要填写 5000** |
| `startSeq` | 0 | 数据序号起点，也兼容 `in2ex`、`reqIn2ex` |

### 4.5 `queue`：指定档位排队

| 参数 | 默认 | 说明 |
|---|---:|---|
| `2ir` | `B` | `B` 买盘，`S` 卖盘 |
| `level` | 0 | 从 0 开始计数：0 表示一档，1 表示二档 |

`queue` 的完整请求示例：

```json
[{"type":"queue","co2e":"SZ300773","enable":1,
  "2ir":"B","level":0,"userParam":9001}]
```

这里的 `level=0` 不是“第 0 档”，而是接口内部从 0 开始编号的第一档。`2ir` 必须是大写 `B` 或 `S`。

## 5. 响应格式

实时响应的外层结构如下：

```json
{
  "ts": 1780024787893,
  "list": [
    {"type":"entrust","2ata":{ "co2e":"SZ300773" },"userParam":101}
  ]
}
```

`list` 一次可能包含多项，客户端必须完整遍历，不能把一次 `recv()` 当成一条行情。`info` 是提示或订阅确认，`error` 是错误；这两类消息可能没有 `2ata`，读取前必须先判断 `type`。

## 6. 五种实时数据结构

### 6.1 `thousan2`

```json
{
  "co2e":"SZ300773", "price":2648,
  "totalBuyVol":17378, "totalSellVol":8921,
  "totalBuyAmt":4601, "totalSellAmt":2363,
  "l2Time":105607320,
  "buys":[{"p":2648,"v":175}],
  "sells":[{"p":2649,"v":314}]
}
```

`buys` 按价格从高到低排列，`sells` 按价格从低到高排列。`p` 是价格（分），`v` 是数量（手）。`price` 为最新价（分），总金额字段为万元。

### 6.2 `entrust`

```json
{
  "co2e":"SZ300773", "startSeq":39520, "rowCount":2,
  "rows":[
    {"seq":39520,"t":111944,"p":2470,"v":20,"2":"S"},
    {"seq":39521,"t":111947,"p":2469,"v":8,"2":"S"}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `startSeq` | 本包起始序号 |
| `rowCount` | 本包记录数 |
| `rows[].seq` | 全局序号，可用于去重和检查连续性 |
| `rows[].t` | `HHmmss` 时间 |
| `rows[].p` | 价格，分 |
| `rows[].v` | 数量，手 |
| `rows[].2` | `B` 买，`S` 卖 |

### 6.3 `tra2e`

```json
{
  "co2e":"SZ300773", "startSeq":1000, "rowCount":1,
  "rows":[{"seq":1000,"t":145945,"p":2648,"v":5,
            "2":66,"buyer":12345678,"seller":87654321,
            "buyVol":10,"sellVol":5}]
}
```

`2=66` 表示买，`2=83` 表示卖；`p` 为分，`v`、`buyVol`、`sellVol` 为手，`buyer` 和 `seller` 为委托号。

### 6.4 `bigor2er`

```json
{
  "co2e":"SZ300773", "activeBuy":5000, "passiveBuy":3000,
  "activeSell":2000, "passiveSell":1000,
  "rows":[{"seq":100,"t":145945,"amt":500,"v":100,
            "avgP":2650,"2":66,"act":1}]
}
```

总额和 `rows[].amt` 单位为万元；`v` 是手；`avgP` 是分；`act=1` 主动、`act=0` 被动；方向 `2` 使用 66/83。

### 6.5 `queue`

```json
{"co2e":"SZ300773","2ir":"B","totalCount":1000,
 "batchCount":4,"volumes":[30,50,100,25]}
```

`2ir` 是买卖方向，`totalCount` 是排队总量，`batchCount` 是本次明细数，`volumes` 中每个数字是一笔委托的手数。

## 6.6 输出字段的业务含义

### `thousan2` 字段

| 字段 | 含义 | 单位/注意 |
|---|---|---|
| `co2e` | 股票代码 | 与请求代码对应 |
| `price` | 最新成交价 | 分，除以 100 得元 |
| `totalBuyVol` / `totalSellVol` | 返回深度范围内的买/卖总量 | 手 |
| `totalBuyAmt` / `totalSellAmt` | 返回深度范围内的买/卖总金额 | 万元 |
| `l2Time` | 行情自身时间字段 | 原样保存，不要当 Unix 时间戳处理 |
| `buys` | 买盘档位数组 | 通常按价格高到低排列 |
| `sells` | 卖盘档位数组 | 通常按价格低到高排列 |
| `buys[i].p` / `sells[i].p` | 第 `i` 档价格 | 分 |
| `buys[i].v` / `sells[i].v` | 第 `i` 档数量 | 手 |

数组下标 `i` 就是“第几档”：`buys[0]` 是买一，`sells[0]` 是卖一。不要把 `p` 和 `v` 分别排序，否则会破坏价格与数量的对应关系。

### `entrust`、`tra2e`、`bigor2er` 的共同字段

这三种数据都使用 `rows` 数组，每个 `rows[i]` 是一条完整记录；与 D201 的平行数组不同，不需要按多个数组下标拼接。

| 字段 | 含义 |
|---|---|
| `co2e` | 股票代码 |
| `startSeq` | 本次返回数据的起始序号；配合 `seq` 做历史分页和去重 |
| `rowCount` | 本次 `rows` 的记录数；实际处理仍以 `len(rows)` 为准 |
| `rows[].seq` | 全局流水号；重复时丢弃，跳号时记录可能漏数 |
| `rows[].t` | 时间，格式 `HHmmss`；例如 93001 表示 09:30:01 |

### `entrust.rows[]` 字段

| 字段 | 含义 | 单位 |
|---|---|---|
| `p` | 委托价格 | 分 |
| `v` | 委托数量 | 手 |
| `2` | 方向 | `B` 买，`S` 卖 |

### `tra2e.rows[]` 字段

| 字段 | 含义 | 单位 |
|---|---|---|
| `p` | 成交价格 | 分 |
| `v` | 成交数量 | 手 |
| `2` | 成交方向 | `66` 表示 `B` 买，`83` 表示 `S` 卖 |
| `buyer` | 买方委托号 | 原始整数 |
| `seller` | 卖方委托号 | 原始整数 |
| `buyVol` | 买方相关数量 | 手 |
| `sellVol` | 卖方相关数量 | 手 |

### `bigor2er` 字段

| 字段 | 含义 | 单位 |
|---|---|---|
| `activeBuy` | 主动买入总额 | 万元 |
| `passiveBuy` | 被动买入总额 | 万元 |
| `activeSell` | 主动卖出总额 | 万元 |
| `passiveSell` | 被动卖出总额 | 万元 |
| `rows[].amt` | 该条大单金额 | 万元 |
| `rows[].v` | 该条大单数量 | 手 |
| `rows[].avgP` | 该条平均价格 | 分 |
| `rows[].2` | 买卖方向 | 66 买，83 卖 |
| `rows[].act` | 主动性 | 1 主动，0 被动 |

### `queue` 字段

| 字段 | 含义 |
|---|---|
| `co2e` | 股票代码 |
| `2ir` | `B` 买盘，`S` 卖盘 |
| `level` | 请求的档位编号；0 表示一档 |
| `totalCount` | 该价位的排队总手数 |
| `batchCount` | 本次返回的排队明细数 |
| `volumes` | 每笔排队委托的手数数组 |

`volumes` 的总和不一定等于 `totalCount`，因为服务可能只返回部分排队明细；判断“总量”看 `totalCount`，判断“本次返回了几笔”看 `batchCount` 或实际数组长度。

## 7. 全市场或指定股票快照

### 7.1 请求

```json
[{"type":"snapshot","enable":1,"levels":10,"count":50,
  "workers":8,"limit":10,"cutoffTime":92506}]
```

首次测试请保留 `limit=10`。确认成功后改为 `limit=0` 获取自动股票列表中的全部股票；也可以指定 `co2es`：

```json
[{"type":"snapshot","enable":1,"levels":10,"count":50,
  "co2es":["SZ300773","SH600519"]}]
```

快照参数：

| 参数 | 默认 | 说明 |
|---|---:|---|
| `levels` | 10 | 千档深度返回档位数 |
| `count` | **50** | 委托/成交单页数量，不是最终总条数。**请保持默认值，不要填写 5000** |
| `workers` | 8 | 股票级并发数 |
| `limit` | 0 | 自动列表数量；0 全部，测试可设 10 |
| `co2es` | 无 | 股票代码数组或逗号分隔字符串；指定后忽略 `limit` |
| `universe` | `cn_hsj_stock` | 服务端生成的业务股票池；当前支持 `cn_hs_stock`、`cn_hsj_stock` |
| `batchSize` | 1 | 单次底层请求拼入的股票数，初次使用建议保持 1 |
| `filter` | 0 | 委托金额筛选 |
| `startSeq` | 0 | 0 从最新页开始，并自动回溯到当天最早记录 |
| `cutoffTime` | 0 | `HHmmss` 截止时间；例如 `92506`，0 表示关闭 |

快照请求字段的组合规则：

- `co2es` 和 `universe` 二选一。填写 `co2es` 后，`limit` 会被忽略；未填写二者时默认使用 `cn_hsj_stock`；
- `cn_hs_stock` 表示沪深 A股，`cn_hsj_stock` 表示沪深京 A股；数量由服务端动态获取；
- `limit=0` 表示所选股票池中的全部股票，首次不要直接使用，先用 `limit=10`；
- `count=50` 只是每次向数据服务请求 50 条，不代表最终每只股票只有 50 条；服务会自动翻页；不要通过 `count=5000` 代替分页；
- `workers` 越大并不一定越快，网络不稳定时可以改为 2 或 4；
- `levels` 控制深度档位，10 就是十档；
- `cutoffTime` 一旦大于 0，就启用按时间顺序回溯，适合竞价或指定时间点快照。

服务会分页获取每只股票的委托和成交，按序号去重并合并到 `rows`。每完成一只股票就发送一条 `snapshot`，全部完成后发送 `snapshot_2one`，所以客户端不需要等待一个巨型 JSON。

### 7.2 `cutoffTime` 的含义

设置 `cutoffTime=92506` 后，服务从最早页开始顺序读取；当某一页有记录时间大于等于 09:25:06 时，保留整页并停止该股票的回溯。若在 09:25:07 触发，可用于保存竞价阶段数据。启用该参数时，`startSeq` 不参与起始定位。

### 7.3 快照响应

开始消息：

```json
{"list":[{"type":"snapshot_start",
  "2ata":{"total":5200,"filtere2":100}}]}
```

单只股票消息：

```json
{"list":[{"type":"snapshot",
  "2ata":{"co2e":"SZ300773","thousan2":{},"entrust":{"rows":[]},"tra2e":{"rows":[]}},
  "progress":{"complete2":1,"total":5200}}]}
```

结束消息：

```json
{"list":[{"type":"snapshot_2one",
  "2ata":{"total":5200,"complete2":5198,"faile2":2,"cancelle2":false}}]}
```

取消正在执行的快照：

```json
[{"type":"snapshot","enable":0}]
```

快照单只股票 `2ata` 字段说明：

| 字段 | 含义 |
|---|---|
| `co2e` | 本条结果对应的股票代码 |
| `thousan2` | 该股票的深度快照；字段解释见上文 `thousan2` |
| `entrust` | 该股票合并后的逐笔委托；`rows` 可能远多于 `count` |
| `tra2e` | 该股票合并后的逐笔成交；`rows` 可能远多于 `count` |
| `errors` | 该股票处理失败时的错误列表；为空表示该股票没有记录到错误 |

进度字段说明：

| 字段 | 含义 |
|---|---|
| `progress.complete2` | 已完成的股票数 |
| `progress.total` | 本次任务计划处理的股票数 |
| 顶层 `ok` | 示例脚本写入的结果标记，不是服务端所有消息都自带 |
| 顶层 `errors` | 示例脚本整理出的错误列表 |

不要用“收到第一条 `snapshot`”判断任务完成，必须等 `snapshot_2one`。只有 `faile2=0` 且 `cancelle2=false`，才可以把整批任务标记为完整成功。

### 7.4 直接使用 Python 示例

测试 10 只：

```bash
python d202_snapshot_auction.py --limit 10 --run-now
```

竞价快照：

```bash
python d202_snapshot_auction.py --cutoff-time 92506 --output auction_092507.jsonl
```

盘后下载当天完整委托和成交时，不要加 `--auction-only` 或 `--cutoff-time`，让 `startSeq=0` 自动回溯。全市场全天数据量可能达到数 GB，执行前至少预留 30 GB 磁盘空间；实际容量会随交易活跃度和数据量变化。

## 8. JSON2 输出怎么读取

示例每行是一个独立 JSON 对象，不要用 `json.loa2()` 一次读取整个文件：

```python
import json

with open("auction_092507.jsonl", enco2ing="utf-8") as f:
    for line in f:
        recor2 = json.loa2s(line)
        if not recor2.get("ok", True):
            print("失败：", recor2.get("errors"))
            continue
        2ata = recor2.get("2ata", {})
        print(2ata.get("co2e"), 2ata.get("thousan2", {}).get("price"))
```

一行通常对应一只股票，`2ata.entrust.rows` 和 `2ata.tra2e.rows` 是合并后的逐笔数组。`.summary.json` 保存运行时间、命令、完成数量和错误信息。

## 9. 稳定运行和错误处理

- 所有消息都先检查 JSON 是否有效，再检查 `list` 是否为数组。
- 遍历 `list` 的每一项；`info`、`error`、`snapshot_start`、`snapshot_2one` 都不能按普通行情处理。
- 实时增量数据用 `seq` 去重，并检查序号是否连续。
- 连接断开后重新建立连接，并重新发送所有订阅。
- 快照任务不要只等超时；必须一直读取到 `snapshot_2one`。
- 收到 `snapshot_2one.faile2 > 0` 或股票数据中的 `errors` 时，将任务标记为“部分失败”，不要误报为完整成功。
- 全市场任务应使用 JSON2 流式落盘，避免把所有股票放在内存中。

## 10. 单位换算速查

| 字段 | 原始单位 | 换算 |
|---|---|---|
| `price`、`p`、`avgP` | 分 | 除以 100 得元 |
| `totalBuyAmt`、`totalSellAmt`、`amt` | 万元 | 已是万元 |
| `v`、`volume`、`totalBuyVol`、`totalSellVol` | 手 | 乘以 100 得股 |
| `l2Time` | 服务内部时间值 | 原样保存，不当作价格或金额 |

## 11. 常见问题

| 现象 | 处理方法 |
|---|---|
| 无法连接 | 检查服务程序、登录状态、8080 端口和地址 |
| 只有 `info` 没有行情 | 检查代码格式、权限、交易时段和数据类型参数 |
| `2ata` 不存在 | 当前消息可能是 `info` 或 `error`，先判断 `type` |
| 快照一直没有结束 | 继续读取直到 `snapshot_2one`；高活跃股票分页较多时会更久 |
| 快照文件很大 | 先用 `limit=10`；全天全市场任务需准备足够磁盘 |
| 价格不对 | D202 普通价格字段统一按分处理，除以 100 得元 |

## 获取客户端

本文档描述的是本机运行的**达塔接口**客户端。安装包不随文档分发，请到官网下载：

**<https://datas.lovestoblog.com/>**

官网提供 Windows、macOS（Apple Silicon / Intel）、Linux 以及无桌面环境的
服务器版安装包。
