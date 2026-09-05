# DEV C — API Layer & React Frontend

**Owner:** Dev C
**Scope:** FastAPI controllers + schemas, and the entire React app. You own the API contract — publish it first, everyone codes against it.
**You do NOT touch:** repositories/ingestion (Dev A), agents (Dev B).

**Read `MASTER_overview.md` and `00_SETUP_AND_REQUIREMENTS.md` first.**

> **Revision note.** Two changes from the earlier draft: (1) **the file-upload flow is deleted** — cases are ingested offline, so there is no `POST /cases/upload`, no PDF error handling, no upload UI; (2) there is a new **eval screen** comparing pipeline output against the analyst's real determination. That screen is your strongest demo asset — build it.

---

## Requirements — Dev C only

**Backend packages you own:**
```txt
fastapi>=0.115,<1.0
uvicorn[standard]>=0.32,<1.0
pydantic>=2.9,<3.0
pydantic-settings>=2.6,<3.0
```
`python-multipart` is **no longer needed** — there are no file uploads.

**Frontend:**
```txt
react@^18.3  react-dom@^18.3  react-router-dom@^6.28
@tanstack/react-query@^5.62  axios@^1.7  lucide-react@^0.460  clsx@^2.1
vite@^6.0  typescript@^5.7  @vitejs/plugin-react@^4.3
tailwindcss@^3.4  postcss@^8.4  autoprefixer@^10.4
@types/react@^18.3  @types/react-dom@^18.3
```
Tailwind **v3, not v4**.

**Env vars.** Backend: `CORS_ORIGINS`, `LOG_LEVEL`, `DATABASE_URL`. Frontend: `VITE_API_BASE_URL`, `VITE_MOCK_MODE`, `VITE_POLL_INTERVAL_MS`.

| # | Functional requirement |
|---|---|
| C1 | `app/schemas/` committed within hour 1 — this is the contract A and B build against |
| C2 | Controllers contain zero business logic: validate → call service/repo → map DTO → return |
| C3 | DTOs never expose SQLAlchemy ORM objects |
| C4 | One global exception handler; every error uses the `{"error":{"code","message","detail"}}` envelope |
| C5 | Error codes: `CASE_NOT_FOUND`, `SCREENING_NOT_FOUND`, `GOLDEN_NOT_FOUND`, `SCREENING_FAILED`, `LLM_ERROR`, `VALIDATION_ERROR` |
| C6 | Screening runs via `BackgroundTasks` — no Celery |
| C7 | CORS allows `http://localhost:5173` |
| C8 | OpenAPI docs render at `/docs` with every endpoint documented |
| C9 | `VITE_MOCK_MODE=true` renders the whole UI from fixtures with the backend off |
| C10 | Fixtures written from §1's example payloads during hour 1 |
| C11 | **No upload endpoint or upload UI anywhere** |
| C12 | Screening screen polls while `RUNNING`, stops on `COMPLETE`/`FAILED` |
| C13 | Result screen renders every section of the §1 payload including `possible_matches`, `excluded_matches`, `unchecked_sources` |
| C14 | Eval screen shows pipeline output beside the analyst's determination, per-check pass/fail |
| C15 | Chat renders the agent-trace panel — highest-value UI element, prioritise over chat polish |
| C16 | Similarity as a percentage with a colour ramp: ≥0.95 green, 0.80–0.95 neutral, <0.80 amber |
| C17 | Skeleton loaders, not spinners, on the polling screen |
| C18 | No SSE/streaming on Day 1 — blocking chat endpoint only |

---

## 1. API specification

Base path `/api/v1`. IDs are UUIDs. Timestamps ISO 8601 UTC.

### Cases

**`GET /api/v1/cases`**
```jsonc
{ "items": [ { "case_id":"uuid", "request_id":"12246557",
               "service_offering":"Technology & Transformation \\ Human Capital \\ Organization & Work Transformation",
               "location":"Malaysia (MY)", "date_submitted":"2026-08-05",
               "party_count":3, "has_golden":true,
               "latest_screening_status":"COMPLETE" } ], "total": 1 }
```

