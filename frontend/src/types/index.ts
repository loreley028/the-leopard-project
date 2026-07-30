export type Role = "viewer" | "admin";
export type ReportStatus = "uploaded" | "parsing" | "needs_review" | "blocked" | "ready_to_publish" | "published" | "withdrawn" | "parse_failed";

export interface Principal { username: string; role: Role }

export interface SectorMention {
  sector_key: string;
  sector_name: string;
  summary: string;
  extraction_status: string;
}

export interface Report {
  id: string;
  title: string;
  report_date: string | null;
  candidate_report_date: string | null;
  report_date_confirmed: boolean;
  detected_report_date: string | null;
  report_date_source: string;
  report_date_confidence: "high" | "medium" | "low";
  report_date_confirmed_by_user: boolean;
  market_as_of_date: string | null;
  candidate_market_as_of_date: string | null;
  market_as_of_date_confirmed: boolean;
  interpretation_status: "uploading" | "interpreting" | "ready" | "needs_attention" | "failed";
  enhanced_status: string;
  enhanced_revision_number: number;
  status: ReportStatus;
  core_view: string;
  market_path: string;
  risk_warning: string;
  focus_sectors: string[];
  created_at: string;
  created_at_display?: string;
  published_at: string | null;
  published_at_display?: string | null;
  mentions: SectorMention[];
  pdf_url: string;
  pdf_download_url?: string;
  target_trade_date?: string | null;
  template_version?: string;
  revision_number?: number;
  is_current?: boolean;
  data_notice: string;
  change_summary?: { kind: string; text: string; added_focus_sectors?: string[]; removed_focus_sectors?: string[] };
  raw_text?: string;
  parse_note?: string;
  original_filename?: string;
  unmapped_terms?: Array<{ id: string; term: string; status: string; resolved_sector_key: string | null }>;
  attention_items?: AttentionItem[];
  mapping_summary?: Record<string, number>;
  field_provenance?: Record<string, FieldProvenance>;
}

export interface AttentionItem {
  kind: string;
  severity: "blocking" | "warning";
  message: string;
  term?: string;
}

export interface FieldProvenance {
  extracted_value: string | null;
  extraction_method: string;
  source_page: number | null;
  source_text_range: [number, number] | null;
  confidence: "high" | "medium" | "low";
  manually_modified: boolean;
}

export interface Interpretation {
  report_id: string;
  status: Report["interpretation_status"];
  report_date: string | null;
  detected_report_date: string | null;
  report_date_source: string;
  report_date_confidence: "high" | "medium" | "low";
  report_date_confirmed_by_user: boolean;
  candidate_market_as_of_date: string | null;
  market_as_of_date: string | null;
  market_data_status: "attached" | "not_bound";
  field_provenance: Record<string, FieldProvenance>;
  attention_items: AttentionItem[];
  mapping_summary: Record<string, number>;
  status_counts: Record<PathStatus, number>;
  mentioned_assessments: SectorAssessment[];
  relevant_path_entries: PathEntry[];
  all_path_entries: Array<PathEntry & { group_name: string }>;
  path_entry_count: number;
  external_llm_calls: number;
  ocr_used: boolean;
  quality_status: "verified_structure" | "needs_attention" | "blocking_parse_error";
  quality_summary: Record<string, string | number>;
  pdf_history_matrix: { dates: string[]; rows: Array<{ sector_key: string; sector_name: string; statuses: string[] }>; row_count?: number };
  review_workflow: ReviewWorkflow;
}

export interface ReviewIssue {
  issue_key: string;
  issue_type: string;
  severity: "suggestion" | "required";
  subject_key: string | null;
  subject_label: string;
  explanation: string;
  original_value: unknown;
  suggested_value: unknown;
  options: string[];
  evidence: { page?: number | null; excerpt?: string | null; source_reference?: string; extraction_method?: string; confidence?: string; technical_codes?: string[] };
  resolved: boolean;
  final_value: unknown;
  resolution_source: "accepted_suggestion" | "manual_override" | "bulk_accept" | null;
  resolved_at: string | null;
  resolved_by: string | null;
  optional_note: string;
}

export interface ReviewWorkflow {
  workflow_status: "parsing" | "needs_review" | "blocked" | "ready_to_publish" | "published" | "failed";
  summary: { auto_confirmed: number; suggested_review: number; must_handle: number; handled: number };
  steps: Array<{ key: "upload" | "review" | "publish"; label: string; state: "complete" | "current" | "pending" }>;
  issues: ReviewIssue[];
}

