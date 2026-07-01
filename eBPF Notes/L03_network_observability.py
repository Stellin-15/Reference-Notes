# ============================================================
# L03: Network Observability with eBPF
# ============================================================
# WHAT: eBPF provides deep network visibility — per-connection metrics,
#       packet-level tracing, TCP internals (RTT, retransmits), and
#       XDP-based packet processing — all without libpcap overhead.
# WHY:  Traditional network tools (tcpdump, netstat) either have high
#       overhead or miss short-lived connections. eBPF hooks into the
#       kernel TCP stack and network device layer for zero-miss, low-cost
#       visibility at any scale.
# LEVEL: Foundation
# ============================================================
"""
CONCEPT OVERVIEW:
    eBPF attaches to multiple layers of the Linux network stack. XDP hooks
    at the NIC driver level before the kernel allocates socket buffers.
    TC (Traffic Control) hooks at the qdisc layer with full sk_buff access.
    Tracepoints like tcp:tcp_probe and net:net_dev_xmit expose TCP internals.
    kprobes on tcp_sendmsg, tcp_recvmsg, tcp_v4_connect give per-connection
    visibility. Together they let you trace any network event without
    installing agents in applications or deploying sidecars.

PRODUCTION USE CASE:
    Cloudflare's DDoS mitigation drops >100 Gbps of attack traffic using
    XDP eBPF programs that inspect and drop packets in under 1 microsecond
    — before they touch the kernel networking stack. Meta's network team
    uses eBPF to collect per-flow metrics across millions of connections
    per second with <1% CPU overhead.

COMMON MISTAKES:
    1. Using tcpdump (pcap) for production monitoring — copies entire packets
       to userspace, high overhead. eBPF extracts only needed fields in kernel.
    2. Forgetting byte order: IP addresses and ports in kernel structs are in
       network byte order (big-endian). Use ntohs()/ntohl() to convert.
    3. XDP programs attached in XDP_DRV mode require driver support. Use
       XDP_SKB (generic) mode as fallback — lower performance but universal.
    4. Tracing tcp_probe tracepoint but not enabling it first:
       echo 1 > /proc/sys/net/ipv4/tcp_probe_interval
    5. Building a connection table in eBPF without LRU map — unbounded growth.
       Always use BPF_MAP_TYPE_LRU_HASH for connection tables.
"""

# ============================================================
# SECTION 1: XDP — PACKET PROCESSING AT LINE RATE
# ============================================================
# XDP (eXpress Data Path) processes packets at the network driver level.
# The eBPF program runs before the kernel allocates an sk_buff — this is
# why it's so fast. On supported drivers it runs directly on NIC hardware.

xdp_hook_levels = {
    "XDP_DRV (native)": {
        "description": "Runs in NIC driver interrupt handler, before sk_buff allocation",
        "performance": "Highest — 20-100 million packets/second on modern hardware",
        "requirement": "NIC driver must have XDP support (mlx5, i40e, ixgbe, etc.)",
        "use_case": "DDoS mitigation, load balancing in production",
    },
    "XDP_SKB (generic/fallback)": {
        "description": "Runs after sk_buff allocation, in generic kernel path",
        "performance": "Lower than native but still faster than iptables",
        "requirement": "Any network interface — always available",
        "use_case": "Development, testing, VMs without NIC XDP support",
    },
    "XDP_HW (offload)": {
        "description": "Runs on NIC hardware itself (SmartNIC / FPGA)",
        "performance": "Maximum — zero CPU cycles for packet processing",
        "requirement": "SmartNIC with eBPF offload support (Netronome Agilio, etc.)",
        "use_case": "Carrier-grade DDoS mitigation, telco packet processing",
    },
}

