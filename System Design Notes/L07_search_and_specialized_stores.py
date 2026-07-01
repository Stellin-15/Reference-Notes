# =============================================================================
# WHAT: Search Engines and Specialized Data Stores
# WHY:  A relational database is the wrong tool for full-text search, vector
#       similarity, time-series analysis, and graph traversal. Each of these
#       problem shapes has a store built specifically for it.
# LEVEL: Intermediate → Advanced (System Design Interview / Production Ready)
# =============================================================================
#
# CONCEPT OVERVIEW:
#   Elasticsearch   → inverted index; full-text search, log analytics, faceted search.
#   Vector Database → ANN search over high-dimensional embeddings (AI/ML retrieval).
#   Time-Series DB  → append-only, time-ordered; optimised for aggregations over time.
#   Graph Database  → nodes + edges; efficient graph traversals and relationship queries.
#
# PRODUCTION USE CASES:
#   - GitHub uses Elasticsearch to search across billions of lines of code.
#   - Spotify uses vector search (embeddings) to power "Songs You Might Like".
#   - Tesla uses InfluxDB for vehicle telemetry (time-series at massive scale).
#   - LinkedIn uses Neo4j for "People You May Know" (graph traversal, 2nd/3rd degree).
#
# COMMON MISTAKES:
#   1. Using Elasticsearch as the primary source of truth (it's a search index, not a DB).
#   2. Not setting shard count appropriately for Elasticsearch (too many = overhead).
#   3. Storing raw events without downsampling in a time-series DB (storage explosion).
#   4. Using a graph DB for non-graph workloads (it's slower than relational for flat data).
#   5. Choosing cosine similarity when Euclidean distance is more appropriate (or vice versa).
#   6. Forgetting to normalise embeddings before cosine similarity computation.
# =============================================================================

import math
import time
import heapq
import random
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Set
from collections import defaultdict
from enum import Enum

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# =============================================================================
# SECTION 1: ELASTICSEARCH — INVERTED INDEX
# =============================================================================
# An INVERTED INDEX maps each unique term → list of documents containing that term.
# This is the opposite of a forward index (document → list of terms).
#
# EXAMPLE:
#   doc1: "the quick brown fox"
#   doc2: "the lazy brown dog"
#   Inverted index:
#     "quick" → [doc1]
#     "fox"   → [doc1]
#     "lazy"  → [doc2]
#     "dog"   → [doc2]
#     "brown" → [doc1, doc2]
#     "the"   → [doc1, doc2]  ← stopword; usually filtered out
#
# SEARCH "brown fox":
#   Fetch postings for "brown" → {doc1, doc2}
#   Fetch postings for "fox"   → {doc1}
#   Intersect → {doc1}  (AND query)
#   OR union  → {doc1, doc2}  (OR query)
#
# ELASTICSEARCH ADDITIONAL CONCEPTS:
#   TF-IDF / BM25 → relevance scoring (how well does a document match the query?)
#   Analyzer      → tokenise + normalise text: lowercase, remove stopwords, stem/lemmatise
#   Mapping       → schema for an index (field types: keyword, text, date, integer, ...)
#   Shard         → a single Lucene index; Elasticsearch distributes shards across nodes
#   Replica       → copy of a shard for read scalability and high availability

class Analyzer:
    """
    Simulates an Elasticsearch text analyzer pipeline.
    STAGES: character filter → tokenizer → token filters
    PRODUCTION: use built-in analyzers (standard, english) or custom ones in ES mapping.
    """

    STOPWORDS = {"the", "a", "an", "is", "in", "on", "at", "to", "for", "of", "and", "or"}

    def analyze(self, text: str) -> List[str]:
        """
        Tokenise and normalise text into indexable terms.
        In production, Elasticsearch runs this pipeline at index time AND query time.
        """
        text = text.lower()                        # lowercase filter
        tokens = text.split()                      # whitespace tokenizer
        tokens = [t.strip(".,!?;:\"'()") for t in tokens]  # punctuation strip
        tokens = [t for t in tokens if t and t not in self.STOPWORDS]  # stopword removal
        tokens = [self._simple_stem(t) for t in tokens]    # basic stemming
        return tokens

    @staticmethod
    def _simple_stem(word: str) -> str:
        """Very simplified stemming (real ES uses Snowball stemmer)."""
        for suffix in ("ing", "ed", "s", "er", "ly"):
            if word.endswith(suffix) and len(word) - len(suffix) > 2:
                return word[: -len(suffix)]
        return word


