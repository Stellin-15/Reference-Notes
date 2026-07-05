# ============================================================
# L22: Load Balancing Algorithms — Round Robin, Least Connections, Consistent Hashing
# ============================================================
# WHAT: The specific ALGORITHMS a load balancer uses to pick WHICH
#       backend server handles a given connection/request — round robin,
#       weighted round robin, least connections, and consistent hashing —
#       and the genuinely different scenarios each is designed for.
# WHY: L21 covered WHERE a load balancer sits in the stack (L4 vs L7);
#      this lesson covers the actual DECISION LOGIC it runs to distribute
#      load once a request needs to be routed to SOME backend.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
ROUND ROBIN cycles through backend servers in a fixed, repeating order —
simple to implement and reason about, and works well when ALL backend
servers have roughly EQUAL capacity and each request/connection imposes
roughly equal load. Its weakness: it has NO awareness of a backend's
ACTUAL current load — if one backend happens to be handling several
long-running requests while others are idle, round robin will still
send it an equal share of NEW traffic, potentially overloading it further.

WEIGHTED ROUND ROBIN extends round robin to handle HETEROGENEOUS backend
capacity — assigning each backend a weight (e.g. a server with double
the CPU/memory gets weight 2, receiving twice as many requests per
rotation as a weight-1 server) — this is a straightforward fix for
"backends have different capacity" but STILL has no visibility into
actual real-time load, only a STATIC capacity assumption set ahead of time.

LEAST CONNECTIONS routes each new request to whichever backend CURRENTLY
has the FEWEST active connections — this directly addresses round
robin's blind spot by using REAL-TIME load information rather than a
static assumption, correctly avoiding sending more traffic to an
already-busy backend. Its own limitation: "connection count" isn't
always a perfect proxy for actual load — a backend could have few
connections that are each individually very expensive (long-running,
CPU-intensive requests), in which case connection count alone
under-represents its true load; WEIGHTED LEAST CONNECTIONS or
RESPONSE-TIME-AWARE variants address this further by incorporating
additional signals.

CONSISTENT HASHING solves an ENTIRELY DIFFERENT problem than the above
three: it's used when repeated requests from/about the SAME KEY
(a user ID, a cache key, a session ID) need to consistently route to the
SAME backend — critical for CACHE LOCALITY (routing the same cache key
to the same backend server maximizes that backend's own local cache hit
rate) and STATEFUL connections (WebSocket sessions, in-memory session
state). Naive hashing (`hash(key) % num_servers`) has a severe weakness:
adding or removing EVEN ONE server changes the modulo result for
MOST keys, causing a massive, unnecessary RESHUFFLING of which server
handles which key. Consistent hashing arranges both SERVERS and KEYS on
a conceptual hash ring, and a key is routed to the NEXT server clockwise
on the ring from its own hash position — adding/removing one server
then only affects the keys immediately adjacent to it on the ring, NOT
the entire keyspace, dramatically reducing reshuffling on capacity changes.