# XDP return codes — what to do with each packet:
xdp_return_codes = {
    "XDP_DROP":     "Discard packet immediately (free memory, send no response)",
    "XDP_PASS":     "Pass to normal kernel networking stack (sk_buff path)",
    "XDP_TX":       "Retransmit packet out the same interface",
    "XDP_REDIRECT": "Forward packet to different interface/CPU/socket",
    "XDP_ABORTED":  "Error occurred — drop + increment counter (for debugging)",
}

# Minimal XDP DDoS drop program in C:
xdp_ddos_drop_c = """
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <bpf/bpf_helpers.h>

// Blocklist: set of IP addresses to drop immediately
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10000);
    __type(key,   __u32);   // source IP
    __type(value, __u8);    // 1 = blocked
} blocklist SEC(".maps");

SEC("xdp")
int xdp_drop_blocked(struct xdp_md *ctx) {
    // ctx->data and ctx->data_end are pointers to packet start/end.
    // The verifier requires all pointer arithmetic to be bounds-checked.
    void *data_end = (void *)(long)ctx->data_end;
    void *data     = (void *)(long)ctx->data;

    // Parse Ethernet header
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;   // malformed: let kernel handle it

    // Only process IPv4
    if (eth->h_proto != __constant_htons(ETH_P_IP))
        return XDP_PASS;

    // Parse IP header
    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return XDP_PASS;

    // Check blocklist — O(1) hash lookup
    __u32 src_ip = ip->saddr;
    __u8 *blocked = bpf_map_lookup_elem(&blocklist, &src_ip);
    if (blocked && *blocked == 1) {
        return XDP_DROP;   // silently discard — attacker gets no ICMP response
    }

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
"""

# Load XDP program (using ip command):
# sudo ip link set dev eth0 xdp obj xdp_drop.o sec xdp
# sudo ip link set dev eth0 xdp off   # remove

# ============================================================
# SECTION 2: PARSING PACKET HEADERS IN XDP
# ============================================================
# Every XDP program accesses packet bytes via data/data_end pointers.
# The verifier enforces that EVERY access is bounds-checked.
# Failure to check bounds = program rejected by verifier.

packet_parsing_pattern = """
// Standard pattern for safe packet parsing in XDP:

// Step 1: Get packet boundaries
void *data_end = (void *)(long)ctx->data_end;
void *data     = (void *)(long)ctx->data;
void *pos      = data;   // current parse position

// Step 2: Parse Ethernet (14 bytes)
struct ethhdr *eth = pos;
pos += sizeof(struct ethhdr);
if (pos > data_end) return XDP_PASS;   // MUST check after every advance

// Step 3: Check EtherType for IPv4
if (eth->h_proto != bpf_htons(ETH_P_IP)) return XDP_PASS;

// Step 4: Parse IPv4 header (variable length — check ihl field)
struct iphdr *ip = pos;
if (pos + sizeof(struct iphdr) > data_end) return XDP_PASS;
pos += ip->ihl * 4;   // ihl = header length in 32-bit words

// Step 5: Parse TCP or UDP
if (ip->protocol == IPPROTO_TCP) {
    struct tcphdr *tcp = pos;
    if ((void *)(tcp + 1) > data_end) return XDP_PASS;
    __u16 dport = bpf_ntohs(tcp->dest);   // convert from network byte order
    // ... process TCP
} else if (ip->protocol == IPPROTO_UDP) {
    struct udphdr *udp = pos;
    if ((void *)(udp + 1) > data_end) return XDP_PASS;
    // ... process UDP
}
"""

# ============================================================
# SECTION 3: TCP OBSERVABILITY WITH TRACEPOINTS
# ============================================================
# The kernel exports stable TCP tracepoints for deep TCP visibility.
# These are safer than kprobes — they won't break across kernel updates.

