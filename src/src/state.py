"""
state.py
Shared run state (Day 60). One object per run. Only the orchestrator writes
to it: agents return results, the orchestrator stores them. Every finding cites
evidence ids and every recommendation cites finding ids, and the state refuses
anything that cites an id that does not exist.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .schemas import (Evidence, ExternalFactor, FactorCheck, Finding, Recommendation)


class RunState:
    # what each agent is allowed to see (least context)
    VIEWS = {
        "research": ["question"],
        "analyst": ["question", "research_factors"],
        "strategy": ["question", "findings", "evidence", "factor_checks"],
        "critic": ["findings", "evidence", "recommendations", "factor_checks"],  # not the writer's reasoning
    }

    def __init__(self, question: str):
        self.question = question
        self.research_factors: List[ExternalFactor] = []
        self.evidence: Dict[str, Evidence] = {}
        self.findings: Dict[str, Finding] = {}
        self.factor_checks: List[FactorCheck] = []
        self.recommendations: List[Recommendation] = []

    # ------------------------------------------------------------- writes
    def add_evidence(self, e: Evidence) -> None:
        if e.id in self.evidence:
            raise ValueError(f"duplicate evidence id {e.id}")
        self.evidence[e.id] = e

    def add_finding(self, f: Finding) -> None:
        if f.id in self.findings:
            raise ValueError(f"duplicate finding id {f.id}")
        missing = [i for i in f.evidence_ids if i not in self.evidence]
        if missing:
            raise ValueError(f"finding {f.id} cites unknown evidence {missing}")
        self.findings[f.id] = f

    def add_factor_check(self, c: FactorCheck) -> None:
        missing = [i for i in c.evidence_ids if i not in self.evidence]
        if missing:
            raise ValueError(f"factor check cites unknown evidence {missing}")
        self.factor_checks.append(c)

    def add_recommendation(self, r: Recommendation) -> None:
        missing = [i for i in r.based_on if i not in self.findings]
        if missing:
            raise ValueError(f"recommendation cites unknown findings {missing}")
        self.recommendations.append(r)

    # -------------------------------------------------------------- reads
    def evidence_texts(self) -> List[str]:
        return [e.detail for e in self.evidence.values()]

    def allowed_urls(self) -> set:
        return {u for f in self.research_factors for u in f.source_urls}

    def view_for(self, agent: str) -> dict:
        data = {
            "question": self.question,
            "research_factors": [f.model_dump() for f in self.research_factors],
            "findings": {k: v.model_dump() for k, v in self.findings.items()},
            "evidence": {k: v.model_dump() for k, v in self.evidence.items()},
            "factor_checks": [c.model_dump() for c in self.factor_checks],
            "recommendations": [r.model_dump() for r in self.recommendations],
        }
        return {k: data[k] for k in self.VIEWS[agent]}

    def as_dict(self) -> dict:
        return {
            "question": self.question,
            "research_factors": [f.model_dump() for f in self.research_factors],
            "evidence": {k: v.model_dump() for k, v in self.evidence.items()},
            "findings": {k: v.model_dump() for k, v in self.findings.items()},
            "factor_checks": [c.model_dump() for c in self.factor_checks],
            "recommendations": [r.model_dump() for r in self.recommendations],
        }


def save_run(state: RunState, result: dict, directory: Optional[Path] = None) -> Path:
    """Dump the final state and the result summary as JSON, so a bad answer can be investigated later.
    Run files contain business data: the runs/ folder is in .gitignore."""
    directory = Path(directory or config.RUNS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    payload = {
        "state": state.as_dict(),
        "status": result.get("status"),
        "limitations": result.get("limitations"),
        "log": result.get("log"),
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
