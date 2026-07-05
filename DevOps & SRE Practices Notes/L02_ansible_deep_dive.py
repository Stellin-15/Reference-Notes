# ============================================================
# L02: Ansible Deep Dive — Playbooks, Roles, Inventory, Vault
# ============================================================
# WHAT: Ansible's actual object model — inventory (which hosts),
#       playbooks/tasks/modules (what to do), roles (reusable,
#       shareable bundles of tasks), and Ansible Vault (encrypting
#       secrets within version-controlled configuration).
# WHY: L01 covered configuration management CONCEPTS. Ansible is the
#      most widely adopted AGENTLESS configuration management tool
#      (no persistent agent software required on managed hosts, unlike
#      Puppet/Chef, L03) — this lesson maps those concepts onto Ansible's
#      concrete, installable API.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
An INVENTORY is Ansible's list of managed hosts, organized into GROUPS
(e.g. `webservers`, `dbservers`) — either a static file or a DYNAMIC
inventory script/plugin querying a cloud provider's API for current
instances (essential when hosts are ephemeral/autoscaled, since a static
list would immediately go stale).

A PLAYBOOK is a YAML file defining WHICH hosts to target and WHAT tasks
to run against them. Each TASK invokes a MODULE (Ansible's built-in
units of idempotent functionality — `apt`, `service`, `copy`, `template`,
hundreds more, each implementing the declarative "ensure this state"
pattern from L01) with specific parameters.

A ROLE is Ansible's REUSABILITY mechanism — a standardized directory
structure bundling related tasks, templates, files, and default
variables into one shareable, versioned unit (e.g. a "nginx" role
installable and reusable across many playbooks/projects, potentially
shared via Ansible Galaxy, the community role registry). Building
playbooks FROM roles rather than one large flat task list is what makes
Ansible configurations maintainable and reusable at real scale.

ANSIBLE VAULT solves a real, common problem: configuration inevitably
needs SECRETS (database passwords, API keys) but configuration should
live in VERSION CONTROL for the same review/audit/rollback benefits as
application code — Vault ENCRYPTS specific files or values within
otherwise-plaintext YAML, so secrets can be safely committed to git
(encrypted) while remaining usable by Ansible at execution time (given
the correct vault password/key, sourced from Vault-the-secrets-manager
or a similarly secure mechanism — this repo's Platform Engineering Notes
L03, don't confuse Ansible Vault the FEATURE with HashiCorp Vault the
PRODUCT, which are different things with similar names).

BEING AGENTLESS (Ansible connects over standard SSH, executing Python
on the remote host TEMPORARILY per run, with no persistent daemon left
running) is a meaningful operational simplicity advantage over
agent-based tools (Puppet/Chef, L03) — there's no separate agent
software to install, upgrade, or troubleshoot on every managed host; the
only requirement is SSH access and Python present on the target.

PRODUCTION USE CASE:
A platform team maintains a `web_servers` role (installing/configuring
nginx with a standard hardened config) and a `db_servers` role
(installing/configuring PostgreSQL with standard tuning), each
independently versioned and reusable — a new environment's playbook
simply references both roles by name with environment-specific
variables, rather than duplicating the actual task logic per environment.

COMMON MISTAKES:
- Maintaining a STATIC inventory file for infrastructure that's actually
  dynamic/autoscaled — the inventory silently goes stale, and playbook
  runs either miss newly-launched hosts or fail against terminated ones;
  a dynamic inventory plugin (querying the cloud provider directly) is
  required for genuinely elastic infrastructure.
- Committing SECRETS in plaintext within playbooks/variable files
  instead of using Ansible Vault (or an external secrets manager
  integration) — this is the exact security anti-pattern this repo's
  Auth & Security Notes L06 flags for application secrets, equally
  applicable to infrastructure configuration secrets.
- Writing one large, flat playbook instead of composing REUSABLE roles —
  this makes configuration hard to test, share, and reason about
  independently as the number of managed systems/environments grows.
"""

import textwrap


# ------------------------------------------------------------------
# 1. Inventory — static and dynamic
# ------------------------------------------------------------------
STATIC_INVENTORY_EXAMPLE = textwrap.dedent("""\
    # inventory.ini
    [webservers]
    web-01.internal ansible_host=10.0.1.10
    web-02.internal ansible_host=10.0.1.11

    [dbservers]
    db-01.internal ansible_host=10.0.2.10

    [production:children]
    webservers
    dbservers
