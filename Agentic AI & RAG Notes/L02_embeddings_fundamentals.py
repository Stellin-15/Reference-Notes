# ============================================================
# L02: Embeddings Fundamentals — Providers, Similarity, Dimensionality
# ============================================================
# WHAT: What an embedding actually is, the major embedding model
#       providers (OpenAI Embeddings, Cohere Embed, Voyage AI, Sentence
#       Transformers, BGE, Google Vertex AI Embeddings, Azure OpenAI
#       Embeddings), similarity metrics, and the dimensionality/cost/
#       accuracy tradeoffs between them.
# WHY: Every RAG system (L04 onward) and every vector database (L03) is
#      built on embeddings — you cannot reason about retrieval quality,
#      cost, or storage requirements without understanding what an
#      embedding vector represents and how different providers' choices
#      trade off against each other.
# LEVEL: Foundation (Phase 1 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
An EMBEDDING is a fixed-length vector of real numbers that represents
the SEMANTIC MEANING of a piece of text (or image, audio, etc.) — texts
with similar meaning produce vectors that are numerically CLOSE together
in the embedding space, even if they share few or no exact words
("a dog barked" and "a canine made noise" land near each other; "a dog
barked" and "the stock market crashed" land far apart). This is what
enables SEMANTIC search: finding relevant text by meaning, not just
keyword overlap.

Embeddings are produced by a dedicated EMBEDDING MODEL, distinct from a
generative chat model, though often trained by the same organization.
The major providers:
  - OpenAI Embeddings (text-embedding-3-small/large): widely used,
    variable output dimensionality (can be truncated to a smaller size
    with only modest quality loss — a real cost/storage lever).
  - Cohere Embed: strong multilingual support, offers input-type-specific
    embeddings (a "search_query" embedding differs from a "search_document"
    embedding for the same text, tuned for asymmetric search).
  - Voyage AI: a specialized embeddings-only provider, often benchmarked
    competitively for retrieval-specific quality, including domain-tuned
    variants (e.g. code, finance).
  - Sentence Transformers: an OPEN-SOURCE Python library/model family
    (via Hugging Face) — run locally, no API cost, no data leaving your
    infrastructure, at the cost of self-hosting the model.
  - BGE (BAAI General Embedding): another strong open-source embedding
    model family, frequently near the top of open embedding benchmark
    leaderboards.
  - Google Vertex AI Embeddings / Azure OpenAI Embeddings: cloud-platform
    -native hosted embedding services, chosen for deep integration with
    an existing GCP/Azure deployment rather than a standalone API.

SIMILARITY METRICS quantify "how close" two embedding vectors are. COSINE
SIMILARITY (measuring the angle between vectors, ignoring magnitude) is
the most common default for text embeddings. DOT PRODUCT is
mathematically related but sensitive to vector magnitude — some models
are specifically trained/normalized such that dot product and cosine
similarity give equivalent rankings, which matters when a vector
database's default metric doesn't match what a given embedding model
was tuned for. EUCLIDEAN DISTANCE (straight-line distance) is less common
for text but appears in some vector database defaults.

DIMENSIONALITY (the length of the embedding vector — e.g. 384, 768, 1536,
3072) trades off STORAGE COST and QUERY SPEED against representational
capacity. Higher dimensions can capture more nuance but cost more to
store and search; many modern embedding models support "Matryoshka"
truncation — you can safely use a PREFIX of the full vector (e.g. the
first 256 of 1536 dimensions) with graceful, predictable quality
degradation rather than needing to re-embed at a smaller size.

PRODUCTION USE CASE:
A cost-sensitive RAG system embeds documents with OpenAI's
text-embedding-3-small at a truncated 512 dimensions (instead of the full
1536) — cutting vector storage and search cost roughly 3x while
retaining most retrieval quality, a tradeoff explicitly enabled by the
model's Matryoshka-style training.

COMMON MISTAKES:
- Embedding queries and documents with DIFFERENT models (or different
  versions of the same model) — embedding spaces are NOT necessarily
  compatible across models/versions; comparing a query embedded with
  model A against documents embedded with model B produces meaningless
  similarity scores.
- Using cosine similarity against a vector database configured for a
  DIFFERENT default metric than what the embedding model was tuned for
  — most vector databases let you choose the metric explicitly; leaving
  it as a default without checking the embedding model's documentation
  is a common, silent-quality-degradation mistake.
- Choosing the largest/highest-dimensional embedding model "to be safe"
  without measuring actual retrieval quality on your own data — smaller
  open-source models (Sentence Transformers, BGE) are frequently
  competitive for many domains at a fraction of the cost/latency of the
  largest hosted options.
"""

import math


# ------------------------------------------------------------------
# 1. What an embedding IS — a minimal illustration
# ------------------------------------------------------------------
def toy_embed(text: str) -> list[float]:
    """
    A deliberately simplified, illustrative "embedding" (NOT a real
    model) — maps a handful of hand-picked semantic dimensions to make
    the CONCEPT of "similar meaning -> close vectors" concrete before
    treating real embedding models as a black box.
    """
    text_lower = text.lower()
    return [
        1.0 if "dog" in text_lower or "canine" in text_lower or "puppy" in text_lower else 0.0,
        1.0 if "cat" in text_lower or "feline" in text_lower else 0.0,
        1.0 if "stock" in text_lower or "market" in text_lower or "finance" in text_lower else 0.0,
        1.0 if "bark" in text_lower or "noise" in text_lower or "sound" in text_lower else 0.0,
    ]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def similarity_demo():
    texts = [
        "a dog barked loudly",
        "a canine made a lot of noise",
        "the stock market crashed today",
    ]
    embeddings = [toy_embed(t) for t in texts]
    print(f"'{texts[0]}' vs '{texts[1]}': "
          f"cosine similarity = {cosine_similarity(embeddings[0], embeddings[1]):.3f}  (semantically similar)")
    print(f"'{texts[0]}' vs '{texts[2]}': "
          f"cosine similarity = {cosine_similarity(embeddings[0], embeddings[2]):.3f}  (semantically unrelated)")


# ------------------------------------------------------------------
# 2. Real embedding model usage — provider comparison
# ------------------------------------------------------------------
import textwrap

OPENAI_EMBEDDING_EXAMPLE = textwrap.dedent("""\
    from openai import OpenAI
    client = OpenAI()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input="a dog barked loudly",
        dimensions=512,   # Matryoshka-style truncation — a real cost lever,
                            # not just a smaller/lower-quality alternative model
    )
    vector = response.data[0].embedding   # a 512-length list of floats