tcp_tracepoints = {
    "tcp:tcp_probe": {
        "fires_when": "TCP sends/receives data — provides RTT and window info",
        "fields": "saddr, daddr, sport, dport, snd_nxt, snd_una, snd_cwnd, ssthresh, snd_wnd, srtt, rcv_wnd",
        "enable": "echo 1 > /proc/sys/net/ipv4/tcp_probe_interval",
        "use_case": "Measure RTT, detect congestion, monitor slow-start vs. congestion-avoidance",
    },
    "tcp:tcp_retransmit_skb": {
        "fires_when": "TCP retransmits a segment (packet loss event)",
        "fields": "skaddr, sport, dport, saddr, daddr, state",
        "use_case": "Count retransmits per connection, correlate with network path issues",
    },
    "tcp:tcp_destroy_sock": {
        "fires_when": "TCP socket is closed and destroyed",
        "use_case": "Connection lifecycle tracking, detect connection churn",
    },
    "sock:inet_sock_set_state": {
        "fires_when": "TCP state machine transitions (LISTEN→SYN_SENT→ESTABLISHED→etc.)",
        "fields": "skaddr, oldstate, newstate, sport, dport, saddr, daddr, protocol",
        "use_case": "Full connection lifecycle. newstate=TCP_CLOSE → connection closed.",
    },
    "net:net_dev_xmit": {
        "fires_when": "Packet transmitted on network device",
        "fields": "dev_name, len, rc (return code)",
        "use_case": "Per-interface send rate, packet counts",
    },
    "skb:kfree_skb": {
        "fires_when": "Packet dropped anywhere in the kernel",
        "fields": "skbaddr, location (code pointer), reason (kernel 5.17+)",
        "use_case": "Debug packet drops — get reason and code location",
    },
}

# ============================================================
# SECTION 4: TCP CONNECTION TRACKER (BCC)
# ============================================================
# Track all TCP connections: count per dest IP:port, measure duration,
# detect anomalies (many short connections = port scan or connection churn).

tcp_tracker_bpf = """
#include <uapi/linux/ptrace.h>
#include <net/sock.h>
#include <net/inet_sock.h>
#include <linux/tcp.h>

struct conn_key_t {
    u32 saddr;
    u32 daddr;
    u16 sport;
    u16 dport;
};

struct conn_val_t {
    u64 start_ns;    // connection start time
    u64 tx_bytes;    // bytes sent (updated on TCP send events)
    u32 pid;
    char comm[TASK_COMM_LEN];
};

// Active connection table (LRU to auto-evict stale entries)
BPF_LRU_HASH(conns, struct conn_key_t, struct conn_val_t, 65536);

// Completed connections: key=dest IP, value=count
BPF_HASH(dest_counts, u32, u64);

// Duration histogram for completed connections
BPF_HISTOGRAM(duration_ms, u64);

// Event output for new connections
BPF_PERF_OUTPUT(new_conn_events);

// Trace tcp_v4_connect (entry: socket just created, destination known)
int trace_connect(struct pt_regs *ctx, struct sock *sk) {
    struct inet_sock *inet = (struct inet_sock *)sk;
    struct conn_key_t key  = {};

    bpf_probe_read_kernel(&key.saddr, sizeof(key.saddr), &inet->inet_saddr);
    bpf_probe_read_kernel(&key.daddr, sizeof(key.daddr), &inet->inet_daddr);
    bpf_probe_read_kernel(&key.sport, sizeof(key.sport), &inet->inet_sport);
    bpf_probe_read_kernel(&key.dport, sizeof(key.dport), &inet->inet_dport);

    struct conn_val_t val = {};
    val.start_ns = bpf_ktime_get_ns();
    val.pid      = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&val.comm, sizeof(val.comm));

    conns.update(&key, &val);

    // Emit new connection event to userspace
    new_conn_events.perf_submit(ctx, &val, sizeof(val));
    return 0;
}

// Trace tcp_close (connection ending)
int trace_close(struct pt_regs *ctx, struct sock *sk) {
    struct inet_sock *inet = (struct inet_sock *)sk;
    struct conn_key_t key  = {};
    bpf_probe_read_kernel(&key.saddr, sizeof(key.saddr), &inet->inet_saddr);
    bpf_probe_read_kernel(&key.daddr, sizeof(key.daddr), &inet->inet_daddr);
    bpf_probe_read_kernel(&key.sport, sizeof(key.sport), &inet->inet_sport);
    bpf_probe_read_kernel(&key.dport, sizeof(key.dport), &inet->inet_dport);

    struct conn_val_t *val = conns.lookup(&key);
    if (val) {
        u64 duration_ms_val = (bpf_ktime_get_ns() - val->start_ns) / 1000000;
        duration_ms.increment(bpf_log2l(duration_ms_val));

        // Count connections per destination IP
        u64 *cnt = dest_counts.lookup_or_try_init(&key.daddr, &(u64){0});
        if (cnt) (*cnt)++;

        conns.delete(&key);
    }
    return 0;
}
"""

