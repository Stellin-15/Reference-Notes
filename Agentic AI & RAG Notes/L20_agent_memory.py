# ============================================================
# L20: Agent Memory — Short-Term, Long-Term, and Memory Backends
# ============================================================
# WHAT: The distinct TYPES of memory an agent needs (short-term
#       conversation buffer vs long-term persistent memory, episodic vs
#       semantic), dedicated memory tools/libraries (Mem0, Zep, Letta,
#       LangGraph Memory), and the storage backends that actually hold
#       memory data (Redis, PostgreSQL, Neo4j, Chroma).
# WHY: Without memory, an agent is STATELESS between interactions — it
#      can't remember a user's preferences from a prior conversation, or
#      learn from past mistakes on similar tasks. Memory is what turns a
#      one-shot agent into something that improves/personalizes over
#      repeated use, and getting the memory ARCHITECTURE right (what to
#      store, for how long, retrieved how) is a real design problem, not
#      just "save everything."
# LEVEL: Advanced (Phase 5 of 7)
# ============================================================

"""
CONCEPT OVERVIEW:
SHORT-TERM MEMORY is the current conversation/task's context — the
message history within one session, held in the agent's active context
window. This is what L13's LangGraph state (a message list, accumulated
via the `add_messages` reducer) already provides WITHIN a single
thread — it doesn't automatically persist to a NEW conversation/session
unless explicitly designed to.

LONG-TERM MEMORY persists ACROSS sessions — facts, preferences, or
experiences an agent should remember the NEXT time it interacts with the
same user or works on a related task, even after the current
conversation/process has ended. This requires a genuinely different
architecture than short-term memory: what to EXTRACT from a conversation
as worth remembering long-term (not everything said is worth persisting
— L20's core design challenge), how to STORE it (a vector store for
semantic retrieval, a structured database for facts), and how to
RETRIEVE the relevant subset at the start of a new interaction (you
can't just dump ALL historical memory into every new prompt — this is
exactly a RAG-style retrieval problem, L03-L04, applied to an agent's
own memory instead of a document corpus).

EPISODIC MEMORY records SPECIFIC PAST EVENTS/INTERACTIONS ("on March 3rd,
the user asked about refund policy and was frustrated with the wait
time") — useful for recalling precedent or context about a specific past
interaction. SEMANTIC MEMORY stores GENERALIZED FACTS distilled from
possibly many interactions ("this user prefers email over phone contact")
— a summary/abstraction rather than a record of one specific event. Most
production memory systems maintain BOTH, since they serve different
retrieval needs (recalling a specific precedent vs recalling a general preference).

DEDICATED MEMORY LIBRARIES exist because building good long-term memory
extraction/storage/retrieval from scratch is a real engineering problem:
MEM0 focuses specifically on extracting and consolidating memories from
conversations (deciding what's worth remembering, updating existing
memories rather than duplicating when new information conflicts/refines
old). ZEP provides memory with built-in FACT EXTRACTION and a temporal
knowledge graph (tracking how facts about a user/entity change OVER
TIME, not just a flat memory store). LETTA (formerly MemGPT) is built
around the idea of an agent managing ITS OWN memory via explicit
function calls — the agent itself decides what to move between its
active context and long-term storage, rather than an external process
making that decision. LANGGRAPH MEMORY is LangGraph's own built-in
long-term memory store, integrated directly with its checkpointing
system (L13) for teams already using LangGraph who want memory without
adding a separate dedicated library.

MEMORY BACKENDS are where memory data is actually stored: REDIS
(fast, in-memory, good for session-scoped short-term memory needing low
latency), POSTGRESQL (durable, structured, good for semantic facts with
relational structure), NEO4J (a graph database — natural fit for
temporal/relational memory like Zep's knowledge graph, or tracking
relationships between remembered entities), CHROMA (a vector database,
L03 — natural fit for semantic, similarity-based memory retrieval, "find
memories relevant to this new query" rather than exact lookup).

PRODUCTION USE CASE:
A personal-assistant agent uses Mem0 to extract and consolidate facts
across every conversation with a user ("prefers concise answers,"
"traveling to Japan next month," "vegetarian") stored in a vector-backed
memory store (Chroma) for semantic retrieval — at the start of each NEW
conversation, only the memories SEMANTICALLY RELEVANT to the current
query are retrieved and injected into context, rather than dumping the
user's entire memory history into every prompt (which would waste
context and dilute relevance, the exact problem RAG's retrieval step
solves for document corpora, now applied to memory).

COMMON MISTAKES:
- Storing EVERYTHING said in every conversation as long-term memory
  without any extraction/filtering — this bloats storage, slows
  retrieval, and dilutes relevance (most of a typical conversation isn't
  worth remembering long-term; a good memory system extracts the
  meaningful subset, not a full transcript).
- Injecting an agent's ENTIRE memory history into every prompt instead
  of RETRIEVING only the relevant subset — this is the same mistake as
  skipping retrieval entirely in RAG (L04); memory needs its own
  relevance-based retrieval step, not a full dump.
- Not handling CONFLICTING/UPDATED memories — if a user's preference
  changes ("actually, I've stopped being vegetarian"), a memory system
  that just appends new facts without reconciling contradictions with
  old ones will retrieve stale, incorrect information alongside the
  updated fact, confusing rather than helping the agent.
"""

