-- Additive local acceptance migration. Runtime data remains under ignored var/.
CREATE TABLE report_review_issues (
  id VARCHAR(32) PRIMARY KEY,
  report_id VARCHAR(32) NOT NULL REFERENCES reports(id),
  issue_key VARCHAR(240) NOT NULL,
  issue_type VARCHAR(80) NOT NULL,
  severity VARCHAR(30) NOT NULL DEFAULT 'suggestion',
  subject_key VARCHAR(120),
  subject_label VARCHAR(200) NOT NULL DEFAULT '报告内容',
  explanation TEXT NOT NULL,
  original_value_json TEXT NOT NULL DEFAULT 'null',
  suggested_value_json TEXT NOT NULL DEFAULT 'null',
  options_json TEXT NOT NULL DEFAULT '[]',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  final_value_json TEXT,
  resolution_source VARCHAR(40),
  resolved_at DATETIME,
  resolved_by VARCHAR(120),
  optional_note TEXT NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT uq_report_review_issue UNIQUE (report_id, issue_key)
);
CREATE INDEX ix_report_review_issues_report_id ON report_review_issues(report_id);

CREATE TABLE market_automation_controls (
  control_key VARCHAR(40) PRIMARY KEY,
  admin_paused BOOLEAN NOT NULL DEFAULT 0,
  changed_by VARCHAR(120),
  changed_at DATETIME NOT NULL
);
