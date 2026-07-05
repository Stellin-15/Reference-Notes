# ============================================================
# L09: Feature and Model Lineage — Answering "What Depends on This?"
# ============================================================
# WHAT: How to build and query a LINEAGE GRAPH connecting raw data
#       sources, feature definitions, and the models that consume them
#       — so questions like "which models depend on this PII feature"
#       or "if I change this feature, what breaks" are answerable in
#       minutes, not by manually grepping through code.
# WHY: A feature platform (L01-L08) at real organizational scale becomes
#      IMPOSSIBLE to reason about without lineage — hundreds of features,
#      dozens of teams, many models, and no single person has the full
#      dependency graph memorized. Lineage turns tribal knowledge into a
#      queryable data structure.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
A LINEAGE GRAPH models three layers of dependency, each a node type: RAW
DATA SOURCES (Tier 1 tables, L02), FEATURE DEFINITIONS (Tier 2 registry
entries, L02-L03), and MODELS (which consume specific features, tracked
via model registry metadata — this repo's MLOps Notes covers MLflow's
registry). EDGES connect: a raw source FEEDS a feature definition, and a
feature definition IS USED BY a model. This is a DIRECTED graph — lineage
flows from raw data through features to models, and traversing it in
either direction answers different, both genuinely useful, questions.

DOWNSTREAM (forward) lineage answers: "if I change/deprecate/have a
data-quality incident in THIS raw source (or THIS feature), what
breaks?" — traverse edges FORWARD from the changed node to find every
feature and, transitively, every model that depends on it. This is the
question you MUST be able to answer before making a breaking change to
anything upstream.

UPSTREAM (backward) lineage answers: "where did THIS model's behavior
actually come from?" — traverse edges BACKWARD from a model to find
every feature (and, further back, every raw source) it depends on. This
is the question you need for debugging a model's unexpected behavior,
for compliance audits ("does this model use PII, and if so, from where"),
and for impact analysis before retraining.

The PII/COMPLIANCE use case deserves specific emphasis: regulations
increasingly require organizations to answer "which models make
decisions based on this specific piece of personal data" — without an
automated lineage graph, answering this requires manually auditing every
model's feature list against every feature's source data, an
error-prone, slow, and non-scalable process at any real organizational
scale. A properly built lineage graph makes this a graph query returning
results in seconds to minutes, not a multi-week manual audit.

