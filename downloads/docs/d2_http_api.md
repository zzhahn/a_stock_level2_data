# D2 数据查询 HTTP 接口

这份文档面向需要读取数据中心、市场统计、事件数据和资金流向的程序开发者。
D2 是本地 HTTP 查询接口；调用方只连接本机服务，不需要了解外部线路、认证或
数据来源。

默认地址：

```text
http://127.0.0.1:8080
```

完整的接口前缀是 `/d2/`。D2 同时接受 GET 查询参数和
`application/x-www-form-urlencoded` 表单 POST。建议新程序使用表单 POST，中文、
括号和筛选表达式交给 HTTP 库编码。

## 1. 最小请求

```bash
curl --get 'http://127.0.0.1:8080/d2/gc' \
  --data-urlencode 'sub=guchi' \
  --data-urlencode 'status=1'
```

Python：

```python
import requests

base = "http://127.0.0.1:8080"
r = requests.post(
    base + "/d2/gc",
    data={"sub": "rzrq", "type": "list", "pageNumber": 1, "pageSize": 50},
    timeout=15,
)
r.raise_for_status()
payload = r.json()
print(payload)
```

`sub` 是 D2 的业务别名。为了兼容旧程序，`GuChi`、`Guchi`、`guchi` 等大小写
写法等价；也可以把操作名放到路径中，例如 `/d2/gc/GuChi`。

## 2. 通用请求参数

以下参数适用于数据中心类接口；某些实时资金流接口使用 `pn/pz`，两组参数都被
支持。

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `sub` | string | 无 | 业务别名或页面别名。建议始终填写。 |
| `columns` | string | `ALL` | 返回列，填 `ALL` 或逗号分隔的列名。 |
| `filter` | string | 空 | 服务端筛选表达式；也可写 `where`。 |
| `code` | string | 空 | 股票代码快捷筛选；也可用 `codeColumn` 指定代码列。 |
| `date` | string | 空 | 单日筛选，支持 `YYYYMMDD`、`YYYY-MM-DD`。 |
| `startDate` / `endDate` | string | 空 | 区间筛选，支持上述两种日期格式。 |
| `sortColumns` | string | 视接口而定 | 排序列；也可写 `sortColumn`。固定旧接口有默认排序，App 页面别名默认不强加不存在的列。 |
| `sortTypes` | string | 视接口而定 | `-1` 降序、`1` 升序；也接受 `asc`/`desc`。 |
| `pageNumber` | integer | `1` | 页码，从 1 开始；也接受 `page`、`pageNum`。 |
| `pageSize` | integer | `50` | 每页条数；也接受 `size`、`limit`。 |
| `quoteColumns` | string | 空 | 需要同时补充行情字段时填写。 |

筛选表达式的列名必须属于当前报表。对于不同页面，日期列可能不同；如果快捷
`date` 不适用，直接使用 `filter` 更稳妥。返回数据量以响应中的数组长度为准，
不要假设每一页一定有 `pageSize` 条。

## 3. 原有 D2 接口

这些别名已经有固定的业务语义，可以直接使用：

| `sub` | 功能 | 常用附加参数 |
|---|---|---|
| `guchi` | 涨停、炸板、跌停股池 | `status=1/2/3`、`date` |
| `guchi_pc` | 较长区间的股池查询 | `status`、`date`、分页 |
| `guchi_date` | 股池日期统计 | 分页、排序 |
| `time` | 服务时间 | 无 |
| `lhb_daily` | 每日榜单明细 | `date`、`code`、分页 |
| `lhb_inst` | 机构席位追踪 | `date`、分页 |
| `lhb_dept` | 营业部排行 | `date`、分页 |
| `block_trade` | 大宗成交数据 | `date`、`code`、分页 |
| `flow_industry` | 行业资金流向 | `pn`、`pz`、`fid`、`fields` |
| `flow_concept` | 概念资金流向 | `pn`、`pz`、`fid`、`fields` |
| `flow_stock` | 个股资金流向 | `pn`、`pz`、`fid`、`fields` |
| `ipo_apply` | 新股申购日历 | `date`、分页 |
| `jiejin` | 限售解禁 | `date`、`code`、分页 |
| `dividend` | 分红送转方案 | `date`、`code`、分页 |
| `forecast` | 业绩预告 | `date`、`code`、分页 |
| `holder_change` | 股东/高管持股变动 | `date`、`code`、分页 |
| `northbound` | 沪深港通资金与持仓 | `type=flow/hold` |
| `hot_stocks` | 股票热度排行 | `pn`、`pz`、`fields` |
| `holder_num` | 股东户数与筹码变动 | `date`、`code`、分页 |

例：

```python
data = requests.get(
    base + "/d2/gc",
    params={"sub": "flow_stock", "pn": 1, "pz": 100},
    timeout=15,
).json()
```

资金流向接口的返回记录会把常用的 `fXX` 字段补充为中性语义名，例如 `code`、
`name`、`price`、`change_pct`、`volume`、`amount`、`main_net_inflow`。未列入映射
表的字段仍保留原字段名，避免丢失信息。

## 4. App 数据中心页面别名

同一页面下的多个数据表通过 `type` 选择。下面这些接口使用统一的分页、排序、
筛选参数。

### 4.1 融资融券：`sub=rzrq`

支持的 `type`：

```text
list, statistics, industry, industry_profile, profile, trade_profile,
stocks, etf, new_stocks, new_etf, kline, convert_ratio
```

示例：

```text
/d2/gc?sub=rzrq&type=industry&pageNumber=1&pageSize=50
/d2/gc?sub=rzrq&type=stocks&code=000001&pageNumber=1
```

### 4.2 沪深港通报表：`sub=hsgt`

`type=flow` 保持实时分钟资金流向；`type=hold` 保持持股明细。除此之外，还支持：

```text
quota, date_types, deal_history, stock_list, stock_hold, stock_hold_base,
stock_hold_s, stock_hold_etf, stock_hold_update, org_hold, org_hold_base,
org_rank, org_rank_base, org_rank_date, board_hold, board_hold_base,
board_rank, board_rank_base, board_rank_date, top10, top10_update,
hk_deal_rank, etf_list, index_trade, net_inflow, net_statistics,
deal_amount, all_list
```

例如：

```text
/d2/gc?sub=hsgt&type=quota
/d2/gc?sub=hsgt&type=org_hold&pageNumber=1&pageSize=20
/d2/gc?sub=hsgt&type=top10&date=20260821
```

### 4.3 股权质押报表：`sub=pledge`

支持 `latest`、`warning`、`industry`、`org_type`、`ratio`、`ratio_rank`、
`ledger_ratio`、`details`、`repo`。

```text
/d2/gc?sub=pledge&type=latest&pageNumber=1&pageSize=50
/d2/gc?sub=pledge&type=warning&code=600519
```

### 4.4 主力持仓：`sub=zlcc`

支持 `list`、`detail`、`date`：

```text
/d2/gc?sub=zlcc&type=list&pageNumber=1&pageSize=50
/d2/gc?sub=zlcc&type=detail&code=000001
```

### 4.5 估值分析：`sub=gggz`

支持 `status`、`trend`、`scatter`、`industry`、`industry_profile`、`industry_rank`、
`industry_rank5`、`industry_detail`、`undervalue`、`historical`、`quantile` 和
`check`。

`roadmap`、`road_trend` 是 App 内部的专用估值通道，必须同时提供证券代码、
日期类型和指标类型过滤条件；当前不作为稳定用户别名发布。

```text
/d2/gc?sub=gggz&type=status&code=000001
/d2/gc?sub=gggz&type=historical&code=000001&pageSize=200
```

### 4.6 事件与市场指标

