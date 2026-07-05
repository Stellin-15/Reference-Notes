# ============================================================
# L10: Version History and Document Storage — The Capstone of the Docs Case Study
# ============================================================
# WHAT: How a collaborative editor stores a document's FULL EDIT HISTORY
#       efficiently (not just its current state), enabling features like
#       "see version history" and "restore to an earlier version" — and
#       how this ties L06-L09's real-time mechanics to durable storage.
# WHY: Capstone lesson for this case study — L06-L09 covered the
#      real-time editing mechanics; this lesson covers what happens to
#      all those operations AFTER the fact, wiring the case study into
#      a complete, storable, recoverable system.
# LEVEL: Advanced (capstone of this case study)
# ============================================================

"""
CONCEPT OVERVIEW:
STORING EVERY OPERATION vs STORING SNAPSHOTS is the central storage
design decision: a naive approach might store only the document's
CURRENT state, discarding the edit history entirely once applied — this
is storage-efficient but makes "view version history" or "restore to
yesterday's version" impossible without additional infrastructure. The
alternative — storing every OT operation (L06) or CRDT operation (L07)
ever applied, in order — enables full history reconstruction (replay
operations up to any point in time) at the cost of steadily GROWING
storage as edit history accumulates, particularly for long-lived,
heavily-edited documents.

PERIODIC SNAPSHOTTING is the standard resolution to this tradeoff:
periodically (e.g. every N operations, or every few minutes of active
editing) persist a full SNAPSHOT of the current document state, while
CONTINUING to store the operation log since the last snapshot. Restoring
or replaying to any point in time then only requires: load the nearest
PRECEDING snapshot, then replay the (much smaller) set of operations
between that snapshot and the target point — dramatically faster than
replaying a document's ENTIRE lifetime of operations from the very
beginning every time.

NAMED VERSIONS (e.g. Google Docs' "Name current version" feature) are a
USER-FACING concept layered on top of the underlying operation log —
technically, a named version is often just a POINTER to a specific
position in the operation log (or a specific snapshot), not a separately
stored full copy of the document — this is both storage-efficient and
lets the "restore to this version" action be implemented as "replay up
to this log position," reusing the SAME replay mechanism used for
general history browsing.

COMPACTION addresses a related but distinct problem from L07's tombstone
garbage collection: over a document's lifetime, the RAW operation log
can contain enormous numbers of tiny operations (every individual
keystroke, historically) — compaction periodically MERGES sequences of
operations that are no longer independently meaningful (e.g. collapsing
"insert H", "insert e", "insert l", "insert l", "insert o" into a single
"insert Hello" operation) once enough time has passed that fine-grained,
per-keystroke undo/history at that level is no longer useful — reducing
both storage size and the cost of replaying history from further back.

PRODUCTION USE CASE:
Google Docs' "Version history" feature lets a user browse a timeline of
named/automatic checkpoints and preview the document as it looked at any
of them — under the hood, this is implemented by storing periodic
snapshots plus the full operation log between them, with "restore this
version" simply replaying operations up to the selected point and
saving THAT as the new current state (itself becoming a new entry in the
ongoing operation log, preserving full history rather than deleting
anything that came after).

COMMON MISTAKES:
- Storing ONLY the current document state with no operation log at all —
  this makes version history, collaborative-editing audit trails, and
  point-in-time recovery entirely impossible after the fact, a
  significant feature and reliability gap discovered too late if not
  planned for from the start.
- Never snapshotting, relying purely on replaying the ENTIRE operation
  log from the very beginning every time a document is opened or a
  historical version is viewed — this becomes progressively, noticeably
  slower as a document accumulates months/years of edit history,
  eventually becoming a genuine performance/scalability problem.
- Treating "restore to an earlier version" as literally deleting
  everything that happened after that point — the correct approach
  (used by Google Docs and Git alike) treats a restore as a NEW forward
  operation that recreates the old state, preserving the FULL history
  including the fact that a restore happened, rather than destructively
  discarding the intervening history.
"""

import time


# ------------------------------------------------------------------
# 1. Operation log + periodic snapshotting
# ------------------------------------------------------------------
class VersionedDocument:
    def __init__(self, snapshot_interval: int = 5):
        self.operation_log: list[dict] = []
        self.snapshots: list[dict] = []   # each: {"at_op_index": int, "state": str, "timestamp": float}
        self.snapshot_interval = snapshot_interval
        self.current_state = ""

    def apply_operation(self, operation: dict):
        if operation["type"] == "insert":
            pos, text = operation["pos"], operation["text"]
            self.current_state = self.current_state[:pos] + text + self.current_state[pos:]
        self.operation_log.append(operation)

        # Snapshot periodically, not on every single operation
        if len(self.operation_log) % self.snapshot_interval == 0:
            self.snapshots.append({
                "at_op_index": len(self.operation_log),
                "state": self.current_state,
                "timestamp": time.time(),
            })

    def restore_to_op_index(self, target_index: int) -> str:
        # Find the NEAREST preceding snapshot, rather than replaying from op 0
        nearest_snapshot = None
        for snap in self.snapshots:
            if snap["at_op_index"] <= target_index:
                nearest_snapshot = snap
            else:
                break

        if nearest_snapshot:
            state = nearest_snapshot["state"]
            start_index = nearest_snapshot["at_op_index"]
        else:
            state = ""
            start_index = 0

        # Replay only the operations BETWEEN the snapshot and the target —
        # a MUCH smaller replay than starting from the document's beginning
        ops_to_replay = self.operation_log[start_index:target_index]
        for op in ops_to_replay:
            if op["type"] == "insert":
                pos, text = op["pos"], op["text"]
                state = state[:pos] + text + state[pos:]

        print(f"  Restored to op index {target_index}: used snapshot at "
              f"index {start_index if nearest_snapshot else 0}, "
              f"replayed {len(ops_to_replay)} operations (not all "
              f"{target_index} from the beginning)")
        return state


def version_history_demo():
    doc = VersionedDocument(snapshot_interval=3)
    edits = [
        {"type": "insert", "pos": 0, "text": "H"},
        {"type": "insert", "pos": 1, "text": "e"},
        {"type": "insert", "pos": 2, "text": "llo"},   # snapshot taken here (op 3)
        {"type": "insert", "pos": 5, "text": " world"},
        {"type": "insert", "pos": 11, "text": "!"},
        {"type": "insert", "pos": 12, "text": " Nice to meet you."},  # snapshot here (op 6)
    ]
    for edit in edits:
        doc.apply_operation(edit)

    print(f"Final document: '{doc.current_state}'")
    print(f"Snapshots taken at operation indices: {[s['at_op_index'] for s in doc.snapshots]}\n")

    print("Restoring to an earlier point in history (after operation 4):")
    restored_state = doc.restore_to_op_index(4)
    print(f"  Document at that point was: '{restored_state}'")


if __name__ == "__main__":
    version_history_demo()

"""
FINAL CONTEXT (capstone of the Google Docs case study):
The full architecture this case study builds, end to end: L06 (OT) or
L07 (CRDT) ensures concurrent edits from multiple users converge
correctly; L08 layers ephemeral presence/cursor data on top without
touching the document's consistency guarantees; L09 extends the SAME
convergence guarantees to handle clients that were offline for extended
periods; and this lesson (L10) wires the resulting stream of operations
into DURABLE storage — periodic snapshots plus an append-only operation
log — that supports version history, point-in-time restore, and
efficient document loading, all without ever needing to replay a
document's entire lifetime of edits from scratch. This is, in outline,
the real architecture underneath Google Docs' collaborative editing feature.
"""
