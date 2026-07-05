# ============================================================
# L28: Autoscaling Strategies — Reactive, Predictive, and Scheduled Scaling
# ============================================================
# WHAT: The three fundamental approaches to automatically adjusting
#       capacity in response to (or ahead of) demand — reactive
#       (metric-threshold-based), predictive (forecast-based), and
#       scheduled scaling — and the real risks of getting each one wrong.
# WHY: L27 covered PLACING workloads efficiently onto FIXED capacity.
#      Autoscaling addresses the related but distinct problem of
#      deciding HOW MUCH total capacity should exist at any given
#      moment, adjusting it automatically as demand changes.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
REACTIVE (metric-threshold) AUTOSCALING is the most common approach —
continuously monitor a metric (CPU utilization, request queue depth,
requests per second) and add/remove capacity when it crosses defined
thresholds (e.g. "scale up when average CPU exceeds 70% for 2 minutes").
Its core weakness is INHERENT LAG: by the time a metric crosses its
threshold, demand has ALREADY increased, and new capacity takes real
time to become available (booting a new instance, warming up a
container, becoming ready to receive traffic) — during this LAG WINDOW,
existing capacity is already overloaded, which is precisely why COOLDOWN
PERIODS and requiring a metric to be SUSTAINED (not just momentarily
spiked) before triggering a scaling action are necessary — reacting to
every brief, transient spike would cause constant, wasteful "flapping"
(scaling up and down repeatedly for no sustained reason).