| 页面别名 | `type` | 说明 |
|---|---|---|
| `tfp` | `summary`、`list`、`detail` | 停牌/复牌 |
| `ggdq` | 无 | 公告列表 |
| `fhsz` | `plan`、`report_date` | 分红方案/报告日期 |
| `nxfxb` | `market`、`date`、`board`、`currency`、`margin`、`turnover`、`sumtval`、`avg_deal`、`fshis`、`theme`、`hot_theme`、`revalue`、`board_wheel`、`sector_rotation`、`mutual_stock_hold_type`、`market_value`、`stock_change`、`ipo_rise`、`ipo_rise_total`、`recent_lift`、`total_lift`、`investor`、`futures_change`、`index_picture`、`index_picture_simple` | 市场指标 |
| `dchome` | `labels`、`home` | 数据中心功能目录/首页数据 |
| `ipov2` | 无 | 注册制新股发行与上市表现 |

例如：

```text
/d2/gc?sub=tfp&type=list&date=20260821
/d2/gc?sub=ggdq&code=000001&pageNumber=1
/d2/gc?sub=fhsz&type=plan&code=600519
/d2/gc?sub=nxfxb&type=board&pageSize=100
/d2/gc?sub=nxfxb&type=futures_change&pageSize=50
/d2/gc?sub=nxfxb&type=index_picture_simple&code=000300.SH&codeColumn=SECUCODE&pageSize=1&sortColumns=TRADE_DATE&sortTypes=-1
/d2/gc?sub=ipov2&pageNumber=1&pageSize=50
```

### 4.7 新增的 App 数据视图

以下视图已经用 App 的实际请求参数和本地服务回放确认，可以直接使用：

| `sub` | `type` | 说明 |
|---|---|---|
| `financial_report` | `latest`（默认） | 最新业绩预告/报告列表 |
| `financial_report` | `season` | 报告期、财报季和历史摘要 |
| `financial_report` | `board_summary` | 按板块汇总；必须提供 `filter` |
| `economic_calendar` | 无 | 财经日历事件 |
| `new_concept_boards` | 无 | 新增概念板块及关联证券 |
| `billboard_hot_money` | 无 | 龙虎榜游资净买卖明细 |
| `ipo_statistics` | 无 | 新股/月度发行统计 |
| `ipo_unlisted` | 无 | 新股及相关品种申购、上市日历 |
| `ipo_today` | 无 | 当日申购列表；当天没有申购时可能返回空业务结果 |
| `sector_rotation` | 无 | 板块轮动排行 |
| `board_pe_dividend` | 无 | 板块估值与股息率 |
| `theme_hot` | 无 | 热门主题及关联证券 |
| `data_statistics` | 无 | 市场涨跌家数统计 |
| `billboard_brief` | 无 | 龙虎榜市场摘要；建议传 `date` |
| `market_indicator_theme` | 无 | 市场指标中的热门主题 |
| `market_indicator_date` | 无 | 市场指标日期状态 |
| `mutual_quota` | 无 | 沪深港通额度概览 |

示例：

```text
/d2/gc?sub=financial_report&type=latest&date=20260630&pageSize=20
/d2/gc?sub=financial_report&type=season&pageSize=50
/d2/gc?sub=economic_calendar&startDate=20260822&endDate=20260823&pageSize=50
/d2/gc?sub=new_concept_boards&pageSize=50
/d2/gc?sub=billboard_hot_money&date=20260821&pageSize=50
/d2/gc?sub=ipo_statistics&pageSize=12
/d2/gc?sub=ipo_unlisted&pageSize=50
/d2/gc?sub=sector_rotation&pageSize=50
/d2/gc?sub=board_pe_dividend&date=20260821&pageSize=50
/d2/gc?sub=theme_hot&pageSize=50
/d2/gc?sub=data_statistics&date=20260821&pageSize=20
/d2/gc?sub=billboard_brief&date=20260821&pageSize=50
/d2/gc?sub=market_indicator_theme&pageSize=50
/d2/gc?sub=market_indicator_date
/d2/gc?sub=mutual_quota&date=20260821&pageSize=20
```

板块汇总视图的筛选条件由调用方指定报告期和预告类型，例如：

```text
/d2/gc?sub=financial_report&type=board_summary&filter=(REPORT_DATE%3D%272026-06-30%27)(TYPECODE%3D%224%22)(PER_TYPE_CODE%3D%22001%22)&pageSize=50
```

也可以用中性 `dataset` 名称访问这些新增视图：
`financial_report`、`economic_calendar`、`new_concept_boards`、
`billboard_hot_money`、`sector_rotation`、`ipo_statistics`、`ipo_unlisted`、
`ipo_today`。返回字段仍以实际报表为准，建议通过 `columns` 明确选择字段。

本轮新增的独立视图同样使用中性 `sub` 名称。它们已经用成功响应核对过，
不是对内部通道的泛化暴露：

| 接口 | 主要字段 | 入参注意 |
|---|---|---|
| `board_pe_dividend` | `BOARD_CODE`、`BOARD_NAME`、`TRADE_DATE`、`PE`、`DIVIDEND_RATE`、估值分位 | `date` 可指定交易日。 |
| `theme_hot` | `THEME_CODE`、`THEME_NAME`、`SECURITY_CODE`、`SECUCODE`、`SECURITY_NAME` | 页面默认口径不需要日期；按页读取。 |
| `data_statistics` | `TRADE_DATE`、`RISE_NUM`、`DOWN_NUM`、`RISE_NUM_HS`、`DOWN_NUM_HS`、`STATISTICS_CYCLE` | `date` 可指定统计日。 |
| `billboard_brief` | `TRADE_DATE`、累计成交额、总净额、机构净买入、游资净买入及证券字段 | 建议始终传 `date`，不依赖服务端历史默认日。 |
| `market_indicator_theme` | 主题和关联证券字段，另有 `IS_SHOW_LIST` | 不传日期；按页面当前主题口径返回。 |
| `market_indicator_date` | `TODAY_DATE`、`IS_OPEN`、`LAST_DATE`、`NEXT_DATE` | 不传日期；返回日期状态对象列表。 |
| `mutual_quota` | `TRADE_QUOTA`、`MUTUAL_TYPE_NAME`、`FUNDS_DIRECTION`、时间和市场字段 | `date` 可指定交易日。 |

这些接口成功时通常为 `success=true`、`code=0`；个别页面在没有当日业务数据时会返回
空数组或业务错误码，客户端仍应先检查业务状态，再读取 `result.data`。

#### 数据中心视图的配置边界

数据中心页面的可配置项分成两层：调用方可以调整日期、证券代码、筛选表达式、返回列、
排序和分页；页面自身的固定筛选则由 D2 别名保留，以保证结果口径与页面一致。

| 配置层 | 可调整内容 | 注意事项 |
|---|---|---|
| 调用方参数 | `date`、`startDate`/`endDate`、`code`、`filter`、`columns`、`sortColumns`、`sortTypes`、`pageNumber`、`pageSize` | 是否生效取决于当前视图是否有对应列；以响应中的 `result` 为准。 |
| 页面固定口径 | 某些报表的默认筛选、日期列、代码列和排序列 | 不会因为换了 `sub` 就自动套用另一张报表的字段。 |
| 必填页面配置 | `financial_report&type=board_summary` 的报告期、预告类型和报告期类型筛选 | 缺少页面要求的 `filter` 时，接口可能返回空结果或配置错误。 |

因此，新增页面时不能只复制一个报表名称；还必须记录它的筛选条件、日期列、代码列、
默认排序和分页方式。用户如果要完全复现页面，应优先使用该页面示例中的参数，再逐项
替换日期、代码或筛选条件。

