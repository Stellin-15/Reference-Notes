# ============================================================
# L10: SRE Error Budgets and Toil Reduction
# ============================================================
# WHAT: How SLO-derived ERROR BUDGETS turn "be reliable" into a
#       concrete, actionable POLICY governing release velocity, and
#       TOIL — the specific category of operational work SRE explicitly
#       aims to measure and eliminate over time.
# WHY: This repo's Observability Notes L04 covers the mechanics of
#      SLI/SLO/error-budget alerting. This lesson covers the
#      ORGANIZATIONAL/POLICY layer on top: what an error budget actually
#      LETS an organization decide (ship faster vs slow down), and the
#      toil-reduction discipline that's equally central to the SRE
#      practice but distinct from the alerting mechanics.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
An ERROR BUDGET is the ALLOWED AMOUNT of unreliability, derived directly
from an SLO: a 99.9% availability SLO over 30 days allows roughly 43
minutes of downtime/errors within that window — THAT 43 minutes IS the
error budget. The key organizational insight is what this budget is
FOR: as long as the budget ISN'T exhausted, the team has EARNED the
latitude to ship new features, take calculated risks, and move fast —
reliability work is inherently a TRADEOFF against feature velocity, and
the error budget makes that tradeoff EXPLICIT and QUANTIFIED rather than
an ambient, unstated tension between "ship faster" and "be more
careful." When the budget IS exhausted (or trending toward exhaustion),
this is a concrete, pre-agreed SIGNAL to SLOW DOWN feature releases and
prioritize reliability work instead — not a subjective judgment call
argued fresh each time, but a policy agreed upon BEFORE the pressure of
an actual budget-exhaustion moment.

This POLICY ENFORCEMENT aspect is what separates "we have an SLO
dashboard" from genuinely PRACTICING SRE: an organization that tracks
error budget burn but has NO agreed consequence when it's exhausted
(no actual slowdown in releases, no reallocation of engineering time
toward reliability) is measuring the metric without acting on it — the
metric's entire VALUE comes from the POLICY response it triggers, not
from the number itself.

