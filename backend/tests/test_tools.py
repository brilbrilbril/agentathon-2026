"""The tool registry — the layer the agents actually act through.

These run without an inference server: they call the tools directly, the way
the runtime does once the model has chosen them.
"""

import pytest

from app.agents import tools


def test_every_tool_has_a_schema_and_an_implementation():
    for name, (spec, fn) in tools.TOOLS.items():
        assert spec["function"]["name"] == name
        assert spec["function"]["description"].strip()
        assert callable(fn)


def test_specs_can_be_filtered():
    subset = tools.specs(["search_desc_entities", "get_footer_text"])
    assert {s["function"]["name"] for s in subset} == {"search_desc_entities", "get_footer_text"}


def test_unknown_tool_returns_error_not_exception():
    result = tools.execute("no_such_tool", {})
    assert "error" in result
    assert "available" in result


def test_bad_arguments_return_error_not_exception():
    result = tools.execute("search_desc_entities", {"wrong_arg": "x"})
    assert "error" in result


def test_search_desc_finds_kddi():
    result = tools.execute("search_desc_entities", {"entity_name": "KDDI Corporation"})
    assert result["total_matches"] > 0
    names = [r["name"] for r in result["results"]]
    assert any("KDDI" in n for n in names)


def test_search_one_window_is_an_honest_stub():
    result = tools.execute("search_one_window", {"entity_name": "KDDI Corporation"})
    assert result["total_matches"] == 0
    assert result["unchecked"] is True
    assert result["reason"]


def test_wbs_canary_through_the_tool():
    """The classifier the agent reaches for must still fail the canary safely."""
    result = tools.execute("classify_wbs_business_unit", {
        "market_offering_l1": "Audit & Assurance",
        "market_offering_l4": "A&A: ASV-Accounting & Reporting",
        "wbs_text": "KDDI - BCC ACCOUNTING ADVISORY",
    })
    assert result["business_unit"] == "Non-Assurance"
    assert "slide 6" in result["rule_citation"]


def test_desc_contradiction_through_the_tool():
    result = tools.execute("compare_stated_vs_desc_designation", {
        "stated_designation": "Restricted",
        "desc_designation": "Audit Team Restricted, Relationship",
    })
    assert result["contradiction"] is True
    assert result["severity"] == "WARN"
    assert "SEAIndependence@deloitte.com" in result["action"]


@pytest.mark.parametrize("vague", ["2021", "last year", ""])
def test_dccs_rule_refuses_an_unparseable_date(vague):
    """A date the tool cannot parse must not silently skip the staleness test —
    that once produced a confidently wrong 'include it' answer."""
    result = tools.execute("is_dccs_match_relevant", {
        "request_date": vague, "status": "Approved with Conditions",
    })
    assert "error" in result
    assert "relevant" not in result


def test_dccs_rule_excludes_a_stale_match():
    result = tools.execute("is_dccs_match_relevant", {
        "request_date": "2021-03-15", "status": "Approved with Conditions",
    })
    assert result["relevant"] is False
    assert "older than" in result["exclusion_reason"]


def test_cot_rule_refuses_an_unparseable_date():
    result = tools.execute("is_cot_match_acknowledged", {"submission_time": "sometime in 2025"})
    assert "error" in result


def test_cot_cutoff_through_the_tool():
    before = tools.execute("is_cot_match_acknowledged", {"submission_time": "2025-06-01"})
    after = tools.execute("is_cot_match_acknowledged", {"submission_time": "2025-08-01"})
    assert before["acknowledged"] is False
    assert after["acknowledged"] is True


def test_cross_border_japan_through_the_tool():
    result = tools.execute("evaluate_cross_border", {
        "jurisdiction": "Japan", "client_in_desc": True, "gup_in_desc": True, "client_is_gup": False,
    })
    assert result["outcome"] == "Request Not Required"
    assert "slide 11" in result["rule_citation"]


def test_footer_tool_returns_verbatim_text():
    result = tools.execute("get_footer_text", {})
    assert result["verbatim"] is True
    assert "DPM 1420" in result["footer"]
    assert "Personal Conflicts" in result["footer"]


