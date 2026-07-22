# Phase 0 acceptance

## Automated checks

Run from the repository root with Python 3.12 and Pydantic 2:

```bash
PYTHONPATH=backend python3.12 -m unittest discover -s tests -v
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
git diff --check
```

Final Phase 0 run on 2026-07-22: **25 tests passed**, the seed validator returned `passed: true`, and Python bytecode compilation completed without errors.

The suite covers:

- 66 sectors, 8 groups, exact group counts, uniqueness, and consecutive order;
- confirmed alias normalization;
- 66 researched mappings, 62 research-confirmed rows, 4 custom candidates, and source retention;
- no admission before user confirmation and effective date;
- immutable batch approval and mapping-version lineage;
- four custom definitions and valid weights;
- Hang Seng Tech symbol retention and HK calendar separation;
- provider normalization, error classification, and determinism;
- 1/5/10/20/60-session returns, moving averages, MA distance, amount ratios, volume labels, new highs/lows, MA20 crossings, ranking, ties, missing history, and custom-index determinism.

## Manual inspection

1. Confirm naming in `README.md`, `.env.example`, and `docs/architecture.md`.
2. Open the four JSON files under `config/` and spot-check MLCC, 计算机, 创新药/医药, 酒店餐饮, 食品饮料, 光伏/储能, 石油石化, 恒生科技, 国防军工, 黄金概念, and 贵金属.
3. Verify every mapping remains unapproved and has no effective date.
4. Run the approval preview without an effective date and verify `daily_job_eligible` is zero.
5. Review `docs/provider-audit.md`; no production provider is selected.
6. Review `git status` and `git diff --stat`; confirm no push, merge, deployment, server access, or production-data fetch occurred.

## Known Phase 0 limitations

- No production provider, database, scheduler, exporter, API server, or complete frontend is implemented.
- The SQL file is a migration design draft; Phase 1 must convert it to SQLAlchemy/Alembic and test transactional behavior.
- Custom composition code covers deterministic weighted-index math; provider-specific constituent history and proxy execution remain Phase 1 work.
- Provider licensing and redistribution decisions require current authoritative documentation and contracts.

Stop after this report and wait for explicit Phase 1 authorization.
