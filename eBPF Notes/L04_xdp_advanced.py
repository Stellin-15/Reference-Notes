# ============================================================
# L04: XDP (eXpress Data Path) — Advanced Packet Processing
# ============================================================
# WHAT: Running BPF programs at the earliest possible point in the network
#       receive path — inside the NIC driver, before the kernel allocates
#       an sk_buff for the packet.
# WHY (PRODUCTION): This is the fastest place in the Linux networking stack
#       to drop or redirect a packet. For DDoS mitigation and high-throughput
#       load balancing, XDP processes tens of millions of packets/sec per
#       core — orders of magnitude faster than iptables/netfilter, which
#       operates much later in the stack after per-packet allocation.
# LEVEL: Advanced / Staff
# ============================================================

"""
CONCEPT OVERVIEW:
XDP hooks run per-packet, before the kernel's normal networking stack even
sees the packet. The program returns one of a small set of verdicts:
XDP_PASS (continue normal processing), XDP_DROP (discard, cheapest possible
DDoS mitigation), XDP_TX (bounce back out the same interface), XDP_REDIRECT
(send to another interface or into a userspace AF_XDP socket), or
XDP_ABORTED (drop + trace event, for debugging).

Hook modes, in order of performance:
  - Native/driver mode: runs INSIDE the NIC driver's receive path. Fastest,
    but requires driver support (most major NIC vendors support it now).
  - Generic mode: runs later, in the generic kernel receive path — works on
    any NIC but with lower performance (essentially "XDP semantics without
    the driver-level speed").
  - Offload mode: runs ON THE NIC HARDWARE ITSELF (SmartNICs) — fastest
    possible, but limited program complexity and rare hardware support.

PRODUCTION USE CASE:
Facebook's Katran and Cloudflare's L4 load balancer both use XDP to
implement a stateless load balancer that can absorb volumetric DDoS attacks
by dropping malicious packets at line rate, and forward legitimate traffic
via XDP_REDIRECT to backend servers — all without the kernel's normal
socket/routing stack overhead per packet.

COMMON MISTAKES:
- Writing unbounded loops when parsing packet headers — the BPF verifier
  rejects any program it can't prove terminates; header-parsing must use
  explicit bounds checks at every offset access.
- Forgetting bounds checks on `data`/`data_end` pointers before dereferencing
  — the verifier requires an explicit comparison before every packet-data
  access, or it rejects the program as a potential out-of-bounds read.
- Using XDP for stateful connection tracking without understanding it's
  fundamentally a PER-PACKET hook — state must be maintained explicitly in
  BPF maps, there's no automatic connection tracking like conntrack.
"""

import textwrap

# ------------------------------------------------------------------
# 1. XDP verdicts
# ------------------------------------------------------------------
XDP_VERDICTS = {
    "XDP_PASS": "Continue normal kernel network stack processing.",
    "XDP_DROP": "Discard the packet immediately — the cheapest possible "
                "action, used for DDoS mitigation (block malicious source IPs).",
    "XDP_TX": "Transmit the packet back out the SAME interface it arrived "
              "on, after potentially rewriting it (e.g. an XDP-based echo/reflector).",
    "XDP_REDIRECT": "Send the packet to a DIFFERENT interface, or into an "
                     "AF_XDP userspace socket for kernel-bypass processing.",
    "XDP_ABORTED": "Drop + emit a trace event — used during development/debugging.",
}

# ------------------------------------------------------------------
# 2. Parsing packet headers with mandatory bounds checks
# ------------------------------------------------------------------
XDP_PARSE_PROGRAM = textwrap.dedent("""\
    // xdp_drop_udp_port.c — drops UDP packets to a specific port (e.g.
    // mitigating a UDP amplification attack targeting one service port)
    #include <linux/bpf.h>
    #include <linux/if_ether.h>
    #include <linux/ip.h>
    #include <linux/udp.h>
    #include <bpf/bpf_helpers.h>
    #include <bpf/bpf_endian.h>

    #define TARGET_PORT 11211  // e.g. memcached — a classic amplification vector

    SEC("xdp")
    int xdp_drop_udp(struct xdp_md *ctx) {
        void *data     = (void *)(long)ctx->data;
        void *data_end = (void *)(long)ctx->data_end;

        // The verifier REQUIRES this bounds check before any dereference
        // of `eth` — without it, the program is rejected at load time,
        // because the verifier can't statically prove the access is safe.
        struct ethhdr *eth = data;
        if ((void *)(eth + 1) > data_end)
            return XDP_PASS;   // truncated packet — let the kernel handle it

        if (eth->h_proto != bpf_htons(ETH_P_IP))
            return XDP_PASS;   // not IPv4 — nothing to inspect here

        struct iphdr *ip = (void *)(eth + 1);
        if ((void *)(ip + 1) > data_end)
            return XDP_PASS;

        if (ip->protocol != IPPROTO_UDP)
            return XDP_PASS;

        struct udphdr *udp = (void *)ip + (ip->ihl * 4);
        if ((void *)(udp + 1) > data_end)
            return XDP_PASS;

        if (bpf_ntohs(udp->dest) == TARGET_PORT) {
            return XDP_DROP;   // drop at the earliest possible point —
                                // this packet never reaches the socket layer
        }
        return XDP_PASS;
    }
    char _license[] SEC("license") = "GPL";
""")

