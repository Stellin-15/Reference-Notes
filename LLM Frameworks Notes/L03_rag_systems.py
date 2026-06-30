# ============================================================
# L03: RAG (Retrieval Augmented Generation) Systems
# ============================================================
# WHAT: Give LLMs access to external knowledge at query time by
#       retrieving relevant chunks from a document store and
#       injecting them into the prompt before generation.
# WHY:  Solves the three core LLM weaknesses: knowledge cutoff
#       (docs updated daily), private/internal data (never in
#       training), and hallucination on specifics (model must
#       answer from retrieved evidence, not memorized guesses).
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    RAG pipeline stages:
      1. Ingest: load docs → chunk → embed → store in vector DB
      2. Retrieve: embed query → cosine search → top-K chunks
      3. Augment: build prompt with retrieved context
      4. Generate: LLM answers grounded in retrieved evidence

    Key design decisions:
      - Chunking strategy (size, overlap, semantic vs fixed)
      - Embedding model (OpenAI vs open-source)
      - Vector DB (local dev vs managed prod)
      - Retrieval mode (dense / sparse / hybrid)
      - Reranking (bi-encoder retrieve, cross-encoder rerank)

PRODUCTION USE CASE:
    Company internal knowledge base: thousands of PDFs (HR
    policies, engineering runbooks, legal contracts). Employees
    ask natural-language questions; the system retrieves the 3-5
    most relevant paragraphs and generates a cited answer.
    Updated nightly when new docs are added to SharePoint.
    RAGAS evaluation runs in CI to catch retrieval regressions.

COMMON MISTAKES:
    1. Bad chunking: chunk_size too large (dilutes relevance) or
       too small (loses context). No overlap → cuts mid-sentence.
    2. Skipping reranking: bi-encoder retrieval is fast but noisy;
       cross-encoder rerank dramatically improves precision.
    3. Context overflow: stuffing 20 chunks into the prompt. LLMs
       suffer "lost in the middle" — attend poorly to middle chunks.
       3-5 high-quality chunks beats 20 mediocre ones.
    4. Embedding model mismatch: chunk with model A, query with
       model B. Vectors live in different spaces → garbage results.
    5. No relevance threshold: low-score chunks add noise. Always
       filter below a cosine similarity cutoff (e.g., 0.30).
    6. Evaluating only by vibe: use RAGAS metrics (faithfulness,
       answer_relevancy, context_precision, context_recall) in CI.
"""

# ── Imports ──────────────────────────────────────────────────
# pip install langchain langchain-openai langchain-community
# pip install chromadb sentence-transformers cohere ragas
# pip install pypdf tiktoken

from pathlib import Path
from typing import List, Dict, Any

# LangChain document loaders and text splitting
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Embedding models — OpenAI (paid) and HuggingFace (free)
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings

# Vector stores — Chroma for local dev, FAISS for in-memory
from langchain_community.vectorstores import Chroma, FAISS

# RAG chain construction
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

# Retrieval utilities
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain.retrievers.document_compressors import CohereRerank
from langchain.retrievers import ContextualCompressionRetriever

# Evaluation
# from ragas import evaluate  # uncomment when ragas is installed
# from ragas.metrics import faithfulness, answer_relevancy


# ── 1. EMBEDDING MODEL SELECTION ─────────────────────────────

def get_embedding_model(provider: str = "openai"):
    """
    Choose an embedding model based on cost/quality trade-offs.

    Comparison:
      openai  → text-embedding-3-small: 1536-dim, $0.02/1M tokens,
                best quality, requires API key.
      minilm  → all-MiniLM-L6-v2: 384-dim, free, fast, decent
                quality. Good for prototyping or cost-sensitive apps.
      bge     → BAAI/bge-small-en-v1.5: 384-dim, free, MTEB top-5.
                Best free model for production.

    IMPORTANT: whatever model you use to embed chunks at ingest time,
    you MUST use the exact same model to embed queries at retrieval time.
    """
    if provider == "openai":
        # OpenAI managed embeddings — no GPU needed, always available
        return OpenAIEmbeddings(model="text-embedding-3-small")

    elif provider == "minilm":
        # Free local model — downloads ~80 MB on first run
        return HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},   # use "cuda" if GPU available
            encode_kwargs={"normalize_embeddings": True},  # cosine needs unit vecs
        )

    elif provider == "bge":
        # BGE small — free, excellent quality, recommended for prod if GPU available
        return HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-en-v1.5",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    raise ValueError(f"Unknown provider: {provider}")


# ── 2. DOCUMENT LOADING ───────────────────────────────────────

def load_documents(pdf_dir: str) -> List:
    """
    Load all PDFs from a directory. Each page becomes a Document
    object with page_content (text) and metadata (source, page).
    """
    # DirectoryLoader globs all PDFs and delegates to PyPDFLoader per file
    loader = DirectoryLoader(
        pdf_dir,
        glob="**/*.pdf",            # recurse into subdirectories
        loader_cls=PyPDFLoader,
        show_progress=True,         # progress bar for large corpora
    )
    docs = loader.load()
    print(f"Loaded {len(docs)} pages from {pdf_dir}")
    return docs


# ── 3. CHUNKING ───────────────────────────────────────────────

def chunk_documents(docs: List, chunk_size: int = 512, chunk_overlap: int = 50) -> List:
    """
    Split documents into chunks suitable for embedding and retrieval.

    RecursiveCharacterTextSplitter tries to split on: paragraph → sentence
    → word → character — whichever keeps chunks under chunk_size.

    chunk_overlap=50: last 50 chars of chunk N appear as first 50 of chunk N+1.
    This prevents a sentence from being cut exactly at the boundary, ensuring
    at least one full sentence exists in every chunk for context.

    Rule of thumb:
      chunk_size=512   → good for technical docs with dense info per paragraph
      chunk_size=256   → better for Q&A where precision matters
      chunk_size=1024  → acceptable for narrative text (legal, stories)
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        # Separators tried in order; falls back to next if chunk still too large
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,         # character count (use tiktoken for token count)
    )
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks (avg {chunk_size} chars each)")
    return chunks


