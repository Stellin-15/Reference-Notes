# =============================================================================
# WHAT:  Microservices Architecture Patterns
# WHY:   Real systems outgrow monoliths. Microservices solve independent
#        scaling and team autonomy — but introduce distributed system complexity.
#        These patterns are the toolkit for managing that complexity.
# LEVEL: Intermediate → Advanced (assumes REST, Docker, basic DB knowledge)
# =============================================================================

# =============================================================================
# CONCEPT OVERVIEW
# =============================================================================
# Microservices split a single application into small, independently deployable
# services, each owning its data and business logic. The tradeoff is well-known:
#   MONOLITH pros: simple deploy, easy debugging, no network hops, ACID transactions
#   MONOLITH cons: hard to scale one part, one language/framework for all, big teams
#                  conflict on a single codebase, slow deploys as size grows
#   MICROSERVICES pros: independent deploy, independent scale, tech diversity,
#                       team ownership, fault isolation
#   MICROSERVICES cons: network latency, distributed tracing, eventual consistency,
#                       operational overhead (many services to run/monitor)
#
# RULE OF THUMB: Start with a MODULAR MONOLITH (clean internal modules).
#   Extract services when you hit a real pain point (scaling, team ownership,
#   tech mismatch). Don't distribute prematurely — it's very expensive to fix.
# =============================================================================

# =============================================================================
# PRODUCTION USE CASE
# =============================================================================
# E-commerce platform (Amazon-style):
#
#   Client
#     |
#   [API Gateway]  ← single entry point: auth, routing, rate limiting
#     |
#   ┌─────────────────────────────────────────┐
#   │  User      Order     Payment   Notif    │
#   │  Service   Service   Service   Service  │
#   │  (Postgres)(Postgres)(Postgres)(Redis)  │
#   └─────────────────────────────────────────┘
#        ↕ async events via Kafka / RabbitMQ
#
# ORDER FLOW:
#   1. POST /orders → API Gateway validates JWT → Order Service
#   2. Order Service creates order (PENDING)
#   3. Order Service publishes OrderCreated event
#   4. Payment Service subscribes, charges card, publishes PaymentSucceeded
#   5. Inventory Service subscribes, reserves stock, publishes StockReserved
#   6. Notification Service subscribes, sends confirmation email
#   On any failure → compensating events (RefundPayment, ReleaseStock)
# =============================================================================

# =============================================================================
# COMMON MISTAKES
# =============================================================================
# 1. Decomposing by technical layer (UI service, DB service) — WRONG.
#    Correct: decompose by business domain. UI and DB for Orders belong together.
# 2. Synchronous chains: A calls B calls C calls D. D goes down → cascade failure.
#    Fix: async events for non-critical path. Circuit breakers for sync calls.
# 3. Shared databases between services — destroys service independence.
#    Each service must own its data store. Use events to sync data across services.
# 4. Distributed transactions (2-phase commit) — slow, brittle. Use Saga instead.
# 5. Extracting too early — pay distributed tax before you need the benefits.
# =============================================================================


import time
import random
import threading
from enum import Enum
from typing import Callable, Any, Optional
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime


# =============================================================================
# PATTERN 1: SERVICE DECOMPOSITION
# =============================================================================
# Decompose by BUSINESS DOMAIN, not technical layer.
# Each service = bounded context (Domain-Driven Design term).
# Each service owns its own data store — no shared DB.
# Conway's Law: "Organizations design systems that mirror communication structures."
# → Team boundaries = service boundaries.

class UserService:
    """Owns: user profiles, authentication, preferences."""
    def __init__(self):
        self._users = {}           # In reality: PostgreSQL
        self._event_bus = None     # Set externally

    def register(self, user_id: str, email: str, name: str) -> dict:
        user = {"id": user_id, "email": email, "name": name, "created_at": datetime.utcnow().isoformat()}
        self._users[user_id] = user
        # Publish event — other services react asynchronously
        self._publish("UserRegistered", {"user_id": user_id, "email": email})
        return user

    def get_user(self, user_id: str) -> Optional[dict]:
        return self._users.get(user_id)

    def _publish(self, event_type: str, payload: dict):
        if self._event_bus:
            self._event_bus.publish(event_type, payload)


