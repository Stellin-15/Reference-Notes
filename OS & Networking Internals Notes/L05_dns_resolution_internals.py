# ============================================================
# L05: DNS Resolution Internals
# ============================================================
# WHAT: What ACTUALLY happens when a program looks up "example.com" —
#       the recursive resolver, the hierarchical root/TLD/authoritative
#       server chain, and caching/TTLs — the mechanism underneath
#       every single network request that uses a domain name.
# WHY: This repo's System Design Case Studies Notes L21-L26 (load
#      balancers, reverse proxies) and DevOps & SRE Practices Notes L05
#      mention DNS as a component without covering its actual
#      resolution mechanics — this lesson opens that specific abstraction.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
DNS (Domain Name System) translates HUMAN-READABLE domain names
(example.com) into the IP addresses computers actually use to route
network traffic — it's organized as a GLOBALLY DISTRIBUTED, HIERARCHICAL
system, NOT a single central database, which is exactly what allows it
to scale to handle the entire internet's naming needs without any
single point of failure or bottleneck.

THE RESOLUTION CHAIN, walked through for a fresh lookup of
"www.example.com": (1) your device asks a RECURSIVE RESOLVER (typically
provided by your ISP, or a public one like Google's 8.8.8.8 or
Cloudflare's 1.1.1.1) to resolve the name — this resolver does the
actual multi-step work on your behalf; (2) the recursive resolver
first asks a ROOT SERVER (one of only 13 logical root server
addresses globally, though each is actually replicated across MANY
physical machines worldwide via anycast) — the root server doesn't know
the actual answer, but tells the resolver WHICH server handles the
".com" TOP-LEVEL DOMAIN (TLD); (3) the resolver asks that TLD server,
which similarly doesn't know the final answer but tells it WHICH
server is AUTHORITATIVE for "example.com" specifically; (4) the
resolver FINALLY asks that AUTHORITATIVE server, which returns the
actual IP address for "www.example.com" — this is a genuinely
multi-step, hierarchical delegation process, though it typically
completes in milliseconds and, critically, is HEAVILY CACHED at every
level to avoid repeating this full chain for every single lookup.

CACHING AND TTL (Time To Live): every DNS response includes a TTL value
(in seconds) indicating how long the answer may be CACHED before it
should be considered stale and re-queried — this caching happens at
MULTIPLE levels simultaneously (your OS's own resolver cache, your
recursive resolver's cache, and potentially your browser's own DNS
cache) — this is WHY changing a DNS record (e.g. pointing a domain to a
new server) does NOT take effect instantly everywhere: any resolver
that already cached the OLD answer will continue serving it until that
cached entry's TTL expires — this "TTL PROPAGATION DELAY" is a genuine,
practically important consideration when planning infrastructure
changes (like migrating to new servers) that involve a DNS record update.

RECORD TYPES serve different specific purposes: an A record maps a
name directly to an IPv4 address (AAAA for IPv6); a CNAME record maps
a name to ANOTHER name (an alias, useful for pointing multiple names
at one canonical target without duplicating IP address management); an
MX record specifies mail server(s) for a domain; a TXT record holds
arbitrary text data (commonly used for domain ownership verification
and email security policies like SPF/DKIM).

PRODUCTION USE CASE:
A company migrating from an old hosting provider to a new one updates
their domain's A record to point to the new provider's IP address —
because the PREVIOUS record had a TTL of 24 hours, some fraction of
users (whose resolvers had cached the old answer before the change)
continue being routed to the OLD server for up to 24 hours after the
change — a well-planned migration proactively LOWERS the TTL well in
advance of the actual cutover (e.g. to 5 minutes, days ahead of time),
so that by the time the actual migration happens, cached entries expire
quickly and the cutover propagates to users much faster.

COMMON MISTAKES:
- Expecting a DNS record change to take effect INSTANTLY for all users
  everywhere — TTL-based caching at multiple layers means propagation
  is GRADUAL, not instant, and planning any DNS-dependent cutover
  without accounting for this can cause confusing, hard-to-diagnose
  "some users still see the old behavior" symptoms during a migration.
- Setting an extremely LONG TTL for a record expected to change soon
  (or one used for failover purposes) — this directly slows down how
  quickly a change (or a failover to a backup server) actually reaches
  users, since cached resolvers will keep serving the stale answer for
  the full TTL duration regardless of the actual updated record.
- Confusing "DNS resolution is slow" with "the actual server/application
  is slow" — a slow DNS lookup (uncached, requiring the full
  root->TLD->authoritative chain) adds LATENCY BEFORE any actual
  application request even begins; distinguishing DNS resolution time
  from application response time is an important diagnostic
  distinction when investigating perceived slowness.
