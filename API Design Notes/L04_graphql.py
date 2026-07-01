# =============================================================================
# WHAT: GraphQL — Schema, Resolvers, Pagination, DataLoader, Federation
# WHY:  GraphQL lets clients request exactly the fields they need, eliminating
#       over-fetching (too much data) and under-fetching (too many round trips).
#       One endpoint, self-documenting schema, strong typing across the stack.
# LEVEL: Intermediate → Advanced
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# GraphQL is a query language for APIs and a runtime for executing those queries.
# Every GraphQL API has:
#   Schema  — the type system defining what data exists and what operations are allowed
#   Resolvers — functions that fetch data for each field in the schema
#   Operations — Query (read), Mutation (write), Subscription (real-time push)
#
# Clients write queries that mirror the shape of the data they want back.
# The server validates queries against the schema before executing them.
#
# PRODUCTION USE CASE
# -------------------
# GitHub's public API v4 is GraphQL. A CI dashboard can fetch in one request:
# repo name, last 5 commits, open PRs with labels, and workflow run statuses —
# data that would require 4+ REST calls. Twitter/X, Shopify, and Airbnb all
# use GraphQL for their primary client-facing APIs.
#
# COMMON MISTAKES
# ---------------
# 1. N+1 queries — resolving each user's orders in a loop → DataLoader fixes this
# 2. Leaving introspection on in production → leaks full schema to attackers
# 3. No query depth / complexity limits → trivially DoS-able with nested queries
# 4. Treating GraphQL errors like HTTP errors — partial success is a feature
# 5. Offset pagination instead of cursor pagination → breaks on concurrent writes
# 6. Putting all types in one giant schema file → use modules/federation instead
# =============================================================================

# ---------------------------------------------------------------------------
# Standard library
# ---------------------------------------------------------------------------
import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

# ---------------------------------------------------------------------------
# Third-party — pip install strawberry-graphql[fastapi] uvicorn sqlalchemy
# ---------------------------------------------------------------------------
import strawberry
from strawberry import Schema
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON as ScalarJSON
from strawberry.types import Info

# FastAPI for mounting GraphQL
from fastapi import FastAPI

logger = logging.getLogger(__name__)


# =============================================================================
# PART 1 — TYPE SYSTEM: SCALARS, OBJECTS, ENUMS, INTERFACES, UNIONS, INPUTS
# =============================================================================
# Strawberry uses Python dataclasses decorated with @strawberry.type.
# The decorator transforms them into GraphQL type definitions.
# =============================================================================

# ── Enum ──────────────────────────────────────────────────────────────────────
@strawberry.enum
class OrderStatus:
    """
    GraphQL enum. Values are serialized as strings on the wire.
    Clients can use these as literal values in queries and mutations.
    """
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# ── Object types ──────────────────────────────────────────────────────────────
@strawberry.type
class Address:
    street: str
    city: str
    state: str
    country: str


@strawberry.type
class Product:
    id: strawberry.ID           # strawberry.ID is a special scalar for IDs (serializes as string)
    sku: str
    name: str
    price_usd: float
    in_stock: bool


@strawberry.type
class OrderItem:
    product: Product
    quantity: int
    line_total: float           # Computed field: quantity * product.price_usd


@strawberry.type
class Order:
    id: strawberry.ID
    status: OrderStatus
    items: list[OrderItem]
    shipping_address: Address
    total_usd: float
    created_at: str             # ISO 8601 string; use strawberry.scalar for proper DateTime


@strawberry.type
class User:
    id: strawberry.ID
    email: str
    name: str
    # Resolver field — fetched separately, enabling DataLoader batching
    orders: list[Order]         # This is the N+1 problem source if not batched


# ── Interface ─────────────────────────────────────────────────────────────────
@strawberry.interface
class Node:
    """
    Relay-spec Node interface: every identifiable object implements this.
    Enables global object identification: node(id: "abc") fetches any type.
    """
    id: strawberry.ID


@strawberry.type
class PageInfo:
    """Cursor-based pagination metadata (Relay spec)."""
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str] = None   # Opaque cursor for the first edge
    end_cursor: Optional[str] = None     # Opaque cursor for the last edge


# ── Generic Connection/Edge pattern (cursor pagination) ──────────────────────
@strawberry.type
class OrderEdge:
    """Wraps each item with its cursor for pagination."""
    node: Order
    cursor: str                 # Opaque string the client passes to 'after' arg


@strawberry.type
class OrderConnection:
    """
    Relay-spec Connection: the paginated list of Orders.
    Clients use: orders(first: 10, after: "cursor") { edges { node { id } } pageInfo { ... } }
    """
    edges: list[OrderEdge]
    page_info: PageInfo
    total_count: int            # Total items across all pages (expensive; consider omitting)


