ALTER TABLE sector_daily_bars ADD COLUMN open NUMERIC(20, 6) NOT NULL DEFAULT 0;
ALTER TABLE sector_daily_bars ADD COLUMN high NUMERIC(20, 6) NOT NULL DEFAULT 0;
ALTER TABLE sector_daily_bars ADD COLUMN low NUMERIC(20, 6) NOT NULL DEFAULT 0;
ALTER TABLE sector_daily_bars ADD COLUMN turnover_rate NUMERIC(16, 6);
ALTER TABLE sector_daily_bars ADD COLUMN liquidity_status VARCHAR(30) NOT NULL DEFAULT 'unavailable';
ALTER TABLE market_refresh_runs ADD COLUMN short_history_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE market_refresh_runs ADD COLUMN unsupported_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE specification_documents (
  id VARCHAR(32) PRIMARY KEY,
  specification_name VARCHAR(200) NOT NULL,
  version VARCHAR(80) NOT NULL,
  effective_date DATE,
  original_filename VARCHAR(300) NOT NULL,
  storage_filename VARCHAR(120) NOT NULL UNIQUE,
  content_type VARCHAR(120) NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 VARCHAR(64) NOT NULL UNIQUE,
  note TEXT NOT NULL DEFAULT '',
  is_current BOOLEAN NOT NULL DEFAULT 0,
  replaces_specification_id VARCHAR(32),
  uploaded_by VARCHAR(120) NOT NULL,
  uploaded_at DATETIME NOT NULL
);
CREATE INDEX ix_specification_documents_name ON specification_documents (specification_name);
CREATE UNIQUE INDEX ix_specification_documents_sha256 ON specification_documents (sha256);
