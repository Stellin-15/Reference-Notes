# ============================================================
# L06: Operational Transform Fundamentals — How Google Docs Merges Edits
# ============================================================
# WHAT: Operational Transform (OT) — the original algorithmic approach
#       (predating CRDTs, L07) to letting multiple people edit the SAME
#       document simultaneously without their changes conflicting or
#       corrupting the document.
# WHY: This starts a new case study: Google Docs' real-time collaborative
#      editing. Unlike L01-L05's video-call mechanics, this is fundamentally
#      a DATA CONSISTENCY problem — how do you reconcile two people's
#      simultaneous, conflicting edits into ONE correct final document?
# LEVEL: Foundation (of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
When two users edit the SAME document simultaneously, their edits are
generated against what EACH user's client believes is the current
document state — but by the time either edit reaches the server, the
document may have already changed (due to the OTHER user's edit arriving
first). Naively applying both edits in the order received can produce a
CORRUPTED result — e.g. if User A deletes character at position 5 and
User B simultaneously inserts a character at position 3, applying A's
delete AFTER B's insert without adjustment deletes the WRONG character,
since B's insert shifted every subsequent position by one.

OPERATIONAL TRANSFORM (OT) solves this by TRANSFORMING one operation
against another CONCURRENT operation before applying it — given two
operations that were both generated against the SAME base document
state, OT computes an adjusted version of one operation that accounts
for the effect the other operation already had, such that applying both
(in either order, after transformation) converges to the SAME final
document on every client. This property — all clients converge to an
identical document regardless of the order operations happen to arrive
in — is the core correctness guarantee OT (and CRDTs, L07) must provide.

A CENTRAL SERVER is required in the classic OT architecture: the server
maintains the "canonical" sequence of operations and transforms each
incoming operation against every operation that's happened since the
client's LAST KNOWN state before broadcasting the transformed operation
to all other clients — this centralization is what makes classic OT
implementations (as used in the original Google Docs / Google Wave)
comparatively straightforward to reason about, at the cost of requiring
that central coordination point (a genuine constraint for OFFLINE editing,
which L09 addresses).

OT OPERATIONS are typically expressed as a small set of primitives:
INSERT(position, text), DELETE(position, length), and sometimes
RETAIN(length) (skip forward without changing anything, used to compose
operations that only touch part of a document) — transforming two
operations against each other means adjusting their POSITION arguments
based on what the other operation did.

PRODUCTION USE CASE:
Two Google Docs users, both starting from a document reading "Hello
world", simultaneously make edits: User A inserts "there " at position 6
(producing "Hello there world"), while User B deletes "world" (positions
6-11) based on the ORIGINAL text. Without transformation, applying B's
delete using its ORIGINAL positions against the document that now
contains A's insert would delete the wrong text ("there " instead of
"world") — OT transforms B's delete operation to account for A's insert
having shifted everything after position 6, correctly targeting the
NEW position of "world" instead.

COMMON MISTAKES:
- Assuming operations can be applied in whatever order they happen to
  arrive at the server, without transformation — this is EXACTLY the bug
  scenario above: positions computed against an outdated document state
  silently corrupt the document when applied to the current, different state.
- Implementing OT transformation logic that isn't provably correct for
  EVERY possible pair/ordering of concurrent operations — OT's
  transformation functions have famously subtle edge cases (multiple
  concurrent inserts at the exact same position, nested delete/insert
  interactions); a transformation function that's "mostly correct" can
  still silently diverge client document states in rare cases, which is
  precisely why CRDTs (L07) have become popular as an alternative with different correctness tradeoffs.
- Building OT without a clear, authoritative CENTRAL ordering of
  operations — without a server-side canonical sequence to transform
  against, clients have no consistent reference point to transform their
  own pending operations against, risking permanent divergence.
"""

import copy


# ------------------------------------------------------------------
# 1. The naive (broken) approach — applying edits without transformation
# ------------------------------------------------------------------
def naive_apply_without_transform():
    original = "Hello world"
    print(f"Original document: '{original}'")

    # User A inserts "there " at position 6
    doc_after_a = original[:6] + "there " + original[6:]
    print(f"After User A's insert: '{doc_after_a}'")

    # User B's delete operation was computed against the ORIGINAL document
    # (delete positions 6-11, which was "world" in the ORIGINAL text)
    # Applying it directly to doc_after_a (which has shifted) is WRONG:
    broken_result = doc_after_a[:6] + doc_after_a[11:]
    print(f"Naively applying B's delete(6,11) to the NEW document: '{broken_result}'")
    print("  -> WRONG — this deleted 'there ' instead of 'world', because")
    print("     B's positions were computed against the OLD document.")


# ------------------------------------------------------------------
# 2. Operational Transform — correctly adjusting positions
# ------------------------------------------------------------------
def transform_delete_against_insert(delete_start: int, delete_end: int,
                                     insert_pos: int, insert_len: int) -> tuple[int, int]:
    """Adjust a delete operation's positions to account for a concurrent insert."""
    if insert_pos <= delete_start:
        # The insert happened BEFORE the delete's range — shift both bounds forward
        return delete_start + insert_len, delete_end + insert_len
    elif insert_pos >= delete_end:
        # The insert happened AFTER the delete's range — no adjustment needed
        return delete_start, delete_end
    else:
        # The insert happened INSIDE the delete's range — extend the delete
        # to also cover the newly inserted text (a real OT edge case)
        return delete_start, delete_end + insert_len


def correct_ot_demo():
    original = "Hello world"
    print(f"Original document: '{original}'")

    # User A's operation: insert "there " at position 6
    insert_pos, insert_text = 6, "there "
    doc_after_a = original[:insert_pos] + insert_text + original[insert_pos:]
    print(f"After User A's insert: '{doc_after_a}'")

    # User B's operation, as ORIGINALLY authored: delete(6, 11) -> "world"
    original_delete_start, original_delete_end = 6, 11

    # TRANSFORM B's delete against A's concurrent insert
    new_start, new_end = transform_delete_against_insert(
        original_delete_start, original_delete_end, insert_pos, len(insert_text)
    )
    print(f"B's delete transformed: ({original_delete_start},{original_delete_end}) "
          f"-> ({new_start},{new_end})")

    correct_result = doc_after_a[:new_start] + doc_after_a[new_end:]
    print(f"Applying the TRANSFORMED delete: '{correct_result}'")
    print("  -> CORRECT — 'world' is removed, 'there ' is preserved, and this")
    print("     is the SAME result regardless of which operation the server")
    print("     happened to receive/process first.")


if __name__ == "__main__":
    naive_apply_without_transform()
    print()
    correct_ot_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Google Docs' original real-time collaboration engine used a
server-centric OT implementation: every keystroke is sent to the server
as a small operation, the server transforms it against any operations
that occurred concurrently (from other editors) since the client's last
sync point, and broadcasts the transformed operation to all other
connected clients — this is why, in practice, simultaneous edits by
multiple people in the same paragraph of a Google Doc reliably converge
to the same correct text on everyone's screen, even though each person's
keystrokes were generated independently against a slightly different
view of the document at the moment they typed.
"""
