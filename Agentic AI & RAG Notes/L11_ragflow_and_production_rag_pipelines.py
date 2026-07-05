# ============================================================
# L11: RAGFlow and Production, End-to-End RAG Pipeline Tooling
# ============================================================
# WHAT: RAGFlow's deep-document-understanding-first approach to RAG (a
#       full, opinionated platform rather than a composable library),
#       and the production concerns every RAG system needs regardless of
#       which framework built it — chunking strategy selection at scale,
#       incremental re-indexing, and multi-tenant document isolation.
# WHY: L05-L10 covered composable LIBRARIES/frameworks (LangChain,
#      LlamaIndex, Haystack, DSPy) you assemble into a pipeline yourself.
#      RAGFlow represents a different point on the build-vs-buy spectrum
#      — a more complete, opinionated PLATFORM — and this lesson closes
#      Phase 2 by covering what actually running any of these in
#      production requires beyond the initial working pipeline.
# LEVEL: Advanced (Phase 2 of 7 — final RAG lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
RAGFlow is an open-source RAG platform built around DEEP DOCUMENT
UNDERSTANDING as its core differentiator — rather than treating chunking
as a generic text-splitting problem (L04's fixed-size/recursive
strategies), RAGFlow uses specialized parsing/chunking TEMPLATES tuned
per document TYPE (a legal contract, a academic paper, a general
webpage, a table-heavy report each get different, purpose-built chunking
logic), directly extending the layout-awareness theme from L09's
Unstructured.io coverage into a full retrieval PLATFORM rather than just
a parsing library. It ships with its own UI for document management,
built-in citation tracking (linking generated answer text back to the
EXACT source chunk/document it came from), and a more turnkey deployment
model than assembling LangChain/LlamaIndex components yourself.

The BUILD VS BUY spectrum this represents: LangChain/LlamaIndex/Haystack
give you MAXIMUM composability (swap any component) at the cost of
assembling and maintaining the pipeline yourself. RAGFlow (and similar
platforms) give you a more COMPLETE, opinionated system faster, at the
cost of less granular control over individual pipeline stages — a real
tradeoff, not a strictly-better-or-worse choice, that depends on whether
your use case's chunking/retrieval needs fit RAGFlow's built-in templates
or require custom logic a composable library would make easier to build.

PRODUCTION RAG CONCERNS that apply regardless of framework choice:
INCREMENTAL RE-INDEXING (when a source document changes, re-embedding
and re-indexing ONLY that document's chunks, not the entire corpus —
directly connects to this repo's Data Engineering Notes L02's
incremental-loading concepts, applied to a vector index instead of a
data warehouse table). MULTI-TENANT ISOLATION (when serving multiple
customers/organizations from one RAG system, ensuring Customer A's
documents are NEVER retrievable in Customer B's query results — typically
enforced via metadata filtering, L03, scoped to a tenant ID, with the
filter applied at the DATABASE level, not just trusted application logic,
so a bug in application code can't leak cross-tenant data). CITATION
TRACKING (surfacing exactly which source chunk/document a generated
answer's claims came from, both for user trust and for the faithfulness
evaluation covered in L04).

PRODUCTION USE CASE:
A multi-tenant SaaS documentation-search product enforces tenant
isolation at the vector database's metadata-filter level (every query
includes a mandatory `tenant_id` filter applied by the retrieval layer
itself, not left to be remembered by every calling code path) — a design
choice that makes a cross-tenant data leak require a bug in the shared
retrieval layer itself (audited once, centrally) rather than a bug in
any of dozens of individual query call sites.

COMMON MISTAKES:
- Choosing a fully composable framework (LangChain/LlamaIndex) for a
  use case that fits a turnkey platform's (RAGFlow's) built-in templates
  well, and then spending significant engineering time re-building
  features the platform would have provided out of the box.
- Re-embedding and re-indexing an ENTIRE corpus every time a single
  document changes, instead of implementing incremental re-indexing —
  this becomes a real scaling problem as corpus size grows, exactly
  analogous to the full-load-vs-incremental-load tradeoff in Data
  Engineering Notes L02.
