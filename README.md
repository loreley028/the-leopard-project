# The Leopard Project

The Leopard Project (`the-leopard-project`) is a configuration-driven foundation for deterministic after-market sector analytics and later live-commentary verification. Phase 0 contains no production market-data connection, deployment, complete web UI, or AI-generated market numbers.

## Phase 0 contents

- Versioned configuration for the fixed V2.3 universe: 8 groups and 66 sectors.
- All 66 researched Tonghuashun mappings, including provenance and methodology notes.
- Seven confirmed alias-normalization examples.
- Four explicit custom-composition definitions.
- Pydantic domain models and a future PostgreSQL migration draft.
- A provider-neutral interface plus an offline Fake Provider.
- Pure functions for returns, moving averages, amount ratios, volume labels, 20-session position/crossings, ranking, and custom indices.
- A deterministic batch-approval interface that creates a new version instead of overwriting research history.
- Offline unit tests using fixed fixtures.

## Naming contract

| Item | Value |
|---|---|
| Display name | `The Leopard Project` |
| Slug | `the-leopard-project` |
| Python package | `leopard_project` |
| Compose project | `leopard_project` |
| Database | `leopard_project` |
| Containers | `leopard-api`, `leopard-web`, `leopard-scheduler`, `leopard-db` |
| API prefix | `/api/v1/` |

## Local validation

Python 3.12 and Pydantic 2 are required. No internet or production credential is needed.

```bash
PYTHONPATH=backend python3.12 -m unittest discover -s tests -v
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
```

Optional packaging dependencies are declared in `pyproject.toml`; Phase 0 itself is verified with the local fixed-fixture test suite.

## Mapping approval preview

Research confirmation is not production approval. The checked-in seed retains `user_confirmed=false` and `effective_date=null`, so no mapping is eligible for a daily job.

```bash
PYTHONPATH=backend python3.12 -m leopard_project.cli mappings approve-research-version \
  --version v2.3-20260722
```

This command only previews a new version. Add `--effective-date YYYY-MM-DD` to evaluate eligibility, and `--output <new-file.json>` to write a separate versioned artifact. It never updates the research seed in place or connects to a database.

## Phase boundary

Phase 0 stops at foundations, mapping audit, deterministic calculations, tests, and documentation. See [Phase 0 acceptance](docs/phase-0-acceptance.md) before authorizing Phase 1.
