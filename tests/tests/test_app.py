"""Smoke tests for the Streamlit page using Streamlit's own AppTest runner (no browser).
These check behaviour (no crash, run limit, password gate, result shown). They do NOT check how the page looks."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import config

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


def fake_result(status="verified"):
    return {"status": status, "report": "## Findings\n- F1 (E1): UrbanTote is price-driven", "limitations": [],
            "log": {"calls": ["analyst", "strategy", "critic"], "steps": ["analyst", "strategy", "critic"],
                    "tasks": {"internal": {"status": "ok", "seconds": 0.1}}, "handoffs": [], "revisions": 0,
                    "llm": {"calls": 2, "prompt_tokens": 10, "completion_tokens": 5}, "seconds": 0.2}}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    monkeypatch.setattr(config, "MAX_RUNS_PER_SESSION", 2)
    monkeypatch.setattr("src.orchestrator.run_team", lambda question, save=False: fake_result())


def run_button(at):
    return next(b for b in at.button if b.label == "Run the team")


def test_page_loads_and_runs_a_question(configured):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.text_area[0].set_value("What are our top products?")
    run_button(at).click().run()
    assert not at.exception and at.session_state["runs"] == 1
    assert any("UrbanTote is price-driven" in m.value for m in at.markdown)


def test_missing_api_key_disables_the_button(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "APP_PASSWORD", "")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert at.warning and run_button(at).disabled


def test_run_limit_per_session(configured):
    at = AppTest.from_file(APP, default_timeout=30).run()
    for _ in range(2):
        at.text_area[0].set_value("What are our top products?")
        run_button(at).click().run()
    assert at.session_state["runs"] == 2 and run_button(at).disabled


def test_password_gate(configured, monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD", "secret")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not [b for b in at.button if b.label == "Run the team"]          # nothing usable before logging in
    at.text_input[0].set_value("wrong").run()
    assert at.error and not [b for b in at.button if b.label == "Run the team"]
    at.text_input[0].set_value("secret").run()
    assert run_button(at)
