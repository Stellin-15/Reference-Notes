# ============================================================
# L19: MCP (Model Context Protocol) — Servers, Clients, Tools/Resources/Prompts
# ============================================================
# WHAT: MCP's architecture — a standardized protocol (JSON-RPC based)
#       for connecting an LLM application to external tools/data sources
#       via MCP SERVERS, using the MCP SDK/FastMCP to build one, plus a
#       tour of common pre-built servers (GitHub, Slack, PostgreSQL,
#       Google Drive, Filesystem) and the MCP Registry for discovering them.
# WHY: Every framework in Phase 3-4 defines TOOLS in its OWN
#      framework-specific way — a LangGraph tool isn't directly reusable
#      in CrewAI without rewriting it. MCP solves this with a STANDARD
#      PROTOCOL: build a tool/data-source integration ONCE as an MCP
#      server, and ANY MCP-compatible client (regardless of which agent
#      framework it's built with) can use it without reimplementation.
# LEVEL: Advanced (Phase 5 of 7 — Protocol, Memory, Tool Use)
# ============================================================

"""
CONCEPT OVERVIEW:
MCP defines a CLIENT-SERVER protocol (built on JSON-RPC 2.0) between an
LLM APPLICATION (the client — e.g. an agent framework, or a chat
application like Claude Desktop) and an MCP SERVER, which exposes THREE
kinds of capabilities:
  - TOOLS: functions the LLM can call (analogous to the "tools" concept
    in every framework covered so far, but now protocol-standardized —
    an MCP tool works identically whether the calling client is built
    with LangGraph, CrewAI, or a custom application).
  - RESOURCES: read-only data the client can fetch and include as
    context (a file's contents, a database query result) — distinct
    from tools in that resources are meant to be READ, not invoked with
    side effects.
  - PROMPTS: reusable, parameterized prompt TEMPLATES the server can
    expose, so a common prompting pattern can be defined once on the
    server side and reused by any connecting client.

This client-server separation is the key architectural idea: a company
can build ONE MCP server exposing their internal ticketing system, and
that server works with ANY MCP-compatible agent application their teams
build, regardless of which agent framework each team happens to use —
solving the same "write once, use everywhere" problem for tool
integrations that a REST API solves for general software integration.

THE MCP SDK (available in Python, TypeScript, and other languages) is
the reference implementation for building MCP servers and clients.
FASTMCP is a popular, higher-level Python library specifically for
building MCP SERVERS quickly, using decorators to turn plain Python
functions into MCP tools with minimal boilerplate.

Common PRE-BUILT MCP SERVERS exist for widely-needed integrations: a
GITHUB MCP SERVER (repository/issue/PR operations), SLACK MCP SERVER
(reading/posting messages), POSTGRESQL MCP SERVER (querying a database
as a resource/tool), GOOGLE DRIVE MCP SERVER (reading/searching documents),
and FILESYSTEM MCP SERVER (reading/writing local files, typically
sandboxed to a specific directory for safety) — using one of these means
NOT reimplementing a GitHub or Slack integration from scratch. The MCP
REGISTRY is a discoverable catalog of published MCP servers, letting you
find an existing server for a common integration need before building
your own.

PRODUCTION USE CASE:
An organization builds ONE internal MCP server exposing their proprietary
CRM system's read/write operations. Three separate teams — one building
a LangGraph-based sales assistant, one building a CrewAI-based support
triage system, one building a custom internal tool with no framework at
all — all connect to the SAME MCP server, none of them reimplementing
CRM integration logic, and a future change to the CRM's API only needs
updating in ONE place (the MCP server), not three separate framework-
specific tool implementations.

COMMON MISTAKES:
- Building a custom, framework-specific tool integration for a common
  need (GitHub, Slack, a SQL database) without first checking the MCP
  Registry for an existing, maintained server — reinventing integrations
  that already exist and are actively maintained by others.
- Exposing a FILESYSTEM MCP server without properly sandboxing it to a
  specific, restricted directory — an unsandboxed filesystem tool
  handed to an LLM-driven agent is a genuine security risk (see L22 for
  the full AI security treatment of this exact class of problem).
- Conflating MCP TOOLS (invocable, potentially side-effecting actions)
  with MCP RESOURCES (read-only data) when designing a server — using a
  "tool" for what's really just a data-fetch operation adds unnecessary
  invocation semantics; the protocol's own distinction exists to keep
  read vs write/action operations clearly separated.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Building an MCP server with FastMCP
# ------------------------------------------------------------------
FASTMCP_SERVER_EXAMPLE = textwrap.dedent("""\
    from fastmcp import FastMCP

    mcp = FastMCP("Internal Ticketing System")

    @mcp.tool()
    def create_ticket(title: str, description: str, priority: str) -> str:
        \"\"\"Create a new support ticket.\"\"\"
        ticket_id = ticketing_system.create(title, description, priority)
        return f"Created ticket #{ticket_id}"

    @mcp.resource("ticket://{ticket_id}")
    def get_ticket(ticket_id: str) -> str:
        \"\"\"Fetch a ticket's current details as read-only context.\"\"\"
        return ticketing_system.get(ticket_id).to_json()

    @mcp.prompt()
    def escalation_prompt(ticket_id: str) -> str:
        \"\"\"A reusable, server-defined prompt template for escalation decisions.\"\"\"
        return f"Review ticket {ticket_id} and decide if it needs escalation."

    if __name__ == "__main__":
        mcp.run()   # starts the server, listening for MCP client connections
