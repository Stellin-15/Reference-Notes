"""
WHAT: Four realistic Azure-native AI architecture problems, each solved
      with THREE genuinely different, individually defensible approaches
      drawn from L01-L08 -- with an explicit comparison table and
      reasoning for why each answer is valid under different
      constraints.
WHY:  "Standard or PTU capacity," "AI Foundry Agent Service or
      Semantic Kernel directly," "which Cognitive Service vs a custom
      model" are all questions L01-L08 gave you real tools for, not one
      universal answer -- this lesson is about the decision process
      under real quota, cost, and governance constraints specific to
      Azure shops.
LEVEL: Capstone -- read after L01-L08.

This file is reference material, not meant to run top-to-bottom. Before
checking each comparison table, try reconstructing it yourself using
only L01-L08's concepts.
"""

# ============================================================================
# CASE STUDY 1 — CHOOSING AZURE OPENAI CAPACITY MODE FOR A NEW
# PRODUCTION WORKLOAD
# ============================================================================
#
# SETUP: a new customer-facing feature is about to launch on Azure
# OpenAI; usage projections are uncertain (could be low, could scale
# fast), and latency consistency matters for the product experience.
#
# ------------------------------------------------------------------------
# APPROACH A: Standard (pay-as-you-go) deployment (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, Standard capacity has no upfront commitment --
#   cost scales directly with actual usage, the right choice when usage
#   is genuinely uncertain (as stated) and the team doesn't want to
#   commit to a fixed capacity purchase before real traffic data exists.
#   COST: per L02, Standard capacity is subject to regional QUOTA limits
#   and, under high shared demand, can experience more variable latency/
#   throttling than a dedicated capacity model -- for a feature where
#   "latency consistency matters" (as explicitly stated), this is a
#   real, direct tension with Standard's shared-capacity nature.
#
# ------------------------------------------------------------------------
# APPROACH B: Provisioned Throughput Units (PTU) from day one (L02)
# ------------------------------------------------------------------------
#   WHY VALID: per L02, PTU provides DEDICATED, reserved capacity with
#   predictable, consistent latency -- directly addresses the stated
#   latency-consistency requirement, since throughput isn't shared with
#   other tenants' unpredictable demand the way Standard capacity is.
#   COST: per L02, PTU requires a real, fixed capacity commitment/cost
#   regardless of ACTUAL usage -- for a feature with genuinely uncertain
#   (possibly low) initial usage, this risks paying for capacity that
#   goes underutilized, a real, poorly-matched cost structure for the
#   stated uncertainty.
#
# ------------------------------------------------------------------------
# APPROACH C: Launch on Standard capacity (A) to validate real usage
# patterns, with an explicit, planned re-evaluation checkpoint (e.g.
# after 4-6 weeks of real traffic data) to decide whether to migrate
# specific high-volume/latency-sensitive paths to PTU (B)
# ------------------------------------------------------------------------
#   WHY VALID: directly sequences the decision correctly given the
#   stated uncertainty -- per L02, this avoids B's risk of committing to
#   PTU capacity before real usage data justifies the specific sizing,
#   while still planning explicitly to capture B's latency-consistency
#   benefit once actual demand (and which SPECIFIC paths need
#   consistency most) is known.
#   COST: accepts A's latency-variability risk during the initial
#   evaluation window -- if latency consistency is CRITICAL from
#   literally day one (not just "matters," but a hard launch
#   requirement), this deferred approach doesn't meet that bar, and the
#   team needs to have genuinely committed to actually doing the
#   re-evaluation, not just planned to in theory and never revisited it
#   under the pressure of shipping the next feature.
#
# COMPARISON TABLE (Case Study 1):
#   | Approach | Latency consistency | Cost-usage matching | Fits genuine usage uncertainty |
#   |----------|--------------------------|---------------------------|---------------------------------------|
#   | A: Standard only | Lower, shared capacity | Best | Best |
#   | B: PTU from day one | Best | Worst (fixed cost regardless of usage) | Worst |
#   | C: Standard, then evaluate for PTU migration | Deferred | Good | Good |
#   Given the case study's EXPLICIT usage uncertainty, C is the
#   strongest sequencing; B is only right if latency consistency is a
#   genuine, non-negotiable day-one launch requirement that justifies
#   paying for capacity ahead of confirmed demand.


