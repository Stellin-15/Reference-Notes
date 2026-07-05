# ============================================================
# L05: Django Fundamentals — ORM, Views, Admin, vs FastAPI
# ============================================================
# WHAT: Django's "batteries-included" philosophy — the built-in ORM,
#       views/URL routing, and the auto-generated admin interface — and
#       a direct comparison against this repo's FastAPI Notes coverage.
# WHY: FastAPI (this repo's FastAPI Notes) represents a modern, async-
#      first, minimal-by-default Python web framework. Django represents
#      the OPPOSITE philosophy — a mature, comprehensive, "batteries-
#      included" framework still extremely common in production,
#      especially for content-heavy or admin-tool-heavy applications.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
DJANGO'S "BATTERIES-INCLUDED" PHILOSOPHY means the framework ships with
an ORM, an admin interface, a templating engine, authentication, and a
forms library, all INTEGRATED and designed to work together out of the
box — contrasted with FastAPI's more MINIMAL, "bring your own pieces"
philosophy (FastAPI provides the web layer and validation; you choose
your own ORM, typically SQLAlchemy, this repo's FastAPI Notes L03).
This is a genuine, deliberate tradeoff: Django's integration reduces
DECISION FATIGUE and glue-code for STANDARD web application patterns,
at the cost of being less flexible when you need something Django's
conventions don't anticipate.

THE DJANGO ORM lets you define models as PYTHON CLASSES, with Django
automatically generating the underlying SQL (and database migration
files, via `makemigrations`/`migrate`) — a genuinely different
ergonomic than SQLAlchemy's more explicit, close-to-SQL approach
(FastAPI Notes L03). Django's ORM trades some of SQLAlchemy's
flexibility/control for a more OPINIONATED, less-boilerplate default
experience for standard CRUD patterns.

VIEWS AND URL ROUTING: a Django VIEW is a function (or class) that takes
a request and returns a response — URL patterns map paths to views via
a separate `urls.py` configuration, a more EXPLICIT, centralized routing
table compared to FastAPI's decorator-based (`@app.get("/path")`)
routing declared directly at each endpoint function.

THE ADMIN INTERFACE is Django's most distinctive, genuinely unique
feature: registering a model with `admin.site.register()` AUTOMATICALLY
generates a full CRUD web interface for managing that model's data —
list views, filtering, search, create/edit forms — with ZERO additional
code beyond the registration itself. This is enormously valuable for
INTERNAL TOOLING and rapid prototyping (a working data-management UI
"for free"), a capability FastAPI has no direct equivalent for (FastAPI
projects typically build custom internal tools or rely on separate
tooling for this need).

PRODUCTION USE CASE:
An internal operations tool for managing customer accounts, support
tickets, and configuration data uses Django SPECIFICALLY for its admin
interface — the team gets a fully functional CRUD management UI for
every model with essentially zero frontend development effort, letting
engineering focus their actual UI development time on the CUSTOMER-
FACING product instead, while a SEPARATE, performance-critical,
async-heavy customer-facing API (handling real-time features) is built
in FastAPI, each framework applied where its specific strengths matter most.

COMMON MISTAKES:
- Choosing Django for a genuinely async-heavy, high-concurrency API
  workload where FastAPI's native async support (this repo's FastAPI
  Notes L03) is the better architectural fit — Django's async support
  has matured over recent versions but remains less central to its
  design than FastAPI's async-first approach.
- Choosing FastAPI for an application that would benefit enormously from
  Django's admin interface and integrated ORM/migrations, then spending
  significant engineering time re-building equivalent internal tooling
  from scratch — a real cost worth weighing against FastAPI's other advantages.
- Fighting Django's CONVENTIONS (e.g. bypassing the ORM for raw SQL
  everywhere, ignoring the admin interface entirely) instead of either
  embracing them or choosing a more minimal framework better suited to
  a genuinely custom architecture — Django's value proposition
  specifically depends on working WITH its opinionated structure.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Models — the Django ORM
