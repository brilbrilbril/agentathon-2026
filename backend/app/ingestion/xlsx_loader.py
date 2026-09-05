"""Loads DESC / WBS / COT sheets from Sample_3_3 xlsx into Postgres.

Data quality note: DESC contains real typos (e.g. 'Toyko'). We do not correct
them — the agent must reason over what is actually stored (A3, MASTER §2.2).
"""

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.utils import (
    none_if_blank,
    normalise_header,
    safe_date,
    safe_datetime,
)

log = logging.getLogger(__name__)

DESC_COLUMN_MAP = {
    "Legal Name": "legal_name",
    "Alias": "alias",
    "Entity Status": "entity_status",
    "Designation Type": "designation_type",
    "Designation Descriptions": "designation_desc",
    "Domicile/ Country": "domicile_country",
    "GUP Name": "gup_name",
    "Entity Type": "entity_type",
    "City": "city",
    "Legal Country": "legal_country",
    "DGMFID": "dgmfid",
    "Contact Person": "contact_person",
    "Review Due Date": "review_due_date",
    "Date First Added": "date_first_added",
}

WBS_COLUMN_MAP = {
    "CLIENT GMDM": "client_gmdm",
    "WBS CLIENT": "wbs_client",
    "CLIENT NAME FULL": "client_name_full",
    "CLIENT LCSP TEXT FNLN": "client_lcsp_name",
    "WBS L2": "wbs_l2",
    "WBS TEXT": "wbs_text",
    "GEO": "geo",
    "SALES OFFICE TEXT": "sales_office_text",
    "MATERIAL TEXT": "material_text",
    "MARKET OFFERING L1 TEXT": "market_offering_l1",
    "MARKET OFFERING L4 TEXT": "market_offering_l4",
    "EM PARTNER NAME": "em_partner_name",
    "EM MANAGER NAME": "em_manager_name",
    "WBS START DATE": "wbs_start_date",
    "WBS END DATE": "wbs_end_date",
    "WBS COMPLETE DATE": "wbs_complete_date",
    "STATUS": "status",
}

COT_COLUMN_MAP = {
    "Id": "cot_id",
    "Service Line": "service_line",
    "Client Name": "client_name",
    "Requestor": "requestor",
    "Manager": "manager",
    "Partner": "partner",
    "Requesting Country": "requesting_country",
    "COB Form Status": "cob_form_status",
    "JOID": "joid",
    "Submission Time": "submission_time",
}

_DATE_COLUMNS = {"review_due_date", "date_first_added", "wbs_start_date", "wbs_end_date", "wbs_complete_date"}
_DATETIME_COLUMNS = {"submission_time"}


def _load_sheet(path: str, sheet_name: str, column_map: dict[str, str], required_col: str | None = None) -> list[dict]:
    df = pd.read_excel(path, sheet_name=sheet_name, dtype=str)
    df.columns = [normalise_header(c) for c in df.columns]

    rows = []
    for _, series in df.iterrows():
        raw = {k: none_if_blank(v) for k, v in series.to_dict().items()}
        row = {"raw": raw}
        for src_col, dest_col in column_map.items():
            value = none_if_blank(raw.get(src_col))
            if dest_col in _DATE_COLUMNS:
                value = safe_date(value)
            elif dest_col in _DATETIME_COLUMNS:
                value = safe_datetime(value)
            row[dest_col] = value
        # Power BI / Excel exports append trailing footer rows ("Applied
        # filters: ...") that have no real data — skip anything missing the
        # sheet's required NOT NULL column.
        if required_col and not row.get(required_col):
            continue
        rows.append(row)
    return rows


def load_desc(path: str) -> list[dict]:
    rows = _load_sheet(path, "DESC", DESC_COLUMN_MAP, required_col="legal_name")
    log.info("Parsed %d DESC rows", len(rows))
    return rows


def load_wbs(path: str) -> list[dict]:
    rows = _load_sheet(path, "WBS", WBS_COLUMN_MAP, required_col="client_name_full")
    log.info("Parsed %d WBS rows", len(rows))
    return rows


def load_cot(path: str) -> list[dict]:
    rows = _load_sheet(path, "COT", COT_COLUMN_MAP, required_col="client_name")
    for row in rows:
        if row.get("cot_id") is not None:
            try:
                row["cot_id"] = int(float(row["cot_id"]))
            except (ValueError, TypeError):
                row["cot_id"] = None
    log.info("Parsed %d COT rows", len(rows))
    return rows


def ingest_xlsx(session: Session, path: str) -> dict[str, int]:
    """Idempotent: truncate and reload (A1)."""
    session.execute(text("TRUNCATE TABLE desc_entities RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE wbs_engagements RESTART IDENTITY CASCADE"))
    session.execute(text("TRUNCATE TABLE cot_requests RESTART IDENTITY CASCADE"))

    import json

    desc_rows = load_desc(path)
    for row in desc_rows:
        row["raw"] = json.dumps(row["raw"], default=str)
    if desc_rows:
        session.execute(
            text(
                """
                INSERT INTO desc_entities
                    (legal_name, alias, entity_status, designation_type, designation_desc,
                     domicile_country, gup_name, entity_type, city, legal_country, dgmfid,
                     contact_person, review_due_date, date_first_added, raw)
                VALUES
                    (:legal_name, :alias, :entity_status, :designation_type, :designation_desc,
                     :domicile_country, :gup_name, :entity_type, :city, :legal_country, :dgmfid,
                     :contact_person, :review_due_date, :date_first_added, CAST(:raw AS JSONB))
                """
            ),
            desc_rows,
        )

    wbs_rows = load_wbs(path)
    for row in wbs_rows:
        row["raw"] = json.dumps(row["raw"], default=str)
    if wbs_rows:
        session.execute(
            text(
                """
                INSERT INTO wbs_engagements
                    (client_gmdm, wbs_client, client_name_full, client_lcsp_name, wbs_l2,
                     wbs_text, geo, sales_office_text, material_text, market_offering_l1,
                     market_offering_l4, em_partner_name, em_manager_name, wbs_start_date,
                     wbs_end_date, wbs_complete_date, status, raw)
                VALUES
                    (:client_gmdm, :wbs_client, :client_name_full, :client_lcsp_name, :wbs_l2,
                     :wbs_text, :geo, :sales_office_text, :material_text, :market_offering_l1,
                     :market_offering_l4, :em_partner_name, :em_manager_name, :wbs_start_date,
                     :wbs_end_date, :wbs_complete_date, :status, CAST(:raw AS JSONB))
                """
            ),
            wbs_rows,
        )

    cot_rows = load_cot(path)
    for row in cot_rows:
        row["raw"] = json.dumps(row["raw"], default=str)
    if cot_rows:
        session.execute(
            text(
                """
                INSERT INTO cot_requests
                    (cot_id, service_line, client_name, requestor, manager, partner,
                     requesting_country, cob_form_status, joid, submission_time, raw)
                VALUES
                    (:cot_id, :service_line, :client_name, :requestor, :manager, :partner,
                     :requesting_country, :cob_form_status, :joid, :submission_time, CAST(:raw AS JSONB))
                """
            ),
            cot_rows,
        )

    session.commit()
    return {"desc": len(desc_rows), "wbs": len(wbs_rows), "cot": len(cot_rows)}
