# ============================================================
# L03: Ansible vs Puppet vs Chef — Agentless vs Agent-Based Config Management
# ============================================================
# WHAT: A direct comparison of the three major configuration management
#       tools — Ansible's agentless, push-based model vs Puppet and
#       Chef's agent-based, pull-based models — and when each
#       architectural choice actually matters.
# WHY: L02 went deep on Ansible specifically. Real organizations
#      (especially larger, longer-established ones) frequently run
#      Puppet or Chef instead, or alongside Ansible — understanding the
#      actual architectural tradeoff (not just syntax differences) lets
#      you work effectively in either environment and make an informed
#      choice for a new one.
# LEVEL: Intermediate
# ============================================================

"""
CONCEPT OVERVIEW:
The single most consequential architectural difference: ANSIBLE is
AGENTLESS and PUSH-BASED — a control machine connects OUT to managed
hosts (via SSH) and pushes configuration changes on demand, whenever a
playbook is run. PUPPET and CHEF are AGENT-BASED and PULL-BASED — a
persistent agent daemon runs on EVERY managed host, periodically
(typically every 30 minutes) CHECKING IN with a central server and
PULLING/applying its assigned configuration, without needing an external
process to initiate anything.

This has real operational consequences: Ansible's push model means
configuration changes apply IMMEDIATELY when you run a playbook (good
for on-demand, "make it happen right now" changes), but requires
network connectivity FROM the control machine TO every host at the
moment you run it, and there's no AUTOMATIC periodic re-enforcement of
desired state unless you separately schedule playbook runs (e.g. via
cron). Puppet/Chef's pull model means EVERY host continuously and
automatically self-corrects toward its assigned state on its own
schedule (agents catch and fix drift within their check-in interval,
with NO external trigger needed) — a genuine advantage for continuous
drift correction, at the cost of running persistent agent software
(consuming resources, needing its own upgrade/patch cycle, another
piece of software that can itself fail or need troubleshooting) on
every managed host.

PUPPET uses its own declarative DSL (a Ruby-based, but not directly
Ruby, language) built around explicit RESOURCE DECLARATIONS and a
dependency graph the Puppet agent resolves. CHEF uses actual RUBY code
("recipes" and "cookbooks") — giving Chef more raw programming
flexibility (since you're writing real Ruby) at the cost of a
potentially less strictly declarative, more imperative-feeling authoring
experience if not disciplined about it.

CHOOSING between them today: ANSIBLE has become the dominant default for
NEW projects specifically because of its lower operational overhead (no
agents to manage) and gentler learning curve — but an organization with
an EXISTING, mature Puppet or Chef deployment (with years of accumulated
manifests/cookbooks and institutional expertise) often has good reasons
to continue investing in that tool rather than migrating purely for
Ansible's newer popularity, especially given Puppet/Chef's genuine
advantage in continuous, automatic drift correction across a very large fleet.

PRODUCTION USE CASE:
A long-established enterprise with thousands of servers and a decade of
Puppet manifests continues using Puppet specifically because of its
continuous, automatic drift-correction property at that scale — with
thousands of hosts, manually or cron-scheduling Ansible playbook runs
frequently enough to match Puppet's default 30-minute self-correction
interval would itself become significant operational overhead, whereas
Puppet's agents handle this natively without any external orchestration
needed at all.

COMMON MISTAKES:
- Assuming Ansible is strictly "better" because it's newer/more
  popular for greenfield projects, without considering an existing
  organization's actual accumulated tooling investment and the genuine
  architectural tradeoffs (continuous drift correction being a real
  Puppet/Chef advantage, not just legacy inertia).
- Running Ansible playbooks only ON-DEMAND (during deployments) without
  ALSO scheduling periodic runs (e.g. via cron or a CI schedule) to catch
  and correct drift continuously — this forfeits the automatic drift-
  correction property Puppet/Chef provide by default, unless deliberately replicated.
- Writing Chef "recipes" as unstructured, deeply imperative Ruby scripts
  instead of using Chef's own declarative resource primitives — this
  forfeits idempotency guarantees the framework is built to provide,
  the same category of mistake L01 flagged for imperative-style Ansible playbooks.
"""

from dataclasses import dataclass


