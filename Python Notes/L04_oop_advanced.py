# ============================================================
# L04: Advanced OOP
# ============================================================
# WHAT: Metaclasses, __init_subclass__, ABCs, Protocol,
#       dataclasses, descriptors, MRO (C3 linearization),
#       mixin patterns, and __slots__ for memory efficiency.
# WHY:  Framework and library authors use these to build
#       expressive, enforced APIs. Senior engineers use them
#       to design extensible architectures that are hard to
#       misuse. Django ORM, SQLAlchemy, Pydantic, and attrs
#       are all built on these primitives.
# LEVEL: Advanced → Architecture
# ============================================================

"""
CONCEPT OVERVIEW:
    Python's object model is far more dynamic than Java's or C#'s.
    Classes are objects too — instances of their metaclass (type
    by default). This enables declarative DSLs, ORM field
    declarations, automatic registration systems, and protocol
    enforcement.

PRODUCTION USE CASE:
    - Metaclasses: ORM table mapping, plugin registries, API validators
    - ABCs: enforced interfaces across a team's codebase
    - Protocol: structural typing without inheritance (duck typing + types)
    - Dataclasses: clean DTOs, config objects, value objects
    - Descriptors: validated attributes (age must be > 0), lazy loading
    - Mixins: composable behaviors (Serializable, Cacheable, Auditable)

COMMON MISTAKES:
    - Overusing metaclasses when __init_subclass__ suffices
    - Not understanding MRO leading to super() bugs in mixins
    - Using dataclass with mutable default (use field(default_factory=))
    - Forgetting that Protocol requires runtime_checkable for isinstance
    - Descriptors storing state on the descriptor itself (not the instance)
"""

import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable, Any, Optional
from functools import cached_property

# ============================================================
# SECTION 1: Metaclasses
# ============================================================
# WHAT: A metaclass is the class of a class. When Python creates
#       a new class, it calls the metaclass. `type` is the default.
#       type(name, bases, namespace) creates a class dynamically.
# WHY:  Metaclasses let you intercept class creation — add methods,
#       validate definitions, register subclasses automatically.
# WHEN: Prefer __init_subclass__ for most cases. Use metaclass
#       when you need to control the class object itself.

print("=== Metaclasses ===")

class RegistryMeta(type):
    """Metaclass that auto-registers all subclasses by name."""
    _registry: dict = {}

    def __new__(mcs, name: str, bases: tuple, namespace: dict):
        cls = super().__new__(mcs, name, bases, namespace)
        # Register every class created with this metaclass
        if bases:   # skip the base class itself
            mcs._registry[name] = cls
            print(f"  Registered handler: {name}")
        return cls

    def __init_subclass__(mcs, **kwargs):
        # Called when a subclass of a metaclass-using class is created
        super().__init_subclass__(**kwargs)

class BaseHandler(metaclass=RegistryMeta):
    def handle(self, event: dict) -> None:
        raise NotImplementedError

class EmailHandler(BaseHandler):
    def handle(self, event: dict) -> None:
        print(f"  EmailHandler: {event}")

class SMSHandler(BaseHandler):
    def handle(self, event: dict) -> None:
        print(f"  SMSHandler: {event}")

# Dynamic dispatch via registry — no if/elif chains
event = {"type": "EmailHandler", "to": "user@example.com"}
handler_cls = RegistryMeta._registry.get(event["type"])
if handler_cls:
    handler_cls().handle(event)

# ============================================================
# SECTION 2: __init_subclass__ — Simpler Registry
# ============================================================
# WHAT: Called on the base class when a subclass is defined.
#       Cleaner than metaclasses for most registration use cases.
# WHY:  Django-style plugin systems, codec registries, command patterns.

print("\n=== __init_subclass__ ===")

class Plugin:
    """Base class that auto-registers subclasses."""
    _plugins: ClassVar[dict] = {}

    def __init_subclass__(cls, plugin_name: str = "", **kwargs):
        super().__init_subclass__(**kwargs)
        name = plugin_name or cls.__name__
        Plugin._plugins[name] = cls
        print(f"  Plugin registered: {name}")

class JSONPlugin(Plugin, plugin_name="json"):
    def serialize(self, data): return str(data)

class XMLPlugin(Plugin, plugin_name="xml"):
    def serialize(self, data): return f"<data>{data}</data>"

print(f"  Available plugins: {list(Plugin._plugins.keys())}")

# ============================================================
# SECTION 3: Abstract Base Classes (ABC)
# ============================================================
# WHAT: ABCs define interfaces that subclasses MUST implement.
#       Attempting to instantiate a class with unimplemented
#       abstract methods raises TypeError.
# WHY:  Enforces contracts across a team. Better than duck typing
#       when you want explicit interface guarantees.

print("\n=== Abstract Base Classes ===")