class OrderService:
    """Owns: orders, order items, order status."""
    def __init__(self):
        self._orders = {}
        self._event_bus = None

    def create_order(self, order_id: str, user_id: str, items: list, total: float) -> dict:
        order = {
            "id": order_id, "user_id": user_id, "items": items,
            "total": total, "status": "PENDING",
            "created_at": datetime.utcnow().isoformat()
        }
        self._orders[order_id] = order
        # START of Saga — publish event, don't call Payment directly
        self._publish("OrderCreated", {"order_id": order_id, "user_id": user_id, "total": total})
        return order

    def handle_payment_succeeded(self, order_id: str):
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CONFIRMED"
            self._publish("OrderConfirmed", {"order_id": order_id})

    def handle_payment_failed(self, order_id: str, reason: str):
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
            self._orders[order_id]["cancel_reason"] = reason

    def _publish(self, event_type: str, payload: dict):
        if self._event_bus:
            self._event_bus.publish(event_type, payload)


# =============================================================================
# PATTERN 2: SIMPLE EVENT BUS (simulates Kafka/RabbitMQ)
# =============================================================================
# In production: Kafka for durability + replay, RabbitMQ for simpler routing.
# Events decouple services — publisher doesn't know who consumes.
# This is async communication: fire and forget, no blocking.

class InMemoryEventBus:
    """
    Simplified event bus simulating async messaging.
    Real system: Kafka topics, consumer groups, at-least-once delivery.
    """
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable):
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, payload: dict):
        # In production: serialize to JSON, write to Kafka partition
        # Consumer groups process events independently
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            # In production: each handler runs in a separate consumer group
            # with independent offset tracking
            try:
                handler(payload)
            except Exception as e:
                print(f"[EventBus] Handler error for {event_type}: {e}")
                # Real system: dead letter queue, retry with backoff


# =============================================================================
# PATTERN 3: CIRCUIT BREAKER
# =============================================================================
# Problem: Service A calls Service B. B becomes slow/unavailable.
#   Without circuit breaker: A's threads pile up waiting for B → A also fails.
#   With circuit breaker: after N failures, stop calling B. Fail fast immediately.
#   B gets breathing room to recover. A stays responsive.
#
# State machine:
#   CLOSED → normal operation, all calls pass through
#     ↓ (failure threshold exceeded)
#   OPEN → fail fast, don't call B at all
#     ↓ (after recovery timeout)
#   HALF_OPEN → send one test call
#     ↓ success → CLOSED
#     ↓ failure → OPEN again
#
# Production: pybreaker library, or hystrix (Java), resilience4j.

class CircuitState(Enum):
    CLOSED    = "CLOSED"     # Normal — calls pass through
    OPEN      = "OPEN"       # Failing — fail fast
    HALF_OPEN = "HALF_OPEN"  # Testing recovery

