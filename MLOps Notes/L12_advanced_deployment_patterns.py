# ============================================================
# L12: Advanced ML Deployment Patterns — Champion-Challenger, Shadow,
#      Multi-Armed Bandit Rollout
# ============================================================
# WHAT: Three production deployment patterns beyond a simple canary
#       rollout (this repo's Event-Driven & Real-Time AI Systems Notes
#       L09 covered canary+auto-rollback specifically) — CHAMPION-
#       CHALLENGER (an ongoing, permanent comparison, not a temporary
#       rollout phase), SHADOW DEPLOYMENT (a challenger receiving real
#       traffic but its predictions never actually used), and bandit-
#       based traffic allocation (L09's statistical concept, applied
#       here as a deployment MECHANISM).
# WHY: L07's model registry and Event-Driven Notes L09's canary pattern
#      cover the MOST COMMON deployment pattern. This lesson closes out
#      the MLOps additions with the patterns used when a simple canary-
#      then-100% rollout isn't the right fit — genuinely ongoing
#      comparison, zero-risk validation, or dynamic traffic optimization.
# LEVEL: Advanced (final MLOps addition)
# ============================================================

"""
CONCEPT OVERVIEW:
CHAMPION-CHALLENGER is architecturally similar to a canary rollout but
with a different INTENT: rather than a TEMPORARY phase before the
challenger becomes the new champion at 100% traffic, champion-challenger
can be a PERMANENT, ongoing arrangement — the challenger continuously
receives a small, steady percentage of traffic, and its performance is
CONTINUOUSLY compared against the champion, without necessarily ever
"graduating" to full traffic. This is the right pattern when you want
ONGOING, continuous validation that the current champion remains the
best choice (as data distributions drift over time, per this repo's
MLOps Notes L06's drift-detection coverage) rather than a one-time
promotion decision.

SHADOW DEPLOYMENT (also called "dark launch" or "shadow traffic") sends
REAL production traffic to the challenger model, computing its
predictions, but NEVER ACTUALLY USES those predictions to affect any
real user-facing outcome — the champion's predictions are what actually
get served; the challenger's predictions are logged and compared
OFFLINE afterward. This gives you the STRONGEST possible risk guarantee
(a badly broken challenger literally cannot affect any real user,
because its output is never used for anything) at the cost of not being
able to measure metrics that depend on the model's prediction actually
being ACTED UPON (e.g. you can't measure a shadow model's effect on
click-through rate, since users never actually see its recommendations)
— shadow deployment validates PREDICTION QUALITY/LATENCY/ERROR RATE
safely, but not downstream BEHAVIORAL impact.

BANDIT-BASED TRAFFIC ALLOCATION applies L09's multi-armed bandit
statistics as an actual DEPLOYMENT mechanism rather than just an
analysis technique — instead of a fixed canary percentage or a static
champion-challenger split, the traffic allocation between models
DYNAMICALLY shifts based on accumulating evidence of which model is
performing better, in real time — appropriate when you want the system
to automatically minimize the cost of running an underperforming
variant, at the cost of the more complex statistical interpretation L09 covered.

PRODUCTION USE CASE:
A fraud-detection team runs their current model as a PERMANENT champion
with a NEW modeling approach as an ongoing challenger receiving a steady
5% of traffic, continuously compared — rather than a one-time "graduate
or reject" decision, this ongoing comparison lets them detect if EITHER
model's relative performance shifts over time (e.g. fraud patterns
evolving in a way that favors one model's approach over the other) as an
ongoing signal, not a point-in-time evaluation.

COMMON MISTAKES:
- Using shadow deployment to validate a model change and concluding
  "it's safe to fully roll out" based ONLY on shadow results, without
  recognizing that shadow deployment cannot measure DOWNSTREAM
  BEHAVIORAL effects (since predictions are never actually used) — a
  model that looks fine in shadow mode can still have unexpected
  behavioral effects once its predictions actually start being ACTED UPON.
- Treating champion-challenger as just a slower canary rollout, missing
  its actual value as an ONGOING, continuous comparison mechanism —
  prematurely "graduating" a challenger to 100% traffic defeats the
  point of an intentionally PERMANENT comparison architecture.
- Using bandit-based dynamic allocation for a decision that needs a
  clean, stakeholder-presentable statistical result (L09's guidance
  applies here directly) — the dynamically-shifting traffic split
  complicates after-the-fact interpretation in ways a fixed-split
  approach avoids.
"""

from dataclasses import dataclass, field


# ------------------------------------------------------------------
# 1. Champion-challenger — an ongoing, permanent comparison
# ------------------------------------------------------------------
@dataclass
class ModelPerformanceWindow:
    model_name: str
    predictions_served: int = 0
    correct_predictions: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct_predictions / self.predictions_served if self.predictions_served else 0