"""

import time


# ------------------------------------------------------------------
# 1. The resolution chain, illustrated step by step
# ------------------------------------------------------------------
def simulate_dns_resolution_chain(domain: str) -> dict:
    steps = [
        {"step": "Query recursive resolver", "response": "I don't know yet, let me find out"},
        {"step": "Recursive resolver queries ROOT server", "response": "Ask the .com TLD server"},
        {"step": "Recursive resolver queries .com TLD server", "response": f"Ask example.com's authoritative server"},
        {"step": "Recursive resolver queries AUTHORITATIVE server", "response": "IP address: 93.184.216.34"},
    ]
    print(f"Resolving '{domain}' (uncached, full chain):\n")
    for s in steps:
        print(f"  {s['step']}")
        print(f"    -> {s['response']}")
    return {"domain": domain, "resolved_ip": "93.184.216.34"}


def resolution_chain_demo():
    result = simulate_dns_resolution_chain("www.example.com")
    print(f"\nFinal result: {result}")
    print("  -> This full chain typically completes in single-digit")
    print("     milliseconds, but only needs to happen ONCE per TTL")
    print("     period — caching (below) avoids repeating it for every request.")


# ------------------------------------------------------------------
# 2. Caching and TTL — why DNS changes propagate gradually
# ------------------------------------------------------------------
class DNSCache:
    def __init__(self):
        self.cache: dict[str, dict] = {}

    def cache_response(self, domain: str, ip: str, ttl_seconds: int, cached_at: float):
        self.cache[domain] = {"ip": ip, "ttl": ttl_seconds, "cached_at": cached_at}

    def lookup(self, domain: str, now: float) -> str | None:
        entry = self.cache.get(domain)
        if entry and (now - entry["cached_at"]) < entry["ttl"]:
            return entry["ip"]   # still within TTL — serve from cache
        return None   # cache miss or expired — would need a fresh lookup


def ttl_propagation_demo():
    print("\nTTL propagation delay during a server migration:\n")
    cache = DNSCache()
    now = time.time()

    cache.cache_response("api.example.com", "10.0.0.1", ttl_seconds=86400, cached_at=now)  # OLD server, 24h TTL
    print(f"  User's resolver cached OLD IP (10.0.0.1) with a 24-hour TTL at t=0")

    print(f"\n  Company updates DNS to point to NEW server (10.0.0.99) at t=0")
    print(f"  ...but this user's cached entry is still within its TTL window")

    cached_ip = cache.lookup("api.example.com", now=now + 3600)   # 1 hour later
    print(f"  1 hour later, this user's resolver STILL returns: {cached_ip} (STALE)")
    print("  -> This user won't see the new server until the cached entry's")
    print("     24-hour TTL fully expires — this is why proactively LOWERING")
    print("     TTL well before a planned migration is standard practice.")


if __name__ == "__main__":
    resolution_chain_demo()
    ttl_propagation_demo()

"""
PRODUCTION CONTEXT EXAMPLE:
A platform planning a major infrastructure migration lowers their
critical DNS records' TTL from 24 hours to 5 minutes a full week
BEFORE the actual cutover — by the time the migration happens, virtually
all previously-cached entries (from the old, longer TTL) have long
since expired and been re-cached with the new, short TTL — meaning the
ACTUAL cutover (updating the record to point to the new
infrastructure) propagates to the vast majority of users within
minutes rather than being spread unpredictably across up to 24 hours,
directly illustrating why TTL planning is a genuine, standard part of any DNS-involving migration runbook.
"""
