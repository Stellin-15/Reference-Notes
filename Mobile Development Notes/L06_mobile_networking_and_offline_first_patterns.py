# ============================================================
# L06: Mobile Networking and Offline-First Patterns in Depth
# ============================================================
# WHAT: The concrete PATTERNS for building genuinely offline-capable
#       mobile apps — local-first data storage, sync queues, conflict
#       resolution on reconnection, and efficient network usage
#       specifically for mobile's constrained, intermittent connectivity.
# WHY: L01 introduced offline-first as a foundational mobile expectation.
#      This lesson covers the ACTUAL implementation patterns — directly
#      building on this repo's System Design Case Studies Notes L09's
#      offline-sync coverage, applied specifically to the mobile context.
# LEVEL: Advanced
# ============================================================

"""
CONCEPT OVERVIEW:
LOCAL-FIRST DATA STORAGE means the mobile app's LOCAL DATABASE (SQLite,
Realm, or a platform-specific local store) is treated as the PRIMARY
source of truth for the UI — the UI reads from and writes to LOCAL
storage IMMEDIATELY, with network synchronization happening
SEPARATELY, asynchronously, in the background — this is the SAME
underlying principle this repo's System Design Case Studies Notes L09
covered for collaborative editing, applied here as essentially the
DEFAULT architecture for ANY mobile app wanting good perceived
performance and offline resilience, not just for collaborative editing specifically.

THE SYNC QUEUE PATTERN: rather than the app attempting a network call
IMMEDIATELY for every user action (which fails or hangs when offline),
actions that need to reach the server are appended to a PERSISTENT LOCAL
QUEUE — a background process attempts to drain this queue whenever
connectivity is available, retrying failed items with backoff, and
PERSISTING the queue itself to local storage so pending actions SURVIVE
an app restart or the OS terminating the app mid-sync (per L01's app
lifecycle coverage) — this is architecturally similar to this repo's
Distributed Systems Theory Notes' partial-failure handling, applied at
the scale of a single device's pending operations rather than a
distributed cluster's.

CONFLICT RESOLUTION ON RECONNECTION faces the SAME fundamental challenge
this repo's System Design Case Studies Notes L07/L09 (CRDTs, offline
sync for Docs) and Distributed Systems Theory Notes L05 (vector clocks)
covered — a mobile app that was offline for hours may have LOCAL changes
that CONFLICT with changes made elsewhere (a different device, a web
client) during that same window. Simple mobile apps often use
LAST-WRITE-WINS (accepting the risk of losing a conflicting change) for
low-stakes data; more sophisticated apps apply the SAME vector-clock or
CRDT-based techniques covered elsewhere in this repo for genuinely
important data where silently discarding a conflicting change would be unacceptable.

EFFICIENT NETWORK USAGE ON MOBILE requires specific consideration beyond
general API design: BATCHING multiple small requests into fewer, larger
ones reduces the PER-REQUEST OVERHEAD that's proportionally more costly
on higher-latency mobile networks; DELTA SYNC (transferring only WHAT
CHANGED since the last successful sync, rather than the full dataset
every time) significantly reduces both data usage (a real cost concern
for users on metered mobile data plans) and battery drain (radio usage
is one of the most significant battery consumers on mobile devices);
and RESPECTING THE DEVICE'S CURRENT NETWORK TYPE (deferring
large, non-urgent syncs until WiFi is available rather than using
cellular data indiscriminately) is a real, user-respecting design consideration.

PRODUCTION USE CASE:
A field-service mobile app used by technicians working in areas with
unreliable connectivity (basements, rural sites) lets technicians
complete full work orders (photos, notes, checklists) entirely OFFLINE
— all changes are written to local SQLite immediately and queued for
sync — once connectivity resumes (often hours later, back at the
technician's vehicle or office), the sync queue drains automatically in
the background, uploading photos and data in the background using
delta sync to minimize data usage, with the technician never having
been blocked from completing their work by the lack of connectivity in the field.

COMMON MISTAKES:
- Attempting network calls SYNCHRONOUSLY, blocking the UI while waiting
  for a response that may never arrive (poor/no connectivity) — this
  produces exactly the frozen, unresponsive experience mobile users
  find least tolerable, and directly connects to L01's OS-imposed
  "Application Not Responding" risk for blocked main threads.
- Losing QUEUED, not-yet-synced actions if the app is terminated by the
  OS before syncing completes — the sync queue itself MUST be
  persisted to durable local storage, not held only in memory, per L01's
  coverage of unpredictable app termination.
- Re-transferring the FULL dataset on every sync rather than using delta
  sync — this wastes both the user's mobile data allowance and battery
  life unnecessarily, a real, measurable cost to actual users that a
  web application's typically-unmetered, plugged-in usage pattern doesn't share to the same degree.
"""

