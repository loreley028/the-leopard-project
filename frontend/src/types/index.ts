export type Role = "viewer" | "admin";
export type ReportStatus = "uploaded" | "parsing" | "needs_review" | "ready_to_publish" | "published" | "withdrawn" | "parse_failed";

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
  status: ReportStatus;
  core_view: string;
  market_path: string;
  risk_warning: string;
  focus_sectors: string[];
  created_at: string;
  published_at: string | null;
  mentions: SectorMention[];
  pdf_url: string;
  data_notice: string;
  change_summary?: { kind: string; text: string; added_focus_sectors?: string[]; removed_focus_sectors?: string[] };
  raw_text?: string;
  parse_note?: string;
  original_filename?: string;
  unmapped_terms?: Array<{ id: string; term: string; status: string; resolved_sector_key: string | null }>;
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
  data_status: "supported" | "proxy" | "short_history" | "unsupported";
  market_status_detail: string;
  timeline?: Array<{ report_id: string; report_date: string; report_title: string; summary: string }>;
}