# ── Union ─────────────────────────────────────────────────────────────────────
@strawberry.type
class OrderSuccess:
    order: Order


@strawberry.type
class OrderError:
    code: str
    message: str
    field: Optional[str] = None  # Which input field caused the error


# Union type: mutation result is EITHER success OR error
CreateOrderResult = strawberry.union("CreateOrderResult", [OrderSuccess, OrderError])


# ── Input types ───────────────────────────────────────────────────────────────
@strawberry.input
class OrderItemInput:
    """Input types are used for arguments to mutations and queries."""
    sku: str
    quantity: int = strawberry.field(
        default=1,
        description="Number of units to order",
    )


@strawberry.input
class CreateOrderInput:
    customer_id: strawberry.ID
    items: list[OrderItemInput]
    shipping_address_id: strawberry.ID


# =============================================================================
# PART 2 — THE N+1 PROBLEM AND DATALOADER BATCHING
# =============================================================================
# Without batching: fetching 10 users and their orders = 1 + 10 = 11 queries.
# With DataLoader: 10 user IDs are batched into 1 query → 2 queries total.
# DataLoader also deduplicates and caches within a single request.
# =============================================================================

from strawberry.dataloader import DataLoader


async def batch_load_orders_by_user_id(user_ids: list[str]) -> list[list[Order]]:
    """
    Called ONCE per request with ALL pending user IDs — not once per user.
    Returns a list of order lists in the SAME ORDER as user_ids input.

    In production this becomes:
      SELECT * FROM orders WHERE user_id IN (...user_ids...)
    instead of N separate SELECT queries.
    """
    logger.info(
        "DataLoader batch: loading orders for %d users in one query",
        len(user_ids),
    )
    # Simulate DB batch fetch
    orders_by_user: dict[str, list[Order]] = {}
    # ... real code: query DB with IN clause, group by user_id ...

    # Return results in the EXACT same order as input user_ids
    # Missing users must be represented as empty lists (not skipped)
    return [orders_by_user.get(uid, []) for uid in user_ids]


async def batch_load_products_by_sku(skus: list[str]) -> list[Optional[Product]]:
    """
    Batch-loads products by SKU. Returns None for unknown SKUs.
    DataLoader maps missing values to None automatically.
    """
    logger.info("DataLoader batch: loading %d products", len(skus))
    products: dict[str, Product] = {}
    # ... real code: SELECT * FROM products WHERE sku IN (:skus) ...
    return [products.get(sku) for sku in skus]


# DataLoader instances are typically created per-request (not per-app)
# so caching is scoped to a single GraphQL execution
def create_loaders() -> dict[str, DataLoader]:
    return {
        "orders_by_user": DataLoader(load_fn=batch_load_orders_by_user_id),
        "products_by_sku": DataLoader(load_fn=batch_load_products_by_sku),
    }


# =============================================================================
# PART 3 — RESOLVERS: QUERY, MUTATION, SUBSCRIPTION
# =============================================================================
# Strawberry resolvers are async functions decorated with @strawberry.field.
# 'info' provides access to context (loaders, auth, request).
# =============================================================================

@strawberry.type
class Query:
    """Root Query type — all read operations hang off this."""

    @strawberry.field(description="Fetch a single user by ID")
    async def user(self, id: strawberry.ID, info: Info) -> Optional[User]:
        # info.context holds the request-scoped context (loaders, auth user, etc.)
        # loader = info.context["loaders"]["some_loader"]
        logger.info("Resolving user id=%s", id)
        # Simulate DB fetch
        return User(id=id, email="alice@example.com", name="Alice Smith", orders=[])

    @strawberry.field(description="Paginated list of orders with cursor-based pagination")
    async def orders(
        self,
        info: Info,
        first: int = 10,        # How many items to return (page size)
        after: Optional[str] = None,  # Cursor of the last seen item
        # Arguments for filtering — keep them optional and additive
        status: Optional[OrderStatus] = None,
    ) -> OrderConnection:
        """
        Cursor-based pagination is safer than offset pagination because:
        - Offset drifts when rows are inserted/deleted between pages
        - Cursors point to a stable position in the result set
        """
        # Decode the opaque cursor (in prod: base64-encoded row ID or timestamp)
        after_id: Optional[str] = None
        if after:
            import base64
            after_id = base64.b64decode(after.encode()).decode()

        # Simulate fetching page from DB
        # Real code: SELECT * FROM orders WHERE id > :after_id LIMIT :first + 1
        mock_orders: list[Order] = []  # Would be populated from DB

        has_next = len(mock_orders) > first
        page_orders = mock_orders[:first]  # Drop the extra item we fetched

        def make_cursor(order: Order) -> str:
            """Encode an opaque cursor. Clients must treat this as a black box."""
            import base64
            return base64.b64encode(str(order.id).encode()).decode()

        edges = [
            OrderEdge(node=o, cursor=make_cursor(o))
            for o in page_orders
        ]

        return OrderConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_next,
                has_previous_page=after is not None,
                end_cursor=edges[-1].cursor if edges else None,
                start_cursor=edges[0].cursor if edges else None,
            ),
            total_count=0,  # In prod: COUNT(*) — expensive on large tables
        )

    @strawberry.field
    async def node(self, id: strawberry.ID, info: Info) -> Optional[Node]:
        """
        Global object lookup by ID (Relay spec).
        Decodes the ID to determine the type, then fetches it.
        """
        # In prod: decode a Base64 "type:id" global ID
        return None


