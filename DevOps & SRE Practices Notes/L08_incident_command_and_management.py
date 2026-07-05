# ============================================================
# L08: Incident Command and Management
# ============================================================
# WHAT: A structured process for responding to a production incident —
#       severity classification, the Incident Commander role and why
#       it's separate from "the person fixing the problem," and
#       structured communication during an active incident.
# WHY: An unstructured incident response ("everyone jumps in and tries
#       things") frequently makes incidents WORSE — duplicated effort,
#       conflicting changes, unclear ownership, and poor communication
#       to stakeholders. A structured incident command process exists
#       specifically to prevent this, borrowed from emergency-response
#       disciplines outside software entirely (the Incident Command
#       System, originally developed for firefighting).
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
SEVERITY CLASSIFICATION gives every incident a consistent, understood
LEVEL (commonly SEV1 through SEV4, or P0-P3, naming conventions vary)
based on actual USER/BUSINESS IMPACT, not how alarming it feels in the
moment — a SEV1 ("critical, widespread customer-facing outage") demands
immediate, all-hands response and executive visibility; a SEV4 ("minor,
no customer impact, can wait for business hours") does not. Having
this classification agreed upon IN ADVANCE (not improvised during the
incident itself) is what lets the right level of urgency and the right
people get engaged quickly, without every incident triggering a
maximum-urgency response regardless of actual severity.

THE INCIDENT COMMANDER (IC) role is the single most important
structural idea in modern incident response: the IC's job is
COORDINATION, not technical fixing — tracking the incident's overall
status, deciding who's actively working what, managing communication to
stakeholders, and making the call on when the incident is resolved.
CRITICALLY, the IC is a SEPARATE person from whoever is actually
debugging/fixing the technical problem — this separation exists because
a single person cannot do BOTH deep technical troubleshooting AND
maintain the coordination/communication overview simultaneously without
one of them suffering; a technical responder deep in debugging a
specific hypothesis is poorly positioned to also track "have we told
customer support what's happening" or "is someone else duplicating this
same investigation."

STRUCTURED COMMUNICATION during an active incident means: a DEDICATED
channel (a specific Slack channel, a conference bridge) for the
incident, REGULAR STATUS UPDATES at a predictable cadence (even "no new
information yet" is a useful update, preventing stakeholders from
repeatedly asking "any update?" and interrupting the responders), and a
clear distinction between the TECHNICAL WAR ROOM (where active debugging
happens, often noisy/unstructured) and STAKEHOLDER COMMUNICATION
(external-facing, calmer, focused on business impact and ETA, not
technical debugging minutiae).

PRODUCTION USE CASE:
A SEV1 incident (a payment processing outage) is declared: an Incident
Commander is assigned WITHIN MINUTES (separate from the engineer
actually debugging the payment service), who posts a status update
every 15 minutes to a stakeholder-facing channel while the technical
responders work in a separate, focused channel — customer support and
executive stakeholders get consistent, predictable updates without
needing to interrupt the debugging engineers directly, and the IC makes
the final call on declaring the incident resolved once the fix is
confirmed and monitored, rather than that determination being made
informally by whoever happened to apply the fix.

COMMON MISTAKES:
- Having the SAME person both lead technical debugging AND handle all
  stakeholder communication/coordination during a significant incident
  — this person becomes a bottleneck and, worse, the coordination
  function typically degrades as their attention is consumed by the
  more urgent-feeling technical work.
- Not having a PRE-AGREED severity classification, leading to
  inconsistent incident response — every incident either escalates to
  maximum urgency (alert fatigue, unsustainable) or, worse, a genuinely
  severe incident gets under-prioritized because nobody formally
  classified it as urgent.
- Mixing STAKEHOLDER communication with the TECHNICAL debugging
  channel — external-facing updates full of raw technical debugging
  chatter is confusing/alarming to non-technical stakeholders, while
  technical responders being interrupted by stakeholder questions mid-
  debugging slows the actual resolution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ------------------------------------------------------------------
# 1. Severity classification — defined in advance, not improvised
# ------------------------------------------------------------------
class Severity(Enum):
    SEV1 = "SEV1 — Critical: widespread customer-facing outage or data loss risk"
    SEV2 = "SEV2 — Major: significant feature broken, meaningful customer impact"
    SEV3 = "SEV3 — Minor: limited impact, workaround available"
    SEV4 = "SEV4 — Low: no customer impact, can be scheduled for business hours"


SEVERITY_RESPONSE_REQUIREMENTS = {
    Severity.SEV1: {"page_immediately": True, "requires_ic": True, "exec_visibility": True,
                     "update_cadence_minutes": 15},
    Severity.SEV2: {"page_immediately": True, "requires_ic": True, "exec_visibility": False,
                     "update_cadence_minutes": 30},
    Severity.SEV3: {"page_immediately": False, "requires_ic": False, "exec_visibility": False,
                     "update_cadence_minutes": 60},
    Severity.SEV4: {"page_immediately": False, "requires_ic": False, "exec_visibility": False,
                     "update_cadence_minutes": None},
}


def classify_incident(customer_facing: bool, revenue_impacting: bool, has_workaround: bool) -> Severity:
    """A concrete, pre-agreed classification RULE — removing improvisation
    from the highest-pressure moment of an incident."""
    if customer_facing and revenue_impacting and not has_workaround:
        return Severity.SEV1
    if customer_facing and not has_workaround:
        return Severity.SEV2
    if customer_facing and has_workaround:
        return Severity.SEV3
    return Severity.SEV4


# ------------------------------------------------------------------
# 2. The Incident Commander role — separate from technical responders
# ------------------------------------------------------------------
@dataclass
class IncidentRole:
    name: str
    person: str


@dataclass
class Incident:
    incident_id: str
    severity: Severity
    started_at: datetime
    incident_commander: IncidentRole | None = None
    technical_lead: IncidentRole | None = None    # DELIBERATELY a DIFFERENT person than the IC
    status_updates: list[str] = field(default_factory=list)
    resolved_at: datetime | None = None

    def assign_roles(self, ic: str, tech_lead: str):
        if ic == tech_lead:
            raise ValueError(
                "Incident Commander and Technical Lead must be DIFFERENT "
                "people — combining these roles overloads one person with "
                "both deep technical debugging AND coordination/"
                "communication responsibilities simultaneously."
            )
        self.incident_commander = IncidentRole("Incident Commander", ic)
        self.technical_lead = IncidentRole("Technical Lead", tech_lead)

    def post_status_update(self, message: str, now: datetime):
        self.status_updates.append(f"[{now.strftime('%H:%M')}] {message}")

    def resolve(self, now: datetime):
        # THE INCIDENT COMMANDER makes this call — not whoever happened
        # to apply the fix, ensuring resolution is a deliberate,
        # coordinated decision (has the fix been VERIFIED, not just applied).
        self.resolved_at = now
        self.post_status_update("RESOLVED — confirmed by Incident Commander", now)


# ------------------------------------------------------------------
# 3. Structured communication — separate channels for separate audiences
# ------------------------------------------------------------------
COMMUNICATION_STRUCTURE_EXAMPLE = """
#incident-2026-01-15-payments-outage   <- TECHNICAL war room:
                                          fast, noisy, raw debugging chatter,
                                          hypothesis testing, is where the
                                          Technical Lead and responders work

#incidents-stakeholder-updates          <- CALMER, business-impact-focused:
                                          "Payment processing is degraded for
                                          ~15% of transactions since 14:02 UTC.
                                          Root cause identified, fix in
                                          progress, next update in 15 min."
                                          — posted by the IC, NOT copy-pasted
                                          from the technical channel directly
"""


if __name__ == "__main__":
    severity = classify_incident(customer_facing=True, revenue_impacting=True, has_workaround=False)
    print(f"Classified severity: {severity.value}")
    print(f"Response requirements: {SEVERITY_RESPONSE_REQUIREMENTS[severity]}")

    incident = Incident("INC-2026-0042", severity, started_at=datetime(2026, 1, 15, 14, 2))
    incident.assign_roles(ic="Priya (IC)", tech_lead="Sam (debugging payment service)")

    incident.post_status_update("Investigating elevated payment failures", datetime(2026, 1, 15, 14, 5))
    incident.post_status_update("Root cause identified: DB connection pool exhaustion",
                                  datetime(2026, 1, 15, 14, 20))
    incident.resolve(datetime(2026, 1, 15, 14, 35))

    print(f"\nIncident timeline:")
    for update in incident.status_updates:
        print(f"  {update}")

    print(COMMUNICATION_STRUCTURE_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A SEV1 payment outage is handled with a clean IC/Technical-Lead
separation: the Technical Lead spends the entire incident heads-down in
the technical channel, root-causing a database connection pool
exhaustion issue, while the IC — never touching the debugging directly —
posts consistent 15-minute stakeholder updates, coordinates a second
engineer to check if the issue is affecting other services, and makes
the final resolution call once monitoring confirms the fix is holding
— a clean division of attention that let the actual fix happen faster
BECAUSE the Technical Lead was never interrupted by stakeholder
communication needs during the most time-pressured part of the incident.
"""
