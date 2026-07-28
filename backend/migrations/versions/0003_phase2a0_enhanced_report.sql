-- Phase 2A-0 enhanced report reference migration.
-- Runtime tests use SQLAlchemy metadata; production execution is intentionally not enabled.
ALTER TABLE reports ADD COLUMN market_as_of_date DATE;
ALTER TABLE reports ADD COLUMN candidate_market_as_of_date DATE;
ALTER TABLE reports ADD COLUMN market_as_of_date_confirmed BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN enhanced_status VARCHAR(30) NOT NULL DEFAULT 'not_started';
ALTER TABLE reports ADD COLUMN enhanced_revision_number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN detected_report_date DATE;
ALTER TABLE reports ADD COLUMN report_date_source VARCHAR(40) NOT NULL DEFAULT 'unavailable';
ALTER TABLE reports ADD COLUMN report_date_confidence VARCHAR(20) NOT NULL DEFAULT 'low';
ALTER TABLE reports ADD COLUMN report_date_confirmed_by_user BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN interpretation_status VARCHAR(30) NOT NULL DEFAULT 'uploading';
ALTER TABLE reports ADD COLUMN interpretation_meta_json TEXT NOT NULL DEFAULT '{}';

-- SQLAlchemy models define the complete constraints and indexes for:
-- sector_path_entries, sector_assessments, sector_daily_bars,
-- sector_indicator_snapshots, report_sector_market_snapshots,
-- market_refresh_runs, market_refresh_items, report_comparisons,
-- enhanced_report_revisions.
-- SectorPathEntry and SectorAssessment also carry source page/range,
-- confidence, validation flags and quality status in the SQLAlchemy model.
-- A deployment migration will be generated and reviewed only after a
-- production database and migration tool are approved.
