# ============================================================
# L03: Vector Databases — Pinecone, Weaviate, Qdrant, Milvus, Chroma,
#      pgvector, Elasticsearch, Redis, MongoDB Atlas Vector Search
# ============================================================
# WHAT: How vector databases actually index and search embeddings at
#       scale (HNSW/IVF), metadata filtering, hybrid search (combining
#       vector similarity with keyword search), and a practical
#       comparison of the major vector database options.
# WHY: L02 covered WHAT an embedding is; this lesson covers WHERE you
#      store millions/billions of them and how you search them in
#      milliseconds — the actual infrastructure layer every RAG system
#      (L04 onward) depends on.
# LEVEL: Foundation (Phase 1 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
A brute-force nearest-neighbor search (compare a query vector against
EVERY stored vector, exactly) is O(n) per query — fine for thousands of
vectors, infeasible for a corpus of tens of millions. Vector databases
solve this with APPROXIMATE nearest neighbor (ANN) search — trading a
small amount of recall (occasionally missing the true nearest neighbor)
for orders-of-magnitude faster search.

HNSW (Hierarchical Navigable Small World) is the dominant ANN algorithm
used by most modern vector databases: it builds a multi-layer graph
where each vector is a node, connected to its approximate nearest
neighbors, with SPARSER layers on top enabling fast coarse navigation and
DENSER layers at the bottom for fine-grained accuracy — search starts at
the top layer and greedily descends, achieving logarithmic-ish search
time with high recall. IVF (Inverted File Index) instead CLUSTERS vectors
into buckets (via k-means-like partitioning) and only searches the
buckets nearest the query — cheaper to build than HNSW but generally
lower recall at the same speed; often combined with product quantization
(IVF-PQ) to also compress vector storage.

METADATA FILTERING lets you combine vector similarity search with
traditional structured filters — "find the 10 most similar chunks, but
ONLY from documents tagged `department: legal` AND `date > 2025-01-01`."
Different vector databases implement this with meaningfully different
performance characteristics (pre-filtering vs post-filtering the ANN
search affects both speed and whether you might get FEWER than the
requested top-k results if filtering happens after the ANN search
already narrowed the candidate set).

