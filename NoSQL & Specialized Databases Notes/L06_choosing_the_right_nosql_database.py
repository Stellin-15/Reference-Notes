# ============================================================
# L06: Choosing the Right NoSQL Database — A Decision Framework
# ============================================================
# WHAT: A systematic decision framework for choosing among key-value,
#       document, wide-column, graph, and time-series databases (L01-L05)
#       — and, critically, when the correct answer is actually "use a
#       relational database instead."
# WHY: L01-L05 covered each database category individually. The
#      genuinely hard, valuable skill is CHOOSING correctly for a real
#      workload — this lesson provides the concrete framework for that
#      decision, rather than leaving it as an implicit exercise.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
THE FRAMEWORK'S FIRST QUESTION SHOULD ALWAYS BE: "does this workload
genuinely need a NoSQL database at all?" — a well-indexed PostgreSQL or
MySQL instance (this repo's SQL Notes) handles a substantial fraction of
real-world workloads perfectly well, including many that FEEL like they
need NoSQL (JSON columns and PostgreSQL's JSONB type provide meaningful
document-store-like flexibility WITHIN a relational database) — reaching
for NoSQL should be a response to a SPECIFIC, identified limitation
(write-throughput ceiling, a data shape genuinely awkward to normalize,
a need for horizontal write scaling beyond what vertical scaling or
read replicas can provide), not a default modernization choice.

THE SECOND QUESTION: "what is the DOMINANT, PERFORMANCE-CRITICAL ACCESS
PATTERN?" — not "what does the data conceptually look like" (a common
but misleading framing) — per L01-L05: direct lookup by a known key at
extreme scale points to key-value (L01); flexible, nested,
evolving-schema records point to document (L01, Full-Stack & Frontend
Essentials Notes L06); massive write throughput with query-by-known-key
points to wide-column (L02); multi-hop relationship traversal as the
CORE, frequent query points to graph (L04); and time-stamped,
time-range-queried, append-only data points to time-series (L05).

THE THIRD QUESTION: "what CONSISTENCY guarantee does this SPECIFIC
operation actually need?" — per this repo's Distributed Systems Theory
Notes L06, this is often a PER-OPERATION decision, not a single
database-wide answer — a shopping cart update might tolerate eventual
consistency; a payment-balance check might require strong consistency —
many modern NoSQL databases (Cassandra, DynamoDB) support TUNING this
per query, which should factor directly into the choice and configuration,
not be treated as an afterthought.

A CONCRETE WALKTHROUGH EXAMPLE — designing storage for a social media
platform: (1) user profile lookups by user ID, high volume, simple
shape -> document or key-value store; (2) activity feed, extremely
high write volume, queried by user ID with time ordering -> wide-column
store (Cassandra/DynamoDB), following L02-L03's query-first design;
(3) "people you may know" via mutual-friend analysis -> graph database
(L04), since this is fundamentally a multi-hop traversal problem;
(4) engagement metrics dashboards (likes/views over time) -> time-series
database (L05); (5) financial transactions/billing records requiring
strong ACID guarantees and complex reporting joins -> a RELATIONAL
database, despite this being a "modern" platform — NOT every piece of
data belongs in NoSQL, and this specific data's requirements (strong
consistency, complex multi-table joins for reporting) are exactly
where relational databases remain the better-suited tool.

POLYGLOT PERSISTENCE (using MULTIPLE database types within one system,
each for its own best-fit workload, as the example above illustrates
directly) is covered in depth in L07 — this lesson's framework is what
DRIVES those individual per-workload choices.

PRODUCTION USE CASE:
See the social media platform walkthrough above — this concrete,
multi-database architecture (document/key-value + wide-column + graph +
time-series + relational, ALL within one platform) is a realistic
reflection of how large-scale production systems actually apply this
decision framework in practice, rather than committing to a single
"best" database technology for every workload.

COMMON MISTAKES:
- Starting the decision process from "which NoSQL database is most
  popular/modern" rather than "what does THIS workload's actual access
  pattern and consistency requirement need" — this produces
  technology-driven rather than requirement-driven architecture
  decisions, a common source of later regret as the mismatch between
  chosen technology and actual needs becomes apparent under real production load.