export interface Sector {
  sector_key: string;
  sector_name: string;
  group_name: string;
  group_order: number;
  overall_order: number;
  latest_view: string | null;
  latest_view_date?: string | null;
  mentioned_in_latest_published: boolean;
  market_support_status: "supported" | "unsupported";
  market_path_key?: string;
  parent_report_topic?: string;
  report_topic_name?: string;
  data_status: "supported" | "proxy" | "short_history" | "unsupported" | "unverified";
  market_status_detail: string;
  current_path_status: PathStatus;
  current_path_status_label: string;
  latest_market: MarketSnapshot | null;
  latest_complete_market?: MarketSnapshot | null;
  intraday_snapshot?: IntradaySnapshot | null;
  intraday_status?: string;
  intraday_last_attempt_at?: string | null;
  recent_5_trading_days?: RecentTradingDay[];
  timeline?: Array<{ report_id: string; report_date: string; report_title: string; summary: string }>;
  recent_path?: Array<PathEntry & { report_id: string; report_date: string }>;
  recent_mention_count?: number;
  attention_level?: "high" | "normal" | "low";
  status_changed?: boolean;
  reported_status?: PathStatus;
  effective_status?: PathStatus | null;
  effective_status_label?: string;
  active_holding_interval?: HoldingInterval | null;
  historical_holding_intervals?: HoldingInterval[];
  strict_holding_interval?: HoldingInterval | null;
  broad_holding_interval?: HoldingInterval | null;
  historical_strict_intervals?: HoldingInterval[];
  historical_broad_intervals?: HoldingInterval[];
  is_low_attention?: boolean;
  is_pinned_for_research?: boolean;
}

export type PathStatus = "avoid" | "strong_watch" | "watch" | "weak_watch" | "turn_hold" | "hold" | "turn_weak" | "exit" | "not_mentioned";

export interface PathEntry {
  id: string;
  sector_key: string;
  sector_name: string;
  path_status: PathStatus;
  path_status_label: string;
  path_status_color: string;
  explicitly_mentioned: boolean;
  judgement_summary: string;
  source_text_reference: string;
  review_status: string;
  manually_modified: boolean;
  revision_id: string;
  extraction_method?: string;
  source_page?: number | null;
  source_text_start?: number | null;
  source_text_end?: number | null;
  source_text_excerpt?: string;
  confidence?: string;
  validation_flags?: string[];
  quality_status?: string;
  daily_return?: number | null;
  market_as_of_date?: string | null;
  detail_report_id?: string | null;
  has_detailed_report?: boolean;
  market_data_status?: string;
}

export interface MarketSnapshot {
  sector_key?: string;
  trade_date: string;
  close: number;
  open?: number;
  high?: number;
  low?: number;
  pre_close: number;
  daily_pct_change: number;
  return_5d: number | null;
  return_10d: number | null;
  return_20d: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  close_vs_ma5_pct: number | null;
  close_vs_ma10_pct: number | null;
  close_vs_ma20_pct: number | null;
  volume: number | null;
  volume_average_5d: number | null;
  volume_average_20d: number | null;
  volume_ratio_5d: number | null;
  volume_ratio_20d: number | null;
  amount: number | null;
  turnover_rate?: number | null;
  liquidity_status?: "complete" | "partial" | "unavailable";
  history_status: string;
  eod_status: string;
  data_source: string;
  provider_role: string;
  fetched_at: string;
  source_response_hash: string;
  snapshot_hash?: string;
  recent_5_trading_days?: RecentTradingDay[];
}

export interface RecentTradingDay {
  trade_date: string;
  daily_pct_change: number;
  close: number;
  data_status: "eod_complete";
}

export interface IntradaySnapshot {
  sector_key: string;
  trade_date: string;
  observed_at: string;
  index_value: number;
  pre_close: number;
  pct_change: number;
  volume: number | null;
  amount: number | null;
  provider: string;
  provider_symbol?: string | null;
  provider_role: string;
  lineage?: string | null;
  source_status?: string;
  freshness_status?: string;
  intraday_ma5?: number | null;
  intraday_vs_ma5?: number | null;
  native_history_status?: "complete" | "insufficient" | "provider_failed" | "unavailable";
  data_status: "intraday_fresh" | "intraday_stale" | "provider_failed";
  fetched_at: string;
}

export interface IntradayStatus {
  session_status: "running" | "paused";
  market_phase: "intraday_open" | "market_break" | "market_closed" | "calendar_error";
  market_phase_detail?: "non_trading_day" | "before_open" | "after_close" | "intraday_open" | "market_break" | "calendar_out_of_range" | "calendar_source_unavailable" | "calendar_rule_invalid";
  market_session?: "pre_open" | "open" | "market_break" | "closed" | "non_trading_day" | "calendar_error";
  intraday_trade_date?: string;
  refresh_interval_minutes: number;
  provider: string;
  provider_role: string;
  production_primary: null;
  production_primary_approved?: false;
  research_notice: string;
  last_refresh_at: string | null;
  last_attempt_at?: string | null;
  next_refresh_at: string | null;
  latest_snapshot_at: string | null;
  success_count: number;
  failure_count: number;
  stale_count: number;
  unsupported_count: number;
  supported_market_path_count?: number;
  viewer_provider_access: false;
  auto_start: boolean;
  admin_paused?: boolean;
  scheduler_registered?: boolean;
  calendar_coverage_start?: string | null;
  calendar_coverage_end?: string | null;
  calendar_source?: string | null;
  calendar_status?: "trading_day" | "confirmed_non_trading_day" | "calendar_out_of_range" | "calendar_unavailable";
  calendar_warning?: string | null;
  provider_health?: Array<Record<string, unknown>>;
  provider_cycle_stats?: {
    health_probe_count: number;
    primary_skipped_count: number;
    fallback_success_count: number;
    no_fallback_count: number;
  };
}

