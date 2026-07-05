# ============================================================
# L03: NATS vs Kafka — A Decision Framework
# ============================================================
# WHAT: A direct, practical comparison between NATS/JetStream (L02) and
#       Apache Kafka (covered in depth in this repo's Apache Kafka
#       Notes) — operational overhead, throughput ceiling, ecosystem
#       maturity — and a framework for choosing between them based on
#       actual scale and requirements, not popularity.
# WHY: Both solve "durable, ordered, replayable event streaming" — but
#      they make different engineering tradeoffs that matter enormously
#      at different scales. Choosing based on which is more widely
#      discussed, rather than your actual throughput/ops-overhead needs,
#      is the single most common mistake in this decision.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
KAFKA (this repo's Apache Kafka Notes covers its internals in depth —
partitions, consumer groups, exactly-once semantics, KRaft) is built for
VERY HIGH THROUGHPUT (millions of messages/second at scale) with strong
ordering guarantees WITHIN a partition, and has by far the more MATURE
ecosystem — Kafka Connect for integrations, Kafka Streams/ksqlDB for
stream processing, and broad tooling/operational knowledge across the
industry. This maturity and throughput ceiling comes with real
OPERATIONAL WEIGHT: even with KRaft removing the ZooKeeper dependency,
running Kafka well at scale (partition rebalancing, broker sizing,
retention tuning, monitoring consumer lag) is a genuine, ongoing
operational discipline requiring dedicated expertise.

