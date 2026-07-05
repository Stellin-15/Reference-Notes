# ============================================================
# L16: Comment Tree Storage at Scale — How Reddit Stores Nested Threads
# ============================================================
# WHAT: How to store and efficiently query a deeply NESTED, potentially
#       enormous comment tree (a post with tens of thousands of replies,
#       nested many levels deep) — adjacency list vs materialized path
#       vs nested set models, and their real tradeoffs.
# WHY: New case study: Reddit. A comment thread is a classic TREE data
#      structure, but storing and querying a tree efficiently in a
#      database that's fundamentally row/table-oriented (not
#      pointer-based, like in-memory tree structures) is a genuinely
#      distinct system design problem.
# LEVEL: Foundation (of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
An ADJACENCY LIST model stores each comment with a simple PARENT_ID
foreign key pointing to its immediate parent — the simplest possible
representation, and the one most naturally analogous to how you'd model
a tree in memory. Its major weakness: retrieving an ENTIRE subtree
(e.g. "show this comment and all its nested replies, however deep")
requires either a RECURSIVE query (supported by modern SQL databases via
recursive CTEs, but potentially slow for very deep/wide trees) or
multiple round-trip queries (fetch children, then their children, then
THEIR children...) — an operation that should be simple ("show me this
whole conversation") becomes surprisingly expensive at depth/scale.

MATERIALIZED PATH stores each comment's FULL ANCESTOR PATH as a string
(e.g. "1/47/203/891" meaning: comment 891 is a reply to 203, which
replies to 47, which replies to root comment 1) — retrieving an entire
subtree becomes a single, fast, INDEXED PREFIX QUERY ("find all comments
where path starts with '1/47/'"), dramatically simpler and faster than
adjacency list's recursive query. The tradeoff: the path must be UPDATED
for the comment and every descendant if a comment is ever MOVED to a
different parent (rare for comments specifically, but a real
consideration for other tree-shaped data), and the path string has a
practical maximum length/depth.

NESTED SET MODEL (assigning each node a LEFT and RIGHT integer such that
a node's descendants all fall within its own left/right range) makes
subtree queries even FASTER (a simple range comparison, no string
prefix matching needed) but makes INSERTING a new node expensive — every
existing node with a left/right value greater than the insertion point
must be re-numbered, an update that touches a potentially large fraction
of the table on every single new comment — this tradeoff makes nested
sets a poor fit for a comment system specifically (constant new
insertions), despite being excellent for RARELY-modified hierarchical
data (e.g. an organization chart, a product category tree).

REDDIT'S ACTUAL APPROACH (as described in public engineering writeups)
leans toward a MATERIALIZED-PATH-LIKE approach combined with fetching a
LIMITED DEPTH/BREADTH per request and LAZY-LOADING deeper replies
("load more comments" / "continue this thread" links) — this
sidesteps the "retrieve an enormous entire subtree" problem entirely for
the common case, since most users never expand every single nested reply
in a massive thread; the system only needs to efficiently fetch WHATEVER
depth/breadth is actually being viewed at any moment.

PRODUCTION USE CASE:
A viral Reddit post accumulates 50,000 comments across deeply nested
reply chains — rather than ever loading the ENTIRE tree for any single
page view, Reddit's comment-rendering system fetches only the TOP-LEVEL
comments (sorted by the ranking algorithm, L17) plus a LIMITED number of
each one's immediate replies, showing "continue this thread" links for
deeper nesting — a materialized-path-style index makes each of these
BOUNDED fetches fast, while the lazy-loading UI pattern avoids ever
needing an expensive full-tree operation for a normal page view.

COMMON MISTAKES:
- Choosing a nested-set model for comment storage specifically —
  comments are inserted CONSTANTLY and rarely reorganized, which is
  exactly the access pattern nested sets handle POORLY (expensive
  inserts) and RARELY-changing hierarchical data handles well — a clear
  mismatch between the data structure's strengths and the actual workload.
- Loading an ENTIRE comment tree (all 50,000 comments) on every page
  view "to be simple" — this is both a massive unnecessary payload for
  users who will only ever look at the top few comments, and a real
  performance/scalability liability as thread size grows.
- Using adjacency-list recursive queries for very DEEP threads without
  considering the query's cost at depth — a recursive CTE that's fast
  for a 5-level-deep thread can become meaningfully slower for genuinely
  deep nesting (some platforms cap nesting depth specifically to bound this cost).
"""


# ------------------------------------------------------------------
# 1. Adjacency list — simple, but subtree retrieval requires recursion
# ------------------------------------------------------------------
def adjacency_list_demo():
    comments = {
        1: {"text": "Great post!", "parent_id": None},
        2: {"text": "I agree", "parent_id": 1},
        3: {"text": "Same here", "parent_id": 1},
        4: {"text": "Why though?", "parent_id": 2},
        5: {"text": "Because of X", "parent_id": 4},
    }

    def get_subtree_adjacency(root_id: int, all_comments: dict) -> list[int]:
        # Requires walking the tree level by level — multiple lookups,
        # or a recursive SQL CTE in a real database
        result = [root_id]
        children = [cid for cid, c in all_comments.items() if c["parent_id"] == root_id]
        for child_id in children:
            result.extend(get_subtree_adjacency(child_id, all_comments))
        return result

    subtree = get_subtree_adjacency(1, comments)
    print(f"Adjacency list — subtree under comment 1: {subtree}")
    print("  -> Required recursively walking parent_id relationships;")
    print("     a SQL equivalent needs a recursive CTE, which can be slow at depth/scale.")


# ------------------------------------------------------------------
# 2. Materialized path — fast prefix-based subtree retrieval
# ------------------------------------------------------------------
def materialized_path_demo():
    comments = {
        1: {"text": "Great post!", "path": "1"},
        2: {"text": "I agree", "path": "1/2"},
        3: {"text": "Same here", "path": "1/3"},
        4: {"text": "Why though?", "path": "1/2/4"},
        5: {"text": "Because of X", "path": "1/2/4/5"},
    }

    def get_subtree_by_path(root_path: str, all_comments: dict) -> list[int]:
        # A SINGLE, indexable prefix match — no recursion needed at all
        return [cid for cid, c in all_comments.items() if c["path"].startswith(root_path)]

    subtree = get_subtree_by_path("1/2", comments)
    print(f"\nMaterialized path — subtree under comment 2 (path '1/2'): {subtree}")
    print("  -> A single prefix query (equivalent to a SQL 'LIKE 1/2%' with")
    print("     an appropriate index) replaces the recursive walk entirely.")


# ------------------------------------------------------------------
# 3. Lazy-loading — what Reddit actually does for very large threads
# ------------------------------------------------------------------
def lazy_loading_demo():
    print("\nLazy loading strategy for a 50,000-comment thread:")
    print("  1. Fetch only TOP-LEVEL comments, sorted by ranking (L17),")
    print("     e.g. the top 20 by score.")
    print("  2. For EACH top-level comment, fetch only its first 2-3")
    print("     immediate replies (not the full nested subtree).")
    print("  3. Render a 'Continue this thread ->' link for anything beyond")
    print("     that bounded depth/breadth, which triggers a SEPARATE,")
    print("     SCOPED fetch (using the materialized-path prefix query)")
    print("     only when a user actually clicks it.")
    print("  -> The vast majority of page views NEVER trigger a full-tree")
    print("     fetch, because most users only read the top few comments.")


if __name__ == "__main__":
    adjacency_list_demo()
    materialized_path_demo()
    lazy_loading_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A Reddit post that goes viral overnight accumulates comments faster than
almost any other write pattern the platform handles — the comment
storage layer handles this INSERT-heavy load well specifically because
it avoided a nested-set-style model (which would require expensive
re-numbering on every insert); instead, using a materialized-path-like
structure combined with bounded, lazy-loaded fetches keeps both comment
CREATION and comment RETRIEVAL fast, even as an individual thread grows
to tens of thousands of nested replies within a matter of hours.
"""
