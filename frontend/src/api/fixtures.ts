import type {
  CaseDetail, CaseList, ChatReply, EntitySearch, EvalResult, Golden,
  Health, RuleChunk, ScreeningResult, Stats,
} from './types'

const CASE_ID = '00000000-0000-0000-0000-000000000001'
const SCREENING_ID = '00000000-0000-0000-0000-0000000000a1'

export const fixtureStats: Stats = {
  desc_entities: 2, wbs_engagements: 14, cot_requests: 7,
  dccs_search_results: 3480, rule_chunks: 19, cases: 1, screenings: 1,
}

export const fixtureHealth: Health = { status: 'ok', postgres: true, llm: false }

export const fixtureCaseList: CaseList = {
  items: [{
    case_id: CASE_ID,
    request_id: '12246557',
    service_offering: 'Technology & Transformation \\ Human Capital \\ Organization & Work Transformation',
    location: 'Malaysia (MY)',
    date_submitted: '2026-08-05',
    party_count: 3,
    has_golden: true,
    latest_screening_status: 'COMPLETE',
  }],
  total: 1,
}

export const fixtureCaseDetail: CaseDetail = {
  case_id: CASE_ID,
  request_id: '12246557',
  request_type: 'Conflict Check Request',
  originator: 'KARAMUDIN, NUR AMEERAH (MY - KUALA LUMPUR)',
  member_firm: 'Southeast Asia',
  location: 'Malaysia (MY)',
  office: 'TH',
  service_offering: 'Technology & Transformation \\ Human Capital \\ Organization & Work Transformation',
  engagement_name: 'JO-9671950 – HR Transformation (Ph1) / [QRM0034985]',
  engagement_details: 'Review existing HR initiatives and workforce structures, define a talent portfolio, and develop prioritized actions and an implementation roadmap to support business recovery and workforce optimization.',
  is_recurring: false,
  is_inbound_referral: false,
  has_iwrf: false,
  lead_partner: 'PHUKFON, ARIYA',
  lead_manager: 'MAKI, CHIHARU',
  date_submitted: '2026-08-05',
  parties: [
    { entity_name: 'KDDI (Thailand) Limited', party_side: 'CLIENT_SIDE', entity_role: 'Client', location: 'Thailand', stated_designation: 'Do Not Know', is_gup: false },
    { entity_name: 'KDDI Asia Pacific Pte Ltd', party_side: 'CLIENT_SIDE', entity_role: 'Shareholder', location: 'Singapore', stated_designation: 'Relationship', is_gup: false },
    { entity_name: 'KDDI CORPORATION', party_side: 'CLIENT_SIDE', entity_role: 'Global Ultimate Parent', location: 'Japan', stated_designation: 'Restricted', is_gup: true },
  ],
}

