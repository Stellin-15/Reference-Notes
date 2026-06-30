# ============================================================
# L06: LlamaIndex — Document Q&A and Advanced RAG
# ============================================================
# WHAT: LlamaIndex is a data framework for connecting custom
#       data sources to LLMs. It provides 100+ data loaders,
#       multiple index types, query engines, and evaluation
#       tools purpose-built for retrieval-augmented generation.
# WHY:  LLMs have a knowledge cutoff and no access to private
#       data. LlamaIndex bridges that gap: ingest any docs,
#       index them efficiently, and let the LLM answer questions
#       grounded in your actual data — not hallucinations.
# LEVEL: Advanced / Architect
# ============================================================
"""
CONCEPT OVERVIEW:
    LlamaIndex pipeline has three stages:
      1. LOADING  — read raw data into Document objects
      2. INDEXING — chunk into Nodes, embed, store in vector DB
      3. QUERYING — retrieve relevant Nodes, synthesize answer

    Core objects:
      - Document: raw text + metadata dict (filename, author, date)
      - Node: chunk of a Document, carries parent reference and
              RelationshipInfo (PREVIOUS, NEXT, PARENT, CHILD, SOURCE)
      - Index: data structure over Nodes (Vector, Summary, Tree, Keyword)
      - QueryEngine: retrieves + synthesizes in one .query() call
      - Retriever: retrieval-only (returns Nodes, not final answer)

    vs LangChain:
      LlamaIndex  — document-heavy RAG, multiple index types,
                    sub-question decomposition, built-in eval
      LangChain   — general agents, diverse tool ecosystems,
                    richer chain composition primitives

PRODUCTION USE CASE:
    500-PDF internal knowledge base for a legal firm.
    Lawyers ask natural-language questions across contracts.
    Pipeline: SimpleDirectoryReader -> VectorStoreIndex (Pinecone
    backend) -> CohereRerank (top 5 of 20) ->
    SubQuestionQueryEngine -> FaithfulnessEvaluator in CI.
    Faithfulness score < 0.8 triggers Slack alert before deploy.

COMMON MISTAKES:
    1. Not persisting the index — re-embedding 500 PDFs on every
       restart costs money and takes minutes. Always persist().
    2. Using default chunk_size=1024 blindly. For dense legal
       text try 512 with chunk_overlap=50.
    3. Ignoring source_nodes in the response — always log which
       chunks were used; critical for debugging wrong answers.
    4. Skipping reranking — top-k by cosine alone misses semantic
       nuance. Add CohereRerank or cross-encoder for 20->5.
    5. Using compact mode for very long documents — use
       tree_summarize instead to avoid context overflow.
"""

# ── Imports ──────────────────────────────────────────────────
# pip install llama-index llama-index-vector-stores-chroma
# pip install llama-index-postprocessor-cohere-rerank
# pip install llama-index-embeddings-openai chromadb cohere

from llama_index.core import (
    Document,
    VectorStoreIndex,
    SummaryIndex,
    TreeIndex,
    KeywordTableIndex,
    SimpleDirectoryReader,
    StorageContext,
    load_index_from_storage,
    Settings,
)
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.query_engine import SubQuestionQueryEngine, RouterQueryEngine
from llama_index.core.tools import QueryEngineTool, ToolMetadata
from llama_index.core.selectors import LLMSingleSelector, EmbeddingSingleSelector
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.evaluation import (
    FaithfulnessEvaluator,
    RelevancyEvaluator,
    CorrectnessEvaluator,
)
from llama_index.core.response_synthesizers import ResponseMode

# Reranker — requires: pip install llama-index-postprocessor-cohere-rerank
from llama_index.postprocessor.cohere_rerank import CohereRerank

# Vector store backend — requires: pip install llama-index-vector-stores-chroma
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb

from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as LlamaOpenAI

import os
import json

# ── Global LlamaIndex settings ────────────────────────────────
# Settings replaces the old ServiceContext in LlamaIndex 0.10+
Settings.llm = LlamaOpenAI(model="gpt-4o-mini", temperature=0.1)
Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-small")
Settings.chunk_size = 512          # tokens per Node chunk
Settings.chunk_overlap = 50        # overlap prevents cutting context at boundaries


# ═══════════════════════════════════════════════════════════════
# 1. DOCUMENTS AND NODES
# ═══════════════════════════════════════════════════════════════

