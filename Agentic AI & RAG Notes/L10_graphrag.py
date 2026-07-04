# ============================================================
# L10: GraphRAG — Knowledge-Graph-Based Retrieval
# ============================================================
# WHAT: How to build and query a KNOWLEDGE GRAPH extracted from your
#       document corpus (entities and their relationships), and
#       Microsoft's GraphRAG approach specifically — community detection
#       over the graph to answer BROAD, corpus-level questions that
#       chunk-level vector retrieval (L03-L04) handles poorly.
# WHY: Standard RAG retrieves individual CHUNKS — it's excellent at
#      "what does the document say about X" but genuinely struggles with
#      "what are the main THEMES across this entire corpus" or
#      "how are entity A and entity B connected" — questions that require
#      synthesizing information ACROSS many documents/chunks rather than
#      finding one relevant passage.
# LEVEL: Advanced (Phase 2 of 7 — final RAG-frameworks lesson before RAGFlow)
# ============================================================

"""
CONCEPT OVERVIEW:
Standard vector-based RAG (L03-L04) answers LOCAL questions well: "what
does this specific document say about refund policy" retrieves the one
or two chunks that directly discuss it. But GLOBAL questions — "what are
the main themes discussed across all 10,000 support tickets" or "how is
Company A connected to Company B across this corpus of news articles" —
don't have a single relevant chunk to retrieve; the answer requires
synthesizing information distributed across MANY documents, which
chunk-level similarity search fundamentally isn't designed to do.

GraphRAG (Microsoft's approach, and the general pattern) addresses this
by first building a KNOWLEDGE GRAPH from the corpus: an LLM extracts
ENTITIES (people, organizations, concepts) and RELATIONSHIPS between them
from each chunk, and these are merged into one graph where the SAME
entity mentioned across many documents becomes ONE node with edges to
everything it's connected to, corpus-wide.

COMMUNITY DETECTION (using graph algorithms like Leiden clustering) then
groups the graph into COMMUNITIES — densely-interconnected clusters of
related entities, which typically correspond to coherent THEMES or
TOPICS in the underlying corpus. GraphRAG pre-generates a SUMMARY for
each community (and hierarchically, summaries of summaries at multiple
levels of granularity) — so a broad query can be answered by retrieving
and synthesizing relevant COMMUNITY SUMMARIES (a "global search")
instead of trying to find one needle-in-haystack chunk, while a specific,
local query can still use standard entity-centric graph traversal
("local search" — find the entity, look at its direct neighborhood in
the graph) for precise, targeted answers.

PRODUCTION USE CASE:
A market-intelligence tool ingesting thousands of news articles uses
GraphRAG's global search to answer "what are the main competitive
dynamics in the EV battery supply chain this quarter" — a question no
single article chunk answers, but which the pre-computed community
summaries (each representing a cluster of related entities/events)
CAN synthesize into a coherent answer, while a specific query like "what
did Company X's CEO say about battery costs" uses local, entity-centric
graph search for a precise, traceable answer.

COMMON MISTAKES:
- Using GraphRAG for every RAG use case regardless of query pattern —
  the graph construction and community summarization process is
  significantly more expensive (in LLM calls during INDEXING) than
  standard chunk-based RAG; it's justified specifically for corpora
  where GLOBAL, thematic questions are a real, common use case, not a
  default upgrade for every RAG project.
- Expecting entity extraction to be perfectly accurate — LLM-based
  entity/relationship extraction has real error rates (missed entities,
  incorrectly merged/split entities across documents); GraphRAG's value
  is in aggregate, corpus-level synthesis, which is more robust to
  individual extraction errors than a system depending on any single
  extraction being perfectly correct.
- Not distinguishing WHEN to use global (community-summary-based) search
  versus local (entity-neighborhood) search — routing every query
  through the expensive global search path when a precise local query
  would answer it faster and more precisely wastes both cost and latency.
"""

import textwrap
from dataclasses import dataclass, field


# ------------------------------------------------------------------
# 1. Entity and relationship extraction (the graph-building step)
# ------------------------------------------------------------------
ENTITY_EXTRACTION_PROMPT_SKETCH = textwrap.dedent("""\
    # A real GraphRAG indexing pipeline sends EACH chunk through an LLM
    # with a prompt like this, extracting a structured list of entities
    # and relationships to be merged into the corpus-wide graph.

    EXTRACTION_PROMPT = '''
    Extract entities and relationships from the following text.
    Entities: people, organizations, and key concepts.
    Relationships: how entities are connected, with a brief description.

    Text: {chunk_text}

    Output format:
    Entities: [(name, type, description), ...]
    Relationships: [(source_entity, target_entity, description), ...]
    '''
""")


# ------------------------------------------------------------------
# 2. A simplified in-memory graph — nodes, edges, and merging
# ------------------------------------------------------------------
@dataclass
class GraphNode:
    name: str
    entity_type: str
    mentions: list[str] = field(default_factory=list)  # source chunks mentioning it


