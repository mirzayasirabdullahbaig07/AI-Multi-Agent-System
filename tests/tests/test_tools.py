import pytest
import requests

from src import config, tools


def table_counts():
    conn = tools.get_connection()
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("customers", "products", "orders", "sales")}
    finally:
        conn.close()


def test_database_matches_the_week_8_dataset():
    assert table_counts() == {"customers": 60, "products": 10, "orders": 492, "sales": 736}


def test_urbantote_june_pattern_is_present():
    rows = {r["month"]: r for r in tools.get_product_sales("UrbanTote", months=6)}
    may, june = rows["2026-05"], rows["2026-06"]
    assert june["orders"] == may["orders"]                        # orders flat
    assert june["avg_unit_price"] < may["avg_unit_price"] * 0.75  # price fell about 31%


def test_data_tools_return_plain_data():
    assert tools.list_available_months()[-1] == "2026-06"
    assert len(tools.get_top_products(month="2026-06", limit=3)) == 3
    assert {r["region"] for r in tools.get_regional_trend()} == set(config.REGIONS)
    assert tools.get_customer_metrics()


def test_search_without_a_key_raises_research_unavailable(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    with pytest.raises(tools.ResearchUnavailable):
        tools.search_external_information("anything")


def test_search_parses_results(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "key")

    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"results": [{"title": "T", "url": "https://x.com/a", "content": "C"},
                                            {"title": "no url", "content": "dropped"}]}

    monkeypatch.setattr(tools.requests, "post", lambda *a, **k: Resp())
    assert tools.search_external_information("q") == [{"title": "T", "url": "https://x.com/a", "snippet": "C"}]


def test_search_request_failure_becomes_research_unavailable(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "key")

    def boom(*a, **k):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(tools.requests, "post", boom)
    with pytest.raises(tools.ResearchUnavailable):
        tools.search_external_information("q")
