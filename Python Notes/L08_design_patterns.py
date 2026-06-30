# ============================================================
# L08: Design Patterns in Python
# ============================================================
# WHAT: Gang of Four and modern patterns adapted for Python,
#       including SOLID principles and resilience patterns.
# WHY:  Design patterns are a shared vocabulary for solving
#       recurring structural problems. Knowing them lets you
#       communicate "use a Strategy here" instead of explaining
#       a 3-paragraph architectural decision every time.
# LEVEL: Advanced
# ============================================================
"""
CONCEPT OVERVIEW:
    Design patterns are NOT rules — they are templates for solving
    SPECIFIC recurring problems. The wrong pattern is worse than
    no pattern. The key is recognizing the problem structure that
    each pattern addresses.

    Python makes many classical patterns simpler:
      - Strategy → just pass a function (first-class functions)
      - Command → just use a callable
      - Iterator → just use __iter__/__next__ or generators
      - Decorator → @ syntax is built into the language

    But some patterns are MORE important in Python due to its
    dynamic nature (Singleton's thread-safety pitfalls are real,
    Repository makes testing possible when you can't mock easily).

PRODUCTION USE CASE:
    A fintech platform uses:
      - Repository: swap real DB for in-memory in 20k unit tests
      - Circuit Breaker: wraps all third-party API calls
      - Strategy: pluggable pricing engines per product type
      - Observer: event bus for microservice communication
      - Builder: constructing complex SQL queries fluently

COMMON MISTAKES:
    - Implementing Singleton everywhere (it's global state)
    - Using Decorator pattern when Python's @ decorator is enough
    - Making Abstract Factories before you have more than one concrete factory
    - Forgetting weakref in Observer → memory leaks with long-lived subjects
    - Not using dependency injection → untestable code
"""

import weakref
import time
import random
from abc import ABC, abstractmethod
from typing import Callable, Optional, List, Any
from enum import Enum, auto
from dataclasses import dataclass, field


# ============================================================
# SECTION 1: Singleton — and WHY TO AVOID IT
# ============================================================
# Singleton ensures only one instance of a class exists.
# The canonical Python implementation uses __new__.
#
# WHY TO AVOID:
#   1. Global state: any code anywhere can modify the singleton.
#      Bugs caused by one module's changes affect another module —
#      impossible to reason about locally.
#   2. Testing nightmare: tests share the same instance, so one
#      test's state leaks into the next. You must reset the
#      singleton manually, which is fragile.
#   3. Hidden coupling: callers don't declare they need it
#      (it's not in the function signature), so you can't see
#      the dependency graph.
#
# ALTERNATIVE: Dependency Injection. Create ONE instance at the
# application entry point (main.py) and pass it to everything
# that needs it. Same effect (one instance), testable, explicit.

