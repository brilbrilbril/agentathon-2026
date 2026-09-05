"""Ingests the DCCS 'Request Management' PDF export (Sample_3_1).

Approach: shell out to `pdftotext -layout`, then parse the flattened text.

Layout quirk (reverse-engineered from the actual export, verified against the
analyst's known ground truth in MASTER_overview.md §2.3 and §9): the source
PDF renders each form field's *value* visually one slot above its own
*caption*. Once flattened by `pdftotext -layout`, this means the ordered list
of right-hand-column values in a bounded section reconstructs the true field
sequence positionally — it does not line up with the caption printed on the
same text line. We extract the ordered "value" stream per section and index
into it positionally, which has been validated against the known values for
case 12246557 (request_id, location=Malaysia, service_offering, engagement
name, cross-border comment, final_result, conditions, comments all match).

Write the parser as a pure function `parse_dccs_export(text) -> dict` with the
file I/O outside it, so it's unit-testable against a saved text fixture.
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.ingestion.utils import safe_date

log = logging.getLogger(__name__)

_SIDE_VALUES = {"Client", "Other"}

_KNOWN_COUNTRIES = [
    "Thailand", "Singapore", "Japan", "Malaysia", "Vietnam", "Indonesia",
    "Philippines", "China", "Korea", "Taiwan", "India", "Hong Kong",
    "United States", "United Kingdom", "Australia", "Cambodia", "Laos",
    "Myanmar", "Brunei",
]

_ENTITY_HEADER_RE = re.compile(r"^Entities - Client Side Entity - (.+?)(?:\s{2,}.*)?$")
_ROW_START_RE = re.compile(r"^\s+(\d{6,8})\s{2,}(.+)$")
_DATE_FIELD_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")


@dataclass
class ParsedCase:
    request_id: str | None = None
    request_type: str | None = None
    originator: str | None = None
    date_submitted: object = None
    member_firm: str | None = None
    location: str | None = None
    office: str | None = None
    service_offering: str | None = None
    engagement_name: str | None = None
    engagement_details: str | None = None
    is_recurring: bool = False
    is_inbound_referral: bool = False
    has_iwrf: bool = False
    lead_partner: str | None = None
    lead_manager: str | None = None
    parties: list[dict] = field(default_factory=list)
    dccs_rows: list[dict] = field(default_factory=list)
    golden: dict = field(default_factory=dict)


def run_pdftotext(pdf_path: str, txt_path: str) -> None:
    subprocess.run([settings.PDFTOTEXT_BIN, "-layout", "-enc", "UTF-8", pdf_path, txt_path], check=True)


def _split_kv_line(line: str) -> tuple[str, str]:
    """Returns (left, right) for one physical text line. Either side may be ''."""
    stripped_line = line.rstrip("\n")
    m = re.match(r"^(.*?)\s{2,}(.+)$", stripped_line)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    leading = len(stripped_line) - len(stripped_line.lstrip(" "))
    if leading > 40 and stripped_line.strip():
        return "", stripped_line.strip()
    return stripped_line.strip(), ""


def _extract_values(lines: list[str]) -> list[str]:
    values = []
    for line in lines:
        if not line.strip():
            continue
        _, right = _split_kv_line(line)
        if right:
            values.append(right)
    return values


def _find_section(lines: list[str], start_marker: str, end_markers: list[str]) -> list[str]:
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith(start_marker):
            start_idx = i
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if any(line_starts_with(lines[j], m) for m in end_markers):
            end_idx = j
            break
    return lines[start_idx:end_idx]


def line_starts_with(line: str, marker: str) -> bool:
    return line.strip().startswith(marker)


def parse_case_header(lines: list[str]) -> dict:
    summary_lines = _find_section(lines, "Request Summary Quick View", ["Engagement Details"])
    summary_values = _extract_values(summary_lines)

    request_id = summary_values[0] if len(summary_values) > 0 else None
    request_type = summary_values[1] if len(summary_values) > 1 else None
    originator = summary_values[2] if len(summary_values) > 2 else None
    date_submitted_raw = summary_values[3] if len(summary_values) > 3 else None

    detail_lines = _find_section(lines, "Engagement Details", ["Entities - Client Side Entity"])
    detail_values = _extract_values(detail_lines)

    def dv(i):
        return detail_values[i] if len(detail_values) > i else None

    member_firm = dv(3)
    location = dv(4)
    office = dv(5)
    service_offering = dv(6)
    engagement_name = dv(9)
    engagement_details = dv(10)

    team_lines = _find_section(lines, "Engagement Team", ["Entities - Client Side Entity"])
    team_values = _extract_values(team_lines)
    lead_partner = team_values[2] if len(team_values) > 2 else None
    lead_manager = team_values[5] if len(team_values) > 5 else None

    return {
        "request_id": request_id,
        "request_type": request_type,
        "originator": originator,
        "date_submitted": safe_date(date_submitted_raw),
        "member_firm": member_firm,
        "location": location,
        "office": office,
        "service_offering": service_offering,
        "engagement_name": engagement_name,
        "engagement_details": engagement_details,
        "is_recurring": False,
        "is_inbound_referral": False,
        "has_iwrf": False,
        "lead_partner": lead_partner,
        "lead_manager": lead_manager,
    }


def _guess_location(block_text: str) -> str | None:
    for country in _KNOWN_COUNTRIES:
        if re.search(rf"\b{re.escape(country)}\b", block_text):
            return country
    return None


def parse_entities(lines: list[str]) -> list[dict]:
    header_idx = [
        i for i, line in enumerate(lines)
        if _ENTITY_HEADER_RE.match(line.strip()) or line.strip().startswith("Entities - Client Side Entity - ")
    ]
    parties = []
    for pos, idx in enumerate(header_idx):
        end_idx = header_idx[pos + 1] if pos + 1 < len(header_idx) else len(lines)
        # bound the entity's field block at its own DCCS Search Results marker
        field_end = end_idx
        for j in range(idx + 1, end_idx):
            if lines[j].strip().startswith("DCCS Search Results"):
                field_end = j
                break
        # The page-layout renderer sometimes leaks the first row of the
        # following DCCS Search Results table in ahead of its own marker
        # line. The GUP question is always the true last field of this
        # section, so never read values past it (+1 line for a possibly
        # shifted answer).
        gup_label = "Is this Entity the Global Ultimate Parent or Controlling Party?"
        for j in range(idx, field_end):
            if lines[j].strip().startswith(gup_label):
                field_end = min(field_end, j + 2)
                break
        block = lines[idx:field_end]
        header_match = _ENTITY_HEADER_RE.match(lines[idx].strip())
        entity_name = header_match.group(1).strip() if header_match else lines[idx].strip()

        values = _extract_values(block)
        # The full, uncontaminated Target Entity Details form yields at most
        # 14 values (verified against the clean 'Shareholder' entity block).
        # A page/column-layout leak can append 1-2 extra values from the
        # following DCCS Search Results table header — drop anything past
        # that known-clean length rather than misreading it as designation.
        if len(values) > 14:
            values = values[:14]
        entity_type = values[0] if len(values) > 0 else None
        entity_role = values[1] if len(values) > 1 else None
        full_legal_name = values[2] if len(values) > 2 else entity_name
        stated_designation = values[-2] if len(values) >= 2 else None

        block_text = "\n".join(block)
        location = _guess_location(block_text)

        parties.append({
            "entity_name": entity_name,
            "full_legal_name": full_legal_name,
            "party_side": "CLIENT_SIDE",
            "entity_role": entity_role,
            "entity_type": entity_type,
            "abbreviated_names": None,
            "dgmf_id": None,
            "address": None,
            "location": location,
            "stated_designation": stated_designation,
            "is_gup": entity_role == "Global Ultimate Parent",
        })
    return parties


_STATUS_PREFIXES = (
    "Approved", "Opportunity Lost", "Engagement Complete", "No Conflicts",
    "Draft", "Withdrawn", "Rejected", "Pending", "In Progress",
)


def _find_status_idx(fields: list[str]) -> int | None:
    for i in range(len(fields) - 1, -1, -1):
        if fields[i].startswith(_STATUS_PREFIXES):
            return i
    return None


def parse_dccs_rows_for_entity(lines: list[str], for_entity: str, source_case_id: str) -> list[dict]:
    """Most rows carry their own request ID, but many DCCS Search Result pages
    print additional matches under the same request as continuation lines
    with no leading ID at all (verified against the actual export — see the
    'Asia Pacific' block, which is ~19,700 lines of mostly ID-less
    continuation rows). We anchor on the Status column instead of the Date
    column, since Status is always present but Date/Partner/Description are
    frequently absent on continuation lines, and carry the last-seen request
    ID forward onto ID-less rows."""
    section = _find_section(lines, "DCCS Search Results", ["Manual Search Results"])
    rows = []
    current_request_id = None

    for raw_line in section:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if "Entity Name" in line and "Entity Role" in line:
            continue  # repeated column header, printed on every page

        m = _ROW_START_RE.match(line)
        if m:
            current_request_id = m.group(1)
            rest = m.group(2)
        else:
            rest = line

        if current_request_id is None:
            continue

        fields = [f.strip() for f in re.split(r"\s{2,}", rest) if f.strip() != ""]
        status_idx = _find_status_idx(fields)
        if status_idx is None:
            continue

        status = fields[status_idx]
        request_date = None
        lead_partner = None
        description = None
        if len(fields) > status_idx + 1 and _DATE_FIELD_RE.match(fields[status_idx + 1]):
            request_date = safe_date(fields[status_idx + 1])
            lead_partner = fields[status_idx + 2] if len(fields) > status_idx + 2 else None
            description = " ".join(fields[status_idx + 3:]) if len(fields) > status_idx + 3 else None

        pre = fields[0:status_idx]
        side_idx = None
        for i, f in enumerate(pre):
            if f in _SIDE_VALUES:
                side_idx = i
                break

        side = entity_role = request_type = service_type = entity_name = None
        if side_idx is not None:
            side = pre[side_idx]
            entity_role = pre[side_idx + 1] if len(pre) > side_idx + 1 else None
            head = pre[0:side_idx]
        else:
            entity_role = pre[-1] if pre else None
            head = pre[0:-1] if pre else []

        if len(head) >= 3:
            request_type, service_type, entity_name = head[-3], head[-2], head[-1]
        elif len(head) == 2:
            request_type, service_type = head[0], head[1]
        elif len(head) == 1:
            request_type = head[0]

        rows.append({
            "source_case_id": source_case_id,
            "for_entity": for_entity,
            "request_id": current_request_id,
            "request_type": request_type,
            "service_type": service_type,
            "entity_name": entity_name,
            "side": side,
            "entity_role": entity_role,
            "status": status,
            "request_date": request_date,
            "lead_partner": lead_partner,
            "description": description,
            "raw": {"line": line.strip()},
        })
    return rows


def parse_golden(lines: list[str]) -> dict:
    det_lines = _find_section(lines, "Review And Determination", ["Message Activity Log"])
    values = _extract_values(det_lines)

    final_result = values[0] if len(values) > 0 else None
    conditions = [values[1]] if len(values) > 1 else []
    analyst_comments = values[3:] if len(values) > 3 else []

    cb_block = _find_section(lines, "Entities - Other Side Entities", ["Requestor Checklist"])
    cb_values = _extract_values(cb_block)
    comment = cb_values[0] if cb_values else None

    jurisdiction = None
    cb_start = None
    for i, line in enumerate(cb_block):
        if line.strip().startswith("Cross Border Requests"):
            cb_start = i
            break
    outcome = None
    if cb_start is not None:
        for line in cb_block[cb_start + 1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if jurisdiction is None and stripped in _KNOWN_COUNTRIES:
                jurisdiction = stripped
                continue
            if "Request Not Required" in stripped:
                outcome = "Request Not Required"
                break
            if "Request Required" in stripped:
                outcome = "Request Required"
                break

    cross_border = []
    if jurisdiction:
        cross_border.append({
            "jurisdiction": jurisdiction,
            "outcome": outcome,
            "comment": comment,
        })

    return {
        "final_result": final_result,
        "conditions": conditions,
        "analyst_comments": analyst_comments,
        "cross_border": cross_border,
    }


def parse_dccs_export(text: str) -> ParsedCase:
    """Pure function: text in, structured case out. Unit-test this against
    tests/fixtures/case_12246557.txt — never re-run pdftotext in tests."""
    lines = text.split("\n")

    header = parse_case_header(lines)
    parties = parse_entities(lines)
    golden = parse_golden(lines)

    source_case_id = str(uuid.uuid4())
    dccs_rows: list[dict] = []
    header_idx = [i for i, line in enumerate(lines) if line.strip().startswith("Entities - Client Side Entity - ")]
    for pos, idx in enumerate(header_idx):
        end_idx = header_idx[pos + 1] if pos + 1 < len(header_idx) else len(lines)
        header_match = _ENTITY_HEADER_RE.match(lines[idx].strip())
        entity_name = header_match.group(1).strip() if header_match else lines[idx].strip()
        block = lines[idx:end_idx]
        dccs_rows.extend(parse_dccs_rows_for_entity(block, entity_name, source_case_id))

    # dedupe on (request_id, entity_name, entity_role, for_entity) — same row
    # appears in multiple entity blocks (A9)
    seen = set()
    deduped = []
    for row in dccs_rows:
        key = (row["request_id"], row["entity_name"], row["entity_role"], row["for_entity"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    parsed = ParsedCase(
        request_id=header["request_id"],
        request_type=header["request_type"],
        originator=header["originator"],
        date_submitted=header["date_submitted"],
        member_firm=header["member_firm"],
        location=header["location"],
        office=header["office"],
        service_offering=header["service_offering"],
        engagement_name=header["engagement_name"],
        engagement_details=header["engagement_details"],
        is_recurring=header["is_recurring"],
        is_inbound_referral=header["is_inbound_referral"],
        has_iwrf=header["has_iwrf"],
        lead_partner=header["lead_partner"],
        lead_manager=header["lead_manager"],
        parties=parties,
        dccs_rows=deduped,
        golden=golden,
    )
    parsed._source_case_id = source_case_id  # stashed for ingest_pdf
    return parsed


def ingest_pdf(session, pdf_path: str, data_dir: str) -> dict[str, int]:
    import json
    import os

    from sqlalchemy import text as sql

    txt_path = os.path.join(data_dir, "case_dccs_export.txt")
    run_pdftotext(pdf_path, txt_path)
    with open(txt_path, encoding="utf-8", errors="replace") as f:
        raw_text = f.read()

    parsed = parse_dccs_export(raw_text)
    if len(parsed.dccs_rows) < 100:
        log.warning("DCCS row count is suspiciously low (%d) — check the parser regex", len(parsed.dccs_rows))

    session.execute(sql("TRUNCATE TABLE dccs_search_results RESTART IDENTITY CASCADE"))
    session.execute(sql("DELETE FROM cases WHERE request_id = :rid"), {"rid": parsed.request_id})

    case_id = parsed._source_case_id
    session.execute(
        sql(
            """
            INSERT INTO cases (id, request_id, request_type, originator, member_firm, location,
                office, service_offering, engagement_name, engagement_details, is_recurring,
                is_inbound_referral, has_iwrf, lead_partner, lead_manager, date_submitted,
                source_filename, raw_text)
            VALUES (:id, :request_id, :request_type, :originator, :member_firm, :location,
                :office, :service_offering, :engagement_name, :engagement_details, :is_recurring,
                :is_inbound_referral, :has_iwrf, :lead_partner, :lead_manager, :date_submitted,
                :source_filename, :raw_text)
            """
        ),
        {
            "id": case_id,
            "request_id": parsed.request_id,
            "request_type": parsed.request_type,
            "originator": parsed.originator,
            "member_firm": parsed.member_firm,
            "location": parsed.location,
            "office": parsed.office,
            "service_offering": parsed.service_offering,
            "engagement_name": parsed.engagement_name,
            "engagement_details": parsed.engagement_details,
            "is_recurring": parsed.is_recurring,
            "is_inbound_referral": parsed.is_inbound_referral,
            "has_iwrf": parsed.has_iwrf,
            "lead_partner": parsed.lead_partner,
            "lead_manager": parsed.lead_manager,
            "date_submitted": parsed.date_submitted,
            "source_filename": os.path.basename(pdf_path),
            "raw_text": None,
        },
    )

    for party in parsed.parties:
        session.execute(
            sql(
                """
                INSERT INTO case_parties (case_id, entity_name, party_side, entity_role, entity_type,
                    abbreviated_names, dgmf_id, address, location, stated_designation, is_gup)
                VALUES (:case_id, :entity_name, :party_side, :entity_role, :entity_type,
                    :abbreviated_names, :dgmf_id, :address, :location, :stated_designation, :is_gup)
                """
            ),
            {"case_id": case_id, **{k: v for k, v in party.items() if k != "full_legal_name"}},
        )

    if parsed.dccs_rows:
        rows = []
        for row in parsed.dccs_rows:
            r = dict(row)
            r["raw"] = json.dumps(r["raw"])
            rows.append(r)
        session.execute(
            sql(
                """
                INSERT INTO dccs_search_results (source_case_id, for_entity, request_id, request_type,
                    service_type, entity_name, side, entity_role, status, request_date, lead_partner,
                    description, raw)
                VALUES (:source_case_id, :for_entity, :request_id, :request_type, :service_type,
                    :entity_name, :side, :entity_role, :status, :request_date, :lead_partner,
                    :description, CAST(:raw AS JSONB))
                """
            ),
            rows,
        )

    session.execute(sql("DELETE FROM golden_cases WHERE request_id = :rid"), {"rid": parsed.request_id})
    session.execute(
        sql(
            """
            INSERT INTO golden_cases (case_id, request_id, final_result, conditions, analyst_comments, cross_border)
            VALUES (:case_id, :request_id, :final_result, CAST(:conditions AS JSONB),
                CAST(:analyst_comments AS JSONB), CAST(:cross_border AS JSONB))
            """
        ),
        {
            "case_id": case_id,
            "request_id": parsed.request_id,
            "final_result": parsed.golden.get("final_result"),
            "conditions": json.dumps(parsed.golden.get("conditions", [])),
            "analyst_comments": json.dumps(parsed.golden.get("analyst_comments", [])),
            "cross_border": json.dumps(parsed.golden.get("cross_border", [])),
        },
    )

    session.commit()
    log.info("Parsed %d DCCS history rows, %d case parties", len(parsed.dccs_rows), len(parsed.parties))
    return {"dccs_search_results": len(parsed.dccs_rows), "case_parties": len(parsed.parties)}
