# ============================================================
# L24: Structuring a Contribution, Writing the Paper, and Publishing
# ============================================================
# WHAT: How to turn a reproducible finding (L23) into an actual research
#       contribution — what makes a contribution "novel enough," the
#       standard paper structure and what each section actually needs to
#       do, and where solo/independent researchers realistically publish.
# WHY (RESEARCH): This is the lesson that turns everything else in this
#      curriculum into an actual output artifact. Technical skill without
#      knowing how to package and communicate a contribution doesn't
#      become a published paper.
# LEVEL: Research Methods (Phase 7 of 8 — final methodology lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
A research contribution needs to be able to answer: "what do we know now
that we didn't know before, and why should anyone believe it?" There are
several LEGITIMATE shapes a contribution can take (not just "brand new
algorithm"):

  1. NOVEL METHOD — a new technique (like GPTQ/AWQ/SmoothQuant were,
     when first published). Highest bar, but not the only valid shape.
  2. EMPIRICAL CHARACTERIZATION — rigorously answering an open question
     (from L16's list, or one you find yourself) that nobody has
     carefully measured yet, even without a new algorithm. E.g. "how does
     quantization error compound across multi-step reasoning" is a
     legitimate, publishable contribution if answered rigorously, with
     NO new method required.
  3. NEGATIVE RESULT — showing a plausible-sounding approach does NOT
     work, with rigor (L23) explaining why. Underrated, genuinely useful
     to the field, and often easier to execute well than a from-scratch
     novel method.
  4. SYSTEMS CONTRIBUTION — a real, working, benchmarked implementation
     that makes an existing technique meaningfully more practical (faster
     kernel, better memory management, wider hardware support) — this is
     the natural output of Phase 5-6's work, and venues like MLSys are
     specifically built for exactly this kind of contribution.

STANDARD PAPER STRUCTURE, and what each section must actually DO (not
just contain):
  - Abstract: states the CLAIM and the HEADLINE evidence in ~150 words —
    a reader should know if this paper is relevant to them from the
    abstract alone.
  - Introduction: motivates WHY this problem matters, states the
    contribution explicitly (often as a bulleted list), and previews the
    key result.
  - Related Work: positions your contribution RELATIVE to existing work
    — not just a list of citations, but an argument for what gap remains.
  - Method: enough detail that a competent reader could REPRODUCE it —
    this is the section reviewers scrutinize hardest for the exact
    protocol-precision discussed in L23.
  - Experiments: the evaluation protocol, baselines, and RESULTS WITH
    UNCERTAINTY (per L23) — a table without error bars/multiple seeds is
    a common, fixable weakness reviewers will flag.
  - Limitations: an HONEST section on what doesn't work or wasn't tested
    — modern venues increasingly require this explicitly, and a paper
    with NO stated limitations reads as less credible, not more.

PRODUCTION/RESEARCH USE CASE:
For your stated goals (publish papers, build hardware-efficiency
tooling), a realistic FIRST target is a WORKSHOP paper or an arXiv
preprint with a solid systems/empirical contribution (categories 2-4
above) rather than aiming immediately for a top-tier novel-method paper
at NeurIPS/ICML — this is not a lesser goal, it's the correct on-ramp:
build a track record of rigorous, honest, well-scoped work first.

COMMON MISTAKES:
- Scoping a first paper too AMBITIOUSLY ("I'll invent a new quantization
  paradigm") instead of too NARROWLY-BUT-RIGOROUSLY ("I'll characterize
  exactly how quantization error compounds in a specific, well-defined
  setting") — narrow-and-rigorous is more likely to actually finish and
  be sound.
- Treating the Limitations section as an afterthought to minimize, rather
  than genuine content — reviewers (and readers building on your work)
  need to know where the boundaries of your claim actually are.
- Submitting to arXiv/a venue without having someone OTHER than yourself
  read a full draft first — you cannot see your own paper's unclear
  passages or unstated assumptions as well as a fresh reader can; this is
  not optional polish, it's a real error-catching step.
"""

import textwrap


# ------------------------------------------------------------------
# 1. A concrete contribution-scoping checklist
# ------------------------------------------------------------------
CONTRIBUTION_SCOPING_CHECKLIST = [
    "Can I state my claim in ONE precise sentence, with a specific "
    "measurable quantity (not 'improves efficiency', but 'reduces X by "
    "Y% on Z benchmark')?",
    "Have I checked (via L23-style paper reading) that this specific "
    "question hasn't already been rigorously answered? (A quick search "
    "for the most obvious 3-5 keyword combinations, plus checking recent "
    "arXiv listings in the relevant category, catches most overlaps.)",
    "Is the experiment I need to run actually feasible on MY hardware "
    "budget (a single consumer GPU) in a reasonable timeframe? If not, "
    "can the claim be narrowed (smaller model scale, narrower benchmark "
    "set) to something that IS feasible, while still being genuinely "
    "informative?",
    "Do I have a clear, specific BASELINE to compare against, and can I "
    "reproduce that baseline's numbers myself (per L23) before claiming "
    "to beat or characterize it?",
    "If the result comes back NEGATIVE (my method/hypothesis doesn't "
    "pan out), is there still a reportable, honest finding? (If the "
    "answer is 'no, a negative result here is just a dead end with "
    "nothing to say,' the scoping may be too narrow/uninteresting even "
    "before running anything.)",
]


# ------------------------------------------------------------------
# 2. Paper section checklist — what each section must actually contain
# ------------------------------------------------------------------
SECTION_REQUIREMENTS = {
    "Abstract": ["The precise claim, stated as a measurable result.",
                 "One sentence on WHY this matters (motivation).",
                 "The headline number/finding, not just 'we show X improves'."],
    "Introduction": ["The problem, motivated concretely (not just 'LLMs are important').",
                      "An EXPLICIT list of contributions (often literally bulleted).",
                      "A one-sentence preview of the key result."],
    "Related Work": ["Groups prior work by APPROACH, not just chronology.",
                      "States explicitly what gap remains that THIS paper addresses."],
    "Method": ["Enough detail for a competent reader to reproduce it exactly.",
               "Every hyperparameter that affects the result, stated explicitly.",
               "Pseudocode or a clear algorithmic description, not prose-only."],
    "Experiments": ["The exact evaluation protocol (dataset, split, metric).",
                     "Baselines, with a note on how their numbers were obtained "
                     "(reproduced by you, or cited from the original paper).",
                     "Results WITH uncertainty (confidence intervals / multiple seeds)."],
    "Limitations": ["An honest, specific account of what wasn't tested or doesn't work.",
                     "Not a single vague sentence — genuine, useful boundaries."],
}


# ------------------------------------------------------------------
# 3. Realistic publishing venues for independent/solo researchers
# ------------------------------------------------------------------
PUBLISHING_VENUES = {
    "arXiv preprint": "No peer review gate — you can post ANY rigorous "
        "work immediately. This is the standard first step for almost "
        "all ML research now, INCLUDING work later submitted to a "
        "peer-reviewed venue. Establishes a timestamped public record.",
    "Workshop papers (NeurIPS/ICML/ICLR workshops)": "Lower barrier than "
        "the main conference track, often specifically welcoming "
        "in-progress or narrowly-scoped work — a realistic FIRST "
        "peer-reviewed target, with many workshops specifically focused "
        "on efficiency/quantization topics.",
    "MLSys": "A venue SPECIFICALLY for systems contributions (kernels, "
        "serving infrastructure, efficiency work) — often a better fit "
        "for Phase 5-6-flavored contributions than a pure-ML venue.",
    "Open-source contribution + technical report": "Contributing a real, "
        "merged improvement to vLLM/llama.cpp/similar, documented with a "
        "technical writeup (even just a detailed blog post or arXiv "
        "note), is a legitimate, high-signal research artifact — "
        "reviewers and the community weight 'I shipped this and it's "
        "used' very highly, arguably more than a paper nobody reproduces.",
}


def print_scoping_checklist():
    print("Contribution scoping checklist:")
    for i, item in enumerate(CONTRIBUTION_SCOPING_CHECKLIST, 1):
        print(f"  {i}. {item}")


def print_section_requirements():
    for section, requirements in SECTION_REQUIREMENTS.items():
        print(f"\n{section}:")
        for req in requirements:
            print(f"  - {req}")


if __name__ == "__main__":
    print_scoping_checklist()
    print()
    print_section_requirements()

    print("\n\nRealistic venues for independent research:")
    for venue, note in PUBLISHING_VENUES.items():
        print(f"\n{venue}:")
        print(f"  {textwrap.fill(note, width=70, initial_indent='  ', subsequent_indent='  ')}")

"""
RESEARCH/PRODUCTION CONTEXT EXAMPLE:
A concrete, achievable path matching everything built in this curriculum:
(1) pick one of the open questions from L16, or a systems gap from L22's
capstone suggestion; (2) execute it with the reproducibility rigor from
L23; (3) write it up following THIS lesson's section requirements; (4)
post to arXiv first (no gatekeeping, immediate feedback loop possible),
then target a relevant workshop or MLSys for peer review. This is a
genuinely realistic solo-researcher path from "curriculum" to "published,"
not an idealized one — people do exactly this regularly, particularly in
the efficiency/systems corner of ML research this curriculum has been
built around.
"""