""")

DYNAMIC_INVENTORY_EXAMPLE = textwrap.dedent("""\
    # inventory/aws_ec2.yml — a DYNAMIC inventory plugin, querying AWS
    # directly for CURRENT instances matching a filter — essential for
    # autoscaled fleets where a static list would immediately go stale.
    plugin: amazon.aws.aws_ec2
    regions: [us-east-1]
    filters:
      tag:Environment: production
      instance-state-name: running
    keyed_groups:
      - key: tags.Role
        prefix: role   # instances tagged Role=webserver -> group "role_webserver"
""")

# ------------------------------------------------------------------
# 2. Playbooks, tasks, and modules
# ------------------------------------------------------------------
PLAYBOOK_EXAMPLE = textwrap.dedent("""\
    # site.yml
    ---
    - name: Configure web servers
      hosts: webservers
      become: true   # run tasks with sudo/root privileges

      tasks:
        - name: Ensure nginx is installed
          ansible.builtin.apt:
            name: nginx
            state: present
            update_cache: true

        - name: Deploy nginx configuration from a template
          ansible.builtin.template:
            src: templates/nginx.conf.j2
            dest: /etc/nginx/nginx.conf
          notify: Restart nginx   # only fires the handler if this task CHANGED something

        - name: Ensure nginx is enabled and running
          ansible.builtin.service:
            name: nginx
            state: started
            enabled: true

      handlers:
        - name: Restart nginx
          ansible.builtin.service:
            name: nginx
            state: restarted
""")

TEMPLATE_EXAMPLE = textwrap.dedent("""\
    # templates/nginx.conf.j2 — a Jinja2 template, letting configuration
    # vary per host/group using Ansible VARIABLES, not hardcoded values.
    worker_processes {{ ansible_processor_vcpus }};
    events {
        worker_connections {{ nginx_worker_connections | default(1024) }};
    }
""")

# ------------------------------------------------------------------
# 3. Roles — reusable, shareable configuration bundles
# ------------------------------------------------------------------
ROLE_STRUCTURE_EXAMPLE = textwrap.dedent("""\
    roles/
      nginx/
        tasks/main.yml       # the actual task list (as in the playbook above)
        templates/nginx.conf.j2
        handlers/main.yml
        defaults/main.yml    # DEFAULT variable values, overridable by callers
        meta/main.yml        # role metadata, dependencies on OTHER roles

    # A playbook then simply REFERENCES roles by name:
    # site.yml
    - name: Configure web servers
      hosts: webservers
      roles:
        - role: nginx
          vars:
            nginx_worker_connections: 2048   # OVERRIDES the role's default

    # The SAME "nginx" role, unmodified, can be reused across MANY
    # playbooks/projects — sharable via Ansible Galaxy (ansible-galaxy
    # install geerlingguy.nginx, for example, is a widely-used community role).
""")

# ------------------------------------------------------------------
# 4. Ansible Vault — encrypting secrets within version control
# ------------------------------------------------------------------
VAULT_USAGE_EXAMPLE = textwrap.dedent("""\
    # Encrypt a file containing secrets (safe to commit afterward):
    ansible-vault encrypt group_vars/production/secrets.yml

    # The file's CONTENT is now encrypted at rest, but Ansible transparently
    # decrypts it in memory when running a playbook, given the vault password:
    ansible-playbook site.yml --ask-vault-pass

    # Or, in CI/CD, provide the password via a file (itself protected by
    # the CI system's own secrets management, not committed to git):
    ansible-playbook site.yml --vault-password-file /run/secrets/vault_pass

    # Encrypting just ONE variable within an otherwise-plaintext file
    # (useful for keeping most of the file human-readable in diffs):
    ansible-vault encrypt_string 'super-secret-db-password' --name 'db_password'
    # -> produces a `db_password: !vault | ...` block to paste into a
    #    plaintext YAML file — only that ONE value is encrypted.
""")


if __name__ == "__main__":
    print(STATIC_INVENTORY_EXAMPLE)
    print(DYNAMIC_INVENTORY_EXAMPLE)
    print(PLAYBOOK_EXAMPLE)
    print(TEMPLATE_EXAMPLE)
    print(ROLE_STRUCTURE_EXAMPLE)
    print(VAULT_USAGE_EXAMPLE)

"""
PRODUCTION CONTEXT EXAMPLE:
A platform team's CI/CD pipeline runs `ansible-playbook site.yml` against
a DYNAMIC AWS EC2 inventory on every deployment — newly autoscaled
instances are automatically included without any manual inventory
update, secrets (database passwords, API keys) are stored Vault-encrypted
directly in the same git repository as the rest of the configuration
(satisfying both "secrets never in plaintext" and "everything is
version-controlled and reviewable"), and the actual configuration logic
lives in shared, versioned roles reused identically across staging and
production, with only environment-specific variables differing between them.
"""
