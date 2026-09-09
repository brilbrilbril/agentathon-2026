export interface Party {
  entity_name: string
  party_side: string
  entity_role: string | null
  entity_type?: string | null
  location: string | null
  stated_designation: string | null
  is_gup: boolean
}

export interface CaseSummary {
  case_id: string
  request_id: string | null
  service_offering: string | null
  location: string | null
  date_submitted: string | null
  party_count: number
  has_golden: boolean
  latest_screening_status: string | null
}

export interface CaseList {
  items: CaseSummary[]
  total: number
}

export interface CaseDetail {
  case_id: string
  request_id: string | null
  request_type: string | null
  originator: string | null
  member_firm: string | null
  location: string | null
  office: string | null
  service_offering: string | null
  engagement_name: string | null
  engagement_details: string | null
  is_recurring: boolean
  is_inbound_referral: boolean
  has_iwrf: boolean
  lead_partner: string | null
  lead_manager: string | null
  date_submitted: string | null
  parties: Party[]
}

export interface QCFlag {
  severity: string
  message: string
  action: string | null
  rule_citation: string | null
}

export interface MatchRow {
  entity_name: string | null
  source: string
  country: string | null
  designation_type: string | null
  gup_name: string | null
  lcsp_rp: string | null
  partner_name: string | null
  practice_office: string | null
  business_unit: string | null
  status: string | null
  entity_role: string | null
  match_date: string | null
  similarity: number | null
  exclusion_reason: string | null
  note: string | null
  rule_citation: string | null
  risk_tier: 'High' | 'Medium' | 'Low' | null
  risk_reason: string | null
}

export interface CrossBorderAction {
  jurisdiction: string
  outcome: string
  reason: string | null
  rule_citation: string | null
}

export interface UncheckedSource {
  source: string
  reason: string
}

export interface ScreeningResult {
  screening_id: string
  case_id: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETE' | 'FAILED'
  final_result: string | null
  quality_check_flags: QCFlag[]
  summary_table: MatchRow[]
  risk_summary: Record<string, number>
  possible_matches: MatchRow[]
  excluded_matches: MatchRow[]
  conditions: string[]
  cross_border_actions: CrossBorderAction[]
  unchecked_sources: UncheckedSource[]
  draft_response: string | null
  error: string | null
  created_at: string | null
  completed_at: string | null
}

export interface Golden {
  request_id: string
  final_result: string | null
  conditions: string[]
  analyst_comments: string[]
  cross_border: { jurisdiction?: string; outcome?: string; comment?: string }[]
}

export interface EvalCheck {
  name: string
  expected: string
  actual: string
  passed: boolean
}

export interface EvalResult {
  case_id: string
  screening_id: string
  score: string
  passed: number
  total: number
  checks: EvalCheck[]
}

export interface EntityMatch {
  source: string
  matched_name: string
  query_name: string
  similarity: number
  country: string | null
  designation_type: string | null
  gup_name: string | null
  partner_name: string | null
  practice_office: string | null
  business_unit: string | null
  status: string | null
  entity_role: string | null
  match_date: string | null
  rule_citation: string | null
}

export interface EntitySearch {
  query: string
  results: Record<string, EntityMatch[]>
}

export interface RuleChunk {
  chunk_id: string
  slide_number: number
  title: string | null
  source_db: string
  chunk_type: string
  text: string
  score: number | null
}

export interface AgentTrace {
  agent: string
  summary: string | null
  tool_calls: { tool?: string; args?: Record<string, unknown>; result_count?: number }[]
}

export interface ChatReply {
  session_id: string
  reply: string
  agent_trace: AgentTrace[]
  citations: { slide_number: number; title: string | null }[]
}

export interface Stats {
  desc_entities: number
  wbs_engagements: number
  cot_requests: number
  dccs_search_results: number
  rule_chunks: number
  cases: number
  screenings: number
}

export interface Health {
  status: string
  postgres: boolean
  llm: boolean
}

export interface SuggestedQuestion {
  category: string
  question: string
}

export type StreamEvent =
  | { type: 'session'; session_id: string }
  | { type: 'status'; message: string }
  | { type: 'tool_call'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; summary: string }
  | { type: 'token'; text: string }
  | { type: 'error'; message: string }
  | {
      type: 'done'
      session_id: string
      reply: string
      agent_trace: AgentTrace[]
      citations: { slide_number: number; title: string | null }[]
      seconds: number
    }

export interface ChatMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string
  agent_name: string | null
  tool_calls: AgentTrace[]
  created_at: string | null
}
