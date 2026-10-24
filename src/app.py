"""
app.py
Streamlit front end for the AI Business Intelligence Team.

Run with:
    streamlit run src/app.py
"""

import html
import sys
import textwrap
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.orchestrator import run_team
from src.tools import build_database

st.set_page_config(page_title="AI Business Intelligence Team", page_icon="◍", layout="centered")

# ---------------------------------------------------------------------------
# Theme (light, matching the banner: ink text, emerald accent, one colour per agent)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
    :root {
        --bg: #F6F8F7; --panel: #FFFFFF; --border: #E1E6EA; --text: #14201B; --muted: #5C6770;
        --emerald: #059669; --research: #2563EB; --analyst: #D97706; --strategy: #E11D48; --critic: #7C3AED;
    }
    #MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"] { visibility: hidden; height: 0; }
    [data-testid="stSidebar"] { display: none; }
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: var(--bg); color: var(--text); }
    .block-container { max-width: 780px; padding-top: 1.5rem; padding-bottom: 4rem; }

    .bi-topbar { display: flex; align-items: center; justify-content: space-between; padding: 0.9rem 1.1rem;
        margin-bottom: 1.2rem; border: 1px solid var(--border); border-radius: 12px; background: var(--panel); }
    .bi-brand { display: flex; align-items: center; gap: 0.7rem; }
    .bi-title { font-family: 'Source Serif 4', serif; font-size: 1.25rem; font-weight: 700; line-height: 1.1; }
    .bi-tagline { font-size: 0.74rem; color: var(--muted); margin-top: 2px; }
    .bi-pill { font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: var(--muted);
        border: 1px solid var(--border); border-radius: 999px; padding: 0.25rem 0.7rem; background: var(--bg); }

    .bi-card { border: 1px solid var(--border); border-radius: 12px; background: var(--panel);
        padding: 0.9rem 1.1rem; margin: 1.1rem 0 0.4rem 0; }
    .bi-question { font-family: 'Source Serif 4', serif; font-size: 1.02rem; font-weight: 600; margin-top: 0.5rem; }
    .bi-badge { display: inline-block; font-family: 'JetBrains Mono', monospace; font-size: 0.68rem; font-weight: 500;
        border-radius: 999px; padding: 0.15rem 0.65rem; color: #fff; }
    .bi-chip { display: inline-block; font-family: 'JetBrains Mono', monospace; font-size: 0.66rem; border-radius: 999px;
        padding: 0.1rem 0.55rem; margin-right: 0.3rem; border: 1px solid; background: var(--panel); }

    .stTextArea textarea { background: var(--panel) !important; color: var(--text) !important;
        border: 1px solid var(--border) !important; border-radius: 10px !important; }
    .stTextArea textarea:focus { border-color: var(--emerald) !important; box-shadow: 0 0 0 1px var(--emerald) !important; }
    div[data-testid="stButton"] button[kind="primary"] { background: var(--emerald) !important; color: #fff !important;
        border: none !important; font-weight: 600 !important; border-radius: 8px !important; }
    div[data-testid="stButton"] button:not([kind="primary"]) { background: var(--panel); color: var(--muted);
        border: 1px solid var(--border); border-radius: 999px; font-size: 0.74rem; padding: 0.2rem 0.8rem; }
    div[data-testid="stButton"] button:not([kind="primary"]):hover { border-color: var(--emerald); color: var(--emerald); }
    [data-testid="stExpander"] { border: 1px solid var(--border) !important; border-radius: 10px !important; background: var(--panel) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_html(fragment: str) -> None:
    """Collapse to single-line HTML: Streamlit's markdown parser turns an indented multi-line fragment into a code block."""
    st.markdown(" ".join(line.strip() for line in textwrap.dedent(fragment).splitlines()), unsafe_allow_html=True)


MARK_SVG = (
    '<svg width="30" height="30" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="16" cy="16" r="12.5" stroke="#D5DBE3" stroke-width="1.4" stroke-dasharray="3 5"/>'
    '<line x1="16" y1="16" x2="8" y2="8" stroke="#2563EB" stroke-width="2"/>'
    '<line x1="16" y1="16" x2="24" y2="8" stroke="#D97706" stroke-width="2"/>'
    '<line x1="16" y1="16" x2="8" y2="24" stroke="#E11D48" stroke-width="2"/>'
    '<line x1="16" y1="16" x2="24" y2="24" stroke="#7C3AED" stroke-width="2"/>'
    '<circle cx="8" cy="8" r="3.4" fill="#2563EB"/><circle cx="24" cy="8" r="3.4" fill="#D97706"/>'
    '<circle cx="8" cy="24" r="3.4" fill="#E11D48"/><circle cx="24" cy="24" r="3.4" fill="#7C3AED"/>'
    '<circle cx="16" cy="16" r="5" fill="#14201B"/><circle cx="16" cy="16" r="1.8" fill="#10B981"/></svg>'
)

STATUS_COLORS = {
    "verified": "#059669", "not_fully_verified": "#D97706", "partial": "#D97706", "findings_only": "#2563EB",
    "insufficient_evidence": "#5C6770", "needs_clarification": "#2563EB", "error": "#DC2626",
}
AGENT_COLORS = {"research": "#2563EB", "analyst": "#D97706", "strategy": "#E11D48", "critic": "#7C3AED", "revise": "#E11D48"}
EXAMPLES = [
    "Analyze our sales, research the market, and recommend what to do next.",
    "Why did our revenue drop this month, and what should we do next?",
    "What are our top products in June?",
]


@st.cache_resource
def _prepare_data() -> bool:
    build_database()
    return True


# ---------------------------------------------------------------------------
# Session state, password gate, limits
# ---------------------------------------------------------------------------
st.session_state.setdefault("history", [])
st.session_state.setdefault("runs", 0)
st.session_state.setdefault("question", "")

if config.APP_PASSWORD and not st.session_state.get("authed"):
    st.markdown("### AI Business Intelligence Team")
    entered = st.text_input("Password", type="password")
    if entered:
        if entered == config.APP_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()

with st.spinner("Preparing business data…"):
    _prepare_data()

render_html(
    f"""
    <div class="bi-topbar">
        <div class="bi-brand">{MARK_SVG}
            <div><div class="bi-title">AI Business Intelligence Team</div>
            <div class="bi-tagline">Specialist agents. Shared evidence. One verified report.</div></div></div>
        <span class="bi-pill">{st.session_state.runs}/{config.MAX_RUNS_PER_SESSION} runs</span>
    </div>
    """
)

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
def _use_example(text: str) -> None:
    st.session_state["question"] = text


cols = st.columns(len(EXAMPLES))
for col, example in zip(cols, EXAMPLES):
    col.button(example[:34] + "…", key=f"ex_{example[:12]}", on_click=_use_example, args=(example,))

st.text_area("Business question", key="question", height=90, label_visibility="collapsed",
             placeholder="Ask a business question, e.g. which problems matter most and what to do next.")

have_key = bool(config.OPENAI_API_KEY)
limit_reached = st.session_state.runs >= config.MAX_RUNS_PER_SESSION
if not have_key:
    st.warning("No OPENAI_API_KEY is configured, so the team cannot run. Set it in .env or in the host's secrets.")
if limit_reached:
    st.info("This session has used all of its runs. Reload the page to start a new session.")

if st.button("Run the team", type="primary", disabled=(not have_key or limit_reached)):
    question = st.session_state.question.strip()
    if question:
        with st.spinner("The agents are working…"):
            result = run_team(question, save=config.SAVE_RUNS)
        st.session_state.runs += 1
        st.session_state.history.insert(0, {"question": question, "result": result})
        st.rerun()

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
for item in st.session_state.history:
    result = item["result"]
    status = result["status"]
    log = result.get("log", {})
    badge = (f'<span class="bi-badge" style="background:{STATUS_COLORS.get(status, "#5C6770")}">'
             f'{html.escape(status.replace("_", " "))}</span>')
    counts = {}
    for name in log.get("calls", []):
        counts[name] = counts.get(name, 0) + 1
    chips = "".join(f'<span class="bi-chip" style="color:{AGENT_COLORS.get(n, "#5C6770")};'
                    f'border-color:{AGENT_COLORS.get(n, "#5C6770")}">{html.escape(n)} ×{c}</span>'
                    for n, c in counts.items())
    render_html(f'<div class="bi-card">{badge} {chips}<div class="bi-question">{html.escape(item["question"])}</div></div>')

    if status == "error":
        st.error(result["report"])
    else:
        st.markdown(result["report"])

    with st.expander("Run details (plan, agent statuses, calls, tokens)"):
        st.caption(f"Agents chosen by the router: {', '.join(log.get('steps', [])) or 'none'}")
        for tid, info in log.get("tasks", {}).items():
            detail = info.get("error") or info.get("reason") or ""
            st.markdown(f"- **{tid}**: {info['status']} in {info.get('seconds', 0)}s {detail}")
        if log.get("handoffs"):
            st.caption("Handoffs: " + ", ".join(f"{h['from_task']} → {h['to_task']}" for h in log["handoffs"]))
        llm = log.get("llm") or {}
        st.caption(f"{len(log.get('calls', []))} agent calls · {llm.get('calls', 0)} LLM calls · "
                   f"{llm.get('prompt_tokens', 0)} prompt + {llm.get('completion_tokens', 0)} completion tokens · "
                   f"{log.get('seconds', 0)}s total · {log.get('revisions', 0)} revision(s)")
        if log.get("saved_to"):
            st.caption(f"Run saved to {log['saved_to']}")
    st.markdown("---")