**`GET /api/v1/cases/{case_id}`**
```jsonc
{ "case_id":"uuid", "request_id":"12246557", "request_type":"Conflict Check Request",
  "originator":"KARAMUDIN, NUR AMEERAH (MY - KUALA LUMPUR)",
  "member_firm":"Southeast Asia", "location":"Malaysia (MY)", "office":"TH",
  "service_offering":"Technology & Transformation \\ Human Capital \\ Organization & Work Transformation",
  "engagement_name":"JO-9671950 – HR Transformation (Ph1) / [QRM0034985]",
  "engagement_details":"Review existing HR initiatives and workforce structures...",
  "is_recurring":false, "is_inbound_referral":false, "has_iwrf":false,
  "lead_partner":"PHUKFON, ARIYA", "lead_manager":"MAKI, CHIHARU",
  "date_submitted":"2026-08-05",
  "parties":[
    { "entity_name":"KDDI (Thailand) Limited", "party_side":"CLIENT_SIDE",
      "entity_role":"Client", "location":"Thailand",
      "stated_designation":"Do Not Know", "is_gup":false },
    { "entity_name":"KDDI Asia Pacific Pte Ltd", "party_side":"CLIENT_SIDE",
      "entity_role":"Shareholder", "location":"Singapore",
      "stated_designation":"Relationship", "is_gup":false },
    { "entity_name":"KDDI CORPORATION", "party_side":"CLIENT_SIDE",
      "entity_role":"Global Ultimate Parent", "location":"Japan",
      "stated_designation":"Restricted", "is_gup":true }
  ] }
```

**`POST /api/v1/cases`** — manual creation, for screening an entity not already ingested
```jsonc
// request
{ "request_id":"MANUAL-001", "service_offering":"T&T",
  "engagement_details":"...", "location":"Indonesia",
  "is_inbound_referral":false, "has_iwrf":false,
  "parties":[ { "entity_name":"...", "party_side":"CLIENT_SIDE",
                "entity_role":"Client", "location":"...",
                "stated_designation":null, "is_gup":false } ] }
// 201 -> same shape as GET /cases/{id}
```

**`DELETE /api/v1/cases/{case_id}`** → 204. Only for manually created cases; ingested cases return `400`.

> There is no `POST /cases/upload`. Cases come from offline ingestion or the manual form.

### Screening

**`POST /api/v1/cases/{case_id}/screen`** → `202 { "screening_id":"uuid", "status":"PENDING" }`

**`GET /api/v1/screenings/{screening_id}`**
```jsonc
{
  "screening_id":"uuid", "case_id":"uuid", "status":"COMPLETE",
  "final_result":"APPROVED_WITH_CONDITIONS",
  "quality_check_flags":[
    { "severity":"WARN",
      "message":"Request states KDDI CORPORATION designation as 'Restricted'; DESC shows 'Audit Team Restricted, Relationship'. DESC is authoritative.",
      "action":"Contact requestor to clarify; if confirmed, escalate to SEAIndependence@deloitte.com copying the assigned Senior Analysts from the Conflicts and DESC teams",
      "rule_citation":"QRC slide 4" },
    { "severity":"INFO",
      "message":"Individual controlling the GUP not listed among relevant parties",
      "action":"Confirm relevant-party completeness with the requestor",
      "rule_citation":"QRC slide 4" }
  ],
  "summary_table":[
    { "entity_name":"KDDI CORPORATION", "source":"DESC", "country":"Japan",
      "designation_type":"Audit Team Restricted, Relationship",
      "gup_name":"KDDI CORPORATION", "lcsp_rp":"Manabe, Hiroyuki (JP - Tokyo)",
      "business_unit":null, "partner_name":null, "practice_office":null,
      "status":null, "similarity":1.0, "rule_citation":"QRC slide 5" },
    { "entity_name":"KDDI Corporation", "source":"WBS", "country":"VN",
      "practice_office":"Ho Chi Minh City", "business_unit":"Non-Assurance",
      "partner_name":"Van Trinh Bui", "status":"Ongoing",
      "similarity":1.0, "rule_citation":"QRC slide 6" },
    { "entity_name":"KDDI Corporation", "source":"COT", "country":"Singapore",
      "business_unit":"Non-Assurance", "partner_name":"Liew, Li Mei",
      "status":"Ongoing", "similarity":1.0, "rule_citation":"QRC slide 9" },
    { "entity_name":"KDDI Asia Pacific Pte Ltd", "source":"DCCS_HISTORY",
      "entity_role":"Client", "match_date":"2026-02-25",
      "partner_name":"PHAM THI QUYNH, NGOC", "status":"Pursuing",
      "similarity":1.0, "rule_citation":"QRC slide 10" }
  ],
  "possible_matches":[
    { "entity_name":"KDDI (THAILAND) COMPANY LIMITED", "source":"DESC",
      "similarity":0.78, "designation_type":"Relationship",
      "note":"Shares GUP with the client. Below auto-include threshold — analyst review required" }
  ],
  "excluded_matches":[
    { "entity_name":"KDDI CORPORATION", "source":"DCCS_HISTORY",
      "match_date":"2021-07-30",
      "exclusion_reason":"Submission date older than 2 years",
      "rule_citation":"QRC slide 10" },
    { "entity_name":"KDDI Summit Global Myanmar Co., Ltd.", "source":"DCCS_HISTORY",
      "exclusion_reason":"Status is Opportunity Lost",
      "rule_citation":"QRC slide 10" }
  ],
  "conditions":["Relationship client in DESC"],
  "cross_border_actions":[
    { "jurisdiction":"Japan", "outcome":"Request Not Required",
      "reason":"GUP (KDDI CORPORATION) is listed in DESC",
      "rule_citation":"QRC slide 11" }
  ],
  "unchecked_sources":[
    { "source":"ONE_WINDOW",
      "reason":"Strategic Client / Directorship / Sanctions / Open Opportunities data not provided" }
  ],
  "draft_response":"full text ending with the verbatim DPM 1420 footer...",
  "created_at":"...", "completed_at":"..."
}
```
While running: `{"screening_id":"...","status":"RUNNING","progress":{"stage":"SEARCH","message":"Searching DCCS history for KDDI CORPORATION"}}`