class CircuitBreaker:
    """
    Circuit breaker protecting calls to a downstream service.

    Args:
        failure_threshold: number of failures to trip to OPEN
        recovery_timeout:  seconds to wait before testing recovery
        success_threshold: successes in HALF_OPEN needed to close
    """
    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            # Auto-transition OPEN → HALF_OPEN after timeout
            if self._state == CircuitState.OPEN:
                elapsed = time.time() - (self._last_failure_time or 0)
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    print(f"[Circuit:{self.service_name}] OPEN → HALF_OPEN (testing recovery)")
            return self._state

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute func through the circuit breaker."""
        state = self.state

        if state == CircuitState.OPEN:
            # Fail fast — don't even attempt the call
            raise CircuitOpenError(f"Circuit OPEN for {self.service_name}. Service unavailable.")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    print(f"[Circuit:{self.service_name}] HALF_OPEN → CLOSED (recovered)")
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0  # Reset on success

    def _on_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery test → back to OPEN
                self._state = CircuitState.OPEN
                print(f"[Circuit:{self.service_name}] HALF_OPEN → OPEN (recovery failed)")
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                print(f"[Circuit:{self.service_name}] CLOSED → OPEN ({self._failure_count} failures)")

class CircuitOpenError(Exception):
    pass


# =============================================================================
# PATTERN 4: RETRY WITH EXPONENTIAL BACKOFF + JITTER
# =============================================================================
# Retry transient failures (network blip, brief overload).
# Exponential backoff: wait 1s, 2s, 4s, 8s... avoids thundering herd.
# Jitter: add random noise to spread retries across clients.
# Max retries: don't retry forever. Combine with circuit breaker.
#
# CRITICAL: Only retry IDEMPOTENT operations.
#   GET, PUT, DELETE — idempotent, safe to retry.
#   POST creating a new record — NOT idempotent. Use idempotency keys instead.

def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (ConnectionError, TimeoutError)
):
    """
    Retry func with exponential backoff and optional jitter.
    Only catches retryable_exceptions — others propagate immediately.
    """
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                break  # Out of retries

            delay = min(base_delay * (2 ** attempt), max_delay)
            if jitter:
                delay *= (0.5 + random.random() * 0.5)  # ±50% jitter

            print(f"[Retry] Attempt {attempt + 1} failed: {e}. Retrying in {delay:.2f}s")
            time.sleep(delay)

    raise last_exception


# =============================================================================
# PATTERN 5: BULKHEAD
# =============================================================================
# Isolate failures by giving each downstream service its own resource pool.
# Named after ship compartments: if one floods, others don't.
# Without bulkhead: all requests share one thread pool. Slow service B
#   exhausts all threads → service A and C also fail.
# With bulkhead: B has its own pool (10 threads). When B is slow,
#   only B's pool exhausts. A and C keep their pools, keep working.

class Bulkhead:
    """
    Thread-pool bulkhead isolating calls to a downstream service.
    Each service gets a fixed number of concurrent call slots.
    """
    def __init__(self, service_name: str, max_concurrent: int = 10):
        self.service_name = service_name
        self._semaphore = threading.Semaphore(max_concurrent)

    def call(self, func: Callable, *args, timeout: float = 5.0, **kwargs) -> Any:
        """Execute func within the bulkhead's concurrency limit."""
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            raise BulkheadFullError(
                f"Bulkhead for {self.service_name} is full. "
                f"Rejecting request to prevent cascade failure."
            )
        try:
            return func(*args, **kwargs)
        finally:
            self._semaphore.release()

class BulkheadFullError(Exception):
    pass


# =============================================================================
# PATTERN 6: SAGA PATTERN (Choreography-based)
# =============================================================================
# Problem: an order involves Order, Payment, Inventory — 3 services, 3 DBs.
#   Can't use SQL transactions across services. What if Payment succeeds but
#   Inventory fails? Need rollback logic across services.
#
# Saga: sequence of local transactions + compensating transactions.
#   Each service does its part and publishes an event.
#   On failure: previous services run compensating actions.
#
# CHOREOGRAPHY (shown here): no central coordinator. Services react to events.
#   Pros: loosely coupled.
#   Cons: hard to track overall saga state. Business logic scattered in handlers.
#
# ORCHESTRATION (alternative): central Saga Orchestrator tells each service
#   what to do and handles failures. Easier to reason about, more coupling.

class PaymentService:
    """Participates in Order Saga: charges payment, publishes result."""
    def __init__(self):
        self._event_bus = None

    def handle_order_created(self, payload: dict):
        order_id = payload["order_id"]
        total = payload["total"]
        print(f"[Payment] Processing payment of ${total} for order {order_id}")

        # Simulate payment processing (90% success rate)
        success = random.random() > 0.1
        if success:
            # Local transaction: record payment in Payment DB
            print(f"[Payment] Payment succeeded for order {order_id}")
            self._event_bus.publish("PaymentSucceeded", {"order_id": order_id})
        else:
            # Compensate: publish failure so Order Service cancels
            print(f"[Payment] Payment failed for order {order_id}")
            self._event_bus.publish("PaymentFailed", {"order_id": order_id, "reason": "Card declined"})


class InventoryService:
    """Participates in Order Saga: reserves stock after payment succeeds."""
    def __init__(self):
        self._inventory = {"ITEM_001": 100, "ITEM_002": 50}
        self._event_bus = None

    def handle_payment_succeeded(self, payload: dict):
        order_id = payload["order_id"]
        print(f"[Inventory] Reserving stock for order {order_id}")
        # Reserve stock, publish event
        self._event_bus.publish("StockReserved", {"order_id": order_id})

    def handle_payment_failed(self, payload: dict):
        # Nothing to compensate — stock was never reserved
        pass

    def compensate_release_stock(self, order_id: str):
        """Compensating transaction: release previously reserved stock."""
        print(f"[Inventory] Releasing stock for cancelled order {order_id}")


