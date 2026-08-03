# Tushare independent-source feasibility

Status: **research only / no production integration / no cloud request executed**

Evaluation date: 2026-08-03

Source branch: `spike/tushare-cloud-feasibility`

## Decision

Tushare Pro is **not sufficient as a single-source replacement** for the current
66-path market-data scope. The audited SW2021 taxonomy provides 45 exact published
index mappings and 7 explicit, potentially acceptable proxy mappings: **52/66**
theoretical runtime paths. That is below the predeclared cloud-validation gate of
55 and below the 60-path core-feasibility target.

The three existing business composites have research candidates, but they are not
counted as runtime coverage because component semantics require approval. Even if all
three were later approved, the ceiling would be 55/66, still below the core target.
No Tushare token was available locally, but the cloud run was already disallowed by
the lower theoretical coverage. The result is:

`tushare_single_source_insufficient`

Credential status is separately recorded as
`tushare_cloud_validation_blocked_by_credential`; this is not presented as the
primary blocker because the 52-path theory result would prevent the cloud run even
if a credential were present.

This does not reject Tushare as a useful independent **industry** source. It rejects
promoting Tushare, without a second concept-board source and permission validation,
as the sole provider for this product.

## Evidence boundaries

- The canonical scope is read dynamically from `market_path_registry_v1.json`: 66
  supported CN-A paths. HSTECH remains outside this denominator.
- Current cloud evidence is preserved as 54 operational and 12 failed paths; this
  spike does not rewrite that historical result.
- The mapping catalogue is isolated under
  `config/research/tushare_sw_mapping_research_v1.json` and explicitly declares
  `research_only=true`, `production_enabled=false`.
- The analyzer does not import the Tushare SDK, open a socket, call a Provider, or
  serialize a token value.
- Generated JSON and Markdown evidence is written under the ignored directory
  `var/provider-research/tushare-feasibility/`.
- No formal Provider candidate chain, scheduler, product denominator, database,
  report snapshot, `production_primary`, or production policy is changed.

## Tushare endpoint assessment

| Interface | Role in this assessment | Key fields / use | Access boundary | Result |
|---|---|---|---|---|
| `rt_sw_k` | SW industry current snapshot | code, name, trade time, current close, pre-close, OHLC, volume, amount, pct-change | separately purchased realtime permission | Theoretical spot source for published SW indices |
| `sw_daily` | Same-symbol history | date, OHLC, close, pct-change, volume, amount | 5000 points | Theoretical prior-four-close source for same-provider/same-symbol MA5 |
| `index_classify` | Taxonomy and `is_pub` audit | SW2021 code, name, level, published flag | 2000 points | Source of truth for published-index eligibility |
| `index_member_all` | Constituents | L1/L2/L3 membership and effective dates | 2000 points | Useful for bounded basket research, not a spot index by itself |
| `ths_daily` | Existing THS-board history | historical board OHLC and pre-close | 6000 points | Not realtime; cannot close the current spot gap alone |
| `rt_min_daily` | Current-day stock minutes | per-stock minute bars | separate realtime permission | Could support a small approved basket, not a substitute for an SW index |

The `rt_sw_k` documentation permits a full SW market snapshot in one call, which is
substantially safer than 66 per-path realtime calls. Its permission is separate from
the point-based history and classification interfaces. The SW daily endpoint is
explicitly distinct from generic `index_daily`, so the latter must not be used for
SW history.

## 66-path semantic result

| Classification | Count | Runtime treatment |
|---|---:|---|
| exact | 45 | theoretical direct candidate after account and cloud validation |
| acceptable_proxy | 7 | theoretical candidate only with explicit proxy lineage and business approval |
| composite_candidate | 3 | unapproved; excluded from runtime coverage |
| requires_business_decision | 2 | excluded until semantics are approved |
| no_valid_mapping | 9 | excluded; no silent substitution |
| total | 66 | mutually exclusive |

Exact plus explicit proxy coverage is **52/66**. Spot, pre-close, same-symbol history,
and intraday MA5 projections are each 52/66 because this spike counts a path only when
both `rt_sw_k` and `sw_daily` can use the same published SW symbol. This is a theoretical
contract assessment, not permission or cloud evidence.

### Explicit proxy candidates

- `mlcc` → `850823.SI` 被动元件: wider than MLCC alone.
- `advanced_packaging` → `850817.SI` 集成电路封测: wider than advanced packaging.
- `agriculture_breeding` → `801017.SI` 养殖业: narrower than the full agriculture label.
- `battery_lithium` → `801737.SI` 电池: wider than lithium batteries.
- `chemicals` → `801030.SI` 基础化工: wider than the current chemical-products mapping.
- `gold_concept` → `850531.SI` 黄金: an industry proxy, kept distinct from precious metals.
- `lithium_mining` → `801056.SI` 能源金属: includes cobalt and nickel as well as lithium.

### Unapproved composite candidates

- `food_beverage`: 50% `801124.SI` 食品加工 + 50% `801127.SI` 饮料乳品.
- `photovoltaic_energy_storage`: 50% `801735.SI` 光伏设备 + 50% `801737.SI` 电池;
  battery is not equivalent to storage.
- `oil_petrochemical`: 50% `801963.SI` 炼化及贸易 + 50% `801962.SI` 油服工程;
  the exact oil/gas extraction SW index is unpublished, so this is not an approved
  replacement for the existing business composite.

The weights mirror existing research intent only. This spike neither changes formal
weights nor authorizes these compositions.

### Business decision required

- `optical_fiber_theme`: `851025.SI` 通信线缆及配套 is broader than the theme.
- `innovative_drug_medicine`: neither `801151.SI` 化学制药 nor `801152.SI`
  生物制品 is an exact innovative-drug index.

