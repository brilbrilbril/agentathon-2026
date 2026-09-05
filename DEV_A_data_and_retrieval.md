# DEV A — Data Layer, Ingestion & Retrieval

**Owner:** Dev A
**Scope:** Postgres schema, ETL from all three source files, rule storage, all repository + search functions, the deterministic rules engine. You own the **Model** layer.
**You do NOT touch:** LangGraph agents (Dev B), FastAPI routes or React (Dev C).

**Read `MASTER_overview.md` and `00_SETUP_AND_REQUIREMENTS.md` first.**

> **Revision note.** Two changes from the earlier draft: (1) **no Qdrant, no embeddings** — rule retrieval is Postgres full-text search; (2) the PDF is **ingested offline** and yields a fourth searchable database plus a ground-truth answer key. There is no runtime PDF upload.

---

## Requirements — Dev A only

**Packages you own:**
```txt
sqlalchemy>=2.0.36,<3.0
psycopg[binary]>=3.2,<4.0
alembic>=1.14,<2.0
pandas>=2.2,<3.0
openpyxl>=3.1,<4.0
python-pptx>=1.0,<2.0
pdfplumber>=0.11,<1.0
rapidfuzz>=3.10,<4.0
```
Plus the **system binary** `pdftotext` (poppler-utils). Verify it before writing the PDF loader.

**Do not install** `qdrant-client`, `sentence-transformers`, `torch`, `chromadb`, or `faiss`. If you find yourself reaching for one, re-read `MASTER` §3.

**Postgres extensions:** `pg_trgm`. Create it in your first Alembic migration.

**Env vars you consume:** `DATABASE_URL`, `MATCH_THRESHOLD_AUTO_INCLUDE`, `MATCH_THRESHOLD_REVIEW`, `PGTRGM_PREFILTER_THRESHOLD`, `COT_CUTOFF_DATE`, `DCCS_STALENESS_YEARS`, `WBS_RECENT_COMPLETION_DAYS`, `DATA_DIR`, `PDFTOTEXT_BIN`.

| # | Functional requirement |
|---|---|
| A1 | Ingestion is idempotent — truncate and reload, safe to re-run |
| A2 | Every source row keeps its original record in a `raw` JSONB column |
| A3 | Header normalisation handles double-spaced DESC column names |
| A4 | `safe_date()` handles WBS `YYYYMMDD` strings, `'00000000'` nulls, COT datetimes, and PDF `DD/MM/YYYY` |
| A5 | Entity matching is two-stage: `pg_trgm` prefilter → `rapidfuzz` rerank |
| A6 | Name normalisation strips SEA legal suffixes but preserves non-Latin aliases |
| A7 | Every `rules_engine` function returns a QRC slide citation with its verdict |
| A8 | Rule retrieval is dict lookup by `source_db` first; Postgres FTS is the open-question fallback |
| A9 | PDF ingestion populates `cases`, `case_parties`, `dccs_search_results`, and `golden_cases` |
| A10 | Unit tests cover every `rules_engine` function, including the WBS canary |

---

## 1. Domain models — `app/models/domain.py` (everyone imports these)

```python
class MatchSource(str, Enum):
    DESC = "DESC"
    WBS = "WBS"
    COT = "COT"
    DCCS_HISTORY = "DCCS_HISTORY"
    ONE_WINDOW = "ONE_WINDOW"      # stub only

class BusinessUnitNature(str, Enum):
    AUDIT = "Audit"
    ASSURANCE = "Assurance"
    NON_ASSURANCE = "Non-Assurance"

class MatchStatus(str, Enum):
    ONGOING = "Ongoing"
    COMPLETED = "Completed"
    PURSUING = "Pursuing"

class EntityMatch(BaseModel):
    source: MatchSource
    matched_name: str
    query_name: str
    similarity: float                 # 0.0 – 1.0
    country: str | None
    designation_type: str | None      # DESC
    gup_name: str | None              # DESC
    partner_name: str | None          # WBS / COT / DCCS
    practice_office: str | None
    business_unit: BusinessUnitNature | None
    status: MatchStatus | None
    entity_role: str | None           # DCCS history: Client, GUP, Intermediate Parent...
    match_date: date | None
    include_in_summary: bool
    exclusion_reason: str | None
    rule_citation: str | None
    raw: dict

class RuleChunk(BaseModel):
    chunk_id: str
    slide_number: int
    title: str
    source_db: str        # DESC | WBS | COT | ONE_WINDOW | DCCS_SEARCH | CROSS_BORDER | GENERAL | FOOTER
    chunk_type: str       # narrative | decision_table
    text: str
    score: float | None = None
```

