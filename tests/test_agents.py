import json
from types import SimpleNamespace

import pytest
from openai import APIConnectionError

from src import config
from src.agents import (AgentOutputError, AnalystAgent, CriticAgent, LLMClient, ResearchAgent, StrategyAgent,
                        UsageMeter, retry)
from src.agents.base import parse_model
from src.agents.critic_agent import check_numbers
from src.schemas import (Evidence, ExternalFactor, Finding, Issue, Recommendation, ResearchResult,
                         StrategyDraft)
from src.state import RunState
from tests.helpers import FakeLLM, make_search


# ----------------------------------------------------------------------------- permissions
def test_each_agent_can_only_use_its_own_tools():
    with pytest.raises(PermissionError):
        AnalystAgent(FakeLLM()).use_tool("search_external_information", query="x")
    with pytest.raises(PermissionError):
        ResearchAgent(FakeLLM()).use_tool("get_top_products")
    with pytest.raises(PermissionError):
        StrategyAgent(FakeLLM()).use_tool("get_top_products")
    assert AnalystAgent().use_tool("list_available_months")[-1] == "2026-06"


# ----------------------------------------------------------------------------- analyst
def test_analyst_findings_come_from_the_data():
    a = AnalystAgent().analyze_internal()
    text = " ".join(f.statement for f in a.findings)
    assert "Total revenue grew 7.6%" in text and "did not decline" in text
    assert "UrbanTote Backpack revenue declined 35.7%" in text and "price-driven" in text
    assert "AeroFit Running Shoes" in text and "PixelBeam LED Lamp" in text and "demand-driven" in text
    assert "KPK revenue declined 12.8%" in text


def test_analyst_numbers_are_always_in_their_own_evidence():
    a = AnalystAgent().analyze_internal()
    evidence = {e.id: e.detail for e in a.evidence}
    for f in a.findings:
        assert not check_numbers(f.statement, [evidence[i] for i in f.evidence_ids]), f.statement


def test_analyst_is_deterministic_and_never_calls_the_llm():
    llm = FakeLLM()
    first = AnalystAgent(llm).analyze_internal()
    assert first == AnalystAgent(llm).analyze_internal()
    assert llm.calls == []


def test_test_factors_uses_tool_data_and_the_llm_only_to_judge():
    llm = FakeLLM(factor_verdict="contradicted")
    result = AnalystAgent(llm).test_factors([ExternalFactor(
        claim="Heavy summer discounting is common", source_urls=["https://example.com/a"],
        testable_with="UrbanTote Backpack")])
    check = result.factor_checks[0]
    assert check.verdict == "contradicted" and check.evidence_ids == ["X1"]
    assert "UrbanTote Backpack" in result.evidence[0].detail and "-31.2%" in result.evidence[0].detail
    assert llm.roles() == ["judge"]


def test_factor_with_no_matching_data_is_not_testable_and_costs_no_llm_call():
    llm = FakeLLM()
    result = AnalystAgent(llm).test_factors([ExternalFactor(claim="Global oil prices rose",
                                                           source_urls=["https://example.com/a"])])
    assert result.factor_checks[0].verdict == "not_testable" and result.evidence == []
    assert llm.calls == []


def test_a_failed_judgment_is_recorded_not_raised():
    result = AnalystAgent(FakeLLM(fail_roles=("judge",))).test_factors([ExternalFactor(
        claim="Sindh demand is rising", source_urls=["https://example.com/a"])])
    assert result.factor_checks[0].verdict == "not_testable"
    assert "Judgment unavailable" in result.factor_checks[0].reason and result.evidence


# ----------------------------------------------------------------------------- research
def research(llm=None, mode="ok"):
    return ResearchAgent(llm or FakeLLM(), tools={"search_external_information": make_search(mode)})


def test_research_unavailable_is_a_handled_outcome():
    r = research(mode="unavailable").run("Why did sales fall?")
    assert r.status == "unavailable" and "TAVILY_API_KEY" in r.note and r.factors == []


def test_research_with_no_results_is_unavailable():
    assert research(mode="empty").run("q").status == "unavailable"


def test_research_factors_are_tied_to_returned_urls():
    r = research().run("Why did backpack sales fall?")
    assert r.status == "ok" and r.factors[0].source_urls == ["https://example.com/discounts"]


def test_research_drops_factors_with_invented_urls():
    llm = FakeLLM()
    llm.queue["extract"] = [json.dumps({"factors": [
        {"claim": "Real", "source_urls": ["https://example.com/demand"]},
        {"claim": "Invented source", "source_urls": ["https://made-up.com/x"]}]})]
    r = research(llm).run("q")
    assert [f.claim for f in r.factors] == ["Real"]


def test_research_with_only_invented_urls_is_unavailable():
    llm = FakeLLM()
    llm.queue["extract"] = [json.dumps({"factors": [{"claim": "x", "source_urls": ["https://made-up.com/x"]}]})]
    assert research(llm).run("q").status == "unavailable"


def test_research_repairs_one_malformed_reply_then_fails_clearly():
    llm = FakeLLM()
    llm.queue["extract"] = ["not json"]
    assert research(llm).run("q").status == "ok" and llm.roles().count("extract") == 2
    llm2 = FakeLLM()
    llm2.queue["extract"] = ["not json", "still not json"]
    with pytest.raises(AgentOutputError):
        research(llm2).run("q")