TOIL is SRE's specific term for a category of operational work: manual,
repetitive, tactical work that scales LINEARLY with service growth
(more traffic/services = proportionally more manual work) and provides
NO LASTING VALUE once completed (unlike, say, writing a piece of
automation, which is a one-time investment that keeps paying off).
Classic toil examples: manually restarting a service after a routine
alert, manually provisioning a resource for every new customer,
manually running the same investigative query every time a specific
alert fires. SRE practice explicitly recommends CAPPING toil (a common
guideline: no more than 50% of an SRE's time should be toil) and
actively measuring/tracking it, specifically because toil left
unmeasured tends to silently GROW over time as a system's operational
surface area grows, crowding out the time needed for genuinely
higher-leverage engineering work (automation, architecture improvements)
that would actually REDUCE future toil.

PRODUCTION USE CASE:
A team's error budget for their core API has been on-track all quarter,
giving them explicit organizational permission to ship an ambitious new
feature with somewhat higher inherent risk than usual — midway through
the quarter, an unrelated infrastructure issue burns 60% of the
remaining budget in one incident, triggering the team's PRE-AGREED
policy: pause new feature releases for two weeks, during which the team
exclusively addresses reliability work (the root cause of the
infrastructure issue, plus a backlog of smaller reliability
improvements) — a decision made WITHOUT debate or negotiation in the
moment, because the policy and its trigger condition were agreed upon
in advance.

COMMON MISTAKES:
- Tracking an error budget/SLO dashboard without any AGREED, ENFORCED
  policy for what happens when the budget is exhausted — this reduces
  error budgets to a vanity metric, since their entire organizational
  value comes from the policy response they trigger, not the number alone.
- Treating EVERY piece of operational work as equally valuable/necessary,
  without explicitly measuring and categorizing TOIL separately from
  higher-leverage engineering work — toil that's never measured tends to
  silently grow unchecked as systems and their operational surface area
  scale up.
- Setting an error budget POLICY (e.g. "freeze releases when budget
  exhausted") without executive/organizational buy-in secured IN
  ADVANCE — when a real budget-exhaustion moment arrives, an unagreed
  policy gets renegotiated under pressure, defeating the entire purpose
  of having decided it calmly, in advance.
"""

from dataclasses import dataclass
from datetime import timedelta


# ------------------------------------------------------------------
# 1. Error budget calculation and burn-rate tracking
# ------------------------------------------------------------------
@dataclass
class ErrorBudget:
    slo_target_pct: float          # e.g. 99.9
    window_days: int                # e.g. 30
    total_downtime_so_far: timedelta

    @property
    def total_allowed_downtime(self) -> timedelta:
        allowed_fraction = 1 - (self.slo_target_pct / 100)
        return timedelta(days=self.window_days) * allowed_fraction

    @property
    def remaining_budget(self) -> timedelta:
        return self.total_allowed_downtime - self.total_downtime_so_far

    @property
    def budget_consumed_pct(self) -> float:
        return (self.total_downtime_so_far / self.total_allowed_downtime) * 100

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_budget <= timedelta(0)


def error_budget_demo():
    budget = ErrorBudget(slo_target_pct=99.9, window_days=30,
                           total_downtime_so_far=timedelta(minutes=25))
    print(f"Total allowed downtime this window: {budget.total_allowed_downtime}")
    print(f"Consumed so far: {budget.total_downtime_so_far} "
          f"({budget.budget_consumed_pct:.1f}% of budget)")
    print(f"Remaining budget: {budget.remaining_budget}")
    print(f"Exhausted: {budget.is_exhausted}")


# ------------------------------------------------------------------
# 2. Policy enforcement — what actually happens at different burn levels
# ------------------------------------------------------------------
def determine_release_policy(budget_consumed_pct: float) -> str:
    """
    A PRE-AGREED policy mapping budget consumption to a concrete action —
    removing subjective, in-the-moment negotiation about whether to slow
    down releases.
    """
    if budget_consumed_pct < 50:
        return "NORMAL — ship features at normal velocity"
    elif budget_consumed_pct < 90:
        return "CAUTION — require extra review on risky changes, monitor closely"
    elif budget_consumed_pct < 100:
        return "AT RISK — feature freeze; reliability work only until budget recovers"
    else:
        return "EXHAUSTED — full feature freeze; all hands on reliability until resolved"


def policy_demo():
    for pct in [20, 65, 95, 105]:
        print(f"  Budget consumed: {pct}% -> Policy: {determine_release_policy(pct)}")


# ------------------------------------------------------------------
# 3. Toil measurement and the 50% cap
# ------------------------------------------------------------------
@dataclass
class WeeklyTimeAllocation:
    engineer: str
    toil_hours: float
    engineering_hours: float   # automation, architecture, feature work

    @property
    def total_hours(self) -> float:
        return self.toil_hours + self.engineering_hours

    @property
    def toil_pct(self) -> float:
        return (self.toil_hours / self.total_hours) * 100 if self.total_hours else 0

    @property
    def exceeds_toil_cap(self) -> bool:
        return self.toil_pct > 50   # the standard SRE guideline


def toil_tracking_demo():
    allocations = [
        WeeklyTimeAllocation("Alex", toil_hours=15, engineering_hours=25),
        WeeklyTimeAllocation("Priya", toil_hours=28, engineering_hours=12),  # over the cap
    ]
    for a in allocations:
        flag = " ⚠ EXCEEDS 50% TOIL CAP" if a.exceeds_toil_cap else ""
        print(f"  {a.engineer}: {a.toil_pct:.0f}% toil{flag}")

    print("\n  Action for anyone exceeding the cap: their NEXT sprint "
          "should prioritize AUTOMATING their highest-frequency toil "
          "task, not just absorbing more of it — the cap exists "
          "specifically to force this reallocation before toil silently "
          "crowds out ALL higher-leverage engineering time.")


TOIL_EXAMPLES = {
    "Classic toil (manual, repetitive, no lasting value)": [
        "Manually restarting a service after a routine, recurring alert",
        "Manually provisioning infrastructure for each new customer onboarding",
        "Manually running the same investigative query every time a specific alert fires",
    ],
    "NOT toil (one-time or high-leverage engineering work)": [
        "Writing automation that eliminates a recurring manual task",
        "Designing a new system architecture",
        "Root-causing and permanently fixing a recurring alert's underlying issue",
    ],
}


if __name__ == "__main__":
    error_budget_demo()
    print()
    policy_demo()
    print()
    toil_tracking_demo()
    print()
    for category, examples in TOIL_EXAMPLES.items():
        print(f"{category}:")
        for ex in examples:
            print(f"  - {ex}")
        print()

"""
PRODUCTION CONTEXT EXAMPLE:
An SRE team's quarterly review reveals one engineer has spent 65% of
their time on toil (mostly manual customer-onboarding provisioning
steps) — exceeding the team's agreed 50% cap. Rather than treating this
as an individual performance issue, the team's PRE-AGREED policy treats
it as a signal to prioritize automating that specific onboarding
workflow in the next sprint — after the automation ships, that
engineer's toil percentage drops to under 20%, freeing meaningfully more
time for the higher-leverage architecture work the team had been
struggling to find time for, a direct, measured payoff of treating the
toil cap as an enforced policy rather than an informal aspiration.
"""