# ------------------------------------------------------------------
DJANGO_MODEL_EXAMPLE = textwrap.dedent("""\
    # models.py
    from django.db import models

    class Agent(models.Model):
        name = models.CharField(max_length=100)
        status = models.CharField(max_length=20, choices=[
            ('active', 'Active'), ('paused', 'Paused'),
        ])
        created_at = models.DateTimeField(auto_now_add=True)

        def __str__(self):
            return self.name

    # Django auto-generates migration files reflecting model changes:
    #   python manage.py makemigrations
    #   python manage.py migrate

    # ORM query examples — no raw SQL needed for standard operations:
    active_agents = Agent.objects.filter(status='active')
    agent = Agent.objects.get(id=1)
    agent.status = 'paused'
    agent.save()
""")

# ------------------------------------------------------------------
# 2. Views and URL routing
# ------------------------------------------------------------------
DJANGO_VIEWS_EXAMPLE = textwrap.dedent("""\
    # views.py
    from django.http import JsonResponse
    from .models import Agent

    def agent_detail(request, agent_id):
        agent = Agent.objects.get(id=agent_id)
        return JsonResponse({"id": agent.id, "name": agent.name, "status": agent.status})

    # urls.py — a SEPARATE, centralized routing table (contrast with
    # FastAPI's decorator-based routing declared at each endpoint function)
    from django.urls import path
    from . import views

    urlpatterns = [
        path('agents/<int:agent_id>/', views.agent_detail, name='agent_detail'),
    ]
""")

# ------------------------------------------------------------------
# 3. The admin interface — a full CRUD UI for free
# ------------------------------------------------------------------
DJANGO_ADMIN_EXAMPLE = textwrap.dedent("""\
    # admin.py
    from django.contrib import admin
    from .models import Agent

    @admin.register(Agent)
    class AgentAdmin(admin.ModelAdmin):
        list_display = ('name', 'status', 'created_at')
        list_filter = ('status',)
        search_fields = ('name',)

    # THIS FEW LINES OF CODE produces a FULL, working web UI at /admin/:
    #   - a searchable, filterable LIST view of every Agent
    #   - CREATE/EDIT forms auto-generated from the model's fields
    #   - built-in user authentication/permissions for who can access it
    # No custom frontend code was written for any of this.
""")

# ------------------------------------------------------------------
# 4. Django vs FastAPI comparison
# ------------------------------------------------------------------
DJANGO_VS_FASTAPI_COMPARISON = {
    "Philosophy": "Django: batteries-included, opinionated, integrated "
        "ORM/admin/auth. FastAPI: minimal, async-first, you assemble "
        "your own pieces (SQLAlchemy, etc., per this repo's FastAPI Notes).",
    "Async support": "Django: matured over recent versions, but not "
        "as central to its design. FastAPI: async-native from the ground up.",
    "Admin/internal tooling": "Django: full CRUD admin UI essentially "
        "for free. FastAPI: no built-in equivalent — build custom "
        "tooling or use a separate solution.",
    "Best fit": "Django: content-heavy sites, internal tools needing "
        "admin UIs, teams wanting an integrated, convention-driven "
        "stack. FastAPI: high-concurrency APIs, async-heavy workloads, "
        "teams wanting maximum flexibility in component choice.",
}


if __name__ == "__main__":
    print(DJANGO_MODEL_EXAMPLE)
    print(DJANGO_VIEWS_EXAMPLE)
    print(DJANGO_ADMIN_EXAMPLE)
    print("=== Django vs FastAPI ===")
    for aspect, note in DJANGO_VS_FASTAPI_COMPARISON.items():
        print(f"{aspect}: {note}\n")

"""
PRODUCTION CONTEXT EXAMPLE:
An AI product company runs TWO Python backends deliberately: a Django
application powering their internal operations team's customer/ticket
management (leveraging the auto-generated admin interface to give
non-engineers a working management UI within days, not weeks), and a
separate FastAPI service handling their customer-facing, real-time
AI-agent-interaction API (leveraging FastAPI's native async support for
the high-concurrency, I/O-heavy workload of coordinating LLM calls and
streaming responses) — a deliberate, dual-framework architecture where
each framework is applied specifically to the workload its philosophy suits best.
"""
