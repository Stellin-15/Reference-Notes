# DevOps & SRE Practices — Principal Engineer Deep Dive

Companion to L01-L12. Pushes past the lesson files into niche tooling, real
production tradeoffs, and interview-grade depth.


## L01-L03 — Configuration Management, Ansible, Ansible vs Puppet vs Chef

**Beyond the lesson**: Push (Ansible) vs pull (Puppet/Chef) isn't just an
architectural preference — it changes your failure mode. A push model means
a central control node initiates every change; if that node is compromised,
it can push to everything it has access to at once (a real supply-chain
risk surface). A pull model means each node independently checks in on its
own schedule; compromise of the central server requires an attacker to
plant a malicious manifest and WAIT for nodes to pull it, which is slower
but also means no single push event can instantly hit the whole fleet.

**Worked example**: Ansible idempotency in practice — `ansible.builtin.copy`
computes a checksum of the destination file before deciding whether to
report "changed," so re-running the SAME playbook against an
already-converged host reports zero changes; a shell task running a raw
`command:` module has NO such awareness and reports "changed" (and RE-RUNS
the command) every single time unless you add explicit `creates:`/`when:` guards.

**Tradeoff table**:
| Tool | Model | Language | Best fit |
|---|---|---|---|
| Ansible | Push, agentless (SSH) | YAML | Ad-hoc + scheduled, no agent install needed |
| Puppet | Pull, agent-based | Puppet DSL | Large fleets needing continuous drift correction |
| Chef | Pull, agent-based | Ruby DSL | Teams wanting full programming-language flexibility |

**Interview Q&A**:
- *Q: Why might a shop choose Puppet over Ansible for 10,000 servers?* A: Continuous drift correction — Puppet agents check in and self-correct on an interval automatically; Ansible only converges state at the moment you run a playbook, so drift between runs goes undetected until the next explicit run.


## L04 — Linux Systems Administration

**Beyond the lesson**: `systemd` unit dependency ordering (`Wants=`,
`Requires=`, `After=`, `Before=`) is the source of most "service started
before its dependency was ready" production incidents — `After=` only
controls ORDER, not readiness; a service marked `After=postgresql.service`
still starts the instant postgresql's unit is "active," which for a
database might be milliseconds before it can actually accept connections.
The real fix is an explicit readiness check (`ExecStartPre=` polling the
port, or a proper `Type=notify` service that signals systemd only once truly ready).

**Interview Q&A**:
- *Q: A service works when started manually but fails on boot. Why?* A: Classic ordering/readiness gap — a dependency (network, disk mount, DB) that's available by the time you SSH in manually may not be up yet during the boot sequence; `journalctl -b` and checking the unit's `After=`/`Requires=` against what it actually needs is the diagnostic path.


## L05 — Network Engineering for DevOps

**Beyond the lesson**: DNS TTL tuning is a real production lever most
teams never touch until an incident forces it — a 24-hour TTL means a
failover DNS change takes up to 24 hours to fully propagate to every
resolver that cached the old answer; dropping TTL to 60s BEFORE a planned
migration (days in advance) is standard practice specifically so a real
failover later actually takes effect quickly.

**Interview Q&A**:
- *Q: Load balancer health checks are green but users report 5xx errors. What do you check?* A: The health check endpoint's SCOPE — a `/health` returning 200 from the web server process alone doesn't verify the app can reach its database/cache/downstream dependencies; a shallow health check can stay green while the app is fundamentally broken for real traffic.


## L06 — Load & Performance Testing

**Beyond the lesson**: k6 vs Locust vs JMeter, precisely — k6 (JS-based,
scriptable, great CI integration, lower resource overhead per virtual user)
is the modern default for API load testing; Locust (Python, code-first,
easy to model complex user behavior/state machines) wins when the test
scenario itself is genuinely complex business logic; JMeter (GUI-first,
huge protocol support including legacy ones) still wins in shops needing
protocols/plugins the newer tools don't cover, or where non-engineers author tests.

**Worked example**: A load test showing "acceptable" p50 latency that
masked a p99 that was 40x worse — the fix wasn't more load, it was actually
LOOKING at percentile distributions, not averages; a system that's fine for
99% of users but unusable for the unluckiest 1% still fails at scale (that
1% is a LOT of real users at production volume).

**Interview Q&A**:
- *Q: A load test passes in staging but the same load causes outages in production. Why?* A: Staging almost never has production's real data volume/skew (a query that's fast against 10k rows can be catastrophic against 500M), nor production's actual network topology/multi-tenant noisy-neighbor effects — load testing against a materially smaller/cleaner dataset validates code paths, not real capacity.


## L07 — Capacity Planning

**Beyond the lesson**: Little's Law (`L = λW` — average number in system
equals arrival rate times average time in system) is the actual math behind
"why did adding more workers fix a queue backlog" — if requests arrive
faster than they're processed, the backlog (L) grows without bound
regardless of how good each individual request's average latency (W) looks;
capacity planning that only watches per-request latency and ignores arrival
rate vs throughput will miss a queue that's silently building toward collapse.

