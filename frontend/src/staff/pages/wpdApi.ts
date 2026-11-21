import { api } from '../../shared/api/client';
import { call, type Result } from '../../shared/api/problem';

/**
 * Types and calls for the anomaly and impact endpoints. They mirror backend/app/modules/{anomaly,analytics}/schemas.py.
 * The generated client (`npm run gen:api`) will carry them after the next regeneration; until then this file is the contract.
 */

export interface DetectorStatus {
  detector: 'shared_payout' | 'application_spike' | 'helper_burst' | 'repeated_identity';
  title: string;
  status: 'flagged' | 'clear' | 'abstained';
  flags: number;
  abstained_reason: string | null;
  data_points: Record<string, string | number | boolean | null>;
  params: Record<string, string | number | boolean | null>;
}

export interface ScanSummary {
  run_id: string;
  ran_at: string;
  trigger: string;
  applications_scanned: number;
  cases_opened: number;
  cases_refreshed: number;
  suppressed: number;
  detectors: DetectorStatus[];
}

export interface Flag {
  case_id: string;
  case_status: string;
  detector: DetectorStatus['detector'];
  title: string;
  pattern_key: string;
  confidence: number | null;
  priority: number;
  evidence: Record<string, string | number>;
  evidence_count: number;
  evidence_ids: string[];
  cheapest_check: string | null;
  resolution: string | null;
  created_at: string;
}

export interface Anomalies {
  last_scan: ScanSummary | null;
  flags: Flag[];
  counts: Record<string, number>;
  note: string;
}

export interface Duration {
  n: number;
  median_seconds: number | null;
  p90_seconds: number | null;
}

export interface Impact {
  generated_at: string;
  window_days: number;
  department: string;
  handoff: {
    decisions: number;
    by_route: Record<string, number>;
    rate: Record<string, number | null>;
    handoff_rate: number | null;
    not_automatic_rate: number | null;
    silent_guesses: number;
  };
  time_to_decision: {
    automatic: Duration;
    automatic_engine_latency_ms_p50: number | null;
    human_case: Duration;
    human_review_hands_on: Duration;
    human_case_by_kind: Record<string, Duration>;
  };
  fraud_stopped: {
    forged_cards_flagged: number;
    identity_mismatches: number;
    duplicates_caught: number;
    duplicate_candidates: number;
    duplicates_linked_by_a_person: number;
    scams_flagged: number;
    scams_confirmed_by_a_person: number;
    anomaly_cases: { total: number; active: number; confirmed: number; dismissed: number };
    payments_stopped: number;
    payments_stopped_pkr: number;
    held_for_a_person_by_a_guard: number;
  };
  cost_per_claim: {
    decisions: number;
    per_claim_units: number | null;
    all_to_a_person_per_claim_units: number | null;
    units_saved_per_claim: number | null;
    per_claim_pkr_assumed: number | null;
  };
  payments: {
    count: number;
    amount_pkr: number;
    by_status: Record<string, { count: number; amount_pkr: number }>;
    settled_pkr: number;
    average_pkr: number | null;
  };
  time_saved: {
    automatic_decisions: number;
    minutes_per_manual_review_used: number;
    hands_on_source: string;
    hands_on_hours_saved: number;
    waiting_hours_avoided: number | null;
    label: string;
  };
  replay: {
    synthetic: boolean;
    label: string;
    cases: number | null;
    accuracy_of_automatic: number | null;
    false_approvals: number | null;
    false_rejections: number | null;
    unnecessary_handoffs: number | null;
    abstention_rate: number | null;
    cost_per_case: number | null;
    all_human_cost_per_case: number | null;
    ece: number | null;
    stored_run: boolean | null;
  };
  assumptions: { name: string; value: number; unit: string; used_for: string; label: string }[];
  measured_from: Record<string, number>;
  notes: string[];
}

interface Raw {
  GET(path: string, init?: { params?: { query?: Record<string, string | number> } }): Promise<{ data?: unknown; error?: unknown; response: Response }>;
  POST(path: string): Promise<{ data?: unknown; error?: unknown; response: Response }>;
}
const raw = api as unknown as Raw;

export const getImpact = (days: number, minutes: number): Promise<Result<Impact>> =>
  call(raw.GET('/v1/admin/impact', { params: { query: { days, assumed_minutes_per_manual_review: minutes } } }) as Promise<{ data?: Impact; error?: unknown; response: Response }>);

export const getAnomalies = (): Promise<Result<Anomalies>> =>
  call(raw.GET('/v1/anomalies') as Promise<{ data?: Anomalies; error?: unknown; response: Response }>);

export const runAnomalyScan = (): Promise<Result<{ job_id: string; status: string; already_queued: boolean }>> =>
  call(raw.POST('/v1/anomalies/run') as Promise<{ data?: { job_id: string; status: string; already_queued: boolean }; error?: unknown; response: Response }>);

/** Seconds as the largest sensible unit: 4 s, 5 min, 2 h 10 min. */
export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return 'n/a';
  if (s < 90) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = s / 60;
  if (m < 120) return `${m.toFixed(m < 10 ? 1 : 0)} min`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h} h ${Math.round(m - h * 60)} min` : `${(h / 24).toFixed(1)} days`;
}
