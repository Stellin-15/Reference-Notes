# ============================================================
# L04: Azure AI Search — Vector, Hybrid Search, Semantic Ranking
# ============================================================
# WHAT: Azure's managed search product (formerly Azure Cognitive
#       Search) as the retrieval half of a RAG pipeline — indexes,
#       vector fields, hybrid (keyword + vector) queries, semantic
#       re-ranking, and indexer/skillset-based ingestion pipelines.
# WHY: Agentic AI & RAG Notes L03 covers vector databases generically
#      (FAISS, Chroma, Pinecone). Azure AI Search is the Azure-native
#      choice, and it does something those don't: it's a FULL search
#      engine (keyword/BM25 + vector + semantic reranking) as one
#      managed service, not just a vector index — the distinction
#      matters for RAG quality, covered below.
# LEVEL: Core (Lesson 4 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Azure AI Search predates the vector-database wave — it started as a
keyword/full-text search engine (BM25-style ranking) and had vector
search added as a field type. This history is actually its strength for
RAG: it does HYBRID search (keyword + vector in one query, with results
merged) and SEMANTIC RANKING (an ML re-ranker on top of the merged
results) natively, where a pure vector database (Agentic AI & RAG Notes
L03) requires you to bolt keyword search on yourself.

WHY HYBRID BEATS PURE VECTOR SEARCH FOR MANY RAG USE CASES
--------------------------------------------------------------
Pure vector (embedding) search is excellent at SEMANTIC similarity
("find documents about a similar concept") but can miss exact matches
on specific terms — account numbers, product SKUs, error codes, legal
citation numbers — because embeddings compress those into vectors that
don't preserve exact-string signal well. Keyword (BM25) search is the
inverse: excellent at exact-term matches, weak at semantic/conceptual
similarity ("find documents about the same idea, phrased differently").
Hybrid search runs BOTH in parallel and merges results (via Reciprocal
Rank Fusion), then SEMANTIC RANKING re-scores the top N merged results
with a cross-encoder-style model for relevance — this three-stage
pipeline (keyword + vector + semantic rerank) is Azure AI Search's core
value proposition over a bare vector store, and it directly improves
RAG answer quality versus vector-only retrieval, especially for
document sets containing structured identifiers alongside prose.

INDEX SCHEMA: fields, vector fields, filterable/facetable
--------------------------------------------------------------
An Azure AI Search INDEX is a schema of fields, each marked with
capabilities: searchable (full-text), filterable (exact-match `$filter`
queries, e.g. `department eq 'Risk'`), facetable (aggregation/counts),
sortable, and — for RAG — a `vector` type field storing embeddings with
a configured similarity metric (cosine is the default/typical choice)
and an ANN algorithm (HNSW is the standard). Metadata fields
(department, document date, access-control tags) sit alongside the
vector field in the SAME document, which is what makes filtered
vector search possible — e.g. "vector-search these embeddings, but only
within documents where department == 'Risk' AND the querying user has
access" — critical for enterprise RAG where document access control
must be enforced at retrieval time, not just at the UI layer.