### 4.8 个股诊断 HTTP 接口：`sub=diagnosis`

这组接口对应个股诊断页面的评分、估值、资金、趋势和情绪数据，使用统一的
`POST /d2/gc` 入口。个股接口需要 `code`；支持六位代码、带市场后缀的代码
（如 `600519.SH`）以及带市场前缀的代码（如 `sh600519`）。不传市场时，服务会
按代码规则推断沪市、深市或北交所。

| `type` | 说明 | 是否需要 `code` |
|---|---|---:|
| `summary` | 综合评分摘要 | 是 |
| `value` | 估值评估摘要与图表 | 是 |
| `trend` | 趋势研判与技术指标 | 是 |
| `capital` | 资金流向摘要 | 是 |
| `market_heat` | 个股相关市场热度 | 是 |
| `market_cost` | 市场成本历史序列 | 是 |
| `comment` | 综合点评 | 是 |
| `forecast` | 涨跌预测 | 是 |
| `score_history` | 历史评分 | 是 |
| `score_ranking_detail` | 行业/市场评分排名 | 是 |
| `valuation_comment`、`valuation_profitability`、`valuation_growth` | 估值点评、盈利能力、成长能力 | 是 |
| `valuation_level`、`valuation_special`、`valuation_solvency`、`valuation_cashflow` | 估值水平、特殊指标、偿债与运营、现金流 | 是 |
| `capital_summary`、`capital_flow`、`capital_industry` | 资金摘要、个股资金曲线、行业资金 | 是 |
| `capital_level2`、`capital_winner`、`capital_margin` | 逐笔资金、上榜资金、融资融券 | 是 |
| `trend_comment`、`trend_energy`、`trend_technology` | 趋势点评、趋势能量、技术概览 | 是 |
| `trend_macd`、`trend_kdj`、`trend_rsi`、`trend_boll`、`trend_bias`、`trend_wr` | 各项技术指标序列 | 是 |
| `sentiment_comment`、`sentiment_list` | 舆情点评、舆情监控列表 | 是 |
| `ranking` | 诊股排行；`rankType` 可填 `0`～`3` | 否 |
| `check` | 检查证券是否满足诊断条件 | 是 |

示例：

```text
/d2/gc?sub=diagnosis&type=summary&code=000001
/d2/gc?sub=diagnosis&type=trend_macd&code=600519.SH
/d2/gc?sub=diagnosis&type=market_cost&code=000001
/d2/gc?sub=diagnosis&type=ranking&rankType=0
/d2/gc?sub=diagnosis&type=sentiment_list&code=000001&pageNumber=1&pageSize=20
```

#### 个股诊断的入参与可配置项

个股诊断页面的股票标识最终会归一成 `fc`。调用方可以传以下形式：六位代码、带
市场后缀的代码（如 `600519.SH`）或带市场前缀的代码（如 `sh600519`）。`market`
只在六位代码无法从代码本身判断时作为市场提示；`name`/`fn` 和 `color` 是页面显示
配置，不参与数据筛选。

| 参数 | 默认值 | 可配置范围与作用 |
|---|---:|---|
| `code` | 无 | 个股视图必填；`fc`、`symbol`、`id` 也可作为兼容写法。 |
| `market` | 按代码推断 | 六位代码的市场提示；可用市场前缀或页面使用的市场编号。 |
| `name` / `fn` | 空 | 页面标题或显示名称；不影响结果。 |
| `color` | 页面默认 | 页面主题提示；不影响结果。 |
| `rankType` | `0`（`ranking`） | `ranking` 的排行分类；页面提供 `0`～`3` 四档。`score_ranking_detail` 未指定时按页面行业分类 `1`。 |
| `sentimentType` | `0` | `sentiment_list` 的舆情分类；页面分类为全部、新闻、公告、研报，对应 `0`、`1`、`2`、`16`。 |
| `pageNumber` | `1` | `sentiment_list` 的页码；也可用 `pageNum` 或 `page`。 |
| `pageSize` | `20` | `sentiment_list` 每次加载条数；也可用 `size` 或 `limit`。 |

`market_cost` 返回市场成本的历史序列和摘要，主要用于核对当前价格、当日成本、
五日成本及其日期变化。它是成本数据，不等同于个股筹码分布中的获利筹码百分比；
获利筹码需要另行确认其数据来源和字段映射。该视图当前保留页面原始结果结构，
调用方应先检查 `Status` 和 `Result`，再按返回字段读取。

`ranking` 不需要股票代码；其余个股视图需要 `code`。诊断页面内部还会附带设备信息，
但这不是用户侧配置，D2 不要求调用方伪造。未列出的参数不会被当作诊断筛选项使用。

这组接口返回业务页面原有的 `Result`、`Status`、`Message`、`OtherInfo` 结构；
其中 `Result` 的字段会随 `type` 变化，不应把不同类型的结果强行按同一模型解析。

### 4.9 期货持仓与成交 HTTP 接口：`sub=futures_analysis`

这组接口读取期货品种、合约、席位持仓、成交量和净持仓数据。常用参数为
`date=YYYYMMDD`、`market`、`contract`、`orgCode`、`orgCodes`、`companyCode`、
`startDate`、`endDate`、`variety` 和 `initFlag`；不需要的参数不要填写。

| `type` | 说明 | 常用参数 |
|---|---|---|
| `varieties` | 期货品种列表 | 无 |
| `companies` | 席位/机构列表 | 无 |
| `contracts` | 品种与合约对应关系 | 无 |
| `market_date` | 各市场最近交易日 | 无 |
| `position_trend` | 多空持仓趋势 | `date`、`market`、`contract` |
| `position_history` | 总持仓历史序列 | `date`、`market`、`contract` |
| `position_detail` | 多空席位持仓明细 | `date`、`market`、`contract` |
| `net_position` | 净持仓席位明细 | `date`、`market`、`contract` |
| `volume_trend` | 成交量、成交额和结算趋势 | `date`、`market`、`contract` |
| `volume_history` | 总成交历史序列 | `date`、`market`、`contract` |
| `volume_detail` | 成交明细 | `date`、`market`、`contract` |
| `position_distribution` | 全品种净持仓分布 | `date` |
| `kline_broker` | 价格、持仓及席位合并序列 | `date`、`market`、`contract`、`orgCodes` |
| `kline_broker_full` | 完整席位持仓 K 线序列 | `date`、`market`、`contract`、`orgCodes` |
| `broker_position` | 指定席位持仓曲线 | `date`、`market`、`contract`、`orgCode` |
| `broker_position_legacy` | 指定席位历史净持仓曲线 | `date`、`market`、`contract`、`orgCode` |
| `company_list` | 指定品种的席位排行列表 | `market`、`contract` |
| `company_pay_by_variety` | 指定席位的品种盈亏曲线 | `startDate`、`endDate`、`companyCode`、`initFlag` |
| `variety_pay_by_broker` | 指定品种的席位盈亏曲线 | `startDate`、`endDate`、`variety`、`market`、`initFlag` |
| `variety_year_pay` | 品种年度席位盈亏排行 | `variety`、`market` |

示例：

```text
/d2/gc?sub=futures_analysis&type=varieties
/d2/gc?sub=futures_analysis&type=market_date
/d2/gc?sub=futures_analysis&type=position_trend&date=20260821&market=113&contract=rb
/d2/gc?sub=futures_analysis&type=position_history&date=20260821&market=113&contract=rb
/d2/gc?sub=futures_analysis&type=position_distribution&date=20260821
/d2/gc?sub=futures_analysis&type=kline_broker&date=20260821&market=113&contract=rb&orgCodes=0
```

#### 期货接口的入参与页面配置

