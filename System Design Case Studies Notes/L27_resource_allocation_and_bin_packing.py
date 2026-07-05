# ============================================================
# L27: Resource Allocation and Bin Packing — Fitting Workloads onto Machines
# ============================================================
# WHAT: The algorithmic problem underneath every container scheduler
#       (Kubernetes, this repo's GPU Computing Notes L11's K8s GPU
#       scheduling) — deciding WHICH physical/virtual machine each
#       workload should run on to use available capacity efficiently.
# WHY: L21-L26 covered ROUTING traffic to already-running backends. This
#      lesson covers a DIFFERENT, earlier problem: deciding WHERE those
#      backends should even be PLACED across a fleet of machines in the
#      first place, to avoid wasting capacity.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
BIN PACKING is the classic computer science problem this maps to
directly: given a set of ITEMS (workloads, each needing a certain
amount of CPU/memory) and a set of BINS (physical/virtual machines,
each with fixed CPU/memory capacity), pack the items into as FEW bins
as possible — minimizing WASTED, unused capacity spread thinly across
many machines. This is an NP-HARD problem in general (no known
efficient algorithm finds the OPTIMAL packing for large inputs), so real
schedulers use practical, well-understood HEURISTICS rather than exact optimal solutions.

FIRST FIT places each new item into the FIRST bin that has enough
remaining capacity, without searching for the absolute best "fit" —
simple and fast (a genuine advantage for a scheduler that needs to make
decisions quickly at scale), but can leave AWKWARD, hard-to-use
remaining capacity scattered across many bins.

BEST FIT places each item into the bin whose remaining capacity is
CLOSEST to (but still sufficient for) the item's needs — this tends to
produce TIGHTER packing (less wasted space per bin) than first fit, at
the cost of needing to SEARCH across all candidate bins for the best
match rather than stopping at the first workable one, a real computational
cost difference that matters at very large scale (thousands of
nodes/scheduling decisions per second).

BIN PACKING VS SPREADING is a genuine, deliberate TRADEOFF a scheduler
must choose, not just an efficiency question: "pack tightly" (bin
packing, minimizing the NUMBER of machines used, ideal for cost/resource
efficiency) directly CONFLICTS with "spread workloads out" (maximizing
FAULT TOLERANCE — if replicas of the same service are packed onto the
SAME few machines for efficiency, a single machine failure takes out
MULTIPLE replicas simultaneously, defeating the purpose of having
replicas at all). Production schedulers (Kubernetes' scheduler is the
canonical example) support BOTH strategies via configurable policies —
often bin-packing for cost efficiency on stateless, easily-replaceable
workloads, while explicitly SPREADING replicas of the SAME critical
service across different failure domains (different physical racks,
availability zones) for resilience.

RESOURCE REQUESTS VS LIMITS (a distinction Kubernetes makes explicit,
and this repo's Kubernetes Notes and GPU Computing & Distributed
Training Notes L11 cover in their own contexts) matters for bin-packing
decisions specifically: a scheduler packs bins based on each workload's
REQUESTED (guaranteed minimum) resources, not its potential maximum
usage (limit) — this allows OVERCOMMITTING a machine's resources on the
assumption that not every workload will simultaneously use its maximum
allowed limit at the same moment, a calculated bet that trades some risk
of resource contention during simultaneous peak usage for meaningfully
higher overall utilization.

PRODUCTION USE CASE:
A Kubernetes cluster's scheduler uses a bin-packing-favoring policy to
tightly pack stateless web-service pods onto the fewest possible nodes
(directly reducing the number of billed compute instances needed), while
simultaneously applying POD ANTI-AFFINITY rules that force replicas of
the SAME critical database service onto DIFFERENT physical nodes/
availability zones — achieving cost efficiency for the replaceable,
horizontally-scaled workload while preserving genuine fault tolerance
for the workload where a shared-machine failure would be far more consequential.

COMMON MISTAKES:
- Applying bin-packing (tight consolidation) UNIFORMLY to every workload,
  including replicated, fault-tolerance-critical services — this can
  silently concentrate ALL replicas of a critical service onto very few
  machines, defeating the resilience purpose replication was meant to provide.
