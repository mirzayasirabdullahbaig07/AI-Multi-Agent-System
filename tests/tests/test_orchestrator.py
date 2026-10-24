import json

import pytest

from src import config
from src.orchestrator import Task, build_plan, route, run_plan, run_team, waves
from src.tools import DATA_TOOLS
from tests.helpers import FakeLLM, make_team

FULL = "Analyze our sales, research the market, and recommend what to do"


# ----------------------------------------------------------------------------- routing and plan
@pytest.mark.parametrize("question, expected", [
    ("What are our top products in June?", ["analyst"]),
    ("What market trends affect backpacks?", ["research"]),
    ("Why did revenue drop and what should we do next?", ["analyst", "strategy", "critic"]),
    (FULL, ["research", "analyst", "strategy", "critic"]),
    ("Research the market and recommend what to do", ["research", "analyst", "strategy", "critic"]),
    ("What should we do next?", ["analyst", "strategy", "critic"]),
    ("hello", []),
    ("Tell me something interesting", []),
])
def test_router(question, expected):
    assert route(question) == expected


def test_plan_waves_and_optional_dependency():
    plan = build_plan(route(FULL))
    assert [[t.id for t in w] for w in waves(plan)] == [["research", "internal"], ["test"], ["strategy"]]
    assert next(t for t in plan if t.id == "strategy").optional == ["test"]


def test_cycle_is_detected():
    with pytest.raises(ValueError):
        waves([Task("a", "x", ["b"]), Task("b", "x", ["a"])])


def test_failure_isolation_and_skipping():
    plan = [Task("r", "x"), Task("i", "x"), Task("t", "x", ["r"]), Task("s", "x", ["i"], optional=["t"])]

    def boom(_):
        raise RuntimeError("down")

    res = run_plan(plan, {"r": boom, "i": lambda _: "internal", "t": lambda _: "tested", "s": lambda inputs: sorted(inputs)})
    assert {k: v["status"] for k, v in res.items()} == {"r": "failed", "i": "ok", "t": "skipped", "s": "ok"}
    assert res["s"]["output"] == ["i"]                     # ran without the optional input that was skipped


# ----------------------------------------------------------------------------- end-to-end with the real agents
def test_happy_path():
    llm = FakeLLM()
    r = run_team(FULL, make_team(llm))
    calls = r["log"]["calls"]
    assert r["status"] == "verified"
    assert calls == ["research", "analyst", "analyst", "strategy", "critic"] or \
        (set(calls[:2]) == {"research", "analyst"} and calls[2:] == ["analyst", "strategy", "critic"])
    assert "## Recommendations" in r["report"] and "based on F" in r["report"]
    assert "-> supported" in r["report"] and "## Evidence" in r["report"]
    assert r["log"]["llm"]["calls"] == len(llm.calls)       # token accounting matches the calls actually made
    assert {h["from_task"] for h in r["log"]["handoffs"]} == {"research", "internal", "test"}


def test_false_premise_is_reported():
    r = run_team("Why did our revenue drop this month, and what should we do next?", make_team())
    assert r["status"] == "verified" and "did not decline" in r["report"]
    assert "research" not in r["log"]["calls"]


def test_research_unavailable_degrades_and_says_so():
    r = run_team(FULL, make_team(search="unavailable"))
    assert r["status"] == "verified" and any("External research unavailable" in l for l in r["limitations"])
    assert r["log"]["calls"].count("analyst") == 1           # no agent call is spent testing nothing


def test_research_crash_still_produces_a_report():
    r = run_team(FULL, make_team(search="crash"))
    assert r["status"] == "verified" and "strategy" in r["log"]["calls"]
    assert any("External research failed" in l for l in r["limitations"])
    assert any("not tested" in l for l in r["limitations"])
    assert r["log"]["tasks"]["test"]["status"] == "skipped"