Lineage data is typically CAPTURED AUTOMATICALLY as a side effect of the
platform's normal operation — every feature registration (L02's Tier 2
SDK) records its source table; every model training run (via the MLflow
integration this repo's MLOps Notes covers) records which Feature
Service/features it used. This automatic capture is what keeps the
lineage graph ACCURATE over time — a lineage system relying on manual,
separately-maintained documentation drifts out of sync with reality
almost immediately, the same failure mode as any manually-maintained
architecture diagram.

PRODUCTION USE CASE:
A privacy team needs to answer a regulatory data subject access request:
"which of our models used this specific customer's transaction history
to make a decision, and via which features." Querying the lineage graph
backward from every model that consumes any feature sourced from the
`transactions` table (filtered to features touching this customer's
data) produces a complete, auditable answer in minutes — a task that,
without automated lineage, would require manually inspecting every
model's feature dependencies against every feature's source logic.

COMMON MISTAKES:
- Building a lineage system that requires MANUAL entry/maintenance of
  dependency information — this drifts out of sync with reality as soon
  as anyone forgets to update it, which happens quickly at any real scale;
  lineage capture should be an automatic byproduct of normal registration/
  training operations, not a separate documentation task.
- Only tracking ONE direction of lineage (e.g. only "what does this
  model use," never "what depends on this source") — both directions
  answer genuinely different, both necessary, questions; a lineage
  system built for compliance audits alone (upstream-focused) won't
  help with impact analysis before a breaking change (downstream-focused).
- Treating lineage as a "nice to have" observability feature rather than
  a genuine PREREQUISITE for safely operating a feature platform at
  scale — the DEMS/Lasso-style event ledger pattern (L10) is often what
  makes accurate, automatically-captured lineage possible in the first place.
"""

from dataclasses import dataclass, field


# ------------------------------------------------------------------
# 1. The lineage graph — three node types, directed edges
# ------------------------------------------------------------------
@dataclass
class LineageNode:
    node_id: str
    node_type: str   # "source" | "feature" | "model"
    metadata: dict = field(default_factory=dict)


class LineageGraph:
    def __init__(self):
        self.nodes: dict[str, LineageNode] = {}
        self.edges: list[tuple[str, str]] = []   # (from_id, to_id) — dependency direction

    def add_node(self, node: LineageNode):
        self.nodes[node.node_id] = node

    def add_edge(self, from_id: str, to_id: str):
        """from_id FEEDS INTO / IS USED BY to_id — e.g. a source feeds a
        feature, or a feature is used by a model."""
        self.edges.append((from_id, to_id))

    def downstream(self, node_id: str, visited: set | None = None) -> set[str]:
        """Forward traversal: everything that TRANSITIVELY depends on node_id."""
        if visited is None:
            visited = set()
        direct = {to_id for (from_id, to_id) in self.edges if from_id == node_id}
        for d in direct:
            if d not in visited:
                visited.add(d)
                self.downstream(d, visited)
        return visited

    def upstream(self, node_id: str, visited: set | None = None) -> set[str]:
        """Backward traversal: everything node_id TRANSITIVELY depends on."""
        if visited is None:
            visited = set()
        direct = {from_id for (from_id, to_id) in self.edges if to_id == node_id}
        for d in direct:
            if d not in visited:
                visited.add(d)
                self.upstream(d, visited)
        return visited


# ------------------------------------------------------------------
# 2. Building a realistic graph and querying both directions
# ------------------------------------------------------------------
def build_example_graph() -> LineageGraph:
    g = LineageGraph()

    g.add_node(LineageNode("raw.customers", "source", {"contains_pii": True}))
    g.add_node(LineageNode("raw.transactions", "source", {"contains_pii": False}))
    g.add_node(LineageNode("feat.customer_risk_score", "feature", {"owner": "risk-team"}))
    g.add_node(LineageNode("feat.avg_transaction_7d", "feature", {"owner": "payments-team"}))
    g.add_node(LineageNode("model.fraud_detector_v2", "model", {}))
    g.add_node(LineageNode("model.churn_predictor_v1", "model", {}))

    g.add_edge("raw.customers", "feat.customer_risk_score")
    g.add_edge("raw.transactions", "feat.avg_transaction_7d")
    g.add_edge("feat.customer_risk_score", "model.fraud_detector_v2")
    g.add_edge("feat.avg_transaction_7d", "model.fraud_detector_v2")
    g.add_edge("feat.customer_risk_score", "model.churn_predictor_v1")

    return g


def answer_pii_compliance_question(g: LineageGraph) -> list[str]:
    """The compliance use case: which models transitively depend on a
    source flagged as containing PII?"""
    pii_sources = [n.node_id for n in g.nodes.values()
                   if n.node_type == "source" and n.metadata.get("contains_pii")]
    affected_models = set()
    for source in pii_sources:
        downstream_nodes = g.downstream(source)
        affected_models.update(n for n in downstream_nodes if g.nodes[n].node_type == "model")
    return sorted(affected_models)


def answer_impact_analysis_question(g: LineageGraph, changed_node: str) -> list[str]:
    """The pre-change safety check: what breaks if I modify/remove this node?"""
    return sorted(g.downstream(changed_node))


def answer_model_debugging_question(g: LineageGraph, model_id: str) -> list[str]:
    """The debugging/audit use case: what does this model actually depend on?"""
    return sorted(g.upstream(model_id))


if __name__ == "__main__":
    graph = build_example_graph()

    print("Models depending on any PII-flagged source (compliance query):")
    for model in answer_pii_compliance_question(graph):
        print(f"  {model}")

    print("\nImpact of changing 'raw.customers' (pre-change safety check):")
    for affected in answer_impact_analysis_question(graph, "raw.customers"):
        print(f"  {affected}")

    print("\nFull upstream dependency chain of 'model.fraud_detector_v2' (debugging/audit):")
    for dep in answer_model_debugging_question(graph, "model.fraud_detector_v2"):
        print(f"  {dep}")

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team plans to deprecate a legacy raw data source that several
older feature definitions still depend on — running the downstream
lineage query BEFORE deprecating it reveals two production models (one
of them customer-facing) still transitively depend on that source
through features nobody on the platform team realized were still active
— surfacing this dependency in a five-second graph query prevents what
would otherwise have been a production incident discovered only after
the deprecation actually broke those models' feature computation.
"""
