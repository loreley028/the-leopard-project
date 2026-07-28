CREATE TABLE IF NOT EXISTS sector_research_preferences (
    sector_key VARCHAR(120) PRIMARY KEY,
    is_pinned_for_research BOOLEAN NOT NULL DEFAULT 0,
    updated_by VARCHAR(120) NOT NULL,
    updated_at DATETIME NOT NULL
);