期货页面的选择顺序是“市场 → 品种 → 合约”。`varieties` 返回市场和品种选项，
`contracts` 返回品种对应的合约及主力/非主力标记；程序应从返回值取得下一步参数，
不要把市场编号和合约代码写死成一组。当前页面在配置服务没有可用结果时的兜底选择
是市场 `113`、品种 `rb`；这只是页面兜底，不代表所有市场都使用这组值。

| 视图 | 必要入参 | 页面可配置项与行为 |
|---|---|---|
| `varieties` | 无 | 获取市场、品种、交易所和品种代码；作为选择器数据源。 |
| `companies` | 无 | 获取席位列表；返回值中的 `orgCode` 用于后续席位请求。 |
| `contracts` | 无 | 获取品种与合约关系；主力合约需要同时关注主力标记。 |
| `market_date` | 无 | 获取最近交易日信息；页面实际日期仍可能按业务数据修正。 |
| 持仓/成交趋势与历史 | `date`、`market`、`contract` | 日期、市场、品种/合约均可切换；建议使用选择器返回的值。 |
| `position_distribution` | `date` | 只按交易日查看全品种分布；服务可能返回实际可用交易日。 |
| `kline_broker`、`kline_broker_full` | `date`、`market`、`contract`、`orgCodes` | `orgCodes=0` 表示首次加载的汇总席位；选择席位后传单个或逗号分隔的席位编号。 |
| `broker_position`、`broker_position_legacy` | `date`、`market`、`contract`、`orgCode` | 选择一个席位查看曲线；兼容接受 `companyCode` 作为席位编号别名。 |
| `company_list` | `market`、`contract` | 返回该品种的多空席位列表；返回的席位编号再用于明细或曲线。 |
| `company_pay_by_variety` | `startDate`、`endDate`、`companyCode` | 选择席位和盈亏日期区间；首次加载可传 `initFlag=1`。 |
| `variety_pay_by_broker` | `startDate`、`endDate`、`variety`、`market` | 选择品种、市场和盈亏日期区间；首次加载可传 `initFlag=1`。 |
| `variety_year_pay` | `variety`、`market` | 选择品种和市场查看年度席位盈亏排行。 |

常用参数的精确定义如下：

| 参数 | 默认/状态 | 说明 |
|---|---|---|
| `date` | 页面首次请求使用当天 `YYYYMMDD` | 必须是 `YYYYMMDD`；休市日或无数据日期可能被服务调整为最近交易日，程序应以响应中的实际日期为准。 |
| `market` | 无通用默认值；页面兜底为 `113` | 市场编号来自 `varieties`。它必须与 `contract`/`variety` 匹配。 |
| `contract` | 页面兜底为 `rb` | 页面汇总视图通常传品种代码；选择具体主力合约时传合约代码，并配合主力标志。席位合并 K 线会按页面规则自动去掉合约数字部分。缺省时也可用 `code` 兼容传入。 |
| `variety` | 无 | 盈亏视图使用的品种代码；`varietyCode` 和历史拼写 `varityCode` 可作为兼容别名。 |
| `orgCode` | 无 | 单个席位编号。 |
| `orgCodes` | 首次加载为 `0` | 席位合并序列的选择值；可传 `0` 或逗号分隔的席位编号。 |
| `startDate` / `endDate` | 由页面日期控件决定 | 只用于盈亏曲线；服务可能返回修正后的区间，程序应读取响应区间。 |
| `initFlag` | 普通请求可不传 | 页面首次加载使用 `1`，日期或选择项变化时由页面重新请求；它是兼容页面行为的开关，不是分页参数。 |
| `mainAndSlaveTransFlag` | `0` | 选择具体主力合约时页面使用 `1`，品种汇总通常使用 `0`；普通调用可省略。 |

期货这组接口没有通用的 `pageNumber/pageSize` 分页协议；返回值可能是表格数组，也
可能是多条等长时间序列。`orgCodes=0`、`initFlag` 和
`mainAndSlaveTransFlag` 是为了复现页面行为保留的高级参数，普通用户只需先调用
`varieties`、`contracts`、`companies` 获取选项，再按上表组合请求即可。

期货接口通常返回 `code`、`data`、`msg`；`code=10000` 表示业务成功。`data` 可能
是数组，也可能是包含多条时间序列的对象。

### 4.10 涨停专题多视图：`sub=limit_topic`

涨停专题不是一个单独的数据表，而是由日期、市场情绪、涨停池、板块、连板和行情
等多个请求组成。D2 将这些请求收敛到同一个页面别名下，通过 `view` 选择具体数据
源；一次请求只返回一个子视图，程序需要按页面需要并行或顺序调用多个 `view`。

推荐地址：

```text
GET  http://127.0.0.1:8080/d2/limit_topic?view=limit_pool
POST http://127.0.0.1:8080/d2/gc
     sub=limit_topic&view=emotion
```

`/d2/gc?sub=limit_topic` 与 `/d2/limit_topic` 等价。未填写 `view` 时默认返回
`limit_pool`。GET 查询参数和表单 POST 均可使用；`limit_reason` 虽然内部是 JSON
请求，用户侧仍只需传普通查询参数，不需要拼装内部请求体。

#### 视图列表

| `view` | 页面内容 | 默认配置/说明 |
|---|---|---|
| `dates` | 可选交易日期 | 返回日期和新旧日期标记 |
| `limit_summary` | 当日涨停概况 | 涨停数、自然涨停、触板数、封板率等 |
| `quality_monitor` | 质量涨停监控 | 默认保留页面的质量筛选和排序 |
| `emotion` | 涨停情绪 | 连板高度、涨停数、跌停数等情绪序列 |
| `emotion_history` | 历史情绪趋势 | `date`/`endDate` 作为历史截止日 |
| `auction_pool` | 竞价涨停 | 竞价阶段直接封板的股票 |
| `limit_pool` | 涨停池 | 默认的全市场涨停列表 |
| `approaching_pool` | 即将涨停 | 盘中接近涨停的股票 |
| `continuous_pool` | 连板池 | 连续涨停股票筛选 |
| `broken_pool` | 炸板池 | 触及涨停后打开的股票 |
| `yesterday_pool` | 昨日涨停 | 昨日涨停股票及今日表现 |
| `down_pool` | 跌停池 | 跌停股票筛选 |
| `ever_down_pool` | 曾跌停 | 触及跌停后打开的股票 |
| `history_pool` | 指定日期涨停明细 | `date` 指定目标交易日 |
| `ladder` | 连板天梯 | 默认按 App 的板数筛选组合请求 |
| `multi_stock` | 多板个股 | 可用高级筛选参数切换页面口径 |
| `index_list` | 指数行情摘要 | `secids` 可自定义指数集合 |
| `index_trend` | 指数涨跌停走势 | `secids`、`time`、`fields` 可配置 |
| `minute_trend` | 指数/板块分时 | `secid`、`fields1`、`fields2` 可配置 |
| `sector_summary` | 强势板块概况 | 返回板块统计摘要 |
| `sector_list` | 强势板块及个股 | 返回板块和嵌套股票列表 |
| `limit_reason` | 涨停原因 | `date` 必填更稳定，`code` 可选 |

示例：

```python
import requests

base = "http://127.0.0.1:8080/d2/limit_topic"

limit_pool = requests.get(
    base, params={"view": "limit_pool"}, timeout=15
).json()

emotion = requests.get(
    base, params={"view": "emotion", "pageSize": 60}, timeout=15
).json()

reasons = requests.get(
    base, params={"view": "limit_reason", "date": "20260821"}, timeout=15
).json()
```

#### 入参与可配置项

