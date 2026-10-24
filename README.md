<p align="center">
  <img src="assets/banner.svg" alt="AI Multi-Agent System Banner" width="100%"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white" alt="Streamlit"/>
  <img src="https://img.shields.io/badge/Pydantic-Structured%20Handoffs-e92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic"/>
  <img src="https://img.shields.io/badge/Multi--Agent-Orchestrated-10b981?style=flat-square" alt="Multi-Agent"/>
  <img src="https://img.shields.io/badge/Critic-Verified%20Reports-2563eb?style=flat-square" alt="Critic Verified"/>
  <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License"/>
  <img src="https://img.shields.io/badge/Status-In%20Progress-f59e0b?style=flat-square" alt="Status"/>
  <img src="https://img.shields.io/badge/Last%20Commit-Week%209-6366f1?style=flat-square" alt="Last Commit"/>
</p>

<p align="center">
  A team of specialised AI agents — Research, Analyst, Strategy and Critic — coordinated by an Orchestrator, that investigate a business question together and produce one evidence-checked report.<br/>
  Ninth deliverable of a <b>90-day AI Engineering roadmap</b> (Week 9, Days 57–63).
</p>

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Project Status](#-project-status)
- [The Team](#-the-team)
- [Architecture](#️-architecture)
- [Design Principles](#-design-principles)
- [Demo](#-demo)
- [Installation](#️-installation)
- [How to Run](#️-how-to-run)
- [Evaluation Plan](#-evaluation-plan)
- [Folder Structure](#-folder-structure)
- [Limitations](#️-limitations)
- [Future Improvements](#-future-improvements)
- [Roadmap Context](#-roadmap-context)
- [Author](#-author)
- [License](#-license)

---

## 📖 Overview

**AI Multi-Agent System** (working title: *AI Business Intelligence Team*) takes a request such as:

> "Analyze this business, identify its biggest problems, research the market, and recommend what it should do next."

Instead of one agent doing everything, the work is split between agents that each own one responsibility, use only their own tools, and hand structured results to the next agent through shared state. An Orchestrator decides who works when, and a Critic checks the final claims against the evidence before the report is released.

It reuses the ideas from Week 8's Business Agent (SQLite business data, grounded analysis, an honest "insufficient evidence" fallback), but the architecture is now multi-agent.

This is **Week 9** of a structured 90-day AI Engineering roadmap.

---

## 🚧 Project Status

This repository is being built day by day. The table shows what is done and what is planned; it is updated as each day lands, and nothing is marked done until it has been tested.

| Day | Topic | Build | Status |
|---|---|---|---|
| 57 | Multi-agent fundamentals | Two specialised agents with different responsibilities | ⬜ Planned |
| 58 | Roles & structured communication | Research Agent → Analyst Agent handoff (Pydantic schemas) | ⬜ Planned |
| 59 | Orchestration & workflow patterns | Orchestrator that routes tasks to the right agents | ⬜ Planned |
| 60 | Shared memory, state & context | Workflow where each agent uses earlier findings | ⬜ Planned |
| 61 | Critic, verification & recovery | Critic that flags unsupported claims and requests revisions | ⬜ Planned |
| 62 | Full integration | Complete AI Business Intelligence Team | ⬜ Planned |
| 63 | Evaluation & deployment | Tests, evaluation dataset, documented limitations, deployment | ⬜ Planned |

---

## 👥 The Team

Each agent has a distinct responsibility and a limited set of tools.

| Agent | Responsibility | Works with | Produces |
|---|---|---|---|
| **Orchestrator** | Plans the task, routes work, manages shared state, combines results | Shared state | Execution plan + final report |
| **Research Agent** | Collects external information about the market | Web search (optional, free tier) | Sourced external evidence |
| **Analyst Agent** | Analyses the company's own business data | SQLite business database | Numeric findings |
| **Strategy Agent** | Evaluates findings and proposes recommendations | Findings from the other agents | Specific, evidence-linked recommendations |
| **Critic Agent** | Checks evidence, accuracy and missing information | The draft report + evidence | Approval, or a list of unsupported claims to revise |

---

## 🏗️ Architecture

```
User Request
     ↓
Orchestrator Agent
Planning · Routing · Shared State
     ↓
┌──────────────────┬──────────────────┬──────────────────┐
│  Research Agent  │  Analyst Agent   │  Strategy Agent  │
│ External evidence│  Business data   │ Recommendations  │
└──────────────────┴──────────────────┴──────────────────┘
     ↓
Critic Agent — Verification
     ↓  (revise if claims are unsupported, within a retry limit)
Evidence-Based Final Report
```

---

## 🧭 Design Principles

These are the rules the project is built around:

- **Concepts first.** Each day starts with what it is, why it matters, and how it works, before any code.
- **One responsibility per agent.** An agent only exists if it does something the others do not.
- **Simple first.** Start with a simple sequential workflow; add parallel execution or retries only where they genuinely help.
- **Free-tier friendly.** No paid framework or credit card is needed to follow the project.
- **Verify the collaboration.** The project does not claim agents collaborated correctly unless the handoffs, outputs and failure cases have actually been tested.
- **No invented facts.** If the evidence does not support a conclusion, the report says so.

---

## 🎥 Demo

*(Screenshots will be added when the full system is integrated — see `assets/screenshots/`)*

---

## 🛠️ Installation

```bash
# 1. Clone the repository
git clone https://github.com/Hamna-Munir/09-AI-Multi-Agent-System.git
cd 09-AI-Multi-Agent-System

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate      # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env          # On Windows: copy .env.example .env
# then add your Groq/LLM API key (OPENAI_API_KEY, starts with gsk_)
# TAVILY_API_KEY is optional — only needed for the Research Agent's web search
```

---

## ▶️ How to Run

> The commands below become available as the days land (the Streamlit app arrives on Day 62).

```bash
# Run the Streamlit app
streamlit run src/app.py
# or: python -m streamlit run src/app.py

# Run the test suite
pytest
```

---

## 🧪 Evaluation Plan

Day 63 evaluates the system on an evaluation dataset (`evaluation/evaluation.csv`). Planned checks:

| Area | What is checked |
|---|---|
| Coordination | Do handoffs between agents carry the right data? |
| Tool selection | Does each agent use only its own, correct tools? |
| Evidence quality | Is every claim in the report backed by evidence? |
| Failure recovery | What happens on tool errors, timeouts, and conflicting results? |
| Latency | How long does a full run take? |
| Cost | How many LLM calls (and tokens) does one report need? |

Results will be published here once they have been measured.

---

## 📂 Folder Structure

```
09-AI-Multi-Agent-System/
│
├── README.md
├── LICENSE
├── .gitignore
├── requirements.txt
├── .env.example
│
├── src/
│   ├── app.py
│   ├── orchestrator.py
│   ├── state.py
│   ├── agents/
│   │   ├── research_agent.py
│   │   ├── analyst_agent.py
│   │   ├── strategy_agent.py
│   │   └── critic_agent.py
│   ├── tools.py
│   ├── schemas.py
│   ├── prompts.py
│   └── config.py
│
├── data/
├── tests/
│
├── evaluation/
│   └── evaluation.csv
│
├── notes/
│   ├── day-57.md
│   ├── day-58.md
│   ├── day-59.md
│   ├── day-60.md
│   ├── day-61.md
│   ├── day-62.md
│   └── day-63.md
│
├── docs/
│
├── assets/
│   ├── banner.svg
│   └── screenshots/
│
└── journal.md
```

---

## ⚠️ Limitations

The final limitations will be documented on Day 63, after testing. Known up front:

- Multi-agent systems cost more LLM calls than a single agent, so a run is slower and uses more of a free-tier quota.
- A Critic that is itself an LLM can miss errors; it reduces unsupported claims but does not guarantee none.
- External research depends on an optional search API, and results vary in quality.

---

## 🚀 Future Improvements

- [ ] Parallel execution of independent agents (Research and Analyst)
- [ ] Persistent memory across runs
- [ ] Human-in-the-loop approval before the final report is released
- [ ] Support for uploading a company's own CSV files
- [ ] Export the final report as PDF/Word

---

## 🧭 Roadmap Context

This project is **Week 9** of a 90-day AI Engineering roadmap:

| Week | Project | Days |
|---|---|---|
| 7 | AI Meeting Agent | 43–49 |
| 8 | AI Business Agent | 50–56 |
| **9** | **AI Multi-Agent System** | **57–63** |

---

## 👩‍💻 Author

**Hamna Munir**
Software Engineering & AI/ML Student | Building deployable AI/ML projects

- GitHub: [@Hamna-Munir](https://github.com/Hamna-Munir)
- Hugging Face: [@Hamna27](https://huggingface.co/Hamna27)

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
