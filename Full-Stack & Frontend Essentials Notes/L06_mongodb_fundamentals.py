# ============================================================
# L06: MongoDB Fundamentals — Document Model, Schema Design, Aggregation
# ============================================================
# WHAT: MongoDB's document data model (as opposed to this repo's SQL
#       Notes' relational model), schema design principles specific to
#       documents (embedding vs referencing), and the aggregation
#       pipeline for complex queries.
# WHY: This repo covers relational databases (SQL Notes) and wide-column
#      stores (Feature Stores & Modern Data Lake Notes L08's ScyllaDB)
#      in depth, but not the DOCUMENT database model — MongoDB is the
#      dominant document database and a common companion to Node.js/
#      Express (L04) backends specifically, often called a MEAN/MERN stack pairing.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
MongoDB stores data as DOCUMENTS (JSON-like objects, technically BSON —
Binary JSON — internally) grouped into COLLECTIONS, rather than rows in
tables with a fixed schema (this repo's SQL Notes' relational model).
Documents in the SAME collection can have DIFFERENT fields/shapes (a
SCHEMA-FLEXIBLE model) — useful for data that genuinely varies in
structure record-to-record, though in PRACTICE, most production MongoDB
applications still maintain a CONSISTENT, application-enforced schema
(often via a library like Mongoose) even though the database itself
doesn't require it — schema flexibility is a capability, not a mandate
to have no structure at all.

EMBEDDING VS REFERENCING is THE central document-schema design decision,
directly analogous to (but a genuinely different tradeoff than) SQL's
normalization question: EMBEDDING nests related data DIRECTLY inside a
parent document (e.g. a blog post document containing an ARRAY of its
comments, embedded directly) — this makes reading the post-with-comments
a SINGLE document fetch (no join needed), at the cost of the embedded
data being duplicated if it needs to be accessed independently, and
document SIZE growing unboundedly if the embedded array can grow large
(MongoDB has a hard 16MB per-document size limit). REFERENCING stores a
related document's ID and looks it up SEPARATELY (similar to a SQL
foreign key, requiring an explicit join-like lookup, since MongoDB has
no native JOIN the way SQL does, though `$lookup` in the aggregation
pipeline provides SQL-join-like capability) — better for data accessed
INDEPENDENTLY, or growing unboundedly (e.g. comments on a very popular
post), at the cost of requiring a SEPARATE query/lookup to assemble
related data.

THE AGGREGATION PIPELINE is MongoDB's mechanism for complex queries
BEYOND simple find/filter — a SEQUENCE of STAGES (`$match` to filter,
`$group` to aggregate, `$sort`, `$lookup` for join-like operations),
each stage's output feeding into the next, conceptually similar to a
SQL query's WHERE/GROUP BY/JOIN/ORDER BY clauses, but expressed as an
explicit, ordered pipeline of transformation stages rather than a single
declarative SQL statement.