def test_analyst_failure_means_insufficient_evidence():
    team = make_team()

    def boom(**kwargs):
        raise RuntimeError("database locked")

    team.analyst.tools = {**DATA_TOOLS, "get_regional_trend": boom}
    r = run_team(FULL, team)
    assert r["status"] == "insufficient_evidence"
    assert "strategy" not in r["log"]["calls"] and "critic" not in r["log"]["calls"]
    assert any("database locked" in l for l in r["limitations"])


def test_invented_number_is_caught_and_revised():
    r = run_team(FULL, make_team(FakeLLM(strategy_invents=True, reviser_fixes=True)))
    assert r["status"] == "verified" and r["log"]["revisions"] == 1
    assert "45%" not in r["report"] and r["log"]["calls"].count("critic") == 2


def test_unfixable_draft_is_not_presented_as_verified():
    r = run_team(FULL, make_team(FakeLLM(strategy_invents=True, reviser_fixes=False)))
    assert r["status"] == "not_fully_verified" and r["log"]["revisions"] == 1       # stuck detected after one revision
    assert any("number 45" in l for l in r["limitations"])
    assert "NOT fully verified" in r["report"] and "Draft recommendations (unverified)" in r["report"]


def test_llm_critic_blocking_issue_that_never_clears_ends_not_fully_verified():
    llm = FakeLLM(critic_issues=[{"ref": "R1", "kind": "unsupported_claim", "detail": "no support", "severity": "blocking"}])
    r = run_team(FULL, make_team(llm))
    assert r["status"] == "not_fully_verified" and any("no support" in l for l in r["limitations"])


def test_critic_llm_outage_is_disclosed_but_does_not_block():
    r = run_team(FULL, make_team(FakeLLM(fail_roles=("critic",))))
    assert r["status"] == "verified" and any("Reviewer note" in l for l in r["limitations"])


def test_unclear_request_asks_and_spends_nothing():
    llm = FakeLLM()
    r = run_team("hello", make_team(llm))
    assert r["status"] == "needs_clarification" and r["log"]["calls"] == [] and llm.calls == []


def test_call_budget_is_enforced_and_disclosed():
    r = run_team(FULL, make_team(), max_agent_calls=2)
    assert len(r["log"]["calls"]) == 2 and r["status"] == "partial"
    assert any("budget exhausted" in l for l in r["limitations"])


def test_analyst_only_request_is_cheap():
    llm = FakeLLM()
    r = run_team("What are our top products in June?", make_team(llm))
    assert r["status"] == "findings_only" and r["log"]["calls"] == ["analyst"] and llm.calls == []
    assert "## Recommendations" not in r["report"]


def test_research_only_requests():
    r = run_team("What market trends affect backpacks?", make_team())
    assert r["status"] == "findings_only" and r["log"]["calls"] == ["research"]
    assert "not tested against company data" in r["report"]
    r = run_team("What market trends affect backpacks?", make_team(search="unavailable"))
    assert r["status"] == "insufficient_evidence"


def test_repeated_parallel_runs_are_consistent():
    outcomes = {(r["status"], len(r["log"]["calls"])) for r in (run_team(FULL, make_team()) for _ in range(15))}
    assert outcomes == {("verified", 5)}


def test_run_can_be_saved_as_json(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    r = run_team(FULL, make_team(), save=True)
    data = json.loads(open(r["log"]["saved_to"]).read())
    assert data["status"] == "verified" and data["state"]["findings"]


def test_run_team_never_raises():
    team = make_team()

    def boom(*a, **k):
        raise RuntimeError("strategy exploded")

    team.strategy.draft = boom
    r = run_team(FULL, team)
    assert r["status"] == "partial" and any("Strategy step did not complete" in l for l in r["limitations"])
    assert run_team(FULL, team=object())["status"] == "error"


@pytest.mark.xfail(strict=True, reason="Known gap (Day 55/63): nothing checks that an entity named in the question "
                                       "(a 'Tokyo store') exists in the data, so unrelated findings are returned.")
def test_entity_not_in_the_data_should_be_insufficient_evidence():
    assert run_team("Why did our Tokyo store underperform?", make_team())["status"] == "insufficient_evidence"