**Interview Q&A**:
- *Q: How do you size for a traffic spike you've never seen before (a new product launch)?* A: Model against a comparable known event if one exists, load-test synthetically to 3-5x the best estimate, build in autoscaling headroom with a FAST scale-up trigger (not just average-CPU-over-5-minutes, which reacts too slowly for a sudden spike), and have a manual capacity override ready as a fallback if autoscaling itself lags the actual spike rate.


## L08-L09 — Incident Command, Postmortems, Blameless Culture

**Beyond the lesson**: The Incident Commander role's ENTIRE job is
coordination, explicitly NOT hands-on debugging — the moment the IC starts
personally troubleshooting, the coordination function (who's doing what,
what's been tried, when to escalate, communicating to stakeholders) has no
owner, and that's usually the point incidents drag on longer than the
technical fix alone would require.

**Worked example**: A blameless postmortem's actual output isn't "what
mistake did person X make" — it's "what about our SYSTEM made this mistake
easy to make and hard to catch." A deploy that skipped a canary stage
because a script had a silent default-to-skip flag isn't "the engineer
should have checked more carefully" — it's "the script's default behavior
was unsafe," a fixable systemic gap versus an unfixable human-vigilance ask.

**Interview Q&A**:
- *Q: How do you keep a postmortem blameless when the root cause really was someone fat-fingering a command?* A: Ask "what made that command easy to run accidentally, with no confirmation/guardrail, against production" — the fix is almost always a missing safeguard (confirmation prompt, permission scoping, staging-only default), not a demand that humans stop being human.


## L10 — SRE Error Budgets & Toil

**Beyond the lesson**: An error budget is a POLICY LEVER, not just a metric
— once a service has burned its error budget for the period, the actual
enforced consequence (freezing feature releases until reliability work
restores the budget) is what makes SLOs meaningful; an SLO tracked but never
tied to a real consequence just becomes a dashboard nobody acts on.

**Worked example**: Toil identification in practice — work is toil if it's
manual, repetitive, automatable, tactical (no lasting value), and scales
linearly with service growth. A quarterly manual cert rotation across 200
servers is toil; a one-time migration, however tedious, is NOT toil by this
definition (it doesn't recur and scale) — the distinction matters because
SRE teams should spend their automation effort on the former, not burn out
"automating" one-off work that wouldn't have paid back the investment anyway.

**Interview Q&A**:
- *Q: Your service has a 99.9% SLO and is currently at 99.95%. Should the team ship a risky feature?* A: The error budget (0.1% allowed unavailability) still has headroom (currently only using 0.05%) — this is EXACTLY the situation an error budget exists for: spend some of that remaining budget on calculated risk, rather than treating 99.9% as a floor to defend at all costs regardless of budget remaining.


## L11 — On-Call Practices

**Beyond the lesson**: Alert fatigue has a measurable failure mode — once
an on-call engineer has been paged more than roughly 2 times in a shift for
non-actionable alerts, response quality on the NEXT alert (real or not)
measurably degrades. The fix isn't "try harder to stay alert," it's cutting
alert volume at the SOURCE: every alert should map to an action the
on-call person can actually take, or it shouldn't page a human at all
(route it to a dashboard/ticket instead).

**Interview Q&A**:
- *Q: How do you design a fair on-call rotation across time zones?* A: Follow-the-sun rotation where each region's team covers only local waking hours (best fairness, needs 3+ regions), or explicit compensation/time-off for after-hours pages combined with a hard cap on consecutive on-call weeks per person — fairness here is a policy decision, not a scheduling algorithm problem alone.


## NICHE BUT REAL

- **Chaos Engineering in production** — tools like Gremlin/Chaos Mesh
  deliberately inject failures (kill a pod, add network latency, exhaust
  disk) in a CONTROLLED, monitored way to verify resilience assumptions
  actually hold, rather than discovering them during a real outage.
- **Game days** — scheduled, simulated incident-response drills (a fake
  outage the on-call team must actually respond to) that surface runbook
  gaps and team-coordination issues without any real customer impact.
- **The "swiss cheese model" of incident causation** — borrowed from
  aviation/medical safety science: incidents happen when multiple
  independent, normally-harmless weaknesses align (each "hole" in a slice
  of cheese lining up) — used to argue against single-root-cause thinking
  in postmortems.
- **SLI/SLO/SLA precisely distinguished**: SLI is the measured indicator
  (e.g. request latency), SLO is the internal target for that indicator
  (p99 < 300ms), SLA is the externally-facing CONTRACTUAL commitment usually
  with financial penalties for breach — an SLA is typically set looser than
  the internal SLO specifically to leave margin for error.
- **Runbook-as-code** — executable runbooks (a script/workflow an on-call
  engineer runs rather than a static doc they read) reduce the chance of a
  tired 3am engineer mistyping a critical remediation command.
- **DORA metrics** (deployment frequency, lead time for changes, change
  failure rate, time to restore service) — the four metrics the DevOps
  Research and Assessment program found most correlated with high-performing
  engineering orgs; commonly asked about by name in senior interviews.
