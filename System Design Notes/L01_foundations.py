# ============================================================
# L01: Scalability Foundations
# ============================================================
# WHAT: System design is the process of deciding HOW a system is built —
#       not the code, but the architecture. It is about trade-offs, not
#       right answers. Every choice (SQL vs NoSQL, cache vs no cache,
#       monolith vs microservices) has costs and benefits.
# WHY:  Without deliberate architecture, systems collapse under load,
#       become impossible to maintain, or cost 100x more than necessary.
#       Good design handles growth without rewrites.
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    System design covers the decisions made before a single line of
    production code is written: how data flows, where it lives, how
    many machines are needed, what happens when one fails, and how
    the system behaves under 10x or 100x load. It is fundamentally
    about trade-offs — consistency vs availability, latency vs
    throughput, cost vs reliability. There are no universally correct
    answers, only answers that fit constraints.

PRODUCTION USE CASE:
    Twitter serves ~600 million users. They do not scale by buying
    a bigger server. They scale by distributing work across thousands
    of machines, using caches, CDNs, sharded databases, and message
    queues. Every architectural decision has compounding consequences.
    Getting it right early saves years of rewriting.

COMMON MISTAKES:
    - Over-engineering: building for 10M users when you have 1000.
      Start simple, scale when you must. Premature complexity kills startups.
    - Under-engineering: assuming the database is always fast enough.
      It won't be. Plan for caching, indexing, and sharding from day one.
    - Ignoring failure modes: what happens when a service is down?
      Every dependency is a potential failure point.
    - Confusing SLA, SLO, and SLI (explained below).
