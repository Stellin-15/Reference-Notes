# ============================================================
# L12: Production DevOps/SRE Maturity — Full Reference Architecture
# ============================================================
# WHAT: A capstone lesson wiring together every piece from L01-L11 into
#       ONE coherent operational practice — configuration management,
#       systems/network fundamentals, load testing and capacity
#       planning, and the incident/on-call/error-budget discipline that
#       ties reliability engineering together end to end.
# WHY: Every prior lesson covered one piece. A mature DevOps/SRE
#      practice is an INTEGRATED discipline — this lesson shows how
#      the pieces compose into an operational maturity model, and
#      traces one incident through the full lifecycle this domain covers.
# LEVEL: Capstone
# ============================================================

"""
CONCEPT OVERVIEW:
A mature DevOps/SRE practice, assembled from this domain's pieces:

  1. FOUNDATION (L01-L05): configuration management (Ansible or
     Puppet/Chef) eliminates configuration drift; Linux systems
     administration and network engineering fundamentals underpin
     effective debugging beneath higher-level abstractions.
  2. CAPACITY DISCIPLINE (L06-L07): load testing validates behavior
     under realistic traffic BEFORE production discovers the breaking
     point; capacity planning forecasts demand and sizes headroom/
     autoscaling policy proactively rather than reactively.
  3. INCIDENT LIFECYCLE (L08-L09): structured incident command
     (severity classification, a separate IC role, structured
     communication) during an active incident; blameless postmortems
     with 5-Whys root-cause analysis and tracked action items afterward.
  4. RELIABILITY GOVERNANCE (L10-L11): error budgets turn "be reliable"
     into an enforced release-velocity policy; toil measurement keeps
     operational burden visible and capped; sustainable on-call
     rotation design and alert-fatigue reduction keep the human system
     underneath all of this healthy.

This is a MATURITY PROGRESSION, not a checklist to implement all at
once — an organization typically builds configuration management and
basic monitoring first, then incident process, then the more advanced
error-budget/toil governance layer as reliability practice matures.
Skipping ahead (e.g. enforcing error-budget release freezes before
basic incident response is even structured) tends to produce policy
without the underlying operational capability to act on it meaningfully.

PRODUCTION USE CASE:
See the full incident lifecycle trace below — this is how a mature
organization's DevOps/SRE practice actually responds to and learns from
a real production incident, using every layer from L01-L11 in sequence.

COMMON MISTAKES:
- Adopting SRE's more advanced practices (error budgets, toil caps) as
  a checklist/badge of maturity without the underlying capacity
  (accurate SLIs, a functioning incident process, genuine organizational
  buy-in on the resulting policy enforcement) to make them meaningful —
  this produces theater, not actual reliability improvement.
- Treating configuration management, capacity planning, and incident
  response as entirely separate disciplines owned by different teams
  with no shared visibility — a capacity-planning gap (L07) often
  SURFACES as an incident (L08), and an incident's postmortem (L09)
  frequently identifies a configuration-drift (L01) or alerting (L11)
  root cause; these disciplines inform each other constantly in a
  mature practice.
- Measuring operational maturity purely by "do we have a document/
  dashboard for X" rather than by OUTCOMES (declining repeat-incident
  rate, improving on-call sustainability, error budget policy actually
  changing release behavior when triggered) — process without
  measured outcomes is not evidence of genuine maturity.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The maturity progression
# ------------------------------------------------------------------
MATURITY_LAYERS = {
    "Foundation (L01-L05)": "Configuration management eliminates drift; "
        "systems/network fundamentals enable effective debugging.",
    "Capacity discipline (L06-L07)": "Load testing and capacity planning "
        "make reliability PROACTIVE rather than purely reactive.",
    "Incident lifecycle (L08-L09)": "Structured response during an "
        "incident; blameless, action-tracked learning afterward.",
    "Reliability governance (L10-L11)": "Error budgets and toil caps turn "
        "reliability into an ENFORCED policy; sustainable on-call keeps "
        "the human system healthy.",
}

# ------------------------------------------------------------------
# 2. A full incident lifecycle trace, using every layer
# ------------------------------------------------------------------
FULL_LIFECYCLE_TRACE = textwrap.dedent("""\
    Scenario: a payment service outage during a traffic spike.

    PRE-INCIDENT (capacity discipline, L06-L07):
      A capacity plan had forecasted this traffic level as within normal
      range — the actual spike EXCEEDED the forecast by 3x, beyond the
      headroom the team had planned for.

    DURING (incident lifecycle, L08):
      The on-call engineer (L11's rotation) is paged. Given the
      customer-facing, revenue-impacting nature, this is classified SEV1
      immediately (L08's pre-agreed classification rules). An Incident
      Commander is assigned, SEPARATE from the Technical Lead debugging
      the database connection pool exhaustion (a config-management
      gap, L01: the pool size had drifted from the documented standard
      during a past manual fix that was never reconciled).

    RESOLUTION:
      The Technical Lead identifies and fixes the pool exhaustion; the
      IC confirms via monitoring the fix is holding before declaring
      resolution.

    POST-INCIDENT (L09):
      A blameless postmortem uses 5 Whys, tracing past "the pool was
      too small" to the REAL systemic causes: (a) no automated drift
      detection would have caught the manually-changed pool size
      (L01's config management gap), and (b) the capacity plan's
      headroom assumptions didn't account for a spike this large
      (L07's forecasting gap). TWO tracked action items are created,
      each with an owner and deadline.

    GOVERNANCE IMPACT (L10-L11):
      This incident consumed 60% of the quarter's error budget in one
      event — triggering the team's PRE-AGREED policy: feature release
      freeze until the two action items are completed and the budget
      shows signs of recovery. The postmortem ALSO reveals the alert
      that should have caught the connection pool trend BEFORE outright
      exhaustion was too noisy to be trusted (L11's alert-fatigue
      problem) — a third action item: tune that specific alert's
      threshold, closing the loop back to L11.
""")

# ------------------------------------------------------------------
# 3. A maturity self-assessment, per layer
# ------------------------------------------------------------------
def print_maturity_layers():
    for layer, description in MATURITY_LAYERS.items():
        print(f"{layer}: {description}\n")


if __name__ == "__main__":
    print_maturity_layers()
    print(FULL_LIFECYCLE_TRACE)

"""
FINAL CONTEXT:
The measure of having internalized this domain isn't being able to name
every practice (Ansible, k6, error budgets, 5 Whys) — it's recognizing,
when a real incident happens at your own organization, which layer's
gap actually caused it, and which OTHER layers that gap should feed back
into (a capacity-planning miss becomes an incident, an incident's
postmortem should feed BACK into capacity planning, alerting tuning,
AND configuration management, not just producing a one-off document).
This folder is meant to function as a working reference across that full
loop, not a one-time read-through.
"""