def demo_documents_and_nodes():
    """Illustrate Document vs Node and their metadata/relationships."""

    # Document: raw unit of data with arbitrary metadata
    doc = Document(
        text="LlamaIndex connects LLMs to external data efficiently.",
        metadata={
            "filename": "intro.txt",
            "author": "Jerry Liu",
            "date": "2024-01-15",
            "category": "framework",
        },
        # excluded_embed_metadata_keys: these fields won't be embedded
        # (avoids polluting vector space with noise like timestamps)
        excluded_embed_metadata_keys=["date"],
        excluded_llm_metadata_keys=["author"],  # won't appear in LLM context
    )
    print(f"Document ID : {doc.doc_id}")
    print(f"Metadata    : {doc.metadata}")

    # Node: a chunk of a Document, with parent-child relationships
    # In practice, the splitter creates these automatically —
    # manual creation is shown here for understanding.
    node = TextNode(
        text="LlamaIndex connects LLMs to external data.",
        metadata={"source": "intro.txt", "chunk_index": 0},
    )
    # RelationshipInfo links nodes back to their source document
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(
        node_id=doc.doc_id,
        metadata={"filename": "intro.txt"},
    )
    print(f"Node text   : {node.text[:50]}...")
    print(f"Node source : {node.relationships[NodeRelationship.SOURCE].node_id}")

    return doc


# ═══════════════════════════════════════════════════════════════
# 2. LOADING DATA — SimpleDirectoryReader + LlamaHub
# ═══════════════════════════════════════════════════════════════

def load_documents_from_directory(docs_path: str = "./docs") -> list:
    """
    SimpleDirectoryReader auto-detects PDF, TXT, DOCX, etc.
    LlamaHub extends this to Notion, Confluence, GitHub, GDrive.
    """
    # recursive=True walks subdirectories
    # required_exts filters to only PDF and TXT files
    reader = SimpleDirectoryReader(
        input_dir=docs_path,
        required_exts=[".pdf", ".txt"],
        recursive=True,
        # filename_as_id=True ensures doc_id == filename
        # (useful for incremental refresh — only re-embed changed files)
        filename_as_id=True,
    )
    docs = reader.load_data()
    print(f"Loaded {len(docs)} documents from {docs_path}")
    return docs

    # ── LlamaHub connectors (commented — need credentials) ──
    # from llama_index.readers.notion import NotionPageReader
    # from llama_index.readers.confluence import ConfluenceReader
    # from llama_index.readers.github import GithubRepositoryReader
    #
    # notion_reader = NotionPageReader(integration_token=os.environ["NOTION_TOKEN"])
    # notion_docs = notion_reader.load_data(page_ids=["<page-id>"])
    #
    # confluence_reader = ConfluenceReader(base_url="https://company.atlassian.net")
    # confluence_docs = confluence_reader.load_data(space_key="ENG")


# ═══════════════════════════════════════════════════════════════
# 3. INDEX TYPES
# ═══════════════════════════════════════════════════════════════

def demo_index_types(docs: list):
    """
    Four main index types — choose based on your query pattern.
    """

    # VectorStoreIndex: default and most common.
    # Stores Node embeddings; retrieves by cosine similarity.
    # Best for: specific factual Q&A over large document sets.
    vector_index = VectorStoreIndex.from_documents(
        docs,
        show_progress=True,  # prints progress bar during embedding
    )
    print("VectorStoreIndex built.")

    # SummaryIndex: does NOT embed. Summarises all docs sequentially.
    # Best for: "give me a summary of everything" queries.
    # Expensive at query time — every Node goes into the prompt.
    summary_index = SummaryIndex.from_documents(docs)
    print("SummaryIndex built.")

    # TreeIndex: builds a tree of summaries bottom-up.
    # Best for: navigating very long documents hierarchically.
    tree_index = TreeIndex.from_documents(docs)
    print("TreeIndex built.")

    # KeywordTableIndex: extracts keywords, builds inverted index.
    # Best for: exact keyword search, not semantic similarity.
    keyword_index = KeywordTableIndex.from_documents(docs)
    print("KeywordTableIndex built.")

    return vector_index, summary_index


# ═══════════════════════════════════════════════════════════════
# 4. PERSIST AND RELOAD
# ═══════════════════════════════════════════════════════════════