# ============================================================
# SECTION 5: PACKET DROP ANALYSIS
# ============================================================
# Dropped packets are a common source of mysterious network issues.
# eBPF can trace the exact kernel location and reason for every drop.

packet_drop_bpftrace = """
#!/usr/bin/env bpftrace
// File: drop_reason.bt
// Requires kernel 5.17+ for drop reason field
// Run: sudo bpftrace drop_reason.bt

#include <linux/skbuff.h>

// kfree_skb fires when any packet is dropped anywhere in the kernel
kprobe:kfree_skb
{
    // arg0 = sk_buff pointer, arg1 = void* location (code address)
    $skb = (struct sk_buff *)arg0;
    @drops_by_caller[ksym(arg1)] = count();
}

// tracepoint version (kernel 5.17+) includes reason enum
tracepoint:skb:kfree_skb
{
    // args->reason: SKB_DROP_REASON_NOT_SPECIFIED, SKB_DROP_REASON_NO_SOCKET, etc.
    @drops_by_reason[args->reason] = count();
    @drops_by_dev[args->dev_name]  = count();
}

interval:s:5
{
    printf("\\n=== Packet Drops (last 5s) ===");
    print(@drops_by_caller);
    print(@drops_by_reason);
    clear(@drops_by_caller);
    clear(@drops_by_reason);
}
"""

# ============================================================
# SECTION 6: PER-PROCESS NETWORK USAGE
# ============================================================
# Associate network activity with processes — something netstat cannot do
# for short-lived connections. Track bytes sent/received per PID.

per_process_net_bpf = """
#include <uapi/linux/ptrace.h>
#include <net/sock.h>

struct proc_key_t {
    u32  pid;
    char comm[TASK_COMM_LEN];
};

BPF_HASH(tx_bytes, struct proc_key_t, u64);
BPF_HASH(rx_bytes, struct proc_key_t, u64);

// tcp_sendmsg: userspace wrote data to TCP socket
int trace_sendmsg(struct pt_regs *ctx, struct sock *sk,
                  struct msghdr *msg, size_t size) {
    struct proc_key_t key = {};
    key.pid = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&key.comm, sizeof(key.comm));

    u64 *bytes = tx_bytes.lookup_or_try_init(&key, &(u64){0});
    if (bytes) __sync_fetch_and_add(bytes, size);
    return 0;
}

// tcp_recvmsg: userspace read data from TCP socket
int trace_recvmsg(struct pt_regs *ctx, struct sock *sk,
                  struct msghdr *msg, size_t len, int nonblock,
                  int flags, int *addr_len) {
    struct proc_key_t key = {};
    key.pid = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&key.comm, sizeof(key.comm));

    // Return value (actual bytes received) captured in kretprobe
    // Here we just mark this TID as in-flight for kretprobe correlation
    return 0;
}
"""

# ============================================================
# SECTION 7: PORT SCAN DETECTION
# ============================================================
# Detect port scanning: same source IP connecting to many different ports
# within a short time window. Pure eBPF — no userspace needed for decision.

