# ============================================================
# L09: Postmortems and Blameless Culture
# ============================================================
# WHAT: How to write a postmortem that actually PREVENTS recurrence —
#       the 5 Whys root-cause technique, action item tracking with real
#       accountability, and why BLAMELESS framing isn't just a nicety
#       but a structural requirement for postmortems to surface truthful
#       information at all.
# WHY: L08 covered RESPONDING to an incident. This lesson covers what
#      happens AFTER — the difference between an organization that
#      genuinely learns from incidents (fewer repeat failures over time)
#      and one that just moves on until the same failure recurs.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
BLAMELESS CULTURE is a structural, not just cultural-nicety, requirement
for effective postmortems: if engineers fear PERSONAL blame/punishment
for mistakes surfaced during a postmortem, they will — rationally,
self-protectively — omit or soften details that reflect poorly on
themselves, and the postmortem's root-cause analysis becomes
SYSTEMATICALLY LESS ACCURATE as a direct result. A blameless postmortem
explicitly frames the investigation around "what in our SYSTEMS AND
PROCESSES allowed this to happen" rather than "who made the mistake" —
this isn't about avoiding accountability, it's a recognition that a
SINGLE HUMAN ERROR is rarely the true root cause; the more useful
question is why the surrounding system (monitoring, testing, review
process, tooling) didn't catch or prevent that human error from causing
real impact.

THE 5 WHYS TECHNIQUE is a simple, disciplined way to drive PAST the
surface-level, first explanation toward the actual systemic root cause
— repeatedly asking "why did THAT happen" (typically five times,
though the exact count is illustrative, not a strict rule) until you
reach a cause that's genuinely actionable at the SYSTEM level, not just
"an engineer made a typo" (which is rarely fixable — humans will always
occasionally make typos; the fixable question is why nothing caught it
before it reached production).

ACTION ITEMS from a postmortem must have REAL ACCOUNTABILITY to actually
get done — a postmortem's action items list is, in practice, often where
good intentions go to die without: a specific OWNER (not "the team"), a
specific DEADLINE, and — critically — a TRACKING mechanism ensuring
someone actually checks whether action items were completed weeks/
months later, not just filed and forgotten. An organization's genuine
commitment to learning from incidents is measurable by its postmortem
ACTION ITEM COMPLETION RATE, not by how thorough any individual
postmortem document reads.

PRODUCTION USE CASE:
A postmortem for a database outage superficially concludes "an engineer
ran a migration without a maintenance window" — pushing past this with
5 Whys reveals: why wasn't there a maintenance-window requirement
enforced in the deployment tooling itself (a SYSTEM gap, not a human
error), why didn't the migration's expected impact get caught in staging
(a testing environment gap), and why wasn't there an automated rollback
triggered by the resulting error rate spike (a monitoring/automation
gap) — three DIFFERENT, genuinely actionable system-level fixes, none
of which is "tell the engineer to be more careful," which fixes nothing
structurally.

COMMON MISTAKES:
- Writing a postmortem that names and focuses on WHO made a mistake
  rather than WHAT in the surrounding system allowed that mistake to
  cause real impact — beyond being demoralizing, this actively degrades
  the ACCURACY of future postmortems, since people learn to protect
  themselves rather than disclose fully.
- Stopping the root-cause analysis at the FIRST plausible explanation
  ("the deploy caused it") instead of continuing to ask "why" until
  reaching a genuinely systemic, actionable cause — a shallow root cause
  analysis produces shallow, ineffective action items.
- Creating action items with no OWNER, no DEADLINE, and no follow-up
  tracking — a postmortem's real value is measured by whether its
  action items actually get implemented, not by how thorough the
  narrative write-up is.