PRODUCTION USE CASE:
A caching layer (this repo's Redis & Caching Notes) in front of a
database uses consistent hashing to route cache lookups: the SAME user's
profile data cache key always routes to the SAME cache node, maximizing
that node's cache hit rate for that user's repeated requests — when a
cache node is added to scale up capacity, consistent hashing ensures
only a small fraction of keys need to move to the new node, rather than
the near-total cache invalidation a naive modulo-based hash would cause.

COMMON MISTAKES:
- Using plain round robin for backends with GENUINELY different capacity
  (e.g. mixed instance sizes in a cloud auto-scaling group) — this sends
  equal traffic to unequal-capacity servers, overloading smaller
  instances while underutilizing larger ones.
- Using naive modulo-based hashing (`hash(key) % N`) for any workload
  where server count changes over time (autoscaling, rolling
  deployments) — this causes a near-total keyspace reshuffle on every
  single capacity change, defeating the cache-locality benefit hashing
  was meant to provide in the first place.
- Using ROUND ROBIN or LEAST CONNECTIONS for workloads that actually need
  KEY-BASED AFFINITY (the same user's requests must hit the same
  backend for correctness, e.g. an in-memory session store) — these
  algorithms have no concept of "route the same key to the same place,"
  which consistent hashing is specifically designed to provide.
"""

import hashlib


# ------------------------------------------------------------------
# 1. Round robin and weighted round robin
# ------------------------------------------------------------------
class WeightedRoundRobin:
    def __init__(self, servers_with_weights: dict[str, int]):
        # Expand into a rotation list proportional to each server's weight
        self.rotation = []
        for server, weight in servers_with_weights.items():
            self.rotation.extend([server] * weight)
        self.index = 0

    def next_server(self) -> str:
        server = self.rotation[self.index % len(self.rotation)]
        self.index += 1
        return server


def round_robin_demo():
    lb = WeightedRoundRobin({"server-A (weight 2)": 2, "server-B (weight 1)": 1})
    assignments = [lb.next_server() for _ in range(6)]
    print(f"Weighted round robin assignments over 6 requests: {assignments}")
    print("  -> server-A (double capacity) receives roughly twice as many")
    print("     requests as server-B, proportional to its assigned weight.")


# ------------------------------------------------------------------
# 2. Least connections
# ------------------------------------------------------------------
def least_connections_select(server_connection_counts: dict[str, int]) -> str:
    return min(server_connection_counts, key=server_connection_counts.get)


def least_connections_demo():
    current_connections = {"server-A": 45, "server-B": 12, "server-C": 30}
    chosen = least_connections_select(current_connections)
    print(f"\nCurrent connections: {current_connections}")
    print(f"Least-connections routes the new request to: {chosen}")
    print("  -> Unlike round robin, this reacts to REAL-TIME load rather")
    print("     than blindly cycling through servers regardless of current state.")


# ------------------------------------------------------------------
# 3. Consistent hashing — stable key-to-server mapping across resizes
# ------------------------------------------------------------------
class ConsistentHashRing:
    def __init__(self, servers: list[str], virtual_nodes_per_server: int = 100):
        self.ring: dict[int, str] = {}
        self.virtual_nodes_per_server = virtual_nodes_per_server
        for server in servers:
            self._add_server(server)

    def _hash(self, key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def _add_server(self, server: str):
        # Multiple VIRTUAL points per physical server smooths out
        # distribution across the ring (avoids uneven "hot spots")
        for i in range(self.virtual_nodes_per_server):
            point = self._hash(f"{server}-vnode-{i}")
            self.ring[point] = server

    def remove_server(self, server: str):
        self.ring = {point: s for point, s in self.ring.items() if s != server}

    def get_server(self, key: str) -> str:
        if not self.ring:
            return None
        key_hash = self._hash(key)
        sorted_points = sorted(self.ring.keys())
        for point in sorted_points:
            if key_hash <= point:
                return self.ring[point]
        return self.ring[sorted_points[0]]   # wrap around the ring


def consistent_hashing_demo():
    ring = ConsistentHashRing(["cache-node-1", "cache-node-2", "cache-node-3"])

    keys = [f"user_{i}_profile" for i in range(5)]
    print("\nBefore adding a new node:")
    before_assignments = {key: ring.get_server(key) for key in keys}
    for key, server in before_assignments.items():
        print(f"  {key} -> {server}")

    ring._add_server("cache-node-4")   # scaling up
    print("\nAfter adding cache-node-4:")
    after_assignments = {key: ring.get_server(key) for key in keys}
    changed = 0
    for key, server in after_assignments.items():
        moved = " (MOVED)" if server != before_assignments[key] else ""
        if moved:
            changed += 1
        print(f"  {key} -> {server}{moved}")

    print(f"\n  -> Only {changed} of {len(keys)} keys moved to a different")
    print("     node — a naive modulo hash would have reshuffled MOST keys")
    print("     on this same capacity change.")


if __name__ == "__main__":
    round_robin_demo()
    least_connections_demo()
    consistent_hashing_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A distributed caching tier (this repo's Redis & Caching Notes) uses
consistent hashing to route cache reads/writes across a cluster of
cache nodes, ensuring each user's data is consistently cached on the
SAME node across requests (maximizing hit rate) — while a SEPARATE web
application tier in front of it uses least-connections load balancing,
since web requests have no key-affinity requirement and benefit instead
from real-time load awareness — two DIFFERENT load balancing algorithms,
each matched deliberately to its own layer's actual requirements rather
than one algorithm applied uniformly across the whole system.
"""