"""

# ============================================================
# 1. SCALABILITY: VERTICAL vs HORIZONTAL
# ============================================================

# VERTICAL SCALING ("scale up"):
#   Buy a bigger machine — more RAM, faster CPU, larger SSD.
#   Pros: simple, no code changes, low latency within machine.
#   Cons: expensive, hard ceiling (largest EC2 instance ~ $30k/month),
#         single point of failure (one machine = one outage risk).
#   Use when: early stage, database that can't easily shard,
#             traffic is predictable and modest.

# HORIZONTAL SCALING ("scale out"):
#   Add more machines, distribute work across them.
#   Pros: theoretically unlimited, fault tolerant (lose one, others continue),
#         cheaper at scale (commodity hardware).
#   Cons: complexity — need load balancers, distributed state, coordination.
#   Use when: high traffic, need redundancy, stateless services.

# KEY INSIGHT: Almost all large systems (Google, Amazon, Netflix) are
# horizontal. Vertical has a ceiling. Horizontal scales to millions of servers.

class ScalingExample:
    """Illustrate vertical vs horizontal limits."""

    # Vertical ceiling: Amazon's largest instance (u-24tb1.metal)
    # has 448 vCPUs, 24TB RAM — ~$218/hour. Still one machine.
    VERTICAL_CEILING_RAM_TB = 24
    VERTICAL_CEILING_VCPU = 448

    # Horizontal: Google runs ~2.5 million servers. No ceiling.
    HORIZONTAL_SERVERS_GOOGLE = 2_500_000


# ============================================================
# 2. LATENCY vs THROUGHPUT
# ============================================================

# LATENCY: Time to complete ONE request (milliseconds).
#   "How long does a user wait for a response?"
#   Goal: minimize latency for interactive systems (APIs, web pages).

# THROUGHPUT: Requests processed per second (RPS or QPS).
#   "How many requests can the system handle simultaneously?"
#   Goal: maximize throughput for batch systems (ETL, analytics).

# THE TRADE-OFF: They often conflict.
#   BATCHING: group 100 small requests into 1 large one.
#     - Throughput IMPROVES (1 network round trip instead of 100).
#     - Latency INCREASES (first request waits for 99 others to accumulate).
#   Example: Kafka batches messages. Higher throughput, higher latency.
#   Example: HTTP/2 multiplexing — many requests in one connection.

# Rule of thumb:
#   - User-facing APIs: optimize latency (target < 100ms P99).
#   - Background jobs / pipelines: optimize throughput.

latency_reference = {
    # These numbers are worth memorizing for interviews.
    "L1 cache hit":         "0.5 ns",
    "L2 cache hit":         "7 ns",
    "RAM read":             "100 ns",       # ~0.0001 ms
    "SSD random read":      "0.1 ms",       # 1000x slower than RAM
    "HDD seek":             "10 ms",        # 100x slower than SSD
    "Network: same DC":     "0.5 ms",       # within data center
    "Network: cross-region":"150 ms",       # e.g., US-East to EU-West
    "Network: satellite":   "600 ms",       # unusable for real-time
    "Disk throughput":      "100-200 MB/s", # HDD sequential
    "SSD throughput":       "500 MB/s",     # NVMe can hit 3.5 GB/s
    "Network (1GbE)":       "125 MB/s",
    "RAM throughput":       "10-50 GB/s",
}
# INSIGHT: RAM is 1000x faster than SSD. SSD is 100x faster than HDD.
# A cache hit (RAM) vs a DB miss (disk) = 100,000x difference.


# ============================================================
# 3. SLA / SLO / SLI
# ============================================================

# SLA — Service Level Agreement
#   A LEGAL CONTRACT with a customer defining acceptable performance.
#   Includes penalties (refunds, credits) if breached.
#   Example: AWS SLA — EC2 < 99.99% uptime → 30% bill credit.
#   EXTERNAL: agreed with customers.

# SLO — Service Level Objective
#   An INTERNAL TARGET that, if met, satisfies the SLA.
#   Usually tighter than SLA (buffer for emergencies).
#   Example: SLA = 99.9%. Internal SLO = 99.95%.
#   INTERNAL: engineering team owns it.

# SLI — Service Level Indicator
#   The ACTUAL MEASUREMENT used to evaluate SLOs.
#   Examples: request success rate, P99 latency, uptime percentage.
#   MEASURED: from logs, metrics, monitoring systems.

# WORKFLOW: Instrument SLIs → compare to SLOs → alert before SLA breach.
#   If SLI dips → page on-call → fix before SLO is missed → never breach SLA.

sla_examples = {
    "99.0%":   {"downtime_year": "87.6 hours",  "downtime_month": "7.3 hours"},
    "99.9%":   {"downtime_year": "8.7 hours",   "downtime_month": "43.8 min"},
    "99.99%":  {"downtime_year": "52.6 min",    "downtime_month": "4.4 min"},
    "99.999%": {"downtime_year": "5.3 min",     "downtime_month": "26 sec"},
}
# INSIGHT: Going from 99.9% to 99.99% = 10x more reliability.
# It also costs roughly 10x more (redundant everything, zero downtime deploys).
# Most consumer apps target 99.9%. Financial systems target 99.999%.


# ============================================================
# 4. CAP THEOREM
# ============================================================

# In a distributed system you can guarantee at most 2 of 3:
#
#   C — CONSISTENCY:
#       Every read returns the most recent write (or an error).
#       All nodes see the same data at the same time.
#
#   A — AVAILABILITY:
#       Every request gets a response (not necessarily the latest data).
#       The system never rejects a request (unless truly down).
#
#   P — PARTITION TOLERANCE:
#       The system continues operating even when network messages
#       are lost between nodes (network partition).
#
# KEY INSIGHT: Partitions ALWAYS happen in real networks (cables fail,
# switches drop packets). So P is not optional. The real choice is:
#   CP: Consistent + Partition-tolerant → sacrifice Availability.
#       "Return error rather than stale data."
#       Use for: banking (wrong balance = fraud), inventory (oversell = loss).
#       Examples: HBase, Zookeeper, PostgreSQL with strong consistency.
#
#   AP: Available + Partition-tolerant → sacrifice Consistency.
#       "Return stale data rather than error."
#       Use for: social media (stale follower count is fine), caches.
#       Examples: Cassandra, DynamoDB, CouchDB.
#
# Most web apps choose AP. Eventual consistency is acceptable for:
# likes, views, feed ranking, friend counts. NOT acceptable for:
# bank balances, inventory counts, auth tokens.

cap_choices = {
    "PostgreSQL (primary)":     "CP — strong consistency, will fail on partition",
    "DynamoDB (eventual mode)": "AP — available, eventually consistent",
    "Cassandra":                "AP — tunable consistency per-operation",
    "Zookeeper":                "CP — used for leader election (must be correct)",
    "Redis (single node)":      "CA — no partitions, not distributed",
}


# ============================================================
# 5. CONSISTENCY MODELS (spectrum, strong → weak)
# ============================================================

consistency_models = {
    "Strong (Linearizable)": {
        "guarantee": "Every read sees the most recent write. All operations appear atomic.",
        "cost":      "Slow — requires coordination between all nodes before responding.",
        "use_for":   "Financial transactions, distributed locks, leader election.",
        "example":   "Google Spanner (uses TrueTime API for global timestamps).",
    },
    "Causal": {
        "guarantee": "Operations with causal relationships (A caused B) are seen in order.",
        "cost":      "Moderate — track causality vectors (vector clocks).",
        "use_for":   "Collaborative editing (comments before replies always visible).",
        "example":   "MongoDB sessions, Facebook TAO.",
    },
    "Read-Your-Writes": {
        "guarantee": "You always see your own writes. Others may see stale data.",
        "cost":      "Low — route your reads to the replica you wrote to.",
        "use_for":   "User profile updates (you see your change immediately).",
        "example":   "Route user to same replica using sticky sessions or user-pinning.",
    },
    "Monotonic Reads": {
        "guarantee": "Once you read a value, you never see an older value.",
        "cost":      "Low — remember which replica each user read from.",
        "use_for":   "Prevents confusing backward-in-time reads (pagination).",
        "example":   "Always route user X to the same replica shard.",
    },
    "Eventual": {
        "guarantee": "All nodes will converge to the same value — eventually.",
        "cost":      "Lowest — no coordination needed.",
        "use_for":   "DNS, social media counts, shopping cart (Amazon Dynamo paper).",
        "example":   "DynamoDB default, Cassandra, Redis async replication.",
    },
}


# ============================================================
# 6. ACID vs BASE
# ============================================================

# ACID (SQL databases: PostgreSQL, MySQL):
#   A — Atomicity:   Transaction is all-or-nothing. No partial writes.
#   C — Consistency: DB moves from one valid state to another. Constraints hold.
#   I — Isolation:   Concurrent transactions don't interfere (as if sequential).
#   D — Durability:  Committed data survives crashes (written to disk).
#
#   Cost: locking, coordination → slower, harder to scale horizontally.
#   Use when: money, orders, inventory — where correctness > speed.

# BASE (NoSQL: Cassandra, DynamoDB, MongoDB):
#   BA — Basically Available:    System is available most of the time.
#   S  — Soft state:             State can change without input (convergence).
#   E  — Eventually consistent:  Will converge to correct state eventually.
#
#   Cost: application must handle stale reads, conflicts, partial failures.
#   Use when: high scale, eventual correctness acceptable.

# CHOOSING: Use ACID for anything financial or inventory-critical.
# Use BASE for analytics, social features, session data, recommendations.


# ============================================================
# 7. STATELESS vs STATEFUL SERVERS
# ============================================================

# STATELESS: Server holds no session state. Each request is self-contained.
#   Pros: add/remove servers freely — any server can handle any request.
#         Perfect for horizontal scaling. No sticky sessions needed.
#   Example: REST APIs that authenticate via JWT (token carries identity).

# STATEFUL: Server holds session data in memory.
#   Cons: requests must go to SAME server. Can't add servers freely.
#         Server failure = session loss.
#   Old approach: PHP sessions stored in server memory.

# SOLUTION: Move state OUT of servers into shared infrastructure.
#   Sessions  → Redis (fast in-memory key-value store, shared by all servers)
#   Files     → S3 / GCS (object storage, globally accessible)
#   User data → Database (PostgreSQL, MySQL)
#
# GOAL: Servers should be cattle, not pets.
# Any server is replaceable. State lives in data stores, not servers.

stateless_architecture = {
    # Request flow for a stateless auth system
    "step_1": "User POSTs login → server validates → generates JWT token",
    "step_2": "JWT contains user_id + expiry, signed with server secret",
    "step_3": "User sends JWT in every request header",
    "step_4": "ANY server validates JWT signature → no shared session store needed",
    "step_5": "Add 100 servers → all handle requests equally. Scale freely.",
}


# ============================================================
# 8. BACK-OF-ENVELOPE ESTIMATION (URL Shortener example)
# ============================================================
# This is a practiced skill. Interviewers use it to test systems thinking.
# Be deliberate, show your assumptions, round liberally.

def url_shortener_estimation():
    """
    URL Shortener estimation — step by step.
    Assumptions: system like bit.ly.
    """

    # --- TRAFFIC ESTIMATES ---
    daily_active_users        = 100_000_000   # 100M DAU
    shortens_per_user_per_day = 0.1           # most users only read
    reads_per_user_per_day    = 10            # read >> write

    write_qps = (daily_active_users * shortens_per_user_per_day) / 86_400
    read_qps  = (daily_active_users * reads_per_user_per_day) / 86_400
    # write_qps ~ 116, read_qps ~ 11,600. Read-to-write ratio ~ 100:1.

    # --- STORAGE ESTIMATES ---
    years_to_keep      = 5
    seconds_per_year   = 365 * 24 * 3600      # ~31.5M
    total_records      = write_qps * seconds_per_year * years_to_keep
    bytes_per_record   = 500                  # short_code(7) + long_url(200) + metadata
    total_storage_gb   = (total_records * bytes_per_record) / 1e9
    # total_records ~ 18.3 billion, storage ~ 9.1 TB over 5 years.

    # --- BANDWIDTH ESTIMATES ---
    avg_url_size_bytes  = 200                 # average long URL
    read_bandwidth_mbps = (read_qps * avg_url_size_bytes * 8) / 1e6
    # read bandwidth ~ 18.6 Mbps — trivial for modern network.

    # --- CACHE ESTIMATES ---
    # Zipf's law: 20% of URLs get 80% of traffic (power law distribution).
    hot_url_fraction  = 0.20
    cache_size_gb     = (total_records * hot_url_fraction * bytes_per_record) / 1e9
    # Cache just the hot 20% ~ 1.8 TB. Fits in Redis cluster.

    # --- SERVER ESTIMATES ---
    # Assume 1 server handles ~10,000 req/s for simple redirects.
    redirect_servers = max(1, int(read_qps / 10_000))
    write_servers    = max(1, int(write_qps / 1_000))
    # redirect_servers ~ 2, write_servers ~ 1. Very small at this scale.

    return {
        "write_qps":             round(write_qps),
        "read_qps":              round(read_qps),
        "read_write_ratio":      "~100:1",
        "total_records_5yr":     f"{total_records / 1e9:.1f} billion",
        "storage_5yr_tb":        f"{total_storage_gb / 1000:.1f} TB",
        "read_bandwidth_mbps":   f"{read_bandwidth_mbps:.1f} Mbps",
        "cache_size_tb":         f"{cache_size_gb / 1000:.2f} TB",
        "redirect_servers_est":  redirect_servers,
        "write_servers_est":     write_servers,
        "key_insight": (
            "Read-heavy (100:1). Optimize reads with Redis cache. "
            "Storage is manageable (9 TB). Bandwidth is trivial. "
            "Hard problem: generating unique 7-char codes at scale without collisions."
        ),
    }

# Run estimation
if __name__ == "__main__":
    import json
    result = url_shortener_estimation()
    print("=== URL Shortener Estimation ===")
    print(json.dumps(result, indent=2))


# ============================================================
# ARCHITECTURE SUMMARY DIAGRAM
# ============================================================
#
#   FOUNDATIONS MAP
#   ===============
#
#   SYSTEM DESIGN
#       ├── Scale Strategy
#       │       ├── Vertical   → Simple, limited. Use early.
#       │       └── Horizontal → Complex, unlimited. Use at scale.
#       │
#       ├── Performance
#       │       ├── Latency    → ms per request. Cache, CDN, co-location.
#       │       └── Throughput → RPS. Batching, parallelism, queues.
#       │
#       ├── Reliability
#       │       ├── SLI (measure) → SLO (target) → SLA (contract)
#       │       └── 99.9% = 8.7h/yr, 99.99% = 52min/yr, 99.999% = 5min/yr
#       │
#       ├── Consistency (CAP Theorem)
#       │       ├── CP systems  → Banks, inventory, locks
#       │       └── AP systems  → Social media, caches, DNS
#       │
#       ├── Data Guarantees
#       │       ├── ACID (SQL)  → Correctness. Transactions. Finance.
#       │       └── BASE (NoSQL)→ Scale. Eventual consistency. Social.
#       │
#       └── State Management
#               ├── Stateless servers → scale freely, JWT auth
#               └── State → Redis (sessions), S3 (files), DB (records)
#
# ============================================================