import textwrap
from dataclasses import dataclass, field
from datetime import datetime


# ------------------------------------------------------------------
# 1. Short-term memory — the current session's conversation buffer
# ------------------------------------------------------------------
@dataclass
class ConversationBuffer:
    """The simplest possible short-term memory — bounded by a max size
    to avoid unbounded context growth within one long session."""
    messages: list[dict] = field(default_factory=list)
    max_messages: int = 20

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_messages:
            # Trim the OLDEST messages first — a real system might
            # instead SUMMARIZE trimmed messages into a compact form
            # rather than discarding them entirely, preserving some
            # signal from the trimmed portion of the conversation.
            self.messages = self.messages[-self.max_messages:]


# ------------------------------------------------------------------
# 2. Long-term memory — extraction, storage, and RETRIEVAL (not dump-all)
# ------------------------------------------------------------------
@dataclass
class Memory:
    content: str
    memory_type: str        # "episodic" or "semantic"
    user_id: str
    created_at: datetime
    embedding: list[float] = field(default_factory=list)  # for semantic retrieval


class LongTermMemoryStore:
    def __init__(self):
        self.memories: list[Memory] = []

    def extract_and_store(self, conversation_text: str, user_id: str):
        """
        A REAL implementation sends the conversation through an LLM
        specifically prompted to extract WORTH-REMEMBERING facts (not
        the full transcript) — this stand-in illustrates the CONCEPT:
        extraction is a filtering step, not "store everything said."
        """
        extracted_facts = self._toy_extract(conversation_text)
        for fact in extracted_facts:
            self._upsert_memory(fact, user_id)

    def _toy_extract(self, text: str) -> list[str]:
        # A toy stand-in for an LLM-based extraction prompt.
        facts = []
        if "vegetarian" in text.lower():
            facts.append("User is vegetarian")
        if "concise" in text.lower():
            facts.append("User prefers concise answers")
        return facts

    def _upsert_memory(self, fact: str, user_id: str):
        """
        UPSERT, not blind append — check for a conflicting/superseded
        existing memory and REPLACE it rather than storing both an old
        and new, contradictory fact side by side.
        """
        existing = [m for m in self.memories if m.user_id == user_id and self._same_topic(m.content, fact)]
        for m in existing:
            self.memories.remove(m)   # supersede the old fact
        self.memories.append(Memory(fact, "semantic", user_id, datetime.now()))

    def _same_topic(self, a: str, b: str) -> bool:
        # A toy topic-matching stand-in — real systems use semantic
        # similarity or an LLM-based conflict-detection step here.
        return a.split()[0:2] == b.split()[0:2]

    def retrieve_relevant(self, query: str, user_id: str, top_k: int = 3) -> list[Memory]:
        """
        RETRIEVAL, not a full dump — exactly the RAG pattern from L04,
        applied to memory instead of documents. In production this uses
        real embedding similarity (L02-L03); simplified to keyword
        overlap here for a dependency-free illustration.
        """
        user_memories = [m for m in self.memories if m.user_id == user_id]
        scored = [
            (m, sum(1 for w in query.lower().split() if w in m.content.lower()))
            for m in user_memories
        ]
        return [m for m, score in sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]]