# ── 4. VECTOR STORE — BUILD AND PERSIST ──────────────────────

def build_chroma_store(chunks: List, embeddings, persist_dir: str = "./chroma_db"):
    """
    Embed all chunks and store in Chroma (local disk-backed vector DB).

    Chroma is ideal for:
      - Development and prototyping
      - Up to ~100k documents
      - Teams without a dedicated vector DB deployment

    For production at scale, prefer:
      - Pinecone (managed, serverless, fast)
      - Qdrant (self-hosted Rust, very fast, supports filtering)
      - pgvector (if you already run Postgres — single data layer)
    """
    # from_documents embeds every chunk and writes to persist_dir
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=persist_dir,    # survives process restarts
        collection_name="company_docs",   # namespace for multiple collections
    )
    print(f"Stored {len(chunks)} chunks in Chroma at {persist_dir}")
    return vectorstore


def load_chroma_store(embeddings, persist_dir: str = "./chroma_db"):
    """Load an existing Chroma store without re-embedding (fast startup)."""
    return Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        collection_name="company_docs",
    )


# ── 5. RETRIEVAL STRATEGIES ───────────────────────────────────

def dense_retriever(vectorstore, k: int = 20):
    """
    Dense retrieval: embed the query, find nearest chunk vectors by cosine.
    MMR (Maximal Marginal Relevance) diversifies results — avoids returning
    5 near-identical chunks. fetch_k=40 means retrieve 40, then diversify to k=5.
    """
    return vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": k,           # number of chunks to return
            "fetch_k": 40,    # pool size before MMR filtering
            "lambda_mult": 0.7,  # 1.0=pure relevance, 0.0=pure diversity
        },
    )


def hybrid_retriever(chunks: List, vectorstore, k: int = 10):
    """
    Hybrid retrieval = Dense (embedding cosine) + Sparse (BM25 keyword).
    Combined with Reciprocal Rank Fusion (RRF) — almost always outperforms
    either method alone.

    Use case: dense misses exact product codes ("SKU-4821"), sparse catches them.
    Sparse misses synonyms ("car" vs "vehicle"), dense catches them.
    Hybrid catches both.
    """
    # BM25 retriever: classic TF-IDF keyword matching
    bm25 = BM25Retriever.from_documents(chunks)
    bm25.k = k

    # Dense (vector) retriever
    faiss_retriever = vectorstore.as_retriever(search_kwargs={"k": k})

    # EnsembleRetriever applies RRF: weights=[0.4, 0.6] favors dense slightly
    ensemble = EnsembleRetriever(
        retrievers=[bm25, faiss_retriever],
        weights=[0.4, 0.6],   # tune based on your domain; keyword-heavy → 0.6/0.4
    )
    return ensemble