import time
import uuid


# ------------------------------------------------------------------
# 1. Local-first writes with a persistent sync queue
# ------------------------------------------------------------------
class LocalFirstStore:
    def __init__(self):
        self.local_data: dict[str, dict] = {}
        self.sync_queue: list[dict] = []   # in a REAL app, persisted to SQLite/disk

    def save_locally_and_queue_sync(self, entity_id: str, data: dict):
        # ALWAYS write locally first — the UI reads this immediately,
        # regardless of network state
        self.local_data[entity_id] = data

        # Queue the sync action — persisted so it survives app restarts
        self.sync_queue.append({
            "action_id": str(uuid.uuid4())[:8],
            "entity_id": entity_id,
            "data": data,
            "queued_at": time.time(),
            "attempts": 0,
        })

    def attempt_sync(self, is_online: bool) -> list[str]:
        if not is_online:
            return []   # simply leave the queue as-is, retry later

        synced_ids = []
        remaining_queue = []
        for item in self.sync_queue:
            # Simulate a successful sync — a real implementation would
            # make the actual network call here, with retry/backoff on failure
            synced_ids.append(item["action_id"])
        self.sync_queue = remaining_queue   # queue drained
        return synced_ids


def sync_queue_demo():
    store = LocalFirstStore()

    print("Field technician completes 3 work orders while OFFLINE:")
    store.save_locally_and_queue_sync("order_1", {"status": "completed", "notes": "Fixed leak"})
    store.save_locally_and_queue_sync("order_2", {"status": "completed", "notes": "Replaced part"})
    store.save_locally_and_queue_sync("order_3", {"status": "completed", "notes": "No issue found"})

    print(f"  Local data available IMMEDIATELY: {list(store.local_data.keys())}")
    print(f"  Pending sync queue: {len(store.sync_queue)} items")

    print("\nAttempting sync WHILE STILL OFFLINE:")
    synced = store.attempt_sync(is_online=False)
    print(f"  Synced: {synced} (correctly did nothing, queue remains intact)")

    print("\nConnectivity resumes (technician reaches the office):")
    synced = store.attempt_sync(is_online=True)
    print(f"  Synced: {len(synced)} items, queue now empty: {len(store.sync_queue) == 0}")
    print("  -> The technician's work was NEVER blocked by lack of connectivity,")
    print("     and no completed work order was ever lost.")


# ------------------------------------------------------------------
# 2. Delta sync vs full sync — the data/battery cost difference
# ------------------------------------------------------------------
def delta_sync_savings_demo():
    full_dataset_size_kb = 5000   # e.g. a technician's full order history
    changed_records_size_kb = 15   # just the 3 orders actually modified

    print(f"\nFull sync (re-transfer everything): {full_dataset_size_kb} KB")
    print(f"Delta sync (only what changed): {changed_records_size_kb} KB")
    savings_pct = (1 - changed_records_size_kb / full_dataset_size_kb) * 100
    print(f"  -> {savings_pct:.1f}% reduction in mobile data usage and radio")
    print("     time (a direct battery-life benefit) for this sync operation.")


if __name__ == "__main__":
    sync_queue_demo()
    delta_sync_savings_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A grocery delivery app's driver-facing mobile app lets drivers mark
deliveries complete, capture proof-of-delivery photos, and update order
status entirely OFFLINE while inside buildings with poor cellular
signal — every action is written to local storage immediately and
queued for sync, with photos uploaded via delta sync (only new/changed
photos, never re-uploading previously-synced ones) once the driver's
phone regains a strong signal back in their vehicle — this exact
pattern, built on the SAME local-first + sync-queue + delta-sync
principles this lesson covers, is what makes such apps genuinely usable
in the connectivity-challenged environments delivery work actually happens in.
"""