- Enforcing multi-tenant isolation only in APPLICATION CODE (e.g. "we
  always remember to add the tenant filter") rather than at the
  retrieval layer/database level — this is a single missed filter away
  from a serious cross-tenant data leak, and application-code-level
  enforcement doesn't get audited as a single, reviewable control point.
"""

import textwrap


# ------------------------------------------------------------------
# 1. RAGFlow's document-type-aware chunking templates
# ------------------------------------------------------------------
RAGFLOW_CONCEPT_NOTE = textwrap.dedent("""\
    RAGFlow assigns each document a PARSING TEMPLATE based on its
    detected type:
      - "General": standard layout-aware chunking (similar in spirit to
        L09's Unstructured.io approach)
      - "Q&A": optimized for FAQ-style documents, chunking around
        question/answer pairs rather than generic paragraphs
      - "Table": specialized extraction preserving row/column structure
        (directly building on L09's table-extraction concept)
      - "Paper": tuned for academic paper structure (abstract, sections,
        references treated distinctly rather than uniformly)

    This is the platform's core bet: purpose-built chunking per document
    TYPE outperforms one generic chunking strategy applied uniformly —
    directly extending L09's document-processing lesson into a
    full retrieval system with citation tracking and a management UI
    built around that principle.
""")

CITATION_TRACKING_NOTE = textwrap.dedent("""\
    RAGFlow (and well-built production RAG systems generally) return
    generated answers WITH explicit citations back to source chunks:

        {
          "answer": "Refunds are processed within 5 business days [1].",
          "citations": [
            {"id": 1, "document": "refund_policy.pdf", "chunk_id": "c42",
             "text": "Refunds are processed within 5 business days of..."}
          ]
        }

    This serves TWO purposes: user trust (a user can verify the claim
    against the actual source) and automated faithfulness evaluation
    (L04) — checking whether the cited chunk ACTUALLY supports the
    claim made is a far more precise faithfulness check than trying to
    verify an uncited answer against the entire retrieved context blob.
""")

# ------------------------------------------------------------------
# 2. Incremental re-indexing
# ------------------------------------------------------------------
def incremental_reindex(changed_document_id: str, vector_index: dict[str, list],
                          document_chunks: dict[str, list[str]]):
    """
    Only re-embeds/re-indexes chunks belonging to the CHANGED document —
    directly analogous to Data Engineering Notes L02's incremental-load
    pattern, applied to a vector index. A full-corpus re-embed on every
    single document update doesn't scale past a small corpus.
    """
    # Remove stale chunks for this document.
    stale_chunk_ids = [cid for cid in vector_index if cid.startswith(f"{changed_document_id}_")]
    for cid in stale_chunk_ids:
        del vector_index[cid]

    # Re-chunk and re-embed ONLY this document's current content.
    for i, chunk_text in enumerate(document_chunks[changed_document_id]):
        chunk_id = f"{changed_document_id}_{i}"
        vector_index[chunk_id] = embed(chunk_text)   # placeholder for a real embedding call

    print(f"Re-indexed {len(document_chunks[changed_document_id])} chunks "
          f"for document '{changed_document_id}' — {len(stale_chunk_ids)} "
          f"stale chunks removed, rest of corpus untouched.")


def embed(text: str) -> list[float]:
    return [len(text) % 10 / 10.0] * 4  # a placeholder stand-in for a real embedding call


# ------------------------------------------------------------------
# 3. Multi-tenant isolation — enforced at the retrieval layer, not application code
# ------------------------------------------------------------------
class TenantScopedRetriever:
    """
    The tenant filter is baked into the RETRIEVER ITSELF — every query
    MUST specify a tenant_id, and the filter is applied here, centrally,
    rather than trusting every individual calling code path across a
    codebase to remember to add it. A single, audited enforcement point.
    """

    def __init__(self, vector_index: dict[str, dict]):
        self.vector_index = vector_index  # chunk_id -> {"embedding": [...], "tenant_id": "...", "text": "..."}

    def retrieve(self, query_embedding: list[float], tenant_id: str, top_k: int) -> list[str]:
        # The tenant filter is NOT optional and NOT left to the caller —
        # it's structurally required by this method's signature and
        # applied unconditionally inside it.
        tenant_chunks = {
            cid: data for cid, data in self.vector_index.items()
            if data["tenant_id"] == tenant_id
        }
        # (a real implementation would use the vector DB's native
        # metadata filtering from L03, not a Python-level filter)
        return list(tenant_chunks.keys())[:top_k]


# ------------------------------------------------------------------
# 4. Build vs buy — a decision framework
# ------------------------------------------------------------------
BUILD_VS_BUY_FACTORS = [
    "Does your document corpus fit one of RAGFlow's (or a similar "
    "platform's) built-in parsing templates well, or does it need "
    "genuinely custom chunking/retrieval logic a composable framework "
    "makes easier to build?",
    "Do you need to swap individual pipeline stages (a specific "
    "reranker, a specific vector DB, a specific LLM provider) "
    "independently — composable frameworks (L05-L08) make this far "
    "easier than an opinionated platform.",
    "How much engineering time can you realistically invest in building "
    "and MAINTAINING citation tracking, a document management UI, and "
    "multi-tenant isolation yourself, versus getting them out of the box?",
]


if __name__ == "__main__":
    print(RAGFLOW_CONCEPT_NOTE)
    print(CITATION_TRACKING_NOTE)

    print("--- Incremental re-indexing ---")
    index = {"doc1_0": [0.1] * 4, "doc1_1": [0.2] * 4, "doc2_0": [0.3] * 4}
    chunks = {"doc1": ["updated chunk text one", "updated chunk text two, now longer"]}
    incremental_reindex("doc1", index, chunks)
    print("Index after re-index:", list(index.keys()))

    print("\n--- Multi-tenant isolation ---")
    tenant_index = {
        "c1": {"embedding": [0.1] * 4, "tenant_id": "acme_corp", "text": "Acme's refund policy"},
        "c2": {"embedding": [0.1] * 4, "tenant_id": "globex_inc", "text": "Globex's refund policy"},
    }
    retriever = TenantScopedRetriever(tenant_index)
    print("Acme's results:", retriever.retrieve([0.1] * 4, tenant_id="acme_corp", top_k=5))
    print("Globex's results:", retriever.retrieve([0.1] * 4, tenant_id="globex_inc", top_k=5))

    print("\nBuild vs buy factors:")
    for factor in BUILD_VS_BUY_FACTORS:
        print(f"  - {factor}")

"""
PRODUCTION CONTEXT EXAMPLE:
A B2B SaaS company evaluates RAGFlow against a custom LangChain-based
build for their customer-facing documentation search feature — RAGFlow's
built-in citation tracking and Q&A-optimized chunking template fit their
FAQ-heavy content well, and the multi-tenant isolation requirement
(critical, given the compliance implications of any cross-customer data
leak) is satisfied by RAGFlow's tenant-scoped document collections out of
the box, saving meaningful engineering time versus building and
independently auditing that isolation guarantee themselves in a custom
LangChain pipeline.
"""
