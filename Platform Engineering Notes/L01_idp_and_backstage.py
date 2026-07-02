# ============================================================
# L01: Internal Developer Platforms (IDP) and Backstage
# ============================================================
# WHAT: Self-service platforms that let application developers provision
#       infra, discover services, and follow "golden paths" without filing
#       tickets to a platform/infra team.
# WHY (PRODUCTION): At scale (50+ services, 100+ engineers), every developer
#       asking "where's the API docs for billing-service?" or "how do I get
#       a new Postgres DB?" in Slack is unscalable. An IDP turns tribal
#       knowledge into a searchable, self-service catalog.
# LEVEL: Mid-to-senior backend / platform engineer
# ============================================================

"""
CONCEPT OVERVIEW:
An Internal Developer Platform (IDP) is the layer between raw infrastructure
(Kubernetes, Terraform, cloud APIs) and the application developer. It exposes
a curated, opinionated subset of infra capabilities as self-service actions:
"create a new service", "provision a database", "deploy to staging".

Backstage (open-sourced by Spotify, now a CNCF incubating project) is the
dominant open-source IDP framework. It is NOT a PaaS — it doesn't run your
code. It's a UI + backend that indexes metadata about your services
(the "software catalog") and provides a plugin framework for everything else
(CI/CD status, docs, cost, on-call, security scorecards).

PRODUCTION USE CASE:
A platform team runs one Backstage instance for the whole engineering org.
Every microservice registers a `catalog-info.yaml` in its repo root. Backstage
scans all repos nightly (or on webhook) and builds a graph: which services
exist, who owns them, what APIs they expose, what they depend on. A new hire
can open Backstage, search "payments", and immediately see: the repo, the
on-call rotation, the runbook, the API contract, and a "deploy" button that
kicks off a pre-approved pipeline.

COMMON MISTAKES:
- Treating Backstage as "just a wiki" — its real value is the catalog graph
  and scaffolder automation, not TechDocs alone.
- Not enforcing catalog-info.yaml via CI (a linter/pre-commit check), so the
  catalog silently drifts from reality.
- Building custom plugins before establishing catalog data quality — garbage
  in, garbage out.
"""

import textwrap

# ------------------------------------------------------------------
# 1. Software Catalog: the core data model
# ------------------------------------------------------------------
# Every entity in Backstage is one of these "kinds". Component is the most
# common (a deployable service/library). System groups related Components.
# Domain groups related Systems (e.g. "Payments" domain owns several systems).
CATALOG_ENTITY_KINDS = {
    "Component": "A single piece of software: a service, website, library, or job.",
    "API": "A machine-readable contract (OpenAPI, gRPC, GraphQL, AsyncAPI).",
    "Resource": "Infrastructure the component depends on: a database, a queue, an S3 bucket.",
    "System": "A collection of Components/APIs/Resources that together deliver a capability.",
    "Domain": "A grouping of Systems by business area (e.g. Payments, Identity).",
    "Group": "A team or organizational unit (owns Components).",
    "User": "An individual person entity, usually synced from an identity provider (Okta/LDAP).",
}

# ------------------------------------------------------------------
# 2. catalog-info.yaml — the file every repo must have
# ------------------------------------------------------------------
# This lives at the repo root. Backstage's "discovery" processor scans
# GitHub/GitLab orgs for these files and ingests them on a schedule.
CATALOG_INFO_EXAMPLE = textwrap.dedent("""\
    apiVersion: backstage.io/v1alpha1
    kind: Component
    metadata:
      name: billing-service
      description: Handles invoice generation and payment capture
      annotations:
        # These annotations wire up plugins automatically.
        github.com/project-slug: myorg/billing-service
        backstage.io/techdocs-ref: dir:.                # docs live in this repo
        pagerduty.com/service-id: PXXXXXX               # on-call plugin
        sonarqube.org/project-key: billing-service       # code quality plugin
      tags:
        - payments
        - java
      links:
        - url: https://grafana.internal/d/billing
          title: Grafana Dashboard
          icon: dashboard
    spec:
      type: service                # service | website | library | tool
      lifecycle: production        # experimental | production | deprecated
      owner: group:payments-team   # MUST reference a Group entity
      system: payments             # groups this under the "payments" System
      providesApis:
        - billing-api              # references an API entity below
      dependsOn:
        - resource:billing-postgres
        - component:notification-service
""")

# A companion API entity — the OpenAPI spec Backstage will render interactively.
API_ENTITY_EXAMPLE = textwrap.dedent("""\
    apiVersion: backstage.io/v1alpha1
    kind: API
    metadata:
      name: billing-api
      description: REST API for invoice and payment operations
    spec:
      type: openapi
      lifecycle: production
      owner: group:payments-team
      system: payments
      definition:
        $text: https://raw.githubusercontent.com/myorg/billing-service/main/openapi.yaml
""")

# A Resource entity — models a database the service depends on, so the
# catalog graph shows "billing-service --depends on--> billing-postgres".
RESOURCE_ENTITY_EXAMPLE = textwrap.dedent("""\
    apiVersion: backstage.io/v1alpha1
    kind: Resource
    metadata:
      name: billing-postgres
      description: Primary transactional database for billing-service
    spec:
      type: database
      owner: group:payments-team
      system: payments
""")


