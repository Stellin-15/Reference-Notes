# ============================================================
# L07: FinOps — Cloud Cost Management at Scale
# ============================================================
# WHAT: The operating model (people, process, tooling) for making cloud
#       spend a first-class, team-visible metric instead of a surprise on
#       the monthly finance report.
# WHY (PRODUCTION): A Kubernetes cluster's bill is one number by default —
#       nobody can tell if team A's batch job or team B's over-provisioned
#       API is driving the cost. FinOps attributes spend to the team/service
#       that caused it, so optimization decisions have an accountable owner.
# LEVEL: Senior backend / platform engineer, engineering manager
# ============================================================

"""
CONCEPT OVERVIEW:
FinOps (the term, coined by the FinOps Foundation) is the practice of
bringing financial accountability to the variable-spend model of the cloud.
It has three phases per cost cycle: Inform (visibility/attribution),
Optimize (rightsizing, commitment discounts), Operate (continuous
governance — budgets, anomaly alerts).

On Kubernetes specifically, the hard problem is that a single node's cost
must be *allocated* across every pod scheduled on it, proportional to
requested (or used) CPU/memory — nodes aren't billed per-pod natively.

PRODUCTION USE CASE:
A platform team rolls out mandatory tagging (`team`, `service`,
`environment`) enforced by an OPA policy (see L04) at resource-creation
time. Kubecost then attributes every dollar of cluster spend to a team via
namespace labels. A monthly Slack digest shows each team their spend trend;
one team notices their staging environment costs 40% of their production
environment — because a load-generator CronJob was never turned off after
a one-time test — and kills it, saving $3k/month.

COMMON MISTAKES:
- Rightsizing based on peak CPU alone, ignoring that memory OOM-kills are
  often the real constraint driving over-provisioning.
- Buying Reserved Instances for workloads that are inherently variable
  (research/backtesting clusters) instead of using them only for the
  stable, always-on baseline.
- Chargeback without warning — surprise bills erode trust in the whole
  FinOps program faster than any technical mistake.
"""

from dataclasses import dataclass

# ------------------------------------------------------------------
# 1. Tagging strategy — the foundation of all cost attribution
# ------------------------------------------------------------------
MANDATORY_TAGS = {
    "team": "Owning team — maps to a Backstage Group entity (see L01).",
    "service": "Service name — maps to a Backstage Component entity.",
    "environment": "prod | staging | dev — separates baseline vs elastic spend.",
    "cost-center": "Finance department code, for chargeback reconciliation.",
}


def check_tag_compliance(resource_tags: dict) -> list[str]:
    """A CI/OPA-style check — run against every Terraform plan or K8s manifest."""
    missing = [tag for tag in MANDATORY_TAGS if tag not in resource_tags]
    return [f"missing required tag: {tag}" for tag in missing]


# ------------------------------------------------------------------
# 2. Kubernetes cost allocation (Kubecost / OpenCost model)
# ------------------------------------------------------------------
@dataclass
class NodeCost:
    hourly_cost: float
    cpu_cores: float
    memory_gb: float


@dataclass
class PodRequest:
    namespace: str
    cpu_cores: float
    memory_gb: float


def allocate_node_cost(node: NodeCost, pods: list[PodRequest]) -> dict[str, float]:
    """
    Simplified version of what OpenCost computes: split a node's hourly cost
    across pods proportional to their RESOURCE REQUESTS (not limits — limits
    are a ceiling, not a claim on the node). Idle/unrequested capacity is
    typically bucketed as "cluster overhead" cost, a strong signal to
    rightsize the node pool.
    """
    total_requested_cpu = sum(p.cpu_cores for p in pods) or 1e-9
    cost_per_namespace: dict[str, float] = {}
    for pod in pods:
        share = pod.cpu_cores / total_requested_cpu
        cost_per_namespace[pod.namespace] = (
            cost_per_namespace.get(pod.namespace, 0.0) + share * node.hourly_cost
        )
    return cost_per_namespace


