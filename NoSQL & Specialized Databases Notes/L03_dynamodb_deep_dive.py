# ============================================================
# L03: DynamoDB Deep Dive — Fully Managed, Single-Digit-Millisecond NoSQL
# ============================================================
# WHAT: DynamoDB's specific data model (partition + sort key, Global
#       Secondary Indexes), its capacity/scaling model, and the
#       single-table design pattern that DynamoDB's cost/performance
#       model actively encourages.
# WHY: L02 covered Cassandra, a SELF-MANAGED wide-column database.
#      DynamoDB is AWS's FULLY MANAGED equivalent with genuinely
#      different operational and design implications — this lesson
#      covers those specific differences.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
DYNAMODB'S CORE DATA MODEL closely parallels Cassandra's (L02): a
PARTITION KEY (determines which physical partition stores an item) and
an optional SORT KEY (determines ordering within that partition) — the
same query-first design discipline applies: efficient queries are
those filtering by partition key (optionally range-filtered by sort
key); anything else requires either a SCAN (reading the ENTIRE table —
expensive and generally avoided in production) or a properly-designed
secondary index.

GLOBAL SECONDARY INDEXES (GSIs) let you query by an ALTERNATIVE
partition/sort key combination beyond the table's primary key — this is
DynamoDB's mechanism for supporting a SECOND access pattern on the same
underlying data, conceptually similar to Cassandra's "create a second
denormalized table" approach (L02), but implemented as an INDEX
DynamoDB manages automatically rather than a second table your
application writes to explicitly — GSIs are EVENTUALLY consistent by
default (a genuine tradeoff: the index may briefly lag behind the base
table after a write), while LOCAL SECONDARY INDEXES (sharing the base
table's partition key, different sort key) can be read with STRONG consistency.

CAPACITY MODES — a genuinely operational, cost-relevant decision: ON-
DEMAND capacity mode automatically scales to handle traffic with NO
capacity planning required, at a HIGHER per-request cost — appropriate
for unpredictable or spiky traffic patterns; PROVISIONED capacity mode
requires specifying expected read/write throughput ahead of time (with
optional auto-scaling within configured bounds), at a LOWER cost for
predictable, steady traffic, but risking THROTTLING (requests rejected)
if actual traffic exceeds the provisioned capacity faster than
auto-scaling can react — this decision directly parallels this repo's
System Design Case Studies Notes L28's reactive/predictive autoscaling
tradeoffs, applied specifically to database capacity.

SINGLE-TABLE DESIGN is a DynamoDB-specific pattern (much more
aggressively pursued than Cassandra's multi-table denormalization,
L02) that stores MULTIPLE DIFFERENT ENTITY TYPES (e.g. users, orders,
products) in ONE PHYSICAL TABLE, using GENERIC partition/sort key names
(often literally called "PK" and "SK") with entity-type-specific VALUE
PREFIXES (e.g. `PK=USER#123`, `PK=ORDER#456`) — this seemingly unusual
design is driven DIRECTLY by DynamoDB's pricing and performance model:
a SINGLE query against ONE table can retrieve MULTIPLE RELATED entity
types in one request (e.g. a user AND their recent orders, both sharing
a cleverly-designed key structure) that would otherwise require
multiple separate queries/tables — trading schema readability
(single-table designs look unfamiliar and are harder to casually browse) for query efficiency and cost.

PRODUCTION USE CASE:
A serverless e-commerce backend (paired with AWS Lambda) uses a
single DynamoDB table with items like `PK=USER#123, SK=PROFILE` (the
user's profile) and `PK=USER#123, SK=ORDER#789` (one of that user's
orders) — a SINGLE query for `PK=USER#123` retrieves the user's
profile AND all their orders in ONE request, at ONE table's read cost —
a deliberate design optimizing specifically for DynamoDB's per-request,
per-table-scan cost model, which a naturally-normalized multi-table
design would not achieve nearly as efficiently.

COMMON MISTAKES:
- Using a full table SCAN in production application code (rather than a
  properly-indexed QUERY) — a scan reads the ENTIRE table regardless of
  how few items actually match, an operation whose cost and latency grow
  directly with total table size, defeating DynamoDB's intended
  key-based access pattern entirely.
- Choosing PROVISIONED capacity mode for genuinely unpredictable,
  spiky traffic without adequate auto-scaling headroom — this risks
  THROTTLING during sudden traffic spikes, a real availability cost that
  ON-DEMAND mode (at a higher steady-state cost) would avoid.
- Applying single-table design dogmatically to EVERY DynamoDB use case,
  even when the added query complexity/design difficulty isn't
  justified by an actual, corresponding cost/performance benefit for
  that SPECIFIC application's access patterns — single-table design is
  a powerful but genuinely more complex pattern, appropriate when its
  benefits (fewer, cheaper, related-entity queries) actually apply.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Single-table design — multiple entity types, one table
# ------------------------------------------------------------------
SINGLE_TABLE_DESIGN_EXAMPLE = textwrap.dedent("""\
    DynamoDB single-table design — items for DIFFERENT entity types,
    sharing the SAME table, distinguished by key PREFIXES:

    | PK           | SK           | Attributes                          |
    |--------------|--------------|--------------------------------------|
    | USER#123     | PROFILE      | name=Alice, email=alice@example.com |
    | USER#123     | ORDER#789    | total=99.99, date=2026-06-01        |
    | USER#123     | ORDER#790    | total=45.50, date=2026-06-15        |
    | PRODUCT#456  | DETAILS      | name=Widget, price=9.99             |

    A SINGLE query for PK="USER#123" retrieves the user's profile AND
    both of their orders in ONE request — a naturally normalized,
    multi-table design would require TWO separate queries (one per
    table) to assemble the same information.
""")

# ------------------------------------------------------------------
# 2. Capacity mode decision framework
# ------------------------------------------------------------------
def choose_capacity_mode(traffic_pattern: str) -> str:
    decision_map = {
        "highly unpredictable/spiky, hard to forecast": "ON-DEMAND (higher per-request cost, zero capacity planning)",
        "steady, predictable, well-understood": "PROVISIONED with modest auto-scaling headroom (lower steady-state cost)",
        "known scheduled spikes (e.g. a sale event)": "PROVISIONED, manually scaled UP ahead of the known event (like System Design Case Studies Notes L28's scheduled scaling)",
    }
    return decision_map.get(traffic_pattern, "Start with ON-DEMAND, switch to PROVISIONED once traffic patterns are well understood")


def capacity_mode_demo():
    print(SINGLE_TABLE_DESIGN_EXAMPLE)
    print("Capacity mode decision framework:\n")
    for pattern in ["highly unpredictable/spiky, hard to forecast",
                    "known scheduled spikes (e.g. a sale event)"]:
        print(f"  '{pattern}':")
        print(f"    -> {choose_capacity_mode(pattern)}\n")


# ------------------------------------------------------------------
# 3. GSI eventual consistency — a concrete illustration
# ------------------------------------------------------------------
def gsi_consistency_illustration():
    print("Global Secondary Index (GSI) consistency behavior:\n")
    print("  1. Write to base table: item created with attribute 'status=pending'")
    print("  2. IMMEDIATELY query the base table by primary key: sees 'status=pending' (consistent read available)")
    print("  3. IMMEDIATELY query a GSI on 'status': may NOT yet see this item —")
    print("     GSI updates are propagated ASYNCHRONOUSLY, with a brief")
    print("     (typically sub-second, but non-zero) replication lag")
    print("\n  -> An application relying on 'read my own GSI write immediately'")
    print("     can encounter a race condition; base-table reads with strong")
    print("     consistency don't have this same lag, a genuine design")
    print("     consideration when choosing which access path a given feature relies on.")


if __name__ == "__main__":
    capacity_mode_demo()
    gsi_consistency_illustration()

"""
PRODUCTION CONTEXT EXAMPLE:
A serverless SaaS backend built on Lambda + DynamoDB uses a single-table
design storing tenants, users, and documents all in one table with
carefully designed PK/SK prefixes — retrieving "everything for tenant
X's dashboard" (tenant metadata, its users, its recent documents) is a
SINGLE DynamoDB query rather than 3+ separate queries against separate
tables — directly reducing both latency and per-request cost at scale,
a benefit specifically enabled by embracing DynamoDB's single-table
design pattern rather than porting a traditional relational schema over unchanged.
"""
