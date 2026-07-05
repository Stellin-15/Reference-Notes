# ============================================================
# L08: Presence, Cursors, and Awareness — The "Who's Here" Layer
# ============================================================
# WHAT: The EPHEMERAL, non-document-content real-time state a
#       collaborative editor tracks — who's currently viewing/editing,
#       where their cursor/selection is, and how this differs
#       architecturally from the actual document content (L06-L07).
# WHY: L06-L07 covered making CONCURRENT DOCUMENT EDITS converge
#      correctly. Presence/cursor data is a DIFFERENT category of data
#      with different requirements — it's fine to lose it on
#      disconnect, but it needs to update with much lower latency than
#      document persistence requires.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
PRESENCE/AWARENESS data (who's currently in the document, their cursor
position, their current selection, their name/avatar color) is
fundamentally EPHEMERAL — unlike the document content itself, there's no
need to durably persist "User X's cursor was at position 47 three days
ago." This has a major architectural consequence: presence data does NOT
need the strong CONVERGENCE guarantees L06-L07 built for document content
— if a cursor-position update is dropped or arrives out of order, the
worst outcome is a momentarily stale cursor indicator, not silent
document corruption. This lets presence updates use a SIMPLER, LOWER-
OVERHEAD transport (e.g. "just broadcast the latest position, discard
anything older that arrives late" — a last-write-wins semantics that
would be UNACCEPTABLE for document content but is entirely fine for a cursor).