""")

COHERE_EMBEDDING_EXAMPLE = textwrap.dedent("""\
    import cohere
    co = cohere.Client("...")
    response = co.embed(
        texts=["a dog barked loudly"],
        model="embed-english-v3.0",
        input_type="search_document",   # ASYMMETRIC: a QUERY at search
                                          # time uses input_type="search_query"
                                          # instead — Cohere trains these
                                          # differently for better retrieval,
                                          # unlike a symmetric embedding
                                          # model where query and document
                                          # embeddings are produced identically.
    )
""")

SENTENCE_TRANSFORMERS_EXAMPLE = textwrap.dedent("""\
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")   # runs LOCALLY, no API call
    embedding = model.encode("a dog barked loudly")    # a numpy array, 384-dim

    # BGE (another strong open-source family) works identically via the
    # same library:
    # model = SentenceTransformer("BAAI/bge-large-en-v1.5")
""")

VOYAGE_EXAMPLE = textwrap.dedent("""\
    import voyageai
    vo = voyageai.Client()
    result = vo.embed(["a dog barked loudly"], model="voyage-3", input_type="document")
    # Voyage AI is embeddings-ONLY (no chat/completion API) — chosen
    # specifically when retrieval quality is the priority and you're
    # already using a separate provider for generation.
""")

# ------------------------------------------------------------------
# 3. Provider/model comparison table
# ------------------------------------------------------------------
EMBEDDING_PROVIDER_COMPARISON = {
    "OpenAI text-embedding-3-small/large": "Hosted API, Matryoshka "
        "truncation supported, widely integrated across frameworks — a "
        "strong general-purpose default.",
    "Cohere Embed v3": "Hosted API, asymmetric search_query/search_document "
        "input types, strong multilingual support.",
    "Voyage AI": "Hosted API, embeddings-only specialist, domain-tuned "
        "variants (code, finance, law) available.",
    "Sentence Transformers (open-source)": "Self-hosted, zero per-call "
        "cost, no data leaves your infrastructure, wide range of model "
        "sizes (from tiny/fast to large/accurate).",
    "BGE (open-source)": "Self-hosted like Sentence Transformers, "
        "frequently top-ranked on open retrieval benchmarks.",
    "Google Vertex AI Embeddings / Azure OpenAI Embeddings": "Cloud-"
        "platform-native hosted options — the natural choice when the "
        "rest of your stack already lives on that specific cloud.",
}

# ------------------------------------------------------------------
# 4. Dimensionality tradeoffs
# ------------------------------------------------------------------
def storage_cost_estimate(num_vectors: int, dimensions: int, bytes_per_float: int = 4) -> float:
    """A back-of-envelope storage cost calculation — the direct,
    quantifiable reason dimensionality matters at scale."""
    return num_vectors * dimensions * bytes_per_float / 1e9  # in GB


def dimensionality_tradeoff_demo():
    num_vectors = 10_000_000  # 10M document chunks — a realistic large RAG corpus
    for dims in (256, 512, 1536, 3072):
        gb = storage_cost_estimate(num_vectors, dims)
        print(f"  {dims:5d} dimensions: {gb:7.1f} GB raw vector storage "
              f"for {num_vectors:,} vectors")


if __name__ == "__main__":
    similarity_demo()
    print()
    print(OPENAI_EMBEDDING_EXAMPLE)
    print(COHERE_EMBEDDING_EXAMPLE)
    print(SENTENCE_TRANSFORMERS_EXAMPLE)
    print(VOYAGE_EXAMPLE)

    print("=== Provider comparison ===")
    for provider, note in EMBEDDING_PROVIDER_COMPARISON.items():
        print(f"{provider}: {note}\n")

    print("=== Dimensionality vs storage cost (10M vectors) ===")
    dimensionality_tradeoff_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A legal-document RAG system evaluates three embedding options on its
OWN retrieval benchmark (not a generic public leaderboard): OpenAI's
text-embedding-3-large, Voyage AI's domain-tuned legal variant, and a
self-hosted BGE model — the domain-tuned Voyage model wins on retrieval
accuracy for legal-specific phrasing, justifying its cost over the more
general-purpose (and cheaper, at scale) self-hosted BGE alternative for
this specific use case; a different domain (general customer support
FAQs) might reach the opposite conclusion on the same three options.
"""
