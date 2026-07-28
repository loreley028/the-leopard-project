CREATE TABLE sector_path_history_entries (
  id VARCHAR(32) PRIMARY KEY,
  sector_key VARCHAR(120) NOT NULL,
  sector_name VARCHAR(120) NOT NULL,
  path_report_date DATE NOT NULL,
  path_status VARCHAR(30) NOT NULL,
  source_report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
  detail_report_id VARCHAR(32) REFERENCES reports(id),
  market_as_of_date DATE,
  frozen_daily_pct_change NUMERIC(16, 6),
  market_data_status VARCHAR(40) NOT NULL DEFAULT 'unavailable',
  source_pdf_sha256 VARCHAR(64) NOT NULL,
  template_version VARCHAR(20) NOT NULL DEFAULT 'unknown',
  source_kind VARCHAR(40) NOT NULL DEFAULT 'full_pdf_matrix',
  created_at DATETIME NOT NULL,
  CONSTRAINT uq_sector_path_history_date UNIQUE (sector_key, path_report_date)
);
CREATE INDEX ix_sector_path_history_entries_sector_key ON sector_path_history_entries (sector_key);
CREATE INDEX ix_sector_path_history_entries_path_report_date ON sector_path_history_entries (path_report_date);
CREATE INDEX ix_sector_path_history_entries_source_report_id ON sector_path_history_entries (source_report_id);
CREATE INDEX ix_sector_path_history_entries_detail_report_id ON sector_path_history_entries (detail_report_id);

CREATE TABLE path_history_imports (
  id VARCHAR(32) PRIMARY KEY,
  source_report_id VARCHAR(32) NOT NULL UNIQUE REFERENCES reports(id),
  source_pdf_sha256 VARCHAR(64) NOT NULL,
  template_version VARCHAR(20) NOT NULL DEFAULT 'unknown',
  date_count INTEGER NOT NULL,
  sector_count INTEGER NOT NULL,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  unchanged_count INTEGER NOT NULL DEFAULT 0,
  difference_count INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(40) NOT NULL DEFAULT 'initialized',
  differences_json TEXT NOT NULL DEFAULT '[]',
  initialized_at DATETIME NOT NULL
);
CREATE UNIQUE INDEX ix_path_history_imports_source_report_id ON path_history_imports (source_report_id);
CREATE INDEX ix_path_history_imports_source_pdf_sha256 ON path_history_imports (source_pdf_sha256);

CREATE TABLE sector_intraday_snapshots (
  id VARCHAR(32) PRIMARY KEY,
  sector_key VARCHAR(120) NOT NULL,
  trade_date DATE NOT NULL,
  observed_at DATETIME NOT NULL,
  index_value NUMERIC(20, 6) NOT NULL,
  pre_close NUMERIC(20, 6) NOT NULL,
  pct_change NUMERIC(16, 6) NOT NULL,
  volume NUMERIC(24, 4),
  amount NUMERIC(24, 4),
  provider VARCHAR(100) NOT NULL,
  provider_role VARCHAR(60) NOT NULL,
  data_status VARCHAR(40) NOT NULL,
  response_hash VARCHAR(64) NOT NULL,
  fetched_at DATETIME NOT NULL,
  refresh_run_id VARCHAR(32) REFERENCES market_refresh_runs(id),
  CONSTRAINT uq_sector_intraday_observed UNIQUE (sector_key, observed_at)
);
CREATE INDEX ix_sector_intraday_snapshots_sector_key ON sector_intraday_snapshots (sector_key);
CREATE INDEX ix_sector_intraday_snapshots_trade_date ON sector_intraday_snapshots (trade_date);
CREATE INDEX ix_sector_intraday_snapshots_observed_at ON sector_intraday_snapshots (observed_at);
CREATE INDEX ix_sector_intraday_snapshots_refresh_run_id ON sector_intraday_snapshots (refresh_run_id);

CREATE TABLE intraday_refresh_sessions (
  id VARCHAR(32) PRIMARY KEY,
  status VARCHAR(30) NOT NULL DEFAULT 'paused',
  refresh_interval_minutes INTEGER NOT NULL DEFAULT 5,
  provider_role VARCHAR(60) NOT NULL DEFAULT 'diagnostic_provider',
  started_by VARCHAR(120) NOT NULL,
  started_at DATETIME NOT NULL,
  paused_at DATETIME,
  last_refresh_at DATETIME,
  next_refresh_at DATETIME
);