NATS/JetStream (L02) is architecturally much SIMPLER — a single NATS
server binary (or a small clustered deployment) with dramatically lower
resource footprint and operational surface area than a Kafka cluster.
At MODERATE throughput (the CV's explicit reference point: "thousands-
per-day scale"), this translates to genuinely lower total cost of
ownership — fewer moving parts to monitor, patch, and reason about
during an incident, and a much shallower learning curve for a small team
to operate confidently. NATS's ecosystem (stream processing, connectors)
is real but meaningfully less mature/extensive than Kafka's.

The decision, made concrete: at THOUSANDS of events per day
(order-of-magnitude a few messages per second sustained, with bursts),
Kafka's throughput ceiling is wildly beyond what's needed — you'd be
paying Kafka's full operational complexity tax for headroom the workload
will never approach using. At MILLIONS of events per second, Kafka's
purpose-built throughput engineering and mature ecosystem tooling become
genuinely necessary, and NATS/JetStream would likely require far more
custom scaling work to reach comparable throughput reliably. The
crossover point isn't a fixed number — it's a genuine "measure your
actual and projected throughput, and honestly assess your team's
operational capacity for a Kafka cluster" question.

PRODUCTION USE CASE:
A team building a real-time trigger-evaluation platform (L05) processing
customer lifecycle events at THOUSANDS PER DAY explicitly chooses NATS/
JetStream over Kafka specifically because, at that volume, Kafka's
operational overhead (a multi-broker cluster, partition planning,
dedicated on-call expertise) would be disproportionate to the actual
throughput need — NATS's single-binary simplicity gets the SAME
durability/replay guarantees (via JetStream) the use case requires, at
roughly a tenth of the operational burden, by the team's own estimate.

COMMON MISTAKES:
- Choosing Kafka by default because it's the more widely known/
  discussed option, without actually measuring whether the workload's
  throughput justifies its operational complexity — "everyone uses
  Kafka" is not itself evidence that YOUR specific, moderate-throughput
  workload needs it.
- Choosing NATS for a workload that's ALREADY at or approaching Kafka-
  scale throughput, then hitting real scaling friction that Kafka's more
  mature, purpose-built-for-this-scale architecture would have handled
  more naturally — measure actual/projected throughput honestly BEFORE
  committing, not after hitting a wall.
- Treating this as a permanent, un-revisitable choice — a system that
  starts on NATS at moderate scale and later needs to migrate to Kafka
  as throughput genuinely grows is a legitimate, sometimes-necessary
  evolution, not evidence the original choice was wrong for its original scale.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Direct comparison matrix
# ------------------------------------------------------------------
@dataclass
class ComparisonDimension:
    dimension: str
    nats_jetstream: str
    kafka: str


COMPARISON_MATRIX = [
    ComparisonDimension(
        "Throughput ceiling",
        "Solid at moderate throughput (thousands to low millions/day); "
        "scaling further requires more deliberate cluster design",
        "Purpose-built for very high sustained throughput (millions/sec "
        "at scale) — this is Kafka's core engineering focus",
    ),
    ComparisonDimension(
        "Operational overhead",
        "Low — a single binary or small cluster, minimal moving parts, "
        "shallow learning curve for a small team",
        "Higher — broker sizing, partition rebalancing, retention "
        "tuning, dedicated operational expertise typically needed at scale",
    ),
    ComparisonDimension(
        "Ecosystem maturity",
        "Real but less extensive — growing stream-processing/connector "
        "ecosystem, smaller pool of operational war-stories/tooling",
        "Very mature — Kafka Connect, Kafka Streams, ksqlDB, broad "
        "industry operational knowledge and tooling",
    ),
    ComparisonDimension(
        "Ordering guarantees",
        "Per-subject ordering within JetStream",
        "Strong per-PARTITION ordering, with well-understood patterns "
        "for partitioning strategy (this repo's Kafka Notes L04)",
    ),
    ComparisonDimension(
        "Resource footprint",
        "Small — meaningfully lower memory/CPU/disk footprint per unit "
        "of achieved throughput at moderate scale",
        "Larger — JVM-based brokers, more resource-intensive per node, "
        "amortized well at Kafka's target high-throughput scale",
    ),
]


def print_comparison():
    for c in COMPARISON_MATRIX:
        print(f"{c.dimension}:")
        print(f"  NATS/JetStream: {c.nats_jetstream}")
        print(f"  Kafka:          {c.kafka}\n")


# ------------------------------------------------------------------
# 2. A concrete decision calculator
# ------------------------------------------------------------------
def estimate_ops_overhead_ratio(events_per_day: int, team_kafka_expertise: bool) -> dict:
    """
    A simplified, illustrative heuristic — NOT a precise formula, but a
    concrete way to reason about the crossover point rather than relying
    purely on intuition or popularity.
    """
    events_per_second_avg = events_per_day / 86400

    if events_per_second_avg < 100 and not team_kafka_expertise:
        recommendation = "NATS/JetStream — throughput is well within its "\
                          "comfortable range, and Kafka's operational tax " \
                          "isn't justified without existing team expertise"
    elif events_per_second_avg < 100 and team_kafka_expertise:
        recommendation = "Either is reasonable — NATS is simpler, but if "\
                          "the team ALREADY operates Kafka elsewhere, "\
                          "reusing that expertise/infrastructure may win"
    elif events_per_second_avg >= 10_000:
        recommendation = "Kafka — approaching throughput levels where its "\
                          "purpose-built engineering and mature ecosystem " \
                          "tooling become genuinely necessary"
    else:
        recommendation = "Genuinely depends on projected GROWTH trajectory "\
                          "and team's operational capacity — measure and " \
                          "revisit, don't decide purely on current volume alone"

    return {
        "events_per_second_avg": round(events_per_second_avg, 2),
        "recommendation": recommendation,
    }


if __name__ == "__main__":
    print_comparison()

    print("=== Decision calculator examples ===")
    scenarios = [
        (5_000, False),      # thousands/day, no existing Kafka expertise
        (500_000, True),     # higher volume, team already knows Kafka
        (50_000_000, False), # very high volume
    ]
    for events_per_day, has_expertise in scenarios:
        result = estimate_ops_overhead_ratio(events_per_day, has_expertise)
        print(f"  {events_per_day:,} events/day, kafka_expertise={has_expertise}: "
              f"{result['events_per_second_avg']} events/sec avg -> {result['recommendation']}")

"""
PRODUCTION CONTEXT EXAMPLE:
A Gen-AI platform team building real-time trigger evaluation for
customer lifecycle events explicitly measures their expected volume
(low thousands of events per day, well under 1 event/second sustained
average) and their team's existing operational familiarity (no dedicated
Kafka expertise on the team) before choosing NATS/JetStream — their own
estimate of roughly 10x lower operational overhead compared to standing
up and operating even a small Kafka cluster for that same moderate
throughput was the deciding, MEASURED factor, not a default preference
for either technology.
"""