class ChampionChallengerSystem:
    """
    Unlike a temporary canary, this arrangement is INTENDED to persist —
    the challenger's traffic percentage is a steady-state configuration,
    not a ramping phase toward eventual 100% promotion.
    """

    def __init__(self, champion: str, challenger: str, challenger_traffic_pct: int = 5):
        self.champion = champion
        self.challenger = challenger
        self.challenger_traffic_pct = challenger_traffic_pct
        self.performance: dict[str, ModelPerformanceWindow] = {
            champion: ModelPerformanceWindow(champion),
            challenger: ModelPerformanceWindow(challenger),
        }

    def route_and_record(self, request_id: int, was_correct: bool):
        # Deterministic routing based on request_id, standing in for a
        # real consistent-hashing traffic split.
        model = self.challenger if (request_id % 100) < self.challenger_traffic_pct else self.champion
        window = self.performance[model]
        window.predictions_served += 1
        if was_correct:
            window.correct_predictions += 1

    def compare(self) -> dict:
        return {name: w.accuracy for name, w in self.performance.items()}


# ------------------------------------------------------------------
# 2. Shadow deployment — real traffic, zero user-facing risk
# ------------------------------------------------------------------
@dataclass
class ShadowComparisonLog:
    champion_prediction: str
    shadow_prediction: str
    matched: bool


class ShadowDeployment:
    def __init__(self, champion_model, shadow_model):
        self.champion_model = champion_model
        self.shadow_model = shadow_model
        self.comparison_logs: list[ShadowComparisonLog] = []

    def handle_request(self, request_input: dict) -> str:
        # The CHAMPION's prediction is what actually gets returned/used.
        champion_output = self.champion_model(request_input)

        # The SHADOW model ALSO runs on this same real request, but its
        # output is only LOGGED, never returned to the caller or used to
        # affect any real outcome — this is the entire safety guarantee.
        shadow_output = self.shadow_model(request_input)
        self.comparison_logs.append(ShadowComparisonLog(
            champion_output, shadow_output, matched=(champion_output == shadow_output),
        ))

        return champion_output   # ONLY the champion's output is ever actually used

    def agreement_rate(self) -> float:
        if not self.comparison_logs:
            return 0.0
        matches = sum(1 for log in self.comparison_logs if log.matched)
        return matches / len(self.comparison_logs)


def shadow_deployment_demo():
    def champion_model(x):
        return "approve" if x["score"] > 0.5 else "reject"

    def shadow_model(x):
        # A slightly different decision boundary — simulating a genuinely
        # different (in this case, subtly disagreeing) challenger model.
        return "approve" if x["score"] > 0.45 else "reject"

    shadow = ShadowDeployment(champion_model, shadow_model)
    test_requests = [{"score": s} for s in [0.3, 0.47, 0.6, 0.44, 0.9]]

    for req in test_requests:
        result = shadow.handle_request(req)
        print(f"  request score={req['score']}: champion returned '{result}' "
              f"(the only output actually used)")

    print(f"\n  Champion/shadow agreement rate: {shadow.agreement_rate():.0%}")
    print("  -> disagreements identify SPECIFIC inputs where the models "
          "diverge, worth investigating BEFORE ever letting the shadow "
          "model's predictions affect a real decision — but note this "
          "tells you nothing about DOWNSTREAM behavioral effects, since "
          "no user ever actually saw the shadow model's output.")


# ------------------------------------------------------------------
# 3. Choosing between patterns
# ------------------------------------------------------------------
PATTERN_SELECTION_GUIDE = {
    "Canary + eventual 100% rollout (Event-Driven Notes L09)": "A ONE-TIME "
        "promotion decision — the challenger is EXPECTED to become the new "
        "champion if it performs well.",
    "Champion-Challenger (ongoing)": "A PERMANENT comparison arrangement — "
        "used when continuous validation against an alternative approach "
        "is valuable indefinitely, not just during a rollout window.",
    "Shadow Deployment": "Maximum safety validation for prediction "
        "quality/latency/errors on REAL traffic, with ZERO risk to real "
        "outcomes — but cannot measure downstream behavioral impact.",
    "Bandit-based allocation (L09)": "Dynamic, self-optimizing traffic "
        "split — minimizes the cost of an underperforming variant during "
        "evaluation, at the cost of more complex statistical interpretation.",
}


if __name__ == "__main__":
    print("--- Champion-Challenger (ongoing) ---")
    system = ChampionChallengerSystem("fraud_model_v2", "fraud_model_v3_experimental",
                                        challenger_traffic_pct=5)
    import random
    random.seed(0)
    for i in range(1000):
        system.route_and_record(i, was_correct=random.random() < 0.92)
    print(f"  Comparison: {system.compare()}")

    print("\n--- Shadow Deployment ---")
    shadow_deployment_demo()

    print("\n=== Pattern selection guide ===")
    for pattern, note in PATTERN_SELECTION_GUIDE.items():
        print(f"{pattern}:\n  {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A payments platform validates a completely rearchitected fraud model
(a genuinely risky change, not an incremental update) via SHADOW
DEPLOYMENT for two weeks first — confirming prediction latency and
error rates are acceptable with zero risk to real transactions — THEN
transitions to a standard canary rollout (Event-Driven Notes L09) for
the actual traffic ramp, and FINALLY, once fully rolled out, the
previous model is kept running as an ONGOING CHAMPION-CHALLENGER at 3%
traffic for continuous comparison — three different patterns from this
lesson and L09, each serving a DIFFERENT phase and risk profile of the
same overall model transition.
"""
