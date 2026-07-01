# =============================================================================
# WHAT: API Versioning Strategies and OpenAPI 3.1 Specification
# WHY:  APIs evolve. Without versioning you break clients on every change.
#       OpenAPI gives you machine-readable contracts — docs, mocks, and
#       client SDKs all generated automatically from one source of truth.
# LEVEL: Intermediate → Advanced
# =============================================================================
#
# CONCEPT OVERVIEW
# ----------------
# Versioning answers: "how do clients opt into a new API contract?"
# Three mainstream strategies:
#   1. URL path   — /v1/users   (most visible, easiest to route)
#   2. Header     — Accept: application/vnd.myapi+json;version=2
#   3. Query param — GET /users?version=2  (least RESTful, fine for internal)
#
# OpenAPI 3.1 (aligned with JSON Schema draft 2020-12) is the standard for
# describing REST APIs. FastAPI generates it automatically from Python types.
#
# PRODUCTION USE CASE
# -------------------
# Stripe maintains /v1/ indefinitely while evolving the schema with additive
# changes. GitHub uses URL versioning plus Sunset headers to give clients
# 12-month deprecation windows. Your internal platform team publishes an
# OpenAPI spec that feeds: Swagger UI (devs), Prism (mock server),
# oapi-codegen (Go client), and openapi-typescript (frontend types).
#
# COMMON MISTAKES
# ---------------
# 1. Removing a field without a deprecation period → instant client breakage
# 2. Changing a field type (string → int) inside the same version → breaking
# 3. Forgetting Sunset / Deprecation response headers → clients never know
# 4. Putting v2 on a breaking PATCH-level change → wastes a version number
# 5. Hand-editing OpenAPI YAML then letting it drift from the actual code
# =============================================================================

# ---------------------------------------------------------------------------
# Standard library imports
# ---------------------------------------------------------------------------
import json
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Any, Optional, Union
import subprocess  # for running CLI tools shown as examples

# ---------------------------------------------------------------------------
# Third-party imports (pip install fastapi uvicorn pydantic)
# ---------------------------------------------------------------------------
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# CLI commands referenced throughout this file (shown as string constants
# so the file is importable without these tools installed)
# ---------------------------------------------------------------------------
CMD_INSTALL = "pip install fastapi uvicorn pydantic openapi-spec-validator"
CMD_RUN_DEV = "uvicorn main:app --reload --port 8000"
CMD_VALIDATE_SPEC = "openapi-spec-validator openapi.yaml"
# Spectral is the gold-standard OpenAPI linter
CMD_SPECTRAL_LINT = "npx @stoplight/spectral-cli lint openapi.yaml"
# Bundle a multi-file OpenAPI spec into one file
CMD_REDOCLY_BUNDLE = "npx @redocly/cli bundle openapi/root.yaml -o dist/openapi.yaml"


# =============================================================================
# PART 1 — URL PATH VERSIONING
# =============================================================================
# Most discoverable strategy. The version is right in the URL so curl commands,
# browser tabs, and server logs all show it without extra config.
# Router prefixes in FastAPI make this trivial.
# =============================================================================

# Create separate FastAPI routers for each major version
from fastapi import APIRouter

router_v1 = APIRouter(prefix="/v1", tags=["v1"])
router_v2 = APIRouter(prefix="/v2", tags=["v2"])


# V1 user model — the original contract
class UserV1(BaseModel):
    id: int
    name: str          # V1: name is a single string
    email: str


# V2 user model — breaking change (name split into first/last)
# This MUST go behind /v2 because existing /v1 clients break if we mutate
class UserV2(BaseModel):
    id: int
    first_name: str    # V2 splits name into two fields
    last_name: str
    email: str
    created_at: datetime  # V2 adds an audit field (non-breaking addition within v2)


# V1 endpoint — stays frozen once published
@router_v1.get("/users/{user_id}", response_model=UserV1)
async def get_user_v1(user_id: int) -> UserV1:
    # In real code: query the DB and return V1 shape
    return UserV1(id=user_id, name="Alice Smith", email="alice@example.com")