def persist_and_reload(index: VectorStoreIndex, storage_dir: str = "./storage"):
    """
    Persist avoids re-embedding on every restart.
    Critical in production — embedding 500 PDFs = minutes + $$.
    """
    # Save index, docstore, and vector store to disk
    index.storage_context.persist(persist_dir=storage_dir)
    print(f"Index persisted to {storage_dir}/")

    # Reload from disk — no re-embedding needed
    storage_context = StorageContext.from_defaults(persist_dir=storage_dir)
    reloaded_index = load_index_from_storage(storage_context)
    print("Index reloaded from disk.")
    return reloaded_index


# ═══════════════════════════════════════════════════════════════
# 5. VECTOR STORE BACKENDS (Chroma example)
# ═══════════════════════════════════════════════════════════════

def build_index_with_chroma_backend(docs: list) -> VectorStoreIndex:
    """
    Production deployments use a dedicated vector DB instead of
    the default in-memory store. Chroma shown here; swap for
    Pinecone, Weaviate, Qdrant, or pgvector with same interface.
    """
    # Initialise ChromaDB client (persistent local storage)
    chroma_client = chromadb.PersistentClient(path="./chroma_db")

    # Create or get a named collection (like a table in a relational DB)
    chroma_collection = chroma_client.get_or_create_collection("my_docs")

    # Wrap Chroma collection in LlamaIndex's vector store adapter
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    # StorageContext wires the vector store into the index
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Build index — embeddings go into Chroma, not RAM
    index = VectorStoreIndex.from_documents(
        docs,
        storage_context=storage_context,
        show_progress=True,
    )
    print("Index built with Chroma backend.")
    return index

    # ── Pinecone backend (commented — needs pinecone installed) ──
    # import pinecone
    # from llama_index.vector_stores.pinecone import PineconeVectorStore
    # pinecone.init(api_key=os.environ["PINECONE_API_KEY"], environment="us-east1-gcp")
    # pinecone_index = pinecone.Index("my-index")
    # vector_store = PineconeVectorStore(pinecone_index=pinecone_index)


# ═══════════════════════════════════════════════════════════════
# 6. QUERY ENGINE AND RESPONSE MODES
# ═══════════════════════════════════════════════════════════════

def demo_query_engine(index: VectorStoreIndex):
    """
    QueryEngine = retriever + response synthesizer in one call.
    """

    # compact: fits all retrieved chunks into one prompt — default.
    # Good for short answers where all context fits in one window.
    engine_compact = index.as_query_engine(
        similarity_top_k=5,            # retrieve 5 most similar Nodes
        response_mode="compact",
    )

    # refine: generates initial answer from first chunk, then refines
    # by passing each subsequent chunk + current answer iteratively.
    # Better quality but more LLM calls (= slower + more expensive).
    engine_refine = index.as_query_engine(
        similarity_top_k=5,
        response_mode="refine",
    )

    # tree_summarize: builds a summary tree over retrieved chunks.
    # Best for long documents where context > single prompt window.
    engine_tree = index.as_query_engine(
        similarity_top_k=10,
        response_mode="tree_summarize",
    )

    # no_text: retrieval only — returns source Nodes, no LLM call.
    # Useful when you want raw chunks to process yourself.
    engine_retrieve_only = index.as_query_engine(
        similarity_top_k=5,
        response_mode="no_text",
    )

    # Execute a query
    question = "What are the main benefits of using LlamaIndex?"
    response = engine_compact.query(question)

    # .response: the synthesized answer string
    print(f"\nAnswer: {response.response}")

    # .source_nodes: list of NodeWithScore — always inspect these
    # to understand which chunks drove the answer
    for i, node in enumerate(response.source_nodes):
        print(f"\nSource {i+1} (score={node.score:.3f}):")
        print(f"  File    : {node.metadata.get('filename', 'N/A')}")
        print(f"  Excerpt : {node.text[:120]}...")

    return response


# ═══════════════════════════════════════════════════════════════
# 7. RERANKING PIPELINE
# ═══════════════════════════════════════════════════════════════

