# RideOps Support Console (v0)

Internal tool built for the RideOps support case study. Three views:

| View | User | Purpose |
|---|---|---|
| L1 Escalation Gate | L1 agent | See how similar tickets ended, finish a checklist, generate a hand-off note for engineering |
| Lead Radar | Support lead | Backlog, weekly trend of the success measures, agent coaching table |
| Diagnosis and plan | Head of Ops | The numbers behind the diagnosis, the claims tested, the four-week plan |

Everything is computed from the ticket CSV. Upload a CSV in the sidebar, or put it at `data/rideops_support_tickets.csv`.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Push this folder to GitHub. The case data is confidential, so `data/*.csv` is git-ignored: make the repo private, or upload the CSV in the app sidebar after deploying.
2. On share.streamlit.io choose **New app**, pick the repo and set the main file to `app.py`.
3. If the repo is private and you want the CSV bundled, remove the `data/*.csv` line from `.gitignore`.

## Metrics
- **Avoidable handoff rate**: escalations returned to L1 as "Config issue" or "Insufficient info", divided by all escalations. Primary measure.
- **Median time to final close, escalated tickets**: outcome measure.
- **Guardrails**: reopen rate, CSAT, median first response.

## Assumptions
- Checklists and required identifiers are a proposal to validate with engineering.
- Verdicts use historical outcome rates for the issue (or its category when the issue has fewer than 10 escalations). It is not a prediction model.
- Data was pulled on 30 Sep 2026, so the latest partial week is left out of the weekly charts.
