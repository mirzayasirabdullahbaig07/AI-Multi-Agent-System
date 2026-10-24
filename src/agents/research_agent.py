"""
agents/research_agent.py
The Research Agent owns EXTERNAL evidence. Its only tool is web search, so it
cannot touch the company database. Every factor it returns must be tied to a URL
that the search actually returned; anything else is dropped.
"""

from typing import List

from pydantic import BaseModel

from .. import config
from ..prompts import RESEARCH_EXTRACT_SYSTEM, RESEARCH_QUERY_SYSTEM
from ..schemas import ExternalFactor, ResearchResult
from ..tools import SEARCH_TOOLS, ResearchUnavailable
from .base import BaseAgent


class _Extraction(BaseModel):
    factors: List[ExternalFactor] = []


class ResearchAgent(BaseAgent):
    name = "research"

    def __init__(self, llm=None, tools=None):
        super().__init__(llm, SEARCH_TOOLS if tools is None else tools)

    def _query(self, task: str) -> str:
        """Ask the LLM for a short query; fall back to the task text itself if that fails."""
        try:
            query = self.llm.chat(RESEARCH_QUERY_SYSTEM, task, max_tokens=40)
            query = query.strip().splitlines()[0].strip(" \"'") if query.strip() else ""
        except Exception:
            query = ""
        return (query or task)[:120]

    def run(self, task: str) -> ResearchResult:
        query = self._query(task)
        try:
            results = self.use_tool("search_external_information", query=query, max_results=3)
        except ResearchUnavailable as e:
            return ResearchResult(status="unavailable", note=str(e))
        if not results:
            return ResearchResult(status="unavailable", note="Search returned no results.")

        allowed = {r["url"] for r in results}
        listing = "\n".join(f"[{i}] title: {r['title']}\n    url: {r['url']}\n    snippet: {r['snippet'][:400]}"
                            for i, r in enumerate(results, 1))
        extraction = self.ask_model(RESEARCH_EXTRACT_SYSTEM, f"Business question: {task}\n\nSearch results:\n{listing}",
                                    _Extraction, max_tokens=900)
        valid = [f for f in extraction.factors if all(u in allowed for u in f.source_urls)][:config.MAX_FACTORS]
        if not valid:
            return ResearchResult(status="unavailable", note="No factor could be tied to a returned source.")
        return ResearchResult(status="ok", factors=valid)