def build_reranked_query_engine(index: VectorStoreIndex) -> RetrieverQueryEngine:
    """
    Two-stage retrieval:
      Stage 1 — vector similarity fetches top-20 candidates (fast)
      Stage 2 — cross-encoder reranker selects top-5 (accurate)

    This pattern is standard in production RAG systems.
    Cohere reranker typically improves answer quality 10-20%
    over cosine-only retrieval at minimal extra latency.
    """
    # Stage 1: retrieve broader candidate set (top-20)
    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=20,    # cast wide net in vector space
    )

    # Stage 2: Cohere reranker re-scores all 20 candidates
    # and returns top_n=5 based on cross-attention relevance
    # Requires: COHERE_API_KEY env var
    cohere_reranker = CohereRerank(
        api_key=os.environ.get("COHERE_API_KEY", "dummy-key"),
        top_n=5,                # final number of Nodes after reranking
        model="rerank-english-v3.0",
    )

    # Similarity post-processor: discard nodes with score < 0.7
    # (safety net for clearly irrelevant results)
    sim_filter = SimilarityPostprocessor(similarity_cutoff=0.7)

    # Wire retriever + postprocessors into a query engine
    engine = RetrieverQueryEngine.from_args(
        retriever=retriever,
        node_postprocessors=[sim_filter, cohere_reranker],
        response_mode="compact",
    )
    print("Reranked query engine built (VectorRetriever → CohereRerank → compact).")
    return engine


# ═══════════════════════════════════════════════════════════════
# 8. SUB-QUESTION QUERY ENGINE
# ═══════════════════════════════════════════════════════════════

def build_sub_question_engine(
    q1_index: VectorStoreIndex,
    q2_index: VectorStoreIndex,
) -> SubQuestionQueryEngine:
    """
    SubQuestionQueryEngine decomposes complex questions into
    targeted sub-questions, queries appropriate indices, then
    synthesizes a unified answer.

    Example:
      Input : "Compare Q1 and Q2 revenue trends"
      Decomposed:
        sub-Q1: "What was Q1 revenue?" → Q1 index
        sub-Q2: "What was Q2 revenue?" → Q2 index
      Synthesis: combined answer comparing both.
    """
    # Wrap each index in a tool with a description the LLM uses
    # to decide which index to query for each sub-question
    q1_tool = QueryEngineTool(
        query_engine=q1_index.as_query_engine(),
        metadata=ToolMetadata(
            name="q1_financials",
            description="Q1 2024 financial reports including revenue, expenses, headcount.",
        ),
    )
    q2_tool = QueryEngineTool(
        query_engine=q2_index.as_query_engine(),
        metadata=ToolMetadata(
            name="q2_financials",
            description="Q2 2024 financial reports including revenue, expenses, headcount.",
        ),
    )

    # SubQuestionQueryEngine uses the LLM to plan sub-questions
    # then executes them in parallel against the appropriate tools
    engine = SubQuestionQueryEngine.from_defaults(
        query_engine_tools=[q1_tool, q2_tool],
        use_async=True,    # run sub-queries in parallel for speed
        verbose=True,      # print the sub-question decomposition
    )
    print("SubQuestionQueryEngine built with Q1 and Q2 tools.")
    return engine


# ═══════════════════════════════════════════════════════════════
# 9. ROUTER QUERY ENGINE
# ═══════════════════════════════════════════════════════════════

def build_router_engine(
    vector_index: VectorStoreIndex,
    summary_index: SummaryIndex,
) -> RouterQueryEngine:
    """
    RouterQueryEngine routes each query to the most appropriate
    engine based on query content. Uses LLM or embedding similarity
    to select the engine — no manual if/else branching needed.
    """
    vector_tool = QueryEngineTool.from_defaults(
        query_engine=vector_index.as_query_engine(similarity_top_k=5),
        description="Answers specific factual questions about document content.",
    )
    summary_tool = QueryEngineTool.from_defaults(
        query_engine=summary_index.as_query_engine(response_mode="tree_summarize"),
        description="Answers high-level summarisation questions about all documents.",
    )

    # LLMSingleSelector: uses LLM to pick one engine per query
    # EmbeddingSingleSelector: uses embeddings (faster, cheaper)
    router_engine = RouterQueryEngine(
        selector=LLMSingleSelector.from_defaults(),
        query_engine_tools=[vector_tool, summary_tool],
        verbose=True,
    )
    print("RouterQueryEngine built (LLMSingleSelector).")
    return router_engine


# ═══════════════════════════════════════════════════════════════
# 10. EVALUATION
# ═══════════════════════════════════════════════════════════════