export interface SectorAssessment {
  id: string;
  sector_key: string;
  sector_name: string;
  current_path_status: PathStatus;
  path_status_label: string;
  explicitly_mentioned: boolean;
  recent_path_summary: string;
  current_judgement: string;
  main_basis: string;
  observation_condition: string;
  source_section: string;
  source_text_reference: string;
  review_status: string;
  manually_modified: boolean;
  revision_id: string;
  market: MarketSnapshot | null;
  extraction_method?: string;
  source_page?: number | null;
  source_text_start?: number | null;
  source_text_end?: number | null;
  source_text_excerpt?: string;
  confidence?: string;
  validation_flags?: string[];
  quality_status?: string;
  active_holding_interval?: HoldingInterval | null;
}

export interface HoldingInterval {
  status: "active" | "complete" | "market_insufficient" | "start_unknown";
  start_report_date?: string;
  start_market_as_of_date?: string;
  trading_days?: number | null;
  return_pct?: number;
  eod_return?: number;
  intraday_reference_return?: number;
  end_report_date?: string;
  end_market_as_of_date?: string;
  end_status?: PathStatus;
  calculation_status?: string;
  effective_status?: PathStatus | null;
  latest_report_not_mentioned?: boolean;
}

export interface EnhancedReport {
  report: Report;
  path_entries: PathEntry[];
  sector_assessments: SectorAssessment[];
  status_groups: Array<{ status: PathStatus; count: number; items: SectorAssessment[] }>;
  market_snapshots: MarketSnapshot[];
  comparison: { previous_report_id: string | null; previous_report_date?: string; status_changes: Array<{ sector_key: string; sector_name: string; from: PathStatus; to: PathStatus }>; counts: Record<string, number> };
  market_data_attached: boolean;
  data_notice: string;
}

export interface PathMatrix {
  caption: string;
  dates: Array<{ report_id: string; detail_report_id: string | null; has_detailed_report: boolean; report_date: string; market_as_of_date: string | null; market_weekday: string | null; weekday: string; is_weekend_report: boolean }>;
  groups: Array<{ group_order: number; group_name: string; sector_count: number }>;
  rows: Array<{ sector_key: string; sector_name: string; group_name: string; group_order: number; overall_order: number; cells: Array<PathEntry & { report_id: string; report_date: string }> }>;
  status_contract: { statuses: Array<{ code: PathStatus; label: string; color: string; order: number }> };
  period?: string;
  default_period?: string;
  available_period_count?: number;
  history_origin?: string;
}

export interface SectorResearch {
  sector_key: string;
  sector_name: string;
  market_path_key?: string;
  parent_report_topic?: string;
  report_topic_name?: string;
  group_name: string;
  latest_explicit_view: { report_id: string; report_date: string; path: PathEntry; assessment: SectorAssessment; report_snapshot: MarketSnapshot | null } | null;
  current_latest_market: MarketSnapshot | null;
  latest_complete_market?: MarketSnapshot | null;
  recent_5_trading_days?: RecentTradingDay[];
  intraday_snapshot?: IntradaySnapshot | null;
  intraday_status?: string;
  intraday_session?: IntradayStatus;
  market_support_status: "supported" | "unsupported";
  data_status: string;
  market_status_detail: string;
  reported_status?: PathStatus;
  effective_status?: PathStatus | null;
  active_holding_interval?: HoldingInterval | null;
  historical_holding_intervals?: HoldingInterval[];
  strict_holding_interval?: HoldingInterval | null;
  broad_holding_interval?: HoldingInterval | null;
  historical_strict_intervals?: HoldingInterval[];
  historical_broad_intervals?: HoldingInterval[];
  is_low_attention?: boolean;
  is_pinned_for_research?: boolean;
  recent_path_entries?: Array<{ id: string; report_id: string; detail_report_id: string | null; report_date: string; market_as_of_date: string | null; reported_status: PathStatus; effective_status: PathStatus | null; has_detailed_assessment: boolean; path: PathEntry }>;
  history: Array<{ report_id: string; report_date: string; path: PathEntry; assessment: SectorAssessment; report_snapshot: MarketSnapshot | null }>;
  detailed_history?: Array<{ report_id: string; report_date: string; path: PathEntry; assessment: SectorAssessment; report_snapshot: MarketSnapshot | null }>;
  recent_path?: Array<{ id: string; report_id: string; detail_report_id: string | null; report_date: string; market_as_of_date: string | null; reported_status: PathStatus; effective_status: PathStatus | null; has_detailed_assessment: boolean; path: PathEntry }>;
  market_history?: MarketSnapshot[];
  path_periods?: number;
  available_path_periods?: number;
  market_days?: number;
}
