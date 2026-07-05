# ============================================================
# L07: CRDTs for Collaborative Editing — The Modern Alternative to OT
# ============================================================
# WHAT: Conflict-free Replicated Data Types (CRDTs) — a fundamentally
#       different approach to the SAME problem L06's OT solves, with a
#       key structural advantage: no central server is required for
#       correctness.
# WHY: L06 covered OT's server-dependent approach. Many modern
#      collaborative editors (Figma, Notion's underlying tech, and
#      increasingly newer Google Docs-like tools) use CRDTs instead —
#      this lesson covers WHY, and the real tradeoffs between the two approaches.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
A CRDT (Conflict-free Replicated Data Type) is a data structure
specifically designed so that ANY set of concurrent operations, applied
in ANY order, on ANY replica, converges to the SAME final state — without
requiring a central server to determine a canonical operation order (L06's
OT fundamentally NEEDS that central ordering to transform against). This
property is called STRONG EVENTUAL CONSISTENCY.

For TEXT editing specifically, a common CRDT approach gives every
character a UNIQUE, IMMUTABLE, TOTALLY-ORDERABLE IDENTIFIER when it's
inserted — rather than tracking POSITIONS (which shift as the document
changes, exactly the problem OT's transformation logic exists to handle),
each character "knows" its own permanent place in the document's logical
ordering relative to its neighbors at insertion time. Common schemes
include RGA (Replicated Growable Array) and various "sequence CRDTs" (e.g.
Logoot, Treedoc) — each with different strategies for generating these
stable identifiers efficiently. DELETING a character in most text CRDTs
doesn't actually remove it from the underlying data structure — it marks
it as a TOMBSTONE (a deleted-but-still-present marker), because other
replicas may still reference that character's identifier in operations
that haven't arrived yet; permanently removing it too early could break
convergence for a concurrent operation still in flight.

NO CENTRAL SERVER REQUIRED (for correctness — a server may still be
used for other reasons, like message relay or persistence) is the
structural advantage over OT: since each replica can independently apply
operations in ANY order and still converge, CRDTs are a NATURAL fit for
OFFLINE-FIRST editing (L09) — a client can accumulate edits while
disconnected and merge them in whenever reconnected, with NO risk of the
kind of divergence that OT's central-ordering dependency is specifically designed to prevent.

THE TRADEOFF: CRDTs typically have HIGHER memory/storage overhead than
OT — tombstones accumulate over a document's lifetime (though periodic
GARBAGE COLLECTION of tombstones that are provably safe to remove
mitigates this), and the unique-identifier metadata per character is
larger than OT's simple position-based operations. OT, in exchange for
requiring central coordination, can be more memory-efficient and was
historically easier to reason about for SIMPLE, common cases — though
CRDT tooling (e.g. Yjs, Automerge) has matured significantly, narrowing this gap in practice.

PRODUCTION USE CASE:
A collaborative document editor built for offline-first mobile use (users
frequently lose connectivity) uses a CRDT (e.g. via the Yjs library)
specifically because it doesn't require a live connection to a central
transformation server to remain CORRECT — each user's device can buffer
local edits while offline and merge seamlessly once reconnected, with the
CRDT's mathematical convergence guarantee ensuring the merged document is
identical regardless of how long any individual device was offline or
what order reconnections happen in.

COMMON MISTAKES:
- Assuming CRDTs eliminate the need for ANY server — a server is still
  commonly used for relaying operations between clients and persisting
  document state durably; the CRDT property is specifically about not
  needing that server to perform CENTRAL TRANSFORMATION LOGIC for correctness.
- Never garbage-collecting tombstones — an editor with years of edit
  history can accumulate enormous numbers of tombstoned (deleted)
  characters if none are ever safely removed, growing document size and
  memory usage unboundedly; production CRDT implementations need a
  strategy for safely reclaiming tombstones once it's provable no
  in-flight operation still references them.
- Choosing a CRDT library/scheme without benchmarking its actual memory
  overhead for the target document sizes — different CRDT sequence
  algorithms (RGA, Logoot, Treedoc, and newer approaches) have genuinely
  different memory/performance tradeoffs, and this choice matters more
  as document size and edit-history length grow.
