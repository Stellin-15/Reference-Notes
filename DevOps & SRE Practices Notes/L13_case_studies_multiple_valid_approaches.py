"""
WHAT: Four realistic DevOps/SRE operational problems, each solved with
      THREE genuinely different, individually defensible approaches
      drawn from L01-L12 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Push or pull config management," "how strict should an error
      budget policy be," "who should be on-call" are all questions
      L01-L12 gave you real tools for, not one universal answer -- this
      lesson is about the decision process under real organizational
      constraints.
LEVEL: Capstone -- read after L01-L12.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L12's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING A CONFIGURATION MANAGEMENT APPROACH FOR A FLEET
# OF 200 LONG-LIVED VMS (NOT CONTAINERS)
# ============================================================================
#
# SETUP: a company runs 200 long-lived VMs (not containerized) for
# legacy reasons, and needs consistent OS-level configuration
# (packages, users, cron jobs) across them, currently managed via ad hoc
# SSH scripts.
#
# ------------------------------------------------------------------------
# APPROACH A: Ansible (L02), push-based, run from a central control
# node/CI job on a schedule
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Ansible requires NO agent installed on the
#   managed nodes (just SSH access) -- the lowest-friction adoption
#   path for an EXISTING fleet of 200 VMs that don't already have any
#   config-management agent running, and its push model means changes
#   propagate on-demand rather than waiting for each node's own pull
#   cycle.
#   COST: per L03's push-vs-pull framework, push-based tools depend on
#   the control node successfully REACHING every managed node at
#   execution time -- a node that's temporarily unreachable (network
#   partition, VM briefly down) simply doesn't get updated until the
#   NEXT successful run reaches it, and at 200 nodes, a single Ansible
#   run touching all of them serially (without careful batching/
#   parallelism tuning) can take a genuinely long time.
#
# ------------------------------------------------------------------------
# APPROACH B: Puppet or Chef (L03), pull-based, agent installed on every
# VM, checking in periodically
# ------------------------------------------------------------------------
#   WHY VALID: per L03, pull-based tools have each node independently
#   check in and self-converge to the desired state on its OWN schedule
#   -- a node that was temporarily unreachable simply catches up on its
#   next check-in with no action needed from the control side, and
#   configuration drift correction happens continuously/automatically
#   rather than only when someone explicitly triggers a push run.
#   COST: per L03, requires installing and maintaining an AGENT on
#   every one of the 200 VMs -- real additional software to deploy,
#   update, and monitor across the fleet (an agent itself can have
#   bugs, resource usage, or version-compatibility concerns), a
#   meaningfully higher initial adoption cost than Ansible's agentless
#   model for a fleet that doesn't already have this infrastructure.
#
# ------------------------------------------------------------------------
# APPROACH C: Migrate the VMs to immutable, declaratively-defined images
# (a golden-image pipeline) rather than configuration-managing long-
# lived VMs at all -- replace VMs wholesale on update rather than
# patching them in place
# ------------------------------------------------------------------------
#   WHY VALID: per L01's push-vs-pull/declarative-vs-imperative framing
#   taken to its logical extreme, this eliminates CONFIGURATION DRIFT as
#   a category of problem entirely -- there's no "did the config
#   management run correctly on THIS specific node" question when nodes
#   are never individually configured after creation; every VM is
#   provably identical because it's built from the same image.
#   COST: represents a genuinely LARGER architectural shift than either
#   A or B -- moving from "long-lived VMs configured in place" to
#   "immutable VMs replaced wholesale" touches deployment tooling,
#   requires the underlying workload to tolerate being replaced
#   (stateful workloads need external state, not local VM state), and
#   is real, substantial migration effort beyond just picking a config-
#   management tool.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Adoption friction | Drift-correction reliability | Architectural change required |
#   |----------|------------------------|------------------------------------|--------------------------------------|
#   | A: Ansible (push) | Lowest | Medium (depends on run reaching every node) | None |
#   | B: Puppet/Chef (pull) | Medium (agent rollout) | High (self-correcting) | None |
#   | C: immutable golden images | Highest | Highest (drift impossible by design) | Large |
#   For a legacy, long-lived VM fleet, A is the pragmatic near-term fix
#   given zero existing tooling; C is the strongest LONG-TERM answer if
#   the workload can tolerate it, and worth genuinely evaluating rather
#   than assuming "we use VMs so we must configuration-manage them in
#   place forever."


# ============================================================================
# CASE STUDY 2 — SETTING AN ERROR BUDGET POLICY FOR A NEWLY-DEFINED SLO
# ============================================================================
#
# SETUP: a team has just defined an SLO (99.9% availability) for a
# service for the first time and needs to decide what actually HAPPENS
# when the error budget is exhausted (L10).
#
# ------------------------------------------------------------------------
# APPROACH A: A strict, automatically-enforced feature-freeze policy --
# CI blocks non-emergency deploys once the error budget hits zero (L10)
# ------------------------------------------------------------------------
#   WHY VALID: per L10, this gives the error budget REAL teeth --
#   without an enforced consequence, an error budget is just a metric
#   nobody acts on, and automatic enforcement removes the awkward,
#   easily-deprioritized human negotiation of "should we really stop
#   shipping features right now" during a busy period.
#   COST: for a BRAND NEW SLO (as stated), the initial target (99.9%)
#   may simply be miscalibrated -- either too strict (an achievable-but-
#   ambitious target that gets blown through immediately due to
#   legitimate early-stage instability) or too loose; automatically
#   freezing deploys based on a target that hasn't yet been VALIDATED
#   as reasonable risks blocking real work over a number that may
#   itself need adjusting, not the team's actual reliability practices.
#
# ------------------------------------------------------------------------
# APPROACH B: A softer policy -- error budget exhaustion triggers a
# mandatory review/discussion (not an automatic block), where the team
# explicitly decides whether to slow feature work
# ------------------------------------------------------------------------
#   WHY VALID: per L10, this preserves human judgment for a genuinely
#   NEW SLO where the target itself is unproven -- the team can
#   distinguish "we blew the budget because of a real, systemic
#   reliability problem" (should slow down) from "we blew it because of
#   one unusual, unlikely-to-recur incident" (may be fine to continue),
#   a distinction a purely automatic policy can't make.
#   COST: per L10's own point about error budgets needing real
#   enforcement to matter, a discussion-only policy is easy to quietly
#   erode over time -- "let's just ship this one more thing" can become
#   a repeated pattern with no automatic backstop, especially under
#   deadline pressure, gradually turning the SLO into a number nobody
#   actually acts on.
#
# ------------------------------------------------------------------------
# APPROACH C: Run the SLO in "observation mode" for an initial period
# (e.g. one quarter) with NO enforcement consequence at all, purely to
# gather real data on whether the target is achievable, THEN introduce
# an enforcement policy (A or B) once the target is validated
# ------------------------------------------------------------------------
#   WHY VALID: directly addresses A's "the target itself may be
#   miscalibrated" risk by explicitly sequencing "validate the target
#   is reasonable" BEFORE "enforce consequences for missing it" -- a
#   genuinely sound approach specifically because this is described as
#   a NEWLY DEFINED SLO with no track record yet.
#   COST: delays any real enforcement teeth for the observation period's
#   full duration -- if the service genuinely has serious reliability
#   problems from day one, this approach means living with zero
#   consequence-driven pressure to fix them for that entire window,
#   a real cost if the team's baseline reliability discipline isn't
#   already strong without an enforced backstop.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Enforcement strength | Fits an UNVALIDATED, brand-new target | Risk of policy erosion |
#   |----------|---------------------------|--------------------------------------------|------------------------------|
#   | A: automatic freeze | Strongest | Poor (may block on a wrong number) | Low (can't be quietly skipped) |
#   | B: discussion-based | Weaker | Good (allows judgment) | High |
#   | C: observation period, then enforce | Delayed | Best | N/A during observation |
#   C is the strongest sequencing for a genuinely NEW SLO (this case
#   study's exact situation); once the target is validated through a
#   real observation period, transitioning to A is generally stronger
#   than staying on B indefinitely, given B's real erosion risk.


# ============================================================================
# CASE STUDY 3 — DESIGNING AN ON-CALL ROTATION FOR A SMALL TEAM (5
# ENGINEERS) SUPPORTING A 24/7 SERVICE
# ============================================================================
#
# SETUP: a 5-engineer team needs to provide 24/7 on-call coverage for a
# service with real (if not extreme) uptime requirements, and is
# deciding how to structure the rotation (L11).
#
# ------------------------------------------------------------------------
# APPROACH A: A simple weekly rotation, each engineer on-call for a full
# week at a time, no secondary/backup on-call
# ------------------------------------------------------------------------
#   WHY VALID: the simplest possible schedule to build and understand --
#   with only 5 engineers, a weekly rotation cycles back to each person
#   roughly once every 5 weeks, a reasonable frequency that avoids being
#   on-call too often.
#   COST: per L11's alert-fatigue discussion, a FULL WEEK of on-call
#   with no secondary/backup means a single engineer bears 100% of the
#   response burden for 7 consecutive days -- if a serious incident
#   happens during that week (or several incidents in succession), there's
#   no built-in relief, and per L11's fairness discussion, a bad week
#   (e.g. an incident-heavy week landing on one specific person by pure
#   chance) isn't distributed or mitigated in any way.
#
# ------------------------------------------------------------------------
# APPROACH B: Primary + secondary on-call, shorter rotation shifts (e.g.
# 3-4 days), secondary escalated to if primary doesn't acknowledge
# within a set window (L11)
# ------------------------------------------------------------------------
#   WHY VALID: per L11, this directly addresses A's "single point of
#   response burden" problem -- a secondary provides real backup if the
#   primary is unreachable or overwhelmed, and shorter shifts reduce how
#   long any one person carries the FULL weight of being first-
#   responder, both real fairness and reliability improvements.
#   COST: with only 5 engineers, running BOTH primary and secondary
#   rotations simultaneously means each person is on SOME on-call duty
#   (primary or secondary) a much larger fraction of the time than in
#   A -- a real increase in how often any given engineer's personal
#   time is encumbered by on-call responsibility, a genuine quality-of-
#   life cost for a team this small trying to run a two-tier rotation.
#
# ------------------------------------------------------------------------
# APPROACH C: Follow-the-sun style coverage isn't feasible at 5 people,
# so instead: A single-tier rotation (like A) but with an explicit,
# hard-enforced "no on-call for at least 2 consecutive weeks after a
# genuinely bad/high-incident week" compensation policy, plus strong
# automated alerting/runbooks (L11) to reduce how OFTEN a human needs to
# be paged at all
# ------------------------------------------------------------------------
#   WHY VALID: rather than adding organizational complexity (B's two-
#   tier rotation, hard to sustain fairly at 5 people), this approach
#   invests in REDUCING the actual toil (per L11's toil-elimination
#   discussion, better runbooks/automation can resolve many pages
#   without needing deep human judgment) while adding an explicit
#   fairness safety valve for when a bad week does happen, rather than
#   restructuring the whole rotation shape.
#   COST: doesn't provide B's real-time backup during an ACTIVE
#   incident (no secondary to escalate to mid-incident if the primary
#   is unreachable RIGHT NOW) -- the compensation policy addresses
#   fairness AFTER a bad week, not resilience DURING one, a real,
#   different kind of gap than B directly closes.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Response resilience (backup available?) | Time-encumbrance burden | Team-size fit |
#   |----------|------------------------------------------------|--------------------------------|--------------------|
#   | A: simple weekly, no backup | Weakest | Lowest | Fits, but fragile |
#   | B: primary + secondary | Strongest | Highest (two-tier at only 5 people) | Strained at this size |
#   | C: single-tier + compensation policy + toil reduction | Medium (no live backup) | Medium | Good fit |
#   At exactly 5 engineers, B's two-tier model is a real strain (per-
#   person on-call frequency becomes uncomfortably high); C is often
#   the better-calibrated answer for a team this small, specifically
#   BECAUSE it invests in reducing how often a human is needed at all
#   rather than adding more human-rotation complexity on top of a small
#   pool of people.


# ============================================================================
# CASE STUDY 4 — WRITING A POSTMORTEM FOR AN INCIDENT WITH A GENUINE
# HUMAN-ERROR COMPONENT (AN ENGINEER RAN THE WRONG COMMAND)
# ============================================================================
#
# SETUP: an incident was directly triggered by an engineer running a
# destructive command against the wrong environment; the postmortem
# (L09) needs to be written in a way that's genuinely useful, not just
# procedurally compliant.
#
# ------------------------------------------------------------------------
# APPROACH A: Name the engineer and the specific mistake explicitly in
# the postmortem, focus root-cause analysis on "why did they run the
# wrong command"
# ------------------------------------------------------------------------
#   WHY VALID: directly, honestly documents WHAT happened -- avoiding
#   naming who did what can feel like avoiding the actual facts, and for
#   an organization with a genuinely psychologically safe culture, this
#   level of directness isn't inherently harmful.
#   COST: per L09's blameless-postmortem discussion, this is precisely
#   the pattern blameless postmortems exist to avoid -- focusing on "why
#   did THIS PERSON make THIS mistake" tends to produce a superficial
#   root cause ("they were careless" / "they should have double-
#   checked") that doesn't actually PREVENT recurrence, since the next
#   person under similar conditions (time pressure, an easy-to-confuse
#   environment-selection UI) remains just as likely to make the same
#   mistake -- and naming individuals creates a real chilling effect on
#   future honest incident reporting.
#
# ------------------------------------------------------------------------
# APPROACH B: A fully blameless postmortem (L09) -- no individual named,
# root-cause analysis via the "5 Whys" technique focused on SYSTEM/
# PROCESS factors that made the error possible (why was it possible to
# run a destructive command against the wrong environment at all)
# ------------------------------------------------------------------------
#   WHY VALID: per L09, "5 Whys" applied to this incident likely surfaces
#   the REAL, actionable root cause -- e.g. "why could the wrong
#   environment be targeted" might reveal that production and staging
#   look nearly identical in the tooling used, or that there's no
#   confirmation step before destructive commands -- SYSTEM fixes
#   (clearer environment labeling, a confirmation prompt, restricted
#   permissions) that genuinely reduce the chance of ANY engineer making
#   this mistake, not just this one.
#   COST: a fully blameless framing can, if not handled carefully, tip
#   into never acknowledging that INDIVIDUAL judgment/process-following
#   was also a real factor at all -- per L09's own nuance, "blameless"
#   should mean not punishing the individual, not literally omitting
#   that a human action was part of the causal chain; done poorly, an
#   overcorrected "purely systemic" framing can miss legitimate
#   process-adherence gaps (e.g. if a documented safety procedure was
#   simply skipped) that DO need addressing, just not punitively.
#
# ------------------------------------------------------------------------
# APPROACH C: A blameless postmortem (as in B) PLUS a SEPARATE, private
# 1:1 conversation between the engineer and their manager to check in on
# how they're doing after the incident -- keeping the public postmortem
# document and the personal/emotional support conversation as explicitly
# separate channels
# ------------------------------------------------------------------------
#   WHY VALID: per L09's broader point that blameless culture is about
#   PROCESS, not about ignoring that a real person went through a
#   stressful incident -- this explicitly separates the SYSTEM-focused,
#   shareable artifact (the postmortem, which should be blameless and
#   widely readable) from the HUMAN, private support the individual
#   engineer may genuinely need after causing (even blamelessly) a real
#   incident, addressing both the technical and human sides without
#   conflating them.
#   COST: requires a manager who's actually skilled at and comfortable
#   having this kind of supportive, non-punitive conversation -- not a
#   given in every organization, and if handled poorly (the "private"
#   conversation becomes an informal blame session that just moved out
#   of the written document), it can undermine the whole blameless
#   premise while LOOKING like it's following the right process on
#   paper.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Actionable systemic fix likelihood | Psychological safety impact | Addresses the human element |
#   |----------|------------------------------------------|-----------------------------------|------------------------------------|
#   | A: name and blame | Low (superficial root cause) | Negative | Poorly (punitively) |
#   | B: fully blameless, systemic 5 Whys | High | Positive | Indirectly (via safer culture) |
#   | C: B + separate private support conversation | High | Most positive | Directly, appropriately |
#   C is the strongest answer specifically because it doesn't force a
#   choice between "the postmortem should be blameless" and "the person
#   involved might need real support" -- it holds both, explicitly,
#   through separate channels, rather than either ignoring the human
#   element (B alone) or contaminating the shared document with it (A).


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