@dataclass
class ESDocument:
    """Represents one document stored in an Elasticsearch index."""
    doc_id: str
    fields: Dict[str, Any]  # e.g., {"title": "Quick Brown Fox", "category": "animals"}


class InvertedIndex:
    """
    Simplified inverted index demonstrating Elasticsearch's core data structure.
    Each term maps to a posting list: list of (doc_id, term_frequency) pairs.
    """

    def __init__(self, analyzer: Optional[Analyzer] = None):
        self.analyzer = analyzer or Analyzer()
        # term → {doc_id: term_frequency}
        self._postings: Dict[str, Dict[str, int]] = defaultdict(dict)
        self._docs: Dict[str, ESDocument] = {}      # forward index: doc_id → document
        self._doc_count: int = 0                    # total documents (for IDF calculation)

    def index(self, doc: ESDocument, field: str = "title"):
        """Add a document to the index."""
        self._docs[doc.doc_id] = doc
        self._doc_count += 1
        text = str(doc.fields.get(field, ""))
        terms = self.analyzer.analyze(text)
        for term in terms:
            # increment term frequency for this document
            tf = self._postings[term].get(doc.doc_id, 0)
            self._postings[term][doc.doc_id] = tf + 1

    def search(self, query: str, operator: str = "OR", top_k: int = 5) -> List[Tuple[str, float]]:
        """
        Execute a full-text query and return top_k results ranked by BM25-like score.
        operator: "AND" → all terms must match; "OR" → any term matches.
        """
        terms = self.analyzer.analyze(query)
        if not terms:
            return []

        # Gather candidate doc IDs
        if operator == "AND":
            # start with all docs; intersect with each term's posting list
            candidates: Set[str] = set(self._postings.get(terms[0], {}).keys())
            for term in terms[1:]:
                candidates &= set(self._postings.get(term, {}).keys())
        else:  # OR
            candidates = set()
            for term in terms:
                candidates |= set(self._postings.get(term, {}).keys())

        # Score each candidate using a simplified TF-IDF
        scored = []
        for doc_id in candidates:
            score = self._score(doc_id, terms)
            scored.append((doc_id, score))

        # Return top_k results sorted by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _score(self, doc_id: str, terms: List[str]) -> float:
        """
        Simplified BM25 scoring (real Elasticsearch uses full BM25 with field length norms).
        BM25 is the default similarity algorithm in Elasticsearch since version 5.0.
        TF-IDF intuition:
          TF  (term frequency): term appearing more in a doc → more relevant.
          IDF (inverse document frequency): term in fewer docs → more specific → more weight.
        """
        score = 0.0
        n = max(self._doc_count, 1)  # total doc count
        for term in terms:
            posting = self._postings.get(term, {})
            tf = posting.get(doc_id, 0)
            df = len(posting)  # number of docs containing this term
            if tf > 0 and df > 0:
                # IDF: terms in fewer documents are more distinctive
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
                # TF component: diminishing returns for high frequency
                k1 = 1.2  # BM25 saturation parameter (typically 1.2–2.0)
                tf_score = (tf * (k1 + 1)) / (tf + k1)
                score += idf * tf_score
        return score


# =============================================================================
# SECTION 2: ELASTICSEARCH QUERY DSL (conceptual reference)
# =============================================================================
# Full-text search → use "match" or "multi_match" queries (analyzed).
# Exact match      → use "term" or "terms" queries on keyword fields.
# Range queries    → use "range" on numeric/date fields.
# Boolean queries  → combine with "bool" (must/should/must_not/filter).
# Aggregations     → compute metrics (avg, sum, terms, date_histogram) over results.

