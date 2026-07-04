# ============================================================
# L06: LlamaIndex Deep Dive — Index Types, Query Engines, Response Synthesis
# ============================================================
# WHAT: LlamaIndex's core abstractions — multiple index TYPES (not just
#       a flat vector index), query engines, node parsers, and response
#       synthesis strategies for combining multiple retrieved chunks into
#       one coherent answer.
# WHY: While LangChain (L05) is a general-purpose LLM-application
#      framework that happens to support RAG well, LlamaIndex was built
#      SPECIFICALLY for data indexing/retrieval — it offers index
#      structures and synthesis strategies beyond the simple "embed
#      chunks, retrieve top-k" pattern that matter for more sophisticated
#      retrieval needs.
# LEVEL: Intermediate (Phase 2 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
LlamaIndex offers several INDEX TYPES beyond the flat vector index used
in L04's basic RAG pattern:
  - VECTOR STORE INDEX: the standard embed-and-retrieve pattern from L04
    — the default choice for most RAG use cases.
  - SUMMARY INDEX: stores document summaries and retrieves by summary
    relevance first, useful when whole-document-level relevance matters
    more than chunk-level granularity.
  - TREE INDEX: builds a HIERARCHICAL summary tree (leaf nodes are
    chunks, parent nodes are summaries of their children, recursively up
    to a root) — querying can traverse the tree top-down, useful for
    very large document sets where you want to narrow from "which broad
    section is relevant" down to "which specific chunk" rather than
    searching every chunk equally.
  - KNOWLEDGE GRAPH INDEX: extracts entities and relationships into a
    graph structure — a lighter-weight, LlamaIndex-native precursor to
    the more specialized GraphRAG approach covered in depth in L10.

A QUERY ENGINE wraps an index with the actual query-time LOGIC: which
retrieval strategy to use, how many results to fetch, and how to
SYNTHESIZE a final response from potentially multiple retrieved nodes.
RESPONSE SYNTHESIS modes matter because naively concatenating many
retrieved chunks into one prompt can exceed context limits or dilute
relevance — LlamaIndex offers several explicit strategies: "refine"
(process chunks ONE AT A TIME, iteratively refining an answer with each
new chunk — handles more chunks than fit in one prompt, at the cost of
multiple sequential LLM calls), "compact" (pack as many chunks as fit
into each refine step, reducing the number of LLM calls versus naive
refine), "tree_summarize" (recursively summarize chunks in a
tournament-style tree, useful for large numbers of chunks needing a
single synthesized answer).

NODE PARSERS are LlamaIndex's term for the chunking step (L04) —
including parsers aware of document STRUCTURE (e.g. a node parser that
respects Markdown headers, keeping a section's heading attached to its
content rather than an arbitrary character-count split).

PRODUCTION USE CASE:
A legal research tool uses a Tree Index over thousands of case documents
— a broad query first narrows to the relevant case-law AREA (contract
law vs tort law, at a summary level), then descends into the specific
cases and passages within that narrowed set, avoiding an expensive flat
search across every chunk of every case document for every query.

COMMON MISTAKES:
- Defaulting to a flat Vector Store Index for every use case without
  considering whether a Summary or Tree Index better matches the actual
  query patterns (e.g. "which of these 500 documents discusses X" is a
  document-level relevance question a Summary Index answers more
  naturally than chunk-level vector search).
- Using the "refine" response synthesis mode by default when "compact"
  would produce the same quality with fewer, cheaper LLM calls — refine's
  one-chunk-at-a-time processing is more expensive than necessary once
  chunks are small enough to batch into "compact" mode's packed prompts.
- Using a naive character-count node parser on structured documents
  (Markdown, HTML) instead of a structure-aware parser — this can split
  a heading from its content, producing chunks that lose important
  context a structure-aware parser would have preserved.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Index types