export const fixtureScreening: ScreeningResult = {
  screening_id: SCREENING_ID,
  case_id: CASE_ID,
  status: 'COMPLETE',
  final_result: 'APPROVED_WITH_CONDITIONS',
  quality_check_flags: [
    {
      severity: 'WARN',
      message: "Request states KDDI CORPORATION designation as 'Restricted'; DESC shows 'Audit Team Restricted, Relationship'. DESC is authoritative.",
      action: 'Contact requestor to clarify; if the requestor confirms the submitted value, escalate to SEAIndependence@deloitte.com copying the assigned Senior Analysts from the Conflicts and DESC teams',
      rule_citation: 'QRC slide 4',
    },
    {
      severity: 'INFO',
      message: 'Individual controlling the GUP not listed among relevant parties',
      action: 'Confirm relevant-party completeness with the requestor',
      rule_citation: 'QRC slide 4',
    },
  ],
  summary_table: [
    { entity_name: 'KDDI CORPORATION', source: 'DESC', country: 'Japan', designation_type: 'Audit Team Restricted, Relationship', gup_name: 'KDDI CORPORATION', lcsp_rp: 'Manabe, Hiroyuki (JP - Tokyo)', partner_name: 'Manabe, Hiroyuki (JP - Tokyo)', practice_office: 'Toyko', business_unit: null, status: null, entity_role: null, match_date: null, similarity: 1.0, exclusion_reason: null, note: null, rule_citation: 'QRC slide 5' , risk_tier: 'High', risk_reason: 'DESC records a Restricted designation (Audit Team Restricted) — independence risk (slide 5)' },
    { entity_name: 'KDDI Corporation', source: 'WBS', country: 'VN', designation_type: null, gup_name: null, lcsp_rp: null, partner_name: 'Van Trinh Bui', practice_office: 'Ho Chi Minh City', business_unit: 'Non-Assurance', status: 'Ongoing', entity_role: null, match_date: null, similarity: 1.0, exclusion_reason: null, note: null, rule_citation: 'QRC slide 6; QRC slide 6' , risk_tier: 'Low', risk_reason: 'Non-Assurance ongoing — record only (slide 6)' },
    { entity_name: 'KDDI Corporation', source: 'COT', country: 'Singapore', designation_type: null, gup_name: null, lcsp_rp: null, partner_name: 'Liew, Li Mei', practice_office: null, business_unit: 'Non-Assurance', status: 'Ongoing', entity_role: null, match_date: '2026-05-05', similarity: 1.0, exclusion_reason: null, note: null, rule_citation: 'QRC slide 9' , risk_tier: 'Low', risk_reason: 'Non-Assurance ongoing — record only (slide 6)' },
    { entity_name: 'KDDI Asia Pacific Pte Ltd', source: 'DCCS_HISTORY', country: null, designation_type: null, gup_name: null, lcsp_rp: null, partner_name: 'PHAM THI QUYNH, NGOC', practice_office: null, business_unit: null, status: 'Pursuing', entity_role: 'Client', match_date: '2026-02-25', similarity: 1.0, exclusion_reason: null, note: null, rule_citation: 'QRC slide 10' , risk_tier: 'Low', risk_reason: 'Prior DCCS activity — contextual (slide 10)' },
  ],
  possible_matches: [
    { entity_name: 'KDDI (THAILAND) COMPANY LIMITED', source: 'DESC', country: 'Thailand', designation_type: 'Relationship', gup_name: 'KDDI CORPORATION', lcsp_rp: null, partner_name: null, practice_office: null, business_unit: null, status: null, entity_role: null, match_date: null, similarity: 0.78, exclusion_reason: 'Below auto-include threshold — analyst review required', note: 'Below auto-include threshold — analyst review required', rule_citation: 'QRC slide 5' , risk_tier: 'Medium', risk_reason: 'DESC designation Relationship requires a condition (slide 5)' },
  ],
  excluded_matches: [
    { entity_name: 'KDDI CORPORATION', source: 'DCCS_HISTORY', country: null, designation_type: null, gup_name: null, lcsp_rp: null, partner_name: null, practice_office: null, business_unit: null, status: null, entity_role: 'Client', match_date: '2021-07-30', similarity: 1.0, exclusion_reason: 'DCCS request dated 2021-07-30 is older than 2 years', note: null, rule_citation: 'QRC slide 10' , risk_tier: null, risk_reason: null },
    { entity_name: 'KDDI Summit Global Myanmar Co., Ltd.', source: 'DCCS_HISTORY', country: null, designation_type: null, gup_name: null, lcsp_rp: null, partner_name: null, practice_office: null, business_unit: null, status: null, entity_role: 'Target', match_date: '2024-03-02', similarity: 0.86, exclusion_reason: "DCCS status 'Opportunity Lost' is excluded per slide 10", note: null, rule_citation: 'QRC slide 10' , risk_tier: null, risk_reason: null },
  ],
  risk_summary: { High: 1, Medium: 1, Low: 2 },
  conditions: ['Relationship client in DESC', 'Audit Team Restricted in DESC'],
  cross_border_actions: [
    { jurisdiction: 'Japan', outcome: 'Request Not Required', reason: 'GUP (KDDI CORPORATION) is listed in DESC', rule_citation: 'QRC slide 11' },
  ],
  unchecked_sources: [
    { source: 'ONE_WINDOW', reason: 'Strategic Client / Directorship / Sanctions / Open Opportunities data not provided' },
  ],
  draft_response: 'Conflict check response — Request 12246557\n\n...\n\n── Reminders ──\n\n[Slide 14 footer text appears here verbatim]',
  error: null,
  created_at: '2026-09-05T10:00:00Z',
  completed_at: '2026-09-05T10:00:22Z',
}

