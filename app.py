"""RideOps Support Console (v0)

Internal tool for L1 support agents, the support lead and the head of ops.
Everything is computed live from the ticket CSV: nothing is hard-coded except
the L1 checklists, which are assumptions to be validated with engineering.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="RideOps Support Console", page_icon="🛡️", layout="wide")

DATA_PATH = Path(__file__).parent / "data" / "rideops_support_tickets.csv"
RETURNED = ["Config issue - returned to L1", "Insufficient info - returned to L1"]
OUTCOME_ORDER = [
    "Fixed",
    "Duplicate of known issue",
    "Config issue - returned to L1",
    "Insufficient info - returned to L1",
    "Not a bug - how-to",
    "Not reproducible",
]
OUTCOME_COLORS = ["#2e9e6b", "#3b82c4", "#d9922b", "#c8453b", "#8a94a0", "#b8c0c8"]
MIN_ISSUE_SAMPLE = 10  # below this, fall back to category-level history

CHECKLISTS: dict[str, list[str]] = {
    "Roster / booking not syncing": [
        "Opened the client's booking cutoff and shift config and compared it with the roster date",
        "Confirmed whether the booking was created, edited or cancelled, and by whom",
        "Noted the exact roster date, shift and the booking IDs that are wrong",
        "Checked whether other clients reported the same symptom today",
    ],
    "Live tracking / GPS incorrect": [
        "Got the trip ID and the clock time the location froze or jumped",
        "Checked driver app version, phone data and GPS permission",
        "Compared with another trip by the same cab on the same day",
        "Attached a screenshot of the employee app or the link error",
    ],
    "Report export failing": [
        "Noted report type and date range (ranges over 15 days fail)",
        "Retried once with a shorter range",
        "Searched the known-issue list for this report",
        "Captured the exact error or the loading screenshot",
    ],
    "OTP / boarding issue": [
        "Collected trip ID and employee ID",
        "Confirmed OTP SMS delivery time and the number it went to",
        "Checked whether the driver app shows the trip as started",
        "Attached a screenshot of the invalid OTP message",
    ],
    "Billing / invoice discrepancy": [
        "Noted invoice number, month and the line that looks wrong",
        "Checked the client rate card and the trip list behind that line",
        "Checked whether cancelled trips are billed as dead km by contract",
        "Attached the client's own trip count if they have one",
    ],
    "Employee address / geocode change": [
        "Confirmed the new address and pin location with the client",
        "Checked that the address saved and the geocode moved",
        "Checked upcoming trips already generated with the old pickup",
    ],
    "Cab delay / no-show complaint": [
        "Pulled the trip timeline: assigned, arrived, started",
        "Checked the driver call log and the no-show mark time",
        "Resolved with the client; escalate only for a systemic pattern",
    ],
    "Login / access issue": [
        "Checked user role and active status",
        "Triggered a password reset",
        "Escalate only if the reset fails twice",
    ],
    "How-to / feature request": [
        "Pointed to the help article or gave the steps",
        "Logged feature requests to product, not engineering support",
    ],
    "Driver / vehicle compliance docs": [
        "Checked document expiry dates in the vendor record",
        "Asked the vendor to upload; escalate only if upload fails",
    ],
}
IDENTIFIERS: dict[str, list[str]] = {
    "Roster / booking not syncing": ["Roster date and shift", "Booking ID(s)"],
    "Live tracking / GPS incorrect": ["Trip ID", "Time of freeze or jump (IST)"],
    "Report export failing": ["Report name", "Date range"],
    "OTP / boarding issue": ["Trip ID", "Employee ID"],
    "Billing / invoice discrepancy": ["Invoice number", "Disputed trip ID(s)"],
}
DEFAULT_IDENTIFIERS = ["Trip or reference ID", "Time it happened (IST)"]

st.markdown(
    """