""")

# ------------------------------------------------------------------
# 2. Connecting an MCP client (from an agent framework)
# ------------------------------------------------------------------
MCP_CLIENT_EXAMPLE = textwrap.dedent("""\
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(command="python", args=["ticketing_server.py"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover what this server offers — tools/resources/prompts
            # are all DISCOVERABLE at runtime, not hardcoded by the client.
            tools = await session.list_tools()

            result = await session.call_tool(
                "create_ticket",
                arguments={"title": "Login broken", "description": "...", "priority": "high"},
            )

    # ANY MCP-compatible agent framework (LangGraph, CrewAI, a custom
    # app) can connect to this SAME server using this SAME protocol —
    # the tool implementation lives once, on the server side.
""")

# ------------------------------------------------------------------
# 3. Tools vs Resources vs Prompts — the protocol's own distinction
# ------------------------------------------------------------------
MCP_CAPABILITY_TYPES = {
    "Tools": "Invocable actions, potentially with side effects (create a "
        "ticket, send a message, run a query that modifies state).",
    "Resources": "Read-only data the client fetches for context (a "
        "file's contents, a ticket's current details) — no side effects.",
    "Prompts": "Reusable, parameterized prompt templates defined "
        "server-side, so a common prompting pattern is shared across "
        "every client connecting to that server, not redefined per client.",
}

# ------------------------------------------------------------------
# 4. Common pre-built MCP servers
# ------------------------------------------------------------------
COMMON_MCP_SERVERS = {
    "GitHub MCP Server": "Repository, issue, and PR operations — "
        "read/create/comment without a custom GitHub API integration.",
    "Slack MCP Server": "Reading channel history, posting messages, "
        "searching Slack — a standard integration for agent notifications/actions.",
    "PostgreSQL MCP Server": "Query a Postgres database as a resource/"
        "tool — often with read-only enforcement configurable at the "
        "server level for safety.",
    "Google Drive MCP Server": "Search and read documents from Google "
        "Drive as resources.",
    "Filesystem MCP Server": "Read/write local files — should ALWAYS be "
        "sandboxed to a specific, restricted directory, never given "
        "unrestricted host filesystem access (see L22).",
}

# ------------------------------------------------------------------
# 5. The MCP Registry — discovering existing servers
# ------------------------------------------------------------------
REGISTRY_NOTE = (
    "The MCP Registry is a searchable, public catalog of published MCP "
    "servers — before building a custom integration for a common need "
    "(a popular SaaS tool, a common database type), checking the "
    "registry for an existing, maintained server is the first step, "
    "directly analogous to checking PyPI/npm before writing a library "
    "from scratch for a well-solved problem."
)


if __name__ == "__main__":
    print(FASTMCP_SERVER_EXAMPLE)
    print(MCP_CLIENT_EXAMPLE)

    print("=== MCP capability types ===")
    for cap, note in MCP_CAPABILITY_TYPES.items():
        print(f"{cap}: {note}\n")

    print("=== Common pre-built MCP servers ===")
    for server, note in COMMON_MCP_SERVERS.items():
        print(f"{server}: {note}\n")

    print(REGISTRY_NOTE)

"""
PRODUCTION CONTEXT EXAMPLE:
A company standardizes on MCP for ALL internal tool integrations —
their internal CRM, ticketing system, and deployment pipeline each get
ONE MCP server, and every team's agent (regardless of whether it's built
with LangGraph, CrewAI, or a vendor SDK from L18) connects to the SAME
servers. When the deployment pipeline's API changes, exactly ONE MCP
server needs updating, and every downstream agent automatically benefits
from the fix on their next connection — a maintenance win that would
have required updating N separate framework-specific tool
implementations without the protocol standardization MCP provides.
"""