---

## 2. Postgres schema

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============ SOURCE DATABASES (Sample 3.3 xlsx) ============

CREATE TABLE desc_entities (
    id                SERIAL PRIMARY KEY,
    legal_name        TEXT NOT NULL,
    alias             TEXT,
    entity_status     TEXT,
    designation_type  TEXT,           -- comma-list: 'Audit Team Restricted, Relationship'
    designation_desc  TEXT,
    domicile_country  TEXT,
    gup_name          TEXT,
    entity_type       TEXT,
    city              TEXT,
    legal_country     TEXT,
    dgmfid            TEXT,
    contact_person    TEXT,           -- the DESC LCSP / Responsible Party
    review_due_date   DATE,
    date_first_added  TIMESTAMP,
    raw               JSONB NOT NULL
);
CREATE INDEX ON desc_entities USING gin (legal_name gin_trgm_ops);
CREATE INDEX ON desc_entities USING gin (alias gin_trgm_ops);

CREATE TABLE wbs_engagements (
    id                 SERIAL PRIMARY KEY,
    client_gmdm        TEXT,
    wbs_client         TEXT,
    client_name_full   TEXT NOT NULL,
    client_lcsp_name   TEXT,
    wbs_l2             TEXT,
    wbs_text           TEXT,
    geo                TEXT,
    sales_office_text  TEXT,
    material_text      TEXT,
    market_offering_l1 TEXT,
    market_offering_l4 TEXT,
    em_partner_name    TEXT,
    em_manager_name    TEXT,
    wbs_start_date     DATE,
    wbs_end_date       DATE,
    wbs_complete_date  DATE,
    status             TEXT,
    raw                JSONB NOT NULL
);
CREATE INDEX ON wbs_engagements USING gin (client_name_full gin_trgm_ops);

CREATE TABLE cot_requests (
    id                 SERIAL PRIMARY KEY,
    cot_id             INTEGER,
    service_line       TEXT,
    client_name        TEXT NOT NULL,
    requestor          TEXT,
    manager            TEXT,
    partner            TEXT,
    requesting_country TEXT,
    cob_form_status    TEXT,
    joid               TEXT,
    submission_time    TIMESTAMP,
    raw                JSONB NOT NULL
);
CREATE INDEX ON cot_requests USING gin (client_name gin_trgm_ops);

-- ============ FOURTH DATABASE (from the PDF) ============

CREATE TABLE dccs_search_results (
    id             SERIAL PRIMARY KEY,
    source_case_id UUID,              -- which case export this came from
    for_entity     TEXT,              -- the entity whose search block contained this row
    request_id     TEXT NOT NULL,
    request_type   TEXT,              -- Conflict Check Request | Cross Border Request
    service_type   TEXT,
    entity_name    TEXT NOT NULL,
    side           TEXT,              -- Client | Other
    entity_role    TEXT,              -- Client, Global Ultimate Parent, Client Subsidiary...
    status         TEXT,              -- Approved with Conditions | Opportunity Lost | ...
    request_date   DATE,
    lead_partner   TEXT,
    description    TEXT,
    raw            JSONB
);
CREATE INDEX ON dccs_search_results USING gin (entity_name gin_trgm_ops);
CREATE INDEX ON dccs_search_results (request_id);
CREATE INDEX ON dccs_search_results (request_date);

-- ============ CASES ============

