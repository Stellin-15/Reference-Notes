# ============================================================
# L04: Neo4j and Graph Databases — Where Relationships Are the Point
# ============================================================
# WHAT: How graph databases store and query RELATIONSHIP-heavy data
#       fundamentally differently from relational or document databases
#       — the property graph model, Cypher query language, and exactly
#       WHY multi-hop traversal is where graph databases decisively outperform SQL JOINs.
# WHY: L01-L03 covered databases optimized for lookup-by-key access
#      patterns. Graph databases solve a GENUINELY different problem —
#      efficiently traversing RELATIONSHIPS between entities — that
#      neither key-value, document, nor wide-column models handle well.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
THE PROPERTY GRAPH MODEL: data is represented as NODES (entities, e.g.
a Person, a Product) and RELATIONSHIPS (typed, directed connections
between nodes, e.g. `(Alice)-[:FRIENDS_WITH]->(Bob)`) — both nodes and
relationships can hold their own PROPERTIES (key-value attributes, e.g.
a FRIENDS_WITH relationship might have a `since` property). Critically,
relationships in a graph database are FIRST-CLASS, STORED entities —
NOT computed on the fly via a join operation at query time, which is
the fundamental architectural difference that makes graph traversal fast.

WHY SQL JOINS DEGRADE WITH TRAVERSAL DEPTH: finding "friends of friends"
in a relational database requires a JOIN connecting the friendship table
to itself — finding "friends of friends of friends" (3 hops) requires
joining it to itself AGAIN — each additional hop multiplies the
INTERMEDIATE RESULT SET size the query engine must materialize and
filter, and query planners generally struggle to optimize increasingly
deep join chains, causing QUERY TIME TO GROW SUBSTANTIALLY (often worse
than linearly) with traversal depth. In a graph database, traversing
from one node to its relationships is a DIRECT POINTER FOLLOW (each node
stores direct references to its relationships) — traversal COST SCALES
WITH THE SIZE OF THE ACTUAL RESULT (how many nodes/relationships are
genuinely touched), largely INDEPENDENT of how deep the traversal goes
or how large the OVERALL graph is — this property, sometimes called
"index-free adjacency," is the core reason graph databases handle
multi-hop queries so much better than relational JOINs at real scale.