def validate_catalog_entity(entity: dict) -> list[str]:
    """
    A minimal validator mirroring what Backstage's catalog processor checks.
    Run this in CI (pre-merge) so broken catalog-info.yaml never reaches main —
    a common failure mode is a typo in `owner:` that silently orphans a service.
    """
    errors = []
    required_top_level = ("apiVersion", "kind", "metadata", "spec")
    for field in required_top_level:
        if field not in entity:
            errors.append(f"missing required field: {field}")

    metadata = entity.get("metadata", {})
    if "name" not in metadata:
        errors.append("metadata.name is required (must be unique, DNS-safe)")

    spec = entity.get("spec", {})
    owner = spec.get("owner", "")
    # Backstage requires owner references to be namespaced kind:name,
    # e.g. "group:payments-team" — a bare "payments-team" silently fails
    # to resolve and the entity shows "unknown owner" in the UI.
    if owner and ":" not in owner:
        errors.append(
            f"spec.owner '{owner}' should be namespaced, e.g. 'group:{owner}'"
        )
    return errors


# ------------------------------------------------------------------
# 3. Scaffolder — self-service "create new service" templates
# ------------------------------------------------------------------
# The scaffolder is Backstage's answer to "how do I bootstrap a new repo
# that already has CI, catalog registration, and the org's linting config?"
# Templates are YAML + Nunjucks templating, executed as a wizard in the UI.
SCAFFOLDER_TEMPLATE_EXAMPLE = textwrap.dedent("""\
    apiVersion: scaffolder.backstage.io/v1beta3
    kind: Template
    metadata:
      name: new-python-fastapi-service
      title: New Python FastAPI Service
      description: Golden-path template for a production-ready FastAPI service
    spec:
      owner: group:platform-team
      type: service
      parameters:
        - title: Service details
          required: [name, owner]
          properties:
            name:
              title: Service Name
              type: string
              pattern: '^[a-z][a-z0-9-]*$'
            owner:
              title: Owning Team
              type: string
              ui:field: OwnerPicker      # renders a Group-entity dropdown
      steps:
        - id: fetch
          name: Fetch skeleton
          action: fetch:template          # built-in action: copy + template a skeleton dir
          input:
            url: ./skeleton
            values:
              name: ${{ parameters.name }}
              owner: ${{ parameters.owner }}
        - id: publish
          name: Publish to GitHub
          action: publish:github          # built-in action: create repo + push
          input:
            repoUrl: github.com?repo=${{ parameters.name }}&owner=myorg
        - id: register
          name: Register in catalog
          action: catalog:register        # built-in action: auto-registers catalog-info.yaml
          input:
            repoContentsUrl: ${{ steps.publish.output.repoContentsUrl }}
            catalogInfoPath: /catalog-info.yaml
      output:
        links:
          - title: Repository
            url: ${{ steps.publish.output.remoteUrl }}
          - title: Open in catalog
            icon: catalog
            entityRef: ${{ steps.register.output.entityRef }}
""")

# ------------------------------------------------------------------
# 4. Custom plugin shape (conceptual)
# ------------------------------------------------------------------
# A Backstage plugin has two halves:
#   - Frontend: a React package registered into the app's sidebar/entity page
#   - Backend: an Express-based Node service exposing REST endpoints
# Most orgs never write a frontend plugin from scratch — they consume the
# 100+ community plugins (Kubernetes, ArgoCD, PagerDuty, Cost Insights) and
# only build custom backend plugins to expose an internal system
# (e.g. an internal secrets-rotation-status API) into the catalog UI.
CUSTOM_PLUGIN_BACKEND_SKETCH = textwrap.dedent("""\
    // packages/backend/src/plugins/costInsights.ts (conceptual)
    import { createRouter } from '@internal/plugin-cost-insights-backend';

    export default async function createPlugin(env) {
      return await createRouter({
        logger: env.logger,
        // this handler queries your internal billing API and returns
        // cost-per-service JSON that the frontend plugin renders as a chart
        costFetcher: async (entityRef) => fetchCostFromBillingAPI(entityRef),
      });
    }
""")

# ------------------------------------------------------------------
# 5. Golden path adoption — how you measure IDP success
# ------------------------------------------------------------------
# An IDP with a 5% adoption rate is a failed project regardless of how
# elegant the catalog schema is. Track these as platform SLIs (see L08):
GOLDEN_PATH_METRICS = {
    "template_usage_rate": "new services created via scaffolder / total new services",
    "catalog_coverage": "services with valid catalog-info.yaml / total known repos",
    "time_to_first_commit": "median time from 'click new service' to first merged PR",
    "docs_freshness": "% of TechDocs sites not updated in > 90 days (staleness signal)",
    "onboarding_nps": "survey score from new hires: 'how easy was it to find X'",
}

if __name__ == "__main__":
    bad_entity = {"apiVersion": "backstage.io/v1alpha1", "kind": "Component",
                   "metadata": {"name": "x"}, "spec": {"owner": "payments-team"}}
    print("Validation errors:", validate_catalog_entity(bad_entity))
    # -> ["spec.owner 'payments-team' should be namespaced, e.g. 'group:payments-team'"]

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
A platform team of 4 supports 200 engineers across 300 services. Without an
IDP, each new service takes ~3 days of back-and-forth (CI setup, DB
provisioning ticket, on-call registration). With Backstage + a scaffolder
template + catalog:register action, that drops to ~20 minutes — the template
already wires CI, requests the DB via a Terraform module, and registers
on-call. The platform team's leverage scales because they encode policy once
(in the template) instead of enforcing it manually per PR review.
"""