# ------------------------------------------------------------------
# 3. Right-sizing — VPA recommendation vs actual usage
# ------------------------------------------------------------------
RIGHTSIZING_SIGNALS = textwrap = {
    "cpu_request_vs_p95_usage": "If p95 usage is 20% of the request, the "
        "request is 5x oversized — this is wasted, reserved-but-unused "
        "capacity that still costs money.",
    "container_cpu_cfs_throttled_seconds": "Non-zero throttling despite a "
        "high CPU limit means the LIMIT (not request) is too low — a "
        "different failure mode from over-provisioning.",
    "oom_kill_count": "Frequent OOMKilled events mean memory REQUESTS are "
        "too low, not that memory is being 'saved' — this is the opposite "
        "problem from CPU over-provisioning and needs a request increase.",
}

# ------------------------------------------------------------------
# 4. Spot / Preemptible instance strategy
# ------------------------------------------------------------------
SPOT_STRATEGY_NOTES = (
    "Run STATELESS, INTERRUPTIBLE workloads (batch jobs, CI runners, "
    "research/backtest clusters) on spot node pools — 60-90% cheaper than "
    "on-demand. Never run a StatefulSet's only replica on spot without "
    "PodDisruptionBudgets and graceful-shutdown handling for the ~2-minute "
    "interruption notice. Production request-serving pods typically split "
    "70/30 on-demand/spot via node affinity + PriorityClass so a spot "
    "reclaim event never drops below the on-demand-guaranteed floor."
)

# ------------------------------------------------------------------
# 5. Reserved Instances vs Savings Plans
# ------------------------------------------------------------------
COMMITMENT_MODELS = {
    "Reserved Instances": "Commit to a SPECIFIC instance family/region for "
        "1-3 years for up to ~72% discount. Inflexible — a workload "
        "migration to a different instance type strands the commitment.",
    "Savings Plans": "Commit to a DOLLAR AMOUNT of compute spend per hour, "
        "applies automatically across instance families/regions. More "
        "flexible than RIs, similar discount depth — generally the better "
        "default choice unless you have a truly static fleet.",
}


def break_even_months(upfront_cost: float, monthly_savings: float) -> float:
    """Simple break-even calc used before committing to a 1-3yr RI/Savings Plan."""
    return upfront_cost / monthly_savings if monthly_savings else float("inf")


# ------------------------------------------------------------------
# 6. Chargeback vs showback
# ------------------------------------------------------------------
CHARGEBACK_VS_SHOWBACK = {
    "showback": "Visibility only — team sees their cost dashboard, no "
        "budget is actually debited. Lower friction to roll out, builds "
        "cost awareness before enforcing accountability.",
    "chargeback": "Team's cost-center budget is ACTUALLY debited for their "
        "usage. Requires accurate, trusted attribution (see tagging above) "
        "— rolling this out with unreliable attribution data destroys "
        "trust in the whole program.",
}

# ------------------------------------------------------------------
# 7. Waste detection
# ------------------------------------------------------------------
WASTE_SIGNALS = [
    "Idle nodes: cluster nodes with < 10% average CPU utilization over 7 days.",
    "Orphaned EBS/PVCs: volumes not attached to any running pod/instance.",
    "Unused load balancers: an ELB/ALB with zero requests over 30 days.",
    "Stopped instances with attached EBS: you still pay for the storage.",
    "Dev/staging environments running 24/7 when nobody works nights/weekends "
    "— scheduled scale-to-zero can cut ~65% off non-prod compute spend.",
]

if __name__ == "__main__":
    node = NodeCost(hourly_cost=2.40, cpu_cores=16, memory_gb=64)
    pods = [
        PodRequest("payments", cpu_cores=4, memory_gb=8),
        PodRequest("search", cpu_cores=2, memory_gb=4),
    ]
    print(allocate_node_cost(node, pods))
    print("Break-even months:", break_even_months(upfront_cost=12000, monthly_savings=800))

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A firm runs nightly backtests across a 200-node spot cluster (research
workload, fully interruptible) alongside an always-on 12-node on-demand
cluster for live order execution (cannot tolerate spot reclaim mid-trade).
Kubecost attributes the backtest cluster's cost to the "quant-research"
cost-center via namespace tagging; a monthly showback report shows the
backtest team their spend is trending up 15%/month, prompting them to
right-size their default job memory request from 32Gi to 12Gi after
observing p95 actual usage — a $9k/month saving with zero code change.
"""