def test_bulk_classifier_runs_over_collected_matches():
    tools.reset_collected()
    tools.execute("search_desc_entities", {"entity_name": "KDDI Corporation"})
    tools.execute("search_wbs_engagements", {"entity_name": "KDDI Corporation"})

    result = tools.execute("apply_qrc_rules_to_all_matches", {})
    assert result["total_classified"] > 0
    assert "by_source" in result
    # The canary again, this time via the bulk path the rules agent uses.
    assert result["wbs_business_units"].get("Audit") is None


def test_search_tools_collect_full_matches_for_persistence():
    tools.reset_collected()
    assert tools.collected_matches() == []
    tools.execute("search_desc_entities", {"entity_name": "KDDI Corporation"})
    assert len(tools.collected_matches()) > 0


def test_risk_tier_tool_differentiates():
    high = tools.execute("assess_risk_tier", {"source": "DESC", "designation_type": "SEC Restricted"})
    low = tools.execute("assess_risk_tier", {"source": "WBS", "business_unit": "Non-Assurance"})
    assert high["risk_tier"] == "High"
    assert low["risk_tier"] == "Low"
    assert "QRC" in high["rule_citation"]


def test_adjudicate_same_entity_returns_facts_not_a_verdict():
    """Whether two records are the same legal entity is a judgement call, so
    the tool must not decide it (MASTER §7)."""
    result = tools.execute("adjudicate_same_entity", {
        "query_name": "KDDI (Thailand) Limited",
        "candidate_name": "KDDI (THAILAND) COMPANY LIMITED",
        "query_country": "Thailand",
        "candidate_country": "Thailand",
    })
    assert "same_entity" not in result
    assert result["countries_match"] is True
    assert result["guidance"]


def test_adjudicate_flags_a_false_positive_as_different():
    result = tools.execute("adjudicate_same_entity", {
        "query_name": "KDDI (Thailand) Limited",
        "candidate_name": "Motto Auction Thailand Company Limited",
    })
    assert result["names_match_after_stripping_legal_suffixes"] is False


def test_bulk_classifier_reports_risk_tiers():
    tools.reset_collected()
    tools.execute("search_desc_entities", {"entity_name": "KDDI Corporation"})
    tools.execute("search_wbs_engagements", {"entity_name": "KDDI Corporation"})
    result = tools.execute("apply_qrc_rules_to_all_matches", {})
    assert result["risk_tiers"], "no tiers assigned"
    assert "needs_reviewer_attention" in result
    # Triage must actually reduce the reviewer's load.
    assert result["needs_reviewer_attention"] < result["included_in_summary"]


def test_engagement_team_search_finds_a_partner():
    """The people side: which clients a named partner already serves."""
    result = tools.execute("search_engagements_by_partner", {"partner_name": "Soon Bee Koh"})
    assert result["total_engagements"] > 0
    assert result["by_source"]
    assert "personnel records are not available" in result["note"]


def test_desc_responsible_party_lookup():
    result = tools.execute("get_desc_responsible_party", {"entity_name": "KDDI Corporation"})
    match = result["matches"][0]
    assert match["responsible_party"]
    assert "Restricted" in (match["designation"] or "")


def test_get_case_details_redirects_an_entity_name():
    """The model reaches for this with a company name; a raw UUID cast error
    is neither useful to it nor safe to surface."""
    result = tools.execute("get_case_details", {"case_id": "KDDI (Thailand) Limited"})
    assert "not a case id" in result["error"]
    assert "search_desc_entities" in result["hint"]


@pytest.mark.parametrize("query", [
    "KDDI CORPORATION", "kddi corporation", "Kddi Corporation", "  KDDI   Corporation  ",
])
def test_entity_search_is_case_and_whitespace_insensitive(query):
    """An analyst types however they type."""
    assert tools.execute("search_desc_entities", {"entity_name": query})["total_matches"] > 0
    assert tools.execute("search_wbs_engagements", {"entity_name": query})["total_matches"] > 0


@pytest.mark.parametrize("query", ["Soon Bee Koh", "soon bee koh", "SOON BEE KOH"])
def test_partner_search_is_case_insensitive(query):
    assert tools.execute("search_engagements_by_partner", {"partner_name": query})["total_engagements"] > 0


@pytest.mark.parametrize("designation", [
    "Audit Team Restricted", "audit team restricted", "AUDIT TEAM RESTRICTED",
])
def test_risk_tier_is_case_insensitive(designation):
    assert tools.execute("assess_risk_tier", {
        "source": "DESC", "designation_type": designation,
    })["risk_tier"] == "High"
