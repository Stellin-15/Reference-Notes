# Agentic AI & RAG — Principal Engineer Deep Dive

Companion to the existing 26-lesson track. This is the theory/pipeline-
mechanics deep dive; AI Agent & Automation Tooling Notes covers the
PRODUCT/FRAMEWORK landscape — read both together.


## Chunking Strategy — The Most Underrated RAG Lever

**Beyond the lesson**: Most RAG quality problems trace back to CHUNKING
decisions made before embedding ever happens, not to the embedding model
or vector database choice. Fixed-size chunking (every 500 tokens) is
simple but routinely SPLITS a coherent idea across two chunks, degrading
both chunks' retrievability. Semantic chunking (splitting at natural
boundaries — paragraphs, sections, or via an embedding-similarity-based
boundary detector) preserves coherent units at the cost of variable chunk
sizes. Recursive character splitting (try splitting on paragraphs first,
fall back to sentences, then words, only as needed to hit a size target)
is the common pragmatic middle ground most production RAG pipelines
actually use. The often-missed lever: chunk OVERLAP (including the tail
of the previous chunk at the start of the next) directly mitigates the
"split a key sentence across a boundary" failure mode at a modest storage cost.

**Worked example**: Contextual retrieval (Anthropic's documented
technique) — prepending each chunk with a short, LLM-generated summary of
the chunk's context WITHIN the full document before embedding it — fixes
a real, common RAG failure where a chunk like "the company's revenue grew
30%" is unretrievable for a query about "Acme Corp's Q3 2024 performance"
because the chunk itself never mentions the company name or period,
those facts existing only in surrounding context that got chunked away.

**Interview Q&A**:
- *Q: A RAG system retrieves technically relevant chunks, but the final generated answer still seems to miss key context. Where do you look first?* A: Whether the retrieved chunks, in isolation, actually contain enough SELF-CONTAINED context to answer the question — a chunk can be topically relevant (good vector similarity) while missing critical surrounding context that was chunked away, which reranking/similarity tuning alone can't fix since the problem is upstream, in chunking strategy, not retrieval ranking.


## Agent Planning: ReAct, Reflexion, and Why Agents Loop

**Beyond the lesson**: ReAct (Reasoning + Acting) interleaves explicit
reasoning steps with tool-call actions in one continuous loop — the model
reasons about what it needs, takes an action (a tool call), observes the
result, and reasons again about the NEXT step — this loop structure is
literally why agent frameworks (LangGraph, see AI Agent & Automation
Tooling deep dive) model agents as graphs with cycles rather than a
single linear chain. Reflexion extends this with an explicit
SELF-CRITIQUE step — after attempting a task, the agent evaluates its
own output against the goal and, if unsatisfactory, revises its approach
and retries — a genuinely different mechanism from simple retry-on-error,
since the critique is about QUALITY/CORRECTNESS, not just execution failure.

**Interview Q&A**:
- *Q: An agent gets stuck in a loop, repeatedly calling the same tool with slightly different arguments without making progress. What structural safeguards prevent this in production?* A: A hard max-iteration/max-tool-call cap per task (a circuit breaker, see AI Agent & Automation Tooling deep dive section 10), explicit loop-detection (comparing recent tool calls for near-duplicates and forcing a different strategy or escalating to a human), and giving the agent visibility into its OWN history so it can recognize repetition itself rather than relying purely on external limits.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Retrieval quality techniques beyond basic vector search
- **Hybrid search** (see AI Agent & Automation Tooling and Search Engines
  deep dives) — combining BM25 keyword scoring with vector similarity;
  genuinely state-of-the-art for most production RAG, since keyword
  search catches exact terms (product SKUs, names) vector search sometimes misses.
- **Query expansion/rewriting** — using an LLM to rewrite a user's raw
  query into a more retrieval-friendly form (expanding abbreviations,
  adding synonyms, or decomposing a complex multi-part question into
  several simpler retrieval queries) BEFORE hitting the vector store.
- **HyDE (Hypothetical Document Embeddings)** — generating a
  HYPOTHETICAL answer to the query first, then embedding THAT (rather
  than the raw query) for retrieval — works because a hypothetical
  answer's embedding is often closer in vector space to the actual
  relevant documents than the question's embedding is, a genuinely
  counterintuitive but empirically effective technique.

### Advanced RAG architectures
- **GraphRAG** — building a knowledge graph FROM the source documents
  (extracting entities and relationships) and using graph traversal
  alongside/instead of pure vector similarity — particularly effective
  for questions requiring MULTI-HOP reasoning across documents ("what
  products does the company that acquired X also sell") that pure
  chunk-similarity retrieval handles poorly.
- **Agentic RAG** — the retrieval step itself becomes an agent decision
  (should I retrieve at all? from which source? do I need a second
  retrieval round after seeing the first results?) rather than a fixed
  single retrieve-then-generate pipeline — a real, more expensive but
  more capable architecture for complex, multi-step information needs.
- **Multi-vector retrieval** — storing MULTIPLE embeddings per document
  (a summary embedding AND detailed chunk embeddings) letting retrieval
  match at different granularities depending on the query's specificity.

### Agent memory architectures (see also AI Agent & Automation Tooling section 7)
- **Working memory vs episodic memory vs semantic memory** — a useful
  cognitive-science-inspired framing: working memory is the current
  context window; episodic memory is a log of past interactions/events
  (what happened, when); semantic memory is extracted, consolidated FACTS
  learned across interactions (not just a raw log) — production agent
  memory systems increasingly implement something like all three tiers
  rather than treating "memory" as one undifferentiated concept.


## NICHE BUT REAL

- **The retrieval-generation gap** — even with PERFECT retrieval (the
  exact right chunk retrieved every time), the generation step can still
  fail to use it correctly (ignoring retrieved context, or blending it
  incorrectly with the model's own parametric knowledge, occasionally
  producing a hallucination that CONTRADICTS the retrieved context) — a
  real, distinct failure mode from retrieval quality, requiring separate
  evaluation (RAGAS's faithfulness metric specifically targets this gap, see AI Agent & Automation Tooling deep dive).
- **Chunking for multimodal RAG** — retrieving over documents containing
  tables, images, and charts (not just plain text) requires genuinely
  different handling — table-aware chunking, image captioning before
  embedding, or multimodal embedding models that can directly embed
  images/text into the same vector space — an increasingly common, real
  production requirement as RAG expands beyond pure-text knowledge bases.
- **Self-RAG** — a research direction where the model itself decides,
  token by token during generation, WHETHER retrieval is even needed for
  the current part of its answer, and can critique its own retrieved
  context's relevance inline — a more integrated alternative to the
  fixed "always retrieve first, then generate" pipeline most production systems still use.
- **Long-context vs RAG tradeoff, as context windows grow** — with
  context windows now reaching very large sizes, a real, ongoing
  architectural debate is whether RAG remains necessary versus simply
  stuffing more raw source material directly into a long context —
  the practical answer in most production systems remains RAG for cost
  (long-context inference is expensive per call) and precision (irrelevant
  stuffed context can still degrade generation quality — see LLM Core
  Theory deep dive's "lost in the middle" finding), not because long context makes RAG theoretically obsolete.
