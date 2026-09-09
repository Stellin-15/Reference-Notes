# Technical Leadership & Staff Engineering — In-Depth Reference

The career-layer material every other domain in this repo assumes you'll
eventually need but never teaches directly — RFC writing, tech-debt
negotiation, cross-team influence, and what actually changes at Staff/Principal level.


## 1. WHAT ACTUALLY CHANGES AT STAFF/PRINCIPAL LEVEL

The core, most commonly cited framing (from Will Larson's "Staff
Engineer"): a Staff+ engineer's IMPACT scales through INFLUENCE and
LEVERAGE, not personal output alone — the same person who wrote the most
code as a senior engineer now spends meaningfully more time on:
architecture decisions that shape MULTIPLE teams' work, unblocking others
(reviewing designs, mentoring, unsticking a stalled cross-team
initiative), and organizational-scale problem identification (noticing a
systemic issue — recurring incidents in one area, a recurring pattern of
teams reinventing the same wheel — before it's escalated to you). The
common failure mode moving into this level: continuing to optimize for
personal code output/heroics rather than the team/org-level leverage that actually defines the role.

**The four "Staff archetypes"** (Larson's framing, genuinely useful as a
self-assessment lens): **Tech Lead** (drives a specific initiative/team's
technical direction), **Architect** (owns technical strategy/consistency
across a wider surface), **Solver** (parachutes into the hardest,
highest-ambiguity problems), **Right Hand** (extends an executive's
reach/judgment across the org) — most Staff+ engineers lean toward one
primarily, and recognizing which archetype fits a given role/situation
clarifies what "doing the job well" actually looks like day to day.


## 2. WRITING TECHNICAL RFCS/DESIGN DOCS THAT ACTUALLY GET READ

A design doc's real job is to get GENUINE feedback before code is
written, when changes are cheap — the actual structure that achieves
this: **context/problem** (why does this matter, what's broken/missing
NOW), **goals and explicit non-goals** (scoping — what this deliberately
doesn't solve is as important as what it does), **proposed solution**
with **alternatives considered and why rejected** (the single most-
skipped section, and the one that prevents "why didn't you just do X"
review comments derailing the doc after the fact), and **risks/open
questions** stated honestly rather than glossed over. A doc that reads
as already-decided (no genuine alternatives, no acknowledged risks)
invites either rubber-stamp approval (no real review happened) or
adversarial pushback (reviewers feel steamrolled) — neither is the goal;
genuine two-way engagement with real tradeoffs on the page is.


## 3. NEGOTIATING TECHNICAL DEBT AGAINST FEATURE PRESSURE

The framing that actually works with non-technical stakeholders:
translate tech debt into the SAME business language feature requests
use — not "the code is messy" (unpersuasive) but "this area has caused N
incidents in the last quarter, and each new feature here takes 2x longer
to build safely because of X" (concrete, comparable cost). Error budgets
(see DevOps & SRE deep dive) formalize this exact negotiation for
reliability specifically — an explicit, PRE-AGREED policy ("when error
budget is exhausted, reliability work takes priority over new features")
removes the need to re-litigate the tradeoff informally, case by case, under pressure, every time.


## 4. CROSS-TEAM INFLUENCE WITHOUT AUTHORITY

Staff+ engineers routinely need to drive change across teams they don't
manage — the practical mechanisms that actually work: building genuine
CONSENSUS through early, informal conversations before a formal proposal
(so the RFC isn't the first time stakeholders hear the idea — a common,
avoidable cause of late, defensive pushback), finding and empowering
ALLIES on affected teams who can advocate from within their own team's
trusted-insider position, and — critically — being willing to do the
unglamorous IMPLEMENTATION work yourself (writing the migration script, doing the first painful integration) rather than only proposing the idea and expecting others to execute it, which builds credibility that pure "ideas person" behavior doesn't.


## 5. NICHE BUT REAL

- **Glue work** — the unglamorous, often-invisible work that makes a
  team function (running the standup nobody else wants to run,
  writing the onboarding doc, coordinating a cross-team launch) — Tanya
  Reilly's well-known essay on this names a real, common pattern where
  this work disproportionately falls on senior engineers (often women)
  and is systematically under-recognized in promotion processes despite
  being genuinely high-leverage — worth knowing this exact framing/vocabulary exists.
- **The "50% rule" for Staff+ time allocation** — a commonly cited
  (not universal) guideline that a Staff engineer should spend roughly
  half their time on hands-on technical work and half on leadership/
  coordination — useful less as a literal target and more as a check
  against drifting entirely into either pure management-adjacent work
  (losing technical credibility/currency) or pure IC work (failing to
  provide the leverage the level actually requires).
- **Blameless postmortems as a leadership skill** (see DevOps & SRE deep
  dive) — facilitating one well is a genuinely distinct, learnable
  leadership skill from writing the postmortem document itself, and a
  real, visible opportunity for a Staff+ engineer to model the
  psychological safety a healthy engineering culture depends on.
- **Sponsorship vs mentorship, precisely distinguished** — mentorship is
  ADVICE given directly to someone; sponsorship is ADVOCACY for someone
  in rooms they're not in (recommending them for a project, vouching for
  their readiness for promotion) — genuinely different, and Staff+
  engineers are increasingly expected to actively SPONSOR more junior
  engineers, not just informally mentor when asked.
- **Technical vision documents** — distinct from a single RFC (which
  solves one specific problem), a vision doc articulates where a
  system/domain should be in 1-3 years, providing the context against
  which individual RFCs/decisions can be evaluated for consistency — a
  genuinely higher-leverage, harder-to-write artifact than a typical
  design doc, and a common explicit expectation at Principal level specifically.
