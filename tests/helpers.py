"""Stand-ins for the LLM and the search API, so the real agents, tools and orchestrator can be tested
offline. The fake LLM answers by ROLE (identified from the system prompt) with canned JSON."""

import json
import re
from types import SimpleNamespace

from src import prompts
from src.agents import AnalystAgent, CriticAgent, ResearchAgent, StrategyAgent
from src.agents.base import UsageMeter
from src.orchestrator import Team
from src.tools import ResearchUnavailable

ROLES = {
    prompts.RESEARCH_QUERY_SYSTEM: "query",
    prompts.RESEARCH_EXTRACT_SYSTEM: "extract",
    prompts.FACTOR_JUDGE_SYSTEM: "judge",
    prompts.STRATEGY_SYSTEM: "strategy",
    prompts.STRATEGY_REVISE_SYSTEM: "revise",
    prompts.CRITIC_SYSTEM: "critic",
}
INVENTED = " A further 45% drop is expected in July."


class FakeLLM:
    def __init__(self, strategy_invents=False, reviser_fixes=True, critic_issues=None, fail_roles=(),
                 factor_verdict="supported"):
        self.meter = UsageMeter()
        self.calls = []                      # (role, user_prompt)
        self.queue = {}                      # role -> list of forced raw replies, consumed first
        self.strategy_invents = strategy_invents
        self.reviser_fixes = reviser_fixes
        self.critic_issues = critic_issues or []
        self.fail_roles = set(fail_roles)
        self.factor_verdict = factor_verdict

    def chat(self, system, user, max_tokens=900, temperature=0.0):
        role = ROLES[system]
        self.calls.append((role, user))
        self.meter.add(SimpleNamespace(prompt_tokens=100, completion_tokens=50))
        if role in self.fail_roles:
            raise RuntimeError(f"{role} unavailable")
        if self.queue.get(role):
            return self.queue[role].pop(0)
        return getattr(self, f"_{role}")(user)

    def roles(self):
        return [r for r, _ in self.calls]

    # ------------------------------------------------------------------ canned answers
    def _query(self, user):
        return "backpack demand trends pakistan"

    def _extract(self, user):
        url = re.search(r"url: (\S+)", user).group(1)
        return json.dumps({"factors": [{"claim": "Heavy summer discounting is common in apparel",
                                        "source_urls": [url], "testable_with": "UrbanTote Backpack"}]})

    def _judge(self, user):
        return json.dumps({"verdict": self.factor_verdict, "reason": "The data is consistent with the claim."})

    def _draft(self, user, invent):
        urban = re.search(r"(F\d+): UrbanTote Backpack revenue declined", user)
        total = re.search(r"(F\d+): Total revenue", user)
        urban_id = urban.group(1) if urban else "F1"
        total_id = total.group(1) if total else "F1"
        text = ("Total revenue grew 7.6%, so the decline is local. UrbanTote's average price fell 31.2% while "
                "its orders stayed flat, which makes it a price-driven decline.")
        if invent:
            text += INVENTED
        return json.dumps({"text": text, "recommendations": [
            {"text": "Review the June UrbanTote discount before raising acquisition spend.", "based_on": [urban_id]},
            {"text": "Do not cut the overall budget: total revenue grew, so target the local declines.",
             "based_on": [total_id]}]})

    def _strategy(self, user):
        return self._draft(user, self.strategy_invents)

    def _revise(self, user):
        return self._draft(user, not self.reviser_fixes and self.strategy_invents)

    def _critic(self, user):
        return json.dumps({"issues": self.critic_issues})


def make_search(mode="ok"):
    def search(query, max_results=3):
        if mode == "unavailable":
            raise ResearchUnavailable("External research is not configured (no TAVILY_API_KEY set).")
        if mode == "crash":
            raise RuntimeError("search API down")
        if mode == "empty":
            return []
        return [{"title": "Summer discounts in Pakistani retail", "url": "https://example.com/discounts",
                 "snippet": "Retailers discount apparel heavily in summer."},
                {"title": "Consumer demand outlook", "url": "https://example.com/demand", "snippet": "Demand is mixed."}]
    return search


def make_team(llm=None, search="ok", use_llm_critic=True):
    llm = llm or FakeLLM()
    return Team(llm,
                ResearchAgent(llm, tools={"search_external_information": make_search(search)}),
                AnalystAgent(llm), StrategyAgent(llm), CriticAgent(llm, use_llm=use_llm_critic))
