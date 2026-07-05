# ============================================================
# L07: Capacity Planning — Forecasting Demand, Headroom, Autoscaling Design
# ============================================================
# WHAT: The systematic practice of predicting FUTURE resource needs
#       before you hit them — demand forecasting from historical trends,
#       headroom planning (how much spare capacity to keep, and why),
#       and designing autoscaling policies that actually respond fast
#       enough to real traffic patterns.
# WHY: L06 covered testing what happens UNDER a given load level.
#      Capacity planning is the complementary discipline of PREDICTING
#      what load level you'll actually face, and ensuring capacity is
#      provisioned (or can scale up) fast enough to meet it — the
#      difference between reactive firefighting and proactive readiness.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
DEMAND FORECASTING uses HISTORICAL usage trends (this repo's
Observability Notes covers the metrics infrastructure that provides this
data) to project FUTURE resource needs — accounting for both
long-term GROWTH TRENDS (steady month-over-month traffic increase) and
CYCLICAL/SEASONAL patterns (daily peak hours, weekly patterns, known
seasonal spikes like a retail Black Friday). A naive forecast using only
recent average traffic MISSES both dimensions — it neither projects
forward the growth trend nor anticipates a known seasonal spike, both of
which historical data can reveal if analyzed deliberately rather than
just "look at yesterday's average."

HEADROOM is the deliberate GAP between current provisioned capacity and
actual current usage — NOT provisioning any headroom means any traffic
spike above the current baseline immediately causes degradation before
autoscaling (if any) can react; too MUCH headroom wastes cost on
permanently idle capacity. The right amount of headroom depends on: how
FAST your autoscaling can actually add capacity (if scaling takes 5
minutes, you need enough headroom to absorb 5 minutes of growth at your
worst-case traffic acceleration rate) and how VARIABLE your traffic
actually is (a highly spiky workload needs more headroom than a smooth,
predictable one).

