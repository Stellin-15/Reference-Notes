"""
WHAT: Four realistic internal-developer-platform problems, each solved
      with THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Backstage or a custom portal," "how much self-service is too
      much," "how strict should policy-as-code be" are all questions
      L01-L08 gave you real tools for, not one universal answer -- this
      lesson is about the decision process under real organizational
      maturity constraints.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — DECIDING WHETHER TO BUILD A DEVELOPER PORTAL FOR A
# 15-ENGINEER COMPANY
# ============================================================================
#
# SETUP: a company with 15 engineers, ~10 services, is considering
# whether to invest in an internal developer platform (IDP)/portal
# (L01) or continue with ad hoc tooling.
#
# ------------------------------------------------------------------------
# APPROACH A: Adopt Backstage (L01), fully configured with service
# catalogs, templates, and documentation integration
# ------------------------------------------------------------------------
#   WHY VALID: per L01, Backstage provides a comprehensive, well-
#   established platform for service discovery, scaffolding, and
#   documentation -- if the company anticipates rapid near-term growth
#   in engineering headcount/service count, investing early avoids a
#   more painful retrofit later.
#   COST: per L08's platform-maturity discussion, Backstage (and IDPs
#   generally) have real setup and ONGOING maintenance overhead -- for
#   a 15-engineer company with only 10 services, this is likely
#   significant overhead relative to actual current need; per L08's
#   maturity-model framing, investing in comprehensive platform tooling
#   before the organization has the scale/pain that justifies it is a
#   common, real over-engineering trap.
#
# ------------------------------------------------------------------------
# APPROACH B: No dedicated platform at all -- rely on good
# documentation (a README per service, a shared wiki) and direct
# engineer-to-engineer knowledge sharing
# ------------------------------------------------------------------------
#   WHY VALID: per L08's maturity model, this is proportionate to the
#   CURRENT scale -- at 15 engineers, most people likely already know
#   most services and each other, and the coordination/discovery
#   problems a platform solves may not yet be a genuinely FELT pain
#   point worth solving with dedicated tooling.
#   COST: per L01/L08, this doesn't scale gracefully -- as engineering
#   headcount and service count grow, informal knowledge-sharing
#   degrades (new engineers can't easily discover what exists, tribal
#   knowledge becomes a bottleneck), and there's no clear trigger point
#   built into this approach for when to formalize, risking the
#   problem becoming acute before anyone deliberately addresses it.
#
# ------------------------------------------------------------------------
# APPROACH C: Start minimal -- a simple, low-maintenance service
# catalog (even a well-maintained spreadsheet or a lightweight static
# site) plus documentation conventions, with an EXPLICIT plan to adopt
# a full IDP (like Backstage) once specific, defined maturity signals
# are hit (e.g. engineer count crosses N, or onboarding-time complaints
# become frequent) (L08)
# ------------------------------------------------------------------------
#   WHY VALID: per L08's platform-maturity model directly, this
#   explicitly sequences investment to match actual organizational
#   growth -- avoiding both A's premature overhead and B's "never
#   formalize until it's genuinely painful" risk, by defining upfront
#   what signals would trigger the next investment tier.
#   COST: requires genuine discipline to actually track the defined
#   trigger signals and act on them -- without real follow-through, this
#   can quietly degrade into B's risk (the plan to formalize "later"
#   never actually happens), the same discipline-dependency risk seen
#   in other domains' capstones' "phased investment" case studies.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Overhead at current (15-engineer) scale | Scales gracefully with growth | Requires follow-through discipline |
#   |----------|------------------------------------------------|--------------------------------------|-------------------------------------------|
#   | A: full Backstage now | High, likely premature | Yes, already invested | No (already committed) |
#   | B: no dedicated platform | Lowest | No | No (but degrades silently) |
#   | C: minimal now, explicit trigger to formalize | Low | Yes, once triggered | Yes, real risk if not honored |
#   C is the strongest answer per L08's own maturity-model framing --
#   the specific trigger conditions should be defined and actually
#   revisited, not just stated as an intention, for this sequencing to
#   deliver its intended benefit over B's alternative of never
#   formalizing.


# ============================================================================
# CASE STUDY 2 — HOW MUCH SELF-SERVICE TO GRANT DEVELOPERS FOR
# PROVISIONING CLOUD INFRASTRUCTURE
# ============================================================================
#
# SETUP: deciding how much autonomy application engineers should have to
# provision their own cloud infrastructure (a new database, a new
# service) versus going through a centralized platform/ops team (L02,
# L04, L06).
#
# ------------------------------------------------------------------------
# APPROACH A: Full self-service -- any engineer can provision any
# resource directly via cloud console/CLI access
# ------------------------------------------------------------------------
#   WHY VALID: per L06's developer-experience discussion, maximizes
#   velocity -- no waiting on a centralized team for routine
#   infrastructure needs, engineers can move at their own pace.
#   COST: per L02/L04, this provides NO consistency guarantee (every
#   engineer might configure resources differently, some insecurely),
#   no cost visibility/control (per L07's FinOps discussion, unmonitored
#   ad hoc provisioning is a well-documented cause of runaway cloud
#   spend), and no policy enforcement (nothing stops a resource from
#   being misconfigured in a way that violates security/compliance
#   requirements) -- a real, serious governance gap at any meaningful
#   organizational scale.
#
# ------------------------------------------------------------------------
# APPROACH B: No self-service -- all infrastructure provisioning goes
# through a centralized platform/ops team via ticket request
# ------------------------------------------------------------------------
#   WHY VALID: per L02/L04, maximizes consistency and control -- the
#   centralized team can enforce standards, security policy, and cost
#   discipline on every single resource, since nothing is provisioned
#   without their direct involvement.
#   COST: per L06, this creates a real, often severe VELOCITY
#   bottleneck -- every routine infrastructure need (even a trivial one)
#   waits on the centralized team's queue, a well-documented developer-
#   experience pain point that platform engineering as a discipline
#   largely exists to solve, not preserve.
#
# ------------------------------------------------------------------------
# APPROACH C: Self-service through GOLDEN PATHS -- pre-approved,
# pre-configured Infrastructure-as-Code templates (L02) with
# policy-as-code (L04) guardrails baked in, letting engineers provision
# standard resource types themselves quickly WITHIN those guardrails,
# with the centralized team involved only for genuinely non-standard
# requests
# ------------------------------------------------------------------------
#   WHY VALID: per L02/L04/L06 together, this is the standard, well-
#   established modern platform-engineering answer -- engineers get A's
#   velocity for the COMMON, well-understood cases (which are the vast
#   majority of real requests), while policy-as-code guardrails (L04)
#   automatically enforce B's consistency/security/cost requirements
#   without needing a human in the loop for every request, and the
#   centralized team's attention is reserved for the genuinely unusual
#   cases that actually need it.
#   COST: requires real, genuine upfront investment to build and
#   maintain the golden-path templates and policy guardrails
#   themselves -- and per L04, policy-as-code rules need ongoing
#   maintenance as requirements evolve, plus the golden paths need to
#   actually cover enough of engineers' REAL needs to meaningfully
#   reduce reliance on the centralized team's ticket queue, or this
#   just becomes B with extra steps for the cases golden paths don't
#   cover.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Velocity | Consistency/security/cost control | Upfront investment |
#   |----------|--------------|------------------------------------------|--------------------------|
#   | A: full self-service | Best | Worst | Lowest |
#   | B: fully centralized | Worst | Best | Lowest (per-request effort, not upfront) |
#   | C: golden paths + policy-as-code guardrails | Good, for common cases | Good, automatically enforced | Highest, upfront |
#   C is the standard target state for a maturing platform team; B is a
#   reasonable STARTING point for a very early-stage org that hasn't
#   yet invested in golden paths; A is rarely defensible once genuine
#   organizational scale/stakes exist, given the real governance gaps
#   it leaves open.


# ============================================================================
# CASE STUDY 3 — HOW STRICT SHOULD POLICY-AS-CODE ENFORCEMENT BE
# ============================================================================
#
# SETUP: a platform team has built policy-as-code rules (L04) checking
# infrastructure changes against security/cost/compliance standards --
# deciding how strictly to enforce them (block vs. warn).
#
# ------------------------------------------------------------------------
# APPROACH A: Hard-block any policy violation -- a change that violates
# any rule simply cannot be deployed, no override mechanism (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, guarantees the standards are ALWAYS actually
#   enforced -- no risk of a violation slipping through under time
#   pressure or being "just this once" waived, the strongest possible
#   compliance guarantee.
#   COST: per L04/L06, a policy engine is a codified set of rules that
#   can genuinely be WRONG for a specific, legitimate edge case the
#   rule author didn't anticipate -- a hard block with no override means
#   a genuinely valid, urgent change can be completely stuck, a real
#   developer-experience and (in a genuine emergency) operational-
#   response cost.
#
# ------------------------------------------------------------------------
# APPROACH B: Warn-only -- policy violations are flagged/logged but
# don't block deployment
# ------------------------------------------------------------------------
#   WHY VALID: per L04/L06, never blocks legitimate work, avoids A's
#   edge-case rigidity entirely -- developers get VISIBILITY into policy
#   violations without velocity being held hostage to the policy
#   engine's own potential blind spots or bugs.
#   COST: per L04, warnings that don't BLOCK are, in practice, very
#   easy to ignore under time pressure -- a well-documented pattern
#   where "just a warning" policy violations accumulate and get
#   normalized rather than actually fixed, undermining the entire
#   point of having the policy in the first place.
#
# ------------------------------------------------------------------------
# APPROACH C: Block by default, with an EXPLICIT, AUDITABLE override
# mechanism (e.g. requiring a second approver's sign-off and a logged
# justification) for genuine exceptions (L04)
# ------------------------------------------------------------------------
#   WHY VALID: per L04, this combines A's real enforcement teeth with
#   B's flexibility for genuine edge cases -- the DEFAULT behavior is
#   still a hard block (preserving the compliance guarantee for the
#   vast majority of cases), but a genuinely legitimate exception has an
#   explicit, deliberate, AUDITED path forward rather than either being
#   permanently stuck (A) or the whole policy silently eroding into
#   "just a suggestion" (B).
#   COST: requires real design/implementation work to build the
#   override mechanism itself (who can approve, how it's logged/
#   audited) -- and if the override process is too easy/low-friction, it
#   can itself become a routine workaround that undermines the policy
#   almost as much as B's pure warn-only approach would, requiring
#   genuine, ongoing attention to whether overrides are being used
#   appropriately (rare, justified exceptions) or too casually.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Compliance guarantee strength | Flexibility for legitimate edge cases | Risk of policy erosion over time |
#   |----------|------------------------------------|---------------------------------------------|------------------------------------------|
#   | A: hard block, no override | Strongest | None (real rigidity risk) | Low (can't be bypassed) |
#   | B: warn-only | Weakest | Full | High (easy to ignore) |
#   | C: block by default + audited override | Strong | Good, via explicit process | Medium (needs monitoring override usage) |
#   C is the standard, well-established best practice for genuinely
#   important policies (security, compliance-driven rules); B is
#   reasonable specifically for NEW, not-yet-fully-trusted policy rules
#   during a rollout/tuning period, before graduating them to C's
#   enforced status once confidence in the rule's correctness is
#   established.


# ============================================================================
# CASE STUDY 4 — ATTRIBUTING AND CONTROLLING CLOUD COSTS ACROSS MANY
# TEAMS SHARING INFRASTRUCTURE
# ============================================================================
#
# SETUP: a company's cloud bill has grown significantly, and cost is
# currently NOT attributed per team -- deciding on a FinOps approach
# (L07).
#
# ------------------------------------------------------------------------
# APPROACH A: Mandate strict resource TAGGING (every resource must be
# tagged with an owning team) enforced via policy-as-code (L04, L07),
# with cost dashboards built from those tags
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this is the standard FinOps foundation --
#   accurate cost attribution requires accurate tagging, and enforcing
#   it via policy-as-code (rather than relying on voluntary compliance)
#   ensures the data is actually reliable enough to build meaningful
#   cost dashboards/chargebacks from.
#   COST: per L07, retrofitting tagging onto EXISTING, already-deployed
#   infrastructure (not just new resources going forward) is real,
#   nontrivial cleanup work -- and enforcement alone doesn't
#   automatically REDUCE cost, it only makes existing cost visible/
#   attributable, a necessary first step but not itself a cost
#   reduction.
#
# ------------------------------------------------------------------------
# APPROACH B: Set hard per-team budget CAPS with automatic enforcement
# (e.g. provisioning is blocked once a team's monthly spend limit is
# hit) (L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L07, provides a hard, guaranteed ceiling on spend --
#   directly prevents runaway cost growth, a strong lever if the
#   company's immediate concern is capping an already-concerning cost
#   trajectory quickly.
#   COST: per L07, this requires A's tagging/attribution to already be
#   reliable (you can't enforce a per-team cap without first knowing
#   what each team is actually spending) -- and hard caps can block
#   genuinely legitimate, needed infrastructure provisioning once a
#   limit is hit, a real operational risk similar to Case Study 3's
#   hard-block rigidity concern, now applied to cost rather than policy
#   compliance.
#
# ------------------------------------------------------------------------
# APPROACH C: A first (build reliable attribution), THEN cost
# VISIBILITY/showback (teams see their own costs, without hard
# enforcement) before B's hard caps, giving teams a chance to self-
# correct once they have visibility, escalating to B's hard enforcement
# only for teams that don't respond to visibility alone (L07)
# ------------------------------------------------------------------------
#   WHY VALID: per L07's FinOps maturity framing, this sequences the
#   investment correctly -- attribution (A) is a genuine PREREQUISITE
#   for anything else, and per L07's own point that showback/visibility
#   alone often drives substantial voluntary cost optimization (teams
#   who can SEE their own spend frequently self-correct without needing
#   hard enforcement), this avoids B's rigidity risk for teams that
#   respond well to visibility alone, reserving hard caps for teams that
#   genuinely need that stronger intervention.
#   COST: slower to guarantee a hard cost ceiling than jumping straight
#   to B -- if the company's cost situation is severe enough that
#   waiting for voluntary self-correction isn't an acceptable risk, this
#   more gradual sequencing may not move fast enough, and B's harder,
#   faster intervention may be justified despite its own real cost.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Prerequisite for other approaches | Guarantees a hard cost ceiling | Preserves team autonomy |
#   |----------|------------------------------------------|--------------------------------------|--------------------------------|
#   | A: tagging + attribution | Yes (foundational) | No | Full |
#   | B: hard budget caps | No (requires A first) | Yes | Reduced (can block provisioning) |
#   | C: A, then showback, then B for non-responders | Includes A | Eventually, for teams that need it | Preserved longer, for responsive teams |
#   A is always the necessary first step regardless of the ultimate
#   destination; C is the strongest overall sequencing for most
#   organizations; B (skipping straight past showback once attribution
#   exists) is justified specifically when cost growth is severe enough
#   that waiting for voluntary self-correction is too risky.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
