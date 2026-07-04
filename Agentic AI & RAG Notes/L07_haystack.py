# ============================================================
# L07: Haystack — Pipelines, Components, Document Stores
# ============================================================
# WHAT: Haystack's explicit PIPELINE/COMPONENT architecture — a graph of
#       named, independently swappable components (retrievers, readers,
#       generators) wired together into a DAG, plus its document store
#       abstraction.
# WHY: Haystack takes a more EXPLICIT, production-oriented approach to
#      pipeline definition than LangChain's LCEL chaining or LlamaIndex's
#      query-engine abstraction — its component graph is directly
#      inspectable/serializable, which matters for teams wanting a very
#      clear, debuggable pipeline structure rather than a more implicit
#      composition style.
# LEVEL: Intermediate (Phase 2 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
A Haystack PIPELINE is an explicit, named DAG of COMPONENTS — each
component has declared INPUTS and OUTPUTS, and you wire them together by
explicitly connecting named ports (`pipeline.connect("retriever.documents",
"generator.documents")`), rather than an implicit `|` chaining syntax
(LangChain's LCEL) or a higher-level query-engine call (LlamaIndex).
This explicitness is deliberate: a Haystack pipeline's structure is
directly serializable to YAML and fully inspectable, which matters for
teams who want the pipeline's exact data flow to be reviewable/auditable
as a first-class artifact, not just readable from chained Python code.

COMPONENTS are the building blocks — RETRIEVERS (BM25Retriever for
keyword search, EmbeddingRetriever for vector search, and combinations
for hybrid search directly analogous to L03's hybrid search concept),
READERS (extractive QA models that pull an exact answer SPAN from
retrieved text, distinct from GENERATIVE answering — useful when you
need a precise extracted quote rather than a paraphrased LLM-generated
answer), and GENERATORS (LLM-based answer generation, the RAG pattern
from L04). Haystack's component model is explicitly designed to be
EXTENSIBLE — writing a custom component with declared inputs/outputs is
a first-class, well-documented pattern.

A DOCUMENT STORE is Haystack's storage abstraction (backed by
Elasticsearch, OpenSearch, Weaviate, Qdrant, or an in-memory store for
testing) — providing both keyword AND vector search depending on the
backend, which is what enables Haystack's retriever components to
implement hybrid search naturally against a single underlying store.

PRODUCTION USE CASE:
A compliance-sensitive document search tool uses an EXTRACTIVE reader
component instead of (or alongside) a generative answer — for
regulatory reasons, the tool needs to show an EXACT quoted span from a
source document as the "answer," not an LLM's paraphrase, which a
generative-only RAG pipeline (L04's default pattern) doesn't naturally
provide without extra constraint.

COMMON MISTAKES:
- Assuming Haystack's explicit pipeline graph is strictly MORE complex
  than LCEL/query-engine alternatives without value — the explicitness
  is a deliberate tradeoff favoring inspectability/auditability, which
  matters more for some production contexts (regulated industries,
  large teams needing to review pipeline changes) than others.
- Using a purely generative pipeline when an extractive reader would
  better serve the actual requirement (exact quotes needed, not
  paraphrase) — conflating "RAG" with "must be generative" misses
  Haystack's explicit support for extractive QA as a distinct pattern.
- Choosing a document store backend without considering whether hybrid
  (keyword + vector) search is actually needed — an in-memory or
  vector-only store is simpler to operate but loses the keyword-matching
  half of hybrid search (L03) that some use cases genuinely need.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Pipeline and component wiring
# ------------------------------------------------------------------
HAYSTACK_PIPELINE_EXAMPLE = textwrap.dedent("""\
    from haystack import Pipeline
    from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever
    from haystack.components.embedders import OpenAITextEmbedder
    from haystack.components.builders import PromptBuilder
    from haystack.components.generators import OpenAIGenerator
    from haystack.document_stores.in_memory import InMemoryDocumentStore

    document_store = InMemoryDocumentStore()

    pipeline = Pipeline()
    pipeline.add_component("embedder", OpenAITextEmbedder())
    pipeline.add_component("retriever", InMemoryEmbeddingRetriever(document_store))
    pipeline.add_component("prompt_builder", PromptBuilder(
        template="Answer using this context:\\n{{ documents }}\\n\\nQuestion: {{ question }}"
    ))
    pipeline.add_component("generator", OpenAIGenerator(model="gpt-4o"))

    # EXPLICIT wiring — each connection names the exact output port of
    # one component and the exact input port of the next. This graph is
    # fully inspectable/serializable, unlike an implicit chain.
    pipeline.connect("embedder.embedding", "retriever.query_embedding")
    pipeline.connect("retriever.documents", "prompt_builder.documents")
    pipeline.connect("prompt_builder.prompt", "generator.prompt")

    result = pipeline.run({
        "embedder": {"text": "How do I request a refund?"},
        "prompt_builder": {"question": "How do I request a refund?"},
    })
""")

# ------------------------------------------------------------------
# 2. Retrievers — keyword, vector, and hybrid
# ------------------------------------------------------------------
RETRIEVER_TYPES = {
    "BM25Retriever": "Pure keyword/BM25 search — the exact-match half of "
        "hybrid search (L03), no embedding required.",
    "EmbeddingRetriever / InMemoryEmbeddingRetriever": "Vector similarity "
        "search — the semantic half.",
    "Hybrid (both, combined)": "Running BOTH retriever types and fusing "
        "results (e.g. via Reciprocal Rank Fusion, as shown in L03) — "
        "Haystack pipelines make this an explicit, composable pattern: "
        "two retriever components feeding into a joiner component.",
}

HYBRID_RETRIEVAL_PIPELINE_SKETCH = textwrap.dedent("""\
    from haystack.components.joiners import DocumentJoiner

    pipeline.add_component("bm25_retriever", InMemoryBM25Retriever(document_store))
    pipeline.add_component("embedding_retriever", InMemoryEmbeddingRetriever(document_store))
    pipeline.add_component("joiner", DocumentJoiner(join_mode="reciprocal_rank_fusion"))

    pipeline.connect("bm25_retriever.documents", "joiner.documents")
    pipeline.connect("embedding_retriever.documents", "joiner.documents")
    # Both retrievers run on the SAME query; the joiner fuses their
    # ranked lists — the exact RRF concept from L03, expressed as an
    # explicit Haystack pipeline component rather than custom code.
""")

# ------------------------------------------------------------------
# 3. Extractive readers — exact spans instead of generated paraphrase
# ------------------------------------------------------------------
EXTRACTIVE_READER_EXAMPLE = textwrap.dedent("""\
    from haystack.components.readers import ExtractiveReader

    reader = ExtractiveReader(model="deepset/roberta-base-squad2")
    result = reader.run(
        query="How many days does a refund take?",
        documents=retrieved_documents,
    )
    # Returns an EXACT SPAN extracted from the source text (e.g.
    # "5 business days"), with a confidence score and the exact source
    # document/offset it came from — no LLM paraphrase involved. This
    # matters when the use case requires provably-exact quotes (legal,
    # compliance, medical) rather than a generative model's rewording,
    # which could subtly alter meaning even when well-intentioned.
""")


if __name__ == "__main__":
    print(HAYSTACK_PIPELINE_EXAMPLE)
    print("=== Retriever types ===")
    for retriever, note in RETRIEVER_TYPES.items():
        print(f"{retriever}: {note}\n")
    print(HYBRID_RETRIEVAL_PIPELINE_SKETCH)
    print(EXTRACTIVE_READER_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A pharmaceutical company's drug-label search tool uses Haystack's
ExtractiveReader instead of a generative pipeline specifically because
regulatory requirements demand answers be EXACT quotes traceable to a
specific approved document and section — a generative LLM's paraphrase,
even if factually equivalent, would not satisfy the compliance
requirement for verbatim sourcing, a distinction the extractive-vs-
generative choice in Haystack's component model makes explicit and
easy to enforce architecturally, rather than trying to constrain a
generative model's output after the fact.
"""