"""

from dataclasses import dataclass, field
from datetime import date


# ------------------------------------------------------------------
# 1. The 5 Whys technique, illustrated
# ------------------------------------------------------------------
@dataclass
class FiveWhysChain:
    question: str
    answers: list[str] = field(default_factory=list)

    def add_why(self, answer: str):
        self.answers.append(answer)

    def print_chain(self):
        print(f"Incident: {self.question}")
        for i, answer in enumerate(self.answers, 1):
            print(f"  Why #{i}: {answer}")


def five_whys_demo():
    chain = FiveWhysChain("The database went down during a routine migration")
    chain.add_why("An engineer ran a schema migration during peak traffic hours")
    chain.add_why("There is no enforced maintenance-window requirement in "
                   "the deployment tooling — it was left to individual judgment")
    chain.add_why("The migration's lock-heavy operation wasn't caught in "
                   "staging, because staging traffic volume is much lower "
                   "than production, so the lock contention never manifested there")
    chain.add_why("There's no load-representative staging environment or "
                   "pre-deploy migration-impact analysis step in the pipeline")
    chain.add_why("The team has historically prioritized shipping speed "
                   "over investing in a staging environment that "
                   "realistically represents production load")
    chain.print_chain()

    print("\nSurface-level (WRONG) action item: 'remind engineers to be careful "
          "with migrations'")
    print("Actual SYSTEMIC action items, from the full chain:")
    print("  1. Add an automated maintenance-window enforcement check to the "
          "deployment pipeline (owner: Platform team, due: 2 weeks)")
    print("  2. Build a lock-contention analysis step for schema migrations, "
          "run automatically pre-deploy (owner: DB team, due: 1 month)")
    print("  3. Invest in a load-representative staging environment "
          "(owner: Platform team, due: 1 quarter — larger initiative)")


# ------------------------------------------------------------------
# 2. Action items with real accountability tracking
# ------------------------------------------------------------------
@dataclass
class ActionItem:
    description: str
    owner: str
    due_date: date
    completed: bool = False
    completed_date: date | None = None

    def mark_complete(self, completed_date: date):
        self.completed = True
        self.completed_date = completed_date

    @property
    def is_overdue(self) -> bool:
        return not self.completed  # a real system compares due_date to TODAY


class PostmortemTracker:
    """Tracks action items ACROSS many postmortems — the organizational
    view that turns 'we wrote thorough postmortems' into a measurable
    'we actually complete our action items' commitment."""

    def __init__(self):
        self.action_items: list[ActionItem] = []

    def add(self, item: ActionItem):
        self.action_items.append(item)

    def completion_rate(self) -> float:
        if not self.action_items:
            return 1.0
        completed = sum(1 for item in self.action_items if item.completed)
        return completed / len(self.action_items)

    def overdue_items(self, today: date) -> list[ActionItem]:
        return [item for item in self.action_items
                if not item.completed and item.due_date < today]


def accountability_tracking_demo():
    tracker = PostmortemTracker()
    tracker.add(ActionItem("Add maintenance-window enforcement check",
                             owner="Platform team", due_date=date(2026, 1, 29)))
    tracker.add(ActionItem("Build lock-contention analysis for migrations",
                             owner="DB team", due_date=date(2026, 2, 15)))
    tracker.add(ActionItem("Invest in load-representative staging",
                             owner="Platform team", due_date=date(2026, 4, 1)))

    tracker.action_items[0].mark_complete(date(2026, 1, 25))

    print(f"\nCompletion rate: {tracker.completion_rate():.0%}")
    overdue = tracker.overdue_items(today=date(2026, 3, 1))
    print(f"Overdue items as of March 1st: {[item.description for item in overdue]}")


# ------------------------------------------------------------------
# 3. Blameless framing — a direct before/after example
# ------------------------------------------------------------------
BLAME_FRAMING_COMPARISON = {
    "Blame-oriented (produces less accurate postmortems)":
        "'Sam ran the migration without checking the deployment schedule, "
        "causing the outage.' — Sam (and future engineers observing this) "
        "learns to be defensive/less forthcoming in FUTURE postmortems.",
    "Blameless (produces more accurate, actionable postmortems)":
        "'A migration was executed during peak hours. Our deployment "
        "tooling did not enforce or even surface maintenance-window "
        "guidance at the point of action, and staging didn't reflect "
        "production load closely enough to have caught the impact "
        "beforehand.' — focuses on the SYSTEM gaps, which are the "
        "actually fixable, actionable findings.",
}


if __name__ == "__main__":
    five_whys_demo()
    accountability_tracking_demo()

    print("\n=== Blame-oriented vs blameless framing ===")
    for framing, example in BLAME_FRAMING_COMPARISON.items():
        print(f"{framing}:\n  {example}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An organization tracks postmortem action item completion rate as an
explicit, reviewed metric (not just writing postmortems and moving on)
— discovering their completion rate had quietly dropped to 40% over two
quarters, they invest in a lightweight tracking process (a shared
dashboard reviewed monthly by engineering leadership) that raises
completion back above 85% — and, measurably, the RATE of repeat/similar
incidents drops correspondingly over the following two quarters, the
concrete, measurable payoff of treating postmortem action items as
genuine commitments rather than a documentation exercise.
"""
