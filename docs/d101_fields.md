# D101 完整行情字段目录

> 本目录覆盖当前可用的 203 个正式字段；单条 `snapshot` 最多请求 255 个字段。JSON 响应保留原始数值、文本和空值约定；下表的“换算规则”只说明客户端如何生成显示值，不改变线上响应。
>
> 价格字段必须使用同一行的 `decimal_num`：显示值 = `raw / 10**decimal_num`。`display_decimal_num` 只控制显示位数，不是价格除数。比例、金额、数量和股本分别按字段规则处理，不能全表统一除以 100。
>
> `tick_vol`（现手）是现手数量，方向在独立字段 `buy_sell_flag`；`tick_vol` 不以负数表示买卖。`buy_sell_flag` 的取值枚举为 `0=NONE`、`1=SELL`、`2=BUY`、`3=UNKNOWN`、`4=AUCTION`，响应仍保留原始数字。
>
> D101 是“字段变化才推送”的增量行情：字段被选中只表示它允许出现在推送中，不表示每一帧都会重复发送。GUI 默认集合保留身份、精度、低频参考基线、品种单位元数据，以及最新价、最高/最低价、均价、成交量和主力净流入；现手、买卖方向、盘口等高频字段按需增加。
>
> 请求字段时应优先选择任务需要的最小集合。最新价、昨收价、最高价、最低价和均价已经返回时，涨跌幅、涨跌额、振幅、实体涨幅、开盘/昨收比、若干日线涨幅、现价均价差和成交额可在客户端计算，不必为显示这些结果重复请求服务端字段。面向 AI agent 的程序不要把全部 203 个字段作为默认请求；只有原始字段核对、采样或明确业务需要时才请求全部字段。当前单条 `snapshot` 命令可请求完整 203 个字段；代码数量超过单条底层连接的 6000 只容量时，由服务端在同一条命令内部按代码分批。
>
> GUI 的成交额本地值按“成交量 × 均价”实现，但计算前会先用 `decimal_num` 还原均价，再按品种成交单位换算：当前已覆盖样本确认的 A股/ETF（100 份/手）、`SO`/`ZO` 期权（10,000 份/张）、中金所期权（100 单位/张）、`DCE|jmm`（60 吨/手）和美股（1 股/股）。指数及未知单位不自行伪造成交额；若必须使用服务端精确原始值，显式请求 `amount`。

## GUI 默认集合可以生成的字段

下面的百分比公式结果乘以 `10000` 后，才是 D101 原始百分数字段；界面再按目录规则除以 `100` 显示。价格差保留价格原始单位。`amount` 因均价本身有精度限制，是本地估算值；服务端 `amount` 仍可用于精确对照。

```text
change_pct              = (price - pre_close) / pre_close × 10000
change_amt              = price - pre_close
amplitude               = (high - low) / pre_close × 10000
body_change_pct         = (price - open_price) / open_price × 10000
open_pre_ratio          = open_price / pre_close × 10000
price_avg_diff          = price - avg_price
amount                  ≈ volume × (avg_price / 10**decimal_num) × 品种成交单位换算因子

this_month_pct          = (price - last_month_price) / last_month_price × 10000
this_year_pct           = (price - last_year_price) / last_year_price × 10000
change_pct_20d          = (price - prev_19_price) / prev_19_price × 10000
change_pct_recent_year  = (price - prev_249_price) / prev_249_price × 10000
change_pct_5d           = (price - prev4_price) / prev4_price × 10000

turnover_ratio          ≈ volume / float_share × `volume_unit_flag` 成交量单位换算因子
real_turnover_ratio     ≈ volume / free_float_market_share × `volume_unit_flag` 成交量单位换算因子
inner_outer_ratio       ≈ inner_vol / outer_vol × 100
order_buy_sell_diff     = order_buy_volume - order_sell_volume
```