AUTOSCALING POLICY DESIGN is where forecasting and headroom become
concrete, actionable configuration: what METRIC triggers scaling (CPU
utilization, request queue depth, custom application metrics — this
repo's Kubernetes Notes L06 covers HPA/VPA/KEDA mechanics), what
THRESHOLD triggers a scale-up/scale-down action, and critically, the
COOLDOWN/STABILIZATION WINDOW preventing THRASHING (rapidly scaling up
and down in response to normal, brief traffic fluctuation, which wastes
resources on constant instance churn without providing real benefit).
A policy that scales too AGGRESSIVELY (very low threshold, no cooldown)
thrashes; one that scales too CONSERVATIVELY (high threshold, long
cooldown) reacts too slowly to real spikes, defeating the point of
autoscaling at all.

PRODUCTION USE CASE:
A team analyzes 12 months of traffic data before their annual peak
sales event, identifying both the underlying month-over-month growth
trend (accounted for by scaling their BASELINE capacity up
proportionally) and the specific magnitude of last year's peak-event
spike relative to normal traffic (used to size headroom AND validate
their autoscaling policy can actually reach the needed capacity within
the expected traffic ramp-up time) — turning "we hope autoscaling
handles it" into a specifically validated, load-tested (L06) capacity plan.

COMMON MISTAKES:
- Forecasting future capacity needs using only a simple recent-average
  extrapolation, missing both underlying growth trends and known
  seasonal/cyclical patterns that historical data, examined properly,
  would reveal.
- Configuring autoscaling with NO cooldown/stabilization window,
  causing THRASHING — rapid, resource-wasting scale-up/scale-down cycles
  in response to normal, brief traffic noise rather than a genuine sustained change.
- Assuming autoscaling ALONE eliminates the need for capacity planning
  — autoscaling has a REACTION TIME (new instances take time to launch,
  warm up, and start serving traffic) and often a HARD CEILING (a
  configured max instance count, or an underlying resource quota/limit)
  — a traffic spike faster or larger than autoscaling can accommodate
  still causes degradation regardless of how well-configured the
  autoscaling policy is.
"""

import statistics
from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Demand forecasting — trend + seasonality, not just recent average
# ------------------------------------------------------------------
@dataclass
class HistoricalDataPoint:
    day_of_week: int   # 0=Monday .. 6=Sunday
    week_number: int    # for identifying the underlying growth trend
    requests_per_second: float


def naive_forecast(historical_data: list[HistoricalDataPoint]) -> float:
    """THE WRONG WAY: just averages recent data, ignoring both trend and
    seasonality entirely."""
    recent = historical_data[-7:]   # last week
    return statistics.mean(d.requests_per_second for d in recent)


def trend_and_seasonality_aware_forecast(
    historical_data: list[HistoricalDataPoint], target_day_of_week: int,
) -> float:
    """
    A better forecast: (a) identifies the GROWTH TREND by comparing
    early vs late weeks' averages, and (b) accounts for DAY-OF-WEEK
    seasonality by only averaging historical data from the SAME
    day-of-week as the target — a Monday's typical traffic, not a
    blended average across all days.
    """
    same_day_data = [d for d in historical_data if d.day_of_week == target_day_of_week]
    if len(same_day_data) < 2:
        return naive_forecast(historical_data)

    # Trend: compare the FIRST half vs SECOND half of same-day-of-week history
    midpoint = len(same_day_data) // 2
    early_avg = statistics.mean(d.requests_per_second for d in same_day_data[:midpoint])
    late_avg = statistics.mean(d.requests_per_second for d in same_day_data[midpoint:])
    growth_rate_per_period = (late_avg - early_avg) / max(early_avg, 1e-9)

    # Project the trend forward by one more period from the most recent same-day value
    most_recent_same_day = same_day_data[-1].requests_per_second
    return most_recent_same_day * (1 + growth_rate_per_period)


def forecasting_demo():
    # Simulated data: steady growth trend, PLUS Fridays consistently higher
    data = []
    for week in range(8):
        for dow in range(7):
            base = 100 + week * 8   # steady growth ~8 rps/week
            seasonal_bump = 40 if dow == 4 else 0   # Fridays run hotter
            data.append(HistoricalDataPoint(dow, week, base + seasonal_bump))

    naive = naive_forecast(data)
    aware_friday = trend_and_seasonality_aware_forecast(data, target_day_of_week=4)
    aware_tuesday = trend_and_seasonality_aware_forecast(data, target_day_of_week=1)

    print(f"Naive forecast (blended recent average): {naive:.1f} rps")
    print(f"Trend+seasonality aware forecast for next FRIDAY: {aware_friday:.1f} rps")
    print(f"Trend+seasonality aware forecast for next TUESDAY: {aware_tuesday:.1f} rps")
    print("  -> the naive forecast would UNDER-provision for Friday and "
          "OVER-provision for Tuesday, missing both the trend and the "
          "day-of-week pattern the aware forecast captures.")


# ------------------------------------------------------------------
# 2. Headroom sizing — accounting for autoscaling reaction time
# ------------------------------------------------------------------
def calculate_required_headroom(
    current_rps: float, worst_case_growth_rate_per_minute: float,
    autoscaler_reaction_time_minutes: float,
) -> float:
    """
    The MINIMUM headroom needed is however much traffic could grow
    DURING the time it takes autoscaling to actually add capacity — if
    scaling takes 5 minutes and traffic can grow 10%/minute in a worst-
    case spike, you need enough headroom to absorb ~50% additional load
    before new capacity comes online.
    """
    projected_growth_during_reaction = current_rps * (
        (1 + worst_case_growth_rate_per_minute) ** autoscaler_reaction_time_minutes - 1
    )
    return projected_growth_during_reaction


def headroom_demo():
    current = 1000.0
    for reaction_time in [1, 5, 10]:
        headroom_needed = calculate_required_headroom(
            current, worst_case_growth_rate_per_minute=0.10, autoscaler_reaction_time_minutes=reaction_time,
        )
        print(f"  Autoscaler reaction time {reaction_time} min: "
              f"need {headroom_needed:.0f} rps of headroom above current {current:.0f} rps")


# ------------------------------------------------------------------
# 3. Autoscaling policy design — avoiding thrashing
# ------------------------------------------------------------------
AUTOSCALING_POLICY_EXAMPLE = """
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-app
  minReplicas: 4          # HEADROOM baseline — never scale below this,
                            # even at the lowest observed traffic
  maxReplicas: 50           # a hard ceiling — capacity planning must
                              # confirm this is enough for worst-case
                              # forecasted demand, or it becomes the
                              # bottleneck regardless of scaling speed
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60   # scale up before hitting 100% —
                                     # this IS a form of headroom, applied
                                     # at the per-pod level
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0     # react QUICKLY to genuine spikes
      policies:
        - type: Percent
          value: 100                     # can DOUBLE pod count per period
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300     # WAIT 5 min of sustained low
                                            # usage before scaling down —
                                            # this asymmetry (fast up, slow
                                            # down) is the standard THRASHING
                                            # prevention pattern: react fast
                                            # to real spikes, but don't
                                            # immediately reverse on a brief dip
"""


if __name__ == "__main__":
    forecasting_demo()
    print()
    headroom_demo()
    print(AUTOSCALING_POLICY_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
An e-commerce platform's capacity plan for its annual peak sales event
combines all three techniques from this lesson: a trend+seasonality-
aware forecast projects expected peak traffic (accounting for both
year-over-year growth and the specific historical spike pattern of this
particular event), a headroom calculation confirms their autoscaler's
actual 3-minute reaction time is fast enough given the forecasted
traffic ramp-up rate, and their HPA's scaleUp/scaleDown asymmetry
(aggressive scale-up, conservative scale-down) is validated via a k6
load test (L06) simulating the exact forecasted traffic curve — turning
"we hope it works" into a specifically tested, three-part capacity plan
before the actual event, rather than during it.
"""
