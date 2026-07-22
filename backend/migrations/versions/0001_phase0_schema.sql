-- Phase 0 design draft only. Not executed against any database.
CREATE TABLE sector (
    sector_key text PRIMARY KEY,
    sector_name text NOT NULL UNIQUE,
    category_level_1 text NOT NULL,
    group_order integer NOT NULL,
    within_group_order integer NOT NULL,
    overall_order integer NOT NULL UNIQUE,
    enabled boolean NOT NULL DEFAULT false,
    start_date date,
    end_date date,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (group_order, within_group_order),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

CREATE TABLE sector_alias (
    alias text PRIMARY KEY,
    sector_key text NOT NULL REFERENCES sector(sector_key),
    confirmed boolean NOT NULL DEFAULT false,
    basis text NOT NULL,
    note text
);

CREATE TABLE mapping_version (
    mapping_version text PRIMARY KEY,
    parent_mapping_version text REFERENCES mapping_version(mapping_version),
    research_complete boolean NOT NULL DEFAULT false,
    production_approved boolean NOT NULL DEFAULT false,
    approval_date date,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sector_mapping (
    mapping_version text NOT NULL REFERENCES mapping_version(mapping_version),
    sector_key text NOT NULL REFERENCES sector(sector_key),
    mapping_status text NOT NULL,
    mapping_method text NOT NULL,
    provider_key text NOT NULL,
    primary_symbol text NOT NULL,
    backup_symbols jsonb NOT NULL DEFAULT '[]',
    effective_date date,
    user_confirmed boolean NOT NULL DEFAULT false,
    methodology_note text NOT NULL,
    primary_source_url text NOT NULL,
    backup_source_url text,
    research_date date NOT NULL,
    PRIMARY KEY (mapping_version, sector_key)
);

CREATE TABLE job_run (
    job_run_id uuid PRIMARY KEY,
    job_type text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    configuration_version text NOT NULL,
    indicator_version text NOT NULL,
    program_version text NOT NULL,
    success_count integer NOT NULL DEFAULT 0,
    failure_count integer NOT NULL DEFAULT 0
);

CREATE TABLE daily_bar (
    provider text NOT NULL,
    symbol text NOT NULL,
    market text NOT NULL,
    trade_date date NOT NULL,
    symbol_name text NOT NULL,
    open numeric NOT NULL,
    high numeric NOT NULL,
    low numeric NOT NULL,
    close numeric NOT NULL,
    pre_close numeric NOT NULL,
    change numeric NOT NULL,
    pct_change numeric NOT NULL,
    volume numeric NOT NULL,
    amount numeric NOT NULL,
    fetched_at timestamptz NOT NULL,
    source_payload_hash text NOT NULL,
    data_status text NOT NULL,
    PRIMARY KEY (provider, symbol, market, trade_date)
);

CREATE TABLE indicator_snapshot (
    snapshot_id uuid PRIMARY KEY,
    sector_key text NOT NULL REFERENCES sector(sector_key),
    trade_date date NOT NULL,
    mapping_version text NOT NULL REFERENCES mapping_version(mapping_version),
    values jsonb NOT NULL,
    data_status text NOT NULL,
    job_run_id uuid NOT NULL REFERENCES job_run(job_run_id),
    UNIQUE (sector_key, trade_date, mapping_version)
);

CREATE TABLE daily_sector_snapshot (
    sector_key text NOT NULL REFERENCES sector(sector_key),
    trade_date date NOT NULL,
    mapping_version text NOT NULL REFERENCES mapping_version(mapping_version),
    provider text NOT NULL,
    symbol text NOT NULL,
    market text NOT NULL,
    job_run_id uuid NOT NULL REFERENCES job_run(job_run_id),
    PRIMARY KEY (sector_key, trade_date, mapping_version),
    FOREIGN KEY (provider, symbol, market, trade_date)
        REFERENCES daily_bar(provider, symbol, market, trade_date)
);

CREATE TABLE data_anomaly (
    anomaly_id uuid PRIMARY KEY,
    job_run_id uuid NOT NULL REFERENCES job_run(job_run_id),
    sector_key text REFERENCES sector(sector_key),
    symbol text,
    category text NOT NULL,
    severity text NOT NULL,
    message text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}',
    detected_at timestamptz NOT NULL
);

CREATE TABLE export_manifest (
    export_id uuid PRIMARY KEY,
    job_run_id uuid NOT NULL REFERENCES job_run(job_run_id),
    trade_date date NOT NULL,
    format text NOT NULL,
    relative_path text NOT NULL,
    sha256 text NOT NULL,
    row_count integer NOT NULL,
    configuration_version text NOT NULL,
    created_at timestamptz NOT NULL
);