这些字段只在依赖值有效且同一资产行可用时生成；若推送是增量帧，客户端应先按 `code` 合并缓存，再重新计算。不能从已有基础值确定的指标（例如没有对应参考价的 3/10/60 日统计和资金指标）仍应按需请求原始字段。

| JSON 字段 | 含义 | 单位 | 换算规则 | 可信度 |
|---|---|---|---|---|
| `price` | 最新价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `high` | 当日最高价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `low` | 当日最低价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `pre_close` | 昨收价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `volume` | 累计成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `amount` | 累计成交额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `total_share` | 总股本 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `net_share` | 流通/净股本 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 中 |
| `pe_ratio` | 市盈率（通用口径） | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `code` | 带市场标识的证券代码 | 文本 | 原值透传；不做全局缩放 | 高 |
| `name` | 证券名称 | 文本 | 原值透传；不做全局缩放 | 高 |
| `decimal_num` | 价格小数位数（数据精度） | 原始数值 | 原始值；作为其他字段的精度/单位元数据 | 高 |
| `dr_ieps` | DR IEPS 财务指标 | 财务指标原始单位 | 原值透传；不做全局缩放 | 中 |
| `season` | 季度/季节标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `change_pct` | 当日涨跌幅 | % | raw / 100；结果按百分数显示 | 高 |
| `change_amt` | 当日涨跌额 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `turnover_ratio` | 换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `market_value` | 总市值 | 原始数值 | 原值透传；不做全局缩放 | 高 |
| `float_market_value` | 流通市值 | 原始数值 | 原值透传；不做全局缩放 | 高 |
| `float_share` | 流通股本 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `stock_status` | 证券状态码 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `financing_flag` | 融资融券标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `growth_3min` | 3 分钟涨速 | % | raw / 100；结果按百分数显示 | 高 |
| `tick_vol` | 现手成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `buy_sell_flag` | 现手成交方向/状态码 | 原始标志/代码 | 原值透传；不做全局缩放 | 高 |
| `dr_iepa` | DR IEPA 财务指标 | 财务指标原始单位 | 原值透传；不做全局缩放 | 中 |
| `amplitude` | 振幅 | % | raw / 100；结果按百分数显示 | 高 |
| `pb_ratio` | 市净率 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `open_interest` | 未平仓量/持仓量 | 未平仓量/持仓数量（资产单位） | 原值透传；不做全局缩放 | 中 |
| `day_inc` | 日增统计值 | 统计原始单位 | 原值透传；不做全局缩放 | 中 |
| `speculation` | 投机度统计值 | 统计原始单位 | 原值透传；不做全局缩放 | 中 |
| `net_profit` | 净利润 | 净利润金额（保留原始单位） | 原值透传；不做全局缩放 | 中 |
| `total_share_ex` | 总股本扩展值 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 中 |
| `cdr_flag` | 存托凭证标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `bid1_price` | 买一价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `bid1_vol` | 买一量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `ask1_price` | 卖一价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `ask1_vol` | 卖一量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `kechuang_flag` | 科创标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `historical_up_days` | 历史上涨天数统计 | 次数/天数/家数 | 原值透传；不做全局缩放 | 中 |
| `last_month_price` | 上月参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `last_year_price` | 上年参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `prev_19_price` | 前 19 日参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `prev_249_price` | 前 249 日参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `up_days` | 连续上涨天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `this_month_pct` | 本月涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `this_year_pct` | 本年涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `change_pct_20d` | 20 日/近一月涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `change_pct_recent_year` | 近一年涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `display_decimal_num` | 显示小数位数 | 原始标志/代码 | 原始值；作为其他字段的精度/单位元数据 | 高 |
| `global_trade_type` | 全局交易阶段标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `before_after_price` | 盘前/盘后价格 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `before_after_volume` | 盘前/盘后成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 中 |
| `before_after_pct` | 盘前/盘后涨跌幅 | % | raw / 100；结果按百分数显示 | 中 |
| `before_after_change` | 盘前/盘后涨跌额 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `volume_unit_flag` | 成交量单位标志 | 原始标志/代码 | `0=按股/份`、`1=按手`；参与本地成交额和换手率单位换算 | 中 |
| `contract_type` | 合约类型标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `hsgt_flag` | 沪深港通标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `prev4_price` | 前 4 日参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `change_pct_5d` | 5 日涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `industry_name` | 所属行业/板块名称 | 文本 | 原值透传；不做全局缩放 | 高 |
| `net_inflow` | 主力净流入 | 原始数值 | 股票资金流样本：raw 为万元；换算元=raw×10000 | 高 |
| `fund_rate` | 资金率指标 | 统计原始单位 | 原值透传；不做全局缩放 | 中 |
| `change_pct_60d` | 60 日涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `zero_flags` | 数值置零/有效性标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `limit_up_price` | 涨停价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `limit_down_price` | 跌停价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `stock_type` | 证券品种类型码 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `trade_status` | 交易状态码 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `change_pct_recent_6month` | 近半年涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `volume_ratio` | 量比 | 无量纲比值 | raw / 100；结果为无量纲比值 | 高 |
| `auction_change_pct` | 集合竞价涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `auction_amount` | 集合竞价成交额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `auction_volume` | 集合竞价成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `auction_unmatched_amount` | 集合竞价未匹配金额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `auction_unmatched_volume` | 集合竞价未匹配量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `post_volume` | 盘后成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `post_amount` | 盘后成交额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `change_pct_since_ipo` | 上市以来涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `change_pct_3y` | 近三年涨幅 | % | raw / 100；结果按百分数显示 | 中 |
| `bid2_price` | 买二价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `ask2_price` | 卖二价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `bid3_price` | 买三价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `ask3_price` | 卖三价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `bid4_price` | 买四价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `ask4_price` | 卖四价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `bid5_price` | 买五价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `ask5_price` | 卖五价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `up_buy_price` | 上方买入参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `down_sell_price` | 下方卖出参考价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `price_avg_diff` | 现价与均价差 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `body_change_pct` | 实体涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `open_pre_ratio` | 开盘/昨收比 | % | raw / 100；结果按百分数显示 | 高 |
| `inner_vol` | 内盘累计量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `outer_vol` | 外盘累计量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `inner_outer_ratio` | 内外盘比 | 无量纲比值 | raw / 100；结果为无量纲比值 | 高 |
| `order_buy_volume` | 委买量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `order_sell_volume` | 委卖量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `order_buy_sell_ratio` | 委比 | % | raw / 100；结果按百分数显示 | 高 |
| `total_market_cap2` | 总市值扩展口径 | 原始数值 | 原值透传；不做全局缩放 | 高 |
| `free_float_market_share` | 自由流通股本 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `free_float_market_cap` | 自由流通市值 | 原始数值 | 原值透传；不做全局缩放 | 高 |
| `increase_rate_2min` | 2 分钟涨速 | % | raw / 100；结果按百分数显示 | 高 |
| `auction_turnover_ratio` | 集合竞价换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `auction_real_turnover_ratio` | 集合竞价实际换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `real_turnover_ratio` | 实际换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `prev_day_change_pct` | 昨日涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `prev_day_volume` | 昨日成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `prev_day_amount` | 昨日成交额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `auction_volume_ratio` | 竞昨量比 | 无量纲比值 | raw / 100；结果为无量纲比值 | 高 |
| `auction_pre_volume_ratio_legacy` | 旧版竞昨成交比字段 | 无量纲比值 | raw / 100；结果为无量纲比值 | 低 |
| `post_deals` | 盘后成交笔数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `post_order_buy_volume` | 盘后委买量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `post_order_sell_volume` | 盘后委卖量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `change_pct_3d` | 3 日涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `change_pct_10d` | 10 日涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `high_all_time` | 历史最高价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `high_60d` | 近 60 日最高价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `dynamic_pe` | 动态市盈率 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `static_pe` | 静态市盈率 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `ttm_pe` | TTM 市盈率 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `ps_ratio` | 市销率 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `dividend_yield` | TTM 股息率 | % | raw / 100；结果按百分数显示 | 高 |
| `amount_2min` | 2 分钟成交额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `main_net_ratio` | 主力净比 | % | raw / 100；结果按百分数显示 | 高 |
| `main_net_inflow_3d` | 3 日主力净流入 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `main_net_inflow_5d` | 5 日主力净流入 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `main_net_inflow_10d` | 10 日主力净流入 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `main_net_inflow_20d` | 20 日主力净流入 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `ddx` | DDX 指标 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `ddy` | DDY 指标 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `ddz` | DDZ 指标 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `ddx_up_days` | DDX 连红天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `inc_pos_ratio` | 今日增仓占比 | % | raw / 100；结果按百分数显示 | 高 |
| `inc_pos_ratio_3d` | 3 日增仓占比 | % | raw / 100；结果按百分数显示 | 高 |
| `inc_pos_ratio_10d` | 10 日增仓占比 | % | raw / 100；结果按百分数显示 | 高 |
| `inc_pos_ratio_20d` | 20 日增仓占比 | % | raw / 100；结果按百分数显示 | 高 |
| `volume_increase_rate` | 量涨速 | 统计原始单位 | 原值透传；不做全局缩放 | 高 |
| `ddf` | DDF 指标 | 指标点 | raw / 100；指标显示刻度，不是金额 | 高 |
| `order_buy_sell_diff` | 委差 | 原始数值 | 原值透传；不做全局缩放 | 高 |
| `avg_hold_share` | 报告期人均持股数 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `float_b_share` | 流通 B 股 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `float_h_share` | H 股 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `share_update_time` | 股本数据更新时间 | 日期整数 | 原值；通常按 YYYYMMDD 解释 | 高 |
| `change_pct_6d` | 6 日涨幅 | % | raw / 100；结果按百分数显示 | 高 |
| `increase_rate_1min` | 1 分钟涨速 | % | raw / 100；结果按百分数显示 | 高 |
| `increase_rate_3min` | 3 分钟涨速 | % | raw / 100；结果按百分数显示 | 高 |
| `increase_rate_4min` | 4 分钟涨速 | % | raw / 100；结果按百分数显示 | 高 |
| `increase_rate_5min` | 5 分钟涨速 | % | raw / 100；结果按百分数显示 | 高 |
| `turnover_ratio_3d` | 3 日换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `turnover_ratio_5d` | 5 日换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `turnover_ratio_6d` | 6 日换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `turnover_ratio_10d` | 10 日换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `turnover_ratio_20d` | 20 日换手率 | % | raw / 100；结果按百分数显示 | 高 |
| `days_beating_market_5d` | 5 日跑赢大盘天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `days_beating_market_10d` | 10 日跑赢大盘天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `days_beating_market_20d` | 20 日跑赢大盘天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `ddf_ma1` | DDF 1 日移动平均 | 指标点 | raw / 100；指标显示刻度，不是金额 | 中 |
| `ddf_ma2` | DDF 2 日移动平均 | 指标点 | raw / 100；指标显示刻度，不是金额 | 中 |
| `ddf_ma3` | DDF 3 日移动平均 | 指标点 | raw / 100；指标显示刻度，不是金额 | 中 |
| `ddf_ma5` | DDF 5 日移动平均 | 指标点 | raw / 100；指标显示刻度，不是金额 | 中 |
| `ddf_ma10` | DDF 10 日移动平均 | 指标点 | raw / 100；指标显示刻度，不是金额 | 中 |
| `ddf_ma20` | DDF 20 日移动平均 | 指标点 | raw / 100；指标显示刻度，不是金额 | 中 |
| `open_price` | 今开价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `trade_date` | 交易日期 | 日期整数 | 原值；通常按 YYYYMMDD 解释 | 高 |
| `first_limit_time` | 首次涨停时间 | 时间整数 | 原值；按时间整数解释 | 高 |
| `last_limit_time` | 最终涨停时间 | 时间整数 | 原值；按时间整数解释 | 高 |
| `limit_up_days_legacy` | 旧版几天几板文本字段 | 文本 | 原值透传；不做全局缩放 | 低 |
| `block_ratio` | 封成比 | % | raw / 100；结果按百分数显示 | 高 |
| `pre_block_ratio` | 昨封成比 | % | raw / 100；结果按百分数显示 | 高 |
| `limit_volume` | 封单量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `limit_amount` | 封单额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `prev_limit_volume` | 昨封单量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 高 |
| `prev_limit_amount` | 昨封单额 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `block_flow_ratio` | 封流比 | % | raw / 100；结果按百分数显示 | 高 |
| `block_flow_ratio2` | 封流比 2 | % | raw / 100；结果按百分数显示 | 高 |
| `limit_up_open_count` | 涨停开板次数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `yearly_limit_up_days` | 年内涨停天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `avg_price` | 均价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `float_a_share` | 流通 A股 | 股本/持股数量（保留原始股本单位） | 原值透传；不做全局缩放 | 高 |
| `otc_fund_nav` | 场外基金净值 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 高 |
| `bk_leading_stock_code` | 板块龙头证券代码 | 文本 | 原值透传；不做全局缩放 | 中 |
| `bk_leading_stock_name` | 板块龙头证券名称 | 文本 | 原值透传；不做全局缩放 | 中 |
| `bk_up_stock_count` | 板块上涨家数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 中 |
| `bk_down_stock_count` | 板块下跌家数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 中 |
| `bk_equal_stock_count` | 板块平盘家数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 中 |
| `bk_limit_up_stock_count` | 板块涨停家数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 中 |
| `bk_limit_down_stock_count` | 板块跌停家数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 中 |
| `main_net_inflow_speed` | 主力净流入速度 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `super_big_order_net_inflow` | 超大单净流入 | 金额（保留原始金额单位） | 原值透传；不做全局缩放 | 高 |
| `consecutive_limit_up_days` | 连板天数 | 次数/天数/家数 | 原值透传；不做全局缩放 | 高 |
| `after_hours_price` | 盘后价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `after_hours_high_price` | 盘后最高价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `after_hours_low_price` | 盘后最低价 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `after_hours_volume` | 盘后成交量 | 成交/委托数量（单位由 volume_unit_flag 与资产类型决定） | 原值透传；不做全局缩放 | 中 |
| `after_hours_change_pct` | 盘后涨跌幅 | % | raw / 100；结果按百分数显示 | 中 |
| `after_hours_change` | 盘后涨跌额 | 价格/价格差原始单位 | raw / 10^decimal_num；使用同一行的 `decimal_num` | 中 |
| `after_hours_time` | 盘后时间 | 时间整数 | 原值；按时间整数解释 | 中 |
| `market` | 行情市场编码 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `market171_expire_flag` | 市场有效期标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `delay_flag` | 行情延迟标志 | 原始标志/代码 | 原值透传；不做全局缩放 | 中 |
| `auction_pre_volume_ratio` | 当前竞昨成交比 | 无量纲比值 | raw / 100；结果为无量纲比值 | 高 |
| `limit_up_days` | 几天几板文本 | 文本 | 原值透传；不做全局缩放 | 高 |

