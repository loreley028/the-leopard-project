CREATE TABLE sector_provider_native_closes (
    id VARCHAR(32) PRIMARY KEY,
    sector_key VARCHAR(120) NOT NULL,
    provider VARCHAR(100) NOT NULL,
    provider_symbol VARCHAR(120) NOT NULL,
    trade_date DATE NOT NULL,
    close NUMERIC(20, 6) NOT NULL,
    source_response_hash VARCHAR(64) NOT NULL,
    lineage TEXT NOT NULL,
    fetched_at DATETIME NOT NULL,
    CONSTRAINT uq_sector_provider_native_close UNIQUE (sector_key, provider, provider_symbol, trade_date)
);
CREATE INDEX ix_sector_provider_native_closes_sector_key ON sector_provider_native_closes (sector_key);
CREATE INDEX ix_sector_provider_native_closes_provider ON sector_provider_native_closes (provider);
CREATE INDEX ix_sector_provider_native_closes_provider_symbol ON sector_provider_native_closes (provider_symbol);
CREATE INDEX ix_sector_provider_native_closes_trade_date ON sector_provider_native_closes (trade_date);
ALTER TABLE sector_intraday_snapshots ADD COLUMN native_history_status VARCHAR(40) NOT NULL DEFAULT 'unavailable';
