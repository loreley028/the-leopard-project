# Migration design status

`versions/0001_phase0_schema.sql` is a Phase 0 PostgreSQL design draft. It is not applied anywhere. Phase 1 must implement equivalent SQLAlchemy 2 models and an Alembic revision, then verify upgrade, downgrade, idempotency, and rollback against a disposable local database.
