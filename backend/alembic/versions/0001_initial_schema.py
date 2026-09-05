"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-05
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============ SOURCE DATABASES (Sample 3.3 xlsx) ============

CREATE TABLE desc_entities (
    id                SERIAL PRIMARY KEY,
    legal_name        TEXT NOT NULL,
    alias             TEXT,
    entity_status     TEXT,
    designation_type  TEXT,
    designation_desc  TEXT,
    domicile_country  TEXT,
    gup_name          TEXT,
    entity_type       TEXT,
    city              TEXT,
    legal_country     TEXT,
    dgmfid            TEXT,
    contact_person    TEXT,
    review_due_date   DATE,
    date_first_added  TIMESTAMP,
    raw               JSONB NOT NULL
);
CREATE INDEX ix_desc_legal_name_trgm ON desc_entities USING gin (legal_name gin_trgm_ops);
CREATE INDEX ix_desc_alias_trgm ON desc_entities USING gin (alias gin_trgm_ops);

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
CREATE INDEX ix_wbs_client_name_trgm ON wbs_engagements USING gin (client_name_full gin_trgm_ops);

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
CREATE INDEX ix_cot_client_name_trgm ON cot_requests USING gin (client_name gin_trgm_ops);

-- ============ FOURTH DATABASE (from the PDF) ============

CREATE TABLE dccs_search_results (
    id             SERIAL PRIMARY KEY,
    source_case_id UUID,
    for_entity     TEXT,
    request_id     TEXT NOT NULL,
    request_type   TEXT,
    service_type   TEXT,
    entity_name    TEXT NOT NULL,
    side           TEXT,
    entity_role    TEXT,
    status         TEXT,
    request_date   DATE,
    lead_partner   TEXT,
    description    TEXT,
    raw            JSONB
);
CREATE INDEX ix_dccs_entity_name_trgm ON dccs_search_results USING gin (entity_name gin_trgm_ops);
CREATE INDEX ix_dccs_request_id ON dccs_search_results (request_id);
CREATE INDEX ix_dccs_request_date ON dccs_search_results (request_date);

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
    party_side    TEXT,
    entity_role   TEXT,
    entity_type   TEXT,
    abbreviated_names TEXT,
    dgmf_id       TEXT,
    address       TEXT,
    location      TEXT,
    stated_designation TEXT,
    is_gup        BOOLEAN
);

-- ============ GROUND TRUTH ============

CREATE TABLE golden_cases (
    id               SERIAL PRIMARY KEY,
    case_id          UUID REFERENCES cases(id) ON DELETE CASCADE,
    request_id       TEXT NOT NULL,
    final_result     TEXT,
    conditions       JSONB,
    analyst_comments JSONB,
    cross_border     JSONB
);

-- ============ RULES (from the pptx) ============

CREATE TABLE rule_chunks (
    id           SERIAL PRIMARY KEY,
    chunk_id     TEXT UNIQUE NOT NULL,
    slide_number INTEGER NOT NULL,
    title        TEXT,
    source_db    TEXT NOT NULL,
    chunk_type   TEXT NOT NULL,
    text         TEXT NOT NULL,
    search_vec   TSVECTOR
);
CREATE INDEX ix_rule_chunks_search_vec ON rule_chunks USING gin (search_vec);
CREATE INDEX ix_rule_chunks_source_db ON rule_chunks (source_db);

-- ============ SCREENING ============

CREATE TABLE screenings (
    id                   UUID PRIMARY KEY,
    case_id              UUID REFERENCES cases(id) ON DELETE CASCADE,
    status               TEXT NOT NULL,
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
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    agent_name TEXT,
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("""
    DROP TABLE IF EXISTS chat_messages, chat_sessions, matches, screenings,
        rule_chunks, golden_cases, case_parties, cases, dccs_search_results,
        cot_requests, wbs_engagements, desc_entities CASCADE;
    """)
