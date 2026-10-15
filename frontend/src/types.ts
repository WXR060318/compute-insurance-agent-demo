export type Company = { id: string; name: string; industry: string; region: string; gpu_model: string; capacity: number; description: string };
export type Scenario = { id: string; name: string; subtitle: string };
export type Catalog = { companies: Company[]; scenarios: Scenario[]; meta: { rule_version: string; model_configured: boolean; simulation: boolean } };
export type EvaluationInput = { company_id: string; scenario_id: string; minute: number; budget: number | null; min_quality: number; sort_by: 'cost' | 'quality' };
export type Supplier = { id: string; name: string; region: string; gpu_model: string; available_cards: number; price_per_card_hour: number | null; quality: number; ready_minutes: number; deployment_minutes: number; total_ready_minutes: number; quote_valid: boolean; eligible: boolean; partial: boolean; reasons: string[]; cost: number | null; rank: number | null; selected: boolean };
export type ChartPoint = { time: string; minute: number; demand: number | null; forecast: number | null; capacity: number | null };
export type Evidence = { id: string; title: string; text: string };
export type Evaluation = {
 snapshot_id: string; input: EvaluationInput; company: Company; scenario: Scenario; now: string;
 metrics: { capacity: number | null; current_demand: number | null; predicted_peak: number | null; peak_gap: number | null; shortage_card_hours: number | null; first_shortage_at: string | null; shortage_duration_minutes: number | null; utilization: number | null; headroom: number | null; lead_minutes: number | null };
 risk: { level: 'low' | 'medium' | 'high' | 'unknown'; label: string; reason: string; data_quality: string; actions: string[] };
 chart: ChartPoint[]; suppliers: Supplier[];
 recommendation: { supplier_id: string | null; supplier_name: string | null; cost: number | null; baseline_cost: number | null; extra_cost: number | null; covered_cards: number | null; remaining_cards: number | null; summary: string; status: 'matched' | 'unresolved' | 'not_needed' | 'data_unavailable' };
 evidence: Evidence[]; service_rules: { id: string; title: string; status: string; text: string }[];
 meta: { simulation: boolean; rule_version: string; forecast_method: string; data_time: string; note: string };
};
export type Plan = { id: string; created_at: string; status: 'draft' | 'simulation_confirmed'; status_label: string; snapshot_id: string; supplier_id: string; supplier_name: string; cost: number; company_name: string; scenario_name: string; evaluation: Evaluation; confirmed_at: string | null; reviewer: string | null };
export type ChatResponse = { mode: 'offline' | 'live' | 'fallback'; answer: string; trace: { tool: string; label: string; status: string; summary: string }[]; evaluation: Evaluation; plan: Plan | null; limitations: string[] };
export type ChatMessage = { id: string; role: 'user' | 'assistant'; text: string; response?: ChatResponse; time: string };