ES_QUERY_EXAMPLES = {
    "match": {
        # Analyzed full-text search on 'title' field
        "query": {"match": {"title": "quick brown fox"}}
    },
    "multi_match": {
        # Search across multiple fields; title is boosted (^3 = 3x weight)
        "query": {"multi_match": {"query": "laptop", "fields": ["title^3", "description"]}}
    },
    "bool_query": {
        "query": {
            "bool": {
                "must":     [{"match": {"title": "elasticsearch"}}],  # required terms
                "filter":   [{"term": {"status": "published"}}],      # exact match (no scoring)
                "must_not": [{"term": {"archived": True}}],           # exclude archived
                "should":   [{"match": {"tags": "search"}}],          # boost if present
            }
        }
    },
    "range_query": {
        "query": {"range": {"price": {"gte": 10, "lte": 100}}}
    },
    "aggregation": {
        # Terms aggregation: count docs per category (like SQL GROUP BY category)
        "aggs": {
            "by_category": {
                "terms": {"field": "category.keyword"},
                "aggs": {"avg_price": {"avg": {"field": "price"}}}  # nested avg per category
            }
        }
    },
    "mapping_example": {
        # Define field types upfront — 'text' is analyzed; 'keyword' is not
        "mappings": {
            "properties": {
                "title":       {"type": "text", "analyzer": "english"},
                "category":    {"type": "keyword"},  # exact match only
                "price":       {"type": "float"},
                "created_at":  {"type": "date"},
                "description": {"type": "text"},
            }
        }
    },
}

# ELASTICSEARCH SHARDING GUIDELINES:
# - Target shard size: 10–50 GB per shard (Elastic's recommendation)
# - Number of shards = (total data size GB) / (target shard size GB)
# - Primary shards are set at index creation — cannot be changed later!
# - Replicas can be changed at any time.
# - Too many small shards: overhead per shard; too few large shards: slow queries.


# =============================================================================
# SECTION 3: VECTOR DATABASES
# =============================================================================
# Vector databases store high-dimensional embeddings and enable Approximate
# Nearest Neighbour (ANN) search — finding the K most similar vectors to a query.
#
# EMBEDDING: a dense float vector (e.g., 1536 dimensions for OpenAI ada-002)
# representing the semantic meaning of text, images, audio, etc.
#
# SIMILARITY METRICS:
#   Cosine similarity    → angle between vectors; ignores magnitude. Best for text.
#   Euclidean distance   → straight-line distance. Best for image embeddings.
#   Dot product          → cosine similarity × magnitude. Used when magnitude matters.
#
# ANN ALGORITHMS:
#   HNSW (Hierarchical Navigable Small World): graph-based; fastest for high recall.
#     Used by: Weaviate, Milvus, pgvector, Elasticsearch.
#   IVF (Inverted File Index): cluster-based; good for very large datasets.
#     Used by: FAISS (Facebook AI Similarity Search), Pinecone.
#   ANNOY (Approximate Nearest Neighbours Oh Yeah): tree-based; read-optimised.
#     Used by: Spotify Annoy (open-source).
#
# PRODUCTION USE CASES:
#   - RAG (Retrieval-Augmented Generation): find relevant chunks before calling LLM.
#   - Recommendation engines: find users/items with similar embeddings.
#   - Semantic search: find documents similar in meaning, not exact keyword match.
#   - Duplicate detection: find near-duplicate content at scale.

class SimilarityMetric(Enum):
    COSINE    = "cosine"
    EUCLIDEAN = "euclidean"
    DOT       = "dot_product"


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity between two vectors: cos(θ) = (a·b) / (|a| × |b|).
    Range: -1 (opposite) to 1 (identical direction).
    IMPORTANT: normalise vectors to unit length before storing for efficiency —
               dot product of unit vectors equals cosine similarity.
    """
    dot = sum(x * y for x, y in zip(a, b))       # dot product
    norm_a = math.sqrt(sum(x * x for x in a))     # |a|
    norm_b = math.sqrt(sum(y * y for y in b))      # |b|
    if norm_a == 0 or norm_b == 0:
        return 0.0  # undefined for zero vectors
    return dot / (norm_a * norm_b)


def euclidean_distance(a: List[float], b: List[float]) -> float:
    """
    Euclidean (L2) distance between two vectors.
    Lower = more similar. To convert to similarity: 1 / (1 + distance).
    """
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def normalize_vector(v: List[float]) -> List[float]:
    """Normalise a vector to unit length (L2 norm = 1)."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return v
    return [x / norm for x in v]


@dataclass
class VectorDocument:
    """One entry in a vector database."""
    doc_id: str
    embedding: List[float]          # the dense vector representation
    metadata: Dict[str, Any] = field(default_factory=dict)  # filterable fields