### No valid published SW runtime mapping

`cpo`, `computing_power_rental`, `liquid_cooling`, `glass_substrate`,
`ai_applications`, `catering`, `internet_finance`, `rare_earth`, and
`commercial_space`.

For catering and rare earth, SW2021 contains semantically named L3 classifications
(`852141.SI` and `850541.SI`) but marks them unpublished. They therefore fail closed
instead of being counted as realtime paths. Commercial space is not replaced with
the broader aerospace or military industries. Gold concept and precious metals retain
separate symbols and separate semantics.

The full row-level matrix, including current formal candidate, current cloud result,
SW candidates, field capability, same-source MA5 status, and final decision, is produced
as `var/provider-research/tushare-feasibility/tushare-capability-matrix.json`.

## Permission, cost, stability and authorization risks

1. `rt_sw_k` is a separately purchased realtime permission. Possessing ordinary
   Tushare points does not prove access.
2. `sw_daily`, classification and constituent endpoints have separate point gates.
   An account must be tested for every required interface.
3. The SW taxonomy is independent of the current THS/Eastmoney public endpoint paths,
   but taxonomic independence does not establish an availability SLA.
4. The official pages document interface limits, not a contractual production SLA or
   the user's redistribution rights. Private use still requires reviewing the account
   terms and any realtime-data license.
5. Published flags and classifications can change. Any future formal mapping needs a
   version and effective date; history must not be rewritten.
6. A full SW snapshot is efficient, but a missing row must not be silently substituted
   or carried forward as fresh data.

## Other independent-source options

| Source | What official material supports | Unresolved issue | Current conclusion |
|---|---|---|---|
| JoinQuant / JQData | index history/current APIs plus index, industry and concept constituents | official evidence for external Alibaba Cloud server execution, licensing and exact 66-path semantics is incomplete | `external_server_usage_unverified`; continue only after written terms/account check |
| iFinD / Wind / Choice | commercial market-data products | purchase, licensing, API entitlement and exact mapping require vendor contact | likely stable but disproportionate to the current private MVP until concept coverage is priced |
| Tushare Pro | strong SW industry taxonomy, daily history, constituents and separate realtime snapshot | only 52 theoretical direct/proxy paths; realtime permission and cloud stability untested | useful industry component, insufficient single source |

No vendor was contacted, no account was registered, and no paid product was purchased.

## Safe future cloud-validation plan

This plan is **not authorized by the current 52-path result**. It is retained for a
later decision if the mapping scope changes or Tushare is evaluated as one component
of a multi-source design.

1. User places `TUSHARE_TOKEN` only in an ephemeral environment variable. Never pass
   it in chat, a command argument, a file, shell history, Git, logs, or report output.
2. Use a one-shot isolated container in a new staging directory. Do not mount
   production SQLite, uploads, PDFs, `production.env`, or the current release writable.
3. Run `rt_sw_k()` once for the full snapshot. Record only code, sanitized field
   presence, timestamp, permission status and a response hash; do not retain raw output.
4. Validate a bounded semantic sample first: semiconductor, bank, hotel, internet
   ecommerce, gold proxy, precious metals, defense military and catering fail-closed.
5. For successful published indices, request `sw_daily` sequentially for at least
   120 trading days and verify the previous four complete dates, duplicates, nulls and
   same-code MA5. Stop on auth, rate-limit or permission errors; do not retry aggressively.
6. Only after the sample passes, evaluate the remaining theoretical 52 paths at one
   request at a time with documented rate limits. Keep network attempt counts explicit.
7. Destroy the one-shot container and staging credentials. Copy back only sanitized
   JSON/Markdown summaries, then verify the formal deployment and database are unchanged.

## Reproduction

Offline analysis (no token and no network required):

```bash
PYTHONPATH=backend .venv/bin/python3.12 scripts/analyze_tushare_market_coverage.py
PYTHONPATH=backend .venv/bin/python3.12 -m pytest -p no:cacheprovider tests/test_tushare_market_coverage.py
git check-ignore -v var/provider-research/tushare-feasibility/tushare-capability-matrix.json
```

Expected summary:

```text
matrix_total=66
exact=45
acceptable_proxy=7
theoretical_runtime_coverage=52
composite_candidate=3
requires_business_decision=2
no_valid_mapping=9
cloud_validation_status=not_run_theoretical_coverage_below_gate
conclusion=tushare_single_source_insufficient
```

## Recommendation

Do not add a formal Tushare Provider, do not promote any Provider role, and do not
change PR #6 on the basis of this spike. If the project needs to continue, the next
decision should be whether to license a concept-board source that complements Tushare's
industry coverage. Tushare may then be re-evaluated as one independent component with
account permission, cloud availability, five-day reconciliation, semantic approval,
and data-authorization gates intact.

## Official references

- Tushare Pro: [SW realtime snapshot (`rt_sw_k`)](https://tushare.pro/document/2?doc_id=417)
- Tushare Pro: [SW daily history (`sw_daily`)](https://tushare.pro/document/2?doc_id=327)
- Tushare Pro: [SW2021 classification (`index_classify`)](https://tushare.pro/document/2?doc_id=181)
- Tushare Pro: [hierarchical SW constituents (`index_member_all`)](https://tushare.pro/document/2?doc_id=335)
- Tushare Pro: [THS board daily history (`ths_daily`)](https://tushare.pro/document/2?doc_id=260)
- Tushare Pro: [A-share current-day minute data (`rt_min_daily`)](https://tushare.pro/document/2?doc_id=457)
- JoinQuant: [index, industry and concept constituents](https://www.joinquant.com/help/data/stock?f=home&m=footer)
- JoinQuant: [JQData market-data API reference](https://www.joinquant.com/help/api/doc?id=9875&name=JQDatadoc)