# ------------------------------------------------------------------
# 1. Push vs pull — the core architectural difference, illustrated
# ------------------------------------------------------------------
PUSH_VS_PULL_NOTE = (
    "PUSH (Ansible): control machine -> SSH -> managed host, TRIGGERED by "
    "a human/CI process running a playbook. No agent, no persistent "
    "process on the managed host. Configuration applies immediately "
    "when triggered; drift is NOT automatically corrected between runs.\n\n"
    "PULL (Puppet/Chef): managed host's own agent -> periodically -> "
    "central server, TRIGGERED by the agent's own schedule (e.g. every "
    "30 min), with NO external process needed to initiate anything. "
    "Drift is automatically corrected on every check-in, continuously, "
    "at the cost of running persistent agent software on every host."
)

# ------------------------------------------------------------------
# 2. Puppet's declarative DSL
# ------------------------------------------------------------------
PUPPET_MANIFEST_EXAMPLE = """\
# nginx.pp — Puppet's own declarative DSL, resource-declaration style
class nginx {
  package { 'nginx':
    ensure => present,
  }

  file { '/etc/nginx/nginx.conf':
    ensure  => file,
    source  => 'puppet:///modules/nginx/nginx.conf',
    require => Package['nginx'],   # explicit DEPENDENCY — Puppet resolves
                                     # the resource graph, ensuring nginx
                                     # is installed BEFORE this file is placed
    notify  => Service['nginx'],    # analogous to Ansible's handler notify
  }

  service { 'nginx':
    ensure => running,
    enable => true,
  }
}
"""

# ------------------------------------------------------------------
# 3. Chef's Ruby-based cookbooks
# ------------------------------------------------------------------
CHEF_RECIPE_EXAMPLE = """\
# recipes/default.rb — Chef "recipes" are actual Ruby, using Chef's own
# RESOURCE primitives (package, template, service) for declarative,
# idempotent operations, embedded within a real programming language's
# full flexibility (conditionals, loops, custom logic) if genuinely needed.
package 'nginx' do
  action :install
end

template '/etc/nginx/nginx.conf' do
  source 'nginx.conf.erb'
  notifies :restart, 'service[nginx]'
end

service 'nginx' do
  action [:enable, :start]
end

# Because this IS Ruby, arbitrary logic is possible (for better or
# worse) — e.g. conditionally including a resource based on node
# attributes:
if node['platform_family'] == 'debian'
  package 'apt-transport-https'
end
"""

# ------------------------------------------------------------------
# 4. Direct comparison matrix
# ------------------------------------------------------------------
@dataclass
class ToolProfile:
    name: str
    architecture: str
    language: str
    agent_overhead: str
    best_fit: str


TOOL_PROFILES = [
    ToolProfile("Ansible", "Agentless, push-based (SSH)",
                "YAML + Jinja2 templating",
                "None — no persistent agent software to manage",
                "New projects, teams wanting the lowest operational "
                "overhead, on-demand/CI-triggered configuration changes"),
    ToolProfile("Puppet", "Agent-based, pull-based",
                "Puppet's own declarative DSL",
                "A persistent agent daemon on every managed host",
                "Large, established fleets wanting continuous, automatic "
                "drift correction with no external trigger needed"),
    ToolProfile("Chef", "Agent-based, pull-based",
                "Real Ruby (recipes/cookbooks)",
                "A persistent agent daemon on every managed host",
                "Teams wanting Puppet/Chef's continuous-correction model "
                "PLUS the flexibility of a full general-purpose language "
                "for genuinely complex configuration logic"),
]


def print_comparison():
    for p in TOOL_PROFILES:
        print(f"{p.name}")
        print(f"  architecture: {p.architecture}")
        print(f"  language: {p.language}")
        print(f"  agent overhead: {p.agent_overhead}")
        print(f"  best fit: {p.best_fit}\n")


if __name__ == "__main__":
    print(PUSH_VS_PULL_NOTE, "\n")
    print(PUPPET_MANIFEST_EXAMPLE)
    print(CHEF_RECIPE_EXAMPLE)
    print_comparison()

"""
PRODUCTION CONTEXT EXAMPLE:
A financial services company running Puppet across 5,000+ servers relies
specifically on its agents' automatic, continuous 30-minute drift
correction to maintain compliance posture (e.g. ensuring a security
patch or firewall rule stays applied even if manually reverted during an
incident) WITHOUT any human needing to remember to re-run a playbook —
the SAME organization's newer, smaller Kubernetes-based microservices
platform uses Ansible instead for its infrequent, on-demand infrastructure
bootstrapping tasks, where Puppet's continuous-correction model offers
no meaningful advantage over Ansible's simpler, agentless, on-demand approach.
"""
