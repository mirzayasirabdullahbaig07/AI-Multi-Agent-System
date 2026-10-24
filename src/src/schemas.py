"""
schemas.py
Every message that moves between agents is a validated Pydantic model, so a
malformed or unsupported output fails at the handoff instead of three steps later.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------- research
class ExternalFactor(BaseModel):
    claim: str
    source_urls: List[str] = Field(min_length=1)      # no source, no factor
    testable_with: Optional[str] = None               # which internal data could test it


class ResearchResult(BaseModel):
    status: Literal["ok", "unavailable"]
    factors: List[ExternalFactor] = []
    note: Optional[str] = None

    @model_validator(mode="after")
    def status_matches_content(self):
        if self.status == "ok" and not self.factors:
            raise ValueError("status 'ok' needs at least one factor")
        if self.status == "unavailable" and self.factors:
            raise ValueError("status 'unavailable' must not contain factors")
        return self


# ---------------------------------------------------------------- analysis
class Evidence(BaseModel):
    id: str
    source: Literal["database", "web"]
    detail: str                                       # the exact numbers, never paraphrased away


class Finding(BaseModel):
    id: str
    statement: str
    evidence_ids: List[str] = Field(min_length=1)     # no finding without evidence
    produced_by: str


class InternalAnalysis(BaseModel):
    evidence: List[Evidence]
    findings: List[Finding]
    limitations: List[str] = []


class FactorCheck(BaseModel):
    claim: str
    verdict: Literal["supported", "contradicted", "not_testable"]
    evidence_ids: List[str] = []
    reason: Optional[str] = None


class FactorTestResult(BaseModel):
    factor_checks: List[FactorCheck] = []
    evidence: List[Evidence] = []                     # extra evidence gathered while testing factors


class FactorVerdict(BaseModel):
    """What the LLM returns when judging one factor against the data."""
    verdict: Literal["supported", "contradicted", "not_testable"]
    reason: str


# ---------------------------------------------------------------- strategy
class Recommendation(BaseModel):
    text: str
    based_on: List[str] = Field(min_length=1)         # finding ids this recommendation cites


class StrategyDraft(BaseModel):
    text: str                                         # short narrative summary
    recommendations: List[Recommendation] = Field(min_length=1)


# ---------------------------------------------------------------- critic
class Issue(BaseModel):
    ref: str                                          # finding / recommendation id, or "report"
    kind: Literal["unsupported_claim", "number_not_in_evidence", "unknown_source",
                  "conflict", "missing_information"]
    detail: str
    severity: Literal["blocking", "minor"]


class Review(BaseModel):
    approved: bool
    issues: List[Issue] = []

    @model_validator(mode="after")
    def approval_matches_issues(self):
        if self.approved and any(i.severity == "blocking" for i in self.issues):
            raise ValueError("cannot approve a report that has blocking issues")
        return self


class LLMReview(BaseModel):
    """What the LLM returns when asked to review a draft."""
    issues: List[Issue] = []


# ---------------------------------------------------------------- handoffs
class Handoff(BaseModel):
    from_task: str
    to_task: str
    payload_type: str
    summary: Optional[Dict[str, Any]] = None
