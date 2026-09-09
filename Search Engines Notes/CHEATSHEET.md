# Search Engines — In-Depth Reference

Elasticsearch/OpenSearch/Solr internals and relevance tuning — the "how do
you actually build good search" domain, distinct from vector-similarity
search (covered in AI Agent & Automation Tooling Notes).


## 1. THE INVERTED INDEX — THE CORE DATA STRUCTURE

A traditional database index maps a ROW to its values; a search engine's
inverted index does the opposite: maps each unique TERM to the list of
documents containing it. Searching for "database" becomes an instant
lookup of the term "database" → [doc IDs], instead of scanning every
document's text — this single structural choice is why full-text search
engines outperform `LIKE '%term%'` queries on a relational database by orders of magnitude at scale.

```
Document 1: "the quick brown fox"
Document 2: "the lazy fox sleeps"

Inverted index:
  "the"   -> [1, 2]
  "quick" -> [1]
  "brown" -> [1]
  "fox"   -> [1, 2]
  "lazy"  -> [2]
  "sleeps"-> [2]
```

**Analyzers** transform raw text into indexed terms — TOKENIZATION (split
into words), LOWERCASING, STEMMING (running → run), and STOP-WORD removal
(the, a, is) — the analyzer used at INDEX time must be compatible with the
one used at QUERY time, or search results silently miss matches (a classic
"why isn't this obviously matching document showing up" debugging session).


## 2. RELEVANCE SCORING — BM25

Modern search engines (Elasticsearch/OpenSearch/Solr, all built on Lucene)
score relevance using **BM25** (Best Match 25), which balances:
- **Term Frequency (TF)** — how often a term appears in a document (more
  occurrences = more relevant, but with DIMINISHING returns — BM25
  specifically saturates this, unlike naive TF-IDF, so a document
  repeating a word 100 times doesn't score 10x higher than one repeating it 10 times).
- **Inverse Document Frequency (IDF)** — rare terms across the whole
  corpus are weighted MORE heavily than common ones (a match on "anaphylaxis" matters more than a match on "the").
- **Field-length normalization** — a term matching in a SHORT field
  (title) is weighted more than the same match in a long field (full body text).

```json
// Elasticsearch query with field boosting — title matches count 3x more
{
  "query": {
    "multi_match": {
      "query": "wireless headphones",
      "fields": ["title^3", "description"]
    }
  }
}
```


## 3. QUERY TYPES

- **Match query** — analyzed, full-text search (the default, handles
  typos/stemming per the analyzer's configuration).
- **Term query** — EXACT, unanalyzed match — used for keyword/enum-style
  fields (a status code, a category ID), never for free-text search.
- **Bool query** — combines `must`(AND, scores), `should` (OR, boosts
  score if matched), `must_not` (exclude), `filter` (AND, but doesn't
  affect scoring — faster, cacheable) — the `filter` vs `must` distinction
  is a real, common performance lever (use `filter` for anything that's a
  binary yes/no criterion, not a relevance signal).
- **Fuzzy query** — matches terms within an edit-distance threshold,
  handling typos (`hedaphones` still matching "headphones").


## 4. NICHE BUT REAL

- **Vector search + BM25 hybrid** — modern Elasticsearch/OpenSearch
  support combining traditional keyword (BM25) scoring WITH vector
  similarity (dense embedding) search in one query — genuinely the current
  state of the art for search quality, since keyword search catches exact
  terms/names vector search sometimes misses, and vector search catches
  semantic similarity keyword search entirely misses.
- **Learning to Rank (LTR)** — training an actual ML model on click-
  through/conversion data to RE-RANK search results beyond what BM25
  alone provides — the difference between "technically relevant" and
  "actually what users click," a real, distinct discipline at companies with search-heavy products.
- **Index aliasing & zero-downtime reindexing** — because changing an
  analyzer/mapping requires a full reindex (can't be done in-place),
  production search systems use an ALIAS pointing to the "live" index,
  build a new index in the background, then atomically swap the alias —
  the standard technique for reindexing without any search downtime.
- **Sharding & routing** — Elasticsearch shards documents across nodes by
  a hash of the document ID by default, but CUSTOM routing (route by
  `customer_id`) lets all of one customer's documents live on the same
  shard, making per-customer queries faster and enabling per-tenant index
  isolation strategies at scale.
- **Search-as-you-type / autocomplete** — implemented via `edge_ngram`
  tokenization (indexing partial prefixes of each term) or a dedicated
  completion suggester, a genuinely different indexing strategy from
  regular full-text search, optimized specifically for prefix matching speed.
