# Project Health Reporting Agent

AI Engineer Intern technical assignment: an explainable system that reads project plans, determines project RAG health, explains the evidence in plain English, handles incomplete/messy data, produces weekly outputs, and synthesizes portfolio risks into a 6-slide executive presentation.

## Assignment coverage

| Requirement | Implementation |
|---|---|
| One-page RAG methodology | `docs/One_Page_RAG_Methodology.pdf` and `.docx` |
| Working agent | `src/health_agent.py` |
| Run instructions | This README + `run_windows.bat` |
| Sample weekly outputs | `outputs/weekly_reports/` |
| Machine-readable outputs | `outputs/json/` |
| Monthly executive deck | `presentation/Monthly_Executive_Project_Health_Synthesis.pptx` |
| Messy-data handling | Defensive parsing, confidence, Unknown handling |
| Weekly scheduling bonus | CLI is scheduler-ready |
| Security/reliability review | `SECURITY_AND_RELIABILITY.md` |

## Design decision

**Deterministic rules own the RAG decision; AI is used only as an optional narrative layer.**

This prevents an LLM from silently changing project health. Every status is traceable to measurable evidence. The output includes a `status_driver` so a reviewer can see whether the result came from a weighted threshold or an explicit safeguard/override.

## Architecture

`Excel inputs → validation → schema normalization → signal extraction → weighted score → safeguards/overrides → plain-English reasoning → weekly JSON/report → monthly portfolio synthesis`

## Final RAG logic

- **Green:** weighted risk score 0–27 and no safeguard/override.
- **Amber:** weighted score 28–54, any critical overdue task, any on-hold task, or **20+ overdue open tasks**.
- **Red:** weighted score 55–100, **3+ critical overdue tasks**, or **8+ severe schedule variances (≤ -10 days)**.
- Missing budget or sentiment is **Unknown**, never automatically Green.

The absolute overdue safeguard prevents a large project from diluting a material number of overdue tasks.

## Sample results (reporting date: 2026-07-08)

- **Project Plan B:** AMBER, risk score 20.4. Driver: `Absolute overdue safeguard: 42 overdue open task(s)`.
- **S2P Project:** RED, risk score 38.2. Driver: `Critical override: 121 severe variance task(s)`.

The second project is Red below the normal score threshold because severe variance evidence triggers an explicit override. This is intentional and is stated in the output.

## Run locally

Requirements: Python 3.10+.

```bash
python -m pip install -r requirements.txt
python src/health_agent.py "data/Project Plan B(2).xlsx" "data/S2P Project(2).xlsx" --as-of 2026-07-08 --out outputs/run
```

Windows users can also use `run_windows.bat`.

## Run in Google Colab

Upload this repository ZIP, extract it, enter the extracted folder, install requirements, and run:

```python
!pip install -q -r requirements.txt
!python src/health_agent.py   "data/Project Plan B(2).xlsx"   "data/S2P Project(2).xlsx"   --as-of 2026-07-08   --out outputs/colab_results
```

## Prove the agent is dynamic

Run the same plans with a different reporting date:

```bash
python src/health_agent.py "data/Project Plan B(2).xlsx" "data/S2P Project(2).xlsx" --as-of 2025-01-01 --out outputs/earlier_date
```

Project Plan B changes because overdue counts are date-dependent. The S2P project remains Red because its severe-variance override is independent of the reporting-date overdue count.

## Graceful handling and security

The agent:
- accepts only local `.xlsx` files;
- validates file size, row count, and required columns;
- parses dates and variance values defensively;
- never executes workbook macros, scripts, formulas, links, or shell commands;
- sanitizes output filenames;
- writes strict JSON atomically;
- isolates file failures so one bad workbook does not stop other valid files;
- does not require an API key or send project data over the network.

See `SECURITY_AND_RELIABILITY.md` for details.

## Weekly scheduling bonus

The CLI can be invoked by Windows Task Scheduler, cron, GitHub Actions, or a cloud scheduler. A production deployment should pin dependencies with hashes, run with least privilege, use encrypted storage, and add monitoring/audit logs.

## Repository structure

```text
project-health-reporting-agent/
├── src/health_agent.py
├── data/
├── docs/
├── outputs/
│   ├── json/
│   └── weekly_reports/
├── presentation/
├── tests/
├── README.md
├── SECURITY_AND_RELIABILITY.md
├── FINAL_VALIDATION_REPORT.txt
├── requirements.txt
└── run_windows.bat
```

## Limitations

Budget health cannot be calculated when budget/actual/EAC fields are absent; it remains Unknown. Keyword-based sentiment is a weak signal and should be human-reviewed. No software can be guaranteed to survive every hardware, OS, storage, or dependency failure; this implementation is designed to fail safely and preserve valid outputs.
