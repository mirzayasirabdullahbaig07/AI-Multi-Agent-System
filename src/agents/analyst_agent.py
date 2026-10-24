"""
agents/analyst_agent.py
The Analyst owns the company's OWN data. Its tools are the read-only database
queries and nothing else.

  analyze_internal()  deterministic: all numbers and findings are computed in
                      Python from tool results (no LLM), so they cannot be invented.
  test_factors()      takes external hypotheses from the Research Agent and checks
                      each against the company data. The LLM only judges "does this
                      data support the claim?"; the numbers it sees come from tools.
"""

import re
from typing import Dict, List, Optional, Tuple

from ..prompts import FACTOR_JUDGE_SYSTEM
from ..schemas import (Evidence, ExternalFactor, FactorCheck, FactorTestResult, FactorVerdict, Finding,
                       InternalAnalysis)
from ..tools import DATA_TOOLS
from .base import BaseAgent
from .. import config


def pct_change(old: float, new: float) -> Optional[float]:
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _s(value: Optional[float]) -> str:
    return f"{value:+.1f}%" if value is not None else "n/a"


def _trend(rows: List[dict]) -> Optional[dict]:
    """Compare the last two months of one product's rows."""
    if len(rows) < 2:
        return None
    a, b = rows[-2], rows[-1]
    return {"product": b["product"], "prev": a["month"], "latest": b["month"], "a": a, "b": b,
            "rev": pct_change(a["revenue"], b["revenue"]),
            "orders": pct_change(a["orders"], b["orders"]),
            "price": pct_change(a["avg_unit_price"], b["avg_unit_price"])}


def _product_detail(t: dict) -> str:
    a, b = t["a"], t["b"]
    return (f"{t['product']}: revenue {t['prev']} PKR {a['revenue']:,.0f} -> {t['latest']} PKR {b['revenue']:,.0f} "
            f"({_s(t['rev'])}); orders {a['orders']} -> {b['orders']} ({_s(t['orders'])}); "
            f"average unit price PKR {a['avg_unit_price']:,.0f} -> PKR {b['avg_unit_price']:,.0f} ({_s(t['price'])})")


def _label(t: dict) -> str:
    rev, orders, price = t["rev"], t["orders"], t["price"]
    if rev is None or orders is None or price is None:
        return "unclear"
    if rev < -5:
        if abs(orders) < 10 and price < -10:
            return "price-driven (orders roughly stable while the average price fell)"
        if orders < -10:
            return "demand-driven (the number of orders fell)"
    if rev > 5:
        if orders > 10:
            return "volume-driven (more orders)"
        if price > 10:
            return "price-driven (the average price rose)"
    return "mixed or unclear"


def _region_detail(region: str, rows: List[dict]) -> Optional[Tuple[str, Optional[float]]]:
    if len(rows) < 2:
        return None
    a, b = rows[-2], rows[-1]
    change = pct_change(a["revenue"], b["revenue"])
    return (f"{region} revenue: {a['month']} PKR {a['revenue']:,.0f} -> {b['month']} PKR {b['revenue']:,.0f} "
            f"({_s(change)}); orders {a['orders']} -> {b['orders']}"), change


class _Builder:
    def __init__(self):
        self.evidence: List[Evidence] = []
        self.findings: List[Finding] = []

    def add_evidence(self, detail: str) -> str:
        eid = f"E{len(self.evidence) + 1}"
        self.evidence.append(Evidence(id=eid, source="database", detail=detail))
        return eid

    def add_finding(self, statement: str, evidence_ids: List[str]) -> None:
        self.findings.append(Finding(id=f"F{len(self.findings) + 1}", statement=statement,
                                     evidence_ids=evidence_ids, produced_by="analyst"))


