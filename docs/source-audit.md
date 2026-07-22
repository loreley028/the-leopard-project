# Source cross-check

## Inputs

| Source | SHA-256 |
|---|---|
| `大盘猎豹直播总结PDF制作规范_V2.3_20260722.md` | `1f01568b08de180b147268b565780c5bb094c1bfe6eb7b3f34aff4fc25b9de27` |
| `大盘猎豹66板块同花顺映射_研究完成版_V2.3.xlsx` | `b3be5e990ceda56096c5da8e65bef120207ff239d8b0b1fce16c1987721c92cb` |
| `盘后板块行情与观点验证系统_Codex项目书_V1.1.md` | `a1959dec6824e7509de149dc4f935fc28de53a1e76644e3ca73f2ac84a751102` |
| `阿里云服务器部署环境说明_脱敏版.md` | `64c02fad75c55c189ea6ae830e37fdcce44773d13754c83d9a46cd58769492b4` |

## Findings

- The PDF specification and workbook both contain 8 groups and 66 sectors.
- All group names, group order, sector names, and within-group order match exactly.
- The workbook master list and mapping sheet match row for row by `sector_key` and canonical name.
- `sector_key`, canonical name, and total order are unique.
- The mapping sheet contains 66 primary source URLs, 62 research-confirmed rows, and 4 custom-composition candidates.
- All 66 rows retain `人工确认=否` and an empty effective date; none is eligible for a daily job.
- Exactly four `CUSTOM_*` primary symbols exist; their definitions are retained separately.
- The server document was used only for isolation, resource, naming, and future security constraints. No connection was made.

The old codename and deployment/component names in source documents are superseded by the user's explicit rename. Business scope and Phase boundaries are unchanged.