| 参数 | 适用视图 | 说明 |
|---|---|---|
| `date` / `tradeDate` | 日期、历史、原因、情绪历史 | 支持 `YYYYMMDD` 和 `YYYY-MM-DD`；`history_pool` 指定目标日，`emotion_history` 指定截止日；`limit_reason` 省略时使用当天 |
| `endDate` / `toDate` | `emotion_history` | 历史趋势截止日，优先级高于 `date` |
| `columns` / `fields` | 数据中心视图 | 逗号分隔字段；省略时使用页面默认字段 |
| `filter` / `where` | 数据中心视图 | 覆盖该视图的默认筛选；语法由数据服务定义，普通调用可省略 |
| `sortColumns` / `sortTypes` | 数据中心视图 | 排序列和方向，`-1` 降序、`1` 升序 |
| `pageNumber` / `pageSize` | 数据中心视图 | 页码和条数；以响应实际数组长度为准 |
| `datetype` / `dateType` | `auction_pool`、`approaching_pool`、`ever_down_pool` | 直接覆盖竞价、盘中或历史触及的日期阶段值；普通调用由 `view` 决定 |
| `zdt` / `limitType` | 上述涨跌停阶段池 | `1` 表示涨停方向，`-1` 表示跌停方向；普通调用由 `view` 决定 |
| `stocktype` | `auction_pool`、`approaching_pool`、`ever_down_pool` | 市场类型集合；默认覆盖沪深京主要股票板块 |
| `secids` | `index_list`、`index_trend` | 逗号分隔的市场索引标识 |
| `secid` | `minute_trend` | 单个指数或板块标识，例如 `1.000001` |
| `fields` / `fields1` / `fields2` | 行情视图 | 行情字段集合；不填写时采用页面默认组合 |
| `time` / `ndays` | 行情视图 | 走势起始时间和分时天数 |
| `code` | `limit_reason`、`history_pool` | 可选证券代码；原因接口不传时返回该日期范围内的原因数据 |

板块和底部筛选池还保留了页面的高级筛选项，适合需要精确复现 App 口径的程序：
`fl`、`ty`、`ft`、`nft`、`st`、`sf`、`vl`。通常不需要填写；例如 `ladder`、
`limit_pool`、`broken_pool` 已提供经过核对的默认组合。高级参数传入后会覆盖对应
的页面默认值，因此建议只覆盖确实需要改变的项。

#### 响应约定

数据中心视图保留统一的 `result`/`success` 业务封装；行情和板块视图保留其列表
或行情封装；不同 `view` 的 `data` 行结构不相同，不能用一个固定模型解析全部子
视图。HTTP 200 只表示请求已被服务处理，程序仍应检查业务状态和 `data`/`result` 是否
为空。

### 4.11 暗盘资金榜：`sub=dark_market`

这个别名对应行情页面的暗盘资金榜，已经固定了页面所需的数据请求和字段解释。
默认返回股票榜；也可以切换到行业板块或概念板块。日期省略时由服务选择最近可用
交易日，因此周末和节假日不需要程序自己计算回退日期。

推荐请求：

```bash
curl.exe -G "http://127.0.0.1:8080/d2/gc" \
  --data-urlencode "sub=dark_market" \
  --data-urlencode "date=20260821" \
  --data-urlencode "page=1" \
  --data-urlencode "pageSize=30"
```

Python：

```python
import requests

payload = requests.get(
    "http://127.0.0.1:8080/d2/gc",
    params={"sub": "dark_market", "view": "stock", "page": 1, "pageSize": 30},
    timeout=15,
).json()
for row in payload.get("data", []):
    print(row["code"], row["name"], row["dark_money_yuan"])
```

#### 页面视图

| `view` | 内容 | 默认日期口径 |
|---|---|---|
| `stock` | 个股暗盘资金榜 | 股票榜；省略 `view` 时使用此项 |
| `industry` / `sector` | 行业板块榜 | 行业板块 |
| `concept` | 概念板块榜 | 概念板块 |

#### 入参与排序

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---:|---|
| `date` | string | 最近交易日 | 支持 `YYYYMMDD`、`YYYY-MM-DD`；响应中的 `trade_date` 才是实际日期 |
| `view` | string | `stock` | 选择股票、行业板块或概念板块 |
| `page` | integer | `1` | 页码，从 1 开始 |
| `pageSize` | integer | `30` | 每页条数，服务支持 `1` 到 `100`；超出范围会回退到 30 |
| `sort` | integer | `6` | 排序字段编号，见下表 |
| `order` | string | `desc` | `desc` 降序或 `asc` 升序 |
| `market` | string | 按 `view` | 高级覆盖项；板块榜使用 `90` |
| `datetype` | string | 按 `view` | 高级覆盖项；行业板块为 `2`，概念板块为 `3` |

已核对的排序字段：

| `sort` | 排序含义 | 适用视图 |
|---:|---|---|
| `6` | 暗盘资金 | 股票、板块 |
| `7` | 明盘资金 | 股票、板块 |
| `8` | 主力净流入（含暗盘） | 股票、板块 |
| `11` | 暗盘活跃度 | 股票、板块 |
| `12` | 暗盘流入家数比例 | 板块 |
| `13` | 最新价 | 股票 |
| `14` | 涨跌幅 | 股票、板块 |
| `15` | 领涨股 | 板块 |

#### 响应字段

成功响应的 `errid` 为 `0`，`total` 是当前视图的总记录数，`data` 是当前页。
金额字段统一为元；百分比字段使用百分数值，例如 `6.758` 表示 `6.758%`，
不是小数 `0.06758`。