"""

import uuid


# ------------------------------------------------------------------
# 1. A simplified sequence CRDT — unique, ordered character identifiers
# ------------------------------------------------------------------
class CRDTCharacter:
    def __init__(self, char: str, char_id: str, deleted: bool = False):
        self.char = char
        self.char_id = char_id   # a globally unique, sortable identifier
        self.deleted = deleted   # tombstone flag, NOT actual removal


class SimpleSequenceCRDT:
    """A drastically simplified illustration — real implementations (RGA,
    Logoot, Yjs) use more sophisticated identifier-generation schemes for
    efficiency, but the CORE idea (stable per-character IDs, tombstones
    instead of true deletion) is the same."""

    def __init__(self):
        self.characters: list[CRDTCharacter] = []

    def insert(self, index: int, char: str) -> CRDTCharacter:
        new_char = CRDTCharacter(char, char_id=str(uuid.uuid4())[:8])
        self.characters.insert(index, new_char)
        return new_char

    def delete_by_id(self, char_id: str):
        # Mark as a TOMBSTONE rather than removing — other concurrent
        # operations may still reference this character's ID
        for c in self.characters:
            if c.char_id == char_id:
                c.deleted = True
                return

    def render(self) -> str:
        return "".join(c.char for c in self.characters if not c.deleted)


def crdt_convergence_demo():
    print("Simulating two replicas starting from 'Hello world', both")
    print("concurrently editing WITHOUT any central coordination:\n")

    # Both replicas start from the same initial state
    replica_a = SimpleSequenceCRDT()
    replica_b = SimpleSequenceCRDT()
    for ch in "Hello world":
        char_obj_a = replica_a.insert(len(replica_a.characters), ch)
        char_obj_b = CRDTCharacter(ch, char_obj_a.char_id)   # SAME id on both replicas
        replica_b.characters.append(char_obj_b)

    print(f"Replica A initial: '{replica_a.render()}'")
    print(f"Replica B initial: '{replica_b.render()}'")

    # Find the "world" characters' IDs on replica B, to simulate deleting them
    world_ids = [c.char_id for c in replica_b.characters[-5:]]

    # Replica A inserts "there " at index 6, independently
    for i, ch in enumerate(" there "):
        replica_a.insert(6 + i, ch)

    # Replica B deletes "world" by ID (NOT by position — this is the key
    # difference from OT: the operation targets a stable IDENTITY, not a
    # position that could have shifted due to a concurrent operation)
    for char_id in world_ids:
        replica_b.delete_by_id(char_id)

    print(f"\nReplica A after local insert: '{replica_a.render()}'")
    print(f"Replica B after local delete: '{replica_b.render()}'")

    # MERGE: apply A's inserts to B, and B's deletes to A — order doesn't matter
    for c in replica_a.characters:
        if c.char_id not in [existing.char_id for existing in replica_b.characters]:
            insert_pos = [existing.char_id for existing in replica_a.characters].index(c.char_id)
            replica_b.characters.insert(insert_pos, c)
    for char_id in world_ids:
        replica_a.delete_by_id(char_id)

    print(f"\nAfter merging both directions:")
    print(f"  Replica A converged to: '{replica_a.render()}'")
    print(f"  Replica B converged to: '{replica_b.render()}'")
    print("  -> Both replicas reach the SAME final state, with NO central")
    print("     server ever transforming operations against each other —")
    print("     each operation targeted a stable character IDENTITY, not a position.")


if __name__ == "__main__":
    crdt_convergence_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
Figma's real-time multiplayer canvas (a widely-cited real-world CRDT use
case, conceptually similar to text-editing CRDTs but applied to design-
object properties) allows multiple designers to edit the SAME file
simultaneously, including briefly going offline (a laptop sleeping, a
flaky connection) without losing edits or corrupting the file — each
client's local edits are CRDT operations that merge deterministically
once connectivity resumes, entirely avoiding the need for a Google-Docs-
style central OT transformation server to remain the single source of
truth for conflict resolution.
"""