def run_evaluation(index: VectorStoreIndex):
    """
    Three built-in evaluators for RAG quality assurance.
    Run these in CI before deploying a new index or prompt.
    """
    engine = index.as_query_engine(similarity_top_k=5)

    # FaithfulnessEvaluator: is the answer grounded in source nodes?
    # Detects hallucinations — answer says X but source doesn't support X.
    faithfulness_eval = FaithfulnessEvaluator()

    # RelevancyEvaluator: are the retrieved source nodes relevant to Q?
    # Detects retrieval failures — right answer, wrong sources.
    relevancy_eval = RelevancyEvaluator()

    # CorrectnessEvaluator: is the answer factually correct?
    # Requires a reference (ground truth) answer — needs labeled data.
    correctness_eval = CorrectnessEvaluator()

    # Sample golden Q&A pairs (in prod: 100-500 labelled pairs)
    golden_qa = [
        {
            "question": "What is LlamaIndex used for?",
            "reference": "LlamaIndex is used to connect LLMs with external data sources for RAG.",
        },
    ]

    results = []
    for qa in golden_qa:
        response = engine.query(qa["question"])

        # Faithfulness: no reference needed — compares answer to source_nodes
        faith_result = faithfulness_eval.evaluate_response(response=response)

        # Relevancy: no reference needed — evaluates source_nodes vs question
        rel_result = relevancy_eval.evaluate_response(
            query=qa["question"],
            response=response,
        )

        # Correctness: needs reference answer; scores 1-5
        corr_result = correctness_eval.evaluate_response(
            query=qa["question"],
            response=response,
            reference=qa["reference"],
        )

        results.append({
            "question": qa["question"],
            "faithfulness": faith_result.passing,      # True / False
            "faithfulness_score": faith_result.score,
            "relevancy": rel_result.passing,
            "correctness_score": corr_result.score,    # 1.0 – 5.0
        })
        print(f"Q: {qa['question']}")
        print(f"  Faithfulness : {faith_result.passing} ({faith_result.score})")
        print(f"  Relevancy    : {rel_result.passing}")
        print(f"  Correctness  : {corr_result.score}/5.0")

    return results


# ═══════════════════════════════════════════════════════════════
# 11. LLAMAINDEX + LANGCHAIN INTEGRATION
# ═══════════════════════════════════════════════════════════════

def llamaindex_as_langchain_tool(index: VectorStoreIndex):
    """
    Expose a LlamaIndex QueryEngine as a LangChain tool.
    Lets you mix LlamaIndex's retrieval power with LangChain's
    agent ecosystem (tool calling, memory, custom chains).
    """
    # Requires: pip install langchain llama-index-langchain-agent
    from langchain.agents import initialize_agent, AgentType
    from langchain.chat_models import ChatOpenAI
    from llama_index.core.langchain_helpers.agents import (
        IndexToolConfig,
        LlamaIndexTool,
    )

    # Wrap LlamaIndex engine as a LangChain-compatible tool
    tool_config = IndexToolConfig(
        query_engine=index.as_query_engine(similarity_top_k=5),
        name="DocumentQA",
        description=(
            "Answers questions about internal company documents. "
            "Use for any question about policies, procedures, or contracts."
        ),
        tool_kwargs={"return_direct": False},
    )
    llamaindex_tool = LlamaIndexTool.from_tool_config(tool_config)

    # Standard LangChain agent — now has document Q&A capability
    lc_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = initialize_agent(
        tools=[llamaindex_tool],
        llm=lc_llm,
        agent=AgentType.OPENAI_FUNCTIONS,
        verbose=True,
    )
    return agent


# ═══════════════════════════════════════════════════════════════
# 12. FULL PRODUCTION PIPELINE
# ═══════════════════════════════════════════════════════════════