# V2 endpoint — new contract; clients must explicitly opt in
@router_v2.get("/users/{user_id}", response_model=UserV2)
async def get_user_v2(user_id: int) -> UserV2:
    return UserV2(
        id=user_id,
        first_name="Alice",
        last_name="Smith",
        email="alice@example.com",
        created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )


# Mount both routers on a single FastAPI app
app = FastAPI(
    title="Versioned API Demo",
    version="2.0.0",
    # docs_url shows Swagger UI; redoc_url shows ReDoc
    docs_url="/docs",
    redoc_url="/redoc",
)
app.include_router(router_v1)
app.include_router(router_v2)


# =============================================================================
# PART 2 — HEADER-BASED VERSIONING
# =============================================================================
# Keeps URLs clean. Standard approach: use a vendor media type in Accept header.
# Downside: invisible in browser address bars, harder to test with curl.
# Used by GitHub (X-GitHub-Api-Version header) and some AWS services.
# =============================================================================

SUPPORTED_VERSIONS = {"1", "2"}
CURRENT_VERSION = "2"
DEPRECATED_VERSIONS = {"1"}  # versions still functional but sunset-scheduled

# Sunset date for v1 — must be at least 6–12 months out in prod
SUNSET_DATE_V1 = "Mon, 31 Dec 2025 23:59:59 GMT"  # RFC 7231 date format


@app.get("/users/{user_id}/header-versioned")
async def get_user_header_versioned(
    user_id: int,
    # Client sends: Accept: application/vnd.myapi+json;version=2
    accept: str = Header(default="application/vnd.myapi+json;version=2"),
    response: Response = None,
) -> dict:
    # Parse version out of the Accept header value
    version_match = re.search(r"version=(\d+)", accept)
    version = version_match.group(1) if version_match else CURRENT_VERSION

    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(
            status_code=406,  # 406 Not Acceptable is semantically correct
            detail=f"Unsupported version: {version}. Supported: {SUPPORTED_VERSIONS}",
        )

    # Attach deprecation signals to the response headers
    if version in DEPRECATED_VERSIONS:
        # Sunset header (RFC 8594): machine-readable date when the API goes dark
        response.headers["Sunset"] = SUNSET_DATE_V1
        # Deprecation header (RFC draft): signals this version is deprecated NOW
        response.headers["Deprecation"] = "true"
        # Link header pointing to migration docs
        response.headers["Link"] = (
            '<https://api.example.com/docs/migration-v2>; rel="deprecation"'
        )

    if version == "1":
        return {"id": user_id, "name": "Alice Smith", "email": "alice@example.com"}

    return {
        "id": user_id,
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice@example.com",
    }


# =============================================================================
# PART 3 — QUERY PARAMETER VERSIONING
# =============================================================================
# Lowest friction for quick scripts and curl. Bad for caching (CDNs often
# ignore query params). Avoid for public APIs; acceptable for internal tooling.
# =============================================================================

@app.get("/users/{user_id}/query-versioned")
async def get_user_query_versioned(
    user_id: int,
    version: str = Query(default="2", description="API version to use"),
) -> dict:
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(status_code=400, detail=f"Unknown version: {version}")

    if version == "1":
        return {"id": user_id, "name": "Alice Smith"}
    return {"id": user_id, "first_name": "Alice", "last_name": "Smith"}


# =============================================================================
# PART 4 — SEMANTIC VERSIONING FOR APIS
# =============================================================================
# Apply SemVer (MAJOR.MINOR.PATCH) to understand what triggers a new URL version.
# =============================================================================

# BREAKING CHANGES → bump MAJOR (e.g., v1 → v2); clients MUST update
BREAKING_CHANGES = [
    "Removing a field from a response",
    "Renaming a field (name → first_name/last_name)",
    "Changing a field type (string → integer)",
    "Changing HTTP method for an endpoint (POST → PUT)",
    "Adding a required request field",
    "Removing an endpoint entirely",
    "Changing authentication scheme",
    "Narrowing enum values (removing accepted values)",
]

