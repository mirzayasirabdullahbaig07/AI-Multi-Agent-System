import json

import pytest

from src.schemas import Evidence, Finding, Recommendation
from src.state import RunState, save_run


def make_state():
    s = RunState("Why did revenue drop?")
    s.add_evidence(Evidence(id="E1", source="database", detail="UrbanTote price -31.2%"))
    s.add_finding(Finding(id="F1", statement="Price-driven", evidence_ids=["E1"], produced_by="analyst"))
    s.add_recommendation(Recommendation(text="Review the discount", based_on=["F1"]))
    return s


def test_valid_state_builds():
    s = make_state()
    assert list(s.findings) == ["F1"] and len(s.recommendations) == 1


def test_citations_to_unknown_ids_are_rejected():
    s = make_state()
    with pytest.raises(ValueError):
        s.add_finding(Finding(id="F2", statement="x", evidence_ids=["E9"], produced_by="analyst"))
    with pytest.raises(ValueError):
        s.add_recommendation(Recommendation(text="x", based_on=["F7"]))


def test_duplicate_ids_are_rejected():
    s = make_state()
    with pytest.raises(ValueError):
        s.add_finding(Finding(id="F1", statement="again", evidence_ids=["E1"], produced_by="analyst"))
    with pytest.raises(ValueError):
        s.add_evidence(Evidence(id="E1", source="database", detail="again"))


def test_each_agent_sees_only_its_own_view():
    s = make_state()
    assert set(s.view_for("research")) == {"question"}
    assert "recommendations" not in s.view_for("analyst")
    assert "recommendations" not in s.view_for("strategy")
    assert set(s.view_for("critic")) == {"findings", "evidence", "recommendations", "factor_checks"}


def test_save_run_writes_readable_json(tmp_path):
    s = make_state()
    path = save_run(s, {"status": "verified", "limitations": [], "log": {"calls": ["analyst"]}}, directory=tmp_path)
    data = json.loads(path.read_text())
    assert data["status"] == "verified" and "F1" in data["state"]["findings"]