HYBRID SEARCH combines VECTOR similarity (semantic meaning) with
traditional KEYWORD/BM25 search (exact term matching) — because pure
semantic search can miss cases where an EXACT term match matters (a
specific product SKU, an exact legal citation, a person's name) that a
purely semantic embedding might not weight highly enough. Results from
both search types are combined (commonly via Reciprocal Rank Fusion)
into one ranked list.

PRODUCTION USE CASE:
A legal document search system uses hybrid search because pure semantic
search sometimes fails to prioritize an EXACT case citation match (e.g.
"Smith v. Jones, 2019") that a lawyer explicitly typed — the keyword/BM25
component ensures exact-match relevance isn't lost to semantic
similarity alone, while the vector component still finds semantically
relevant documents that don't share exact wording.

COMMON MISTAKES:
- Applying metadata filters AFTER an ANN search has already narrowed to
  top-k candidates (post-filtering) when you need STRICT top-k results
  matching the filter — if very few of the ANN search's candidates match
  the filter, you can get far fewer than k results back; pre-filtering
  (searching only within the filtered subset) avoids this at some
  performance cost, and different vector databases default to different
  behavior here.
- Choosing a vector database based purely on benchmark throughput
  numbers without considering your actual operational needs — a
  managed, serverless option (Pinecone) trades some cost/control for
  zero infrastructure management, while a self-hosted option (Qdrant,
  Milvus, Weaviate) trades operational overhead for cost control and
  data locality; the "fastest" option isn't automatically the right one.
- Using pure vector search when the use case has an obvious exact-match
  component (product codes, names, IDs) — hybrid search exists
  specifically because semantic-only search underperforms on this class
  of query.
"""

import math


# ------------------------------------------------------------------
# 1. Brute-force vs approximate search — the scaling problem
# ------------------------------------------------------------------
def brute_force_search(query: list[float], vectors: dict[str, list[float]], top_k: int) -> list[tuple[str, float]]:
    """O(n) exact search — fine for small corpora, the baseline every
    ANN algorithm is approximating (and trading some recall to beat)."""
    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a, norm_b = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    scored = [(doc_id, cosine_sim(query, vec)) for doc_id, vec in vectors.items()]
    return sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]


# ------------------------------------------------------------------
# 2. A simplified illustration of IVF-style clustering
# ------------------------------------------------------------------
def simplified_ivf_search(query: list[float], clusters: dict[str, dict[str, list[float]]],
                            cluster_centroids: dict[str, list[float]], nprobe: int, top_k: int):
    """
    IVF's core idea: only search the `nprobe` clusters whose CENTROID is
    closest to the query, instead of every vector in the entire corpus —
    a real, tunable recall/speed tradeoff via `nprobe` (more clusters
    probed = higher recall, slower search).
    """
    def cosine_sim(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a, norm_b = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    centroid_scores = [(cid, cosine_sim(query, centroid)) for cid, centroid in cluster_centroids.items()]
    nearest_clusters = [cid for cid, _ in sorted(centroid_scores, key=lambda x: x[1], reverse=True)[:nprobe]]

    candidates = {}
    for cid in nearest_clusters:
        candidates.update(clusters[cid])   # only search WITHIN probed clusters

    return brute_force_search(query, candidates, top_k)


# ------------------------------------------------------------------
# 3. Real vector database usage — Pinecone, Weaviate, Qdrant, pgvector
# ------------------------------------------------------------------
import textwrap

PINECONE_EXAMPLE = textwrap.dedent("""\
    from pinecone import Pinecone
    pc = Pinecone(api_key="...")
    index = pc.Index("documents")

    index.upsert(vectors=[
        {"id": "chunk_1", "values": [0.01, 0.02, ...], "metadata": {"department": "legal", "date": "2025-06-01"}},
    ])

    # Metadata filter combined with vector search — Pinecone applies
    # this as a PRE-filter, searching only within matching vectors.
    results = index.query(
        vector=[0.01, 0.02, ...],
        filter={"department": {"$eq": "legal"}, "date": {"$gte": "2025-01-01"}},
        top_k=10,
    )
    # Pinecone is fully MANAGED/serverless — no infrastructure to run
    # yourself, billed by usage.
""")

QDRANT_EXAMPLE = textwrap.dedent("""\
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = QdrantClient(url="http://localhost:6333")   # self-hosted OR Qdrant Cloud
    results = client.search(
        collection_name="documents",
        query_vector=[0.01, 0.02, ...],
        query_filter=Filter(must=[FieldCondition(key="department", match=MatchValue(value="legal"))]),
        limit=10,
    )
""")

PGVECTOR_EXAMPLE = textwrap.dedent("""\
    -- pgvector: adds a vector TYPE and ANN indexing directly to
    -- PostgreSQL — the choice when you want vector search WITHOUT a
    -- separate dedicated database, reusing existing Postgres
    -- infrastructure/operational knowledge.
    CREATE EXTENSION vector;
    CREATE TABLE documents (id bigserial, embedding vector(1536), department text);
    CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

    SELECT id, embedding <=> '[0.01, 0.02, ...]' AS distance
    FROM documents
    WHERE department = 'legal'    -- a NORMAL SQL WHERE clause, since
                                    -- metadata lives as regular columns
    ORDER BY distance
    LIMIT 10;
""")

# ------------------------------------------------------------------
# 4. Hybrid search — combining vector and keyword search
# ------------------------------------------------------------------
def reciprocal_rank_fusion(vector_results: list[str], keyword_results: list[str], k: int = 60) -> list[str]:
    """
    RRF combines two RANKED LISTS (from different search methods) into
    one, without needing the two methods' raw scores to be on comparable
    scales — a document's score is 1/(k + its rank) SUMMED across every
    list it appears in, rewarding documents that rank well in EITHER
    (or ideally both) search methods.
    """
    scores: dict[str, float] = {}
    for rank, doc_id in enumerate(vector_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    for rank, doc_id in enumerate(keyword_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


# ------------------------------------------------------------------
# 5. Vector database comparison
# ------------------------------------------------------------------
VECTOR_DB_COMPARISON = {
    "Pinecone": "Fully managed/serverless, zero infrastructure to run — "
        "the fastest on-ramp, at ongoing usage-based cost.",
    "Weaviate": "Open-source, self-hostable or managed cloud option, "
        "built-in hybrid search and a GraphQL-style query API, native "
        "modules for common embedding providers.",
    "Qdrant": "Open-source, self-hostable or managed cloud, known for "
        "strong filtering performance and a straightforward REST/gRPC API.",
    "Milvus": "Open-source, built specifically for very large-scale "
        "deployments (billions of vectors), more operationally complex "
        "to self-host than Qdrant/Weaviate at smaller scale.",
    "Chroma": "Lightweight, open-source, extremely easy local/embedded "
        "setup — a common default for prototyping and smaller applications.",
    "pgvector": "An extension to PostgreSQL — the choice when you want "
        "vector search without a SEPARATE database, reusing existing "
        "Postgres operational knowledge/infrastructure.",
    "Elasticsearch": "A search engine with vector search added on top of "
        "its mature keyword/BM25 search — a natural hybrid-search choice "
        "if you already run Elasticsearch for text search.",
    "Redis": "Adds vector search as a module on top of its in-memory "
        "data structure store — attractive when you already use Redis "
        "and want low-latency vector search without a new system.",
    "MongoDB Atlas Vector Search": "Vector search built into MongoDB "
        "Atlas — the natural choice when your application data already "
        "lives in MongoDB and you want vector search alongside it.",
}


if __name__ == "__main__":
    vectors = {
        "doc1": [1.0, 0.0, 0.0],
        "doc2": [0.9, 0.1, 0.0],
        "doc3": [0.0, 1.0, 0.0],
    }
    query = [1.0, 0.0, 0.0]
    print("Brute-force top-2:", brute_force_search(query, vectors, top_k=2))

    print("\n=== Vector DB examples ===")
    print(PINECONE_EXAMPLE)
    print(QDRANT_EXAMPLE)
    print(PGVECTOR_EXAMPLE)

    print("=== Hybrid search (RRF) ===")
    vector_ranked = ["doc_a", "doc_b", "doc_c"]
    keyword_ranked = ["doc_c", "doc_a", "doc_d"]
    print("Fused ranking:", reciprocal_rank_fusion(vector_ranked, keyword_ranked))

    print("\n=== Vector DB comparison ===")
    for db, note in VECTOR_DB_COMPARISON.items():
        print(f"{db}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An enterprise search product for internal documentation uses Weaviate's
built-in hybrid search: a query for "Q3 revenue projection spreadsheet"
combines vector similarity (catching documents about "third quarter
financial forecasts" that don't share exact wording) with BM25 keyword
matching (ensuring documents with the EXACT phrase "Q3 revenue
projection" rank highly even if their surrounding context is less
semantically rich) — pure vector search alone, tested during
development, was measurably worse on this exact-term-heavy query
pattern than the hybrid approach.
"""
