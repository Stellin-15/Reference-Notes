# ============================================================
# L11: On-Call Practices — Rotation Design, Alert Fatigue, Runbooks
# ============================================================
# WHAT: Designing a sustainable on-call rotation, the specific problem
#       of ALERT FATIGUE (and why it's a genuine operational risk, not
#       just an annoyance), escalation policies, and runbooks — the
#       written knowledge that lets an on-call engineer act effectively
#       on a page at 3am without needing deep prior context.
# WHY: L08-L10 covered incident response, postmortems, and error-budget
#      policy. This lesson covers the HUMAN SYSTEM underneath all of
#      that — on-call is how incidents actually get a first responder,
#      and a badly-designed on-call system produces burned-out engineers
#      and slower, worse incident response regardless of how good the
#      incident-command process itself is.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
ON-CALL ROTATION DESIGN balances several competing concerns: FAIRNESS
(rotation duration and frequency distributed evenly across the team,
not falling disproportionately on a few people), SUSTAINABILITY (a
rotation that pages someone every night indefinitely burns that person
out regardless of how "fair" its scheduling is — the actual PAGE
VOLUME/frequency matters as much as who's holding the pager), and
COVERAGE (ensuring someone is ALWAYS reachable, including handling
time zones for a geographically distributed team, and secondary/backup
escalation if the primary doesn't respond).

ALERT FATIGUE is the specific, serious failure mode where an on-call
engineer receives so many LOW-VALUE or FALSE-POSITIVE alerts that they
become DESENSITIZED — acknowledging and dismissing pages reflexively
rather than genuinely investigating each one — which means a GENUINELY
CRITICAL alert, indistinguishable in the moment from the noise, gets the
same reflexive, insufficient attention. This is a DIRECT, measurable
operational risk (a real incident missed or under-responded-to because
it looked like "just another noisy alert"), not merely an engineer-
experience/morale concern, though it's also that. The fix is not "tell
engineers to pay closer attention" — it's rigorously REDUCING alert
volume (this repo's Observability Notes L04 covers designing alerts on
genuine SYMPTOMS with real user impact, not every possible internal
metric deviation) and TUNING thresholds so that an alert firing reliably
means something worth waking up for.

AN ESCALATION POLICY defines what happens if the PRIMARY on-call doesn't
acknowledge a page within a defined time window — automatically
escalating to a SECONDARY on-call, and potentially further up a chain
(a team lead, a different team entirely) if that also goes
unacknowledged. This exists because people are occasionally
unreachable (asleep through a page, a phone issue, genuinely
incapacitated) — a system with NO escalation path can leave a critical
incident with literally nobody responding.

RUNBOOKS are written, step-by-step operational procedures for handling
SPECIFIC, KNOWN alert types — "if alert X fires, first check Y, if Y
shows Z, do this specific remediation" — existing specifically because
an on-call engineer paged at 3am for a system they don't work on daily
should NOT need deep, from-scratch investigative expertise to take a
reasonable first action; a good runbook, linked directly FROM the alert
itself, is the difference between a 5-minute guided response and a
30-minute cold investigation for a well-understood, recurring failure mode.

PRODUCTION USE CASE:
A team redesigns their on-call rotation after noticing high turnover
correlated with on-call burnout: reducing rotation length from 2 weeks
to 1 week (more frequent handoffs, but each stint is shorter and less
draining), auditing and eliminating 40% of their alerts as genuinely
low-value noise (directly reducing page volume and alert fatigue), and
writing runbooks for their 10 most frequently firing alert types —
measurably reducing both average incident response time (runbooks
provide immediate guided action) and reported on-call burnout in a
subsequent team survey.

COMMON MISTAKES:
- Designing an on-call rotation purely around "fair distribution of
  shifts" without considering actual PAGE VOLUME/frequency during those
  shifts — a "fairly" distributed rotation that still pages everyone
  every single night is not actually sustainable, regardless of its scheduling fairness.
- Treating every possible alert as worth paging a human for, rather than
  rigorously distinguishing genuinely actionable, user-impacting alerts
  from informational/low-priority signals that could be a ticket or
  dashboard item instead of a 3am page — this is the direct cause of
  alert fatigue.
- Having NO escalation policy (or one that's never actually tested) —
  discovering during a REAL critical incident that the escalation chain
  doesn't actually work (wrong contact info, an untested integration) is
  a far worse time to discover this than during a planned escalation-policy drill.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta


# ------------------------------------------------------------------
# 1. On-call rotation fairness and sustainability tracking
# ------------------------------------------------------------------
@dataclass
class OnCallShift:
    engineer: str
    start: datetime
    end: datetime
    pages_received: int


def rotation_fairness_report(shifts: list[OnCallShift]) -> dict:
    """Tracks BOTH shift-count fairness AND actual page-volume burden —
    a rotation can be perfectly fair by shift COUNT while still being
    wildly unfair by actual PAGE VOLUME if incidents cluster on specific shifts."""
    by_engineer: dict[str, dict] = {}
    for shift in shifts:
        entry = by_engineer.setdefault(shift.engineer, {"shifts": 0, "total_pages": 0})
        entry["shifts"] += 1
        entry["total_pages"] += shift.pages_received

    for engineer, data in by_engineer.items():
        data["avg_pages_per_shift"] = data["total_pages"] / data["shifts"]

    return by_engineer


def rotation_demo():
    shifts = [
        OnCallShift("Alex", datetime(2026, 1, 1), datetime(2026, 1, 8), pages_received=2),
        OnCallShift("Priya", datetime(2026, 1, 8), datetime(2026, 1, 15), pages_received=14),  # a bad week
        OnCallShift("Alex", datetime(2026, 1, 15), datetime(2026, 1, 22), pages_received=1),
        OnCallShift("Sam", datetime(2026, 1, 22), datetime(2026, 1, 29), pages_received=3),
    ]
    report = rotation_fairness_report(shifts)
    for engineer, data in report.items():
        print(f"  {engineer}: {data['shifts']} shifts, "
              f"{data['total_pages']} total pages, "
              f"{data['avg_pages_per_shift']:.1f} avg pages/shift")
    print("  -> equal SHIFT COUNT (fair scheduling) does NOT mean equal "
          "BURDEN — Priya's single bad week may warrant a follow-up "
          "(was this a genuine incident spike, or an alert-tuning gap "
          "that needs fixing before her NEXT rotation?).")


# ------------------------------------------------------------------
# 2. Alert fatigue — measuring signal-to-noise, not just volume
# ------------------------------------------------------------------
@dataclass
class AlertRecord:
    alert_type: str
    was_actionable: bool   # did this alert lead to a REAL remediation action


def alert_signal_to_noise_report(alerts: list[AlertRecord]) -> dict[str, float]:
    """
    For EACH alert type, what fraction of firings were actually
    actionable — a LOW ratio identifies specific alert types that are
    prime candidates for tuning/elimination, rather than treating
    'reduce alert fatigue' as a vague, unmeasurable goal.
    """
    by_type: dict[str, list[bool]] = {}
    for alert in alerts:
        by_type.setdefault(alert.alert_type, []).append(alert.was_actionable)

    return {
        alert_type: sum(actionable_list) / len(actionable_list)
        for alert_type, actionable_list in by_type.items()
    }


def alert_fatigue_demo():
    alerts = (
        [AlertRecord("high_cpu", True)] * 3 + [AlertRecord("high_cpu", False)] * 17 +
        [AlertRecord("payment_failure_spike", True)] * 8 + [AlertRecord("payment_failure_spike", False)] * 1
    )
    report = alert_signal_to_noise_report(alerts)
    for alert_type, actionable_ratio in report.items():
        flag = " <- LOW SIGNAL, candidate for tuning/removal" if actionable_ratio < 0.3 else ""
        print(f"  {alert_type}: {actionable_ratio:.0%} of firings were actually actionable{flag}")


# ------------------------------------------------------------------
# 3. Escalation policy
# ------------------------------------------------------------------
@dataclass
class EscalationPolicy:
    primary: str
    secondary: str
    escalation_timeout: timedelta
    manager_escalation: str


def simulate_escalation(policy: EscalationPolicy, primary_acked: bool, minutes_elapsed: int) -> str:
    if primary_acked:
        return f"Acknowledged by primary ({policy.primary}) — no escalation needed"
    if minutes_elapsed >= policy.escalation_timeout.total_seconds() / 60:
        return f"ESCALATED to secondary ({policy.secondary}) after {minutes_elapsed} min unacknowledged"
    return f"Still waiting on primary ({policy.primary}), {minutes_elapsed} min elapsed"


# ------------------------------------------------------------------
# 4. Runbooks — guided, immediate first action
# ------------------------------------------------------------------
RUNBOOK_EXAMPLE = """
## Runbook: High Database Connection Pool Utilization Alert

**Alert fires when:** connection pool utilization > 90% for 5+ minutes

**Immediate first steps (do these BEFORE deep investigation):**
1. Check the current connection count: `SELECT count(*) FROM pg_stat_activity;`
2. If count is near the configured max, check for LONG-RUNNING queries
   holding connections: `SELECT pid, now() - query_start AS duration, query
   FROM pg_stat_activity ORDER BY duration DESC LIMIT 10;`
3. If a specific query has been running > 10 minutes and matches a known
   pattern (see "Known long-running query patterns" below), it is
   generally safe to terminate it: `SELECT pg_terminate_backend(<pid>);`

**If the above doesn't resolve it within 10 minutes:**
   Escalate to the Database team's on-call (see escalation policy) —
   do NOT continue investigating alone past this point for this specific alert type.

**Known long-running query patterns:** [links to specific documented cases]
**Related dashboards:** [links]
**Last updated:** 2026-01-10 by the DB team, after INC-2025-0891
"""


if __name__ == "__main__":
    rotation_demo()
    print()
    alert_fatigue_demo()

    print("\n--- Escalation simulation ---")
    policy = EscalationPolicy("Alex", "Priya", timedelta(minutes=10), "Engineering Manager")
    for minutes in [3, 8, 12]:
        print(f"  {simulate_escalation(policy, primary_acked=False, minutes_elapsed=minutes)}")

    print(RUNBOOK_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A team's alert signal-to-noise audit reveals their "high_cpu" alert is
actionable only 15% of the time it fires — most firings are brief,
self-resolving spikes with no real impact — while their
"payment_failure_spike" alert is actionable 89% of the time. Tuning the
high-CPU alert's threshold/duration requirement (rather than removing it
entirely) cuts its firing frequency by 70% with no loss of genuine
signal, directly reducing the on-call engineer's total page volume and,
per the rotation fairness tracking, measurably improving reported
on-call sustainability in the team's next retrospective.
"""