class BruteForceVectorStore:
    """
    Brute-force vector store (exact nearest neighbour search).
    Scans every stored vector — O(N × D) per query.
    PRODUCTION: only viable for < 10K vectors.
    For millions of vectors, use HNSW or IVF via FAISS, pgvector, Pinecone, etc.
    """

    def __init__(self, metric: SimilarityMetric = SimilarityMetric.COSINE):
        self.metric = metric
        self._store: List[VectorDocument] = []

    def add(self, doc: VectorDocument):
        """Insert a document with its embedding."""
        if self.metric == SimilarityMetric.COSINE:
            # Pre-normalise for faster cosine via dot product at query time
            doc.embedding = normalize_vector(doc.embedding)
        self._store.append(doc)

    def search(self, query_vector: List[float], top_k: int = 5,
               filter_fn: Optional[Any] = None) -> List[Tuple[str, float]]:
        """
        Return top_k most similar documents to the query vector.
        filter_fn: optional callable(doc) → bool for pre-filtering by metadata.
        """
        if self.metric == SimilarityMetric.COSINE:
            query_vector = normalize_vector(query_vector)

        candidates = self._store if filter_fn is None else [d for d in self._store if filter_fn(d)]

        scored = []
        for doc in candidates:
            if self.metric == SimilarityMetric.COSINE:
                score = cosine_similarity(query_vector, doc.embedding)
                scored.append((doc.doc_id, score))
            elif self.metric == SimilarityMetric.EUCLIDEAN:
                dist = euclidean_distance(query_vector, doc.embedding)
                scored.append((doc.doc_id, -dist))  # negate: higher = better

        scored.sort(key=lambda x: x[1], reverse=True)  # highest score first
        return scored[:top_k]


class HNSWIndex:
    """
    Conceptual sketch of the HNSW algorithm (not a complete implementation).
    HNSW builds a multi-layer graph where each node connects to M nearest neighbours.
    SEARCH: start at the top layer (fewest nodes); greedily descend toward query.
    COMPLEXITY: O(log N) per query; O(N × M × log N) build time.
    PARAMETERS:
      M         → number of neighbours per node (16–64 typical; higher = better recall, more memory)
      efConstruction → search width during index build (higher = better recall, slower build)
      ef        → search width at query time (higher = better recall, slower query)
    PRODUCTION: pgvector extension for PostgreSQL uses HNSW natively.
    """

    def __init__(self, dim: int, M: int = 16, ef_construction: int = 200):
        self.dim = dim                     # embedding dimension
        self.M = M                         # max connections per node
        self.ef_construction = ef_construction
        self._layers: List[Dict[int, List[int]]] = []  # simplified layer graph
        self._vectors: List[List[float]] = []           # stored vectors

    def add_vector(self, vector: List[float]):
        """
        Insert a vector into the HNSW graph.
        Actual implementation assigns the vector to a random highest layer
        using a geometric distribution, then connects it to M neighbours at each layer.
        """
        node_id = len(self._vectors)
        self._vectors.append(normalize_vector(vector))
        # Simplified: just record that the node exists
        logger.debug(f"HNSW: added node {node_id} to index")

    def search_knn(self, query: List[float], k: int = 5) -> List[int]:
        """
        Greedy layer descent to find k approximate nearest neighbours.
        Real HNSW maintains ef candidates during descent for better recall.
        This sketch returns node IDs.
        """
        query = normalize_vector(query)
        if not self._vectors:
            return []
        # Simplified: brute-force over stored vectors (real HNSW uses graph traversal)
        scored = [
            (cosine_similarity(query, v), i)
            for i, v in enumerate(self._vectors)
        ]
        scored.sort(reverse=True)
        return [i for _, i in scored[:k]]


# =============================================================================
# SECTION 4: HYBRID SEARCH
# =============================================================================
# HYBRID SEARCH = combine keyword (BM25) and vector (semantic) search results.
# WHY: keyword search is precise for exact terms; vector search finds semantically
#      similar content even when keywords don't match.
# ALGORITHM: Reciprocal Rank Fusion (RRF) or weighted linear combination.
#
# RECIPROCAL RANK FUSION (RRF):
#   score(doc, result_list) = Σ 1 / (k + rank_in_list)
#   k = 60 (constant that dampens high-rank dominance; from Cormack et al. 2009)

