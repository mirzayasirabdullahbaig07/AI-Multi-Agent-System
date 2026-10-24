"""
agents/critic_agent.py
The Critic checks a draft against the evidence. It sees findings, evidence and
the draft's recommendations, but NOT the writer's reasoning.

Two layers:
  * deterministic checks (reliable): numbers must appear in the evidence, URLs must
    have been returned by research, citations must point at existing findings;
  * an optional LLM judgment: does the cited evidence actually support each claim?
    This layer can be wrong in both directions, so approval is NOT proof of truth.

Known gaps of the number check: whole numbers under 10 are not checked, and a
derived number (a difference computed from two evidence values) is flagged because
it appears in no evidence.
"""

import re
from typing import List, Set

from ..prompts import CRITIC_SYSTEM
from ..schemas import Issue, LLMReview, Review, StrategyDraft
from ..state import RunState
from .base import BaseAgent

_NUM = re.compile(r"\d[\d,]*\.?\d*")
_URL = re.compile(r"https?://[^\s)\]]+")
_ID = re.compile(r"\b[EFRX]\d+\b")


def _numbers(text: str) -> Set[float]:
    out = set()
    for tok in _NUM.findall(text):
        try:
            out.add(float(tok.rstrip(".,").replace(",", "")))
        except ValueError:
            pass
    return out


def check_numbers(text: str, evidence_texts: List[str]) -> List[Issue]:
    """Flag numbers in `text` that appear in no evidence. Ignores ids (F1), years and whole numbers under 10."""
    allowed: Set[float] = set()
    for t in evidence_texts:
        allowed |= _numbers(t)
    issues = []
    for v in sorted(_numbers(_ID.sub("", text))):
        if (v < 10 and v == int(v)) or 1990 <= v <= 2100:
            continue
        if v not in allowed:
            issues.append(Issue(ref="report", kind="number_not_in_evidence",
                                detail=f"number {v:g} appears in the draft but in no evidence", severity="blocking"))
    return issues


def check_urls(text: str, allowed_urls: Set[str]) -> List[Issue]:
    return [Issue(ref="report", kind="unknown_source",
                  detail=f"{u} was not returned by the Research Agent", severity="blocking")
            for u in _URL.findall(text) if u not in allowed_urls]


class CriticAgent(BaseAgent):
    name = "critic"

    def __init__(self, llm=None, use_llm: bool = True, tools=None):
        super().__init__(llm, tools or {})
        self.use_llm = use_llm and llm is not None

    def review(self, draft: StrategyDraft, state: RunState) -> Review:
        text = draft.text + "\n" + "\n".join(r.text for r in draft.recommendations)
        issues = check_numbers(text, state.evidence_texts()) + check_urls(text, state.allowed_urls())
        for n, rec in enumerate(draft.recommendations, 1):
            unknown = [i for i in rec.based_on if i not in state.findings]
            if unknown:
                issues.append(Issue(ref=f"R{n}", kind="unsupported_claim",
                                    detail=f"cites unknown findings {unknown}", severity="blocking"))
        if self.use_llm:
            issues += self._llm_review(draft, state)
        return Review(approved=not any(i.severity == "blocking" for i in issues), issues=issues)

    def _llm_review(self, draft: StrategyDraft, state: RunState) -> List[Issue]:
        view = state.view_for("critic")
        lines = ["Findings:"] + [f"{k}: {v['statement']} (evidence: {', '.join(v['evidence_ids'])})"
                                 for k, v in view["findings"].items()]
        lines += ["", "Evidence:"] + [f"{k}: {v['detail']}" for k, v in view["evidence"].items()]
        lines += ["", "Draft recommendations:"]
        lines += [f"R{n}: {r.text} (based on {', '.join(r.based_on)})" for n, r in enumerate(draft.recommendations, 1)]
        lines += ["", f"Draft summary: {draft.text}"]
        try:
            return self.ask_model(CRITIC_SYSTEM, "\n".join(lines), LLMReview, max_tokens=700).issues
        except Exception as e:  # the LLM layer failing must not block the run; say so instead
            return [Issue(ref="report", kind="missing_information", severity="minor",
                          detail=f"The LLM review step was unavailable ({type(e).__name__}); only the "
                                 f"deterministic checks ran.")]