CYPHER (Neo4j's query language) uses an intuitive, VISUAL, ASCII-ART-like
syntax directly mirroring the graph pattern being matched — e.g.
`MATCH (alice:Person {name: 'Alice'})-[:FRIENDS_WITH]->(friend)-[:FRIENDS_WITH]->(friend_of_friend) RETURN friend_of_friend`
reads almost like a description of the actual relationship pattern
being searched for, a genuinely different query-authoring experience
than expressing the same 2-hop traversal as nested SQL JOINs.

WHEN A GRAPH DATABASE IS THE RIGHT CHOICE VS OVERKILL: graph databases
excel when the DOMINANT, PERFORMANCE-CRITICAL access pattern IS
relationship traversal (social networks, recommendation engines,
fraud-detection ring analysis, knowledge graphs — this repo's System
Design Case Studies Notes L12 touched recommendation systems, and
Agentic AI & RAG Notes L10 touched GraphRAG, both adjacent use cases) —
but for data with only OCCASIONAL or SHALLOW relationship needs (a
typical e-commerce catalog with simple one-level category associations),
a relational or document database handles this perfectly well, and
introducing a graph database adds genuine, unjustified operational
complexity for a benefit that never materializes in practice.

PRODUCTION USE CASE:
A fraud-detection system needs to identify RINGS of related fraudulent
accounts — accounts sharing a payment method, a device fingerprint, or
being connected through several hops of shared attributes — a graph
database traversal query can find "all accounts within 3 hops of this
flagged account, connected via ANY shared attribute" efficiently,
directly surfacing an entire fraud ring in one query — the equivalent
SQL query, chaining multiple self-joins across several shared-attribute
tables, would be substantially more complex to write AND meaningfully slower to execute at real scale.

COMMON MISTAKES:
- Modeling data with only shallow, occasional relationships in a graph
  database "because relationships matter" — if the DOMINANT query
  pattern is still simple lookups/aggregations rather than deep
  traversal, a relational or document database is usually a better,
  operationally simpler fit.
- Attempting deep multi-hop relationship queries in a relational
  database via repeated self-joins at real production scale — this is
  precisely the access pattern where query performance degrades most
  severely as traversal depth grows, a genuine, measurable limitation
  rather than a merely stylistic preference for graph databases.
- Treating a graph database as a general-purpose replacement for ALL
  other database types — graph databases are NOT typically optimized
  for high-volume, simple key-based writes (Cassandra/DynamoDB's
  strength, L02-L03) or complex tabular aggregation (a relational
  database or data warehouse's strength) — it's a SPECIALIZED tool for
  its specific, genuine strength: relationship traversal.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Cypher query syntax — visual, pattern-matching style
# ------------------------------------------------------------------
CYPHER_EXAMPLES = textwrap.dedent("""\
    // Find Alice's direct friends
    MATCH (alice:Person {name: 'Alice'})-[:FRIENDS_WITH]->(friend)
    RETURN friend.name

    // Find "friends of friends" — a 2-hop traversal, expressed intuitively
    MATCH (alice:Person {name: 'Alice'})-[:FRIENDS_WITH]->(friend)-[:FRIENDS_WITH]->(fof)
    WHERE fof <> alice   // exclude Alice herself from the results
    RETURN DISTINCT fof.name

    // Fraud ring detection — accounts connected via ANY shared attribute,
    // within 3 hops (a query genuinely awkward to express as repeated SQL JOINs)
    MATCH (flagged:Account {id: 'acc_123'})-[*1..3]-(related:Account)
    WHERE flagged <> related
    RETURN DISTINCT related.id
""")

# ------------------------------------------------------------------
# 2. Why traversal cost doesn't blow up with hop count — illustrated
# ------------------------------------------------------------------
def simulate_relational_join_cost(num_hops: int, avg_connections_per_node: int) -> int:
    """Illustrative: intermediate result set size grows roughly
    exponentially with hop count in a naive relational self-join."""
    return avg_connections_per_node ** num_hops


def simulate_graph_traversal_cost(num_hops: int, avg_connections_per_node: int) -> int:
    """A graph traversal's actual work is proportional to nodes/edges
    TOUCHED — conceptually similar count here, but the KEY difference is
    that a graph engine doesn't need to materialize and re-scan large
    intermediate JOIN tables at each step; the direct pointer-following
    keeps PER-HOP overhead low and roughly constant regardless of overall graph size."""
    return avg_connections_per_node ** num_hops   # same node count touched, but WITHOUT join materialization overhead


def traversal_cost_comparison_demo():
    print(CYPHER_EXAMPLES)
    print("Nodes touched per traversal depth (avg 20 connections/node):\n")
    for hops in [1, 2, 3, 4]:
        node_count = simulate_graph_traversal_cost(hops, avg_connections_per_node=20)
        print(f"  {hops} hop(s): ~{node_count:,} nodes touched")
    print("\n  -> The RAW node count grows similarly either way, but a")
    print("     relational engine must MATERIALIZE and re-filter these as")
    print("     intermediate JOIN result tables at EACH step (real memory/CPU")
    print("     cost that compounds with each additional join) — a graph")
    print("     database's index-free adjacency avoids this materialization")
    print("     overhead, which is where its REAL performance advantage at depth comes from.")


if __name__ == "__main__":
    traversal_cost_comparison_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A financial institution's fraud team migrates their ring-detection
queries from a PostgreSQL-based system (using increasingly complex,
increasingly slow self-joins as they tried to detect deeper fraud rings)
to Neo4j — a query that previously took over a minute against their
relational schema for a 3-hop ring search completes in under a second
against the SAME underlying data modeled as a graph — not because Neo4j
is universally "faster," but because THIS SPECIFIC access pattern
(multi-hop relationship traversal) is exactly the workload graph
databases are architecturally built to handle efficiently, while
relational databases are architecturally built for a different set of strengths entirely.
"""