INDEXERS & SKILLSETS: automated ingestion pipelines
--------------------------------------------------------
Rather than writing custom code to chunk documents, generate
embeddings, and push them into the index, Azure AI Search supports
INDEXERS (scheduled or triggered jobs that pull from a data source —
Blob Storage, SQL, Cosmos DB) combined with SKILLSETS — a pipeline of
built-in or custom "skills" applied per document: OCR (for scanned
PDFs, via the Vision service from L03), text chunking/splitting, and an
embedding-generation skill that calls Azure OpenAI (L02) to produce
vectors — the entire ingest-chunk-embed-index pipeline runs as a
managed Azure service rather than custom application code, though most
production RAG systems still write custom ingestion for full control
over chunking strategy (a decision covered generically in Agentic AI &
RAG Notes L04's RAG fundamentals).

PRODUCTION USE CASE:
A knowledge-search feature over a bank's internal policy documents uses
hybrid search (so both "what's the wire transfer limit" — exact-term —
and "what happens if a customer disputes a charge" — semantic — surface
relevant results) with semantic ranking on the top 50 merged results,
filtered per query by the requesting employee's department access tag
stored as a filterable field on each indexed chunk — retrieval-time
access control, not just an application-layer check after the fact.

COMMON MISTAKES:
- Using pure vector search when the document set contains exact
  identifiers (account numbers, ticket IDs, product codes) that users
  will search for verbatim — hybrid search is the fix, not a bigger
  embedding model.
- Indexing entire documents as single chunks instead of splitting into
  retrieval-sized chunks (typically a few hundred tokens) — oversized
  chunks dilute the embedding's specificity and return less precise
  matches; undersized chunks lose surrounding context. Chunk-size
  tuning is covered generically in Agentic AI & RAG Notes L04.
- Storing access-control metadata OUTSIDE the search index (e.g.
  checking permissions only after retrieval, in application code) —
  this leaks the existence/content of restricted documents through
  retrieval ranking and relevance signals even if the final answer is
  blocked, and it's slower than filtering at query time.
- Not re-running semantic ranking on hybrid results and settling for
  raw RRF-merged order — semantic ranking is what most measurably
  improves top-k relevance for RAG answer quality in practice.
- Choosing document-level chunking granularity that mismatches how
  users actually ask questions (e.g. one chunk per 50-page policy
  document, when questions are about a single clause).
"""

import textwrap


# ------------------------------------------------------------------
# 1. Index schema with a vector field + filterable access-control field
# ------------------------------------------------------------------
INDEX_SCHEMA_EXAMPLE = textwrap.dedent("""\
    from azure.search.documents.indexes.models import (
        SearchIndex, SearchField, SearchFieldDataType, VectorSearch,
        HnswAlgorithmConfiguration, VectorSearchProfile,
    )

    index = SearchIndex(
        name="policy-docs",
        fields=[
            SearchField(name="id", type=SearchFieldDataType.String, key=True),
            SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                vector_search_dimensions=3072,          # text-embedding-3-large
                vector_search_profile_name="default-hnsw",
            ),
            # filterable, NOT searchable -- exact-match access control at query time
            SearchField(name="department", type=SearchFieldDataType.String, filterable=True),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
            profiles=[VectorSearchProfile(name="default-hnsw", algorithm_configuration_name="hnsw-config")],
        ),
    )
""")

# ------------------------------------------------------------------
# 2. Hybrid query: keyword + vector + semantic ranking + access filter
# ------------------------------------------------------------------
HYBRID_QUERY_EXAMPLE = textwrap.dedent("""\
    from azure.search.documents import SearchClient
    from azure.search.documents.models import VectorizedQuery

    query_embedding = embed_query(user_question)   # call Azure OpenAI (L02)

    results = search_client.search(
        search_text=user_question,                  # keyword/BM25 leg
        vector_queries=[VectorizedQuery(
            vector=query_embedding, k_nearest_neighbors=50, fields="content_vector"
        )],                                          # vector leg -- merged via RRF
        query_type="semantic",                        # rerank the merged top results
        semantic_configuration_name="default-semantic",
        filter=f"department eq '{user.department}'",  # retrieval-time access control
        top=5,
    )

    for result in results:
        print(result["content"], result["@search.reranker_score"])
""")

# ------------------------------------------------------------------
# 3. Indexer + skillset: automated ingest-chunk-embed pipeline
# ------------------------------------------------------------------
INDEXER_SKILLSET_EXAMPLE = textwrap.dedent("""\
    # Conceptual skillset pipeline (JSON, simplified):
    # Blob Storage (source docs)
    #   -> OCR skill (scanned PDFs -- calls Vision service, L03)
    #   -> Text Split skill (chunk into ~500-token passages)
    #   -> Azure OpenAI Embedding skill (calls Azure OpenAI, L02)
    #   -> index projection (one search document PER CHUNK, not per source file)
    #
    # The indexer runs on a schedule or is triggered on new blob upload --
    # new policy documents become searchable within minutes with zero
    # custom ingestion code, at the cost of less control over chunking
    # strategy than a hand-rolled pipeline would give.
""")


if __name__ == "__main__":
    print(INDEX_SCHEMA_EXAMPLE)
    print(HYBRID_QUERY_EXAMPLE)
    print(INDEXER_SKILLSET_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A bank's internal "ask HR policy" search feature indexes policy
documents chunked at ~400 tokens with a `department` and `clearance_level`
filterable field per chunk, runs hybrid search + semantic reranking so
"what's the WFH stipend" (exact term) and "can I expense a home office
chair" (semantic, no exact term match) both surface the right clause,
and enforces access control via the search filter itself -- an employee
without Finance clearance never sees Finance-only chunks even ranked
low, because they're excluded from the query, not just hidden in the UI.
"""
