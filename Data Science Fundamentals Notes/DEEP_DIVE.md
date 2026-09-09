# Data Science Fundamentals — Principal Engineer Deep Dive

Companion to L01-L09. Narrative depth, then a comprehensive common-to-
uncommon reference.


## The Base Rate Fallacy — Why Bayes' Theorem Is a Production Concern, Not Just Theory

**Beyond the lesson**: The base rate fallacy isn't a textbook curiosity —
it's THE reason a "99% accurate" fraud/disease/spam detector can still be
practically useless. If the true positive RATE (base rate) of what you're
detecting is genuinely rare (say, 1 in 10,000 transactions is fraud), even
a highly accurate classifier with a small false-positive rate will flag
FAR MORE false positives than true positives in absolute terms, because
the sheer volume of genuinely negative cases dwarfs the rare positive
ones. This is a real, common product-and-ML miscommunication: a model
with "99% accuracy" sounds great to a non-technical stakeholder, but
Bayes' theorem applied to the actual base rate often reveals its
PRECISION (of everything it flags, how much is actually true) is much lower than that headline number implies.

**Worked example**: A disease-screening test with 99% sensitivity (catches
99% of actual cases) and 99% specificity (correctly clears 99% of healthy
people), applied to a population where the disease's true prevalence is
0.1% — Bayes' theorem shows a POSITIVE test result still only corresponds
to roughly a 9% actual probability of having the disease, because the
99% of the healthy population, even at a 1% false-positive rate, produces
far more false positives in absolute count than the rare true positives
among the 0.1% who are actually sick — a genuinely counterintuitive,
frequently-tested interview calculation.

**Interview Q&A**:
- *Q: A stakeholder is excited about a spam filter with "99.9% accuracy." What question do you ask before celebrating?* A: What's the base rate of spam in the traffic, and what's the model's PRECISION and RECALL specifically (not just aggregate accuracy) — if spam is rare, a trivial "always predict not-spam" baseline could also achieve high accuracy while being completely useless, and the real question is how many flagged emails are ACTUALLY spam (precision) and how much real spam gets through (recall).


## Hypothesis Testing & p-values, Precisely (Not Just "p < 0.05")

**Beyond the lesson**: A p-value is the probability of observing data AT
LEAST as extreme as what was measured, ASSUMING the null hypothesis is
true — it is NOT the probability the null hypothesis is true, a
genuinely common and consequential misinterpretation. p < 0.05 doesn't
mean "95% confident the effect is real" — it means "if there were truly
no effect, we'd see data this extreme (or more) only 5% of the time by
chance." The practical production consequence: running MANY simultaneous
A/B tests (or checking a single test's significance repeatedly as data
accumulates — "p-hacking"/optional stopping) dramatically inflates the
real false-positive rate beyond the nominal 5%, which is exactly why
proper experiment design fixes the sample size/stopping rule IN ADVANCE
and applies multiple-comparison corrections (Bonferroni, false discovery
rate control) when running many tests simultaneously.

**Interview Q&A**:
- *Q: A team ran 20 different metric comparisons in one A/B test and found 1 with p < 0.05. Should they trust it?* A: Be skeptical — with 20 independent tests at a 5% significance threshold, you'd EXPECT roughly 1 false positive by chance alone even if nothing real is happening; this is exactly the multiple-comparisons problem, and the correct response is either a Bonferroni-style correction (a much stricter significance threshold per test) or treating that single finding as a hypothesis to be VALIDATED in a dedicated follow-up test, not a confirmed result.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Statistical distributions worth knowing cold
- **Normal distribution** — the Central Limit Theorem's role (see L02):
  the SAMPLING DISTRIBUTION of a mean tends toward normal regardless of
  the underlying population's distribution shape, given a large enough
  sample — this is WHY normal-distribution-based confidence intervals
  are usable even for non-normally-distributed underlying data.
- **Binomial/Poisson** — binomial for a fixed number of yes/no trials;
  Poisson for counting rare events over a continuous interval (server
  errors per hour) — Poisson is the standard model behind capacity-
  planning/rare-event-rate reasoning (see DevOps & SRE deep dive's Little's Law discussion).
- **Power-law/heavy-tailed distributions** — many real-world metrics
  (website traffic per page, city populations, word frequencies) are
  heavy-tailed, not normal — using normal-distribution assumptions (like
  simple averages/standard-deviation-based anomaly thresholds) on
  genuinely heavy-tailed data produces systematically wrong conclusions,
  a real, common data-analysis mistake.

### Experimentation methodology
- **A/A testing** — running an experiment with NO actual difference
  between variants, specifically to validate the experimentation
  PLATFORM itself isn't introducing bias/bugs before trusting its real A/B test results.
- **Network effects & SUTVA violations** — the Stable Unit Treatment
  Value Assumption (that one user's treatment assignment doesn't affect
  another user's outcome) is violated in genuinely networked products
  (social features, marketplaces) — a user's experience can be affected
  by WHICH VARIANT their friends/counterparties were assigned, requiring
  more sophisticated experiment designs (cluster randomization) than naive per-user A/B splitting.
- **Bayesian A/B testing** — an alternative to frequentist hypothesis
  testing that directly estimates "probability that variant B is better
  than A" rather than a p-value against a null hypothesis — increasingly
  popular in industry specifically because its output is more directly
  actionable/interpretable for business stakeholders than frequentist significance testing.

### Optimization & linear algebra depth
- **Convexity, precisely** — a convex loss function guarantees any local
  minimum found by gradient descent IS the global minimum — this is
  exactly why linear/logistic regression's loss functions are
  deliberately convex (guaranteed optimal convergence), while deep neural
  networks' loss landscapes are NOT convex (gradient descent finds SOME
  local minimum, with no guarantee it's globally optimal, though
  empirically this matters less in practice than the theory alone would suggest).


## NICHE BUT REAL

- **Simpson's Paradox** — a trend that holds within EVERY subgroup of
  data can REVERSE when the subgroups are aggregated together — a real,
  genuinely surprising statistical phenomenon that has caused real
  business-metric misinterpretation (a feature that improves conversion
  within every user segment individually can appear to DECREASE overall
  conversion if segment mix shifted simultaneously) — worth knowing by name as a specific, named failure mode to check for.
- **Survivorship bias** — analyzing only the "survivors" of a selection
  process (customers who didn't churn, companies that didn't go bankrupt)
  systematically misses the full picture; a genuinely common, real
  analytical trap in churn analysis and business-metric interpretation
  more broadly.
- **Regression to the mean** — extreme observations tend to be followed
  by less extreme ones purely due to statistical variance, not necessarily
  a real underlying causal effect — a real, common misattribution risk
  when evaluating an intervention applied specifically to underperforming
  units (did the intervention actually help, or would they have partially recovered anyway).
- **Causal inference beyond correlation** — techniques like propensity
  score matching, instrumental variables, and difference-in-differences
  exist specifically to estimate CAUSAL effects from OBSERVATIONAL
  (non-randomized) data when a true randomized experiment isn't feasible
  — a genuinely deep, distinct discipline from standard predictive ML,
  increasingly relevant for product-analytics teams asked to answer "did
  this feature CAUSE the metric change" questions without a clean A/B test available.