@strawberry.type
class Mutation:
    """Root Mutation type — all write operations hang off this."""

    @strawberry.mutation(description="Create a new order")
    async def create_order(
        self,
        input: CreateOrderInput,
        info: Info,
    ) -> "CreateOrderResult":  # type: ignore[name-defined]
        """
        Returns a union type (OrderSuccess | OrderError).
        This is the GraphQL pattern for mutations: NEVER raise exceptions —
        always return a typed result. Partial success is handled this way too.
        """
        # Validate
        if not input.items:
            return OrderError(code="VALIDATION_ERROR", message="At least one item required")

        # Attempt DB write
        try:
            new_order = Order(
                id=strawberry.ID("ORD-001"),
                status=OrderStatus.PENDING,
                items=[],
                shipping_address=Address(
                    street="", city="", state="", country=""
                ),
                total_usd=0.0,
                created_at="2024-01-01T00:00:00Z",
            )
            return OrderSuccess(order=new_order)
        except Exception as e:
            # Return a typed error instead of raising — client handles it gracefully
            return OrderError(code="INTERNAL_ERROR", message=str(e))

    @strawberry.mutation
    async def cancel_order(
        self,
        order_id: strawberry.ID,
        reason: Optional[str],
        info: Info,
    ) -> "CreateOrderResult":  # type: ignore[name-defined]
        # Check auth: info.context["user"] must own this order
        return OrderError(code="NOT_FOUND", message=f"Order {order_id} not found")


@strawberry.type
class Subscription:
    """
    Root Subscription type — real-time push via WebSocket.
    Clients maintain a WS connection; server pushes updates as they occur.
    Use case: order status tracking, live dashboards, collaborative editing.
    """

    @strawberry.subscription(description="Stream order status changes in real time")
    async def order_status_updated(
        self,
        order_id: strawberry.ID,
        info: Info,
    ) -> AsyncGenerator[Order, None]:
        """
        Yields Order objects whenever the status changes.
        In prod: subscribe to a Redis pub/sub channel or Postgres LISTEN.
        """
        statuses = [OrderStatus.CONFIRMED, OrderStatus.SHIPPED, OrderStatus.DELIVERED]
        for status in statuses:
            # Yield the updated order to all subscribers
            yield Order(
                id=order_id,
                status=status,
                items=[],
                shipping_address=Address(street="", city="", state="", country=""),
                total_usd=99.0,
                created_at="2024-01-01T00:00:00Z",
            )
            await asyncio.sleep(2)  # Real code: wait for pub/sub message


# =============================================================================
# PART 4 — SCHEMA CREATION AND FASTAPI INTEGRATION
# =============================================================================

schema = Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    # Custom scalars, directives, and extensions go here
    extensions=[],
)

app = FastAPI(title="GraphQL API Demo")

# Mount GraphQL at /graphql; GraphiQL IDE available in dev
graphql_app = GraphQLRouter(
    schema,
    graphiql=True,              # Disable in production
    context_getter=lambda: {"loaders": create_loaders()},
)
app.include_router(graphql_app, prefix="/graphql")


# =============================================================================
# PART 5 — FRAGMENTS, VARIABLES, ALIASES, DIRECTIVES
# =============================================================================
# These are client-side GraphQL features. Shown as string constants.
# =============================================================================