PREDICTIVE AUTOSCALING uses HISTORICAL PATTERNS (this repo's Data
Science Fundamentals Notes' time-series-adjacent statistical concepts)
to FORECAST upcoming demand and provision capacity AHEAD of the actual
need, specifically to eliminate reactive scaling's lag problem — e.g.
learning that traffic reliably spikes every weekday at 9 AM as users
start their workday, and beginning to scale up capacity at 8:45 AM,
BEFORE the metric-based trigger would have fired reactively. This
requires genuinely predictable, recurring patterns to work well — it
performs poorly for GENUINELY novel, unprecedented demand spikes
(a surprise viral event) that have no historical precedent to learn from.

SCHEDULED SCALING is the simplest of the three: capacity changes at
FIXED, KNOWN times based on a static schedule (e.g. "always scale up to
20 instances every weekday morning, scale back down to 5 every
weeknight") — appropriate when demand patterns are HIGHLY predictable
and STABLE over time (a business application used only during
office hours), avoiding both the lag risk of reactive scaling and the
forecasting complexity of predictive scaling for a genuinely simple,
well-understood pattern.

THE THUNDERING HERD PROBLEM is a genuine risk specific to scaling
events: when NEW capacity comes online simultaneously (e.g. 10 new
instances all starting at once), they may ALL attempt to perform the
same expensive startup action simultaneously (e.g. all fetching the
same large configuration/cache-warming data from a shared backend at the
exact same moment) — overwhelming that shared backend precisely at the
moment it's least equipped to help (during an already-elevated-demand
scaling event) — staggered/jittered startup timing is a common
mitigation, spreading each new instance's expensive initialization
across a short time window rather than all simultaneously.

SCALE-DOWN CAUTION deserves equal attention to scale-up: removing
capacity too AGGRESSIVELY or too QUICKLY after a demand spike subsides
risks having to scale back UP again moments later if demand hasn't
genuinely stabilized — asymmetric cooldown periods (scale up quickly to
respond to real demand, scale down more CONSERVATIVELY/slowly to avoid
this "flapping" in the other direction) are a common, deliberate design choice.

PRODUCTION USE CASE:
An e-commerce platform combines all three strategies: SCHEDULED scaling
provisions extra baseline capacity ahead of a known, planned marketing
promotion at a specific time; PREDICTIVE scaling handles the platform's
learned, recurring daily/weekly traffic patterns; and REACTIVE scaling
(with a sustained-threshold requirement and asymmetric up/down cooldowns)
handles genuinely unplanned demand spikes that neither of the other two
strategies anticipated — three complementary layers, each covering a
different category of demand pattern.

COMMON MISTAKES:
- Relying purely on reactive scaling for a workload with KNOWN, planned
  demand spikes (a scheduled sale, a product launch) — the inherent lag
  in reactive scaling means capacity arrives AFTER the initial demand
  surge has already caused degraded performance, exactly when
  performance matters most for a high-visibility event.
- Scaling based on a SINGLE, brief metric spike without requiring it to
  be SUSTAINED — this causes wasteful, disruptive flapping in response
  to normal, transient traffic noise rather than genuine sustained demand changes.
- Scaling DOWN as aggressively/quickly as scaling up — this risks
  removing capacity prematurely during a temporary lull within an
  ongoing demand period, forcing another disruptive scale-up moments
  later; asymmetric, more conservative scale-down cooldowns avoid this thrashing.
"""

import time


# ------------------------------------------------------------------
# 1. Reactive scaling with sustained-threshold and cooldown logic
# ------------------------------------------------------------------
class ReactiveAutoscaler:
    def __init__(self, scale_up_threshold: float = 70.0, sustained_periods: int = 3,
                 cooldown_seconds: float = 60.0):
        self.scale_up_threshold = scale_up_threshold
        self.sustained_periods = sustained_periods
        self.cooldown_seconds = cooldown_seconds
        self.recent_high_readings = 0
        self.last_scale_action_time = 0
        self.current_capacity = 5

    def record_metric(self, cpu_utilization: float, now: float) -> str:
        if cpu_utilization >= self.scale_up_threshold:
            self.recent_high_readings += 1
        else:
            self.recent_high_readings = 0   # reset — needs SUSTAINED high readings, not one spike

        cooldown_active = (now - self.last_scale_action_time) < self.cooldown_seconds

        if self.recent_high_readings >= self.sustained_periods and not cooldown_active:
            self.current_capacity += 2
            self.last_scale_action_time = now
            self.recent_high_readings = 0
            return f"SCALED UP to {self.current_capacity} instances"
        elif cooldown_active:
            return "In cooldown — no action taken despite metric"
        return "No action"


def reactive_scaling_demo():
    autoscaler = ReactiveAutoscaler(sustained_periods=3)
    readings = [50, 75, 80, 85, 90, 40, 88, 92, 95]   # includes a brief dip at index 5

    print("Reactive autoscaling — requires SUSTAINED high readings, not a single spike:")
    t = 0
    for reading in readings:
        action = autoscaler.record_metric(reading, now=t)
        print(f"  t={t}s, CPU={reading}%: {action}")
        t += 20
    print("\n  -> The brief dip to 40% correctly reset the sustained-high")
    print("     counter, avoiding a premature scale-up from noisy, transient readings.")


# ------------------------------------------------------------------
# 2. Predictive scaling — pre-provisioning ahead of a known pattern
# ------------------------------------------------------------------
def predictive_scaling_demo():
    historical_pattern = {
        "08:00": 5, "08:45": 8, "09:00": 20, "12:00": 15, "18:00": 6,
    }
    print("\nPredictive scaling — historical pattern learned from past weekdays:")
    for time_label, typical_capacity_needed in historical_pattern.items():
        print(f"  {time_label} -> typically needs ~{typical_capacity_needed} instances")
    print("\n  -> Capacity is provisioned AHEAD of the 09:00 spike (starting")
    print("     at 08:45), rather than waiting for a reactive metric")
    print("     threshold to fire AFTER the spike has already begun.")


if __name__ == "__main__":
    reactive_scaling_demo()
    predictive_scaling_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A ticket-sales platform combines scheduled scaling (provisioning
substantial extra capacity 30 minutes before a widely-publicized,
time-boxed ticket sale begins) with reactive scaling (using a sustained-
threshold requirement and short cooldowns to handle any additional,
unanticipated surge beyond what was scheduled) — relying on reactive
scaling ALONE for this scenario would mean capacity only starts
increasing AFTER the sale begins and demand has already spiked, by
which point the platform may already be visibly struggling during the
single highest-visibility moment of its year.
"""
