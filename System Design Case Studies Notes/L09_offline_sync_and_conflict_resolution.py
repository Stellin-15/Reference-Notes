# ============================================================
# L09: Offline Sync and Conflict Resolution
# ============================================================
# WHAT: How a collaborative editor handles a client going OFFLINE for an
#       extended period, accumulating local edits, then reconnecting and
#       merging those edits back in — the hardest real-world stress test
#       of L06-L07's convergence guarantees.
# WHY: L06-L08 assumed clients were continuously connected. Real usage
#      (a mobile app losing signal, a laptop closing mid-edit) requires
#      handling MINUTES OR HOURS of accumulated offline edits merging
#      back into a document that may have changed substantially in the meantime.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
OFFLINE EDITING means a client continues accepting user edits locally
(updating its own local document copy immediately, for responsiveness)
while DISCONNECTED from the server/other collaborators — the accumulated
local operations must then be reconciled against whatever changes
happened on the server/other clients during that offline period once
connectivity resumes.

CRDTs (L07) HANDLE THIS NATURALLY: since CRDT operations converge
correctly regardless of the order or delay in which they're applied, a
client can buffer ANY NUMBER of local operations while offline and simply
"replay" them against the server's current state on reconnect — no
special offline-specific logic is needed BEYOND what already makes CRDTs
correct for concurrent editing in general. This is the primary practical
reason many modern offline-first collaborative apps (and the CRDT
libraries built for them, like Automerge and Yjs) favor CRDTs over OT.

OT (L06) HANDLES THIS WITH MORE DIFFICULTY: classical OT's transformation
logic assumes operations are transformed against a RELATIVELY RECENT
sequence of prior operations — an operation that's been offline for
hours may need to be transformed against a LARGE number of intervening
operations, which is more complex to implement correctly and can be more
computationally expensive than the CRDT approach, though production OT
systems (including modern versions of Google Docs' collaboration engine)
have engineered solutions for this (e.g. periodically "checkpointing" and simplifying history).

CONFLICT PRESENTATION: even with a mathematically CORRECT merge
(guaranteed by both CRDT and properly-implemented OT), the RESULT can
still be surprising or undesirable to the actual human user — two people
independently rewriting the SAME sentence while one was offline will
merge into some technically-valid but possibly nonsensical combination of
both rewrites. Some collaborative systems handle this by detecting likely
"real" conflicts (overlapping edits to the same region) and surfacing
them to the user for manual resolution (similar in spirit to a Git merge
conflict), rather than silently auto-merging in every case — a genuine
design DECISION, not purely a technical requirement, since automatic
merging is often "good enough" for character-level text edits specifically.

LOCAL-FIRST STORAGE: a well-designed offline-capable client persists its
local document state and pending operations to LOCAL storage (IndexedDB
in a browser, local disk in a native app) BEFORE attempting to sync —
this ensures that even if the app crashes or the device loses power while
offline, the user's edits aren't lost when the app is reopened, decoupling
"having made an edit" from "having successfully synced that edit."

PRODUCTION USE CASE:
A user edits a Google Doc on a flight with no WiFi for three hours,
making substantial changes — their client buffers every edit locally and
persists them to local storage continuously. On landing and reconnecting,
the client sends its buffered operations to the server, which merges them
against however the document changed (from other collaborators) during
that three-hour window — the user sees the merged result and, if it
detects genuinely overlapping edits to the same text region, may
surface a conflict indicator rather than silently picking one version.

COMMON MISTAKES:
- Buffering offline edits ONLY in memory, without persisting to local
  storage — an app crash or device restart during the offline period
  loses all unsaved work, defeating the entire purpose of offline support.
- Assuming CRDTs make ALL merge results "correct" in the sense a human
  would want — CRDTs guarantee STRUCTURAL convergence (all replicas reach
  the same state), not that the merged result is SEMANTICALLY sensible;
  a system may still need conflict surfacing for genuinely overlapping edits.
- Implementing offline support for OT without a strategy for handling
  LONG offline periods — transforming a single operation against
  thousands of intervening operations naively can become a genuine
  performance problem; production OT systems need explicit strategies
  (checkpointing, operation compaction) for this case.
"""

import time


# ------------------------------------------------------------------
# 1. Local-first buffering — persisting edits before syncing
# ------------------------------------------------------------------
class OfflineCapableClient:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.local_document = "Hello world"
        self.pending_operations: list[dict] = []
        self.connected = True

    def local_persistent_storage(self) -> dict:
        # In a real client, this writes to IndexedDB/local disk —
        # simulated here as a plain dict "as if" persisted
        return {"document": self.local_document, "pending_ops": self.pending_operations}

    def go_offline(self):
        self.connected = False
        print(f"[{self.client_id}] Went OFFLINE — will buffer edits locally.")

    def make_edit(self, operation: dict):
        # Apply LOCALLY immediately (for responsiveness), regardless of
        # connectivity — this is what makes the app feel instant even offline
        if operation["type"] == "insert":
            pos, text = operation["pos"], operation["text"]
            self.local_document = self.local_document[:pos] + text + self.local_document[pos:]

        self.pending_operations.append(operation)
        # CRITICAL: persist to LOCAL storage immediately, not just memory —
        # protects against a crash/restart during the offline period
        self.local_persistent_storage()
        print(f"[{self.client_id}] Local edit applied AND persisted: '{self.local_document}'")

    def reconnect_and_sync(self, server_operations_since_disconnect: list[dict]):
        self.connected = True
        print(f"\n[{self.client_id}] Reconnected. Syncing "
              f"{len(self.pending_operations)} local ops against "
              f"{len(server_operations_since_disconnect)} server-side ops "
              f"that happened while offline.")
        # With a CRDT (L07), this merge is a straightforward, order-independent
        # apply of both operation sets — no special "long offline period" logic needed
        return self.pending_operations, server_operations_since_disconnect


def offline_sync_demo():
    client = OfflineCapableClient("mobile_client")
    client.go_offline()

    # User keeps editing while offline — each edit is applied locally
    # AND persisted immediately, never waiting on network connectivity
    client.make_edit({"type": "insert", "pos": 5, "text": ", dear"})
    client.make_edit({"type": "insert", "pos": 0, "text": "Oh! "})

    # Meanwhile, another collaborator made edits on the server side
    server_side_operations = [
        {"type": "insert", "pos": 11, "text": "wonderful "},
    ]

    pending, server_ops = client.reconnect_and_sync(server_side_operations)
    print(f"Local pending operations to send: {pending}")
    print(f"Server operations to merge in: {server_ops}")
    print("  -> With a CRDT, both operation sets merge deterministically")
    print("     regardless of the 3-hour (or 3-second) gap between them —")
    print("     the OFFLINE DURATION itself doesn't change the merge logic.")


if __name__ == "__main__":
    offline_sync_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A note-taking app built offline-first (many are built on Automerge or
Yjs specifically for this reason) lets a user take extensive notes during
an international flight with zero connectivity — every keystroke is
applied to the local CRDT document and persisted to local storage
instantly, giving a fully responsive editing experience despite total
disconnection. On landing, the app silently syncs the accumulated hours
of local edits against the server (and any edits made by collaborators
during that window) with no special "long offline merge" code path
required beyond the CRDT's normal operation — the SAME merge logic that
handles two people editing 200 milliseconds apart also correctly handles
edits three hours apart.
"""
