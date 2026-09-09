"""Eval harness — score the pipeline against the analyst's real determination
(DEV_B §4).

Be honest in the demo: this is one worked case, not a test set. It proves
reproduction, not generalisation.

Usage: python -m app.eval.run_eval 12246557
"""

from __future__ import annotations

import logging
import sys

from app.database import SessionLocal
from app.repositories import case_repository, golden_repository
from app.services.screening_service import get_screening_result, run_screening

log = logging.getLogger(__name__)


def _check(name: str, expected: str, actual: str, passed: bool) -> dict:
    return {"name": name, "expected": expected, "actual": actual, "passed": bool(passed)}


def score(result: dict, golden: dict) -> list[dict]:
    """String-tolerant scoring, per DEV_B §4."""
    checks = []

    # 1. final result
    final = (result.get("final_result") or "").upper()
    checks.append(_check(
        "final_result",
        golden.get("final_result") or "Approved with Conditions",
        result.get("final_result") or "(none)",
        final == "APPROVED_WITH_CONDITIONS",
    ))

    # 2. a condition mentioning a DESC Relationship designation
    conditions = result.get("conditions") or []
    has_relationship = any(
        "relationship" in c.lower() and "desc" in c.lower() for c in conditions
    )
    checks.append(_check(
        "condition_desc_relationship",
        "Relationship client in DESC",
        next((c for c in conditions if "relationship" in c.lower()), "(none)"),
        has_relationship,
    ))

    # 3. every included WBS match is Non-Assurance
    wbs_rows = [r for r in result.get("summary_table", []) if r["source"] == "WBS"]
    non_assurance = [r for r in wbs_rows if r.get("business_unit") == "Non-Assurance"]
    checks.append(_check(
        "wbs_non_assurance",
        "all WBS matches Non-Assurance",
        f"{len(non_assurance)}/{len(wbs_rows)} Non-Assurance",
        bool(wbs_rows) and len(non_assurance) == len(wbs_rows),
    ))

    # 4. at least one WBS match included
    checks.append(_check(
        "wbs_match_found", "at least 1 WBS match", f"{len(wbs_rows)} WBS matches", bool(wbs_rows)
    ))

    # 5. at least one COT match included
    cot_rows = [r for r in result.get("summary_table", []) if r["source"] == "COT"]
    checks.append(_check(
        "cot_match_found", "at least 1 COT match", f"{len(cot_rows)} COT matches", bool(cot_rows)
    ))

    # 6. cross-border Japan resolves to "not required"
    golden_cb = (golden.get("cross_border") or [{}])[0]
    target_jurisdiction = golden_cb.get("jurisdiction", "Japan")
    actions = result.get("cross_border_actions") or []
    japan = next(
        (a for a in actions if (a.get("jurisdiction") or "").lower() == target_jurisdiction.lower()),
        None,
    )
    japan_ok = bool(japan) and "not required" in (japan.get("outcome") or "").lower()
    checks.append(_check(
        "cross_border_japan",
        f"{target_jurisdiction} → {golden_cb.get('outcome', 'Request Not Required')}",
        f"{target_jurisdiction} → {japan.get('outcome')}" if japan else "(no action produced)",
        japan_ok,
    ))

    # 7. triage actually differentiates — the deck's core promise is that a
    # reviewer gets a worklist, not an undifferentiated list of hits.
    summary = result.get("summary_table", [])
    tiered = [r for r in summary if r.get("risk_tier")]
    high_med = [r for r in summary if r.get("risk_tier") in ("High", "Medium")]
    differentiates = bool(tiered) and len(tiered) == len(summary) and len(high_med) < len(summary)
    checks.append(_check(
        "risk_triage_differentiates",
        "every match tiered, and fewer High/Medium than total",
        f"{len(tiered)}/{len(summary)} tiered; {len(high_med)} need attention",
        differentiates,
    ))

    # 8. the DESC-vs-request contradiction is caught
    flags = result.get("quality_check_flags") or []
    contradiction = next(
        (f for f in flags if f.get("severity") == "WARN" and "desc" in (f.get("message") or "").lower()),
        None,
    )
    checks.append(_check(
        "desc_contradiction_caught",
        "WARN flag present",
        "WARN flag present" if contradiction else "(no WARN flag)",
        bool(contradiction),
    ))

    return checks


def evaluate(case_id: str) -> dict:
    """Runs the pipeline on a case and scores it against golden_cases."""
    screening_id = run_screening(case_id)

    session = SessionLocal()
    try:
        result = get_screening_result(session, screening_id)
        golden = golden_repository.get(session, case_id)
        if golden is None:
            raise ValueError(f"no golden answer stored for case {case_id}")

        checks = score(result, golden)
        passed = sum(1 for c in checks if c["passed"])
        return {
            "case_id": case_id,
            "screening_id": screening_id,
            "score": f"{passed}/{len(checks)}",
            "passed": passed,
            "total": len(checks),
            "checks": checks,
        }
    finally:
        session.close()


def print_table(report: dict) -> None:
    checks = report["checks"]
    name_w = max(len(c["name"]) for c in checks) + 2
    exp_w = max(len(str(c["expected"])) for c in checks) + 2
    act_w = max(len(str(c["actual"])) for c in checks) + 2

    print()
    print(f"{'CHECK'.ljust(name_w)}{'EXPECTED'.ljust(exp_w)}{'ACTUAL'.ljust(act_w)}RESULT")
    print("-" * (name_w + exp_w + act_w + 8))
    for c in checks:
        mark = "PASS" if c["passed"] else "FAIL"
        print(
            f"{c['name'].ljust(name_w)}{str(c['expected']).ljust(exp_w)}"
            f"{str(c['actual']).ljust(act_w)}{mark}"
        )
    print("-" * (name_w + exp_w + act_w + 8))
    print(f"SCORE: {report['score']}")
    print()


def main() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")
    request_id = sys.argv[1] if len(sys.argv) > 1 else "12246557"

    session = SessionLocal()
    try:
        case = case_repository.get_by_request_id(session, request_id)
        if case is None:
            print(f"No case found for request {request_id}. Run scripts/run_ingestion.py first.")
            sys.exit(1)
        case_id = str(case["id"])
    finally:
        session.close()

    report = evaluate(case_id)
    print_table(report)
    sys.exit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