- Assuming a single database technology must serve an ENTIRE platform's
  needs uniformly — as the social media walkthrough shows, different
  DATA WITHIN THE SAME PLATFORM frequently has genuinely different
  optimal storage technologies; forcing everything into one choice
  sacrifices real performance/cost benefits available from a polyglot approach.
- Dismissing relational databases as "legacy" for a NEW system without
  evaluating whether the workload's actual requirements (strong
  consistency, complex joins, moderate rather than extreme scale) are
  in fact BETTER served by a relational database than by any NoSQL alternative.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The decision framework, as a callable function
# ------------------------------------------------------------------
def recommend_database(
    dominant_access_pattern: str,
    needs_strong_consistency: bool,
    needs_complex_joins: bool,
) -> str:
    if needs_complex_joins and needs_strong_consistency:
        return "Relational database (PostgreSQL/MySQL) — complex joins + strong consistency is exactly its strength"

    pattern_map = {
        "direct key lookup, extreme scale": "Key-Value store (Redis/DynamoDB)",
        "flexible nested documents": "Document store (MongoDB)",
        "massive write volume, known-key queries": "Wide-column store (Cassandra/DynamoDB)",
        "multi-hop relationship traversal": "Graph database (Neo4j)",
        "time-stamped, time-range queries": "Time-series database (InfluxDB/TimescaleDB)",
    }
    return pattern_map.get(dominant_access_pattern, "Default to a relational database unless a specific NoSQL need is identified")


def decision_framework_demo():
    scenarios = [
        {"pattern": "multi-hop relationship traversal", "strong_consistency": False, "complex_joins": False},
        {"pattern": "massive write volume, known-key queries", "strong_consistency": False, "complex_joins": False},
        {"pattern": "billing/financial records", "strong_consistency": True, "complex_joins": True},
    ]
    for scenario in scenarios:
        recommendation = recommend_database(
            scenario["pattern"], scenario["strong_consistency"], scenario["complex_joins"]
        )
        print(f"  Pattern: '{scenario['pattern']}' "
              f"(strong_consistency={scenario['strong_consistency']}, complex_joins={scenario['complex_joins']})")
        print(f"    -> {recommendation}\n")


# ------------------------------------------------------------------
# 2. Full social media platform walkthrough
# ------------------------------------------------------------------
PLATFORM_WALKTHROUGH = textwrap.dedent("""\
    Social media platform — polyglot database decisions, walked through:

    1. User profiles (lookup by user ID, high volume, simple shape)
       -> Document/Key-Value store

    2. Activity feed (extreme write volume, time-ordered by user)
       -> Wide-column store (Cassandra/DynamoDB), query-first schema (L02-L03)

    3. "People you may know" (mutual-friend, multi-hop analysis)
       -> Graph database (L04) — this specific query pattern is graph
          databases' core strength

    4. Engagement metrics dashboards (likes/views over time)
       -> Time-series database (L05)

    5. Billing/subscription records (strong consistency, complex reporting joins)
       -> RELATIONAL database — despite being a "modern" platform, THIS
          data's actual requirements point clearly back to SQL
""")


if __name__ == "__main__":
    decision_framework_demo()
    print(PLATFORM_WALKTHROUGH)

"""
PRODUCTION CONTEXT EXAMPLE:
A startup building a social platform initially tries to force EVERYTHING
into a single MongoDB deployment "to keep things simple" — as the
platform grows, they discover their friend-recommendation queries
(effectively multi-hop graph traversals modeled awkwardly as document
references) become prohibitively slow, and their billing/subscription
logic (needing genuine ACID transactions across multiple related
records) fights against MongoDB's transaction model. Migrating friend
recommendations to Neo4j and billing to PostgreSQL — while KEEPING
MongoDB for what it's genuinely good at (user profiles, content
documents) — directly illustrates this lesson's core lesson: the right
answer is usually POLYGLOT, driven by each workload's actual access
pattern and consistency needs, not a single technology chosen upfront for the whole platform.
"""
