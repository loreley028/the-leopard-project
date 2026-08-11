-- Phase 2A-3.7 live market-anchor daily reference migration.
-- Runtime schema is managed by SQLAlchemy metadata; this additive file is for
-- future deployment review only. It does not schedule or backfill data.
CREATE TABLE live_market_anchor_daily (
  id VARCHAR(32) PRIMARY KEY,
  symbol VARCHAR(16) NOT NULL,
  trading_date DATE NOT NULL,
  close NUMERIC(20, 6) NOT NULL,
  pre_close NUMERIC(20, 6) NOT NULL,
  pct_change NUMERIC(16, 6) NOT NULL,
  high NUMERIC(20, 6),
  low NUMERIC(20, 6),
  quote_datetime DATETIME NOT NULL,
  fetched_at DATETIME NOT NULL,
  source VARCHAR(100) NOT NULL,
  CONSTRAINT uq_live_market_anchor_daily_symbol_date UNIQUE (symbol, trading_date)
);
CREATE INDEX ix_live_market_anchor_daily_symbol ON live_market_anchor_daily (symbol);
CREATE INDEX ix_live_market_anchor_daily_trading_date ON live_market_anchor_daily (trading_date);
