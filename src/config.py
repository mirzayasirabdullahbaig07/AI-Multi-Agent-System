"""
config.py
Central place for settings, limits and paths.

Settings are read from the environment first (a local .env file is loaded
below) and then from Streamlit secrets, so the same code works locally and on
Streamlit Community Cloud.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent


def get_setting(name: str, default: str = "") -> str:
    """Environment first (works locally via .env), then Streamlit secrets (works on Streamlit Cloud)."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        return str(st.secrets[name])
    except Exception:  # no secrets file, or the key is not in it
        return default


def _int_setting(name: str, default: int) -> int:
    try:
        return int(get_setting(name, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# LLM (Groq's OpenAI-compatible endpoint, same pattern as earlier weeks)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = get_setting("OPENAI_API_KEY")
OPENAI_BASE_URL = get_setting("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = get_setting("LLM_MODEL", "openai/gpt-oss-120b")

LLM_TIMEOUT_SECONDS = 45      # timeout set on the API call itself (see Day 61: a thread cannot be cancelled)
LLM_MAX_ATTEMPTS = 3          # our own retry layer (the SDK's built-in retries are turned off)
LLM_BACKOFF_SECONDS = 1.0     # wait 1s, 2s, 4s ... between attempts

# ---------------------------------------------------------------------------
# External research (optional)
# ---------------------------------------------------------------------------
TAVILY_API_KEY = get_setting("TAVILY_API_KEY")

# ---------------------------------------------------------------------------
# Orchestration limits
# ---------------------------------------------------------------------------
MAX_AGENT_CALLS = 12          # hard cap on agent calls per run (cost guard)
MAX_REVISIONS = 2             # Strategy <-> Critic revision rounds
MAX_FACTORS = 4               # external factors kept from research

# ---------------------------------------------------------------------------
# Public-app protection (used by app.py)
# ---------------------------------------------------------------------------
APP_PASSWORD = get_setting("APP_PASSWORD")              # empty = no password gate
MAX_RUNS_PER_SESSION = _int_setting("MAX_RUNS_PER_SESSION", 10)
SAVE_RUNS = get_setting("SAVE_RUNS", "").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "business.db"
CUSTOMERS_CSV = DATA_DIR / "customers.csv"
PRODUCTS_CSV = DATA_DIR / "products.csv"
ORDERS_CSV = DATA_DIR / "orders.csv"
SALES_CSV = DATA_DIR / "sales.csv"
RUNS_DIR = ROOT_DIR / "runs"  # saved run states (contain business data: keep out of Git)

REGIONS = ["Punjab", "Sindh", "KPK", "Balochistan"]