SEPARATE CHANNEL / SEPARATE DATA STRUCTURE: production collaborative
editors (Yjs's "Awareness" protocol is a widely-used concrete example)
deliberately keep presence state STRUCTURALLY SEPARATE from the CRDT/OT
document state — presence is typically a simple, frequently-overwritten
key-value map per connected client (client ID -> {cursor position,
selection range, user color, last-seen timestamp}), broadcast at a
higher frequency and with much looser consistency requirements than
document operations.

HEARTBEAT / TIMEOUT-BASED PRESENCE CLEANUP: since presence is ephemeral
and tied to an active connection, a client that disconnects
UNGRACEFULLY (a crashed tab, a lost network connection with no clean
close event) needs its presence entry removed WITHOUT an explicit
"I'm leaving" message — this is done via a HEARTBEAT: each active client
periodically re-broadcasts its presence, and a server/peer treats any
client whose last update exceeds a timeout threshold (e.g. 30 seconds) as
disconnected, removing their cursor/presence indicator.

CURSOR POSITION IN A CHANGING DOCUMENT is a genuinely subtle problem: a
cursor is naturally expressed as a position (e.g. "character 47"), but
document edits (L06-L07) constantly shift what "character 47" refers to
— exactly like L06's OT position-transformation problem, but applied to
cursor positions rather than edit operations. The correct approach
anchors a cursor to the SAME stable identity mechanism the underlying
CRDT (L07) uses for characters (or an equivalent transform for OT-based
systems, per L06), so a cursor visually "sticks" to the correct character
even as other users insert/delete text before or after it.

PRODUCTION USE CASE:
Google Docs displays each collaborator's cursor as a colored flag with
their name, updating in near real-time as they type or click elsewhere —
this presence data is broadcast over a lightweight channel completely
separate from the actual text-edit operations, is never persisted to the
document's saved history, and automatically disappears within seconds of
a collaborator closing their tab or losing connection, detected via
heartbeat timeout rather than requiring an explicit disconnect signal.

COMMON MISTAKES:
- Routing presence/cursor updates through the SAME strongly-consistent
  pipeline as document content edits — this adds unnecessary latency and
  complexity for data that doesn't need those correctness guarantees,
  and can even create needless contention with actual document-editing throughput.
- Relying on an explicit "user disconnected" message to clean up presence
  state — ungraceful disconnects (crashes, network loss) never SEND such
  a message; a heartbeat-and-timeout mechanism is required to handle this
  common real-world case, not just the graceful-disconnect happy path.
- Representing cursor position as a raw character INDEX without anchoring
  it to a stable identity (CRDT character ID, or an OT-transformed
  position) — this causes a visible cursor to "jump" to the wrong
  location whenever another collaborator edits text before the cursor's
  position, a jarring and confusing user experience.
"""

import time


# ------------------------------------------------------------------
# 1. Presence as a simple, separate key-value structure
# ------------------------------------------------------------------
class PresenceStore:
    def __init__(self, timeout_seconds: float = 30.0):
        self.clients: dict[str, dict] = {}
        self.timeout_seconds = timeout_seconds

    def update_presence(self, client_id: str, cursor_anchor_id: str, user_name: str, color: str):
        # A simple OVERWRITE — no transformation/merging logic needed,
        # unlike document content operations (L06-L07)
        self.clients[client_id] = {
            "cursor_anchor_id": cursor_anchor_id,   # anchored to a STABLE character ID
            "user_name": user_name,
            "color": color,
            "last_heartbeat": time.time(),
        }

    def prune_stale_clients(self):
        now = time.time()
        stale = [cid for cid, data in self.clients.items()
                 if now - data["last_heartbeat"] > self.timeout_seconds]
        for cid in stale:
            del self.clients[cid]
        return stale

    def active_clients(self) -> dict:
        return self.clients


def presence_demo():
    store = PresenceStore(timeout_seconds=5.0)
    store.update_presence("client_1", cursor_anchor_id="char_id_47", user_name="Alice", color="#FF5733")
    store.update_presence("client_2", cursor_anchor_id="char_id_12", user_name="Bob", color="#33A1FF")

    print("Active presence after both clients connect:")
    for cid, data in store.active_clients().items():
        print(f"  {cid}: {data['user_name']} (cursor anchored to {data['cursor_anchor_id']})")

    # Simulate client_2 disconnecting UNGRACEFULLY (no explicit leave message) —
    # its heartbeat simply stops arriving
    print("\n(client_2 crashes — no disconnect message sent; time passes...)")
    store.clients["client_2"]["last_heartbeat"] -= 10   # simulate 10s since last heartbeat

    stale = store.prune_stale_clients()
    print(f"Pruned stale clients (heartbeat timeout exceeded): {stale}")
    print(f"Remaining active presence: {list(store.active_clients().keys())}")


# ------------------------------------------------------------------
# 2. Cursor anchoring — stable identity vs raw position
# ------------------------------------------------------------------
def cursor_anchoring_demo():
    print("Document: 'Hello world' — Alice's cursor is right before 'world' "
          "(anchored to that character's STABLE id, not raw index 6)\n")

    document_chars = [
        {"char": "H", "id": "id_1"}, {"char": "e", "id": "id_2"},
        {"char": "l", "id": "id_3"}, {"char": "l", "id": "id_4"},
        {"char": "o", "id": "id_5"}, {"char": " ", "id": "id_6"},
        {"char": "w", "id": "id_7"}, {"char": "o", "id": "id_8"},
        {"char": "r", "id": "id_9"}, {"char": "l", "id": "id_10"},
        {"char": "d", "id": "id_11"},
    ]
    alice_cursor_anchor = "id_7"   # anchored to 'w' in "world"

    def render_with_cursor(chars, anchor_id):
        result = ""
        for c in chars:
            if c["id"] == anchor_id:
                result += "|"   # cursor marker
            result += c["char"]
        return result

    print(f"Before Bob's edit: '{render_with_cursor(document_chars, alice_cursor_anchor)}'")

    # Bob inserts "there " BEFORE Alice's cursor position — using stable
    # IDs (L07's CRDT approach), Alice's cursor correctly STAYS anchored
    # to 'w', regardless of how many characters shifted before it
    insert_index = 6
    for i, ch in enumerate(" there "):
        document_chars.insert(insert_index + i, {"char": ch, "id": f"bob_id_{i}"})

    print(f"After Bob inserts ' there ' before it: "
          f"'{render_with_cursor(document_chars, alice_cursor_anchor)}'")
    print("  -> Alice's cursor correctly STAYS anchored to 'w' in 'world' — ")
    print("     if it had been stored as raw index 6, it would now incorrectly")
    print("     point into the middle of Bob's newly inserted text instead.")


if __name__ == "__main__":
    presence_demo()
    print()
    cursor_anchoring_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
In a Google Docs session with five active collaborators, each person's
cursor flag updates smoothly in real time as they move around the
document — this presence layer runs entirely independently of the
document's actual save/sync pipeline (L06's OT or L07's CRDT operations),
uses simple heartbeat-based cleanup so a collaborator's cursor
disappears within seconds of them closing their laptop lid without any
special disconnect handling, and keeps every cursor correctly anchored
to its intended character even as other collaborators simultaneously
insert and delete text throughout the document.
"""