# ── Fragments — reusable field sets ──────────────────────────────────────────
FRAGMENT_EXAMPLE = """
fragment OrderFields on Order {
  id
  status
  totalUsd
  createdAt
}

query GetMyOrders($userId: ID!, $first: Int = 10) {
  user(id: $userId) {
    name
    orders(first: $first) {
      edges {
        node {
          ...OrderFields     # Spread the fragment — avoids repeating fields
          items {
            quantity
            product { name }
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

# ── Variables — parameterized queries ────────────────────────────────────────
QUERY_WITH_VARIABLES = """
mutation CreateOrder($input: CreateOrderInput!) {
  createOrder(input: $input) {
    ... on OrderSuccess {          # Inline fragment for union type
      order { id status }
    }
    ... on OrderError {
      code
      message
      field
    }
  }
}
"""
VARIABLES_EXAMPLE = {
    "input": {
        "customerId": "USER-42",
        "items": [{"sku": "WIDGET-001", "quantity": 2}],
        "shippingAddressId": "ADDR-99",
    }
}

# ── Aliases — request the same field multiple times with different args ───────
ALIAS_EXAMPLE = """
query ComparePrices {
  cheapProduct: product(id: "PROD-001") { name priceUsd }
  expensiveProduct: product(id: "PROD-999") { name priceUsd }
}
"""

# ── Directives — conditional field inclusion ──────────────────────────────────
DIRECTIVE_EXAMPLE = """
query GetUser($id: ID!, $includeOrders: Boolean!, $skipAddress: Boolean!) {
  user(id: $id) {
    name
    orders @include(if: $includeOrders) {   # Field included only if true
      edges { node { id status } }
    }
    shippingAddress @skip(if: $skipAddress) { # Field skipped if true
      street city
    }
  }
}
"""


# =============================================================================
# PART 6 — QUERY COMPLEXITY AND DEPTH LIMITING
# =============================================================================
# Without limits, a malicious client can send:
#   { user { orders { items { product { reviews { author { orders { ... } } } } } } } }
# and bring your DB to its knees. Depth and complexity limits prevent this.
# =============================================================================

# Strawberry extension for query depth limiting
# pip install strawberry-graphql[depth-limit]
from strawberry.extensions import QueryDepthLimiter, MaxTokensLimiter


schema_with_limits = Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        QueryDepthLimiter(max_depth=7),     # Reject queries nested deeper than 7 levels
        MaxTokensLimiter(max_token_count=1000),  # Reject huge documents
    ],
)

# Custom complexity scoring example (manual approach)
FIELD_COSTS: dict[str, int] = {
    "user": 1,
    "orders": 5,            # Expensive — hits DB
    "orderItems": 3,
    "product": 2,
    "reviews": 10,          # Very expensive — separate microservice
}

def calculate_query_complexity(query_ast: Any) -> int:
    """
    Walk the query AST and sum field costs.
    Reject the query if total > MAX_COMPLEXITY.
    In prod use a library like graphql-query-complexity.
    """
    MAX_COMPLEXITY = 100
    # ... AST traversal logic ...
    return 0  # Placeholder


# =============================================================================
# PART 7 — PERSISTED QUERIES
# =============================================================================
# Pre-register known queries on the server. Clients send just the hash.
# Benefits: smaller payloads, server can whitelist queries (no ad-hoc queries
# in production), CDN-cacheable with GET requests.
# =============================================================================

# In-memory store — use Redis in production
PERSISTED_QUERY_STORE: dict[str, str] = {}


def register_persisted_query(query_string: str) -> str:
    """
    Hash a query string and store it. Returns the SHA-256 hash.
    In prod: store in Redis with a long TTL.
    """
    query_hash = hashlib.sha256(query_string.encode()).hexdigest()
    PERSISTED_QUERY_STORE[query_hash] = query_string
    return query_hash


def get_persisted_query(query_hash: str) -> Optional[str]:
    """Look up a query by hash. Returns None if not found."""
    return PERSISTED_QUERY_STORE.get(query_hash)


# APQ (Automatic Persisted Queries) flow:
# 1. Client sends: { "extensions": { "persistedQuery": { "sha256Hash": "abc..." } } }
# 2. Server: hash found → execute; hash not found → return PersistedQueryNotFound
# 3. Client: resends with full query + hash; server stores and executes


# =============================================================================
# PART 8 — ERROR HANDLING IN GRAPHQL (PARTIAL SUCCESS)
# =============================================================================
# Unlike REST, GraphQL can return BOTH data and errors in the same response.
# "errors" is a top-level field alongside "data".
# =============================================================================

GRAPHQL_RESPONSE_WITH_ERRORS = {
    "data": {
        "user": {
            "name": "Alice",
            "orders": None,         # This field errored; others still returned
        }
    },
    "errors": [
        {
            "message": "Failed to load orders: DB connection timeout",
            "locations": [{"line": 4, "column": 5}],
            "path": ["user", "orders"],        # Pinpoints which field failed
            "extensions": {
                "code": "DATABASE_ERROR",      # Machine-readable error code
                "retry_after": 5,              # Seconds until client may retry
            },
        }
    ],
}

# Custom error handling in Strawberry
from strawberry.extensions import SchemaExtension


class ErrorFormattingExtension(SchemaExtension):
    """Normalize all errors to include a machine-readable 'code' in extensions."""

    def on_executing(self):
        yield  # Execute the query

    def format_error(self, error: Exception) -> dict:
        """Called for each error before it's included in the response."""
        formatted = {"message": str(error)}
        # Add extensions based on exception type
        if hasattr(error, "extensions"):
            formatted["extensions"] = error.extensions  # type: ignore[attr-defined]
        return formatted


