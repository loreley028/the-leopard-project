# Provider lineage

Lineage evidence is stored in `data/reconciliation-validation/provider_lineage.json` and validated as structured data.

## Conclusion

`ths_public_validation` and `akshare_ths_research` are `shared_upstream` with high source-code confidence:

- both use Tonghuashun;
- both ultimately request `d.10jqka.com.cn`;
- both use the v4 `line/bk_{code}/01/{year}.js` board chart family;
- both consume the same JSONP semicolon-row response shape;
- AKShare adds name/code lookup and an anti-bot parameter, but that is an adapter difference rather than upstream fault isolation.

Evidence: [AKShare repository](https://github.com/akfamily/akshare), [industry implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_board_industry_ths.py), [concept implementation](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_board_concept_ths.py), and [official interface inventory](https://akshare.akfamily.xyz/tutorial.html).

No Cookie, request header, Token, or account information is persisted. AKShare remains `research_provider`; source equality can never approve it as `candidate_primary`, `production_primary`, or `production_fallback`.
