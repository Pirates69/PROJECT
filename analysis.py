"""Reproduces every number used in the RideOps write-up directly from the ticket CSV.

Usage:  python analysis.py [path/to/rideops_support_tickets.csv]
Defaults to data/rideops_support_tickets.csv. Prints one section per claim in the write-up.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RETURNED = ["Config issue - returned to L1", "Insufficient info - returned to L1"]
path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data" / "rideops_support_tickets.csv"

d = pd.read_csv(path)
for c in ["created_at", "first_response_at", "first_closed_at", "final_closed_at"]:
    d[c] = pd.to_datetime(d[c])
d["esc"] = d["escalated_to_eng"].eq("Yes")
d["returned"] = d["eng_outcome"].isin(RETURNED)
d["reopened"] = d["reopen_count"] > 0
d["ttr_h"] = (d["final_closed_at"] - d["created_at"]).dt.total_seconds() / 3600
d["first_close_h"] = (d["first_closed_at"] - d["created_at"]).dt.total_seconds() / 3600
d["frt_h"] = (d["first_response_at"] - d["created_at"]).dt.total_seconds() / 3600
d["month"] = d["created_at"].dt.strftime("%Y-%m")
d["is_open"] = d["status"].ne("Closed")
snapshot = d["created_at"].max().normalize() + pd.Timedelta(days=1)
esc = d[d["esc"]]


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


section("0. Data")
print(f"{len(d):,} tickets, {d['created_at'].min().date()} to {d['created_at'].max().date()}, {d['client_id'].nunique()} clients, {d['assigned_agent'].nunique()} agents")
print(d["status"].value_counts().to_string())

section("1. Open tickets and what drives them (the '+60%' and why)")
for label, ts in [("end of Jul", pd.Timestamp("2026-07-31 23:59")), ("end of Aug", pd.Timestamp("2026-08-31 23:59")), ("end of Sep", snapshot)]:
    n = ((d["created_at"] <= ts) & (d["final_closed_at"].isna() | (d["final_closed_at"] > ts))).sum()
    print(f"open at {label}: {n}")
m = d.groupby("month").agg(tickets=("ticket_id", "count"), escalation_rate=("esc", "mean"), mean_close_h=("ttr_h", "mean"),
                           median_close_h=("ttr_h", "median"), median_first_response_h=("frt_h", "median"))
print(m.round(2).to_string())
print("\nmedian close of escalated tickets by month (h):")
print(d[d["esc"]].groupby("month")["ttr_h"].median().round(1).to_string())
print(f"volume change Jul to Sep: {m['tickets'].iloc[-1] / m['tickets'].iloc[0] - 1:+.0%}")
print(f"mean close time change Jul to Sep: {m['mean_close_h'].iloc[-1] / m['mean_close_h'].iloc[0] - 1:+.0%}")
print("\ntickets by category and month:")
print(pd.crosstab(d["category"], d["month"]).to_string())

section("2. Escalation is where the time goes")
print(f"escalated: {len(esc)} ({d['esc'].mean():.1%} of tickets)")
print(f"median close, escalated: {esc['ttr_h'].median():.1f} h   L1 only: {d[~d['esc']]['ttr_h'].median():.1f} h")
print(f"share of all ticket-hours held by escalated tickets: {esc['ttr_h'].sum() / d['ttr_h'].sum():.1%}")
op = d[d["is_open"]]
print(f"open tickets today that were escalated: {op['esc'].sum()} of {len(op)} ({op['esc'].mean():.0%})")

section("3. Engineering outcomes and handoffs")
print(esc["eng_outcome"].value_counts().to_string())
print(f"\nnot fixed by engineering: {(esc['eng_outcome'] != 'Fixed').mean():.1%} ({(esc['eng_outcome'] != 'Fixed').sum()} of {len(esc)})")
ret = d[d["returned"]]
print(f"returned to L1 for config or missing info: {len(ret)} = {len(ret) / len(esc):.1%} of escalations (avoidable handoff rate)")
print(f"returned tickets are {len(ret) / len(d):.1%} of tickets but {ret['ttr_h'].sum() / d['ttr_h'].sum():.1%} of ticket-hours")
print("\nby number of engineering handoffs:")
print(esc.groupby("eng_handoffs").agg(tickets=("ticket_id", "count"), median_close_h=("ttr_h", "median"), reopen=("reopened", "mean"), csat=("csat_score", "mean")).round(2).to_string())
print(f"\nCSAT: no escalation {d[~d['esc']]['csat_score'].mean():.2f}, escalated {esc['csat_score'].mean():.2f}")
print("\nduplicates of a known issue, by category:")
print(esc[esc["eng_outcome"] == "Duplicate of known issue"]["category"].value_counts().to_string())

section("4. Agents (what the team said, tested)")
a = d.groupby("assigned_agent").agg(tickets=("ticket_id", "count"), escalation_rate=("esc", "mean"), reopen_rate=("reopened", "mean"),
                                    csat=("csat_score", "mean"), median_close_h=("ttr_h", "median"), median_first_close_h=("first_close_h", "median"))
a["returned_share_of_escalations"] = esc.groupby("assigned_agent")["returned"].mean()
a["not_fixed_share_of_escalations"] = esc.groupby("assigned_agent")["eng_outcome"].apply(lambda s: (s != "Fixed").mean())
print(a.round(2).sort_values("median_close_h").to_string())
fast = a["median_close_h"].idxmin()
rest = d[d["assigned_agent"] != fast]
print(f"\nfastest closer: {fast}. reopened {d[d['assigned_agent'] == fast]['reopened'].mean():.1%} vs {rest['reopened'].mean():.1%} for the rest; CSAT {a.loc[fast, 'csat']:.2f} vs {rest['csat_score'].mean():.2f}")
print("\nreopens and CSAT:")
print(d.groupby("reopen_count").agg(tickets=("ticket_id", "count"), csat=("csat_score", "mean")).round(2).to_string())
print("\nhighest escalation rate agent by category:")
for ag in ["Rahul T"]:
    x = d[d["assigned_agent"] == ag]
    print(ag, x.groupby("category")["esc"].agg(["size", "mean"]).round(2).to_string())

section("5. How well does the issue text predict the engineering outcome?")
big = esc.groupby(["category", "description"]).filter(lambda x: len(x) >= 10)
g = big.groupby(["category", "description"])["eng_outcome"].agg(lambda s: s.value_counts(normalize=True).iloc[0])
print(f"{big.groupby(['category', 'description']).ngroups} issues have 10 or more escalations.")
print(f"share of the most common outcome within those issues: min {g.min():.0%}, median {g.median():.0%}, max {g.max():.0%} (100% would mean fully predictable)")
cat = esc.groupby("category")["eng_outcome"].agg(lambda s: s.value_counts(normalize=True).iloc[0])
print("by category, share of the most common outcome:")
print(cat.round(2).to_string())

section("6. Impact estimate (matches the Diagnosis view defaults: target 15%, L1 resolves 50%)")
cur = esc[esc["eng_outcome"].notna()]["returned"].mean()
target, p_l1 = 0.15, 0.5
fixed1 = d[(d["eng_outcome"] == "Fixed") & (d["eng_handoffs"] == 1)]["ttr_h"].mean()
l1_mean = d[~d["esc"]]["ttr_h"].mean()
avoided = len(ret) * max(1 - target / cur, 0)
after_h = p_l1 * l1_mean + (1 - p_l1) * fixed1
saved = avoided * (ret["ttr_h"].mean() - after_h)
period_h = (snapshot - d["created_at"].min().normalize()).total_seconds() / 3600
avg_open = d["ttr_h"].sum() / period_h
print(f"current rate {cur:.1%}; returned tickets {len(ret)}; avoided {avoided:.0f}")
print(f"mean close of a returned ticket {ret['ttr_h'].mean():.0f} h -> about {after_h:.0f} h (clean fix {fixed1:.0f} h, L1-only {l1_mean:.0f} h)")
print(f"ticket-hours saved {saved:,.0f} over {period_h:,.0f} h => {saved / period_h:.1f} fewer open tickets on average, {saved / period_h / avg_open:.0%} of an average backlog of {avg_open:.0f}")