def test_research_query_falls_back_to_the_task_if_the_llm_fails():
    llm = FakeLLM(fail_roles=("query",))
    seen = {}

    def search(query, max_results=3):
        seen["q"] = query
        return make_search()(query)

    ResearchAgent(llm, tools={"search_external_information": search}).run("Why did backpack sales fall?")
    assert seen["q"] == "Why did backpack sales fall?"


# ----------------------------------------------------------------------------- strategy
@pytest.fixture(scope="module")
def internal():
    """Built inside a test (after the temp database exists), never at import time."""
    return AnalystAgent().analyze_internal()


def test_strategy_parses_fenced_json_and_repairs_bad_output(internal):
    llm = FakeLLM()
    good = llm._strategy("F1: UrbanTote Backpack revenue declined")
    llm.queue["strategy"] = ["```json\n" + good + "\n```"]
    assert isinstance(StrategyAgent(llm).draft("q", internal), StrategyDraft)
    llm.queue["strategy"] = ["nope"]
    StrategyAgent(llm).draft("q", internal)
    assert llm.roles()[-2:] == ["strategy", "strategy"]          # one repair attempt


def test_revision_prompt_contains_the_blocking_issues(internal):
    llm = FakeLLM(strategy_invents=True)
    agent = StrategyAgent(llm)
    draft = agent.draft("q", internal)
    agent.revise("q", draft, [Issue(ref="report", kind="number_not_in_evidence", severity="blocking",
                                    detail="number 45 appears in the draft but in no evidence")], internal)
    role, prompt = llm.calls[-1]
    assert role == "revise" and "number 45 appears" in prompt


# ----------------------------------------------------------------------------- critic
def state_with_evidence():
    s = RunState("q")
    s.add_evidence(Evidence(id="E1", source="database", detail="UrbanTote avg price 3,465 -> 2,384 (-31.2%)"))
    s.add_finding(Finding(id="F1", statement="Price-driven", evidence_ids=["E1"], produced_by="analyst"))
    return s


def draft(text="Price fell 31.2%.", rec="Review the discount", based_on=("F1",)):
    return StrategyDraft(text=text, recommendations=[Recommendation(text=rec, based_on=list(based_on))])


def test_critic_approves_a_grounded_draft():
    assert CriticAgent(use_llm=False).review(draft(), state_with_evidence()).approved


def test_critic_flags_invented_numbers_including_decimals():
    for text, number in (("A further 45% drop is expected.", "45"), ("Revenue rose 8.4%.", "8.4")):
        review = CriticAgent(use_llm=False).review(draft(text=text), state_with_evidence())
        assert not review.approved and number in review.issues[0].detail


def test_critic_number_check_has_a_known_gap_for_whole_numbers_under_10():
    assert CriticAgent(use_llm=False).review(draft(text="Price fell 5%."), state_with_evidence()).approved


def test_critic_flags_unknown_urls_and_unknown_citations():
    review = CriticAgent(use_llm=False).review(draft(text="See https://made-up.com/x", based_on=("F9",)),
                                               state_with_evidence())
    assert {i.kind for i in review.issues} == {"unknown_source", "unsupported_claim"}


def test_critic_llm_failure_is_a_minor_note_not_a_block():
    review = CriticAgent(FakeLLM(fail_roles=("critic",))).review(draft(), state_with_evidence())
    assert review.approved and review.issues[0].severity == "minor"


def test_critic_llm_can_block():
    llm = FakeLLM(critic_issues=[{"ref": "R1", "kind": "unsupported_claim", "detail": "no support", "severity": "blocking"}])
    assert not CriticAgent(llm).review(draft(), state_with_evidence()).approved


# ----------------------------------------------------------------------------- base: retry, parsing, usage, LLM client
def test_retry_backs_off_and_only_retries_transient_errors():
    sleeps, state = [], {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] <= 2:
            raise TimeoutError("slow")
        return "ok"

    assert retry(flaky, sleep=sleeps.append) == "ok" and sleeps == [1.0, 2.0]

    def denied():
        state["n"] += 1
        raise PermissionError("no")

    state["n"] = 0
    with pytest.raises(PermissionError):
        retry(denied)
    assert state["n"] == 1


def test_parse_model_handles_fences_and_surrounding_text():
    assert parse_model('Sure!\n```json\n{"status": "unavailable", "note": "x"}\n```', ResearchResult).status == "unavailable"


def test_usage_meter_tolerates_missing_usage():
    m = UsageMeter()
    m.add(SimpleNamespace(prompt_tokens=420, completion_tokens=130))
    m.add(None)
    assert m.snapshot() == {"calls": 2, "prompt_tokens": 420, "completion_tokens": 130}


def test_llm_client_retries_transient_errors_and_counts_usage(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS", 3)
    attempts = {"n": 0}

    class FakeCompletions:
        def create(self, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise APIConnectionError(request=object())
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                                   choices=[SimpleNamespace(message=SimpleNamespace(content=" hello "))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    sleeps = []
    llm = LLMClient(client=client, sleep=sleeps.append)
    assert llm.chat("s", "u") == "hello"
    assert attempts["n"] == 2 and sleeps == [config.LLM_BACKOFF_SECONDS] and llm.meter.snapshot()["calls"] == 1
