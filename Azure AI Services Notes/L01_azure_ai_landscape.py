# ============================================================
# L01: Azure AI Landscape — Services, Resource Model, AI Foundry
# ============================================================
# WHAT: The map of Azure's AI service surface — Azure OpenAI Service,
#       Azure AI Foundry (formerly Azure AI Studio), Azure Cognitive
#       Services (now "Azure AI Services" as an umbrella brand), Azure
#       AI Search, and Azure Machine Learning — and how Azure resources,
#       regions, quota, and RBAC fit together underneath all of them.
# WHY: Every other lesson in this domain (L02-L08) sits on top of this
#      resource model. Getting the landscape wrong — e.g. confusing an
#      Azure OpenAI *resource* with a *deployment*, or not understanding
#      regional model availability — is the #1 source of "why can't I
#      call my model" confusion for engineers new to Azure AI.
# LEVEL: Foundational (Lesson 1 of 8)
# ============================================================

"""
CONCEPT OVERVIEW:
Azure's AI offering is NOT one product — it's a family of services that
overlap in confusing ways. The naming has also shifted (Azure Cognitive
Services -> Azure AI Services; Azure AI Studio -> Azure AI Foundry), so
job postings and docs mix old and new names. Here's the actual map:

1. AZURE OPENAI SERVICE
   Microsoft's hosted, enterprise-governed access to OpenAI models
   (GPT-4.1, GPT-4o, GPT-4o-mini, o-series reasoning models, embeddings,
   DALL-E, Whisper) — running in Microsoft's Azure tenancy, NOT OpenAI's.
   You get: private networking (VNet integration), regional data
   residency, Azure AD auth, enterprise SLAs, and content filtering
   baked in. Covered in depth in L02.

2. AZURE AI FOUNDRY (formerly Azure AI Studio)
   The unified PORTAL/PLATFORM for building AI apps on Azure — a single
   pane of glass over Azure OpenAI models, thousands of third-party/OSS
   models (Llama, Mistral, Cohere) via the "model catalog," AI Search
   integration, prompt flow (visual pipeline builder), evaluation
   tooling, and — critically for this domain — the AI Foundry AGENT
   SERVICE for building and hosting agentic systems (L07).

3. AZURE AI SERVICES (the "Cognitive Services" umbrella, rebranded)
   Pre-built, task-specific AI APIs that are NOT LLMs — Speech
   (transcription/synthesis), Vision (OCR, image analysis, face),
   Language (sentiment, NER, translation, summarization), and Document
   Intelligence (form/invoice extraction). You call these when you need
   a narrow, well-defined capability faster/cheaper than routing through
   an LLM. Covered in L03.

4. AZURE AI SEARCH (formerly Azure Cognitive Search)
   A managed search-as-a-service product that does keyword search,
   vector search, AND hybrid search with semantic re-ranking — the
   default "retrieval" half of a RAG pipeline on Azure. Covered in L04.

5. AZURE MACHINE LEARNING (Azure ML)
   The platform for training, tracking, and deploying YOUR OWN models
   (classical ML or custom fine-tunes) — workspaces, compute clusters,
   pipelines, model registry, managed online endpoints. This is where
   you'd fine-tune a model or run a custom scikit-learn/PyTorch training
   job, as distinct from calling a pre-trained foundation model via
   Azure OpenAI. Covered in L05.

RESOURCE MODEL: how these actually get provisioned
----------------------------------------------------
Azure organizes everything into a hierarchy:

    Subscription
      -> Resource Group (a logical container, usually per-project/env)
          -> Resource (e.g. one "Azure OpenAI" resource, one "AI Search"
                        resource, one "AI Services multi-service" resource)

An Azure OpenAI RESOURCE is not itself a model — it's an endpoint +
auth boundary. Within that resource you create one or more
DEPLOYMENTS, each pinning a specific model version (e.g. a deployment
named "gpt4o-prod" pointing at gpt-4o version 2024-11-20) to a capacity
tier (Standard, Provisioned Throughput Units). Your application code
calls a DEPLOYMENT NAME, not a raw model name — this indirection is
what lets platform teams swap the underlying model version without
changing application code.

REGIONAL AVAILABILITY & QUOTA
------------------------------
Not every model is available in every Azure region, and each
subscription has a QUOTA (measured in Tokens-Per-Minute, TPM) per
model/region combination. This is the single most common "it worked in
my other subscription" surprise — a model available in East US may not
be available (or may have zero default quota) in UAE North. Enterprise
deployments in regulated regions (e.g. UAE, for data-residency reasons)
often have to request quota increases explicitly before go-live.

IDENTITY & ACCESS: Azure AD / Entra ID over API keys
-----------------------------------------------------
Every Azure AI resource supports two auth modes: a static API KEY
(simple, but a long-lived secret that must be rotated/vaulted) and
MICROSOFT ENTRA ID (formerly Azure AD) token-based auth via a MANAGED
IDENTITY — the enterprise-preferred pattern, since it eliminates
long-lived secrets entirely and lets access be scoped/audited through
Azure RBAC role assignments (e.g. "Cognitive Services OpenAI User" on
a specific resource, nothing more). Regulated environments (banking,
this domain's job-market driver) mandate managed-identity auth almost
universally — a static key in an app-service setting is a recurring
audit finding.

PRODUCTION USE CASE:
A bank's AI platform team provisions one Azure OpenAI resource per
environment (dev/staging/prod) in a data-residency-compliant region,
each with deployments named consistently across environments
("gpt4o-mini-chat", "text-embedding-3-large") so application code never
hardcodes a model version. Access is granted via managed identity +
RBAC role assignment scoped to the specific resource, never a shared
API key. A central "AI Hub gateway" (a pattern covered in depth in L07)
sits in front of all Azure OpenAI resource calls, so quota, cost, and
governance are enforced in one place rather than per-application.

COMMON MISTAKES:
- Treating "the model" and "the deployment" as the same thing — a
  deployment name is an indirection layer application code should use,
  not the raw model identifier.
- Assuming a model available in one region is available (or has quota)
  in another — always check regional model availability before
  designing around a specific model.
- Using a static API key in production instead of managed identity —
  the recurring, avoidable audit finding in regulated deployments.
- Provisioning a separate Azure OpenAI resource per application instead
  of a shared, governed resource behind a gateway — this fragments
  quota, makes cost attribution harder, and multiplies the secrets that
  need rotating.
- Confusing Azure AI Foundry (the platform/portal) with Azure AI
  Services (the pre-built task APIs) — they are different products
  that happen to share the "Azure AI" name prefix.
"""