PRODUCTION USE CASE:
A chat application (directly relevant to L01/L09's chat UI coverage)
EMBEDS a conversation's recent messages directly within the
conversation document (fast, single-document reads for "show me this
conversation") while REFERENCING the full historical message archive in
a separate collection once a conversation's embedded message count
exceeds a threshold (avoiding the 16MB document-size ceiling and keeping
the "hot," frequently-read conversation document small and fast to load).

COMMON MISTAKES:
- Embedding data that can grow UNBOUNDEDLY (e.g. every comment ever
  made on a viral post) directly in a parent document — this risks
  hitting MongoDB's 16MB document size limit and makes the parent
  document progressively slower to read/write as the embedded array grows.
- Treating MongoDB's schema flexibility as license to have NO
  consistent structure at all across an application — in practice, most
  production systems benefit from an APPLICATION-ENFORCED schema (via
  Mongoose or similar validation) even though MongoDB itself doesn't
  require one, since inconsistent document shapes make querying and
  reasoning about the data significantly harder.
- Reaching for MongoDB by default for data that's GENUINELY relational
  (many-to-many relationships, strong consistency/transactional
  requirements across multiple related records) where this repo's SQL
  Notes' relational model and ACID guarantees are the better fit —
  MongoDB has transaction support, but relational databases remain the
  more natural default for genuinely relational data.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Documents and collections — basic CRUD
# ------------------------------------------------------------------
MONGODB_CRUD_EXAMPLE = textwrap.dedent("""\
    // Using the MongoDB Node.js driver (pairs naturally with L04's Express)
    const { MongoClient } = require('mongodb');
    const client = await MongoClient.connect('mongodb://localhost:27017');
    const db = client.db('chatapp');
    const conversations = db.collection('conversations');

    // Insert a document — no fixed schema enforced by MongoDB itself
    await conversations.insertOne({
      title: "Support ticket #4521",
      participants: ["user_1", "agent_bot"],
      messages: [
        { sender: "user_1", text: "My order hasn't arrived", timestamp: new Date() },
      ],
    });

    // Query with a filter — analogous to a SQL WHERE clause
    const activeConvos = await conversations.find({ status: "active" }).toArray();

    // Update — MongoDB's operators like $push append to an ARRAY FIELD
    await conversations.updateOne(
      { _id: conversationId },
      { $push: { messages: { sender: "agent_bot", text: "Let me check that", timestamp: new Date() } } }
    );
""")

# ------------------------------------------------------------------
# 2. Embedding vs referencing — the central schema decision
# ------------------------------------------------------------------
EMBEDDING_EXAMPLE = textwrap.dedent("""\
    // EMBEDDING: messages live DIRECTLY inside the conversation document
    // — a single query retrieves the FULL conversation with all messages.
    {
      "_id": "conv_1",
      "title": "Support ticket #4521",
      "messages": [
        { "sender": "user_1", "text": "...", "timestamp": "..." },
        { "sender": "agent_bot", "text": "...", "timestamp": "..." }
      ]
    }
    // GOOD for: a bounded, typically-small number of messages per
    // conversation, always read TOGETHER with the parent.
    // RISK: if a conversation could accumulate THOUSANDS of messages,
    // this document grows unboundedly toward MongoDB's 16MB limit.
""")

REFERENCING_EXAMPLE = textwrap.dedent("""\
    // REFERENCING: messages live in a SEPARATE collection, referencing
    // their parent conversation by ID.
    // conversations collection:
    { "_id": "conv_1", "title": "Support ticket #4521" }

    // messages collection (separate):
    { "_id": "msg_1", "conversation_id": "conv_1", "sender": "user_1", "text": "..." }
    { "_id": "msg_2", "conversation_id": "conv_1", "sender": "agent_bot", "text": "..." }

    // Retrieving a conversation's messages now requires a SEPARATE query
    // (or a $lookup aggregation stage, below) — GOOD for unbounded
    // growth and independent access patterns (e.g. searching messages
    // across ALL conversations without loading every parent document).
""")

# ------------------------------------------------------------------
# 3. The aggregation pipeline
# ------------------------------------------------------------------
AGGREGATION_PIPELINE_EXAMPLE = textwrap.dedent("""\
    // Find the TOTAL message count per conversation, for conversations
    // with more than 10 messages, sorted by count descending — a query
    // that would be a GROUP BY + HAVING + ORDER BY in SQL.
    const results = await db.collection('messages').aggregate([
      { $group: {
          _id: "$conversation_id",
          messageCount: { $sum: 1 },
        }
      },
      { $match: { messageCount: { $gt: 10 } } },   // like SQL's HAVING
      { $sort: { messageCount: -1 } },
    ]).toArray();

    // $lookup — MongoDB's JOIN-like operation for the REFERENCING
    // pattern, assembling a conversation with its messages in ONE query:
    const conversationWithMessages = await db.collection('conversations').aggregate([
      { $match: { _id: "conv_1" } },
      { $lookup: {
          from: "messages",
          localField: "_id",
          foreignField: "conversation_id",
          as: "messages",   // the joined messages are attached as this field
        }
      },
    ]).toArray();
""")


if __name__ == "__main__":
    print(MONGODB_CRUD_EXAMPLE)
    print(EMBEDDING_EXAMPLE)
    print(REFERENCING_EXAMPLE)
    print(AGGREGATION_PIPELINE_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A customer support chat platform embeds a conversation's most RECENT 50
messages directly in the conversation document (fast, single-query
loads for the common "open this conversation" action), while older
messages are moved to a separate, referenced `message_archive`
collection via a background job once a conversation exceeds that
threshold — a hybrid embedding/referencing strategy directly applying
this lesson's tradeoff analysis to keep the common case fast while
avoiding the unbounded-growth risk embedding alone would create for
genuinely long-running support conversations.
"""