**`GET /api/v1/cases/{case_id}/screenings`** → list
**`GET /api/v1/screenings/{screening_id}/draft-response`** → `{"draft_response":"...","format":"markdown"}`

### Eval

**`GET /api/v1/cases/{case_id}/golden`** → the analyst's stored determination
```jsonc
{ "request_id":"12246557", "final_result":"Approved with Conditions",
  "conditions":["Relationship client in DESC"],
  "analyst_comments":["Listed in DESC","Local WBS: Non-Assurance","WBS & COT match"],
  "cross_border":[ { "jurisdiction":"Japan", "outcome":"Request Not Required",
                     "comment":"Listed in DESC" } ] }
```

**`POST /api/v1/cases/{case_id}/evaluate`** → runs screening then scores it
```jsonc
{ "case_id":"uuid", "screening_id":"uuid", "score":"6/7",
  "checks":[
    { "name":"final_result", "expected":"Approved with Conditions",
      "actual":"APPROVED_WITH_CONDITIONS", "passed":true },
    { "name":"condition_desc_relationship", "expected":"Relationship client in DESC",
      "actual":"Relationship client in DESC", "passed":true },
    { "name":"wbs_non_assurance", "expected":"all WBS matches Non-Assurance",
      "actual":"4/4 Non-Assurance", "passed":true },
    { "name":"cross_border_japan", "expected":"Request Not Required",
      "actual":"Request Not Required", "passed":true },
    { "name":"desc_contradiction_caught", "expected":"WARN flag present",
      "actual":"WARN flag present", "passed":true }
  ] }
```

### Search

**`GET /api/v1/search/entities?q={name}&sources=DESC,WBS,COT,DCCS_HISTORY&threshold=0.8`**
```jsonc
{ "query":"KDDI", "results":{ "DESC":[...], "WBS":[...], "COT":[...], "DCCS_HISTORY":[...] } }
```

**`GET /api/v1/rules/search?q={question}&source_db=WBS&top_k=3`**
```jsonc
{ "results":[ { "chunk_id":"slide6_a", "slide_number":6,
                "title":"Perform Search to Conflicts Databases – WBS",
                "source_db":"WBS", "chunk_type":"narrative",
                "text":"...", "score":0.87 } ] }
```

**`GET /api/v1/rules`** → all chunks, for the Guide tab

### Chat

**`POST /api/v1/chat`**
```jsonc
// request
{ "session_id":"uuid|null", "case_id":"uuid|null",
  "message":"Why was the 2021 DCCS match excluded?" }
// 200
{ "session_id":"uuid",
  "reply":"That match was excluded because its submission date is more than two years old...",
  "agent_trace":[
    { "agent":"orchestrator", "summary":"Procedural question — routed to rules agent" },
    { "agent":"rules_agent",
      "tool_calls":[ {"tool":"get_rules_by_source","args":{"source_db":"DCCS_SEARCH"}} ],
      "summary":"Retrieved QRC slide 10" }
  ],
  "citations":[ { "slide_number":10, "title":"Perform Search to Conflicts Databases – DCCS Search Result" } ] }
```

