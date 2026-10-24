"""
agents/strategy_agent.py
The Strategy Agent turns findings into recommendations. It has NO tools: it
reads what the other agents found (through the orchestrator) and cannot fetch
new data, so it cannot introduce facts of its own. Every recommendation must
cite finding ids; the Critic checks that.
"""

from typing import List, Optional

from ..prompts import STRATEGY_REVISE_SYSTEM, STRATEGY_SYSTEM
from ..schemas import FactorTestResult, InternalAnalysis, Issue, StrategyDraft
from .base import BaseAgent


def _context(question: str, internal: InternalAnalysis, tests: Optional[FactorTestResult]) -> str:
    lines = [f"Business question: {question}", "", "Findings:"]
    lines += [f"{f.id}: {f.statement}" for f in internal.findings]
    lines += ["", "Evidence:"]
    evidence = list(internal.evidence) + (list(tests.evidence) if tests else [])
    lines += [f"{e.id}: {e.detail}" for e in evidence]
    if tests and tests.factor_checks:
        lines += ["", "External factors tested against the company data:"]
        lines += [f"- {c.claim} -> {c.verdict}" + (f" ({c.reason})" if c.reason else "") for c in tests.factor_checks]
    return "\n".join(lines)


class StrategyAgent(BaseAgent):
    name = "strategy"

    def __init__(self, llm=None, tools=None):
        super().__init__(llm, tools or {})

    def draft(self, question: str, internal: InternalAnalysis, tests: Optional[FactorTestResult] = None) -> StrategyDraft:
        return self.ask_model(STRATEGY_SYSTEM, _context(question, internal, tests), StrategyDraft, max_tokens=1000)

    def revise(self, question: str, draft: StrategyDraft, issues: List[Issue], internal: InternalAnalysis,
               tests: Optional[FactorTestResult] = None) -> StrategyDraft:
        blocking = [i for i in issues if i.severity == "blocking"]
        problems = "\n".join(f"- [{i.kind}] {i.ref}: {i.detail}" for i in blocking) or "- (none)"
        user = (f"{_context(question, internal, tests)}\n\nCurrent draft:\n{draft.model_dump_json(indent=2)}\n\n"
                f"Blocking issues to fix:\n{problems}")
        return self.ask_model(STRATEGY_REVISE_SYSTEM, user, StrategyDraft, max_tokens=1000)
