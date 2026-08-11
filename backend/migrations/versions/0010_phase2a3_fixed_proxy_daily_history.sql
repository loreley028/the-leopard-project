-- Phase 2A-3.3 fixed proxy daily history reference migration.
-- Runtime schema is managed by SQLAlchemy metadata; this file documents the
-- additive production migration to be reviewed before any formal deployment.
CREATE TABLE security_proxy_daily (
  id VARCHAR(32) PRIMARY KEY,
  symbol VARCHAR(16) NOT NULL,
  trading_date DATE NOT NULL,
  close NUMERIC(20, 6) NOT NULL,
  open NUMERIC(20, 6),
  high NUMERIC(20, 6),
  low NUMERIC(20, 6),
  amount_yuan NUMERIC(24, 4),
  quote_datetime DATETIME,
  fetched_at DATETIME NOT NULL,
  source VARCHAR(100) NOT NULL,
  CONSTRAINT uq_security_proxy_daily_symbol_date UNIQUE (symbol, trading_date)
);
CREATE INDEX ix_security_proxy_daily_symbol ON security_proxy_daily (symbol);
CREATE INDEX ix_security_proxy_daily_trading_date ON security_proxy_daily (trading_date);