class DataStore(ABC):
    """Abstract interface for a key-value store."""

    @abstractmethod
    def get(self, key: str) -> Any:
        """Retrieve value by key. Returns None if not found."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store value. ttl = seconds until expiry."""
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete key. Returns True if existed."""
        ...

    # Concrete method on ABC — shared implementation
    def get_or_default(self, key: str, default: Any) -> Any:
        result = self.get(key)
        return result if result is not None else default

class InMemoryStore(DataStore):
    """In-process store for testing / local dev."""
    def __init__(self):
        self._data: dict = {}
        self._expiry: dict = {}

    def get(self, key: str) -> Any:
        if key in self._expiry and time.time() > self._expiry[key]:
            del self._data[key]
            del self._expiry[key]
            return None
        return self._data.get(key)

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self._data[key] = value
        if ttl:
            self._expiry[key] = time.time() + ttl

    def delete(self, key: str) -> bool:
        existed = key in self._data
        self._data.pop(key, None)
        return existed

store = InMemoryStore()
store.set("user:1", {"name": "Alice"})
print(f"  get user:1 : {store.get('user:1')}")
print(f"  get_or_def : {store.get_or_default('user:99', {'name': 'Guest'})}")
print(f"  delete     : {store.delete('user:1')}")

# Cannot instantiate ABC directly:
try:
    DataStore()
except TypeError as e:
    print(f"  Cannot instantiate ABC: {e}")

# ============================================================
# SECTION 4: Protocol — Structural Subtyping (Duck Typing + Types)
# ============================================================
# WHAT: Protocol defines an interface by structure, not inheritance.
#       Any class with the right methods satisfies the Protocol,
#       no explicit inheritance needed.
# WHY:  Python is duck-typed. Protocol makes duck typing explicit
#       and checkable by mypy/pyright without forcing inheritance.
# NOTE: Add @runtime_checkable for isinstance() checks.

print("\n=== Protocol (Structural Typing) ===")

@runtime_checkable
class Drawable(Protocol):
    def draw(self, canvas: Any) -> None: ...
    def bounding_box(self) -> tuple: ...

class Circle:
    """No inheritance from Drawable — satisfies it structurally."""
    def __init__(self, x, y, r):
        self.x, self.y, self.r = x, y, r

    def draw(self, canvas):
        print(f"  Drawing circle at ({self.x},{self.y}) r={self.r}")

    def bounding_box(self):
        return (self.x - self.r, self.y - self.r,
                self.x + self.r, self.y + self.r)

c = Circle(0, 0, 5)
print(f"  Circle is Drawable: {isinstance(c, Drawable)}")   # True at runtime
print(f"  bounding_box: {c.bounding_box()}")

# ============================================================
# SECTION 5: Dataclasses
# ============================================================
# WHAT: @dataclass auto-generates __init__, __repr__, __eq__,
#       and optionally __hash__, __lt__, etc.
# WHY:  Eliminates boilerplate for data-holding classes (DTOs,
#       config objects, events, value objects).
# COMMON MISTAKES:
#   - `field(default=[])` → correct: `field(default_factory=list)`
#   - Using dataclass for objects with complex behavior (prefer regular class)
#   - Not using frozen=True for immutable value objects

print("\n=== Dataclasses ===")

@dataclass(frozen=True, slots=True)   # immutable + memory efficient
class Money:
    """Value object: immutable, hashable, comparable."""
    amount: int          # in cents to avoid float precision issues
    currency: str = "USD"

    def __post_init__(self):
        # Validation after auto-generated __init__
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")
        if len(self.currency) != 3:
            raise ValueError(f"Currency must be 3-letter ISO code: {self.currency}")

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(self.amount + other.amount, self.currency)

    @property
    def as_decimal(self) -> str:
        return f"{self.amount / 100:.2f}"

m1 = Money(1000, "USD")   # $10.00
m2 = Money(500, "USD")    # $5.00
m3 = m1 + m2
print(f"  {m1} + {m2} = {m3}")
print(f"  as decimal: ${m3.as_decimal}")
print(f"  hashable (usable as dict key): {hash(m1)}")

# Mutable dataclass with factory defaults
@dataclass
class APIRequest:
    path: str
    method: str = "GET"
    headers: dict = field(default_factory=dict)   # CORRECT: factory
    params: list  = field(default_factory=list)   # CORRECT: factory
    timeout: float = 30.0

    # ClassVar: shared across instances, not part of __init__
    base_url: ClassVar[str] = "https://api.example.com"

req = APIRequest("/users", headers={"Authorization": "Bearer tok"})
print(f"  request: {req}")

# ============================================================
# SECTION 6: Descriptors
# ============================================================
# WHAT: A descriptor is any object that implements __get__,
#       __set__, or __delete__. Accessed as a class attribute,
#       it intercepts attribute access on instances.
# WHY:  Django model fields, SQLAlchemy columns, property(),
#       staticmethod(), classmethod() are all descriptors.
# CRITICAL: Store state on the INSTANCE (using self.name or a
#       WeakKeyDictionary), NEVER on the descriptor object itself.

print("\n=== Descriptors ===")

class Validated:
    """Generic validated attribute descriptor."""

    def __set_name__(self, owner, name: str):
        # Called when the class is created — gives us the attribute name
        self.public_name  = name
        self.private_name = '_' + name  # store on instance with mangled name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self   # class-level access returns the descriptor itself
        return getattr(obj, self.private_name, None)

    def __set__(self, obj, value):
        self.validate(value)
        setattr(obj, self.private_name, value)

    def validate(self, value):
        pass   # override in subclasses

class PositiveInt(Validated):
    def validate(self, value):
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"Expected positive int, got {value!r}")

class NonEmptyStr(Validated):
    def validate(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Expected non-empty string, got {value!r}")

class User:
    name = NonEmptyStr()
    age  = PositiveInt()

    def __init__(self, name: str, age: int):
        self.name = name   # triggers NonEmptyStr.__set__
        self.age  = age    # triggers PositiveInt.__set__

    def __repr__(self):
        return f"User(name={self.name!r}, age={self.age})"

u = User("Alice", 30)
print(f"  user: {u}")

try:
    User("", 30)
except ValueError as e:
    print(f"  validation error: {e}")

try:
    User("Bob", -5)
except ValueError as e:
    print(f"  validation error: {e}")

# cached_property: computed once, then stored as instance attribute
class DataProcessor:
    def __init__(self, data: list):
        self.data = data

    @cached_property
    def statistics(self) -> dict:
        """Expensive computation — cached after first access."""
        print("  Computing statistics...")
        n = len(self.data)
        mean = sum(self.data) / n
        return {"n": n, "mean": mean, "sum": sum(self.data)}

dp = DataProcessor([1, 2, 3, 4, 5])
print(f"  stats (first access):  {dp.statistics}")
print(f"  stats (second access): {dp.statistics}")  # no recompute

# ============================================================
# SECTION 7: MRO — C3 Linearization
# ============================================================
# WHAT: Method Resolution Order determines which method is called
#       when multiple inheritance is involved. Python uses C3
#       linearization (not depth-first or breadth-first).
# WHY:  Understanding MRO prevents super() calling the wrong class.
#       Critical when using mixins.

print("\n=== MRO (C3 Linearization) ===")

class A:
    def who(self): return "A"

class B(A):
    def who(self): return f"B → {super().who()}"

class C(A):
    def who(self): return f"C → {super().who()}"

class D(B, C):
    def who(self): return f"D → {super().who()}"

d = D()
print(f"  D().who()  = {d.who()}")         # D → B → C → A
print(f"  D.__mro__ = {[c.__name__ for c in D.__mro__]}")

# ============================================================
# SECTION 8: Mixin Pattern
# ============================================================
# WHAT: Mixins are small classes that provide a reusable behavior
#       to be mixed into other classes via multiple inheritance.
# WHY:  Composable behaviors: Serializable, Cacheable, Auditable,
#       LoggableMixin — applied to any model without duplication.
# CONVENTION: Mixin class names end in "Mixin". They should not
#       have __init__ or call super().__init__() improperly.

print("\n=== Mixin Pattern ===")

class TimestampMixin:
    """Adds created_at and updated_at to any model."""
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def touch(self):
        self.updated_at = time.time()

class SerializeMixin:
    """Adds JSON-like dict serialization to any dataclass-style object."""
    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()
                if not k.startswith('_')}

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)

class AuditMixin:
    """Tracks who created/modified a record."""
    _current_user: ClassVar[Optional[str]] = None

    def record_change(self, action: str):
        user = self.__class__._current_user or "system"
        print(f"  AUDIT: {action} by {user} on {type(self).__name__}")

class Product(TimestampMixin, SerializeMixin, AuditMixin):
    def __init__(self, name: str, price: float):
        self.name  = name
        self.price = price
        self.updated_at = time.time()

p = Product("Widget", 9.99)
p.touch()
p.record_change("UPDATE")
print(f"  product dict: {p.to_dict()}")
restored = Product.from_dict({"name": "Widget", "price": 9.99})
print(f"  restored: name={restored.name}, price={restored.price}")

# ============================================================
# SECTION 9: Summary
# ============================================================
print("\n=== Key Takeaways ===")
print("""
  metaclass         → Control class creation; use for ORMs/plugin registries
  __init_subclass__ → Simpler auto-registration without full metaclass
  ABC               → Enforced interfaces; TypeError on incomplete impl
  Protocol          → Structural typing; no inheritance required
  @dataclass        → Clean DTOs; use frozen=True for value objects
  field(default_factory=list) → Correct mutable default in dataclass
  Descriptors       → Validated attributes; store state on INSTANCE
  cached_property   → Lazy compute once, then cached on instance
  MRO / C3          → super() follows linearized order, not raw base order
  Mixins            → Composable behaviors; name ends in 'Mixin'
""")