```json
{
  "errid": 0,
  "errmsg": "success",
  "trade_date": "20260821",
  "total": 5337,
  "data": [
    {
      "market": "SZ",
      "code": "300502",
      "name": "新易盛",
      "update_time": "15:34:27",
      "latest_price": 442,
      "change_pct": 6.758,
      "dark_money_yuan": 815133647,
      "regular_money_yuan": 2528692342,
      "net_money_yuan": 3343825989,
      "dark_activity_pct": 3.92,
      "rank": 1
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `market` | string | `SZ`、`SH`；板块榜为 `BOARD` |
| `code` / `name` | string | 股票代码/名称，板块榜为板块代码/名称 |
| `update_time` | string | 数据更新时间，格式 `HH:mm:ss` |
| `latest_price` | number | 个股最新价；板块榜不提供 |
| `change_pct` | number | 涨跌幅，单位为百分数 |
| `dark_money_yuan` | number | 暗盘资金，单位元 |
| `regular_money_yuan` | number | 明盘资金，单位元 |
| `net_money_yuan` | number | 主力净流入（含暗盘），单位元 |
| `dark_activity_pct` | number | 暗盘活跃度，单位为百分数 |
| `dark_inflow_count` / `dark_outflow_count` | integer | 板块暗盘流入/流出家数 |
| `dark_inflow_ratio_pct` | number | 板块暗盘流入家数比例，单位为百分数 |
| `leading_stock_name` / `leading_stock_code` | string | 板块领涨股；股票榜通常为空 |
| `rank` | integer | 页面当前排序下的名次 |

这是按页查询接口，建议逐页读取到 `data` 为空或已达到 `total`，不要一次请求全量
记录。板块榜的行业和概念视图记录数不同，程序应以响应中的 `total` 为准。

## 5. 交易日、研究详情与扩展兼容接口

### 5.1 交易日序列

交易日序列不是期货品种接口的一部分，使用独立的中性入口：

```text
GET /d2/gc?sub=trade_calendar&tdate=20260823&delta=-20
```

入参只有以下几项，且不会把其他参数转发给远端：

| 参数 | 是否必填 | 默认/别名 | 说明 |
|---|---|---|---|
| `tdate` | 否 | 当天；`tradeDate`、`date` 可替代 | 锚定日期，支持 `YYYYMMDD`、`YYYY-MM-DD`、`YYYY/MM/DD`。 |
| `delta` | 否 | `-20`；`offset` 可替代 | 相对锚定日期的数量。负数取之前的交易日，正数取之后的交易日。 |
| `count` | 否 | 无 | 仅在未传 `delta` 时生效；`count=20` 等价于 `delta=-20`，方便普通调用。 |

返回值通常是 `data.tradedates` 日期数组、`data.len` 实际数量和 `data.delta`。它返回的是交易日
序列，不是某一个证券或某一个期货品种的可交易状态。

### 5.2 研究内容详情

研究内容详情使用：

```text
GET /d2/gc?sub=research_report&reportId=<报告编号>&pageNumber=1
```

| 参数 | 是否必填 | 默认 | 说明 |
|---|---|---|---|
| `reportId` | 是 | 无 | 报告/文章编号；`infocode`、`articleId`、`id` 是兼容别名。 |
| `code` | 否 | 空 | 关联证券代码；部分内容没有关联证券，不能强制填写。`stock`、`symbol` 可替代。 |
| `pageNumber` | 否 | `1` | 内容分页；`pageNum`、`page` 也可用。 |
| `needLink` | 否 | `1` | 是否请求内容中的链接信息，只建议填写 `0` 或 `1`。 |
| `clientSource` | 否 | `app_android` | 只接受 `app_android` 或 `app_ios`；通常保持默认即可。 |
| `requestTrace` | 否 | 自动生成 | 调试或重放时才需要固定；普通用户不必传。 |

这里的 `reportId` 必须来自已有的报告列表或调用方自己的数据，不提供“任意关键词搜报告”的
猜测接口。编号无效、内容无权限或内容已下线时，HTTP 可能仍为 `200`，必须继续检查响应中的
业务 `success`、错误信息和内容对象；不能只看 HTTP 状态。

### 5.3 主力建仓复合数据

```text
GET /d2/gc?sub=main_force_build&date=20260821&pageNumber=1&pageSize=20
```

| 参数 | 是否必填 | 默认 | 说明 |
|---|---|---|---|
| `date` | 否 | 不追加日期过滤 | 支持 `YYYYMMDD` 或 `YYYY-MM-DD`；不传时由数据服务返回当前可用日期。 |
| `columns` | 否 | `ALL` | 返回列，建议先用 `ALL` 核对字段，再按实际字段缩小。 |
| `pageNumber` | 否 | `1` | 页码。 |
| `pageSize` | 否 | `50` | 每页条数。 |
| `filter` | 否 | 空 | 高级筛选；只有明确知道复合报表支持的字段和语法时才使用。当前不要把它当作个股或板块代码过滤器。 |

该接口不是普通的 `result.data` 列表，成功时通常是一个复合对象，包含交易日期和
`CHANGE_DATA` 数组。当前未确认稳定的个股/板块代码过滤参数；解析程序应先判断 `result`
是否为对象，再读取数组；不要直接把整个响应当作列表分页。`pageNumber/pageSize` 目前只
作为兼容参数保留，页面服务可能忽略它们并返回完整的 `CHANGE_DATA`，客户端不要据此自动
循环分页。

### 5.4 个股资料详情兼容入口

```text
GET /d2/gc?sub=f10_notice&params=<页面生成的参数载荷>
```

这是为了保留已发现的页面兼容能力，`params` 是必填的不透明载荷。当前不能可靠地从一个股票
代码推导出完整载荷，因此 D2 不会擅自替用户拼接；必须使用对应页面或已验证调用产生的
`params`，并进行 URL 编码。可选的 `columns`、`pageNumber`、`pageSize` 只作为兼容分页字段。

这个入口已确认能够到达服务，但不同载荷可能返回业务错误（例如参数为空或格式不对），所以
不把 HTTP `200` 当成业务成功。普通用户若只需要公告、新闻或研究列表，优先使用 D1 中已经
明确入参和响应的接口。

### 5.5 期货最新交易日兼容入口

```text
GET /d2/gc?sub=futures_analysis&type=latest_trade_date&date=20260821
```

该动作保留了页面接口表中的兼容名称，但目前只确认请求地址可达，尚未确认所有页面参数组合
都能业务成功。因此 D2 不为它伪造 `market`、`variety`、`contract` 或席位默认值；需要重放
页面行为时按页面实际提供的值填写。可选参数包括 `date`/`tradeDate`、`market`、`variety`、
`contract`、`orgCode` 和 `mainAndSlaveTransFlag`。

### 5.6 财报日历辅助接口

交易日状态可以按一个日历日期查询：

```text
GET /d2/gc?sub=trade_day_status&date=20260821
```

返回记录中的 `SOLAR_DATE`、`NEST_TRADE_DATE` 和 `IS_TRADE` 分别表示日历日期、下一交易日
和是否交易。`date` 可省略以查询整张日历，也支持 `YYYYMMDD`、`YYYY-MM-DD` 两种写法。
这是“日期是否交易”的辅助数据，不替代 5.1 的交易日序列。

年度报告日期使用：

```text
GET /d2/gc?sub=annual_report_dates&code=000001&pageNumber=1&pageSize=20
```

该报表需要证券和报告期条件，当前只提供固定报表兼容入口；`code` 的具体字段过滤必须
以服务实际接受的报表筛选语法为准，不设置伪造默认值。无匹配记录时可能返回业务空结果，
应按空集合处理。

### 5.7 公共页面数据接口

以下是一组已经接入并用本地 D2 服务做过真实请求回归的公共数据接口。它们使用固定的
中性 `sub` 和 `view`，不需要调用方了解线路、报表编号或页面内部请求名。

#### 行情、分时、K 线与资金流：`sub=quote`

| `view` | 必填参数 | 返回重点 |
|---|---|---|
| `stock` | `secid` 或 `code` | 单证券行情对象，常用字段在 `data` 中。 |
| `stock_list` | 无 | 分页行情列表，使用 `pn`、`pz`、`fs` 和 `fields`。 |
| `sector_list` | 无 | 板块/行业列表行情，使用 `pn`、`pz`、`fs` 和 `fields`。 |
| `batch_quote` | `secids` | 多证券行情，记录位于 `data.diff`。 |
| `batch_quote_post` | `secids` | 多证券行情的表单 POST 兼容入口。 |
| `trend` | `secid` 或 `code` | 分时序列，使用 `ndays` 控制天数。 |
| `updown_trend` | `secid` 或 `code` | 涨跌趋势序列。 |
| `kline` | `secid` 或 `code` | 历史 K 线，记录位于 `data.klines`。 |
| `today_kline` | `secid` 或 `code` | 当日 K 线列表。 |
| `fund_flow_kline` | `secid` 或 `code` | 资金流历史序列，记录位于 `data.klines`。 |
| `auction` | `secid` 或 `code` | 竞价摘要。 |
| `auction_trend` | `secid` 或 `code` | 竞价过程序列。 |
| `northbound_summary` | 无 | 互联互通资金摘要。 |
| `northbound_realtime` | 无 | 互联互通实时资金序列。 |
| `northbound_block` | 无 | 互联互通分块实时数据。 |

证券标识优先使用 `secid`：沪市通常是 `1.六位代码`，深市和北交所通常是
`0.六位代码`。普通六位代码也可以传给 `code`，服务会按代码规则推断市场；ETF、基金、
债券和期权建议先调用 `security_suggest`，再把候选记录中的完整 `QuoteID` 传给行情视图。

六位数字代码也可以通过 `market` 明确指定市场：`sh/sse` 使用 `1`，`sz/szse/bj/bse`
使用 `0`；也接受搜索结果返回的数字市场编号。完整 `secid` 优先级最高。对于期权等
非六位代码，不根据名称猜市场，直接传搜索结果中的完整标识。

K 线默认口径与页面一致：日线、未复权、截止当天、最多 210 根；默认字段组为：

```text
fields1=f1,f2,f3,f4,f6,f7
fields2=f51,f52,f53,f54,f55,f56,f57,f59,f60
```

如果调用方传 `beg`、`end`、`klt`、`fqt` 或 `lmt`，服务会保留这些设置。每条 `klines`
记录是按 `fields2` 顺序排列的逗号分隔字符串，解析程序应以自己传入的字段顺序为准，
不要把字符串下标写死成另一套字段组合。

示例：

```text
/d2/gc?sub=quote&view=stock&secid=0.000001
/d2/gc?sub=quote&view=batch_quote&secids=0.000001,1.600000&fields=f2,f3,f12,f14
/d2/gc?sub=quote&view=trend&secid=0.000001&ndays=1
/d2/gc?sub=quote&view=kline&secid=0.000001&lmt=210
/d2/gc?sub=quote&view=fund_flow_kline&secid=0.000001&lmt=120
/d2/gc?sub=quote&view=auction&code=000001
/d2/gc?sub=quote&view=today_kline&secid=0.000001
/d2/gc?sub=quote&view=stock&code=510050&market=sh
```

品种预设可以直接写在 `market` 中，服务会按代码范围补全单证券行情和 K 线所需的
市场标识：

| `market` | 适用品种 | 示例 |
|---|---|---|
| `etf` | ETF | `code=510050`、`code=159919` |
| `fund` | 基金 | `code=510050`、`code=159919` |
| `bond` | 债券及债券类品种 | `code=511010` |
| `option` | 期权 | `code=10010971`、`code=90007069` |

品种预设同时适用于 `stock`、`trend`、`kline`、`today_kline` 和资金流序列。默认的
单证券品种字段为 `f43,f57,f58,f59,f60,f170`，其中包含代码、名称、最新价、昨收、
涨跌和涨跌幅等页面常用值。调用方显式传 `fields`、`fields1` 或 `fields2` 时，以调用方
字段为准。跨品种或代码规则不明确时，优先从 `security_suggest` 返回的完整 `QuoteID`
填入 `secid`。

#### 个股资料与基本面：`sub=stock_profile`

这是面向用户程序的稳定资料入口，不需要拼接页面内部的报表名称：

| `view` | 内容 |
|---|---|
| `basic` | 公司基本资料、证券归属和基础信息 |
| `financial` | 财务报告期、盈利、资产负债及现金流等财务字段 |
| `industry` | 行业对比和同业指标 |

`code` 必填，支持六位代码以及 `sh000001`、`000001.SZ`、`0.000001` 等常见写法。
返回对象中的 `result.data` 是资料记录数组，字段会随 `view` 改变；需要控制响应大小时，
使用 `columns` 指定列。

```text
GET /d2/gc?sub=stock_profile&view=basic&code=000001&pageSize=1
GET /d2/gc?sub=stock_profile&view=financial&code=000001&pageSize=1
GET /d2/gc?sub=stock_profile&view=industry&code=000001&pageSize=1
```

#### 白名单报表 POST：`sub=report_post`

该入口只接受 `financial`、`basic`、`industry` 三个公开报表别名，禁止把任意内部报表
名称、主机或路径转发出去。支持 JSON 和表单两种 POST；JSON 适合程序调用，表单适合
命令行和简单脚本。

JSON 示例：

```bash
curl -X POST 'http://127.0.0.1:8080/d2/gc?sub=report_post' \
  -H 'Content-Type: application/json' \
  -d '{"report":"financial","code":"000001","columns":"ALL","pageNumber":1,"pageSize":1}'
