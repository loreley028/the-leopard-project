# Security-proxy market-path feasibility

Status: **research only / user review required / not production approved**

## Product rule

An exact official board remains the preferred source for every path below. When
that board is temporarily unavailable, an ETF or listed-company quote may be
shown only as a separately labelled observation aid. It must never be called the
board return, silently replace the board, enter formal ranking, or overwrite the
canonical mapping.

Use one ETF when its published index theme is reasonably close and diversification
is useful. Use one leader when the business relationship is direct but no suitable
ETF exists. A priority theme may show up to three leaders, with each return shown
separately. The first version must not average those securities or create a
synthetic index.

Fixed Viewer wording:

> 代理证券用于观察主题相关标的表现，不代表官方板块指数或完整行业表现。

## Twelve-path audit

| Path | Preferred | Research fallback | ETF candidate | Leader candidate(s) | Main semantic risk |
|---|---|---|---|---|---|
| CPO | official board | ETF + three leaders | 515880 通信ETF, partial | 300308 中际旭创; 300502 新易盛; 300394 天孚通信 | communication equipment is broader; three firms are not a board |
| 商业航天 | official board | one leader | none verified | 600118 中国卫星 | state aerospace and commercial-space exposure overlap |
| 算力租赁 | official board | ETF + one leader | 516510 云计算ETF, partial | 300442 润泽科技 | cloud software and infrastructure are broader than rental |
| 液冷服务器 | official board | one leader | none verified | 002837 英维克 | company also serves non-server thermal markets |
| 玻璃基板 | official board | unavailable | none | none | verified candidates are too concept-driven; broad materials ETFs drift materially |
| AI应用 | official board | ETF + one leader | 159819 人工智能ETF, partial | 002230 科大讯飞 | ETF includes infrastructure and components |
| 互联网金融 | official board | ETF + one leader | 159851 金融科技ETF, partial | 300033 同花顺 | fintech and Internet finance are overlapping, not identical |
| 光纤概念 | official board | ETF + one leader | 515880 通信ETF, partial | 600487 亨通光电 | ETF and company both include non-fiber businesses |
| 稀土 | official board | ETF + one leader | 516780 稀土ETF | 600111 北方稀土 | methodology differs from the THS concept board |
| 创新药/医药 | official board | ETF + one leader | 159992 创新药ETF | 600276 恒瑞医药 | pipeline-specific risk and different membership weights |
| 半导体 | official board | ETF + one leader | 159995 芯片ETF, partial | 688981 中芯国际 | chip/foundry exposure omits parts of the value chain |
| 酒店 | official board/proxy 881160 | ETF + one leader | 159766 旅游ETF, partial | 600754 锦江酒店 | tourism is broader; this does not change the approved 881160 proxy |

Every row remains `requires_user_review=true`. Glass substrate is the only row
with `no_reliable_proxy`; retaining no proxy is safer than a name-similarity or
concept-label substitution.

## CPO “易中天” example

The market shorthand is represented as three separately quoted securities:

- 中际旭创股份有限公司 — `300308`; its filing describes high-speed optical
  modules used in cloud data centers. [2024 annual report](https://static.cninfo.com.cn/finalpage/2025-04-21/1223155483.PDF)
- 成都新易盛通信技术股份有限公司 — `300502`; its filing documents high-speed
  optical-module products including 800G and 1.6T development. [2024 annual report](https://static.cninfo.com.cn/finalpage/2025-04-23/1223219348.PDF)
- 苏州天孚光通信股份有限公司 — `300394`; its filing identifies optical
  communication components as its operating product category. [2024 annual report](https://static.cninfo.com.cn/finalpage/2025-04-21/1223152632.PDF)

The optional `515880` communication ETF is broader than CPO; it may appear beside
the three companies but does not make the basket an official CPO return. The
three company returns stay separate and are not equally weighted.

## Candidate evidence and caveats

ETF identities and themes were checked against manager or exchange disclosures:

- [515880 communication-equipment ETF](https://e.gtfund.com/etrade/Jijin/view/id/515880)
- [516510 cloud-computing and big-data ETF](https://cdn.efunds.com.cn/owch/data/bulletin/20260212/%E6%98%93%E6%96%B9%E8%BE%BE%E4%B8%AD%E8%AF%81%E4%BA%91%E8%AE%A1%E7%AE%97%E4%B8%8E%E5%A4%A7%E6%95%B0%E6%8D%AE%E4%B8%BB%E9%A2%98%E4%BA%A4%E6%98%93%E5%9E%8B%E5%BC%80%E6%94%BE%E5%BC%8F%E6%8C%87%E6%95%B0%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%91%E5%9F%BA%E9%87%91%E4%BA%A7%E5%93%81%E8%B5%84%E6%96%99%E6%A6%82%E8%A6%81%E6%9B%B4%E6%96%B0.pdf)
- [159819 artificial-intelligence ETF](https://cdn.efunds.com.cn/owch/data/bulletin/20241115/%E6%98%93%E6%96%B9%E8%BE%BE%E4%B8%AD%E8%AF%81%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD%E4%B8%BB%E9%A2%98%E4%BA%A4%E6%98%93%E5%9E%8B%E5%BC%80%E6%94%BE%E5%BC%8F%E6%8C%87%E6%95%B0%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%91%E5%9F%BA%E9%87%91%E4%BA%A7%E5%93%81%E8%B5%84%E6%96%99%E6%A6%82%E8%A6%81%E6%9B%B4%E6%96%B0.pdf)
- [159851 financial-technology ETF](https://www.fsfund.com/fund/159851/fundDetail.shtml)
- [516780 rare-earth ETF exchange notice](https://www.sse.com.cn/disclosure/announcement/general/jjzssgg/c/c_20260407_10814429.shtml)
- [159992 innovation-drug ETF exchange disclosure](https://www.sse.com.cn/disclosure/fund/announcement/c/new/2023-09-21/562320_20230921_SYE5.pdf)
- [159995 semiconductor-chip ETF](https://www.chinaamc.com/fund/159995/index.shtml)
- [159766 tourism ETF](https://www.fullgoal.com.cn/fundDetail/159766/index.html)

Company relationships use regulatory filings linked in the research JSON. Those
filings establish a relevant operating relationship, not that a security is the
unique or permanent leader. Prices, liquidity, constituents and business mix can
change; every candidate therefore needs product-owner approval and periodic
revalidation before any future integration.

## Non-goals and approval gate

This research does not calculate a self-built index, modify the formal registry,
select a production Provider, change the hotel mapping, or modify Viewer code.
Before product integration, the user must approve each path, display mode and
candidate list; legal/licensing review and a confirmed quote-field contract are
separate mandatory gates.