class BadSingleton:
    """
    Textbook singleton. Don't do this in production.
    Shown here so you recognize (and avoid) the pattern.
    """
    _instance: Optional['BadSingleton'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.data = {}
            self._initialized = True

# PREFERRED ALTERNATIVE: module-level instance created once
# In config.py:
#   _config = Config(path="config.yaml")
#   def get_config() -> Config:
#       return _config
# This IS a singleton in practice but testable — tests can
# call the internal _config and replace it if needed.


# ============================================================
# SECTION 2: Factory — create objects without knowing the class
# ============================================================
# Factory is a function (or class method) that returns instances
# of different subclasses based on a parameter.
#
# WHY: callers shouldn't know which concrete class to instantiate.
# The factory encapsulates the "which class?" decision.
# Adding a new type only requires changing the factory.

class Notifier(ABC):
    @abstractmethod
    def send(self, recipient: str, message: str) -> bool:
        """Send a notification. Returns True on success."""
        ...

class EmailNotifier(Notifier):
    def send(self, recipient: str, message: str) -> bool:
        print(f"[EMAIL] To: {recipient} | {message}")
        return True

class SMSNotifier(Notifier):
    def send(self, recipient: str, message: str) -> bool:
        print(f"[SMS] To: {recipient} | {message}")
        return True

class PushNotifier(Notifier):
    def send(self, recipient: str, message: str) -> bool:
        print(f"[PUSH] Device: {recipient} | {message}")
        return True

class NotificationFactory:
    """
    Factory: callers say WHAT channel they want, not HOW to build it.
    Adding 'slack' channel = add one class + one elif here.
    """
    _registry: dict[str, type[Notifier]] = {
        'email': EmailNotifier,
        'sms':   SMSNotifier,
        'push':  PushNotifier,
    }

    @classmethod
    def create(cls, channel: str) -> Notifier:
        klass = cls._registry.get(channel.lower())
        if klass is None:
            raise ValueError(f"Unknown notification channel: {channel!r}. "
                             f"Valid: {list(cls._registry.keys())}")
        return klass()

    @classmethod
    def register(cls, channel: str, klass: type[Notifier]) -> None:
        """Extension point: register new channel types at runtime."""
        cls._registry[channel] = klass


# ============================================================
# SECTION 3: Abstract Factory — factory of factories
# ============================================================
# When you have multiple FAMILIES of related objects that must
# be used together, Abstract Factory ensures consistency.
# Example: all components from the AWS family, or all from GCS.
# You never mix an S3Bucket with a GCSQueue.

class StorageBucket(ABC):
    @abstractmethod
    def upload(self, key: str, data: bytes) -> str: ...
    @abstractmethod
    def download(self, key: str) -> bytes: ...

class MessageQueue(ABC):
    @abstractmethod
    def publish(self, topic: str, message: str) -> None: ...

class CloudFactory(ABC):
    """Abstract factory: produces a FAMILY of cloud components."""
    @abstractmethod
    def create_bucket(self, name: str) -> StorageBucket: ...
    @abstractmethod
    def create_queue(self) -> MessageQueue: ...

# Concrete families (stub implementations for illustration)
class S3Bucket(StorageBucket):
    def __init__(self, name): self.name = name
    def upload(self, key, data): return f"s3://{self.name}/{key}"
    def download(self, key): return b""

class SQSQueue(MessageQueue):
    def publish(self, topic, message): print(f"SQS: {topic}: {message}")

class AWSFactory(CloudFactory):
    def create_bucket(self, name): return S3Bucket(name)
    def create_queue(self): return SQSQueue()

# Usage: the application only sees CloudFactory — swap AWS for GCS
# by changing ONE line at startup.
def setup_infrastructure(factory: CloudFactory):
    bucket = factory.create_bucket("my-data")
    queue  = factory.create_queue()
    return bucket, queue


# ============================================================
# SECTION 4: Builder — fluent step-by-step construction
# ============================================================
# Use Builder when an object requires many optional parameters,
# or when construction has multiple meaningful steps.
# The fluent interface (method chaining) reads like a DSL.
#
# vs just using keyword arguments: Builder is better when:
#   - Construction involves validation between steps
#   - Some params are computed from others
#   - You want to reuse partial configurations

@dataclass
class HTTPRequest:
    url: str
    method: str
    headers: dict
    timeout: float
    retries: int
    body: Optional[bytes]

class HTTPRequestBuilder:
    """
    Fluent builder for HTTPRequest.
    Each method returns self, enabling chaining:
      req = HTTPRequestBuilder("https://api.example.com/data")
               .with_method("POST")
               .with_timeout(30)
               .with_retry(3)
               .with_header("Authorization", "Bearer token")
               .build()
    """
    def __init__(self, url: str):
        self._url = url
        self._method = "GET"
        self._headers: dict = {}
        self._timeout: float = 10.0
        self._retries: int = 0
        self._body: Optional[bytes] = None

    def with_method(self, method: str) -> 'HTTPRequestBuilder':
        self._method = method.upper()
        return self

    def with_timeout(self, seconds: float) -> 'HTTPRequestBuilder':
        if seconds <= 0:
            raise ValueError("Timeout must be positive")
        self._timeout = seconds
        return self

    def with_retry(self, count: int) -> 'HTTPRequestBuilder':
        self._retries = count
        return self

    def with_header(self, key: str, value: str) -> 'HTTPRequestBuilder':
        self._headers[key] = value
        return self

    def with_json_body(self, data: dict) -> 'HTTPRequestBuilder':
        import json
        self._body = json.dumps(data).encode()
        self._headers['Content-Type'] = 'application/json'
        return self

    def build(self) -> HTTPRequest:
        if self._method in ('POST', 'PUT', 'PATCH') and self._body is None:
            raise ValueError(f"{self._method} request requires a body")
        return HTTPRequest(
            url=self._url, method=self._method, headers=self._headers,
            timeout=self._timeout, retries=self._retries, body=self._body
        )


# ============================================================
# SECTION 5: Observer — event-driven communication
# ============================================================
# Subject (publisher) maintains a list of observers (subscribers)
# and notifies them when state changes.
#
# KEY DETAIL: use weakref.WeakSet for the subscriber list.
# If you use a regular set/list, the subject HOLDS a strong
# reference to each subscriber, preventing garbage collection
# even after the subscriber is otherwise unused → memory leak.
# WeakSet allows subscribers to be GC'd when no other references
# exist — the WeakSet automatically removes the dead reference.

class EventBus:
    """
    Simple in-process event bus.
    Subscribers register callables; they're notified on publish().
    Uses WeakSet to avoid keeping dead subscribers alive.
    """
    def __init__(self):
        # topic → set of weak references to callbacks
        self._subscribers: dict[str, weakref.WeakSet] = {}

    def subscribe(self, topic: str, callback: Callable) -> None:
        if topic not in self._subscribers:
            self._subscribers[topic] = weakref.WeakSet()
        self._subscribers[topic].add(callback)

    def publish(self, topic: str, event: dict) -> None:
        for callback in self._subscribers.get(topic, set()):
            try:
                callback(event)
            except Exception as e:
                # Never let one bad subscriber crash the whole bus
                print(f"[EventBus] Subscriber error on {topic!r}: {e}")

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        if topic in self._subscribers:
            self._subscribers[topic].discard(callback)


# ============================================================
# SECTION 6: Strategy — swappable algorithms
# ============================================================
# Strategy pattern: define a family of algorithms, encapsulate
# each one, make them interchangeable. The context object
# doesn't know which algorithm it's running.
#
# Python natural fit: since functions are first-class objects,
# you can often just PASS A FUNCTION instead of a Strategy class.
# Classes are better when the strategy has its own state or config.

# Function-based strategy (Pythonic)
PricingStrategy = Callable[[float, int], float]   # (unit_price, qty) → total

def standard_pricing(unit_price: float, qty: int) -> float:
    return unit_price * qty

def bulk_discount(unit_price: float, qty: int) -> float:
    """10% discount for orders over 100 units."""
    total = unit_price * qty
    if qty > 100:
        total *= 0.90
    return total

def tiered_pricing(unit_price: float, qty: int) -> float:
    """Decreasing unit price as volume increases."""
    if qty < 10:   return unit_price * qty
    if qty < 100:  return unit_price * qty * 0.95
    return unit_price * qty * 0.85

class OrderPricer:
    """Context: uses whatever strategy is injected."""
    def __init__(self, strategy: PricingStrategy):
        self._strategy = strategy

    def calculate(self, unit_price: float, qty: int) -> float:
        return self._strategy(unit_price, qty)

    def set_strategy(self, strategy: PricingStrategy) -> None:
        """Change algorithm at runtime — e.g., during a flash sale."""
        self._strategy = strategy


# ============================================================
# SECTION 7: Command — encapsulate actions with undo/redo
# ============================================================
# Command turns an action into an object, enabling:
#   - Undo/redo: keep a stack of executed commands, call undo()
#   - Job queue: serialize commands, execute later or in a worker
#   - Audit log: every command is logged with its parameters

class Command(ABC):
    @abstractmethod
    def execute(self) -> Any: ...
    @abstractmethod
    def undo(self) -> None: ...

class CommandHistory:
    """Maintains an undo stack of executed commands."""
    def __init__(self):
        self._history: List[Command] = []

    def execute(self, command: Command) -> Any:
        result = command.execute()
        self._history.append(command)
        return result

    def undo(self) -> None:
        if not self._history:
            raise IndexError("Nothing to undo")
        self._history.pop().undo()

# Example: text editor commands
class InsertTextCommand(Command):
    def __init__(self, document: list, position: int, text: str):
        self._doc = document
        self._pos = position
        self._text = text

    def execute(self) -> None:
        self._doc.insert(self._pos, self._text)

    def undo(self) -> None:
        self._doc.pop(self._pos)


# ============================================================
# SECTION 8: Repository — abstract data access
# ============================================================
# Repository provides a collection-like interface for accessing
# domain objects. Callers use save/find/delete without knowing
# whether the data is in PostgreSQL, DynamoDB, or memory.
#
# WHY IT MATTERS FOR TESTING:
# If your service creates a database connection internally, you
# cannot test it without a real database. If it accepts a
# Repository, you inject an InMemoryUserRepository in tests →
# 10ms per test instead of 1000ms.

class UserRepo(ABC):
    @abstractmethod
    def save(self, user) -> 'UserEntity': ...
    @abstractmethod
    def find_by_id(self, user_id: int) -> Optional['UserEntity']: ...
    @abstractmethod
    def delete(self, user_id: int) -> None: ...

@dataclass
class UserEntity:
    id: Optional[int]
    email: str
    name: str

class InMemoryUserRepo(UserRepo):
    """
    Test double: fast, no DB required.
    Swap this in tests by injecting it into the service.
    """
    def __init__(self):
        self._store: dict[int, UserEntity] = {}
        self._next_id: int = 1

    def save(self, user: UserEntity) -> UserEntity:
        if user.id is None:
            user = UserEntity(id=self._next_id, email=user.email, name=user.name)
            self._next_id += 1
        self._store[user.id] = user
        return user

    def find_by_id(self, user_id: int) -> Optional[UserEntity]:
        return self._store.get(user_id)

    def delete(self, user_id: int) -> None:
        self._store.pop(user_id, None)


# ============================================================
# SECTION 9: Dependency Injection
# ============================================================
# DI: pass dependencies as constructor arguments instead of
# creating them inside the class.
#
# WITHOUT DI (bad):
#   class OrderService:
#       def __init__(self):
#           self._db = PostgresDB("postgresql://...")  # hardcoded!
#           self._emailer = SMTPEmailer("smtp.gmail.com")
#           # Now you CANNOT test this without a real DB and SMTP server
#
# WITH DI (good):
#   class OrderService:
#       def __init__(self, db: OrderRepo, emailer: Emailer):
#           self._db = db
#           self._emailer = emailer
#           # Tests inject InMemoryOrderRepo() + Mock() — instant, no infra

class EmailerABC(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None: ...

class OrderService:
    """
    Properly injected. All dependencies visible in __init__.
    Test by passing mocks/in-memory implementations.
    """
    def __init__(self, user_repo: UserRepo, emailer: EmailerABC):
        self._user_repo = user_repo
        self._emailer = emailer

    def create_order(self, user_id: int, items: list) -> dict:
        user = self._user_repo.find_by_id(user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        # ... business logic ...
        self._emailer.send(user.email, "Order Confirmation", "Your order is placed.")
        return {"user": user.name, "items": items}


# ============================================================
# SECTION 10: SOLID Principles in Python
# ============================================================

# S — Single Responsibility: one class, one reason to change.
# BAD: UserManager does auth + profile + email + reporting
# GOOD: UserAuthService, UserProfileService, each small and focused.

# O — Open/Closed: open for extension, closed for modification.
# Add new behavior by subclassing or injecting, not by editing.
# The NotificationFactory.register() above is an example.

# L — Liskov Substitution: a subclass must honor the contract of
# the base class. If Bird has fly(), and Penguin(Bird) raises
# NotImplementedError on fly(), that's a violation — code using
# Bird.fly() breaks when given a Penguin.
# Fix: separate FlyingBird(Bird) from flightless birds.

# I — Interface Segregation: small, focused interfaces over fat ones.
# Python uses Protocol (structural subtyping) instead of forcing
# inheritance from an abstract class.

from typing import Protocol, runtime_checkable

@runtime_checkable
class Readable(Protocol):
    def read(self, n: int = -1) -> bytes: ...

@runtime_checkable
class Writable(Protocol):
    def write(self, data: bytes) -> int: ...

# A function that needs only reading accepts Readable,
# not a combined ReadWriteSeekable — no forced interface.
def read_all(stream: Readable) -> bytes:
    return stream.read()

# D — Dependency Inversion: depend on abstractions (ABC/Protocol),
# not concrete classes. OrderService above depends on UserRepo(ABC),
# not PostgresUserRepo — this IS dependency inversion.


# ============================================================
# SECTION 11: Circuit Breaker — resilience pattern
# ============================================================
# Wraps external calls and "trips" (opens) when failures exceed
# a threshold, preventing cascading failures and giving downstream
# services time to recover.
#
# States:
#   CLOSED    → normal operation; failures are counted
#   OPEN      → all calls fail immediately (fail-fast); no actual calls made
#   HALF-OPEN → after a timeout, one test call is allowed through;
#               if it succeeds → back to CLOSED; if it fails → back to OPEN
#
# WHY: without circuit breaker, if an external API is down for 30s,
# your service queues up 10,000 requests waiting to time out (30s each),
# exhausting threads/connections and taking DOWN your own service.
# With circuit breaker: after 5 failures, all calls fail in <1ms.

class CircuitState(Enum):
    CLOSED    = auto()    # normal, calls pass through
    OPEN      = auto()    # tripped, calls fail immediately
    HALF_OPEN = auto()    # testing if service recovered

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,    # needed in HALF_OPEN before closing
    ):
        self._failure_threshold  = failure_threshold
        self._recovery_timeout   = recovery_timeout
        self._success_threshold  = success_threshold
        self._state              = CircuitState.CLOSED
        self._failure_count      = 0
        self._success_count      = 0
        self._last_failure_time  = 0.0

    def call(self, func: Callable, *args, **kwargs) -> Any:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time > self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
            else:
                raise RuntimeError("Circuit breaker OPEN — call rejected")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        else:
            self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN


# ============================================================
# SECTION 12: Retry with exponential backoff + jitter
# ============================================================
# Exponential backoff: double the wait time after each failure.
# Jitter: add random noise to the wait time.
#
# WHY JITTER: without it, all retrying clients back off to the
# SAME schedule. After 1s they all retry simultaneously → thundering
# herd → all fail again → all wait 2s → all retry → repeat.
# Jitter staggers retries so the server recovers instead of
# getting hammered by synchronized bursts.
#
# Standard formula: min(cap, base * 2^attempt) * random(0.5, 1.5)

def retry_with_backoff(
    func: Callable,
    max_attempts: int = 5,
    base_delay: float = 0.1,   # 100ms initial delay
    max_delay: float = 30.0,   # cap at 30 seconds
    jitter: float = 0.5,       # ±50% random variation
    exceptions: tuple = (Exception,),
) -> Any:
    """
    Retry func with exponential backoff and full jitter.
    Only retries on the specified exception types.
    """
    for attempt in range(max_attempts):
        try:
            return func()
        except exceptions as e:
            if attempt == max_attempts - 1:
                raise   # exhausted all retries, re-raise original

            # Exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s ...
            delay = min(max_delay, base_delay * (2 ** attempt))
            # Full jitter: uniformly random between 0 and the delay
            sleep_time = delay * random.uniform(1 - jitter, 1 + jitter)
            print(f"Attempt {attempt + 1} failed ({e}). "
                  f"Retrying in {sleep_time:.2f}s...")
            time.sleep(sleep_time)


# ============================================================
# QUICK REFERENCE
# ============================================================
# Pattern          Problem it solves                   Python note
# ─────────────────────────────────────────────────────────────────
# Singleton        One shared instance                 Avoid; use DI
# Factory          Hide concrete class selection       Simple function
# Abstract Factory Consistent family of objects        ABC + subclasses
# Builder          Complex object with many options    Method chaining
# Observer         Decouple event source from handlers WeakSet for GC
# Strategy         Swappable algorithm                 Just use functions
# Command          Action as object (undo/audit)       Callable + history
# Repository       Abstract data access for testing    ABC + in-memory impl
# Circuit Breaker  Prevent cascading failures          State machine
# Retry+Backoff    Transient failure recovery          +jitter mandatory
# ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Factory demo
    notifier = NotificationFactory.create('email')
    notifier.send("alice@example.com", "Your order shipped!")

    # Builder demo
    req = (HTTPRequestBuilder("https://api.example.com/users")
           .with_method("GET")
           .with_timeout(5.0)
           .with_retry(3)
           .with_header("Authorization", "Bearer abc123")
           .build())
    print(f"Built request: {req.method} {req.url} timeout={req.timeout}s")

    # Strategy demo
    pricer = OrderPricer(strategy=bulk_discount)
    print(f"150 units @ $10 with bulk discount: ${pricer.calculate(10, 150):.2f}")

    # Repository + DI demo
    repo = InMemoryUserRepo()
    user = repo.save(UserEntity(id=None, email="bob@example.com", name="Bob"))
    print(f"Saved user: {repo.find_by_id(user.id)}")

    # Circuit breaker demo
    cb = CircuitBreaker(failure_threshold=3)
    print(f"Circuit state: {cb._state.name}")