# NON-BREAKING CHANGES → additive; same version is fine
NON_BREAKING_CHANGES = [
    "Adding a new optional response field",
    "Adding a new endpoint",
    "Adding a new optional query parameter",
    "Expanding enum values (adding new accepted values)",
    "Relaxing validation (e.g., max length 50 → 100)",
    "Adding a new HTTP method to an existing resource",
]


# =============================================================================
# PART 5 — PYDANTIC MODELS AND OPENAPI SCHEMA GENERATION
# =============================================================================
# FastAPI reads your Pydantic models and generates OpenAPI schemas automatically.
# The schemas appear in the /openapi.json endpoint and feed Swagger UI / ReDoc.
# =============================================================================

class OrderStatus(str, Enum):
    """String enum → OpenAPI generates an 'enum' keyword in the schema."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Address(BaseModel):
    """Nested model → OpenAPI generates a reusable $ref component."""
    street: str = Field(..., example="123 Main St")
    city: str = Field(..., example="San Francisco")
    state: str = Field(..., min_length=2, max_length=2, example="CA")
    zip_code: str = Field(..., pattern=r"^\d{5}(-\d{4})?$", example="94102")
    country: str = Field(default="US", example="US")


class CreateOrderRequest(BaseModel):
    """
    Request body model. Every field annotation becomes an OpenAPI property.
    Field(...) = required. Field(default=...) = optional.
    """
    customer_id: int = Field(..., gt=0, description="Must reference an existing customer")
    items: list[dict] = Field(..., min_length=1, description="At least one item required")
    shipping_address: Address  # nested model → $ref in OpenAPI
    notes: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional delivery instructions",
    )

    # Custom validator — Pydantic v2 style
    @field_validator("items")
    @classmethod
    def items_must_have_required_keys(cls, v: list[dict]) -> list[dict]:
        for item in v:
            if "sku" not in item or "quantity" not in item:
                raise ValueError("Each item must have 'sku' and 'quantity'")
        return v

    model_config = {
        # Tells Pydantic (and OpenAPI) to use field names, not aliases
        "populate_by_name": True,
        # Adds example to the OpenAPI schema
        "json_schema_extra": {
            "example": {
                "customer_id": 42,
                "items": [{"sku": "WIDGET-001", "quantity": 3}],
                "shipping_address": {
                    "street": "123 Main St",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip_code": "94102",
                },
            }
        },
    }


class OrderResponse(BaseModel):
    """Response model — what the client receives back."""
    order_id: str = Field(..., description="UUID of the created order")
    status: OrderStatus
    customer_id: int
    total_amount: float = Field(..., ge=0)
    created_at: datetime
    estimated_delivery: Optional[date] = None


# =============================================================================
# PART 6 — FULL OPENAPI 3.1 SPEC STRUCTURE (as Python dict)
# =============================================================================
# Understanding the raw structure helps when you need to customize what
# FastAPI generates, or write specs for non-Python services.
# =============================================================================

OPENAPI_3_1_SPEC: dict[str, Any] = {
    # ── Top-level metadata ──────────────────────────────────────────────────
    "openapi": "3.1.0",  # Always specify the exact version
    "info": {
        "title": "Order Management API",
        "version": "2.1.0",               # Your API's SemVer version
        "description": "Manages customer orders with full lifecycle tracking.",
        "termsOfService": "https://example.com/terms",
        "contact": {
            "name": "Platform Team",
            "email": "platform@example.com",
            "url": "https://example.com/support",
        },
        "license": {"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
        # x- extensions: arbitrary vendor metadata, ignored by standard tools
        "x-api-changelog": "https://example.com/docs/changelog",
    },

    # ── Servers ─────────────────────────────────────────────────────────────
    # Clients use these to build full URLs. List all environments.
    "servers": [
        {
            "url": "https://api.example.com/v2",
            "description": "Production",
        },
        {
            "url": "https://staging-api.example.com/v2",
            "description": "Staging",
        },
        {
            # Variables let a single server entry cover many envs
            "url": "http://localhost:{port}/v2",
            "description": "Local development",
            "variables": {"port": {"default": "8000", "enum": ["8000", "8001"]}},
        },
    ],

    # ── Reusable components ─────────────────────────────────────────────────
    "components": {
        # ── Schemas (data models) ────────────────────────────────────────────
        "schemas": {
            "Address": {
                "type": "object",
                "required": ["street", "city", "state", "zip_code"],
                "properties": {
                    "street": {"type": "string", "example": "123 Main St"},
                    "city": {"type": "string"},
                    "state": {"type": "string", "minLength": 2, "maxLength": 2},
                    "zip_code": {
                        "type": "string",
                        "pattern": r"^\d{5}(-\d{4})?$",
                    },
                    "country": {"type": "string", "default": "US"},
                },
            },
            "Error": {
                # Standard error envelope — use the same shape everywhere
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string", "example": "VALIDATION_ERROR"},
                    "message": {"type": "string"},
                    "details": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
            },
        },

        # ── Security schemes ─────────────────────────────────────────────────
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",  # Documentation hint, not enforced
            },
            "ApiKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
            },
            "OAuth2": {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {
                        "tokenUrl": "https://auth.example.com/oauth/token",
                        "scopes": {
                            "orders:read": "Read order data",
                            "orders:write": "Create and modify orders",
                        },
                    }
                },
            },
        },

        # ── Response templates ───────────────────────────────────────────────
        "responses": {
            "UnauthorizedError": {
                "description": "Access token missing or invalid",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                },
            },
            "NotFoundError": {
                "description": "Resource not found",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                },
            },
        },
    },

    # ── Global security (can be overridden per-operation) ───────────────────
    "security": [{"BearerAuth": []}],

    # ── Paths (the actual API surface) ──────────────────────────────────────
    "paths": {
        "/orders": {
            "post": {
                "operationId": "createOrder",      # Unique ID used by code generators
                "summary": "Create a new order",
                "tags": ["Orders"],                 # Groups ops in Swagger UI
                "security": [{"BearerAuth": [], "OAuth2": ["orders:write"]}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Address"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Order created successfully",
                        "headers": {
                            # Location header pointing to the new resource
                            "Location": {
                                "schema": {"type": "string"},
                                "description": "URL of the created order",
                            }
                        },
                    },
                    "400": {"description": "Invalid request body"},
                    "401": {"$ref": "#/components/responses/UnauthorizedError"},
                },
            }
        },
        "/orders/{orderId}": {
            "get": {
                "operationId": "getOrder",
                "summary": "Retrieve a single order",
                "tags": ["Orders"],
                "parameters": [
                    {
                        "name": "orderId",
                        "in": "path",     # path | query | header | cookie
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                    }
                ],
                "responses": {
                    "200": {"description": "Order details"},
                    "404": {"$ref": "#/components/responses/NotFoundError"},
                },
                # Mark this endpoint as deprecated in the spec
                "deprecated": True,
                "x-sunset": "2025-12-31",
            }
        },
    },
}


# =============================================================================
# PART 7 — FASTAPI OPENAPI CUSTOMIZATION
# =============================================================================
# FastAPI auto-generates /openapi.json from your routes + models.
# You can extend the generated spec with custom metadata.
# =============================================================================

def custom_openapi():
    """
    Override FastAPI's default openapi() to inject extra metadata.
    Call this once at startup; FastAPI caches the result.
    """
    if app.openapi_schema:
        return app.openapi_schema  # Return cached schema on subsequent calls

    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title="Order Management API",
        version="2.1.0",
        description="Full lifecycle order management with SLA guarantees.",
        routes=app.routes,
    )

    # Inject custom security schemes that FastAPI doesn't add automatically
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["ApiKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }

    # Mark the entire API as requiring auth by default
    schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema  # Cache it
    return schema


# Wire the custom function into the app
app.openapi = custom_openapi  # type: ignore[method-assign]


# =============================================================================
# PART 8 — SWAGGER UI vs REDOC CONFIGURATION
# =============================================================================
# Both ship with FastAPI. Swagger UI is interactive (you can call endpoints).
# ReDoc is read-only but more polished for public documentation sites.
# =============================================================================

# Serve ReDoc at a custom path with custom theme options
from fastapi.responses import HTMLResponse


@app.get("/api-reference", include_in_schema=False)
async def redoc_custom():
    """Custom ReDoc page with branding. include_in_schema=False hides it from OpenAPI."""
    html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>API Reference</title>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
        <style>body { margin: 0; padding: 0; }</style>
      </head>
      <body>
        <!-- ReDoc CDN — pin to a specific version in production -->
        <redoc spec-url='/openapi.json'
               hide-download-button
               no-auto-auth></redoc>
        <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
      </body>
    </html>
    """
    return HTMLResponse(html)