def production_pdf_qa_system(docs_path: str, question: str) -> dict:
    """
    End-to-end production pipeline:
      SimpleDirectoryReader
        -> VectorStoreIndex (Chroma backend)
        -> Persist to disk
        -> VectorIndexRetriever (top-20)
        -> CohereRerank (top-5)
        -> compact synthesis
        -> FaithfulnessEvaluator
    Returns answer dict with response, sources, and eval score.
    """
    print("=" * 60)
    print("PRODUCTION PDF Q&A PIPELINE")
    print("=" * 60)

    # Step 1: load documents
    print("\n[1/5] Loading documents...")
    # In real prod, check if storage exists first to skip re-embed
    storage_dir = "./prod_storage"
    if os.path.exists(storage_dir):
        print("  Found existing index — reloading from disk.")
        sc = StorageContext.from_defaults(persist_dir=storage_dir)
        index = load_index_from_storage(sc)
    else:
        print("  No existing index — building from scratch.")
        docs = load_documents_from_directory(docs_path)

        # Step 2: parse into nodes with custom splitter
        print("\n[2/5] Parsing into nodes...")
        splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
        nodes = splitter.get_nodes_from_documents(docs, show_progress=True)
        print(f"  Created {len(nodes)} nodes from {len(docs)} documents.")

        # Step 3: build vector index
        print("\n[3/5] Building VectorStoreIndex...")
        index = VectorStoreIndex(nodes, show_progress=True)

        # Step 4: persist to disk
        print("\n[4/5] Persisting index...")
        index.storage_context.persist(persist_dir=storage_dir)

    # Step 5: query with reranking
    print("\n[5/5] Querying with reranking pipeline...")
    retriever = VectorIndexRetriever(index=index, similarity_top_k=20)
    reranker = CohereRerank(
        api_key=os.environ.get("COHERE_API_KEY", "dummy-key"),
        top_n=5,
        model="rerank-english-v3.0",
    )
    engine = RetrieverQueryEngine.from_args(
        retriever=retriever,
        node_postprocessors=[reranker],
        response_mode="compact",
    )

    response = engine.query(question)

    # Evaluate faithfulness — flag if score < 0.8
    evaluator = FaithfulnessEvaluator()
    eval_result = evaluator.evaluate_response(response=response)
    if not eval_result.passing:
        print("  WARNING: Faithfulness check FAILED — possible hallucination.")

    result = {
        "question": question,
        "answer": response.response,
        "faithfulness_score": eval_result.score,
        "faithfulness_passing": eval_result.passing,
        "sources": [
            {
                "file": n.metadata.get("filename", "unknown"),
                "score": round(n.score, 4),
                "excerpt": n.text[:200],
            }
            for n in response.source_nodes
        ],
    }

    print(f"\nAnswer      : {result['answer'][:200]}...")
    print(f"Faithfulness: {result['faithfulness_score']} (passing={result['faithfulness_passing']})")
    print(f"Sources used: {len(result['sources'])}")
    return result


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Demonstrate core concepts without requiring actual PDF files
    print("LlamaIndex L06 — Core Concepts Demo")
    print("=" * 60)

    # 1. Documents and Nodes
    print("\n--- 1. Documents & Nodes ---")
    doc = demo_documents_and_nodes()

    # 2. Build a small in-memory index from synthetic docs
    print("\n--- 2. Building in-memory VectorStoreIndex ---")
    sample_docs = [
        Document(text="LlamaIndex is a framework for document Q&A using LLMs.",
                 metadata={"filename": "overview.txt"}),
        Document(text="VectorStoreIndex stores embeddings for cosine similarity search.",
                 metadata={"filename": "index_types.txt"}),
        Document(text="Reranking with Cohere improves retrieval precision by 10-20%.",
                 metadata={"filename": "retrieval.txt"}),
        Document(text="SubQuestionQueryEngine decomposes complex questions into sub-queries.",
                 metadata={"filename": "advanced.txt"}),
        Document(text="Always persist your index to avoid re-embedding on every restart.",
                 metadata={"filename": "best_practices.txt"}),
    ]

    # Note: without real OpenAI key this will fail on embedding call.
    # Set OPENAI_API_KEY env var to run end-to-end.
    print("Sample docs prepared. Set OPENAI_API_KEY to run full pipeline.")
    print("Architecture summary:")
    print("  Loading  : SimpleDirectoryReader / LlamaHub connectors")
    print("  Indexing : VectorStoreIndex + Chroma/Pinecone backend")
    print("  Querying : Retriever(top-20) -> CohereRerank(top-5) -> Synthesizer")
    print("  Eval     : FaithfulnessEvaluator in CI (threshold 0.8)")
    print("  Advanced : SubQuestionQueryEngine + RouterQueryEngine")
    print("\nDone. See function docstrings for detailed usage.")