**`GET /api/v1/chat/{session_id}/messages`** → history

### Meta
**`GET /api/v1/health`** → `{"status":"ok","postgres":true,"llm":true}`
**`GET /api/v1/stats`** → row counts per source + rule-chunk count + case count

### Errors
```jsonc
{ "error": { "code":"CASE_NOT_FOUND", "message":"...", "detail":{} } }
```

---

## 2. FastAPI structure (MVC)

```
app/
├── controllers/
│   ├── case_controller.py       # /cases
│   ├── screening_controller.py  # /screen, /screenings
│   ├── eval_controller.py       # /golden, /evaluate
│   ├── chat_controller.py       # /chat
│   ├── search_controller.py     # /search, /rules
│   └── health_controller.py
├── schemas/                     # DTOs only — never leak ORM models
└── main.py                      # app factory, CORS, routers, exception handlers
```

Controllers are thin: validate → call service/repo → map DTO → return. Dependency-inject the session via `Depends(get_db)`. One global exception handler. `BackgroundTasks` for screening.

---

## 3. React frontend

Stack: Vite + React + TypeScript + Tailwind + TanStack Query + react-router. Hand-rolled Tailwind components plus `lucide-react` icons — faster than fighting a design system.

### Screens

**1. Dashboard** (`/`) — row counts from `/stats` across all four data sources; case list with status pill and a "has ground truth" badge.

**2. Case detail** (`/cases/:id`) — engagement details, engagement team, and the parties table showing `entity_role` and `stated_designation`. Add a "Run screening" button and, when `has_golden`, a "Run evaluation" button.

**3. New case** (`/cases/new`) — manual form with a repeatable parties table (name, side, role, location, stated designation, is GUP). **No upload tab.**

**4. Screening result** (`/screenings/:id`) — the money screen. Poll while `RUNNING`.
   - Final result badge (green `NO_CONFLICTS_IDENTIFIED` / amber `APPROVED_WITH_CONDITIONS`)
   - Quality-check flags as cards, each with the required action and slide citation. The DESC-contradiction WARN should be visually prominent — it's your best demo beat
   - Summary table grouped by source, with a source badge and rule-citation chip per row
   - Collapsible: "Possible matches (analyst review)" and "Excluded matches" with reasons
   - Cross-border actions panel
   - "Sources not checked" notice
   - Conditions list
   - Draft response in a monospace panel with a copy button

**5. Evaluation** (`/cases/:id/eval`) — two columns: your pipeline's output beside the analyst's actual determination, with a per-check pass/fail table and an overall score. **This is the screen that wins the demo.** Build it even if chat polish suffers.

**6. Chat** (`/chat`, `/cases/:id/chat`) — message list, case selector, and a collapsible agent-trace panel per assistant message showing which agent ran and which tools it called. Citations render as chips opening the rule text in a side drawer.

**7. Search** (`/search`) — free-text lookup, four result columns with similarity scores.

**8. Guide** (`/guide`) — all rule chunks from `GET /rules`, grouped by `source_db`. Cheap, and proves the rule corpus is real.

### Frontend rules
- All API calls in `src/api/client.ts` with typed responses mirroring §1.
- `VITE_MOCK_MODE=true` swaps in `src/api/fixtures.ts`. Write fixtures hour one; build the whole UI against them.
- Skeleton loaders on polling screens.
- Similarity colour ramp per C16.

---

## 4. Two-day schedule

**Day 1 AM** — write `app/schemas/`, commit the API contract, announce it. Scaffold FastAPI with all routes returning fixtures. Scaffold Vite.
**Day 1 PM** — Dashboard, Case detail, Search, Guide — all against mocks.
**Day 2 AM** — wire Dev A's repos into search/rules controllers; wire Dev B's `run_screening`; build the Screening result screen.
**Day 2 PM** — Evaluation screen, Chat + agent trace, error states, end-to-end run on case 12246557, rehearse the demo.

---

## 5. Deliverables checklist

- [ ] API contract committed within hour 1 and announced to Dev A + Dev B
- [ ] `MOCK_MODE` fixtures for every endpoint
- [ ] No upload endpoint, no upload UI, no `python-multipart` dependency
- [ ] Case detail screen shows all three parties with their roles and stated designations
- [ ] Screening result screen renders every section of the §1 payload
- [ ] Evaluation screen renders the side-by-side comparison and pass/fail table
- [ ] Chat agent-trace panel renders
- [ ] `/health` green before the demo starts
