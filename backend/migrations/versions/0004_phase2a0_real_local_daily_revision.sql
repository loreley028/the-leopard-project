ALTER TABLE reports ADD COLUMN target_trade_date DATE;
ALTER TABLE reports ADD COLUMN template_version VARCHAR(20) NOT NULL DEFAULT 'unknown';
ALTER TABLE reports ADD COLUMN revision_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE reports ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE reports ADD COLUMN replaces_report_id VARCHAR(32);
ALTER TABLE reports ADD COLUMN revision_note TEXT NOT NULL DEFAULT '';
ALTER TABLE reports ADD COLUMN data_origin VARCHAR(30) NOT NULL DEFAULT 'real_upload';

CREATE TABLE report_days (
    id VARCHAR(32) PRIMARY KEY,
    report_date DATE NOT NULL UNIQUE,
    state VARCHAR(30) NOT NULL,
    skip_reason TEXT NOT NULL,
    confirmed_by VARCHAR(120),
    updated_at DATETIME NOT NULL
);

CREATE TABLE sector_catalog_versions (
    id VARCHAR(32) PRIMARY KEY,
    version VARCHAR(40) NOT NULL UNIQUE,
    valid_from DATE NOT NULL,
    valid_to DATE,
    source VARCHAR(120) NOT NULL
);

CREATE TABLE sector_catalog_entries (
    id VARCHAR(32) PRIMARY KEY,
    catalog_version VARCHAR(40) NOT NULL,
    sector_key VARCHAR(120) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    group_key VARCHAR(120) NOT NULL,
    display_order INTEGER NOT NULL,
    aliases_json TEXT NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE,
    support_status VARCHAR(40) NOT NULL,
    CONSTRAINT uq_catalog_version_sector UNIQUE (catalog_version, sector_key)
);