# ------------------------------------------------------------------
# 3. IP blocklist via LPM trie map — CIDR-aware matching
# ------------------------------------------------------------------
LPM_TRIE_BLOCKLIST = textwrap.dedent("""\
    // BPF_MAP_TYPE_LPM_TRIE supports LONGEST-PREFIX-MATCH lookups —
    // essential for CIDR-based blocklists (e.g. block 10.0.0.0/8 as one
    // entry instead of 16 million individual /32 entries).
    struct {
        __uint(type, BPF_MAP_TYPE_LPM_TRIE);
        __uint(map_flags, BPF_F_NO_PREALLOC);
        __type(key, struct { __u32 prefixlen; __u32 addr; });
        __type(value, __u8);
        __uint(max_entries, 10000);
    } blocklist SEC(".maps");

    SEC("xdp")
    int xdp_ip_blocklist(struct xdp_md *ctx) {
        // ... parse eth/ip headers with bounds checks as above ...
        struct { __u32 prefixlen; __u32 addr; } key = {32, ip->saddr};
        __u8 *blocked = bpf_map_lookup_elem(&blocklist, &key);
        if (blocked)
            return XDP_DROP;
        return XDP_PASS;
    }
""")

# ------------------------------------------------------------------
# 4. XDP_REDIRECT — load balancing pattern (Katran-style)
# ------------------------------------------------------------------
XDP_LOAD_BALANCER_SKETCH = textwrap.dedent("""\
    // Simplified load-balancer sketch: hash the source IP/port to pick a
    // backend, rewrite the destination MAC/IP to that backend, and
    // XDP_REDIRECT the packet out — the backend receives packets directly
    // (Direct Server Return), and its reply traffic bypasses the load
    // balancer entirely on the return path, avoiding it becoming a
    // bandwidth bottleneck.

    struct {
        __uint(type, BPF_MAP_TYPE_HASH);
        __type(key, __u32);        // backend index
        __type(value, struct backend_info);  // MAC + IP of a real server
        __uint(max_entries, 64);
    } backends SEC(".maps");

    SEC("xdp")
    int xdp_load_balance(struct xdp_md *ctx) {
        // ... parse headers, bounds-check ...
        __u32 backend_idx = hash_5tuple(ip->saddr, ip->daddr,
                                         udp->source, udp->dest) % NUM_BACKENDS;
        struct backend_info *backend = bpf_map_lookup_elem(&backends, &backend_idx);
        if (!backend)
            return XDP_PASS;

        // Rewrite dest MAC to the chosen backend (L2 DSR-style redirect)
        __builtin_memcpy(eth->h_dest, backend->mac, ETH_ALEN);
        return bpf_redirect_map(&tx_port_map, backend->ifindex, 0);
    }
""")

# ------------------------------------------------------------------
# 5. TC (Traffic Control) BPF — egress filtering
# ------------------------------------------------------------------
TC_BPF_NOTE = (
    "XDP only hooks INGRESS (packets arriving). For egress filtering "
    "(controlling packets LEAVING the host), attach a BPF program to the "
    "TC (Traffic Control) qdisc clsact hook instead — same BPF C skills, "
    "different attach point:\n"
    "  tc qdisc add dev eth0 clsact\n"
    "  tc filter add dev eth0 egress bpf da obj tc_egress.o sec classifier\n"
)

# ------------------------------------------------------------------
# 6. AF_XDP — kernel-bypass userspace packet processing
# ------------------------------------------------------------------
AF_XDP_NOTE = (
    "XDP_REDIRECT can target an AF_XDP socket instead of another network "
    "interface — this hands raw packets directly to a USERSPACE process, "
    "bypassing the kernel networking stack entirely after the initial XDP "
    "hook. This is the eBPF-native alternative to DPDK: userspace gets "
    "near-line-rate packet access without needing a fully kernel-bypass "
    "poll-mode NIC driver — the kernel driver is still used, but the "
    "per-packet path after the XDP hook skips socket buffer allocation."
)

# ------------------------------------------------------------------
# 7. XDP vs DPDK vs netfilter — when to use which
# ------------------------------------------------------------------
COMPARISON_TABLE = {
    "netfilter/iptables": "Runs late in the stack (post sk_buff "
        "allocation). Easiest to operate (mature tooling), lowest "
        "throughput ceiling of the three.",
    "XDP": "Runs earliest in-kernel, before sk_buff allocation. Near-DPDK "
        "throughput while STAYING INSIDE the kernel's normal driver model "
        "— no dedicated poll-mode CPU cores required, coexists with normal "
        "kernel networking for non-XDP traffic.",
    "DPDK": "Full kernel bypass — a userspace poll-mode driver owns the "
        "NIC entirely. Highest possible throughput, but dedicates whole "
        "CPU cores to busy-polling and the NIC becomes unusable for "
        "normal kernel networking while DPDK owns it.",
}

if __name__ == "__main__":
    for verdict, desc in XDP_VERDICTS.items():
        print(f"{verdict}: {desc}")

"""
TRADING/PRODUCTION CONTEXT EXAMPLE:
An exchange's market-data multicast gateway uses XDP to drop malformed or
unauthorized-source UDP packets at the NIC driver level before they ever
reach the application's socket buffer, protecting the feed handler from
both malicious traffic and misbehaving upstream senders — critical because
even a small amount of jitter introduced by unnecessary kernel-stack
traversal on bad packets could affect the deterministic low-latency
processing of legitimate market data packets.
"""