def reciprocal_rank_fusion(
    keyword_results: List[str],   # doc_ids ranked by keyword score
    vector_results: List[str],    # doc_ids ranked by vector similarity
    k: int = 60,
) -> List[Tuple[str, float]]:
    """
    Merge two ranked lists using RRF.
    Higher final score = better overall relevance.
    Used by Elasticsearch 8.9+ as the default hybrid search merger.
    """
    scores: Dict[str, float] = defaultdict(float)

    for rank, doc_id in enumerate(keyword_results, start=1):
        scores[doc_id] += 1.0 / (k + rank)  # contribution from keyword ranking

    for rank, doc_id in enumerate(vector_results, start=1):
        scores[doc_id] += 1.0 / (k + rank)  # contribution from vector ranking

    # sort by combined RRF score descending
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# =============================================================================
# SECTION 5: TIME-SERIES DATABASES (InfluxDB / TimescaleDB)
# =============================================================================
# TIME-SERIES DB: optimised for time-ordered, append-only data.
# CHARACTERISTICS:
#   - Write-heavy: thousands of data points per second are common.
#   - Queries are almost always time-range bounded: "last hour", "last 7 days".
#   - Aggregation is more important than individual row retrieval.
#   - Old data becomes less valuable → downsampling and retention policies.
#
# KEY CONCEPTS:
#   Measurement  → like a table; groups related time-series (e.g., "cpu_usage")
#   Tags         → indexed string metadata; used for filtering (e.g., host="web-01")
#   Fields       → actual numeric/string values (e.g., cpu_percent=72.4)
#   Timestamp    → nanosecond precision in InfluxDB
#
# DOWNSAMPLING: aggregate raw data into lower-resolution summaries.
#   WHY: 1-second granularity for 1 year = 31M rows/series; wasteful for dashboards.
#   HOW: run a continuous query every hour: compute mean/max/min for that hour;
#        store in a separate "downsampled" measurement; drop raw data after retention period.
#
# RETENTION POLICY: automatically delete data older than N days.
# CONTINUOUS AGGREGATES (TimescaleDB): materialised views that auto-refresh.

@dataclass
class DataPoint:
    """One time-series observation."""
    measurement: str                    # e.g., "cpu_usage"
    tags: Dict[str, str]               # e.g., {"host": "web-01", "region": "us-east"}
    fields: Dict[str, float]           # e.g., {"cpu_percent": 72.4, "mem_percent": 45.1}
    timestamp: float = field(default_factory=time.time)  # Unix epoch in seconds