# ------------------------------------------------------------------
INDEX_TYPE_COMPARISON = {
    "VectorStoreIndex": "Standard embed-and-retrieve (L04's pattern) — "
        "the default for most RAG use cases, chunk-level relevance.",
    "SummaryIndex": "Retrieves by document-level summary relevance first "
        "— better suited when 'which document is relevant' matters more "
        "than 'which specific passage.'",
    "TreeIndex": "Hierarchical summary tree; queries traverse top-down "
        "from broad summaries to specific leaf chunks — scales better "
        "for very large corpora where flat search across every chunk "
        "would be both slow and less precise.",
    "KnowledgeGraphIndex": "Extracts entities/relationships into a graph "
        "— a lighter-weight precursor to the dedicated GraphRAG approach "
        "in L10, useful for relationship-heavy queries a flat vector "
        "search handles poorly.",
}

VECTOR_STORE_INDEX_EXAMPLE = textwrap.dedent("""\
    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

    documents = SimpleDirectoryReader("./docs").load_data()
    index = VectorStoreIndex.from_documents(documents)
    query_engine = index.as_query_engine(similarity_top_k=5)
    response = query_engine.query("How do I request a refund?")
""")

TREE_INDEX_EXAMPLE = textwrap.dedent("""\
    from llama_index.core import TreeIndex

    # Builds a hierarchical summary tree: leaf nodes are document chunks,
    # parent nodes summarize their children, recursively to a root
    # summary. Querying can traverse top-down, narrowing from a broad
    # summary to specific relevant leaves, rather than flat-searching
    # every chunk in a large corpus equally.
    index = TreeIndex.from_documents(documents)
    query_engine = index.as_query_engine()
    response = query_engine.query("Which section of the handbook covers refunds?")
""")

# ------------------------------------------------------------------
# 2. Response synthesis modes
# ------------------------------------------------------------------
SYNTHESIS_MODE_COMPARISON = {
    "refine": "Processes retrieved chunks ONE AT A TIME, refining the "
        "answer incrementally with each — handles more chunks than fit "
        "in one prompt, at the cost of one sequential LLM call PER chunk.",
    "compact": "Packs as MANY chunks as fit into each refine step, "
        "reducing the total number of LLM calls versus plain refine — "
        "usually the better default once individual chunks are small.",
    "tree_summarize": "Recursively summarizes chunks in a tournament-"
        "style tree (pairs/groups summarized, then those summaries "
        "summarized again) — well suited when you need ONE synthesized "
        "answer from a LARGE number of retrieved chunks.",
}

SYNTHESIS_EXAMPLE = textwrap.dedent("""\
    query_engine = index.as_query_engine(
        similarity_top_k=10,
        response_mode="compact",   # pack chunks efficiently instead of
                                     # one-at-a-time refine calls
    )
""")

# ------------------------------------------------------------------
# 3. Node parsers — structure-aware chunking
# ------------------------------------------------------------------
NODE_PARSER_EXAMPLE = textwrap.dedent("""\
    from llama_index.core.node_parser import MarkdownNodeParser

    # A structure-aware parser that respects Markdown headers — keeps a
    # section's heading attached to its content rather than an arbitrary
    # character-count split that might separate "## Refund Policy" from
    # the paragraph explaining it, which a naive splitter (L04/L05's
    # RecursiveCharacterTextSplitter, applied without structure awareness)
    # could do.
    parser = MarkdownNodeParser()
    nodes = parser.get_nodes_from_documents(documents)
""")


if __name__ == "__main__":
    print("=== Index types ===")
    for idx_type, desc in INDEX_TYPE_COMPARISON.items():
        print(f"{idx_type}: {desc}\n")

    print(VECTOR_STORE_INDEX_EXAMPLE)
    print(TREE_INDEX_EXAMPLE)

    print("=== Response synthesis modes ===")
    for mode, desc in SYNTHESIS_MODE_COMPARISON.items():
        print(f"{mode}: {desc}\n")

    print(SYNTHESIS_EXAMPLE)
    print(NODE_PARSER_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A technical documentation search tool switches from a flat VectorStoreIndex
to a TreeIndex once its corpus grows to thousands of pages spanning many
distinct product lines — a query about "API rate limits" now first
narrows to the relevant PRODUCT's summary node before searching within
that product's specific documentation, both improving relevance
(avoiding cross-product noise in results) and reducing query latency
(searching a narrowed subtree instead of the entire flat corpus).
"""
