# ============================================================
# L07: Elasticsearch Fundamentals — Inverted Index, Mappings, Queries
# ============================================================
# WHAT: How Elasticsearch actually makes full-text search fast (the
#       inverted index), defining document structure via mappings, and
#       the two main query categories — full-text queries and
#       structured/filter queries — plus aggregations for analytics.
# WHY: This repo's Agentic AI & RAG Notes L03 mentioned Elasticsearch
#      briefly as a hybrid-search vector-DB option. This lesson covers
#      Elasticsearch on its OWN terms — as a full-text SEARCH ENGINE
#      first, a capability distinct from (and often complementary to)
#      the vector similarity search that domain focused on.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
An INVERTED INDEX is THE data structure that makes full-text search
fast: instead of storing documents and scanning them for a search term
(which would be prohibitively slow at scale), Elasticsearch builds a
mapping FROM each unique TERM (word) TO the list of documents containing
it — searching for "refund policy" becomes a fast LOOKUP of which
documents contain "refund" AND which contain "policy" (then combining/
scoring those results), rather than scanning every document's full text
character by character. This is the SAME fundamental concept as a
book's index (look up a word, find which pages mention it) applied to a
massive document collection.

A MAPPING defines each field's DATA TYPE and how it should be INDEXED —
critically, TEXT fields (analyzed, tokenized, searched via full-text
matching) are handled COMPLETELY DIFFERENTLY from KEYWORD fields (stored
as exact, unanalyzed strings, used for filtering/sorting/aggregation,
NOT full-text search) — a common, confusing mistake is expecting exact-
match filtering on a `text` field or full-text search on a `keyword`
field; the mapping's TYPE CHOICE determines which capability a field
actually supports.

