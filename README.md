# RideOps Support Console (v0)

Internal tool built for the RideOps support case study. It targets one measure: **avoidable handoffs** (escalations that engineering returns to L1 for config or missing information).

![L1 Escalation Gate](gate.png)

Pick a **Role** in the sidebar. Each role sees only its own work (a demo switch, not a login):

| Role | View | Purpose |
|---|---|---|
| L1 agent | L1 Escalation Gate | Tickets with L1 only (filter by agent with "Signed in as"). See how similar tickets ended, link to a known issue, finish a checklist, hand off with a note engineering can act on. Tickets waiting on engineering are read-only. |
| Engineer | Engineering Queue | Tickets handed to engineering, sorted by priority and wait. Read the L1 note, see how the issue ended before, respond. A return goes back to L1, anything else closes it. |
| Support lead | Lead Radar, Diagnosis and plan | Backlog, weekly trend against targets, pilot before/after, agent coaching table, the diagnosis and an impact estimate. |

![Lead Radar](lead-radar.png)

![Engineering Queue](engineering-queue.png)

## What the L1 agent can do
- **Verdict** from historical outcomes of the same issue (or its category when the issue has fewer than 10 escalations).
- **Known-issue matcher**: if engineering already has the same issue open, link the ticket to it instead of raising a new one.
- **Checklist, identifiers and findings** are required before the handoff note unlocks (P1 outage override available).
- **Hand off to Engineering** creates a simulated engineering ID, moves the ticket to "Open - with Engineering" and logs it.
- **New ticket** adds a simulated open ticket to the queue, owned by the agent you are signed in as.

## What the engineer can do
- See the L1 handoff note (full note for tickets handed off in this app) and other open tickets with the same issue.
- **Record response** (simulated): Fixed, Duplicate, How-to, Not reproducible close the ticket. Config issue or Insufficient info send it back to L1 and count as an avoidable handoff.
- Activity log and an updated tickets CSV can be downloaded.

All of this is session-only. Nothing is written to the CSV or to any external system. The Diagnosis view always uses the original file, so session activity never changes the case-study numbers.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Upload `rideops_support_tickets.csv` in the sidebar, or put it at `data/rideops_support_tickets.csv`. A file with the wrong columns is rejected with a message.

## Deploy on Streamlit Community Cloud
1. Push this folder to GitHub. The case data is confidential, so `data/*.csv` is git-ignored: make the repo private, or upload the CSV in the sidebar after deploying.
2. On share.streamlit.io choose **New app**, pick the repo and set the main file to `app.py`.
3. If the repo is private and you want the CSV bundled, remove the `data/*.csv` line from `.gitignore`.

## Metrics
- **Avoidable handoff rate** (primary): escalations returned to L1 as "Config issue" or "Insufficient info", divided by escalations that have an engineering outcome. Target below 15%.
- **Median time to final close, escalated tickets** (outcome).
- **Guardrails**: reopen rate, CSAT, median first response.

## Assumptions
- Checklists and required identifiers are a proposal to validate with engineering.
- Verdicts are historical rates, not a prediction model.
- The impact estimate in the Diagnosis view is indicative. It assumes an avoided return takes the average time of a clean engineering fix, or of an L1-only ticket for the share L1 now resolves, and converts hours saved to fewer open tickets as hours saved ÷ hours in the period.
- Data was pulled on 30 Sep 2026, so the latest partial week is left out of the weekly charts.