import textwrap


# ------------------------------------------------------------------
# 1. The resource hierarchy, as Azure CLI / Bicep would express it
# ------------------------------------------------------------------
RESOURCE_HIERARCHY_EXAMPLE = textwrap.dedent("""\
    # Subscription
    #   -> Resource Group: rg-ai-platform-prod
    #        -> Azure OpenAI resource: aoai-platform-prod (in uaenorth)
    #             -> Deployment: gpt4o-mini-chat   (model: gpt-4o-mini, 2024-07-18)
    #             -> Deployment: gpt41-reasoning     (model: gpt-4.1, 2025-04-14)
    #             -> Deployment: text-embed-3-large  (model: text-embedding-3-large)
    #        -> Azure AI Search resource: search-platform-prod
    #        -> Azure AI Services (multi-service) resource: ai-svc-platform-prod

    az cognitiveservices account create \\
      --name aoai-platform-prod \\
      --resource-group rg-ai-platform-prod \\
      --kind OpenAI \\
      --sku S0 \\
      --location uaenorth

    az cognitiveservices account deployment create \\
      --name aoai-platform-prod \\
      --resource-group rg-ai-platform-prod \\
      --deployment-name gpt4o-mini-chat \\
      --model-name gpt-4o-mini \\
      --model-version "2024-07-18" \\
      --model-format OpenAI \\
      --sku-capacity 50 \\
      --sku-name Standard
""")

# ------------------------------------------------------------------
# 2. Managed identity auth — the enterprise-preferred pattern
# ------------------------------------------------------------------
MANAGED_IDENTITY_AUTH_EXAMPLE = textwrap.dedent("""\
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    # DefaultAzureCredential tries, in order: environment vars, managed
    # identity (when running in Azure), Azure CLI login (local dev) —
    # NO static key ever appears in code or config.
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )

    client = AzureOpenAI(
        azure_endpoint="https://aoai-platform-prod.openai.azure.com/",
        azure_ad_token_provider=token_provider,   # NOT api_key=
        api_version="2024-10-21",
    )

    response = client.chat.completions.create(
        model="gpt4o-mini-chat",   # the DEPLOYMENT name, not "gpt-4o-mini"
        messages=[{"role": "user", "content": "Summarize this quarter's risk report."}],
    )
""")

# ------------------------------------------------------------------
# 3. RBAC role assignment scoped to one resource
# ------------------------------------------------------------------
RBAC_SCOPING_EXAMPLE = textwrap.dedent("""\
    # Grant an app's managed identity ONLY the ability to call models —
    # not manage the resource, not view/rotate keys.
    az role assignment create \\
      --assignee <app-managed-identity-principal-id> \\
      --role "Cognitive Services OpenAI User" \\
      --scope /subscriptions/<sub-id>/resourceGroups/rg-ai-platform-prod/providers/Microsoft.CognitiveServices/accounts/aoai-platform-prod
""")

AZURE_AI_SERVICE_MAP = {
    "Azure OpenAI Service": "Governed access to OpenAI foundation models (L02)",
    "Azure AI Foundry": "Unified portal + model catalog + Agent Service (L07)",
    "Azure AI Services": "Pre-built task APIs: Speech/Vision/Language/Doc Intel (L03)",
    "Azure AI Search": "Managed keyword + vector + hybrid search (L04)",
    "Azure Machine Learning": "Train/track/deploy custom models (L05)",
}


if __name__ == "__main__":
    print(RESOURCE_HIERARCHY_EXAMPLE)
    print(MANAGED_IDENTITY_AUTH_EXAMPLE)
    print(RBAC_SCOPING_EXAMPLE)
    print("=== Azure AI service map ===")
    for service, note in AZURE_AI_SERVICE_MAP.items():
        print(f"{service}: {note}")

"""
PRODUCTION CONTEXT EXAMPLE:
A regulated bank's platform team stands up one Azure OpenAI resource per
environment in a data-residency-approved region, names deployments by
role rather than raw model ("chat-primary", "embeddings-primary") so a
model version upgrade is a deployment-config change instead of an
application redeploy, and requires every calling application to
authenticate via managed identity with an RBAC role scoped to exactly
one resource — so a security audit can answer "which apps can call
which AI resources" from role assignments alone, with zero API keys to
track down.
"""
