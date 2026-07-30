# Hotel and catering market-path split

Status: structural change complete; Provider coverage 65/66; **DO NOT MERGE**.

## Product contract

- The immutable report topic remains `hotel_catering` / 酒店餐饮.
- The active research paths are `hotel` / 酒店 and `catering` / 餐饮.
- Published reports, PDFs, confirmations, frozen snapshots, and historical path
  rows are not copied, split, backfilled, or recalculated.
- The relationship is one report topic to two market paths. It is not an
  arithmetic composite and does not create two report conclusions.
- HSTECH stays unsupported and outside the supported denominator.

## Controlled Aliyun evidence

Validation used the PR implementation inside an isolated Docker staging area at
`c48594bcb4108ec2580af85103cb276c1c720342`. The formal release, database,
environment, API, and Web containers were not mounted writable, restarted, or
changed. Requests were sequential, grouped in batches of at most five symbols,
with at most one spot and one history request per exact symbol. No complete raw
response was retained.

`881160` returned HTTP 200, `text/html` GBK content, the visible official name
旅游及酒店, normal quote labels, and 137 history rows. `881117` returned the
same response family and quote/history field layout. The old failure was caused
by matching the superseded business label 酒店餐饮, not by a different endpoint
schema. The corrected contract is covered by a deterministic parser test.

The controlled THS industry directory contained 旅游及酒店 `881160`; the
concept directory contained only 旅游概念 `301223`. Neither exposed an
independent catering board. Catering therefore has no approved candidate.

## Complete gap result

All successful rows returned HTTP 200 spot/history responses, current and
pre-close fields, exactly four preceding complete closes from the same Provider
and symbol, and a computable intraday MA5. “Composite” rows keep their configured
components and weights and fail closed if a component is absent.

| Market path | Parent topic | Type | Provider / symbol | Semantic result | Spot / pre-close | History / four closes | Same source / MA5 | Status | Failure or next action |
|---|---|---|---|---|---|---|---|---|---|
| hotel | hotel_catering | proxy | THS / 881160 | 旅游及酒店 is wider than pure hotel | response fields present | 137 rows / complete | yes / capable | validated proxy | Viewer must show proxy wording |
| catering | hotel_catering | direct | none | no independent legal THS board found | unavailable | unavailable | no / unavailable | unverified | research an exact licensed source; no silent substitute |
| food_beverage | food_beverage | composite | THS / 881134 + 881133 | configured 食品加工制造 + 饮料制造, 50/50 | pass | pass | yes / pass | validated composite | keep components and weights |
| photovoltaic_energy_storage | photovoltaic_energy_storage | composite | THS / 881279 + 885921 | configured 光伏设备 + 储能, 50/50 | pass | pass | yes / pass | validated composite | keep components and weights |
| oil_petrochemical | oil_petrochemical | composite | THS / 881180 + 881107 | configured 石油加工贸易 + 油气开采及服务, 50/50 | pass | pass | yes / pass | validated composite | keep components and weights |
| general_equipment | general_equipment | direct | THS / 881117 | 通用设备 exact | pass | pass | yes / pass | validated direct | none |
| nonferrous_metals | nonferrous_metals | direct | THS / 881168 | 工业金属 approved exact mapping | pass | pass | yes / pass | validated direct | none |
| rare_earth | rare_earth | direct | THS / 885343 | 稀土永磁 approved exact mapping | pass | pass | yes / pass | validated direct | none |
| minor_metals | minor_metals | direct | THS / 881170 | 小金属 exact | pass | pass | yes / pass | validated direct | none |
| chemicals | chemicals | direct | THS / 881109 | 化学制品 approved exact mapping | pass | pass | yes / pass | validated direct | none |
| glass_fiber | glass_fiber | direct | THS / 884059 | 玻璃玻纤 exact | pass | pass | yes / pass | validated direct | none |
| gold_concept | gold_concept | direct | THS / 885530 | 黄金概念 exact | pass | pass | yes / pass | validated direct | none |
| steel | steel | direct | THS / 881112 | 钢铁 exact | pass | pass | yes / pass | validated direct | none |
| lithium_mining | lithium_mining | direct | THS / 881267 | 能源金属 approved exact mapping | pass | pass | yes / pass | validated direct | none |
| commercial_space | commercial_space | direct | THS / 886078 | 商业航天 exact | pass | pass | yes / pass | validated direct | none |
| defense_military | defense_military | direct | THS / 885700 | 军工 approved exact mapping | pass | pass | yes / pass | validated direct | none |
| aerospace_equipment | aerospace_equipment | direct | THS / 884180 | 航天装备 exact | pass | pass | yes / pass | validated direct | none |
| port_shipping | port_shipping | direct | THS / 881148 | 港口航运 exact | pass | pass | yes / pass | validated direct | none |
| real_estate | real_estate | direct | THS / 881153 | 房地产 exact | pass | pass | yes / pass | validated direct | none |

## Matrix and release gate

| Metric | Count |
|---|---:|
| report topics | 66 |
| market paths | 67 |
| supported market paths | 66 |
| unsupported HSTECH | 1 |
| validated direct | 61 |
| validated proxy | 1 |
| validated composite | 3 |
| operational coverage | 65 |
| unverified | 1 |
| no mapping | 1 |
| spot/history/MA5 capable | 65 |

Provider distribution for operational paths is THS exact chain 65, Eastmoney
0, and HSTECH requests 0. There was no request storm. PR #6 must remain Draft
with `DO NOT MERGE` until catering has an approved complete chain and two normal
cloud Scheduler cycles pass for all 66 supported paths.