export const fixtureGolden: Golden = {
  request_id: '12246557',
  final_result: 'Approved with Conditions',
  conditions: ['Relationship client in DESC'],
  analyst_comments: ['Listed in DESC', 'Local WBS: Non-Assurance', 'WBS & COT match'],
  cross_border: [{ jurisdiction: 'Japan', outcome: 'Request Not Required', comment: 'Listed in DESC' }],
}

export const fixtureEval: EvalResult = {
  case_id: CASE_ID,
  screening_id: SCREENING_ID,
  score: '7/7',
  passed: 7,
  total: 7,
  checks: [
    { name: 'final_result', expected: 'Approved with Conditions', actual: 'APPROVED_WITH_CONDITIONS', passed: true },
    { name: 'condition_desc_relationship', expected: 'Relationship client in DESC', actual: 'Relationship client in DESC', passed: true },
    { name: 'wbs_non_assurance', expected: 'all WBS matches Non-Assurance', actual: '8/8 Non-Assurance', passed: true },
    { name: 'wbs_match_found', expected: 'at least 1 WBS match', actual: '8 WBS matches', passed: true },
    { name: 'cot_match_found', expected: 'at least 1 COT match', actual: '6 COT matches', passed: true },
    { name: 'cross_border_japan', expected: 'Japan → Request Not Required', actual: 'Japan → Request Not Required', passed: true },
    { name: 'desc_contradiction_caught', expected: 'WARN flag present', actual: 'WARN flag present', passed: true },
  ],
}

export const fixtureRules: RuleChunk[] = [
  { chunk_id: 'qrc-6-1', slide_number: 6, title: 'WBS Business-Unit Classification', source_db: 'WBS', chunk_type: 'narrative', text: '[Slide 6 — WBS Business-Unit Classification]\nIf under T&L, SR&T, T&T : should be indicated as "Non-Assurance"...', score: null },
  { chunk_id: 'qrc-10-1', slide_number: 10, title: 'DCCS Search Result Relevance Tests', source_db: 'DCCS_SEARCH', chunk_type: 'narrative', text: '[Slide 10 — DCCS Search Result Relevance Tests]\nFor prior 2 years submission date, no need to include the match...', score: null },
]

export const fixtureSearch: EntitySearch = {
  query: 'KDDI Corporation',
  results: {
    DESC: [{ source: 'DESC', matched_name: 'KDDI CORPORATION', query_name: 'KDDI Corporation', similarity: 1.0, country: 'Japan', designation_type: 'Audit Team Restricted, Relationship', gup_name: 'KDDI CORPORATION', partner_name: 'Manabe, Hiroyuki (JP - Tokyo)', practice_office: 'Toyko', business_unit: null, status: null, entity_role: null, match_date: null, rule_citation: null }],
    WBS: [], COT: [], DCCS_HISTORY: [],
  },
}

export const fixtureChat: ChatReply = {
  session_id: '00000000-0000-0000-0000-0000000000c1',
  reply: 'That match was excluded because its submission date is more than two years old (QRC slide 10).',
  agent_trace: [
    { agent: 'orchestrator', summary: 'Routed question to the rules agent for a QRC lookup', tool_calls: [] },
    { agent: 'rules_agent', summary: 'Retrieved QRC slide 10', tool_calls: [{ tool: 'search_rules', args: { query: 'why excluded' } }] },
  ],
  citations: [{ slide_number: 10, title: 'DCCS Search Result Relevance Tests' }],
}