class InMemoryTimeSeriesStore:
    """
    Simplified time-series store demonstrating append, range query, and downsampling.
    Production: InfluxDB (OSS / Cloud), TimescaleDB (PostgreSQL extension).
    """

    def __init__(self, retention_seconds: float = 7 * 86400):  # 7 days default
        self._data: List[DataPoint] = []  # append-only; sorted by time in practice
        self.retention_seconds = retention_seconds

    def write(self, point: DataPoint):
        """Append a new data point. Real InfluxDB batches these for efficiency."""
        self._data.append(point)
        self._evict_expired()  # enforce retention policy on write

    def _evict_expired(self):
        """Remove data points older than the retention period."""
        cutoff = time.time() - self.retention_seconds
        # keep only data within retention window
        self._data = [p for p in self._data if p.timestamp >= cutoff]

    def query_range(
        self,
        measurement: str,
        field: str,
        start: float,
        end: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> List[Tuple[float, float]]:
        """
        Return (timestamp, field_value) pairs for the specified measurement and time range.
        Tag filters narrow the result (e.g., only for host="web-01").
        """
        results = []
        for point in self._data:
            if point.measurement != measurement:
                continue
            if not (start <= point.timestamp <= end):
                continue
            if tags and not all(point.tags.get(k) == v for k, v in tags.items()):
                continue  # tag filter mismatch
            if field in point.fields:
                results.append((point.timestamp, point.fields[field]))
        return sorted(results, key=lambda x: x[0])  # sort by timestamp

    def downsample(
        self,
        measurement: str,
        field: str,
        bucket_seconds: int = 3600,  # 1-hour buckets
        agg: str = "mean",           # "mean", "max", "min", "sum"
    ) -> List[Tuple[float, float]]:
        """
        Aggregate data into time buckets for dashboards and long-term storage.
        PRODUCTION: run as a scheduled job; store results in a separate retention tier.
        """
        buckets: Dict[int, List[float]] = defaultdict(list)
        for point in self._data:
            if point.measurement != measurement or field not in point.fields:
                continue
            bucket_key = int(point.timestamp // bucket_seconds) * bucket_seconds
            buckets[bucket_key].append(point.fields[field])

        aggregated = []
        for bucket_ts in sorted(buckets):
            values = buckets[bucket_ts]
            if agg == "mean":
                agg_value = sum(values) / len(values)
            elif agg == "max":
                agg_value = max(values)
            elif agg == "min":
                agg_value = min(values)
            else:  # sum
                agg_value = sum(values)
            aggregated.append((float(bucket_ts), agg_value))

        return aggregated


# =============================================================================
# SECTION 6: GRAPH DATABASES (Neo4j)
# =============================================================================
# GRAPH DATABASE: data is stored as nodes (entities) and edges (relationships).
# OPTIMISED FOR: traversing relationships — following edges is O(edges), not O(table rows).
# In a relational DB, "friends of friends" requires an expensive JOIN on a self-referencing table.
# In Neo4j, the same query traverses pointers in memory — orders of magnitude faster.
#
# NEO4J CONCEPTS:
#   Node     → entity (labelled: :User, :Product, :Movie)
#   Edge     → relationship with direction and type (:FOLLOWS, :PURCHASED, :ACTED_IN)
#   Property → key-value attributes on nodes or edges
#   Cypher   → Neo4j query language (similar to SQL but for graphs)
#
# CYPHER EXAMPLES:
#   MATCH (u:User {id: "alice"})-[:FOLLOWS]->(friend)
#   RETURN friend.name
#   --- finds all users that Alice follows
#
#   MATCH (u:User)-[:FOLLOWS*2]->(fof)
#   WHERE u.id = "alice" AND NOT (u)-[:FOLLOWS]->(fof)
#   RETURN DISTINCT fof.name
#   --- finds friends-of-friends (2 hops) that Alice doesn't already follow
#
#   MATCH (u)-[:PURCHASED]->(p:Product)<-[:PURCHASED]-(other)
#   WHERE u.id = "alice"
#   RETURN other.name, COUNT(*) AS shared ORDER BY shared DESC LIMIT 10
#   --- collaborative filtering: users who bought what Alice bought

@dataclass
class GraphNode:
    node_id: str
    labels: List[str]             # e.g., ["User"], ["Product"]
    properties: Dict[str, Any]


@dataclass
class GraphEdge:
    edge_id: str
    from_id: str                  # source node ID
    to_id: str                    # target node ID
    rel_type: str                 # e.g., "FOLLOWS", "PURCHASED"
    properties: Dict[str, Any] = field(default_factory=dict)


class InMemoryGraphDB:
    """
    Simplified adjacency-list graph database (conceptual; not production-grade).
    Production: Neo4j Community/Enterprise, Amazon Neptune, TigerGraph.
    """

    def __init__(self):
        self._nodes: Dict[str, GraphNode] = {}
        # adjacency list: from_id → list of (to_id, rel_type, properties)
        self._adj: Dict[str, List[Tuple[str, str, Dict]]] = defaultdict(list)
        self._reverse_adj: Dict[str, List[Tuple[str, str, Dict]]] = defaultdict(list)

    def add_node(self, node: GraphNode):
        self._nodes[node.node_id] = node

    def add_edge(self, edge: GraphEdge):
        """Add a directed edge. Also record in reverse adjacency for incoming traversal."""
        self._adj[edge.from_id].append((edge.to_id, edge.rel_type, edge.properties))
        self._reverse_adj[edge.to_id].append((edge.from_id, edge.rel_type, edge.properties))

    def get_neighbours(self, node_id: str, rel_type: Optional[str] = None) -> List[str]:
        """Return node IDs of all nodes reachable from node_id via outgoing edges."""
        neighbours = self._adj.get(node_id, [])
        if rel_type:
            return [nid for nid, rtype, _ in neighbours if rtype == rel_type]
        return [nid for nid, _, _ in neighbours]

    def bfs(self, start_id: str, rel_type: Optional[str] = None, max_depth: int = 2) -> Dict[str, int]:
        """
        BFS traversal up to max_depth hops.
        Returns {node_id: depth} for all reachable nodes.
        Simulates Cypher's variable-length path: -[:FOLLOWS*1..2]->
        """
        visited = {start_id: 0}
        queue = [(start_id, 0)]
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for neighbour_id in self.get_neighbours(current, rel_type):
                if neighbour_id not in visited:
                    visited[neighbour_id] = depth + 1
                    queue.append((neighbour_id, depth + 1))
        return visited

    def friends_of_friends(self, user_id: str) -> Set[str]:
        """
        Find 2nd-degree connections (friends-of-friends) excluding direct connections.
        Simulates the Cypher query pattern MATCH (u)-[:FOLLOWS*2]->(fof).
        """
        direct = set(self.get_neighbours(user_id, "FOLLOWS"))  # 1st degree
        fof = set()
        for friend_id in direct:
            # get friends of each direct friend
            fof.update(self.get_neighbours(friend_id, "FOLLOWS"))
        # exclude direct connections and the user themselves
        return fof - direct - {user_id}

    def shortest_path(self, start_id: str, end_id: str) -> Optional[List[str]]:
        """BFS shortest path between two nodes."""
        if start_id == end_id:
            return [start_id]
        visited = {start_id: [start_id]}  # node_id → path taken to reach it
        queue = [start_id]
        while queue:
            current = queue.pop(0)
            for neighbour in self.get_neighbours(current):
                if neighbour not in visited:
                    path = visited[current] + [neighbour]
                    visited[neighbour] = path
                    if neighbour == end_id:
                        return path  # found shortest path
                    queue.append(neighbour)
        return None  # no path exists


# =============================================================================
# SECTION 7: WHEN TO USE EACH SPECIALIZED STORE
# =============================================================================

STORE_SELECTION_GUIDE = {
    "Elasticsearch": {
        "use_when": [
            "Full-text search over documents (product descriptions, articles)",
            "Log analytics with Kibana dashboards (ELK stack)",
            "Faceted search with filters and aggregations",
            "Autocomplete and search-as-you-type features",
        ],
        "avoid_when": [
            "Primary transactional store (it's an index, not a source of truth)",
            "Strict ACID requirements",
            "Simple key-value lookups (Redis is faster and simpler)",
        ],
        "shard_sizing": "10–50 GB per shard; keep total shard count < 20 per node",
    },
    "Vector Database (Pinecone / Weaviate / pgvector)": {
        "use_when": [
            "Semantic search over embeddings (text, images, audio)",
            "RAG (Retrieval-Augmented Generation) for LLM applications",
            "Recommendation systems based on item/user embeddings",
            "Duplicate/near-duplicate content detection",
        ],
        "avoid_when": [
            "Exact keyword search (use Elasticsearch instead)",
            "Transactional workloads",
            "Very small datasets (< 1000 vectors; just use brute-force in memory)",
        ],
        "algorithm_guide": "HNSW for recall quality; IVF for very large datasets (100M+)",
    },
    "Time-Series DB (InfluxDB / TimescaleDB)": {
        "use_when": [
            "IoT sensor data (temperature, pressure, GPS)",
            "Infrastructure monitoring (CPU, memory, network metrics)",
            "Financial market data (tick data, OHLCV)",
            "Application performance metrics (latency percentiles, error rates)",
        ],
        "avoid_when": [
            "Non-time-ordered data",
            "Frequent updates to historical data (time-series DBs are append-optimised)",
            "Complex relational queries across multiple entity types",
        ],
        "key_config": "Set retention policies and continuous aggregates from day one",
    },
    "Graph DB (Neo4j / Neptune)": {
        "use_when": [
            "Social network features (friends, followers, recommendations)",
            "Fraud detection (shared phone/email/address patterns form a graph)",
            "Knowledge graphs and ontology management",
            "Network topology and dependency analysis (CI/CD pipeline graphs)",
        ],
        "avoid_when": [
            "Flat relational data without meaningful relationships",
            "High write throughput (graph DBs are typically read-optimised)",
            "Data that fits naturally in tables (use PostgreSQL)",
        ],
        "cypher_tip": "Variable-length paths (-[:KNOWS*1..3]->) are graph's killer feature",
    },
}


# =============================================================================
# SECTION 8: DEMO
# =============================================================================

def demo():
    print("\n" + "="*60)
    print("ELASTICSEARCH INVERTED INDEX DEMO")
    print("="*60)

    index = InvertedIndex()
    docs = [
        ESDocument("d1", {"title": "Quick brown fox jumps over the lazy dog"}),
        ESDocument("d2", {"title": "The lazy cat sat on the mat"}),
        ESDocument("d3", {"title": "Elasticsearch is a distributed search engine"}),
        ESDocument("d4", {"title": "Search engines use inverted indexes for fast retrieval"}),
    ]
    for d in docs:
        index.index(d)

    print("\nSearch 'lazy dog' (OR):", index.search("lazy dog", operator="OR"))
    print("Search 'search engine' (AND):", index.search("search engine", operator="AND"))

    print("\n" + "="*60)
    print("VECTOR SIMILARITY SEARCH DEMO")
    print("="*60)

    store = BruteForceVectorStore(SimilarityMetric.COSINE)
    # 3-dimensional embeddings for simplicity
    store.add(VectorDocument("doc-cats",    [0.9, 0.1, 0.0], {"category": "animals"}))
    store.add(VectorDocument("doc-dogs",    [0.8, 0.2, 0.1], {"category": "animals"}))
    store.add(VectorDocument("doc-python",  [0.0, 0.1, 0.9], {"category": "programming"}))
    store.add(VectorDocument("doc-java",    [0.0, 0.2, 0.8], {"category": "programming"}))

    query = [0.85, 0.15, 0.05]  # "pet animals" embedding (hypothetical)
    results = store.search(query, top_k=3)
    print("\nTop-3 similar to query [0.85, 0.15, 0.05]:")
    for doc_id, score in results:
        print(f"  {doc_id}: similarity={score:.4f}")

    # Hybrid search demo
    keyword_results = ["doc-dogs", "doc-cats", "doc-python"]
    vector_results  = ["doc-cats", "doc-dogs", "doc-java"]
    fused = reciprocal_rank_fusion(keyword_results, vector_results)
    print(f"\nHybrid search (RRF): {fused}")

    print("\n" + "="*60)
    print("GRAPH DATABASE DEMO")
    print("="*60)

    db = InMemoryGraphDB()
    for uid in ["alice", "bob", "charlie", "diana", "eve"]:
        db.add_node(GraphNode(uid, ["User"], {"name": uid}))

    edges = [
        ("alice", "bob"),    # alice follows bob
        ("alice", "charlie"),
        ("bob", "diana"),    # bob follows diana
        ("charlie", "eve"),
        ("diana", "eve"),
    ]
    for src, dst in edges:
        db.add_edge(GraphEdge(f"{src}->{dst}", src, dst, "FOLLOWS"))

    print(f"\nAlice's direct follows: {db.get_neighbours('alice', 'FOLLOWS')}")
    print(f"Friends-of-friends for Alice: {db.friends_of_friends('alice')}")
    print(f"Shortest path alice → eve: {db.shortest_path('alice', 'eve')}")

    print("\n" + "="*60)
    print("TIME-SERIES STORE DEMO")
    print("="*60)

    ts = InMemoryTimeSeriesStore(retention_seconds=86400)
    base_time = time.time() - 3600  # 1 hour ago
    for i in range(60):  # 60 data points, 1 per minute
        ts.write(DataPoint(
            measurement="cpu_usage",
            tags={"host": "web-01"},
            fields={"cpu_percent": 40.0 + random.uniform(-10, 30)},
            timestamp=base_time + i * 60,
        ))

    raw = ts.query_range("cpu_usage", "cpu_percent",
                         start=base_time, end=time.time(),
                         tags={"host": "web-01"})
    print(f"\nRaw data points: {len(raw)}")

    downsampled = ts.downsample("cpu_usage", "cpu_percent", bucket_seconds=300, agg="mean")
    print(f"Downsampled to 5-minute buckets: {len(downsampled)} buckets")
    if downsampled:
        print(f"First bucket avg CPU: {downsampled[0][1]:.1f}%")

    print("\nDemo complete.")


if __name__ == "__main__":
    demo()