# ------------------------------------------------------------------
# 3. Real memory library usage patterns
# ------------------------------------------------------------------
MEM0_EXAMPLE = textwrap.dedent("""\
    from mem0 import Memory

    memory = Memory()

    # Extraction/consolidation happens automatically — Mem0 decides what
    # from this conversation is worth remembering and reconciles it
    # against existing memories (updating rather than duplicating).
    memory.add("I've become vegetarian recently", user_id="user_123")

    # Retrieval is semantic, scoped to the relevant subset — not a dump
    # of the user's entire memory history.
    relevant = memory.search("what should I cook for dinner", user_id="user_123")
""")

ZEP_EXAMPLE = textwrap.dedent("""\
    from zep_python import ZepClient

    client = ZepClient(api_key="...")

    # Zep extracts FACTS and maintains a TEMPORAL knowledge graph —
    # tracking not just WHAT is true, but WHEN it became true and
    # whether it's since been superseded, useful for "the user's stated
    # preference changed over time" scenarios a flat memory store
    # doesn't naturally capture.
    facts = client.memory.get_session_facts(session_id="session_123")
""")

LANGGRAPH_MEMORY_NOTE = textwrap.dedent("""\
    LangGraph's own long-term memory store integrates directly with its
    checkpointing system (L13) — a `Store` object, separate from
    per-thread checkpointed STATE, holds memories that persist ACROSS
    different thread_ids for the same user, letting a LangGraph-based
    agent recall long-term facts even when starting a genuinely new
    conversation thread (new thread_id), which checkpointing ALONE
    (scoped to one thread_id) does not provide.
""")

# ------------------------------------------------------------------
# 4. Memory backend selection
# ------------------------------------------------------------------
MEMORY_BACKEND_COMPARISON = {
    "Redis": "Fast, in-memory — well-suited to SHORT-TERM, session-"
        "scoped memory needing low-latency access.",
    "PostgreSQL": "Durable, structured — well-suited to semantic facts "
        "with relational structure (user preferences, account details).",
    "Neo4j": "Graph database — natural fit for TEMPORAL/relational "
        "memory (Zep's knowledge graph model, tracking relationships "
        "between remembered entities over time).",
    "Chroma": "Vector database (L03) — natural fit for SEMANTIC, "
        "similarity-based memory retrieval, finding memories relevant "
        "to a new query rather than exact key lookup.",
}


if __name__ == "__main__":
    buffer = ConversationBuffer(max_messages=3)
    for i in range(5):
        buffer.add("user", f"message {i}")
    print("Trimmed short-term buffer:", buffer.messages)

    print("\n--- Long-term memory: extraction, upsert, retrieval ---")
    store = LongTermMemoryStore()
    store.extract_and_store("I've recently become vegetarian and prefer concise answers", "user_1")
    print("Memories after first conversation:", [m.content for m in store.memories])

    store.extract_and_store("Actually I've become vegetarian again after a break", "user_1")
    print("Memories after conflicting update:", [m.content for m in store.memories])

    relevant = store.retrieve_relevant("what should I cook for dinner tonight", "user_1")
    print("Retrieved relevant memories for a cooking query:", [m.content for m in relevant])

    print()
    print(MEM0_EXAMPLE)
    print(ZEP_EXAMPLE)
    print(LANGGRAPH_MEMORY_NOTE)

    print("=== Memory backend comparison ===")
    for backend, note in MEMORY_BACKEND_COMPARISON.items():
        print(f"{backend}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
A healthcare intake assistant uses Zep specifically for its temporal
knowledge graph — a patient's reported symptoms and medication history
change over multiple visits, and the assistant needs to know not just
the CURRENT state but the PROGRESSION (when a symptom was first
reported, when a medication was changed) — a flat semantic memory store
(just "current facts") would lose exactly the temporal context clinical
reasoning depends on, which is the specific problem Zep's fact-with-
timestamp knowledge graph model is built to solve.
"""
