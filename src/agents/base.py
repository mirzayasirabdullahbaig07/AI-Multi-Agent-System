"""
agents/base.py
Shared building blocks for the agents: the LLM client (with timeout, retry with
backoff, and token accounting), JSON-to-schema parsing with one repair attempt,
and BaseAgent, which enforces each agent's tool permissions in code.

(This file is one small addition to the planned structure, so the four agents
do not each repeat this logic.)
"""

import re
import threading
import time
from typing import Callable, Dict, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .. import config

T = TypeVar("T", bound=BaseModel)


class AgentOutputError(Exception):
    """An agent's output did not match its schema, even after one repair attempt."""


class LLMNotConfigured(RuntimeError):
    """No API key is set. Not retryable."""


def retry(fn: Callable, attempts: int = 3, base_delay: float = 1.0,
          retry_on: tuple = (TimeoutError, ConnectionError), sleep: Callable = time.sleep):
    """Call fn(); on a transient error wait 1x, 2x, 4x ... base_delay and try again, up to `attempts` times.
    Errors outside `retry_on` are raised immediately (retrying a logic error cannot fix it)."""
    for n in range(1, attempts + 1):
        try:
            return fn()
        except retry_on:
            if n == attempts:
                raise
            sleep(base_delay * 2 ** (n - 1))


class UsageMeter:
    """Counts successful LLM calls and tokens. Thread-safe: parallel agents share one meter."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def add(self, usage) -> None:
        with self._lock:
            self.calls += 1
            if usage is not None:  # some providers/models may omit usage
                self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0

    def snapshot(self) -> dict:
        with self._lock:
            return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens}


def _transient_errors() -> tuple:
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
    return (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError, TimeoutError, ConnectionError)


class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat endpoint (Groq by default)."""

    def __init__(self, client=None, meter: Optional[UsageMeter] = None, sleep: Callable = time.sleep):
        self._client = client
        self.meter = meter or UsageMeter()
        self._sleep = sleep

    def _get_client(self):
        if self._client is None:
            if not config.OPENAI_API_KEY:
                raise LLMNotConfigured("OPENAI_API_KEY is not set.")
            from openai import OpenAI
            # SDK retries are off: this class owns retrying, so one logical call never becomes many hidden ones.
            self._client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL,
                                  timeout=config.LLM_TIMEOUT_SECONDS, max_retries=0)
        return self._client

    def chat(self, system: str, user: str, max_tokens: int = 900, temperature: float = 0.0) -> str:
        client = self._get_client()

        def call() -> str:
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self.meter.add(getattr(response, "usage", None))
            return (response.choices[0].message.content or "").strip()

        return retry(call, attempts=config.LLM_MAX_ATTEMPTS, base_delay=config.LLM_BACKOFF_SECONDS,
                     retry_on=_transient_errors(), sleep=self._sleep)


_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


def parse_model(raw: str, model_cls: Type[T]) -> T:
    """Parse the LLM's JSON into a validated model. Tolerates code fences and text around the JSON object."""
    text = _FENCE.sub("", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    return model_cls.model_validate_json(text)


def _short(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'output'}: {e['msg']}" for e in error.errors()[:3])


class BaseAgent:
    name = "agent"

    def __init__(self, llm: Optional[LLMClient] = None, tools: Optional[Dict[str, Callable]] = None):
        self.llm = llm
        self.tools = dict(tools or {})

    def use_tool(self, tool_name: str, **kwargs):
        """The permission guard: an agent may only call the tools it was given."""
        if tool_name not in self.tools:
            raise PermissionError(f"{self.name} is not allowed to use '{tool_name}'")
        return self.tools[tool_name](**kwargs)

    def ask_model(self, system: str, user: str, model_cls: Type[T], max_tokens: int = 900) -> T:
        """Ask the LLM for JSON matching model_cls. One repair attempt on bad output, then a clear error."""
        if self.llm is None:
            raise LLMNotConfigured(f"{self.name} has no LLM client.")
        raw = self.llm.chat(system, user, max_tokens=max_tokens)
        try:
            return parse_model(raw, model_cls)
        except ValidationError as first:
            repair = (f"{user}\n\nYour previous answer was not valid: {_short(first)}.\n"
                      f"Previous answer:\n{raw[:1500]}\n\nReturn ONLY the corrected JSON object.")
            raw2 = self.llm.chat(system, repair, max_tokens=max_tokens)
            try:
                return parse_model(raw2, model_cls)
            except ValidationError as second:
                raise AgentOutputError(
                    f"{self.name}: output did not match {model_cls.__name__} after one repair attempt "
                    f"({_short(second)})") from second
