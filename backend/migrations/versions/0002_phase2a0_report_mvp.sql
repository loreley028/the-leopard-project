-- Phase 2A-0 reference schema only. Runtime schema is managed through SQLAlchemy metadata.
-- Types intentionally remain portable to a future PostgreSQL migration.
CREATE TABLE reports (
    id VARCHAR(32) PRIMARY KEY,
    title VARCHAR(300) NOT NULL,
    report_date DATE,
    candidate_report_date DATE,
    report_date_confirmed BOOLEAN NOT NULL,
    status VARCHAR(30) NOT NULL,
    core_view TEXT NOT NULL,
    market_path TEXT NOT NULL,
    risk_warning TEXT NOT NULL,
    focus_sectors_json TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    parse_note TEXT NOT NULL,
    created_by VARCHAR(120) NOT NULL,
    published_by VARCHAR(120),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    published_at TIMESTAMP,
    withdrawn_at TIMESTAMP,
    withdrawal_reason TEXT
);

CREATE TABLE report_files (
    id VARCHAR(32) PRIMARY KEY,
    report_id VARCHAR(32) NOT NULL UNIQUE REFERENCES reports(id),
    sha256 VARCHAR(64) NOT NULL UNIQUE,
    original_filename VARCHAR(300) NOT NULL,
    storage_filename VARCHAR(100) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TIMESTAMP NOT NULL
);

CREATE TABLE report_sections (
    id VARCHAR(32) PRIMARY KEY,
    report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
    section_type VARCHAR(60) NOT NULL,
    heading VARCHAR(200) NOT NULL,
    raw_text TEXT NOT NULL,
    extraction_status VARCHAR(30) NOT NULL
);

CREATE TABLE sector_mentions (
    id VARCHAR(32) PRIMARY KEY,
    report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
    sector_key VARCHAR(120) NOT NULL,
    sector_name VARCHAR(120) NOT NULL,
    summary TEXT NOT NULL,
    source_text TEXT NOT NULL,
    extraction_status VARCHAR(30) NOT NULL,
    manually_modified BOOLEAN NOT NULL,
    UNIQUE (report_id, sector_key)
);

CREATE TABLE unmapped_terms (
    id VARCHAR(32) PRIMARY KEY,
    report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
    term VARCHAR(200) NOT NULL,
    source_text TEXT NOT NULL,
    status VARCHAR(30) NOT NULL,
    resolved_sector_key VARCHAR(120),
    resolved_by VARCHAR(120),
    resolved_at TIMESTAMP
);

CREATE TABLE report_revisions (
    id VARCHAR(32) PRIMARY KEY,
    report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
    revision_number INTEGER NOT NULL,
    changed_by VARCHAR(120) NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE publish_events (
    id VARCHAR(32) PRIMARY KEY,
    report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
    event_type VARCHAR(30) NOT NULL,
    actor VARCHAR(120) NOT NULL,
    reason TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE audit_events (
    id VARCHAR(32) PRIMARY KEY,
    actor VARCHAR(120) NOT NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(80) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    details_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE users (
    id VARCHAR(32) PRIMARY KEY,
    username VARCHAR(120) NOT NULL UNIQUE,
    role VARCHAR(20) NOT NULL,
    enabled BOOLEAN NOT NULL,
    created_at TIMESTAMP NOT NULL
);