# =============================================================================
# PART 9 — INTROSPECTION: DISCOVERY AND WHY TO DISABLE IN PRODUCTION
# =============================================================================

# GraphQL introspection query (clients use this to auto-generate SDKs / docs)
INTROSPECTION_QUERY = """
{
  __schema {
    types {
      name
      kind
      fields { name type { name kind } }
    }
  }
}
"""

# Why disable introspection in production:
INTROSPECTION_RISKS = [
    "Exposes full schema to unauthenticated clients → reconnaissance for attackers",
    "Reveals internal type names, field names, and relationships",
    "Makes it easier to craft targeted injection or abuse queries",
    "Leaks deprecated or internal fields you forgot to remove",
]

# Disable introspection in Strawberry:
schema_production = Schema(
    query=Query,
    mutation=Mutation,
    # Disable introspection entirely
    extensions=[],
)
# The proper way in Strawberry is to pass disable_field_suggestions=True
# and use a custom extension or middleware to reject __schema/__type queries


# =============================================================================
# PART 10 — APOLLO FEDERATION (SCHEMA STITCHING)
# =============================================================================
# Federation lets multiple GraphQL services each own a part of the schema.
# A Gateway composes them into one unified schema for clients.
# Use when: separate teams own separate parts of the graph.
# =============================================================================

FEDERATION_SCHEMA_EXAMPLE = """
# In the User service:
type User @key(fields: "id") {
  id: ID!
  email: String!
  name: String!
}

# In the Order service:
type Order @key(fields: "id") {
  id: ID!
  status: OrderStatus!
  user: User!            # References User from another service
}

# The Order service 'extends' User to add the orders field
extend type User @key(fields: "id") {
  id: ID! @external      # Declared here, owned by User service
  orders: [Order!]!      # Order service resolves this
}
"""

# Federation subgraph setup with strawberry-django or strawberry-federation
CMD_APOLLO_ROVER = "rover subgraph publish my-graph@prod --schema ./schema.graphql --name orders --routing-url http://orders-service/graphql"


# =============================================================================
# PART 11 — WHEN GRAPHQL HURTS
# =============================================================================

GRAPHQL_DOWNSIDES = {
    "HTTP caching": (
        "POST requests are not cached by CDNs. "
        "Workaround: persisted queries with GET, but complex to set up."
    ),
    "Simple CRUD": (
        "REST is simpler for basic endpoints. GraphQL adds schema/resolver overhead "
        "that isn't justified if you always fetch the same fields."
    ),
    "File uploads": (
        "Not natively supported. Use multipart/form-data spec or a separate REST endpoint."
    ),
    "Rate limiting": (
        "Hard to rate-limit by 'endpoint' — every request goes to /graphql. "
        "Must implement query complexity-based rate limiting."
    ),
    "Error codes": (
        "No standardized error code system. Each team invents their own 'extensions.code'."
    ),
    "Monitoring": (
        "Traditional APM tools show one endpoint /graphql with many operation names. "
        "Need operation-aware instrumentation."
    ),
    "N+1 by default": (
        "Naive resolvers will generate N+1 DB queries. DataLoader is required but "
        "adds architectural complexity."
    ),
}


# =============================================================================
# DEMO BLOCK
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    print("GraphQL API reference. Endpoints:")
    print("  GraphiQL IDE → http://localhost:8000/graphql")
    print()

    # Register a persisted query
    query_hash = register_persisted_query(FRAGMENT_EXAMPLE)
    print(f"Registered persisted query hash: {query_hash[:16]}...")

    # Show example request with variables
    print("\nExample mutation request body:")
    print(json.dumps(
        {
            "query": QUERY_WITH_VARIABLES,
            "variables": VARIABLES_EXAMPLE,
            "operationName": "CreateOrder",
        },
        indent=2,
    ))

    uvicorn.run(app, host="0.0.0.0", port=8000)