@dataclass
class GraphEdge:
    source: str
    target: str
    description: str


class KnowledgeGraph:
    def __init__(self):
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []

    def add_entity(self, name: str, entity_type: str, source_chunk: str):
        # THE key merging step: the same entity mentioned across MANY
        # different documents becomes ONE node with an accumulating list
        # of mentions — this is what lets community detection later find
        # patterns that span the whole corpus, not just one document.
        if name not in self.nodes:
            self.nodes[name] = GraphNode(name, entity_type, mentions=[])
        self.nodes[name].mentions.append(source_chunk)

    def add_relationship(self, source: str, target: str, description: str):
        self.edges.append(GraphEdge(source, target, description))

    def neighbors(self, entity_name: str) -> list[GraphEdge]:
        """LOCAL search: an entity's direct neighborhood — for precise,
        targeted queries about a specific named entity."""
        return [e for e in self.edges if e.source == entity_name or e.target == entity_name]


# ------------------------------------------------------------------
# 3. Community detection (simplified) and hierarchical summarization
# ------------------------------------------------------------------
def simplified_community_detection(graph: KnowledgeGraph) -> dict[str, list[str]]:
    """
    A REAL implementation uses a graph algorithm like Leiden clustering
    on edge density/weight — this simplified version just groups
    entities that share at least one edge, to illustrate the CONCEPT of
    partitioning the graph into densely-connected clusters without
    requiring a graph-algorithm library dependency.
    """
    communities: dict[str, list[str]] = {}
    assigned: dict[str, str] = {}
    community_counter = 0

    for edge in graph.edges:
        source_community = assigned.get(edge.source)
        target_community = assigned.get(edge.target)

        if source_community is None and target_community is None:
            community_id = f"community_{community_counter}"
            community_counter += 1
            communities[community_id] = [edge.source, edge.target]
            assigned[edge.source] = community_id
            assigned[edge.target] = community_id
        elif source_community is not None:
            communities[source_community].append(edge.target)
            assigned[edge.target] = source_community
        elif target_community is not None:
            communities[target_community].append(edge.source)
            assigned[edge.source] = target_community

    return communities


COMMUNITY_SUMMARIZATION_SKETCH = textwrap.dedent("""\
    # For EACH detected community, an LLM generates a summary from the
    # entities/relationships/source text within it — pre-computed at
    # INDEXING time, not at query time, which is what makes global
    # search fast despite synthesizing information across many documents.

    SUMMARY_PROMPT = '''
    Summarize the key theme connecting these entities and their relationships:
    Entities: {community_entities}
    Relationships: {community_relationships}
    '''
    # These summaries are stored and become the retrieval unit for
    # GLOBAL search — instead of retrieving chunks, global search
    # retrieves and synthesizes relevant COMMUNITY SUMMARIES.
""")

# ------------------------------------------------------------------
# 4. Global search vs local search — when to use which
# ------------------------------------------------------------------
SEARCH_MODE_COMPARISON = {
    "Local search (entity-centric)": "Find a specific named entity, "
        "traverse its direct graph neighborhood — best for precise "
        "questions about a KNOWN entity ('what did Company X say about Y').",
    "Global search (community-summary-based)": "Retrieve and synthesize "
        "relevant pre-computed COMMUNITY SUMMARIES — best for broad, "
        "thematic questions spanning the whole corpus ('what are the "
        "main themes across all documents').",
}


if __name__ == "__main__":
    print(ENTITY_EXTRACTION_PROMPT_SKETCH)

    graph = KnowledgeGraph()
    graph.add_entity("Company A", "Organization", "article_1")
    graph.add_entity("Company B", "Organization", "article_2")
    graph.add_entity("Battery Supply Chain", "Concept", "article_1")
    graph.add_relationship("Company A", "Battery Supply Chain", "supplies raw materials to")
    graph.add_relationship("Company B", "Battery Supply Chain", "competes for the same suppliers as")

    print("Local search — neighbors of 'Company A':")
    for edge in graph.neighbors("Company A"):
        print(f"  {edge.source} --[{edge.description}]--> {edge.target}")

    print("\n--- Community detection ---")
    communities = simplified_community_detection(graph)
    for cid, members in communities.items():
        print(f"  {cid}: {members}")

    print(COMMUNITY_SUMMARIZATION_SKETCH)

    print("=== Search mode comparison ===")
    for mode, note in SEARCH_MODE_COMPARISON.items():
        print(f"{mode}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An investment research firm's GraphRAG system, built over years of
earnings call transcripts, answers a broad query like "what are the
emerging risks across the semiconductor industry this year" via global
search over pre-computed community summaries (synthesizing patterns
across hundreds of transcripts no single chunk-level search could find),
while an analyst's follow-up question "what specifically did NVIDIA's
CFO say about supply constraints" is answered via fast, precise local
search on the NVIDIA entity's direct graph neighborhood — the same
system serving both query types by routing to the appropriate search mode.
"""