FULL-TEXT QUERIES (the `match` query and its relatives) search TEXT
fields, using the SAME analysis process (tokenization, lowercasing,
stemming) used when the document was indexed — this means "Running" in
a search query can match "run" in an indexed document if stemming is
configured, a fundamentally FUZZY, relevance-scored matching behavior.
STRUCTURED/FILTER QUERIES (`term`, `range`) match KEYWORD/numeric/date
fields EXACTLY, with NO relevance scoring (a document either matches the
filter or it doesn't) — and, importantly, FILTER context queries are
CACHEABLE by Elasticsearch in a way full-text queries aren't, making
them faster for repeated exact-match filtering.

AGGREGATIONS let Elasticsearch compute ANALYTICS over search results —
counts, averages, histograms, grouped by field values — directly
analogous to SQL's GROUP BY, but computed over Elasticsearch's own
indexed data rather than requiring a separate analytics database for
this specific data.

PRODUCTION USE CASE:
A support-ticket search feature uses a `match` query against a `text`-
mapped `description` field (fuzzy, relevance-ranked full-text search
across ticket descriptions) COMBINED, in the SAME query, with a `term`
filter on a `keyword`-mapped `status` field (exact match — only
"open" tickets) — the full-text portion handles the FUZZY "find tickets
about X" need, while the filter portion handles the EXACT "only open
ones" constraint, each using the field-type-appropriate query mechanism.

COMMON MISTAKES:
- Mapping a field as `keyword` when full-text search is actually needed
  (or vice versa) — a `keyword` field requires an EXACT match (no
  stemming, no partial matching), which silently fails to find
  documents a user would reasonably expect a "search" to find.
- Using a full-text `match` query for what should be an EXACT filter
  (e.g. matching a status field) — this applies unnecessary text
  analysis/relevance scoring to what should be a simple, fast, cacheable
  boolean filter check.
- Not understanding that CHANGING a field's mapping typically requires
  REINDEXING the data (creating a new index with the corrected mapping
  and re-populating it) — mappings are largely fixed once data is
  indexed; getting them right from the start avoids costly reindexing later.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Defining a mapping — text vs keyword fields
# ------------------------------------------------------------------
MAPPING_EXAMPLE = textwrap.dedent("""\
    PUT /support_tickets
    {
      "mappings": {
        "properties": {
          "description": { "type": "text" },      // FULL-TEXT searchable,
                                                     // analyzed/tokenized
          "status": { "type": "keyword" },          // EXACT match only,
                                                     // used for filtering
          "priority": { "type": "keyword" },
          "created_at": { "type": "date" },
          "customer_id": { "type": "keyword" }
        }
      }
    }

    // A common pattern: map the SAME field BOTH ways, for different
    // needs — full-text search AND exact-match aggregation on one field:
    "title": {
      "type": "text",
      "fields": {
        "raw": { "type": "keyword" }   // access as "title.raw" for exact match
      }
    }
""")

# ------------------------------------------------------------------
# 2. Full-text queries vs structured filters
# ------------------------------------------------------------------
QUERY_EXAMPLE = textwrap.dedent("""\
    GET /support_tickets/_search
    {
      "query": {
        "bool": {
          "must": [
            { "match": { "description": "refund not received" } }
            // FULL-TEXT match — fuzzy, relevance-scored, analyzed
            // (matches "refund" even if the doc says "refunded", "refunds", etc.
            // depending on the configured analyzer's stemming behavior)
          ],
          "filter": [
            { "term": { "status": "open" } },
            // EXACT match, NO relevance scoring, CACHEABLE — filter
            // context is specifically optimized for this kind of
            // repeated, boolean-only matching
            { "range": { "created_at": { "gte": "2026-01-01" } } }
          ]
        }
      }
    }

    // Combining full-text relevance (finding RELEVANT tickets) with
    // exact filters (only OPEN, only RECENT) in ONE query — the "must"
    // clause affects the relevance SCORE; the "filter" clause does not,
    // it purely includes/excludes.
""")

# ------------------------------------------------------------------
# 3. Aggregations — analytics over indexed data
# ------------------------------------------------------------------
AGGREGATION_EXAMPLE = textwrap.dedent("""\
    GET /support_tickets/_search
    {
      "size": 0,   // don't return individual documents, just the aggregation
      "aggs": {
        "tickets_by_priority": {
          "terms": { "field": "priority" }   // GROUP BY priority, like SQL
        },
        "avg_resolution_time": {
          "avg": { "field": "resolution_time_hours" }
        },
        "tickets_over_time": {
          "date_histogram": { "field": "created_at", "calendar_interval": "day" }
        }
      }
    }
    // Returns: a count of tickets PER priority value, an average
    // resolution time, and a daily histogram — computed directly over
    // Elasticsearch's own indexed data, no separate analytics query needed.
""")

# ------------------------------------------------------------------
# 4. The inverted index, illustrated conceptually
# ------------------------------------------------------------------
INVERTED_INDEX_ILLUSTRATION = textwrap.dedent("""\
    Documents:
      doc1: "refund policy for damaged items"
      doc2: "how to request a refund"
      doc3: "shipping policy overview"

    Inverted index (term -> which documents contain it):
      "refund"  -> [doc1, doc2]
      "policy"  -> [doc1, doc3]
      "damaged" -> [doc1]
      "request" -> [doc2]
      "shipping" -> [doc3]

    A search for "refund policy" looks up BOTH terms in this index
    (O(1)-ish lookups, not a full document scan), finds doc1 matches
    BOTH terms (higher relevance score) while doc2 and doc3 each match
    only ONE term (lower scores) — this scoring-by-term-overlap is the
    basis of Elasticsearch's relevance ranking (TF-IDF/BM25-style
    scoring, refining this basic concept with term frequency and
    document-length normalization).
""")


if __name__ == "__main__":
    print(MAPPING_EXAMPLE)
    print(QUERY_EXAMPLE)
    print(AGGREGATION_EXAMPLE)
    print(INVERTED_INDEX_ILLUSTRATION)

"""
PRODUCTION CONTEXT EXAMPLE:
A support platform's ticket search combines a full-text `match` query
(finding tickets RELEVANT to a customer's free-text search) with exact
`term` filters (status=open, customer's own tickets only) and a
`terms` aggregation showing ticket counts by priority alongside the
search results — the SAME query serving both the search-results list
AND a small analytics sidebar ("12 high-priority, 34 medium-priority
matching tickets"), avoiding a separate analytics query entirely by
using Elasticsearch's combined query+aggregation capability in one call.
"""