```

Python 表单示例：

```python
r = requests.post(
    base + "/d2/gc?sub=report_post",
    data={"report": "financial", "code": "000001", "columns": "ALL",
          "pageNumber": 1, "pageSize": 1},
    timeout=15,
)
r.raise_for_status()
rows = r.json().get("result", {}).get("data", [])
```

`columns`、`filter`、`codeColumn`、`pageNumber`、`pageSize`、`sortColumns` 和 `sortTypes`
均可配置；不填写 `columns` 时使用完整字段。接口返回 `success`、`code`、`result.data`
等统一结果字段，业务失败时仍需检查 `success`，不能只看 HTTP 状态码。

#### 证券搜索：`sub=security_search`

```text
GET /d2/gc?sub=security_search&input=平安银行
```

`input` 支持名称、代码和拼音关键词；`type` 可选，用于限制证券类型，默认是常用证券
类型组合。返回值是标准 JSON，候选记录位于 `QuotationCodeTable.Data`，没有结果时按空
数组处理。

#### 证券搜索建议：`sub=security_suggest`

建议输入框使用建议视图，返回结果同时带有代码、分类、数字市场标识和完整行情标识，
适合直接连接后续的 `sub=quote`。默认类型集合覆盖股票、指数、基金、ETF、债券及其他
可搜索品种：

```text
GET /d2/gc?sub=security_suggest&input=平安银行&count=10
```

| 参数 | 默认 | 说明 |
|---|---:|---|
| `input` | 无 | 名称、代码或拼音，必填。 |
| `type` | `1,2,...,15` | 建议匹配类型组合；需要限定品种时自行传入类型编号。 |
| `count` | `10` | 兼容参数；返回数量以当前搜索结果为准。 |

候选记录中的 `QuoteID` 可直接作为 `quote` 的 `secid`；不要把 `Code` 单独当作跨品种
行情标识。

#### 市场总览与宽度统计：`sub=market_overview`

这一组接口把页面上的市场总览拆成三个稳定视图：

| `view` | 返回重点 | 常用参数 |
|---|---|---|
| `change_statistics` | 上涨、下跌及主要市场范围家数 | `date`、`columns`、`filter`、分页 |
| `intraday_amount` | 盘中成交额趋势和时点摘要 | `date`、`columns`、分页 |
| `bull_bear` | 市场指标对象 | `date`、`columns`、`filter`、分页 |

示例：

```text
GET /d2/gc?sub=market_overview&view=change_statistics&date=20260821&pageSize=20
GET /d2/gc?sub=market_overview&view=intraday_amount&pageSize=20
```

`change_statistics` 是默认视图；它返回的是统计表，不是逐证券行情列表。若要展示
具体证券，使用 `sub=quote&view=stock_list` 或 `batch_quote`。

#### 沪深港通页面数据：`sub=hsgt_http`

| `view` | 说明 | 参数 |
|---|---|---|
| `summary` | 实时汇总 | `date`、`market` |
| `date_tab` | 可选统计日期 | 无 |
| `index_chart` | 指数及资金序列 | 无 |
| `stock_detail` | 单证券信息 | `code` 必填 |
| `detail` | 明细分页兼容入口 | `code`、`pageIndex`、`pageSize`、`sty`；当前页面数据可能为空 |
| `ten_top_time` | 前十时段摘要 | `date`、`market` |

示例：

```text
/d2/gc?sub=hsgt_http&view=date_tab
/d2/gc?sub=hsgt_http&view=index_chart
/d2/gc?sub=hsgt_http&view=stock_detail&code=000001
```

`date_tab` 返回日期对象数组；`index_chart` 返回图表数据对象；`stock_detail` 返回单个
证券对象；`summary` 和 `ten_top_time` 返回页面汇总对象。交易时段之外，实时视图可能
返回空业务结果，客户端应按空集合或空对象处理。

#### 股权质押页面数据：`sub=pledge_http`

| `view` | 说明 | 主要参数 |
|---|---|---|
| `first_chart` | 质押比例区间图 | 无 |
| `second_chart` | 按主体类型的质押图 | 无 |
| `third_chart` | 风险区间图 | 无 |
| `notice_list` | 最新质押公告列表 | `pi`、`ps`；也支持日期状态参数 |
| `pledge_chart` | 个股质押详情图 | `code` 或 `fc` |
| `shareholder_amount` | 质押股东数量汇总 | `code` 或 `fc` |
| `shareholder_detail` | 质押股东明细 | `code` 或 `fc`、分页 |
| `shareholder_group` | 质押股东分组 | `code` 或 `fc`、分页 |
| `ranking_industry` | 行业排行 | `pi`、`ps`、`orderField`、`orderType` |
| `ranking_rate` | 个股质押比例排行 | `pi`、`ps`、`orderField`、`orderType` |

示例：

```text
/d2/gc?sub=pledge_http&view=first_chart
/d2/gc?sub=pledge_http&view=notice_list&pi=1&ps=20
/d2/gc?sub=pledge_http&view=pledge_chart&code=000001
/d2/gc?sub=pledge_http&view=ranking_rate&pi=1&ps=20
```

该组接口的返回通常是数组，数组元素再包含 `Data`、`TableName`、分页和字段说明；
不同视图的 `Data` 行结构不同。排行视图省略排序参数时使用页面默认排序：行业按平均
质押比例，个股按质押比例。证券没有质押记录时，`Data` 可能是 `null`，这属于空业务
结果，不是 HTTP 故障。

#### 研究报告列表：`sub=research_report&view=list`

```text
GET /d2/gc?sub=research_report&view=list&stock_list=0.000001&page_size=20
```

| 参数 | 默认 | 说明 |
|---|---:|---|
| `stock_list` | 空 | 证券标识，建议使用 `0.000001`、`1.600000` 这类完整标识；省略时查询当前列表。 |
| `page_index` | `1` | 页码；也接受 `pageNumber`、`page`。 |
| `page_size` | `20` | 每页条数；也接受 `pageSize`、`size`。 |
| `begin_time` / `end_time` | 空 | 报告日期范围，支持 `YYYY-MM-DD`；也接受驼峰写法。 |
| `column_code` | `1` | 列表分类；保持默认即可。 |

成功响应通常为：

```json
{
  "success": 1,
  "error": "",
  "data": {
    "page_index": 1,
    "page_size": 20,
    "total_hits": 0,
    "list": []
  }
}
```

指定证券没有报告时返回成功的空列表；这不是错误。详情查询仍使用 5.2 中的
`reportId` 入口，列表和详情不要混用参数。

#### 公告与正文内容：`sub=content_detail`

这组入口补齐正文类页面，不把列表、摘要和正文混成一个响应。支持四种视图：

| `view` | 必填标识 | 说明 |
|---|---|---|
| `article` | `postid` | 文章正文。可选 `reportid` 指定关联编号。 |
| `brief` | `postid` | 文章/研究摘要。 |
| `announcement` | `infoCode` | 公告正文查询；支持 `pageIndex`。 |
| `research` | `reportId` | 研究内容详情，等价于研究详情入口。 |

示例：

```text
GET /d2/gc?sub=content_detail&view=article&postid=1523604926
GET /d2/gc?sub=content_detail&view=brief&postid=1523604926
GET /d2/gc?sub=content_detail&view=announcement&infoCode=<公告编号>&pageIndex=1
GET /d2/gc?sub=content_detail&view=research&reportId=<报告编号>&pageNumber=1
```

正文和摘要响应的字段由文章类型决定；公告视图返回公告正文对象。`infoCode` 应使用
公告列表中的公告编号；D2 不根据关键词猜测文章编号。无内容时可能返回成功的空对象或
空数组，客户端应按业务结果处理。

### 5.8 请求上下文由服务内部维护

用户程序不需要从抓包内容复制令牌、客户端身份、会话字段、设备字段或随机参数。
D2 启动时会读取本地运行配置，并按当前页面配置刷新行情上下文；请求时间戳、请求追踪值
和一次性随机码在每次请求时生成。匿名运行时没有登录态，相关会话字段保持为空，不会伪造
用户身份。

`fields`、`secid`、日期、筛选、排序和分页属于业务参数，仍可由调用方按本节各接口说明
配置。业务默认字段只是为了复现页面的默认显示，不是需要用户长期保存的鉴权参数。
因此，不要把某一次请求中的上下文值写死到 Python、C++ 或配置模板中；若确实要做离线重放，
只在内部测试配置中临时覆盖，并在测试结束后删除。

## 6. 内部报表能力（用户侧不调用）

EXE 内部保留了按权限启用的报表注册和页面适配能力，用于在新页面尚未形成稳定的
D2 中性别名时完成内部验证。它不是用户侧的通用查询接口，用户程序不应自行猜测
报表名、字段名或筛选语法；用户目录和示例也不列出这条内部通道。

某个页面经过验证并形成稳定语义后，会增加独立的中性 `sub`/`view` 别名，并在本用户
文档中给出明确的入参、出参和字段单位。这样用户只依赖已经稳定的 D2 接口，权限控制
和内部报表选择由 EXE 完成。

## 7. 响应结构与错误处理

数据中心类响应通常类似：

```json
{
  "success": true,
  "message": "ok",
  "result": {
    "pages": 1,
    "count": 2,
    "data": [
      {"SECURITY_CODE": "000001", "SECURITY_NAME_ABBR": "示例名称"}
    ]
  }
}
```

不同数据表的外层字段可能略有差异，程序应按以下顺序判断：

1. HTTP 状态为 `200`；
2. `success` 不为 `false`，或业务码表示成功；
3. `result.data`、`data` 或接口说明中的数组是否存在；
4. 空数组表示当前日期/筛选条件没有记录，不一定是故障。

`ipo_today` 在当天没有申购项目时可能返回业务码 `9201` 且没有 `result.data`；这表示
业务上为空，应按空列表处理，不要当成本地服务断开。

常见 HTTP 状态：

| 状态 | 含义 |
|---:|---|
| `200` | 本地代理完成请求；仍需检查业务 JSON。 |
| `403` | D2 未授权、登录状态失效或产品未启动。 |
| `404` | `/d2/` 路径或模块名写错。 |
| `500` | 本地转发或远端业务暂时失败，稍后重试并保留请求参数。 |

## 8. Python 分页示例

```python
import requests

BASE = "http://127.0.0.1:8080/d2/gc"

def fetch_all(sub, **params):
    page = 1
    page_size = params.pop("pageSize", 50)
    rows = []
    while True:
        query = {"sub": sub, **params, "pageNumber": page, "pageSize": page_size}
        response = requests.get(BASE, params=query, timeout=15)
        response.raise_for_status()
        body = response.json()
        result = body.get("result") or {}
        current = result.get("data") or body.get("data") or []
        rows.extend(current)
        pages = result.get("pages")
        if not current or (isinstance(pages, int) and page >= pages):
            break
        if len(current) < page_size and pages is None:
            break
        page += 1
    return rows

rows = fetch_all("rzrq", type="stocks", code="000001", pageSize=50)
print(len(rows), rows[:1])
```

## 9. 与实时接口的边界

D2 是按需查询，适合历史数据、排行榜、事件和统计报表；它不是实时推送通道。
需要持续接收行情时使用 D101/D201/D202 的 WebSocket 文档；历史 K 线可以使用本节的
`sub=quote&view=kline`，需要 D4 的实时行情线路时再使用 D4 文档。D2 返回的字段单位和
精度以具体报表字段为准，不要套用实时行情接口的单位换算规则。