<style>
.block-container {padding-top: 2.2rem; max-width: 1280px;}
.tile {border: 1px solid rgba(128,128,128,.28); border-radius: 8px; padding: 12px 14px;}
.tile small {opacity: .65; text-transform: uppercase; letter-spacing: .06em; font-size: .7rem;}
.tile b {display: block; font-size: 1.55rem; font-variant-numeric: tabular-nums; line-height: 1.25;}
.tile span {opacity: .65; font-size: .78rem;}
.verdict {border-radius: 8px; padding: 14px 16px; border: 1px solid; margin-bottom: 14px;}
.verdict b {display: block; font-size: 1.1rem; margin-bottom: 2px;}
.v-good {background: rgba(46,158,107,.14); border-color: #2e9e6b;}
.v-warn {background: rgba(217,146,43,.14); border-color: #d9922b;}
.v-bad {background: rgba(200,69,59,.14); border-color: #c8453b;}
h1 {font-size: 1.7rem !important;}
</style>
""",
    unsafe_allow_html=True,
)


def tile(label: str, value: str, note: str = "") -> str:
    return f'<div class="tile"><small>{label}</small><b>{value}</b><span>{note}</span></div>'


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy()
    for c in ["created_at", "first_response_at", "first_closed_at", "final_closed_at"]:
        d[c] = pd.to_datetime(d[c])
    d["esc"] = d["escalated_to_eng"].eq("Yes")
    d["returned"] = d["eng_outcome"].isin(RETURNED)
    d["reopened"] = d["reopen_count"] > 0
    d["ttr_h"] = (d["final_closed_at"] - d["created_at"]).dt.total_seconds() / 3600
    d["frt_h"] = (d["first_response_at"] - d["created_at"]).dt.total_seconds() / 3600
    d["is_open"] = d["status"].ne("Closed")
    d["month"] = d["created_at"].dt.to_period("M").astype(str)
    return d


REQUIRED_COLUMNS = [
    "ticket_id", "created_at", "channel", "client_id", "client_name", "client_tier", "category", "priority",
    "description", "assigned_agent", "first_response_at", "escalated_to_eng", "eng_ticket_id", "eng_handoffs",
    "eng_outcome", "status", "first_closed_at", "final_closed_at", "reopen_count", "csat_score",
]


def check_schema(raw: pd.DataFrame) -> list[str]:
    """Return a list of blocking problems (empty list means the file is usable)."""
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        return [f"Missing columns: {', '.join(missing)}"]
    problems = []
    if raw.empty:
        problems.append("The file has no rows.")
    if not set(raw["escalated_to_eng"].dropna().unique()) <= {"Yes", "No"}:
        problems.append("`escalated_to_eng` must contain only Yes or No.")
    try:
        pd.to_datetime(raw["created_at"])
    except Exception:
        problems.append("`created_at` could not be read as dates (expected like 2026-07-02 01:27).")
    return problems


def load() -> pd.DataFrame | None:
    up = st.sidebar.file_uploader("Ticket CSV", type="csv", help="Same columns as rideops_support_tickets.csv")
    raw = None
    if up is not None:
        try:
            raw = pd.read_csv(up)
        except Exception:
            st.error("That file could not be read as a CSV. Please upload `rideops_support_tickets.csv` in its original format.")
            st.stop()
        source = "uploaded file"
    elif DATA_PATH.exists():
        raw = pd.read_csv(DATA_PATH)
        source = "bundled file"
    if raw is None:
        return None
    problems = check_schema(raw)
    if problems:
        st.title("RideOps Support Console")
        st.error("This is not the RideOps ticket file the app expects. Please upload the correct CSV (`rideops_support_tickets.csv`).")
        for p in problems:
            st.markdown(f"- {p}")
        st.caption(f"Columns found in the {source}: {', '.join(map(str, raw.columns))}")
        st.stop()
    d = prepare(raw)
    unknown_cat = sorted(set(d["category"].dropna()) - set(CHECKLISTS))
    unknown_out = sorted(set(d["eng_outcome"].dropna()) - set(OUTCOME_ORDER))
    if unknown_cat or unknown_out:
        st.sidebar.warning(
            "Some values are new to this app and may be left out of checklists or outcome charts: "
            + "; ".join(x for x in [f"categories {unknown_cat}" if unknown_cat else "", f"outcomes {unknown_out}" if unknown_out else ""] if x)
        )
    return d


def weekly(d: pd.DataFrame, snapshot: pd.Timestamp) -> pd.DataFrame:
    rows = []
    start = d["created_at"].min().normalize()
    start += pd.Timedelta(days=(7 - start.weekday()) % 7)  # first Monday
    s = start
    while s + pd.Timedelta(days=7) <= snapshot:
        e = s + pd.Timedelta(days=7)
        w = d[(d["created_at"] >= s) & (d["created_at"] < e)]
        ee = w[w["esc"]]
        open_end = ((d["created_at"] < e) & (d["final_closed_at"].isna() | (d["final_closed_at"] >= e))).sum()
        rows.append(
            {
                "week": s,
                "Created": len(w),
                "Escalated": len(ee),
                "Open at week end": int(open_end),
                "Open ÷ weekly volume": open_end / max(len(w), 1),
                "Avoidable handoff rate %": ee["returned"].mean() * 100 if len(ee) else None,
                "Median final close, escalated (h)": ee["ttr_h"].median() if len(ee) else None,
                "Reopen rate %": w["reopened"].mean() * 100,
                "CSAT": w["csat_score"].mean(),
                "Median first response (h)": w["frt_h"].median(),
            }
        )
        s = e
    return pd.DataFrame(rows)


def line(df: pd.DataFrame, col: str, height: int = 190) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_line(point=True, color="#3b82c4")
        .encode(x=alt.X("week:T", title=None), y=alt.Y(f"{col}:Q", title=None, scale=alt.Scale(zero=False)), tooltip=["week:T", col])
        .properties(height=height, title=col)
    )


# ----------------------------------------------------------------------------
# Escalation history for a ticket type
# ----------------------------------------------------------------------------
def history(d: pd.DataFrame, category: str, desc: str) -> dict:
    issue = d[(d["category"] == category) & (d["description"] == desc)]
    cat = d[d["category"] == category]
    scope, label = (issue, "this exact issue") if issue["esc"].sum() >= MIN_ISSUE_SAMPLE else (cat, "this category")
    esc = scope[scope["esc"]]
    mix = esc["eng_outcome"].value_counts().reindex(OUTCOME_ORDER).fillna(0).astype(int)
    return {
        "issue": issue,
        "scope_label": label,
        "esc_n": len(esc),
        "mix": mix,
        "fixed": mix["Fixed"] / len(esc) if len(esc) else 0,
        "dup": mix["Duplicate of known issue"] / len(esc) if len(esc) else 0,
        "back": (mix[RETURNED].sum() / len(esc)) if len(esc) else 0,
    }


def verdict(h: dict, issue_n: int) -> tuple[str, str, str]:
    if h["esc_n"] == 0:
        return "v-good", "Resolve at L1", f"{issue_n} similar tickets, none needed engineering."
    if h["dup"] >= 0.30:
        return "v-warn", "Link to the known issue before raising a new one", f"{h['dup']:.0%} of escalations like this were duplicates of an open engineering issue."
    if h["back"] >= 0.40:
        return "v-bad", "Complete the checks, then escalate with the full note", f"{h['back']:.0%} of escalations like this came back to L1 as config or missing info, each return adding days."
    if h["fixed"] >= 0.55:
        return "v-good", "Escalate, with a complete note", f"Engineering fixed {h['fixed']:.0%} of these. Send it complete the first time."
    return "v-warn", "Check first, escalate if the checks fail", f"Engineering fixed {h['fixed']:.0%} and returned {h['back']:.0%}."


# ----------------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------------
def session_log() -> list[dict]:
    return st.session_state.setdefault("handoff_log", [])


def apply_session(d: pd.DataFrame) -> pd.DataFrame:
    """Reflect this session's new tickets and handoffs in the data (simulated, session only)."""
    new = st.session_state.get("new_tickets", [])
    log = session_log()
    if not new and not log:
        return d
    d = d.copy()
    if new:
        add = prepare(pd.DataFrame(new)[REQUIRED_COLUMNS])
        d = pd.concat([d, add], ignore_index=True)
    for h in log:
        m = d["ticket_id"] == h["ticket"]
        d.loc[m, "escalated_to_eng"] = "Yes"
        d.loc[m, "esc"] = True
        d.loc[m, "eng_ticket_id"] = h["eng_id"]
        d.loc[m, "eng_handoffs"] = d.loc[m, "eng_handoffs"] + 1
        d.loc[m, "status"] = "Open - with Engineering"
        d.loc[m, "is_open"] = True
    return d


def next_eng_id(d: pd.DataFrame) -> str:
    eng = pd.concat([d["eng_ticket_id"].dropna().astype(str), pd.Series([h["eng_id"] for h in session_log()], dtype=str)])
    return f"ENG-{int(pd.to_numeric(eng.str.extract(r'(\d+)')[0], errors='coerce').max()) + 1}"


def create_ticket(d: pd.DataFrame, snapshot: pd.Timestamp, client: str, category: str, desc: str, priority: str, channel: str) -> None:
    sup_n = int(pd.to_numeric(d["ticket_id"].str.extract(r"(\d+)")[0], errors="coerce").max()) + 1
    c = d[d["client_name"] == client].iloc[0]
    row = {col: None for col in REQUIRED_COLUMNS}
    row.update({
        "ticket_id": f"SUP-{sup_n}", "created_at": snapshot - pd.Timedelta(minutes=1), "channel": channel, "client_id": c["client_id"],
        "client_name": client, "client_tier": c["client_tier"], "category": category, "priority": priority, "description": desc,
        "assigned_agent": "L1 (you)", "escalated_to_eng": "No", "eng_handoffs": 0, "status": "Open - with L1", "reopen_count": 0,
    })
    st.session_state.setdefault("new_tickets", []).append(row)
    st.session_state["last_handoff"] = f"{row['ticket_id']} created for {client}. It is now in the open queue as Open - with L1."


def hand_off(d: pd.DataFrame, ticket: dict, note: str, override: bool) -> None:
    eng_id = next_eng_id(d)
    when = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %H:%M")
    session_log().append({
        "time": when, "ticket": ticket["id"], "eng_id": eng_id, "client": ticket["client"], "category": ticket["category"],
        "priority": ticket["priority"], "owner": ticket["owner"], "override": override,
        "handoff_no": ticket["handoffs"] + 1, "note": note,
    })
    st.session_state["last_handoff"] = f"{ticket['id']} handed off to engineering as {eng_id} at {when} IST. Status is now Open - with Engineering."


def log_section() -> None:
    log = session_log()
    st.divider()
    st.subheader("Handed off this session")
    st.caption("v0 keeps this queue for the current session only. It is not connected to RideOps' engineering system.")
    if not log:
        st.info("No handoffs yet. Complete a ticket's checks above and press Hand off to Engineering.")
        return
    t = pd.DataFrame(log)
    shown = t.rename(columns={"time": "Time (IST)", "ticket": "Ticket", "eng_id": "Eng ticket", "client": "Client", "category": "Category",
                              "priority": "Priority", "owner": "Owner", "override": "Override", "handoff_no": "Handoff #"})
    st.dataframe(shown[["Time (IST)", "Ticket", "Eng ticket", "Client", "Category", "Priority", "Handoff #", "Owner", "Override"]], hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    c1.download_button("Download handoff log (CSV)", t.to_csv(index=False).encode(), "handoff_log.csv", "text/csv")
    updated = st.session_state.get("updated_csv")
    if updated is not None:
        c2.download_button("Download tickets CSV with these changes", updated, "rideops_support_tickets_updated.csv", "text/csv")


def looks_like_text(text: str) -> bool:
    """Light guard against keyboard mashing. It cannot judge whether the findings are true."""
    words = [w.strip(".,;:()!?-").lower() for w in text.split()]
    words = [w for w in words if w]
    if len(words) < 5:
        return False
    plausible = sum(1 for w in words if len(w) <= 14 and any(v in w for v in "aeiou") and not any(w.count(ch) >= 4 for ch in set(w)))
    return plausible / len(words) >= 0.6 and len(set(words)) >= 4


def gate_view(d: pd.DataFrame, snapshot: pd.Timestamp) -> None:
    st.title("L1 Escalation Gate")
    st.caption("Check what happened to similar tickets, finish the checklist, then hand off with a note engineering can act on.")
    if msg := st.session_state.pop("last_handoff", None):
        st.success(msg)
    mode = st.radio("Mode", ["Open tickets", "New ticket"], horizontal=True, label_visibility="collapsed")

    if mode == "Open tickets":
        op = d[d["is_open"]].copy()
        op["age_h"] = (snapshot - op["created_at"]).dt.total_seconds() / 3600
        c1, c2, c3 = st.columns(3)
        cat_f = c1.selectbox("Category", ["All"] + sorted(op["category"].unique()))
        st_f = c2.selectbox("Status", ["All"] + sorted(op["status"].unique()))
        ag_f = c3.selectbox("Agent", ["All"] + sorted(op["assigned_agent"].unique()))
        if cat_f != "All":
            op = op[op["category"] == cat_f]
        if st_f != "All":
            op = op[op["status"] == st_f]
        if ag_f != "All":
            op = op[op["assigned_agent"] == ag_f]
        op["_with_eng"] = op["status"].eq("Open - with Engineering")
        op = op.sort_values(["_with_eng", "eng_handoffs", "age_h"], ascending=[True, False, False])
        if op.empty:
            st.info("No open tickets match these filters.")
            return
        labels = {
            r.ticket_id: f"{r.ticket_id} | {r.priority} | {r.category} | {r.client_name} | {r.age_h:.0f}h old | {r.eng_handoffs} handoffs"
            for r in op.itertuples()
        }
        tid = st.selectbox("Ticket", list(labels), format_func=labels.get)
        t = op[op["ticket_id"] == tid].iloc[0]
        ticket = {
            "id": t.ticket_id, "client": t.client_name, "tier": t.client_tier, "category": t.category,
            "desc": t.description, "priority": t.priority, "channel": t.channel,
            "age": f"{t.age_h:.0f} h", "handoffs": int(t.eng_handoffs), "reopens": int(t.reopen_count),
            "status": t.status, "owner": t.assigned_agent, "outcome": t.eng_outcome if isinstance(t.eng_outcome, str) else "",
        }
    else:
        c1, c2 = st.columns(2)
        category = c1.selectbox("Category", sorted(d["category"].unique()))
        descs = d[d["category"] == category]["description"].value_counts().index.tolist()
        desc = c2.selectbox("Issue", descs)
        c3, c4, c5 = st.columns(3)
        client = c3.selectbox("Client", sorted(d["client_name"].unique()))
        priority = c4.selectbox("Priority", ["P1", "P2", "P3", "P4"], index=2)
        channel = c5.selectbox("Channel", sorted(d["channel"].unique()))
        if st.button("Create ticket", type="primary"):
            create_ticket(d, snapshot, client, category, desc, priority, channel)
            st.rerun()
        st.caption("The ticket is added to the open queue as Open - with L1. Switch to Open tickets to work it and hand it off.")
        return

    st.divider()
    left, right = st.columns([1, 1.15], gap="large")
    h = history(d, ticket["category"], ticket["desc"])

    with left:
        st.subheader(f"{ticket['id']}  ·  {ticket['client']}")
        m = st.columns(4)
        m[0].metric("Priority", ticket["priority"])
        m[1].metric("Age", ticket["age"])
        m[2].metric("Handoffs", ticket["handoffs"])
        m[3].metric("Reopens", ticket["reopens"])
        st.markdown(f"**{ticket['category']}**  \n{ticket['desc']}  \n`{ticket['status']}` · {ticket['tier']} · via {ticket['channel']} · owner {ticket['owner']}")
        if ticket["outcome"].endswith("returned to L1"):
            st.error(f"Engineering returned this ticket: **{ticket['outcome']}**. Do not re-escalate until the checklist and identifiers are complete.")

        cls, title, why = verdict(h, len(h["issue"]))
        st.markdown(f'<div class="verdict {cls}"><b>{title}</b>{why}</div>', unsafe_allow_html=True)

        st.markdown(f"**What happened to {h['scope_label']} before** ({h['esc_n']} escalated tickets)")
        if h["esc_n"]:
            mix = h["mix"].rename_axis("Outcome").reset_index(name="Tickets")
            chart = (
                alt.Chart(mix[mix["Tickets"] > 0])
                .mark_bar()
                .encode(
                    y=alt.Y("Outcome:N", sort=OUTCOME_ORDER, title=None, axis=alt.Axis(labelLimit=260)),
                    x=alt.X("Tickets:Q", title=None),
                    color=alt.Color("Outcome:N", scale=alt.Scale(domain=OUTCOME_ORDER, range=OUTCOME_COLORS), legend=None),
                    tooltip=["Outcome", "Tickets"],
                )
                .properties(height=200)
            )
            st.altair_chart(chart, width="stretch")
        iss = h["issue"]
        k = st.columns(3)
        k[0].metric("Median, resolved at L1", f"{iss[~iss['esc']]['ttr_h'].median():.0f} h" if (~iss["esc"]).any() else "n/a")
        k[1].metric("Median, escalated", f"{iss[iss['esc']]['ttr_h'].median():.0f} h" if iss["esc"].any() else "n/a")
        k[2].metric("CSAT, escalated", f"{iss[iss['esc']]['csat_score'].mean():.1f}" if iss["esc"].any() else "n/a")

    with right:
        key = ticket["id"] + ticket["desc"]
        st.subheader("Before you hand off")
        checks = [st.checkbox(item, key=f"{key}-c{i}") for i, item in enumerate(CHECKLISTS.get(ticket["category"], []))]
        st.markdown("**Identifiers engineering needs**")
        idents = IDENTIFIERS.get(ticket["category"], DEFAULT_IDENTIFIERS)
        cols = st.columns(len(idents))
        vals = [cols[i].text_input(name, key=f"{key}-i{i}") for i, name in enumerate(idents)]
        summary = st.text_area("What you checked and what you saw", key=f"{key}-s", height=100,
                               placeholder="e.g. Cutoff set to 14:00 in config, roster still built at 16:00 for 6 Oct night shift.")
        override = st.checkbox("P1 outage: escalate now, finish the note after", key=f"{key}-o")

        missing = []
        if not all(checks):
            missing.append(f"{checks.count(False)} checklist item(s)")
        if not all(len(v.strip()) >= 3 for v in vals):
            missing.append("identifiers (at least 3 characters each)")
        if len(summary.split()) < 5 or len(summary.strip()) < 25 or not looks_like_text(summary):
            missing.append("investigation summary (a sentence of at least 5 real words)")
        ready = not missing or override

        if ready:
            note = "\n".join(
                [
                    f"ESCALATION {ticket['id']}  |  {ticket['priority']}  |  {ticket['client']} ({ticket['tier']})",
                    f"Category: {ticket['category']}",
                    f"Issue: {ticket['desc']}",
                    f"Previous engineering handoffs: {ticket['handoffs']}",
                    "",
                    *[f"{n}: {v.strip() or '(not provided)'}" for n, v in zip(idents, vals)],
                    "",
                    "Checked at L1:",
                    *[f"  [{'x' if c else ' '}] {item}" for c, item in zip(checks, CHECKLISTS.get(ticket["category"], []))],
                    "",
                    f"L1 findings: {summary.strip() or '(to follow)'}",
                    "",
                    "Client needs: a confirmed cause and a date for a fix or workaround.",
                    "If you return this, please name the one thing you need.",
                ]
            )
            if ticket["status"] == "Open - with L1":
                st.success("Ready to hand off." if not missing else "Override on. Missing: " + ", ".join(missing) + ".")
                st.code(note, language=None, wrap_lines=True)
                if st.button("Hand off to Engineering", type="primary", key=f"{key}-send"):
                    hand_off(d, ticket, note, override and bool(missing))
                    st.rerun()
            else:
                eng_id = next((h["eng_id"] for h in reversed(session_log()) if h["ticket"] == ticket["id"]), None)
                st.info(f"Already with engineering{f' as {eng_id}' if eng_id else ''}. Chase for an ETA instead of escalating again.")
        else:
            st.warning("Handoff note locked. Still needed: " + ", ".join(missing) + ".")


def _gate_footer(d: pd.DataFrame) -> None:
    if session_log():
        st.session_state["updated_csv"] = d[REQUIRED_COLUMNS].to_csv(index=False).encode()
    log_section()


def lead_view(d: pd.DataFrame, snapshot: pd.Timestamp) -> None:
    st.title("Lead Radar")
    st.caption("Backlog, aging and quality for the support lead. The weekly numbers use complete Monday-to-Sunday weeks only.")
    w = weekly(d, snapshot)
    op = d[d["is_open"]]
    esc = d[d["esc"]]
    k = st.columns(5)
    k[0].markdown(tile("Open now", str(len(op)), f"{(op['status'] == 'Open - with Engineering').sum()} with engineering"), unsafe_allow_html=True)
    k[1].markdown(tile("Avoidable handoff rate", f"{esc[esc['eng_outcome'].notna()]['returned'].mean():.0%}", "escalations returned for config or missing info"), unsafe_allow_html=True)
    k[2].markdown(tile("Median close, escalated", f"{esc['ttr_h'].median():.0f} h", f"L1-only: {d[~d['esc']]['ttr_h'].median():.0f} h"), unsafe_allow_html=True)
    k[3].markdown(tile("Reopen rate", f"{d['reopened'].mean():.1%}", "guardrail"), unsafe_allow_html=True)
    k[4].markdown(tile("CSAT", f"{d['csat_score'].mean():.2f}", "guardrail, 1 to 5"), unsafe_allow_html=True)
    st.write("")

    st.subheader("Weekly trend")
    cols = ["Avoidable handoff rate %", "Median final close, escalated (h)", "Reopen rate %", "CSAT", "Median first response (h)", "Open ÷ weekly volume"]
    for row in range(0, len(cols), 3):
        cc = st.columns(3)
        for c, name in zip(cc, cols[row:row + 3]):
            c.altair_chart(line(w, name), width="stretch")
    st.caption("Raw open count follows volume. Open ÷ weekly volume shows whether the system itself is slowing down.")

    st.subheader("Agents")
    rows = []
    for a, x in d.groupby("assigned_agent"):
        ee = x[x["esc"]]
        rows.append({
            "Agent": a, "Tickets": len(x), "Escalation %": x["esc"].mean() * 100,
            "Returned % of escalations": ee[ee["eng_outcome"].notna()]["returned"].mean() * 100 if ee["eng_outcome"].notna().any() else 0,
            "Reopen %": x["reopened"].mean() * 100, "CSAT": x["csat_score"].mean(),
            "Median close (h)": x["ttr_h"].median(),
        })
    ag = pd.DataFrame(rows).sort_values("Reopen %", ascending=False)
    st.dataframe(ag.style.format({c: "{:.0f}" for c in ag.columns if "%" in c or "(h)" in c} | {"CSAT": "{:.2f}"})
                 .map(lambda v: "background-color: rgba(217,146,43,.35)" if v >= 25 else "", subset=["Reopen %"])
                 .map(lambda v: "background-color: rgba(217,146,43,.35)" if v >= 50 else "", subset=["Escalation %", "Returned % of escalations"]),
                 hide_index=True, width="stretch")
    fast = ag.sort_values("Median close (h)").iloc[0]
    st.caption(f"Read this as a coaching aid, not a ranking. {fast['Agent']} closes fastest but is reopened {fast['Reopen %']:.0f}% of the time, "
               f"against {ag[ag['Agent'] != fast['Agent']]['Reopen %'].mean():.0f}% for the others.")

    st.subheader("Open backlog")
    a, b = st.columns(2)
    by_cat = op.groupby(["category", "status"]).size().reset_index(name="Tickets")
    a.altair_chart(alt.Chart(by_cat).mark_bar().encode(
        y=alt.Y("category:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)), x=alt.X("Tickets:Q", title=None),
        color=alt.Color("status:N", title=None, scale=alt.Scale(range=["#3b82c4", "#d9922b"])), tooltip=["category", "status", "Tickets"]
    ).properties(height=280, title="By category"), width="stretch")
    ho = op.groupby("eng_handoffs").size().reset_index(name="Tickets")
    b.altair_chart(alt.Chart(ho).mark_bar(color="#c8453b").encode(
        x=alt.X("eng_handoffs:O", title="Engineering handoffs so far"), y=alt.Y("Tickets:Q", title=None), tooltip=["eng_handoffs", "Tickets"]
    ).properties(height=280, title="By handoffs"), width="stretch")


def diagnosis_view(d: pd.DataFrame, snapshot: pd.Timestamp) -> None:
    st.title("Diagnosis and four-week plan")
    esc = d[d["esc"]]
    m = d.groupby("month").agg(n=("ticket_id", "count"), esc=("esc", "mean"), mean=("ttr_h", "mean"), med=("ttr_h", "median"))
    months = list(m.index)
    first, last = months[0], months[-1]

    def open_at(ts: pd.Timestamp) -> int:
        return int(((d["created_at"] <= ts) & (d["final_closed_at"].isna() | (d["final_closed_at"] > ts))).sum())

    first_end = pd.Period(first).end_time
    o1, o2 = open_at(first_end), open_at(snapshot)
    returned = esc["returned"].sum()
    hours_share = d.loc[d["returned"], "ttr_h"].sum() / d["ttr_h"].sum()
    esc_hours = d.loc[d["esc"], "ttr_h"].sum() / d["ttr_h"].sum()
    not_fixed = (esc["eng_outcome"] != "Fixed").mean()

    st.markdown("### 1. What is driving the backlog")
    k = st.columns(4)
    k[0].markdown(tile("Open tickets", f"{o1} → {o2}", f"{(o2 / o1 - 1):+.0%} end {first} to end {last}"), unsafe_allow_html=True)
    k[1].markdown(tile("Monthly volume", f"{m.loc[first, 'n']:.0f} → {m.loc[last, 'n']:.0f}", f"{(m.loc[last, 'n'] / m.loc[first, 'n'] - 1):+.0%}"), unsafe_allow_html=True)
    k[2].markdown(tile("Mean time to close", f"{m.loc[first, 'mean']:.0f} → {m.loc[last, 'mean']:.0f} h", f"{(m.loc[last, 'mean'] / m.loc[first, 'mean'] - 1):+.0%}"), unsafe_allow_html=True)
    k[3].markdown(tile("Escalation rate", f"{m.loc[first, 'esc']:.0%} → {m.loc[last, 'esc']:.0%}", "support is not escalating more"), unsafe_allow_html=True)
    st.write("")
    st.markdown(
        f"- **Volume grew faster than the system's speed.** Tickets rose {(m.loc[last, 'n'] / m.loc[first, 'n'] - 1):.0%} while the share escalated fell. Open tickets follow volume times time-to-close.\n"
        f"- **Escalation is where the time goes.** {len(esc):,} escalated tickets ({d['esc'].mean():.0%}) have a median close of {esc['ttr_h'].median():.0f} h against {d[~d['esc']]['ttr_h'].median():.0f} h at L1, and hold {esc_hours:.0%} of all ticket-hours. "
        f"{d[d['is_open']]['esc'].mean():.0%} of tickets open today were escalated.\n"
        f"- **{not_fixed:.0%} of escalations ended without an engineering fix.** {returned} came back to L1 as config or missing info. They are {returned / len(d):.0%} of tickets but {hours_share:.0%} of ticket-hours, because each return adds a handoff."
    )
    ho = esc.groupby("eng_handoffs").agg(Tickets=("ticket_id", "count"), Median_close_h=("ttr_h", "median"), CSAT=("csat_score", "mean")).round(1)
    st.dataframe(ho.rename(columns={"Median_close_h": "Median close (h)"}), width="stretch")

    st.markdown("### 2. Testing what the team said")
    karan = d.groupby("assigned_agent").agg(med=("ttr_h", "median"), reopen=("reopened", "mean"), csat=("csat_score", "mean"), n=("ticket_id", "count")).sort_values("med")
    fast = karan.index[0]
    rest = d[d["assigned_agent"] != fast]
    st.table(pd.DataFrame(
        [
            ["Meera: engineering is the problem", "Partly. Escalated tickets are slow, but a third of them wasted handoffs that L1 information would have avoided."],
            ["Meera: agents close in a few hours, so it can be fast", f"{fast} closes fastest (median {karan.loc[fast, 'med']:.0f} h) but is reopened {karan.loc[fast, 'reopen']:.0%} of the time vs {rest['reopened'].mean():.0%} for others, CSAT {karan.loc[fast, 'csat']:.2f} vs {rest['csat_score'].mean():.2f}. Fast here means closed early."],
            ["Sandeep: support escalates what should not reach engineering", f"Supported. {not_fixed:.0%} of escalations were not fixes, and one in three was returned for config or missing information."],
            ["Ritika: bring the open number down", "Open count mostly tracks volume. Targeting it directly rewards early closing. Track handoffs and time to final close instead."],
        ], columns=["Claim", "What the data says"]).set_index("Claim"))

    st.markdown("### 3. How to measure better")
    st.markdown(
        "- **Primary:** avoidable handoff rate (escalations returned for config or missing info). Target: below 15%.\n"
        "- **Outcome:** median time to final close for escalated tickets.\n"
        "- **Guardrails:** reopen rate, CSAT, median first response.\n"
        "- **For leadership:** open tickets shown next to open ÷ weekly volume."
    )

    st.markdown("### 4. Next four weeks")
    st.table(pd.DataFrame(
        [
            ["Week 1", "Validate checklists with the engineering manager. Build a known-issue list for the top roster and report-export problems."],
            ["Week 2", "Pilot the gate with two L1 agents. Handoff note required for every escalation."],
            ["Week 3", "Add a return-reason tag on the engineering side so 'missing info' names the missing thing."],
            ["Week 4", "Review the scorecard. Coaching conversations on early closing and over-escalation, with the pattern, not the ranking."],
        ], columns=["When", "What"]).set_index("When"))
    st.markdown("**Deliberately not doing:** hiring or an engineering SLA (the data points at handoffs first), a close-time target (it rewards early closing), ML auto-triage (the data has one-line descriptions only).")
    st.markdown("**Assumptions and limits:** checklists and identifiers are my proposal and need engineering sign-off. Outcomes are only weakly predicted by the issue text, so verdicts use historical rates, not a model. Data was pulled on 30 Sep, so open counts at the edge are partial.")


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
st.sidebar.markdown("## RideOps Support Console")
st.sidebar.caption("v0 · internal")
base_df = load()
df = apply_session(base_df) if base_df is not None else None
if df is None:
    st.title("RideOps Support Console")
    st.info("Upload the ticket CSV in the sidebar to begin, or place it at `data/rideops_support_tickets.csv`.")
    st.stop()

snapshot = base_df["created_at"].max().normalize() + pd.Timedelta(days=1)
view = st.sidebar.radio("View", ["L1 Escalation Gate", "Lead Radar", "Diagnosis and plan"])

op_now = int(df["is_open"].sum())
st.sidebar.divider()
st.sidebar.metric("Open tickets", op_now)
st.sidebar.metric("Handed off this session", len(session_log()))
if st.session_state.get("new_tickets"):
    st.sidebar.caption(f"{len(st.session_state['new_tickets'])} ticket(s) created this session")
st.sidebar.metric("Avoidable handoff rate", f"{df[df['esc'] & df['eng_outcome'].notna()]['returned'].mean():.0%}", help="Escalations returned to L1 as config or missing info. Target below 15%.")
st.sidebar.caption(f"{len(df):,} tickets · data to {(snapshot - pd.Timedelta(days=1)).date()}")

if view == "L1 Escalation Gate":
    gate_view(df, snapshot)
    _gate_footer(df)
elif view == "Lead Radar":
    lead_view(df, snapshot)
else:
    diagnosis_view(base_df, snapshot)