class AnalystAgent(BaseAgent):
    name = "analyst"

    def __init__(self, llm=None, tools=None):
        super().__init__(llm, DATA_TOOLS if tools is None else tools)

    # ------------------------------------------------------------------ internal analysis
    def analyze_internal(self) -> InternalAnalysis:
        regional = self.use_tool("get_regional_trend", months=6)
        products = self.use_tool("get_product_sales", months=6)
        b = _Builder()
        limitations: List[str] = []

        # 1. overall revenue: does the premise "revenue dropped" even hold for the whole business?
        totals: Dict[str, float] = {}
        for row in regional:
            totals[row["month"]] = totals.get(row["month"], 0) + row["revenue"]
        months = sorted(totals)
        if len(months) < 2:
            return InternalAnalysis(evidence=[], findings=[], limitations=["Fewer than two months of data."])
        prev, latest = months[-2], months[-1]
        change = pct_change(totals[prev], totals[latest])
        eid = b.add_evidence(f"Total revenue across all regions: {prev} PKR {totals[prev]:,.0f} -> "
                             f"{latest} PKR {totals[latest]:,.0f} ({_s(change)})")
        if change is not None and change >= 0:
            b.add_finding(f"Total revenue grew {abs(change):.1f}% from {prev} to {latest}, so overall revenue did "
                          f"not decline; any decline is confined to specific products or regions.", [eid])
        elif change is not None:
            b.add_finding(f"Total revenue declined {abs(change):.1f}% from {prev} to {latest}.", [eid])

        # 2. regions with a notable move
        by_region: Dict[str, List[dict]] = {}
        for row in regional:
            by_region.setdefault(row["region"], []).append(row)
        moves = []
        for region, rows in by_region.items():
            rows.sort(key=lambda r: r["month"])
            result = _region_detail(region, rows)
            if result and result[1] is not None and abs(result[1]) >= 8:
                moves.append((abs(result[1]), region, result[0], result[1]))
        for _mag, region, detail, ch in sorted(moves, reverse=True)[:4]:
            eid = b.add_evidence(detail)
            b.add_finding(f"{region} revenue {'declined' if ch < 0 else 'grew'} {abs(ch):.1f}% from {prev} to {latest}.", [eid])

        # 3. products with a notable move, and whether it is price-driven or demand-driven
        by_product: Dict[str, List[dict]] = {}
        for row in products:
            by_product.setdefault(row["product"], []).append(row)
        flagged = []
        for rows in by_product.values():
            rows.sort(key=lambda r: r["month"])
            t = _trend(rows)
            if t and t["latest"] == latest and t["rev"] is not None and abs(t["rev"]) >= 10:
                flagged.append(t)
        # declines come first: a "why did revenue drop?" question must not lose a decline behind bigger gains
        declines = sorted([t for t in flagged if t["rev"] < 0], key=lambda t: t["rev"])[:4]
        growth = sorted([t for t in flagged if t["rev"] > 0], key=lambda t: -t["rev"])[:6 - len(declines)]
        for t in declines + growth:
            eid = b.add_evidence(_product_detail(t))
            b.add_finding(f"{t['product']} revenue {'declined' if t['rev'] < 0 else 'grew'} {abs(t['rev']):.1f}%; "
                          f"the change is {_label(t)}.", [eid])

        # 4. the current best sellers
        top = self.use_tool("get_top_products", month=latest, limit=3)
        if top:
            names = ", ".join(r["product"] for r in top)
            eid = b.add_evidence(f"Top products in {latest} by revenue: " +
                                 ", ".join(f"{r['product']} (PKR {r['revenue']:,.0f})" for r in top))
            b.add_finding(f"The top 3 products in {latest} by revenue are {names}.", [eid])

        limitations += [f"Comparison covers the latest two months only ({prev} vs {latest}).",
                        "No cost or profit data is available, so margins cannot be assessed.",
                        "The business data is a synthetic sample dataset."]
        return InternalAnalysis(evidence=b.evidence, findings=b.findings, limitations=limitations)

    # ------------------------------------------------------------------ testing external factors
    @staticmethod
    def _match_entity(text: str, product_names: List[str]) -> Optional[Tuple[str, str]]:
        lowered = text.lower()
        for name in product_names:
            for candidate in (name.lower(), name.split()[0].lower()):
                if re.search(rf"\b{re.escape(candidate)}\b", lowered):
                    return "product", name
        for region in config.REGIONS:
            if re.search(rf"\b{re.escape(region.lower())}\b", lowered):
                return "region", region
        return None

    def _entity_detail(self, kind: str, name: str) -> Optional[str]:
        if kind == "product":
            rows = [r for r in self.use_tool("get_product_sales", product_name=name, months=6) if r["product"] == name]
            t = _trend(sorted(rows, key=lambda r: r["month"]))
            return _product_detail(t) if t and t["rev"] is not None else None
        rows = sorted([r for r in self.use_tool("get_regional_trend", months=6) if r["region"] == name],
                      key=lambda r: r["month"])
        result = _region_detail(name, rows)
        return result[0] if result else None

    def _judge(self, claim: str, detail: str) -> FactorVerdict:
        try:
            return self.ask_model(FACTOR_JUDGE_SYSTEM, f"Claim: {claim}\nCompany data:\n{detail}",
                                  FactorVerdict, max_tokens=200)
        except Exception as e:  # a failed judgment must not break the run: record it and carry on
            return FactorVerdict(verdict="not_testable", reason=f"Judgment unavailable ({type(e).__name__}).")

    def test_factors(self, factors: List[ExternalFactor]) -> FactorTestResult:
        product_names = self.use_tool("get_product_names")
        evidence: List[Evidence] = []
        checks: List[FactorCheck] = []
        cache: Dict[str, Optional[Tuple[str, str]]] = {}

        for factor in factors:
            entity = self._match_entity(f"{factor.claim} {factor.testable_with or ''}", product_names)
            if entity is None:
                checks.append(FactorCheck(claim=factor.claim, verdict="not_testable",
                                          reason="No matching product or region in the company data."))
                continue
            kind, name = entity
            if name not in cache:
                detail = self._entity_detail(kind, name)
                if detail is None:
                    cache[name] = None
                else:
                    xid = f"X{len(evidence) + 1}"
                    evidence.append(Evidence(id=xid, source="database", detail=detail))
                    cache[name] = (xid, detail)
            if cache[name] is None:
                checks.append(FactorCheck(claim=factor.claim, verdict="not_testable",
                                          reason=f"Not enough months of data for {name}."))
                continue
            xid, detail = cache[name]
            verdict = self._judge(factor.claim, detail)
            checks.append(FactorCheck(claim=factor.claim, verdict=verdict.verdict, evidence_ids=[xid],
                                      reason=verdict.reason))
        return FactorTestResult(factor_checks=checks, evidence=evidence)