# ============================================================================
# CASE STUDY 2 — BUILDING A DOCUMENT-PROCESSING PIPELINE (EXTRACT
# STRUCTURED DATA FROM SCANNED INVOICES)
# ============================================================================
#
# SETUP: processing scanned invoices to extract structured fields
# (vendor name, amount, date, line items) at moderate volume.
#
# ------------------------------------------------------------------------
# APPROACH A: Azure AI Document Intelligence's prebuilt invoice model
# (L03)
# ------------------------------------------------------------------------
#   WHY VALID: per L03, the prebuilt invoice model is specifically
#   trained for exactly this document type -- zero training data or
#   custom model development needed, fastest path to a working solution,
#   and Microsoft's prebuilt models are trained on a very large, diverse
#   set of real invoice formats.
#   COST: per L03, a PREBUILT model is optimized for COMMON invoice
#   layouts/fields -- if the organization's actual invoices have
#   unusual, non-standard fields or layouts specific to their industry/
#   vendors, the prebuilt model may extract those specific fields poorly
#   or not at all, a real accuracy ceiling for genuinely non-standard
#   documents.
#
# ------------------------------------------------------------------------
# APPROACH B: A custom-trained Document Intelligence model (L03),
# trained on the organization's OWN labeled invoice samples
# ------------------------------------------------------------------------
#   WHY VALID: per L03, custom training directly addresses A's
#   limitation -- a model trained on the organization's SPECIFIC vendors
#   and invoice formats can achieve meaningfully higher accuracy on
#   those specific documents than a general-purpose prebuilt model,
#   especially for unusual fields the prebuilt model wasn't trained to
#   recognize at all.
#   COST: per L03, requires collecting and LABELING a real training
#   dataset of the organization's own invoices -- genuine, real upfront
#   effort (data collection, labeling, validation) before any model
#   exists at all, a cost prebuilt models entirely avoid.
#
# ------------------------------------------------------------------------
# APPROACH C: A hybrid -- use the prebuilt invoice model (A) as a FIRST
# PASS for the common, standard fields it handles well, with Azure
# OpenAI (L02) used as a fallback/supplement specifically for extracting
# any unusual, non-standard fields the prebuilt model misses or
# extracts unreliably
# ------------------------------------------------------------------------
#   WHY VALID: combines A's zero-training-data speed for standard fields
#   with a flexible LLM-based approach (which can be prompted to extract
#   arbitrary custom fields without needing a labeled training set)
#   specifically for the non-standard portions A struggles with --
#   avoids B's full custom-training-data cost while still handling
#   organization-specific fields.
#   COST: genuinely more architecturally complex than either A or B
#   alone -- two different extraction mechanisms to build, monitor, and
#   reconcile (what happens when they disagree on a field both could in
#   principle extract), and an LLM-based extraction fallback needs its
#   own accuracy validation (LLM Core Theory Notes L07's evaluation
#   concerns), since LLM-extracted structured data isn't automatically
#   reliable just because it's easy to prompt for.
#
# COMPARISON TABLE (Case Study 2):
#   | Approach | Setup speed | Accuracy on standard fields | Accuracy on non-standard/unusual fields |
#   |----------|-----------------|------------------------------------|-------------------------------------------------|
#   | A: prebuilt model only | Fastest | Good | Poor |
#   | B: custom-trained model | Slowest (needs labeled data) | Best (if trained well) | Best (if trained well) |
#   | C: prebuilt + LLM fallback for unusual fields | Fast | Good | Good, with validation needed |
#   Start with A to validate the actual gap (does the organization's
#   real invoice set genuinely have fields the prebuilt model misses);
#   if the gap is real and significant, B is the strongest long-term
#   accuracy answer if the labeling investment is justified by volume;
#   C is the pragmatic middle ground when full custom training isn't
#   yet justified but real gaps exist.