未形成稳定公共语义的字段不列入本目录；用户只能请求本目录中的正式 JSON 字段。

## 关键枚举

- `buy_sell_flag`：`0=NONE`、`1=SELL`、`2=BUY`、`3=UNKNOWN`、`4=AUCTION`；未知原码继续保留。
- `global_trade_type`：`0=Trading`、`1=Finished`、`2=BeforeTrading`、`3=AfterTrading`。
- `delay_flag`：`0=REALTIME`、`1=DELAY`。
- `volume_unit_flag`：单位取值为 `0=Share`、`1=Lot`；D101 响应仍给原始数值，非股票资产还要结合资产类型解释。

## 请求字段命名要求（请使用规范名）

> 新代码和新配置必须使用上表中的规范 JSON 字段名。当前版本可能暂时接受部分历史别名，但别名仅用于迁移，后续版本可能取消支持；请尽快将已有调用改为右侧规范名。响应字段按上表规范名输出。

| 历史别名（仅迁移参考，可能移除） | 应使用的规范字段名 |
|---|---|
| `action_volume_ratio` | `auction_volume_ratio` |
| `after_hours_amount` | `post_amount` |
| `after_hours_amount64` | `prev_day_amount` |
| `after_hours_bid_vol` | `post_order_buy_volume` |
| `after_hours_vol` | `post_volume` |
| `auction_pre_volume_ratio2` | `auction_pre_volume_ratio` |
| `auction_pre_volume_ratio_old` | `auction_pre_volume_ratio_legacy` |
| `auction_unmatched_vol` | `auction_unmatched_volume` |
| `bid_amount` | `auction_amount` |
| `bid_pct` | `auction_change_pct` |
| `bid_unmatched_amount` | `auction_unmatched_amount` |
| `bid_unmatched_volume` | `auction_unmatched_volume` |
| `bid_volume` | `auction_volume` |
| `bk_equal_stock_count_8bit` | `consecutive_limit_up_days` |
| `broken_times` | `limit_up_open_count` |
| `change_pct_120d` | `change_pct_recent_6month` |
| `change_pct_1min` | `increase_rate_1min` |
| `change_pct_2min` | `increase_rate_2min` |
| `change_pct_2min_legacy` | `increase_rate_2min` |
| `change_pct_3min` | `increase_rate_3min` |
| `change_pct_4min` | `increase_rate_4min` |
| `change_pct_5min` | `increase_rate_5min` |
| `change_pct_all` | `change_pct_since_ipo` |
| `change_pct_recent_month` | `change_pct_20d` |
| `float_share_legacy` | `net_share` |
| `increase_rate_volume` | `volume_increase_rate` |
| `limit_desc` | `limit_up_days_legacy` |
| `limit_up_days2` | `limit_up_days` |
| `net_share_ex` | `float_share` |
| `one_month_price` | `change_pct_20d` |
| `one_year_price` | `change_pct_recent_year` |
| `pb_ratio_legacy` | `pb_ratio` |
| `post_wei_buy_volume` | `post_order_buy_volume` |
| `post_wei_sell_volume` | `post_order_sell_volume` |
| `post_weighted_buy` | `post_order_buy_volume` |
| `post_weighted_sell` | `post_order_sell_volume` |
| `turnover_6d` | `turnover_ratio_6d` |
| `weighted_buy_sell_diff` | `order_buy_sell_diff` |
| `weighted_buy_sell_ratio` | `order_buy_sell_ratio` |
| `weighted_buy_volume` | `order_buy_volume` |
| `weighted_sell_volume` | `order_sell_volume` |
| `year_limit_days` | `yearly_limit_up_days` |

## 无效值

`null` 和空文本表示当前没有有效业务值；`2147483647`、`255` 以及部分极大值可能是资产/字段不适用的哨兵值。客户端必须按字段语义判断，不能把哨兵值当成真实行情。

## 获取客户端

本文档描述的是本机运行的**达塔接口**客户端。安装包不随文档分发，请到官网下载：

**<https://datas.lovestoblog.com/>**

官网提供 Windows、macOS（Apple Silicon / Intel）、Linux 以及无桌面环境的
服务器版安装包。