# ── 6. RERANKING ─────────────────────────────────────────────

def add_reranker(base_retriever, cohere_api_key: str, top_n: int = 5):
    """
    Two-stage retrieval:
      Stage 1 (bi-encoder): fast embedding search, retrieve top-20 candidates
      Stage 2 (cross-encoder): slower but highly accurate reranking to top-5

    Cross-encoders score (query, chunk) pairs jointly — they understand the
    relationship between query and chunk, not just their individual semantics.

    Options:
      Cohere Rerank (managed API, excellent quality, ~$1/1000 calls)
      BAAI/bge-reranker-base (free, run locally, good quality)
    """
    # Cohere's reranker is managed and requires no GPU
    compressor = CohereRerank(
        cohere_api_key=cohere_api_key,
        top_n=top_n,              # keep only top 5 after reranking
        model="rerank-english-v3.0",
    )

    # ContextualCompressionRetriever wraps any retriever with a compressor
    return ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,   # runs first, then reranker filters
    )


# ── 7. RAG PROMPT ─────────────────────────────────────────────

RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful assistant answering questions about company documents.
Use ONLY the information in the context below. If the answer is not in the context,
say "I don't have that information in the available documents."
Do not make up facts. Cite which document/section you drew from.

Context:
{context}"""),
    ("human", "{input}"),
])


# ── 8. FULL RAG CHAIN ─────────────────────────────────────────

def build_rag_chain(retriever, llm):
    """
    Assemble the full RAG chain using LangChain Expression Language (LCEL).

    create_stuff_documents_chain: takes retrieved docs, formats them as
    a single context string, then calls the LLM.

    create_retrieval_chain: wires retriever → doc chain. Returns both
    the answer and the source documents for citation.
    """
    # Combines retrieved docs into the {context} slot of the prompt
    doc_chain = create_stuff_documents_chain(llm, RAG_PROMPT)

    # Wraps everything: query → retrieve → prompt → llm → answer
    rag_chain = create_retrieval_chain(retriever, doc_chain)
    return rag_chain


# ── 9. RELEVANCE FILTERING ────────────────────────────────────

def filter_by_score(docs_and_scores: List, threshold: float = 0.30) -> List:
    """
    Drop chunks below a cosine similarity threshold before sending to LLM.

    Rationale: a chunk with similarity 0.18 is noise — it matches because of
    common stop words, not because it's actually relevant. Including it
    wastes context window and confuses the model.

    Threshold guidance:
      > 0.40: highly relevant (safe to trust)
      0.30-0.40: somewhat relevant (usually include)
      < 0.30: likely noise (drop)
    """
    filtered = [
        doc for doc, score in docs_and_scores
        if score >= threshold
    ]
    dropped = len(docs_and_scores) - len(filtered)
    if dropped:
        print(f"Filtered out {dropped} low-relevance chunks (< {threshold})")
    return filtered


# ── 10. RAGAS EVALUATION ──────────────────────────────────────

def prepare_ragas_dataset(questions: List[str], rag_chain) -> Dict:
    """
    Build evaluation dataset for RAGAS.

    RAGAS metrics:
      faithfulness:       Is the answer grounded in the retrieved context?
                          Catches hallucination. Ideal: 1.0
      answer_relevancy:   Does the answer address the question?
                          Ideal: 1.0
      context_precision:  Are the retrieved chunks actually relevant?
                          Measures retrieval quality. Ideal: 1.0
      context_recall:     Were all relevant chunks found?
                          Measures coverage. Requires ground truth.

    Run this in CI: if faithfulness drops below 0.7, alert the team —
    chunking or retrieval may have regressed.
    """
    records = []
    for question in questions:
        result = rag_chain.invoke({"input": question})

        records.append({
            "question": question,
            "answer": result["answer"],
            # Extract text from each retrieved Document object
            "contexts": [doc.page_content for doc in result["context"]],
            # ground_truth required for context_recall — fill from human annotations
            "ground_truth": "",
        })

    return records


# ── 11. END-TO-END EXAMPLE ────────────────────────────────────

def run_company_qa_pipeline(pdf_dir: str, openai_key: str, cohere_key: str):
    """
    Full pipeline: load PDFs → chunk → embed → store → hybrid retrieve
    → rerank → GPT-4o answer → RAGAS evaluation.

    This mirrors a real production deployment where:
      - PDFs are HR policies, engineering runbooks, legal contracts
      - Employees query via Slack bot or internal web UI
      - RAGAS runs nightly against a golden test set
    """
    # Step 1: Load all PDFs from the directory
    docs = load_documents(pdf_dir)

    # Step 2: Chunk with overlap to avoid mid-sentence cuts
    chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=50)

    # Step 3: Embed with OpenAI (consistent model for ingest + query)
    embeddings = get_embedding_model("openai")

    # Step 4: Store in Chroma for persistent local vector search
    vectorstore = build_chroma_store(chunks, embeddings, persist_dir="./company_db")

    # Step 5: Hybrid retriever (dense + BM25) — catches acronyms and synonyms
    hybrid = hybrid_retriever(chunks, vectorstore, k=20)

    # Step 6: Rerank top-20 down to top-5 using Cohere cross-encoder
    retriever = add_reranker(hybrid, cohere_api_key=cohere_key, top_n=5)

    # Step 7: LLM — GPT-4o for high-quality grounded generation
    llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=openai_key)

    # Step 8: Assemble the full RAG chain
    rag_chain = build_rag_chain(retriever, llm)

    # Step 9: Answer a question
    question = "What is the company's remote work reimbursement policy?"
    result = rag_chain.invoke({"input": question})

    print("\n=== RAG ANSWER ===")
    print(result["answer"])
    print("\n=== SOURCE CHUNKS ===")
    for i, doc in enumerate(result["context"], 1):
        # Print source filename and first 200 chars of each chunk
        print(f"\n[{i}] {doc.metadata.get('source', 'unknown')} p.{doc.metadata.get('page', '?')}")
        print(doc.page_content[:200] + "...")

    # Step 10: Prepare RAGAS evaluation dataset
    test_questions = [
        "What is the company's remote work reimbursement policy?",
        "How many vacation days do employees get in year one?",
        "What is the process for requesting a hardware upgrade?",
    ]
    ragas_data = prepare_ragas_dataset(test_questions, rag_chain)

    print("\n=== RAGAS DATASET (submit to ragas.evaluate()) ===")
    for rec in ragas_data:
        print(f"Q: {rec['question']}")
        print(f"A: {rec['answer'][:100]}...")
        print(f"Contexts: {len(rec['contexts'])} chunks retrieved\n")

    # Uncomment to run actual RAGAS evaluation:
    # from datasets import Dataset
    # from ragas import evaluate
    # from ragas.metrics import faithfulness, answer_relevancy, context_precision
    # dataset = Dataset.from_list(ragas_data)
    # scores = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_precision])
    # print(scores)

    return result


# ── 12. QUICK DEMO (no API key required) ─────────────────────

def demo_chunking_only():
    """
    Demonstrate chunking logic without any API calls.
    Useful for verifying chunk strategy before spending on embeddings.
    """
    from langchain_core.documents import Document

    # Simulate a loaded PDF page
    sample_text = """
    Remote Work Policy

    Employees are eligible for remote work after completing their 90-day
    onboarding period. Remote work requests must be submitted via the HR portal
    at least 5 business days in advance.

    Reimbursement: The company reimburses up to $150/month for home internet
    and $500/year for ergonomic equipment (chair, monitor, keyboard). Receipts
    must be submitted within 30 days of purchase via Concur.

    Security: Remote employees must use company-issued VPN at all times.
    Connecting from public Wi-Fi without VPN is a policy violation.
    """

    doc = Document(page_content=sample_text, metadata={"source": "hr_policy.pdf", "page": 3})

    # Chunk the simulated document
    chunks = chunk_documents([doc], chunk_size=200, chunk_overlap=30)

    print(f"\nOriginal: {len(sample_text)} chars → {len(chunks)} chunks\n")
    for i, chunk in enumerate(chunks):
        print(f"--- Chunk {i+1} ({len(chunk.page_content)} chars) ---")
        print(chunk.page_content)
        print()


if __name__ == "__main__":
    # Run chunking demo (no API keys needed)
    demo_chunking_only()

    # To run the full pipeline, provide real paths and keys:
    # run_company_qa_pipeline(
    #     pdf_dir="./company_docs",
    #     openai_key="sk-...",
    #     cohere_key="...",
    # )
