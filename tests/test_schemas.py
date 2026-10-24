import pytest
from pydantic import ValidationError

from src.schemas import (ExternalFactor, Finding, Issue, Recommendation, ResearchResult, Review,
                         StrategyDraft)

FACTOR = ExternalFactor(claim="Summer heat raises demand", source_urls=["https://example.com/heat"])


def test_research_result_round_trips_through_json():
    good = ResearchResult(status="ok", factors=[FACTOR])
    assert ResearchResult.model_validate_json(good.model_dump_json()) == good


def test_factor_without_a_source_is_rejected():
    with pytest.raises(ValidationError):
        ExternalFactor(claim="Prices are rising", source_urls=[])


@pytest.mark.parametrize("bad", [dict(status="ok"), dict(status="unavailable", factors=[FACTOR])])
def test_status_must_match_content(bad):
    with pytest.raises(ValidationError):
        ResearchResult(**bad)


@pytest.mark.parametrize("raw", ['{"status": "ok", "factors": [{"claim": "x"}]}', "not json at all"])
def test_malformed_output_raises_a_catchable_validation_error(raw):
    with pytest.raises(ValidationError):
        ResearchResult.model_validate_json(raw)


def test_finding_without_evidence_is_rejected():
    with pytest.raises(ValidationError):
        Finding(id="F1", statement="Revenue fell", evidence_ids=[], produced_by="analyst")


def test_recommendation_must_cite_a_finding():
    with pytest.raises(ValidationError):
        Recommendation(text="Do something", based_on=[])
    with pytest.raises(ValidationError):
        StrategyDraft(text="x", recommendations=[])


def test_review_cannot_be_approved_with_a_blocking_issue():
    blocking = Issue(ref="R1", kind="unsupported_claim", detail="x", severity="blocking")
    with pytest.raises(ValidationError):
        Review(approved=True, issues=[blocking])
    assert Review(approved=True, issues=[blocking.model_copy(update={"severity": "minor"})]).approved