- Scheduling based on resource LIMITS rather than REQUESTS (or vice versa,
  depending on the intended tradeoff) without understanding the
  consequence — scheduling by limits wastes capacity (assuming every
  workload will simultaneously use its maximum), while scheduling
  purely by requests without any headroom risks resource contention if
  many workloads simultaneously spike toward their limits at once.
- Treating bin-packing as a purely academic algorithms problem rather
  than recognizing the real, deliberate business tradeoff (cost
  efficiency vs fault tolerance) it represents — the "best" packing
  strategy depends entirely on which of these two competing goals
  matters more for a SPECIFIC workload, not a universal answer.
"""


# ------------------------------------------------------------------
# 1. First fit vs best fit bin packing
# ------------------------------------------------------------------
def first_fit(items: list[int], bin_capacity: int) -> list[list[int]]:
    bins = []
    for item in items:
        placed = False
        for b in bins:
            if sum(b) + item <= bin_capacity:
                b.append(item)
                placed = True
                break
        if not placed:
            bins.append([item])
    return bins


def best_fit(items: list[int], bin_capacity: int) -> list[list[int]]:
    bins = []
    for item in items:
        best_bin_index, best_remaining = None, None
        for i, b in enumerate(bins):
            remaining = bin_capacity - sum(b)
            if remaining >= item:
                if best_remaining is None or remaining < best_remaining:
                    best_bin_index, best_remaining = i, remaining
        if best_bin_index is not None:
            bins[best_bin_index].append(item)
        else:
            bins.append([item])
    return bins


def bin_packing_demo():
    # Workloads (e.g. memory requests in GB), bins (e.g. 10GB machines)
    workloads = [6, 4, 3, 7, 2, 5, 4]
    capacity = 10

    ff_result = first_fit(workloads, capacity)
    bf_result = best_fit(workloads, capacity)

    print(f"Workloads: {workloads} (bin capacity: {capacity} each)\n")
    print(f"First fit uses {len(ff_result)} machines: {ff_result}")
    print(f"Best fit uses {len(bf_result)} machines: {bf_result}")
    print("\n  -> Best fit often (not always) achieves tighter packing —")
    print("     fewer machines used for the SAME set of workloads — at")
    print("     the cost of a more expensive per-item placement search.")


# ------------------------------------------------------------------
# 2. Bin packing vs spreading — the fault-tolerance tradeoff
# ------------------------------------------------------------------
def schedule_with_anti_affinity(replicas: list[str], nodes: list[str],
                                 same_service_replicas: set[str]) -> dict[str, str]:
    assignment = {}
    used_nodes_for_service = set()
    for replica in replicas:
        # Prefer a node NOT already hosting another replica of the SAME service
        available = [n for n in nodes if n not in used_nodes_for_service]
        chosen_node = available[0] if available else nodes[0]
        assignment[replica] = chosen_node
        if replica in same_service_replicas:
            used_nodes_for_service.add(chosen_node)
    return assignment


def spreading_demo():
    nodes = ["node-1", "node-2", "node-3"]
    db_replicas = ["db-replica-1", "db-replica-2", "db-replica-3"]

    assignment = schedule_with_anti_affinity(db_replicas, nodes, set(db_replicas))
    print("\nCritical database replicas, scheduled with ANTI-AFFINITY "
          "(spread, not packed):")
    for replica, node in assignment.items():
        print(f"  {replica} -> {node}")
    print("  -> Each replica lands on a DIFFERENT node — a single node")
    print("     failure can take out at most ONE replica, preserving the")
    print("     fault tolerance replication was meant to provide.")


if __name__ == "__main__":
    bin_packing_demo()
    spreading_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team running a mixed workload cluster configures Kubernetes
to bin-pack stateless API server pods tightly (minimizing node count,
directly reducing cloud compute spend, since any individual pod failing
is trivially replaced), while applying explicit pod anti-affinity rules
ensuring their PostgreSQL primary/replica database pods NEVER land on
the same physical node or availability zone — the SAME cluster
deliberately applies OPPOSITE placement strategies to different
workloads, matched to each workload's actual failure-tolerance requirements.
"""
