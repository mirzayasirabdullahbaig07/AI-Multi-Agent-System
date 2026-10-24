"""
orchestrator.py
Decides which agents run, in what order, with what input, and what happens when
something fails (Days 59, 61, 62).

  route()      read the request, choose the agents (or ask the user to clarify)
  build_plan() turn the chosen agents into tasks with dependencies
  run_plan()   execute the task graph in waves; independent tasks run in parallel
  run_team()   the full run: plan -> agents -> shared state -> Critic loop -> report

Rules this file enforces:
  * the orchestrator is the ONLY writer of the shared state;
  * a failure never crashes the run: it becomes a status and a limitation;
  * the report always says what it is (verified / not fully verified / partial / ...);
  * a hard cap on agent calls per run, shared safely by parallel threads.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import config
from .agents import AnalystAgent, CriticAgent, LLMClient, ResearchAgent, StrategyAgent
from .schemas import FactorTestResult, Handoff, Review
from .state import RunState, save_run

STATUS_LABELS = {
    "verified": "verified by the Critic",
    "not_fully_verified": "NOT fully verified (see limitations)",
    "partial": "partial (no recommendations produced)",
    "findings_only": "findings only (no recommendations requested)",
}


# =============================================================================
# Team: the four agents sharing one LLM client (and so one usage meter)
# =============================================================================
@dataclass
class Team:
    llm: LLMClient
    research: ResearchAgent
    analyst: AnalystAgent
    strategy: StrategyAgent
    critic: CriticAgent


def build_team(llm: Optional[LLMClient] = None, use_llm_critic: bool = True) -> Team:
    llm = llm or LLMClient()
    return Team(llm, ResearchAgent(llm), AnalystAgent(llm), StrategyAgent(llm), CriticAgent(llm, use_llm=use_llm_critic))


# =============================================================================
# Routing and planning
# =============================================================================
def route(question: str) -> List[str]:
    """Rule-based router. Returns [] when it cannot tell what the user wants (the caller then asks)."""
    q = question.lower()
    wants_external = any(w in q for w in ("market", "competitor", "industry", "external", "trend", "outside"))
    wants_internal = any(w in q for w in ("our ", "revenue", "sales", "customer", "product", "region", "orders"))
    wants_recs = any(w in q for w in ("recommend", "what should", "next step", "advice"))
    if not (wants_external or wants_internal or wants_recs):
        return []
    steps: List[str] = []
    if wants_external:
        steps.append("research")
    # recommendations need the company's own data, so asking for them always brings the Analyst in
    if wants_internal or wants_recs or not wants_external:
        steps.append("analyst")
    if wants_recs:
        steps.append("strategy")
    if "strategy" in steps:
        steps.append("critic")
    return steps


@dataclass
class Task:
    id: str
    agent: str
    depends_on: List[str] = field(default_factory=list)   # hard: if one failed, this task is skipped
    optional: List[str] = field(default_factory=list)     # soft: used if it succeeded, otherwise ignored


def build_plan(steps: List[str]) -> List[Task]:
    """The Critic is not a task here: review-and-revise is a loop of unknown length, so it runs after the graph."""
    tasks: List[Task] = []
    if "research" in steps:
        tasks.append(Task("research", "research"))
    if "analyst" in steps:
        tasks.append(Task("internal", "analyst"))
        if "research" in steps:
            tasks.append(Task("test", "analyst", depends_on=["research"]))
    if "strategy" in steps and any(t.id == "internal" for t in tasks):
        tasks.append(Task("strategy", "strategy", depends_on=["internal"],
                          optional=[t.id for t in tasks if t.id == "test"]))
    return tasks


def waves(tasks: List[Task]) -> List[List[Task]]:
    """Group tasks into waves: every task in a wave has all its dependencies finished."""
    done, remaining, out = set(), {t.id: t for t in tasks}, []
    while remaining:
        ready = [t for t in remaining.values() if all(d in done for d in t.depends_on + t.optional)]
        if not ready:
            raise ValueError("cycle or missing dependency in plan")
        out.append(ready)
        done |= {t.id for t in ready}
        for t in ready:
            del remaining[t.id]
    return out


def run_plan(tasks: List[Task], handlers: Dict[str, Callable], parallel: bool = True) -> Dict[str, dict]:
    """Run the task graph. Each task ends as ok / failed / skipped, with its duration; nothing is raised."""
    results: Dict[str, dict] = {}

    def run_one(task: Task) -> dict:
        failed = [d for d in task.depends_on if results[d]["status"] != "ok"]
        if failed:
            return {"status": "skipped", "reason": f"dependency failed: {failed}", "seconds": 0.0}
        inputs = {d: results[d]["output"] for d in task.depends_on + task.optional if results[d]["status"] == "ok"}
        t0 = time.perf_counter()
        try:
            output = handlers[task.id](inputs)
            return {"status": "ok", "output": output, "seconds": round(time.perf_counter() - t0, 3)}
        except Exception as e:
            return {"status": "failed", "error": f"{type(e).__name__}: {e}", "seconds": round(time.perf_counter() - t0, 3)}

    for wave in waves(tasks):
        if parallel and len(wave) > 1:
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                for t, r in zip(wave, pool.map(run_one, wave)):
                    results[t.id] = r
        else:
            for t in wave:
                results[t.id] = run_one(t)
    return results


# =============================================================================
# The review loop (Day 61)
# =============================================================================
def revise_until_approved(draft, review_fn: Callable, revise_fn: Callable, max_revisions: int = 2) -> dict:
    """Review, and while there are blocking issues, revise. Stops when approved, when the revision limit is
    reached, or when the same blocking issues come back unchanged (no progress)."""
    seen, review = None, review_fn(draft)
    for round_no in range(max_revisions + 1):
        blocking = sorted((i.ref, i.kind, i.detail) for i in review.issues if i.severity == "blocking")
        if review.approved or not blocking:
            return {"status": "approved", "rounds": round_no, "draft": draft, "issues": review.issues}
        if blocking == seen:
            return {"status": "stuck", "rounds": round_no, "draft": draft, "issues": review.issues}
        if round_no == max_revisions:
            return {"status": "unresolved", "rounds": round_no, "draft": draft, "issues": review.issues}
        seen = blocking
        draft = revise_fn(draft, review.issues)
        review = review_fn(draft)


# =============================================================================
# The integrated run
# =============================================================================
class BudgetExceeded(Exception):
    pass


def run_team(question: str, team: Optional[Team] = None, max_agent_calls: int = config.MAX_AGENT_CALLS,
             max_revisions: int = config.MAX_REVISIONS, save: bool = False, parallel: bool = True) -> dict:
    """Run the whole team on one question. Always returns a dict with status, report, limitations and log;
    it never raises."""
    started = time.perf_counter()
    log: dict = {"calls": [], "revisions": 0, "tasks": {}, "handoffs": [], "steps": [], "llm": {}, "seconds": 0.0}
    try:
        return _run_team(question, team, max_agent_calls, max_revisions, save, parallel, log, started)
    except Exception as e:  # last line of defence: a readable result, not a traceback
        log["seconds"] = round(time.perf_counter() - started, 2)
        return {"status": "error", "limitations": [f"Unexpected error: {type(e).__name__}: {e}"], "log": log,
                "report": "The run failed unexpectedly. No report was produced."}


def _run_team(question, team, max_agent_calls, max_revisions, save, parallel, log, started) -> dict:
    steps = route(question)
    log["steps"] = steps
    if not steps:
        log["seconds"] = round(time.perf_counter() - started, 2)
        return {"status": "needs_clarification", "limitations": [], "log": log,
                "report": "I could not tell what to analyse. Do you want your own sales data analysed, "
                          "market research, or recommendations?"}

    team = team or build_team()
    lock = threading.Lock()

    def hit(name: str) -> None:
        """Count one agent call; refuse once the budget is used. The counter is shared by parallel threads."""
        with lock:
            if len(log["calls"]) >= max_agent_calls:
                raise BudgetExceeded("agent call budget exhausted")
            log["calls"].append(name)

    def research_h(inputs):
        hit("research")
        return team.research.run(question)

    def internal_h(inputs):
        hit("analyst")
        return team.analyst.analyze_internal()

    def test_h(inputs):
        research = inputs["research"]
        if research.status != "ok":                       # nothing to test: no agent call is spent
            return FactorTestResult()
        hit("analyst")
        return team.analyst.test_factors(research.factors)

    def strategy_h(inputs):
        hit("strategy")
        return team.strategy.draft(question, inputs["internal"], inputs.get("test"))

    plan = build_plan(steps)
    log["plan"] = [t.id for t in plan]
    results = run_plan(plan, {"research": research_h, "internal": internal_h, "test": test_h, "strategy": strategy_h},
                       parallel=parallel)
    log["tasks"] = {tid: {k: v for k, v in r.items() if k != "output"} for tid, r in results.items()}
    for t in plan:
        for dep in t.depends_on + t.optional:
            if results[dep]["status"] == "ok":
                log["handoffs"].append(Handoff(from_task=dep, to_task=t.id,
                                               payload_type=type(results[dep]["output"]).__name__).model_dump())

    # ---- from here on the orchestrator is the ONLY writer of the shared state ----
    state, limitations, internal_out, tests_out = RunState(question), [], None, None

    def finish(status: str, report: str, draft_result=None) -> dict:
        log["seconds"] = round(time.perf_counter() - started, 2)
        log["llm"] = team.llm.meter.snapshot() if hasattr(team.llm, "meter") else {}
        result = {"status": status, "limitations": limitations, "log": log, "report": report}
        if save:
            log["saved_to"] = str(save_run(state, result))
        return result

    if "analyst" in steps:
        internal = results["internal"]
        if internal["status"] != "ok":
            limitations.append(f"Internal analysis unavailable: {internal.get('error') or internal.get('reason')}")
            return finish("insufficient_evidence", "Insufficient evidence to answer from the available business data.")
        internal_out = internal["output"]
        for e in internal_out.evidence:
            state.add_evidence(e)
        for f in internal_out.findings:
            state.add_finding(f)
        limitations += internal_out.limitations

    research = results.get("research")
    if research:
        if research["status"] != "ok":
            limitations.append(f"External research failed: {research.get('error') or research.get('reason')}")
        elif research["output"].status != "ok":
            limitations.append(f"External research unavailable: {research['output'].note}")
        else:
            state.research_factors = research["output"].factors
    test = results.get("test")
    if test and test["status"] == "ok":
        tests_out = test["output"]
        for e in tests_out.evidence:
            state.add_evidence(e)
        for c in tests_out.factor_checks:
            state.add_factor_check(c)
    elif research:
        limitations.append("External factors were not tested against the company data.")

    if not state.findings and not state.research_factors:
        return finish("insufficient_evidence", "Insufficient evidence to answer from the available data.")

    status = "partial" if "strategy" in steps else "findings_only"
    draft_result = None
    strategy = results.get("strategy")
    if strategy and strategy["status"] == "ok":
        draft0 = strategy["output"]

        def review_fn(draft) -> Review:
            hit("critic")
            return team.critic.review(draft, state)

        def revise_fn(draft, issues):
            log["revisions"] += 1
            hit("revise")
            return team.strategy.revise(question, draft, issues, internal_out, tests_out)

        try:
            draft_result = revise_until_approved(draft0, review_fn, revise_fn, max_revisions)
        except Exception as e:  # budget exhausted, or an agent failed, during review
            draft_result = {"status": "error", "draft": draft0, "issues": [], "error": f"{type(e).__name__}: {e}"}

        notes = [i for i in draft_result["issues"] if i.severity == "minor"]
        limitations += [f"Reviewer note: {i.detail}" for i in notes]
        if draft_result["status"] == "approved":
            try:
                for r in draft_result["draft"].recommendations:
                    state.add_recommendation(r)
                status = "verified"
            except ValueError as e:
                status = "not_fully_verified"
                limitations.append(f"Unresolved: {e}")
        else:
            status = "not_fully_verified"
            if draft_result["status"] == "error":
                limitations.append(f"Review step did not complete: {draft_result['error']}")
            limitations += [f"Unresolved: {i.detail}" for i in draft_result["issues"] if i.severity == "blocking"]
    elif strategy:
        limitations.append(f"Strategy step did not complete: {strategy.get('error') or strategy.get('reason')}")

    return finish(status, assemble_report(state, status, limitations, draft_result, log), draft_result)


# =============================================================================
# Report: built by code from the shared state, so every line traces back to ids
# =============================================================================
def assemble_report(state: RunState, status: str, limitations: List[str], draft_result, log: dict) -> str:
    lines = ["# Business Intelligence Report", f"**Question:** {state.question}",
             f"**Verification status:** {STATUS_LABELS[status]}"]
    draft = draft_result["draft"] if draft_result else None
    if draft:
        lines += ["", "## Summary" if status == "verified" else "## Draft summary (unverified)", draft.text]
    if state.findings:
        lines += ["", "## Findings"]
        lines += [f"- {f.id} ({', '.join(f.evidence_ids)}): {f.statement}" for f in state.findings.values()]
        lines += ["", "## Evidence"]
        lines += [f"- {e.id}: {e.detail}" for e in state.evidence.values()]
    if state.factor_checks:
        lines += ["", "## External factors tested"]
        lines += [f"- {c.claim} -> {c.verdict}" + (f": {c.reason}" if c.reason else "") for c in state.factor_checks]
    elif state.research_factors:
        lines += ["", "## External factors (not tested against company data)"]
        lines += [f"- {f.claim} (source: {', '.join(f.source_urls)})" for f in state.research_factors]
    if state.recommendations:
        lines += ["", "## Recommendations"]
        lines += [f"- {r.text} (based on {', '.join(r.based_on)})" for r in state.recommendations]
    elif draft and status == "not_fully_verified":
        lines += ["", "## Draft recommendations (unverified)"]
        lines += [f"- {r.text} (based on {', '.join(r.based_on)})" for r in draft.recommendations]
    lines += ["", "## Limitations"] + ([f"- {l}" for l in limitations] or ["- None recorded"])
    lines += ["", f"_Run log: {len(log['calls'])} agent calls, {log['revisions']} revision(s)._"]
    return "\n".join(lines)