port_scan_detection_bpftrace = """
#!/usr/bin/env bpftrace
// File: detect_portscan.bt
// Alert if any source connects to >20 distinct ports in 10 seconds

#include <linux/socket.h>

kprobe:tcp_v4_connect
{
    $sk = (struct sock *)arg0;
    // Track (source_pid, dest_port) combinations
    @port_count[pid, comm] = count();
}

interval:s:10
{
    // Print processes with suspiciously high connection diversity
    printf("\\n[%s] Port connection counts (10s window):\\n", strftime("%H:%M:%S", nsecs));
    print(@port_count);

    // In production: emit alert if any count > threshold
    // (bpftrace can't do conditional alerting well — use BCC for that)
    clear(@port_count);
}
"""

# ============================================================
# SECTION 8: CILIUM HUBBLE — L7 NETWORK OBSERVABILITY
# ============================================================
# Hubble is built on top of Cilium (which uses eBPF) to provide
# Layer 7 (HTTP, gRPC, DNS, Kafka) visibility for Kubernetes.

hubble_cli_commands = {
    "Install Hubble": [
        "helm install cilium cilium/cilium --set hubble.enabled=true --set hubble.relay.enabled=true",
        "cilium hubble enable",
    ],
    "Observe all traffic": [
        "hubble observe",
        "hubble observe --follow",
    ],
    "Filter by namespace": [
        "hubble observe --namespace production",
    ],
    "L7 HTTP traffic": [
        "hubble observe --type l7 --protocol http",
        "hubble observe --type l7 --protocol http --http-status 5xx",
    ],
    "Specific pod traffic": [
        "hubble observe --pod frontend --pod backend",
        "hubble observe --from-pod web-frontend --to-pod api-server",
    ],
    "DNS queries": [
        "hubble observe --type l7 --protocol dns",
    ],
    "Connection drops (policy violations)": [
        "hubble observe --verdict DROPPED",
        "hubble observe --verdict DROPPED --namespace prod",
    ],
    "Service map": [
        "hubble observe --output json | jq '.flow.source.labels, .flow.destination.labels'",
        "# Or use Hubble UI: kubectl port-forward -n kube-system svc/hubble-ui 12000:80",
    ],
    "Metrics": [
        "# Hubble exports Prometheus metrics:",
        "hubble_flows_processed_total{subtype,type,verdict}",
        "hubble_tcp_flags_total{flag,direction}",
        "hubble_drop_total{direction,reason}",
    ],
}

# ============================================================
# SECTION 9: TCP RTT AND RETRANSMIT MONITORING (bpftrace)
# ============================================================

tcp_metrics_bt = """
#!/usr/bin/env bpftrace
// File: tcp_metrics.bt
// Monitor TCP RTT and retransmits

#include <linux/tcp.h>
#include <net/sock.h>

// tcp_probe gives us RTT measurements (must enable probe interval)
// echo 1 > /proc/sys/net/ipv4/tcp_probe_interval
tracepoint:tcp:tcp_probe
{
    // args->srtt is in microseconds * 8 (kernel internal units)
    $rtt_us = args->srtt >> 3;
    @rtt_us = hist($rtt_us);

    // Track by destination
    $daddr = args->daddr;
    @rtt_by_dst[$daddr] = avg($rtt_us);
}

// Count retransmissions (packet loss events)
tracepoint:tcp:tcp_retransmit_skb
{
    @retransmits[args->saddr, args->daddr, args->dport] = count();
}

interval:s:10
{
    printf("\\n=== TCP RTT Distribution (us) ===\\n");
    print(@rtt_us);

    printf("\\n=== Retransmits by connection ===\\n");
    print(@retransmits);

    clear(@rtt_us);
    clear(@retransmits);
}
"""

print("eBPF L03: Network observability loaded.")
print(f"TCP tracepoints documented: {len(tcp_tracepoints)}")
print(f"XDP hook levels: {len(xdp_hook_levels)}")
print(f"XDP return codes: {len(xdp_return_codes)}")
