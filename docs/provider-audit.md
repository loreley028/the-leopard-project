# Provider audit framework

Phase 0 does not choose or connect a production provider. The researched Tonghuashun mapping workbook establishes business symbols and cited public pages; it does not establish API entitlement, technical availability, or redistribution permission.

## Gate before implementation

For each candidate provider, collect current primary-source evidence for:

1. Coverage of all referenced industry, concept, custom-component, and Hong Kong index symbols.
2. Trading-calendar coverage for both A shares and Hong Kong, including exceptional closures.
3. Historical depth, update time, corrections, and late-data behavior.
4. OHLC, volume, amount units, adjustment policy, timezone, and date semantics.
5. Authentication, quotas, rate limits, concurrency, retry guidance, and service guarantees.
6. Price, contract term, data ownership, caching, storage, display, export, and redistribution rights.
7. Symbol retirement, constituent history, corporate actions, and backfill policy.
8. Stable provenance fields and a permitted raw-payload hash/audit trail.
9. Fallback-provider compatibility and reconciliation rules.
10. Operational error mapping into the Phase 0 taxonomy.

## Unresolved research questions

- Which licensed interface can legally supply all Tonghuashun industry/concept histories and component histories?
- Does its identifier set match the workbook display codes, or is an additional audited identifier map required?
- Are `HS2083` and/or `HSTECH` available with an HK-specific calendar?
- Are stored daily bars and derived custom indices allowed in private exports and future application displays?
- What are the provider's current amount units, correction policy, and redistribution restrictions?

These questions require current provider documentation and contracts during Phase 1. No conclusion is asserted from memory.