# =============================================================================
# PART 9 — JSON SCHEMA VALIDATION OUTSIDE FASTAPI
# =============================================================================
# Sometimes you need to validate payloads in a non-FastAPI context
# (message queue consumers, CLI tools, test fixtures).
# jsonschema is the reference library.
# =============================================================================

# pip install jsonschema
JSON_SCHEMA_EXAMPLE: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12",
    "title": "CreateOrderRequest",
    "type": "object",
    "required": ["customer_id", "items"],
    "properties": {
        "customer_id": {"type": "integer", "minimum": 1},
        "items": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["sku", "quantity"],
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
}


def validate_payload(payload: dict, schema: dict) -> list[str]:
    """
    Validate a dict against a JSON Schema.
    Returns a list of validation error messages (empty = valid).
    Requires: pip install jsonschema
    """
    try:
        import jsonschema  # Lazy import — optional dependency

        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
        return [f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors]
    except ImportError:
        return ["jsonschema not installed; run: pip install jsonschema"]


# =============================================================================
# PART 10 — API CHANGELOG PATTERN
# =============================================================================
# Track breaking vs non-breaking changes in structured format.
# Feed this into your docs site or Slack release bot automatically.
# =============================================================================

CHANGELOG: list[dict[str, Any]] = [
    {
        "version": "2.1.0",
        "date": "2024-03-01",
        "type": "minor",          # minor = new features, backward-compatible
        "changes": [
            {
                "breaking": False,
                "description": "Added estimated_delivery field to OrderResponse",
                "endpoints": ["GET /v2/orders/{orderId}"],
            }
        ],
    },
    {
        "version": "2.0.0",
        "date": "2024-01-01",
        "type": "major",          # major = breaking changes
        "changes": [
            {
                "breaking": True,
                "description": "Split 'name' into 'first_name' and 'last_name' in UserResponse",
                "endpoints": ["GET /v2/users/{userId}"],
                "migration": "Update client code to read first_name and last_name separately",
            }
        ],
    },
    {
        "version": "1.3.0",
        "date": "2023-10-15",
        "type": "minor",
        "changes": [
            {
                "breaking": False,
                "description": "Added notes field to CreateOrderRequest (optional)",
                "endpoints": ["POST /v1/orders"],
            }
        ],
        "sunset": "2025-12-31",   # v1 sunset date
    },
]


# =============================================================================
# DEMO / QUICK-START BLOCK
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    # Print the generated OpenAPI spec to stdout for inspection
    # In real usage: curl http://localhost:8000/openapi.json | python -m json.tool
    print("Starting API server. Visit:")
    print("  Swagger UI → http://localhost:8000/docs")
    print("  ReDoc      → http://localhost:8000/redoc")
    print("  Raw spec   → http://localhost:8000/openapi.json")

    # Run validation on the hardcoded spec
    errors = validate_payload(
        {"customer_id": 1, "items": [{"sku": "X", "quantity": 2}]},
        JSON_SCHEMA_EXAMPLE,
    )
    print("Validation errors:", errors or "None — payload is valid")

    uvicorn.run(app, host="0.0.0.0", port=8000)
