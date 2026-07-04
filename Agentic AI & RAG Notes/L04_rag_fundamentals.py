# ============================================================
# L04: RAG Fundamentals — End-to-End Architecture, Chunking, Reranking, Evaluation
# ============================================================
# WHAT: The complete Retrieval-Augmented Generation pipeline from raw
#       document to grounded LLM answer — chunking strategies, the
#       retrieve-then-generate flow, reranking, and how to actually
#       measure whether a RAG system is working (RAGAS-style metrics).
# WHY: L01-L03 covered the building blocks (models, embeddings, vector
#      DBs) in isolation. This lesson assembles them into the actual RAG
#      pattern — the foundation every framework in Phase 2 (LlamaIndex,
#      Haystack, DSPy, etc.) is a more sophisticated implementation of.
# LEVEL: Foundation (Phase 1 of 7 — final foundations lesson)
# ============================================================

"""
CONCEPT OVERVIEW:
RAG solves a specific problem: an LLM's knowledge is frozen at training
time and it has no access to your private/current data. Instead of
fine-tuning a model on your data (expensive, slow to update, and prone
to the model still "hallucinating" facts not actually grounded in
source text), RAG RETRIEVES relevant text at query time and INSERTS it
into the prompt, so the model generates its answer GROUNDED in that
retrieved context — updating the knowledge is as simple as updating the
document corpus, no retraining required.

The full pipeline: (1) CHUNK your documents into retrieval-sized pieces
(a whole document is usually too large/unfocused to embed meaningfully
or fit in a prompt); (2) EMBED each chunk (L02) and store it in a vector
database (L03); (3) at query time, EMBED the user's question and
RETRIEVE the top-k most similar chunks; (4) optionally RERANK those
candidates with a more expensive, more accurate model (initial retrieval
optimizes for speed across millions of chunks; reranking optimizes for
accuracy across just the top candidates); (5) construct a PROMPT
combining the retrieved chunks and the user's question; (6) GENERATE the
final answer with an LLM, ideally citing which chunks it used.

CHUNKING STRATEGY significantly affects retrieval quality: FIXED-SIZE
chunking (split every N tokens) is simplest but can cut a sentence or
idea in half. SEMANTIC/RECURSIVE chunking splits along natural boundaries
(paragraphs, then sentences, then words, as a fallback cascade) to avoid
mid-thought splits. OVERLAP (each chunk shares some tokens with its
neighbor) reduces the chance a relevant fact sits exactly at a chunk
boundary and gets fragmented across two, neither of which alone contains
the full context.

RERANKING uses a CROSS-ENCODER (a model that scores a query-document PAIR
jointly, more accurate but far more expensive than the BI-ENCODER
embedding similarity used for initial retrieval, which scores query and
document independently). The two-stage pattern (cheap bi-encoder
retrieval over the WHOLE corpus, narrow to top-50, then expensive
cross-encoder reranking of just those 50 down to the final top-5) gets
most of a cross-encoder's accuracy without its prohibitive cost of
scoring every document in the corpus against every query.

EVALUATION (RAGAS-style metrics) measures RAG quality along several
distinct axes, because "the answer sounds good" isn't sufficient:
FAITHFULNESS (is the generated answer actually supported by the
retrieved context, or does it hallucinate beyond it), ANSWER RELEVANCE
(does the answer actually address the question asked), CONTEXT
PRECISION (of the retrieved chunks, how many were actually relevant —
low precision means noisy, wasted context), and CONTEXT RECALL (of the
chunks that WERE relevant and existed in the corpus, how many did
retrieval actually find — low recall means missed information regardless
of how good the generation step is).

PRODUCTION USE CASE:
A customer support RAG system retrieves the top-20 candidate help-
articles via fast bi-encoder search, reranks them down to the top-3 with
a cross-encoder for higher precision, and measures FAITHFULNESS on a
sample of production answers weekly — catching a regression where the
system started generating plausible-sounding but unsupported answers
after a prompt template change, before it became a widespread customer
complaint.

COMMON MISTAKES:
- Chunking too LARGE (whole documents or huge sections) — this dilutes
  the embedding's semantic focus (a chunk "about everything" embeds
  vaguely) and wastes prompt context on irrelevant surrounding text.
- Chunking too SMALL without overlap — fragments ideas across multiple
  chunks, so retrieval might find a chunk with HALF a relevant fact and
  miss the chunk containing the other half.
- Evaluating RAG quality only by "does the answer look plausible" via
  spot-checking, instead of systematic metrics (faithfulness, precision,
  recall) — this misses SYSTEMATIC issues (e.g. a bug causing retrieval
  to consistently miss a specific document type) that don't show up in
  a handful of manually inspected examples.
"""