# =============================================================================
# PATTERN 7: API GATEWAY
# =============================================================================
# Single entry point for all clients. Handles cross-cutting concerns so
# individual services don't have to implement them redundantly.
#
# Responsibilities:
#   - Routing: /orders/* → Order Service, /users/* → User Service
#   - Authentication: validate JWT before request hits any service
#   - Rate limiting: protect services from overload
#   - SSL termination: services communicate internally over HTTP
#   - Request/response transformation: version translation
#   - Logging & tracing: attach correlation IDs to every request
#   - Load balancing: across service instances
#
# Products: Kong, AWS API Gateway, Nginx + Lua, Envoy, Traefik

class ApiGateway:
    """
    Simplified API Gateway demonstrating routing and auth.
    Production: Kong or AWS API Gateway handle this at infrastructure level.
    """
    def __init__(self):
        self._routes: dict[str, Any] = {}
        self._auth_required: set[str] = set()
        self._valid_tokens = {"token_alice": "user_001", "token_bob": "user_002"}

    def register_route(self, prefix: str, service, require_auth: bool = True):
        self._routes[prefix] = service
        if require_auth:
            self._auth_required.add(prefix)

    def handle(self, method: str, path: str, headers: dict, body: dict = None) -> dict:
        # 1. Find matching route
        service = None
        matched_prefix = None
        for prefix, svc in self._routes.items():
            if path.startswith(prefix):
                service = svc
                matched_prefix = prefix
                break

        if service is None:
            return {"status": 404, "error": "Route not found"}

        # 2. Auth check — validate JWT before hitting service
        if matched_prefix in self._auth_required:
            token = headers.get("Authorization", "").replace("Bearer ", "")
            if token not in self._valid_tokens:
                return {"status": 401, "error": "Invalid or missing token"}
            # Inject user_id into request context (service doesn't need to re-auth)
            if body is not None:
                body["_gateway_user_id"] = self._valid_tokens[token]

        # 3. Add correlation ID for distributed tracing
        headers["X-Correlation-ID"] = f"req_{int(time.time() * 1000)}"

        # 4. Forward to service (in reality: HTTP call to service instance)
        return {"status": 200, "forwarded_to": service.__class__.__name__, "correlation_id": headers["X-Correlation-ID"]}


# =============================================================================
# PATTERN 8: SERVICE DISCOVERY (concept demonstration)
# =============================================================================
# Services are ephemeral (containers start/stop). Hard-coded IPs don't work.
# Solution: service registry. On startup, service registers its address.
#   Other services query registry by name to find instances.
#
# Client-side discovery: service queries Consul/Eureka, picks instance itself.
# Server-side discovery: load balancer queries registry, routes traffic.
# Kubernetes: built-in DNS. "order-service" resolves to the service's ClusterIP.

class ServiceRegistry:
    """Simulates Consul or Eureka service registry."""
    def __init__(self):
        self._registry: dict[str, list[dict]] = {}

    def register(self, service_name: str, host: str, port: int, metadata: dict = None):
        instance = {"host": host, "port": port, "metadata": metadata or {}, "registered_at": time.time()}
        self._registry.setdefault(service_name, []).append(instance)
        print(f"[Registry] Registered {service_name} at {host}:{port}")

    def deregister(self, service_name: str, host: str, port: int):
        instances = self._registry.get(service_name, [])
        self._registry[service_name] = [i for i in instances if not (i["host"] == host and i["port"] == port)]

    def discover(self, service_name: str) -> list[dict]:
        """Return all healthy instances of a service."""
        return self._registry.get(service_name, [])

    def get_instance(self, service_name: str) -> Optional[dict]:
        """Return one instance (round-robin in production)."""
        instances = self.discover(service_name)
        if not instances:
            return None
        return random.choice(instances)  # Production: round-robin or least-connections


# =============================================================================
# FULL DEMO: wiring patterns together
# =============================================================================