# ============================================================================
# CASE STUDY 3 — CHOOSING BETWEEN SEMANTIC KERNEL AND THE AI FOUNDRY
# AGENT SERVICE FOR A NEW AGENTIC FEATURE
# ============================================================================
#
# SETUP: building an agent that helps internal employees query company
# knowledge and take simple actions (e.g. submit a time-off request) --
# deciding on the Azure-native agent-building approach (L06, L07).
#
# ------------------------------------------------------------------------
# APPROACH A: Semantic Kernel (L06), self-orchestrated within the
# team's own application
# ------------------------------------------------------------------------
#   WHY VALID: per L06, Semantic Kernel gives full, direct control over
#   the orchestration logic (plugins, planners, memory) within code the
#   team owns and can customize arbitrarily -- appropriate when the
#   agent's behavior needs genuinely custom logic that a more
#   opinionated managed service might not accommodate cleanly.
#   COST: per L06, the team owns ALL the operational plumbing --
#   hosting, scaling, conversation-state management, and integrating
#   whatever human-in-the-loop or tool-execution infrastructure the
#   agent needs -- real, ongoing engineering investment beyond just the
#   agent logic itself.
#
# ------------------------------------------------------------------------
# APPROACH B: The AI Foundry Agent Service (L07), a managed agent
# hosting/orchestration platform
# ------------------------------------------------------------------------
#   WHY VALID: per L07, this provides managed hosting, built-in human-
#   in-the-loop tooling, and orchestration infrastructure OUT OF THE BOX
#   -- meaningfully less operational burden than A for a team that
#   doesn't want to build/maintain that infrastructure themselves,
#   letting the team focus on the agent's actual task-specific logic and
#   tool integrations.
#   COST: per L07, adopting a managed service means working within ITS
#   specific abstractions and constraints -- less flexibility for
#   genuinely unusual orchestration patterns than A's full-code-control
#   approach, and creates a real dependency on the service's specific
#   feature set and roadmap.
#
# ------------------------------------------------------------------------
# APPROACH C: Start with the AI Foundry Agent Service (B) for the
# INITIAL version (it likely covers "query company knowledge" and
# "submit a simple form-like request" well within its standard
# capabilities), with an explicit plan to migrate specific components to
# Semantic Kernel (A) ONLY IF a genuinely custom orchestration need
# emerges that the managed service can't accommodate
# ------------------------------------------------------------------------
#   WHY VALID: per L06-L07's own framing (comparable to Case Study 1's
#   Standard-then-PTU sequencing), starting with the lower-operational-
#   burden managed option and only reaching for full custom control once
#   a SPECIFIC, confirmed need justifies it avoids over-engineering B's
#   flexibility before it's actually required -- this case study's
#   stated use cases (knowledge query, simple form submission) sound
#   like exactly what a managed agent service is built to handle well.
#   COST: if the team already has strong intuition that HIGHLY custom
#   orchestration will be needed soon (e.g. complex, multi-system
#   approval workflows planned for a near-term roadmap), starting with B
#   and migrating later is a real, avoidable detour versus just building
#   on A from the start -- this sequencing is only the RIGHT call when
#   that certainty doesn't yet exist.
#
# COMPARISON TABLE (Case Study 3):
#   | Approach | Operational burden | Orchestration flexibility | Fits THIS case study's stated (fairly standard) use cases |
#   |----------|--------------------------|---------------------------------|-------------------------------------------------------------------|
#   | A: Semantic Kernel, self-orchestrated | Highest | Highest | Overkill for the stated needs |
#   | B: AI Foundry Agent Service | Lowest | Lower (managed constraints) | Good fit |
#   | C: B first, migrate to A only if needed | Low initially | Deferred flexibility | Best sequencing for this case study |
#   Given the case study's fairly standard stated use cases, C is the
#   strongest answer -- reach for A's full control specifically once a
#   confirmed, concrete need for it emerges, not preemptively.