CREATE TABLE cases (
    id                  UUID PRIMARY KEY,
    request_id          TEXT UNIQUE,
    request_type        TEXT,
    originator          TEXT,
    member_firm         TEXT,
    location            TEXT,
    office              TEXT,
    service_offering    TEXT,
    engagement_name     TEXT,
    engagement_details  TEXT,
    is_recurring        BOOLEAN,
    is_inbound_referral BOOLEAN DEFAULT FALSE,
    has_iwrf            BOOLEAN DEFAULT FALSE,
    lead_partner        TEXT,
    lead_manager        TEXT,
    date_submitted      DATE,
    source_filename     TEXT,
    raw_text            TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE case_parties (
    id            SERIAL PRIMARY KEY,
    case_id       UUID REFERENCES cases(id) ON DELETE CASCADE,
    entity_name   TEXT NOT NULL,
    party_side    TEXT,        -- CLIENT_SIDE | OTHER_SIDE
    entity_role   TEXT,        -- Client | Shareholder | Global Ultimate Parent | ...
    entity_type   TEXT,
    abbreviated_names TEXT,
    dgmf_id       TEXT,
    address       TEXT,
    location      TEXT,
    stated_designation TEXT,   -- what the REQUEST claims — diff this against DESC
    is_gup        BOOLEAN
);

-- ============ GROUND TRUTH ============

CREATE TABLE golden_cases (
    id               SERIAL PRIMARY KEY,
    case_id          UUID REFERENCES cases(id) ON DELETE CASCADE,
    request_id       TEXT NOT NULL,
    final_result     TEXT,          -- 'Approved with Conditions'
    conditions       JSONB,         -- ['Relationship client in DESC']
    analyst_comments JSONB,         -- ['Listed in DESC', 'Local WBS: Non-Assurance', ...]
    cross_border     JSONB          -- [{jurisdiction, outcome, comment}]
);

-- ============ RULES (from the pptx) ============

CREATE TABLE rule_chunks (
    id           SERIAL PRIMARY KEY,
    chunk_id     TEXT UNIQUE NOT NULL,
    slide_number INTEGER NOT NULL,
    title        TEXT,
    source_db    TEXT NOT NULL,
    chunk_type   TEXT NOT NULL,     -- narrative | decision_table
    text         TEXT NOT NULL,
    search_vec   TSVECTOR
);
CREATE INDEX ON rule_chunks USING gin (search_vec);
CREATE INDEX ON rule_chunks (source_db);

-- populate search_vec on insert:
--   UPDATE rule_chunks SET search_vec = to_tsvector('english', title || ' ' || text);

-- ============ SCREENING ============

CREATE TABLE screenings (
    id                   UUID PRIMARY KEY,
    case_id              UUID REFERENCES cases(id) ON DELETE CASCADE,
    status               TEXT NOT NULL,    -- PENDING | RUNNING | COMPLETE | FAILED
    final_result         TEXT,
    conditions           JSONB,
    cross_border_actions JSONB,
    quality_check_flags  JSONB,
    unchecked_sources    JSONB,
    draft_response       TEXT,
    error                TEXT,
    created_at           TIMESTAMPTZ DEFAULT now(),
    completed_at         TIMESTAMPTZ
);

CREATE TABLE matches (
    id                 SERIAL PRIMARY KEY,
    screening_id       UUID REFERENCES screenings(id) ON DELETE CASCADE,
    source             TEXT NOT NULL,
    query_name         TEXT NOT NULL,
    matched_name       TEXT NOT NULL,
    similarity         REAL,
    country            TEXT,
    designation_type   TEXT,
    gup_name           TEXT,
    partner_name       TEXT,
    practice_office    TEXT,
    business_unit      TEXT,
    status             TEXT,
    entity_role        TEXT,
    match_date         DATE,
    include_in_summary BOOLEAN DEFAULT TRUE,
    exclusion_reason   TEXT,
    rule_citation      TEXT,
    raw                JSONB
);

-- ============ CHAT ============

CREATE TABLE chat_sessions (
    id         UUID PRIMARY KEY,
    case_id    UUID REFERENCES cases(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE chat_messages (
    id         SERIAL PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,     -- user | assistant | tool
    content    TEXT NOT NULL,
    agent_name TEXT,
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 3. Ingestion — `app/ingestion/`

### 3.1 `xlsx_loader.py`

Three sheets: `DESC`, `WBS`, `COT`.
- `pandas.read_excel(path, sheet_name=None, dtype=str)`.
- **Normalise headers before mapping**: strip, collapse internal whitespace. DESC has genuine double-space column names like `'Individual  Address City'`.
- Map only schema columns; put the entire row dict in `raw`.
- Empty strings → `NULL`.
- Dates: WBS uses `YYYYMMDD` strings with `'00000000'` for null; COT has real datetimes.
- Data quality: DESC contains real typos (`'Toyko'`). Do not correct them — the agent must reason over what's actually stored.

### 3.2 `pdf_loader.py` — the important one

**Approach: shell out to `pdftotext -layout`, then split by section headers with regex.** Do not try `pdfplumber.extract_tables()` as the primary path — the pages are A0-sized with wide fixed-column layouts, and `-layout` text preserves the columns more reliably.

```python
subprocess.run([settings.PDFTOTEXT_BIN, "-layout", pdf_path, txt_path], check=True)
```

**Section anchors** (these appear as standalone lines):
```
Request Summary Quick View
Engagement Details
Engagement Team
Entities - Client Side Entity - <ENTITY NAME>     ← repeats, one per entity
Target Entity Details
DCCS Search Results
Manual Search Results
Entities - Other Side Entities
Cross Border Requests
Requestor Checklist
Review And Determination
Message Activity Log
Request Activity Log
```

**Parse in four passes:**

**Pass 1 — case header.** From `Request Summary Quick View` and `Engagement Details`, key-value lines are `label` + run of spaces + `value`. Split on 3+ spaces:
```python
m = re.match(r"^(.{3,}?)\s{3,}(.+)$", line)
```
Extract: `Request Id`, `Request Type`, `Submitted By` → originator, `Date Submitted` (DD/MM/YYYY), `Member Firm`, `Location`, `Office`, `Service Offering`, `Engagement/Project Description`, `Is this a Recurring Engagement?`, `Is this Engagement an Inbound Work Referral from another member firm?`. Also grab `Lead Engagement Partner` and `Lead Engagement Manager` from `Engagement Team`.

**Pass 2 — entities.** Split the document on `^Entities - Client Side Entity - (.+)$`. Each block's `Target Entity Details` section uses the same key-value pattern:
`Entity Type`, `Entity Role`, `Full Legal Entity Name`, `Abbreviated Name(s)`, `DGMF ID`, `Address` (multi-line — join continuation lines), `Location`, `What is the Entity Designation?` → `stated_designation`, `Is this Entity the Global Ultimate Parent or Controlling Party?` → `is_gup`.

For case 12246557 you should get exactly three parties: Client, Shareholder, Global Ultimate Parent.

**Pass 3 — DCCS search result rows.** Within each entity block, everything between `DCCS Search Results` and `Manual Search Results`. Rows start with a 6–8 digit request ID after leading whitespace:
```python
ROW = re.compile(r"^\s+(\d{6,8})\s{2,}(.+)$")
```
Split the remainder on runs of 2+ spaces into fields, then map positionally to:
`request_type, service_type, entity_name, side, entity_role, status, request_date, lead_partner, description`.

Guard rails, because column alignment drifts between pages:
- If the field count is short, pad with `None` rather than raising.
- `request_date` must match `DD/MM/YYYY`; if the field in that position doesn't, search the row for a date pattern and realign.
- `description` is truncated in the source (it runs off the page). Store what's there; never fabricate the remainder.
- Deduplicate on `(request_id, entity_name, entity_role, for_entity)` — the same row appears in multiple entity blocks.

Expect low thousands of rows after dedupe. Log the count; if it's under 100, your regex is wrong.

**Pass 4 — ground truth.** From `Review And Determination`: `Final Result`, `Conditions`, and the `Comments` block (multi-line — collect until the next section header). From `Cross Border Requests`: jurisdiction, outcome line (`Request Not Required` / `Request Required`), and the `Comments:` value. Write to `golden_cases`.

**Write the parser as a pure function** `parse_dccs_export(text) -> ParsedCase` with the file I/O outside it, so it's unit-testable against a saved text fixture. Save `pdftotext` output once into `tests/fixtures/case_12246557.txt` and test against that — do not re-run pdftotext on an 82 MB file in every test.

### 3.3 `qrc_loader.py` — the rulebook into `rule_chunks`

**Chunking: one chunk per rule block, semantic. Never fixed-size.**

| Slide | Chunks | `source_db` | `chunk_type` |
|---|---|---|---|
| 1 | skip (title) | — | — |
| 2 | 1 — assigning DCCS request | GENERAL | narrative |
| 3 | 2 — (a) engagement-details QC, (b) referral work | GENERAL | narrative |
| 4 | 2 — (a) relevant-parties QC, (b) DESC inconsistency handling | DESC | narrative |
| 5 | 1 — DESC search + designation types | DESC | narrative |
| 6 | 2 — (a) business-unit classification, (b) status classification | WBS | narrative |
| 7 | 1 — One Window intro + Strategic Client | ONE_WINDOW | narrative |
| 8 | 3 — Directorship / Sanction / Open Opportunities | ONE_WINDOW | narrative |
| 9 | 1 — COT search + 15 Jul 2025 cutoff | COT | narrative |
| 10 | 1 — DCCS search result relevance tests | DCCS_SEARCH | narrative |
| 11 | 1 — **cross-border matrix, kept whole as markdown** | CROSS_BORDER | decision_table |
| 12 | 1 — sending a cross-border request | CROSS_BORDER | narrative |
| 13 | 1 — collate relationships, final result options | GENERAL | narrative |
| 14 | 1 — **DPM 1420 footer + personal conflicts, verbatim** | FOOTER | decision_table |

Rules: never split a table. Prepend each chunk with `[Slide {n} — {title}]`. Populate `search_vec` after insert.

---

## 4. Repositories — `app/repositories/`

### 4.1 `entity_search.py`

```python
def search_desc(name, threshold=0.80, limit=10) -> list[EntityMatch]
def search_wbs(name, threshold=0.80, limit=20) -> list[EntityMatch]
def search_cot(name, threshold=0.80, limit=20) -> list[EntityMatch]
def search_dccs_history(name, threshold=0.80, limit=50) -> list[EntityMatch]
def search_all(name) -> dict[MatchSource, list[EntityMatch]]
```

**Stage 1 — Postgres prefilter** (deliberately loose):
```sql
SET pg_trgm.similarity_threshold = 0.3;
SELECT * FROM desc_entities
WHERE legal_name % :q OR alias % :q
   OR legal_name ILIKE '%' || :q || '%'
LIMIT 200;
```

**Stage 2 — `rapidfuzz` rerank:**
- Normalise both sides: uppercase; strip legal suffixes (`CO., LTD`, `LIMITED`, `LTD`, `CORPORATION`, `CORP`, `PTE LTD`, `SDN BHD`, `TBK`, `PT`, `INC`, `LLC`, `K.K.`, `KK`, `L.P.`); collapse punctuation and whitespace.
- Score with `fuzz.token_set_ratio` — plain ratio fails on `"KDDI (THAILAND) COMPANY LIMITED"` vs `"KDDI (Thailand) Limited"`.
- Score against `legal_name` and `alias`, take the max. **Do not strip non-ASCII** — aliases include `KDDI株式会社`.
- `similarity = score / 100`.

**Must pass:** the request's `KDDI (Thailand) Limited` matches DESC's `KDDI (THAILAND) COMPANY LIMITED` above `MATCH_THRESHOLD_REVIEW`. This bridge is required for the demo case to work.

### 4.2 `rule_repository.py`
```python
def get_rules_by_source(source_db: str) -> list[RuleChunk]     # PRIMARY — dict/SQL lookup
def search_rules(query: str, source_db=None, top_k=3) -> list[RuleChunk]   # FTS fallback
def get_cross_border_table() -> RuleChunk
def get_footer_text() -> str                                    # slide 14 verbatim
```

FTS query:
```sql
SELECT *, ts_rank(search_vec, plainto_tsquery('english', :q)) AS score
FROM rule_chunks
WHERE search_vec @@ plainto_tsquery('english', :q)
  AND (:source_db IS NULL OR source_db = :source_db)
ORDER BY score DESC LIMIT :k;
```

With only ~20 chunks, cache them all in memory at startup. `get_rules_by_source` should never hit the DB twice.

### 4.3 `case_repository.py`, `screening_repository.py`, `golden_repository.py`, `chat_repository.py`
Standard CRUD. Screening repo needs `create_pending()`, `update_status()`, `save_matches()`, `finalize()`. Case repo needs `create_case_manual()` for the UI form path.

---

## 5. `app/rules/rules_engine.py` — deterministic rules

**These are lookups, not judgment calls. Hardcode them.** This is the biggest hallucination risk in the app and costs under an hour to eliminate.

```python
def classify_wbs_business_unit(l1, l4, wbs_text) -> tuple[BusinessUnitNature, str]:
    """QRC slide 6. Returns (nature, citation).
    T&L / SR&T / T&T                                    -> NON_ASSURANCE
    A&A + l4 == 'A&A: AUD-Large & Complex' and wbs_text
        contains 'Statutory' or 'Financial Statement'   -> AUDIT
    A&A + same l4 and wbs_text contains
        'Assurance' | 'Attestation' | 'ISAE'            -> ASSURANCE
    any other A&A                                        -> NON_ASSURANCE
    Case-insensitive substring matching."""

def classify_wbs_status(status, complete_date, desc_designation) -> tuple[MatchStatus, bool, str|None, str]:
    """QRC slide 6. Returns (status, include, exclusion_reason, citation).
    'Released'              -> (ONGOING, True, None)
    'Technically Completed' -> COMPLETED; exclude UNLESS it is an Audit engagement
        completed within WBS_RECENT_COMPLETION_DAYS AND the entity is still
        Restricted in DESC."""

def is_cot_match_acknowledged(submission_time) -> tuple[bool, str|None, str]:
    """QRC slide 9. Before COT_CUTOFF_DATE -> excluded.
    Acknowledged COT matches are always ONGOING and NON_ASSURANCE (Tax BU)."""

def parse_desc_designations(designation_type: str) -> list[str]:
    """Comma-split. Recognised: Relationship, DTT Restricted, SEC Restricted,
    EUPIE Restricted, Reverse Restricted, Watchlist, Loan Rule,
    Business Relationship Restricted, Audit Team Restricted.
    A non-designated match is excluded from the table summary but must produce
    a caveat in 'Conditions to be satisfied' (slide 5 note)."""

def is_dccs_match_relevant(request_date, status, already_in_other_source) -> tuple[bool, str|None, str]:
    """QRC slide 10.
    older than DCCS_STALENESS_YEARS               -> exclude
    status in ('Engagement Complete','Opportunity Lost') -> exclude
    already captured in WBS/One Window            -> exclude (dedupe)
    otherwise                                      -> include as PURSUING"""

def evaluate_cross_border(client_in_desc, gup_in_desc, client_is_gup) -> CrossBorderDecision:
    """QRC slide 11 matrix, transcribed exactly. Returns actions for requesting
    and receiving MF, for both the Foreign Client and Foreign GUP columns.
    Footnote: a Logging Request is sent when the client entity is listed in DESC
    as Relationship or Restricted.
    Sanity check against the sample case: GUP KDDI CORPORATION is in DESC, so the
    Japan cross-border resolves to 'No additional steps required' — which is
    exactly what the human analyst recorded ('Request Not Required')."""

def compare_stated_vs_desc_designation(stated, desc_designation) -> QCFlag | None:
    """QRC slide 4. DESC is authoritative. If they differ, return a WARN flag
    naming the escalation path: contact the requestor; if the requestor confirms
    the submitted value, contact SEAIndependence@deloitte.com copying the assigned
    Senior Analysts from the Conflicts and DESC teams.
    On the sample case this fires: request says 'Restricted', DESC says
    'Audit Team Restricted, Relationship'."""
```

Every function returns its slide citation. Unit-test all of them.

---

## 6. Deliverables checklist

- [ ] `docker compose up` brings up Postgres; `alembic upgrade head` applies the schema
- [ ] `python scripts/run_ingestion.py` loads DESC, WBS, COT, DCCS history, rule chunks, case 12246557, and its golden answer — idempotently
- [ ] `parse_dccs_export()` is a pure function, tested against `tests/fixtures/case_12246557.txt`
- [ ] Exactly 3 `case_parties` rows for case 12246557, with roles Client / Shareholder / Global Ultimate Parent
- [ ] `dccs_search_results` count logged and in the thousands
- [ ] `search_all("KDDI Corporation")` returns hits from all four sources
- [ ] `KDDI (Thailand) Limited` → `KDDI (THAILAND) COMPANY LIMITED` above the review threshold
- [ ] `rules_engine` unit tests green, including the WBS canary
- [ ] `get_rules_by_source("WBS")` returns the two slide-6 chunks
- [ ] `pip freeze | grep -Ei "torch|qdrant|sentence|chroma|faiss"` returns nothing
- [ ] **Publish every function signature to Dev B by end of Day 1 morning.** Ship stubs returning fixtures first, fill in after — Dev B is blocked on your signatures, not your implementations.