def demo_microservices_patterns():
    print("=" * 60)
    print("MICROSERVICES PATTERNS DEMO")
    print("=" * 60)

    # Setup event bus
    bus = InMemoryEventBus()

    # Setup services
    user_svc = UserService()
    order_svc = OrderService()
    payment_svc = PaymentService()
    inventory_svc = InventoryService()

    # Wire services to event bus
    user_svc._event_bus = bus
    order_svc._event_bus = bus
    payment_svc._event_bus = bus
    inventory_svc._event_bus = bus

    # Wire saga event handlers (choreography)
    bus.subscribe("OrderCreated", payment_svc.handle_order_created)
    bus.subscribe("PaymentSucceeded", order_svc.handle_payment_succeeded)
    bus.subscribe("PaymentSucceeded", inventory_svc.handle_payment_succeeded)
    bus.subscribe("PaymentFailed", order_svc.handle_payment_failed)
    bus.subscribe("PaymentFailed", inventory_svc.handle_payment_failed)

    # Setup circuit breaker for Order → Payment sync calls (if using sync)
    cb = CircuitBreaker("payment-service", failure_threshold=3, recovery_timeout=5.0)
    bulkhead = Bulkhead("payment-service", max_concurrent=5)

    # Setup API gateway
    gateway = ApiGateway()
    gateway.register_route("/users", user_svc, require_auth=False)
    gateway.register_route("/orders", order_svc, require_auth=True)

    # Setup service registry
    registry = ServiceRegistry()
    registry.register("order-service", "10.0.1.10", 8080)
    registry.register("order-service", "10.0.1.11", 8080)
    registry.register("payment-service", "10.0.2.10", 8081)

    print("\n--- Service Discovery ---")
    order_instances = registry.discover("order-service")
    print(f"Order service instances: {len(order_instances)}")
    chosen = registry.get_instance("order-service")
    print(f"Routing to: {chosen['host']}:{chosen['port']}")

    print("\n--- API Gateway Auth ---")
    result = gateway.handle("POST", "/orders/create", {"Authorization": "Bearer invalid_token"}, {})
    print(f"Invalid token: {result}")
    result = gateway.handle("POST", "/orders/create", {"Authorization": "Bearer token_alice"}, {})
    print(f"Valid token: {result}")

    print("\n--- Saga: Order Placement ---")
    user_svc.register("user_001", "alice@example.com", "Alice")
    order_svc.create_order("order_001", "user_001", [{"sku": "ITEM_001", "qty": 2}], 59.99)

    print("\n--- Circuit Breaker Demo ---")
    def failing_call():
        raise ConnectionError("Payment service unreachable")

    for i in range(5):
        try:
            cb.call(failing_call)
        except (ConnectionError, CircuitOpenError) as e:
            print(f"  Call {i+1}: {type(e).__name__}")


if __name__ == "__main__":
    demo_microservices_patterns()

# =============================================================================
# STRANGLER FIG PATTERN (conceptual — no code needed)
# =============================================================================
# Migrate monolith gradually. Never do a big-bang rewrite.
#
# Phase 1: Put a proxy in front of the monolith
# Phase 2: Build new User Service. Route /users/* to new service.
# Phase 3: Build new Order Service. Route /orders/* to new service.
# Phase 4: Monolith only handles legacy features. Gradually extract rest.
# Phase 5: Monolith is gone.
#
# Key: the proxy is the strangler. Old monolith routes to proxy,
# which routes to new services. Monolith never knows it's being replaced.
#
# This is how Netflix, Airbnb, Amazon all migrated from monoliths.
# =============================================================================

# =============================================================================
# DATA CONSISTENCY IN MICROSERVICES
# =============================================================================
# PROBLEM: no ACID transactions across services.
#   Order Service DB and Payment Service DB are separate.
#   Can't do BEGIN TRANSACTION across both.
#
# SOLUTIONS:
#   1. Saga (shown above): sequence of local transactions + compensation
#   2. Outbox pattern: write event to same DB as business data in one transaction.
#      Separate process reads outbox and publishes to message bus.
#      Guarantees: if business data is saved, event WILL be published.
#   3. Event sourcing: state is derived from event log. Every change = event.
#      Current state = replay of all events. Natural audit log.
#
# AVOID: 2-phase commit (2PC). Requires all DBs to lock until all ACK.
#   Too slow for microservices. Brittle. One coordinator failure = all stuck.
#
# EMBRACE: eventual consistency. Accept that services may be briefly inconsistent.
#   Design UX to handle this ("Your order is being processed" not "Order confirmed").
# =============================================================================