# ============================================================================
# CASE STUDY 4 — GOVERNANCE FOR MULTIPLE TEAMS BUILDING AI FEATURES ON
# THE SAME AZURE TENANT
# ============================================================================
#
# SETUP: several product teams are independently building AI features on
# Azure OpenAI within the same company, currently each managing their
# own resource, quota, and content-filtering configuration ad hoc.
#
# ------------------------------------------------------------------------
# APPROACH A: Leave each team fully autonomous -- separate Azure OpenAI
# resources, separate configuration, no central coordination
# ------------------------------------------------------------------------
#   WHY VALID: maximum team autonomy and speed -- no cross-team
#   coordination overhead, each team configures exactly what THEY need
#   without waiting on or negotiating with a central authority, genuinely
#   valuable for a small number of teams with low coordination cost.
#   COST: per L01/L07-L08's AI Hub gateway discussion, this risks real,
#   duplicated inefficiency (multiple teams separately requesting quota
#   for the same region, no shared visibility into total organizational
#   spend/usage) and INCONSISTENT content-filtering/responsible-AI
#   policy across teams -- one team's feature might have meaningfully
#   weaker safety filtering than another's, an inconsistency that's a
#   real governance/compliance risk once someone asks "what's our
#   company-wide AI safety posture."
#
# ------------------------------------------------------------------------
# APPROACH B: A centralized AI Hub gateway (L07) that ALL teams must
# route requests through, with centrally-enforced quota allocation,
# logging, and Responsible AI content-filtering policy
# ------------------------------------------------------------------------
#   WHY VALID: per L07, directly solves A's inconsistency and visibility
#   problems -- one place to see total usage/cost across the
#   organization, and centrally-enforced content filtering means every
#   team's feature meets the SAME safety bar by construction, not by
#   each team's independent, potentially-inconsistent choices.
#   COST: per L07, introduces a real, additional infrastructure
#   dependency (the gateway itself) that every team's request now flows
#   through -- a genuine central point of coordination/potential
#   bottleneck, and requires actual organizational buy-in/migration
#   effort to move existing teams' already-built features onto the
#   centralized gateway.
#
# ------------------------------------------------------------------------
# APPROACH C: A lighter-weight middle ground -- teams keep their own
# Azure OpenAI resources (preserving A's autonomy for resource
# management), but a SHARED, centrally-maintained content-filtering/
# Responsible-AI POLICY (not infrastructure) is mandated and audited
# across all teams' resources, without requiring a full centralized
# gateway
# ------------------------------------------------------------------------
#   WHY VALID: per L08's Responsible AI governance discussion, this
#   specifically addresses the INCONSISTENT-safety-policy risk (arguably
#   the most organizationally urgent part of A's gap) without requiring
#   B's full infrastructure migration -- a lower-friction first step
#   that closes the most pressing governance gap while preserving more
#   team autonomy than B.
#   COST: doesn't solve A's OTHER gap (fragmented usage visibility/quota
#   coordination across teams) -- teams still independently manage their
#   own resources and quota requests, meaning organization-wide cost/
#   usage visibility remains fragmented even after this fix, a real,
#   different gap than the one this approach directly closes.
#
# COMPARISON TABLE (Case Study 4):
#   | Approach | Content-filtering consistency | Usage/cost visibility | Team autonomy | Migration effort |
#   |----------|------------------------------------|-----------------------------|--------------------|-------------------------|
#   | A: fully autonomous teams | Inconsistent | Fragmented | Highest | None |
#   | B: centralized AI Hub gateway | Consistent, enforced | Unified | Lowest | Highest |
#   | C: shared policy, no central gateway | Consistent, enforced | Still fragmented | Medium-high | Medium |
#   For an organization with a SMALL number of teams and low regulatory
#   exposure, C is a reasonable, lower-friction first step; for a
#   larger organization, or one in a regulated industry where "what's
#   our AI safety posture" is a real compliance question that needs a
#   confident, verifiable answer, B is the stronger long-term answer
#   despite its higher migration cost.


if __name__ == "__main__":
    print("This file is reference material -- see the WHAT/WHY header and")
    print("the four case studies above.")