import math
import re


# ------------------------------------------------------------------
# 1. Chunking strategies
# ------------------------------------------------------------------
def fixed_size_chunk(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Splits by a fixed token(-ish, using whitespace as a proxy) count,
    with OVERLAP so a fact sitting at a boundary isn't fragmented into
    two chunks that each contain only half of it."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap   # step forward by less than chunk_size -> overlap
    return chunks


def recursive_chunk(text: str, max_chunk_size: int) -> list[str]:
    """
    Splits along a CASCADE of natural boundaries — paragraphs first; any
    paragraph still too long gets split by sentence; any sentence still
    too long falls back to fixed-size splitting. This avoids cutting
    mid-sentence/mid-idea whenever a natural boundary is available.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    for para in paragraphs:
        if len(para.split()) <= max_chunk_size:
            chunks.append(para)
        else:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            current = []
            current_len = 0
            for sentence in sentences:
                sentence_len = len(sentence.split())
                if current_len + sentence_len > max_chunk_size and current:
                    chunks.append(" ".join(current))
                    current, current_len = [], 0
                current.append(sentence)
                current_len += sentence_len
            if current:
                chunks.append(" ".join(current))
    return chunks


# ------------------------------------------------------------------
# 2. The retrieve-then-generate pipeline
# ------------------------------------------------------------------
def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a, norm_b = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def toy_embed(text: str) -> list[float]:
    """Same illustrative toy embedding as L02 — stands in for a real
    embedding model call to keep this example dependency-free."""
    keywords = ["refund", "shipping", "password", "billing"]
    return [1.0 if kw in text.lower() else 0.0 for kw in keywords]


def retrieve(query: str, chunks: list[str], top_k: int) -> list[tuple[str, float]]:
    query_emb = toy_embed(query)
    scored = [(chunk, cosine_similarity(query_emb, toy_embed(chunk))) for chunk in chunks]
    return sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]


def build_rag_prompt(query: str, retrieved_chunks: list[str]) -> str:
    context = "\n\n".join(f"[{i+1}] {chunk}" for i, chunk in enumerate(retrieved_chunks))
    return (
        f"Answer the question using ONLY the context below. "
        f"Cite sources like [1], [2] where relevant. If the context "
        f"doesn't contain the answer, say so explicitly rather than guessing.\n\n"
        f"Context:\n{context}\n\nQuestion: {query}\n\nAnswer:"
    )


# ------------------------------------------------------------------
# 3. Two-stage retrieval: bi-encoder retrieval + cross-encoder reranking
# ------------------------------------------------------------------
def toy_cross_encoder_score(query: str, chunk: str) -> float:
    """
    A real cross-encoder JOINTLY processes (query, chunk) through one
    model for a more accurate relevance score than comparing two
    INDEPENDENTLY-computed embeddings (a bi-encoder) — far more expensive
    per pair, which is exactly why it's only applied to a SMALL,
    pre-filtered candidate set (the reranking pattern), not the whole corpus.
    """
    query_words = set(query.lower().split())
    chunk_words = set(chunk.lower().split())
    overlap = len(query_words & chunk_words)
    return overlap / max(len(query_words), 1)


def two_stage_retrieval(query: str, all_chunks: list[str], retrieve_k: int, final_k: int) -> list[str]:
    # Stage 1: cheap bi-encoder retrieval across the WHOLE corpus.
    candidates = retrieve(query, all_chunks, top_k=retrieve_k)
    # Stage 2: expensive cross-encoder reranking, but ONLY on the small
    # candidate set from stage 1 — this is what makes cross-encoder
    # accuracy affordable at all.
    reranked = sorted(
        [(chunk, toy_cross_encoder_score(query, chunk)) for chunk, _ in candidates],
        key=lambda x: x[1], reverse=True,
    )
    return [chunk for chunk, _ in reranked[:final_k]]


# ------------------------------------------------------------------
# 4. RAGAS-style evaluation metrics
# ------------------------------------------------------------------
def context_precision(retrieved_chunks: list[str], relevant_chunks: set[str]) -> float:
    """Of what was retrieved, how much was actually relevant?"""
    if not retrieved_chunks:
        return 0.0
    relevant_retrieved = sum(1 for c in retrieved_chunks if c in relevant_chunks)
    return relevant_retrieved / len(retrieved_chunks)


def context_recall(retrieved_chunks: list[str], relevant_chunks: set[str]) -> float:
    """Of what WAS relevant and existed in the corpus, how much did retrieval find?"""
    if not relevant_chunks:
        return 1.0
    found = sum(1 for c in relevant_chunks if c in retrieved_chunks)
    return found / len(relevant_chunks)


def faithfulness_check(answer: str, context: str) -> float:
    """
    A SIMPLIFIED faithfulness proxy: what fraction of the answer's
    claimed "facts" (here, just distinctive words as a toy proxy) also
    appear in the retrieved context. A real RAGAS faithfulness check
    uses an LLM to decompose the answer into atomic claims and verify
    each is entailed by the context — this illustrates the CONCEPT with
    a dependency-free stand-in.
    """
    answer_words = set(w for w in answer.lower().split() if len(w) > 4)
    context_words = set(context.lower().split())
    if not answer_words:
        return 1.0
    supported = sum(1 for w in answer_words if w in context_words)
    return supported / len(answer_words)


if __name__ == "__main__":
    doc = ("How to request a refund. Refunds are processed within 5 business days. "
           "Shipping delays. Standard shipping takes 3-7 days. "
           "Password reset. Use the forgot password link on the login page.")

    fixed_chunks = fixed_size_chunk(doc, chunk_size=8, overlap=2)
    print(f"Fixed-size chunks ({len(fixed_chunks)}):")
    for c in fixed_chunks:
        print(f"  - {c}")

    print("\n--- Retrieval + prompt construction ---")
    top = retrieve("how long does a refund take", fixed_chunks, top_k=2)
    print("Top retrieved:", top)
    prompt = build_rag_prompt("how long does a refund take", [c for c, _ in top])
    print(f"\nConstructed prompt:\n{prompt}")

    print("\n--- Two-stage retrieval ---")
    reranked = two_stage_retrieval("how long does a refund take", fixed_chunks, retrieve_k=4, final_k=1)
    print("Final reranked result:", reranked)

    print("\n--- Evaluation metrics ---")
    relevant = {fixed_chunks[0]}
    print("Context precision:", context_precision([c for c, _ in top], relevant))
    print("Context recall:", context_recall([c for c, _ in top], relevant))
    print("Faithfulness:", faithfulness_check(
        "Refunds are processed within 5 business days.",
        "Refunds are processed within 5 business days.",
    ))

"""
PRODUCTION CONTEXT EXAMPLE:
An internal knowledge-base RAG tool measures context recall weekly
against a curated set of question/relevant-document pairs, and notices
recall dropping specifically for questions about a recently-reorganized
product category — root-causing it to a chunking change that
accidentally split key information across chunk boundaries during a
recent re-indexing, a regression that "does the answer look right"
spot-checking had completely missed because the LLM was still generating
plausible-sounding (if subtly incomplete) answers from whatever partial
context it did retrieve.
"""
