# ============================================================
# L01: Configuration Management Fundamentals
# ============================================================
# WHAT: The core problem configuration management tools solve — keeping
#       a fleet of servers in a known, consistent, reproducible state —
#       and the declarative-vs-imperative and idempotency principles
#       every tool in this space (Ansible, Puppet, Chef) implements.
# WHY: This repo's Platform Engineering Notes covers Terraform
#      (provisioning infrastructure — creating the VM/instance). This
#      domain covers what happens AFTER provisioning: configuring the
#      software/state ON that infrastructure reliably, at fleet scale,
#      without manually SSHing into every machine.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
CONFIGURATION DRIFT is the problem configuration management exists to
solve: over time, servers that started identical accumulate small,
undocumented differences — a manual fix applied to one server during an
incident, a package upgraded on one machine but not others, a config
file edited by hand once and never again. Without a system tracking and
enforcing "what SHOULD this machine look like," a fleet of "identical"
servers gradually becomes a fleet of subtly different, undocumented
snowflakes — and the server that fails differently from its peers during
an incident is a direct symptom of drift.

DECLARATIVE vs IMPERATIVE is the key design distinction across
configuration management tools: an IMPERATIVE approach describes the
STEPS to take ("install nginx, then start it, then copy this config
file") — you're scripting a procedure. A DECLARATIVE approach describes
the DESIRED END STATE ("nginx should be installed and running, this
config file should have this exact content") and lets the tool figure
out what steps are needed to REACH that state, INCLUDING deciding to do
NOTHING if the state already matches. Ansible, Puppet, and Chef (L02-L03)
all lean declarative for most operations, though Ansible retains more
imperative, "run these tasks in order" flavor than Puppet/Chef's more
purely declarative resource model.

IDEMPOTENCY is the property that makes declarative configuration safe to
apply REPEATEDLY: running the same configuration against a server
already in the desired state should be a NO-OP (or close to it) — not an
error, and not a duplicated action. This is the SAME idempotency
principle covered for data pipelines in this repo's Data Engineering
Notes L01, applied here to SYSTEM STATE instead of data — "install
nginx" run twice shouldn't install it twice or fail the second time;
"ensure this line exists in a config file" run twice shouldn't duplicate
the line.

PRODUCTION USE CASE:
A team investigating "why does server web-07 behave differently from
web-01 through web-06" discovers, via a configuration management tool's
own drift-detection report, that web-07 has a manually-installed package
version mismatch from an ad-hoc fix during a past incident that was
never reconciled back into the managed configuration — the drift report
surfaces this in seconds; without it, this kind of divergence typically
surfaces only when it CAUSES a production problem, and is then far
harder to root-cause.

COMMON MISTAKES:
- Making manual, one-off changes directly on a server "just this once"
  to fix an urgent issue, without ALSO updating the managed configuration
  to reflect that change — this is exactly how configuration drift
  accumulates, turning an "emergency fix" into permanent, undocumented divergence.
- Writing configuration management "playbooks"/"manifests" imperatively
  (a long sequence of shell-command-equivalent steps) instead of
  leveraging the tool's declarative resource primitives — this forfeits
  idempotency and makes the configuration harder to reason about as
  "what state does this produce," rather than "what steps does this run."
- Not treating configuration-as-code with the SAME rigor as application
  code — version control, code review, and testing apply to
  infrastructure configuration just as much as to application source code.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Configuration drift, illustrated
# ------------------------------------------------------------------
DRIFT_EXAMPLE = textwrap.dedent("""\
    Day 1: web-01 through web-07 are provisioned identically —
           nginx 1.24, a specific config file, a specific set of packages.

    Day 45: During an incident, an engineer manually upgrades nginx to
            1.26 on web-07 ONLY, to test a hotfix — the fix works, the
            incident resolves, and nobody updates the MANAGED
            configuration to reflect this change on the other 6 servers,
            or documents that web-07 is now different.

    Day 90: A NEW deployment assumes nginx 1.24's config syntax across
            the fleet — it breaks SPECIFICALLY on web-07, which nobody
            remembers is running a different version, because nothing
            has been tracking or reporting this divergence since day 45.

    This is DRIFT: undocumented, accumulated divergence from the
    intended, managed state — invisible until it causes a failure.
""")

# ------------------------------------------------------------------
# 2. Imperative vs declarative — the same task, two styles
# ------------------------------------------------------------------
IMPERATIVE_STYLE_EXAMPLE = textwrap.dedent("""\
    #!/bin/bash
    # IMPERATIVE: a sequence of STEPS — running this TWICE on a machine
    # already in the desired state either errors (apt-get install may
    # complain, or may not) or wastefully re-runs every step regardless
    # of current state.
    apt-get update
    apt-get install -y nginx
    systemctl start nginx
    cp nginx.conf /etc/nginx/nginx.conf
    systemctl restart nginx
""")

DECLARATIVE_STYLE_EXAMPLE = textwrap.dedent("""\
    # DECLARATIVE (Ansible task syntax, covered fully in L02): describes
    # the DESIRED STATE — Ansible itself determines what action (if any)
    # is needed to reach it, and running this repeatedly against an
    # already-compliant server does NOTHING on subsequent runs.
    - name: Ensure nginx is installed
      apt:
        name: nginx
        state: present   # "present" = desired state, not "install it now"

    - name: Ensure nginx is running
      service:
        name: nginx
        state: started   # again, a STATE, not a command — a no-op if
                           # nginx is already running

    - name: Ensure the correct config file is in place
      copy:
        src: nginx.conf
        dest: /etc/nginx/nginx.conf
      notify: restart nginx   # only restarts IF this task actually
                                # changed something — not unconditionally
""")

# ------------------------------------------------------------------
# 3. Idempotency, demonstrated with a minimal Python simulation
# ------------------------------------------------------------------
class ServerState:
    """A toy simulation of a server's configuration state, used to
    illustrate idempotent vs non-idempotent configuration application."""

    def __init__(self):
        self.installed_packages: set[str] = set()
        self.config_lines: list[str] = []

    def non_idempotent_ensure_package(self, package: str) -> str:
        """BAD: unconditionally 'installs' every time, even if already
        present — wasteful, and in a real system, can error on a second run."""
        self.installed_packages.add(package)
        return f"installed {package} (unconditionally)"

    def idempotent_ensure_package(self, package: str) -> str:
        """GOOD: checks CURRENT state first — a second call with the
        same package is a genuine no-op, exactly matching real
        configuration management tool behavior."""
        if package in self.installed_packages:
            return f"{package} already present — no action taken"
        self.installed_packages.add(package)
        return f"installed {package}"

    def idempotent_ensure_line_in_config(self, line: str) -> str:
        """GOOD: checks for EXISTENCE before appending — running this
        twice does NOT duplicate the line, unlike a naive `echo >> file`."""
        if line in self.config_lines:
            return f"line already present — no action taken"
        self.config_lines.append(line)
        return f"added line: {line}"


def idempotency_demo():
    server = ServerState()

    print("First application:")
    print(f"  {server.idempotent_ensure_package('nginx')}")
    print(f"  {server.idempotent_ensure_line_in_config('worker_processes auto;')}")

    print("\nRe-applying the SAME configuration (should be safe, no-op):")
    print(f"  {server.idempotent_ensure_package('nginx')}")
    print(f"  {server.idempotent_ensure_line_in_config('worker_processes auto;')}")

    print(f"\nFinal state: packages={server.installed_packages}, "
          f"config_lines={server.config_lines}  (unchanged by the re-application)")


if __name__ == "__main__":
    print(DRIFT_EXAMPLE)
    print(IMPERATIVE_STYLE_EXAMPLE)
    print(DECLARATIVE_STYLE_EXAMPLE)
    idempotency_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team runs their configuration management tool's compliance/
drift-check mode NIGHTLY across their entire fleet (not just when
applying changes) — this surfaces any manual, out-of-band change made
during an incident within 24 hours, prompting either a reconciliation
(formally incorporating the change into managed configuration) or a
remediation (reverting the drift) — turning "undetected drift causes a
mystery failure months later" into "detected and addressed within a day,"
purely by treating drift detection as a continuous, scheduled check
rather than something only noticed when applying NEW configuration changes.
"""
