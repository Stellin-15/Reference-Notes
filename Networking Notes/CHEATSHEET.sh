#!/usr/bin/env bash
# =============================================================================
# NETWORKING CHEATSHEET — In-Depth Reference
# Practical companion to "OS & Networking Internals Notes" (the theory track).
# Ports/protocols, subnetting, DNS, diagnostics, SSH tunneling, firewalls, TLS.
# Read top-to-bottom; run individually.
# =============================================================================


# =============================================================================
# 1. THE OSI / TCP-IP MODEL, QUICK MAP
# =============================================================================

# OSI Layer          TCP/IP Layer        Examples
# 7 Application       Application         HTTP, DNS, SSH, FTP, SMTP
# 6 Presentation       Application         TLS/SSL encoding
# 5 Session             Application         TLS session, sockets
# 4 Transport            Transport           TCP, UDP
# 3 Network                Internet            IP, ICMP, routing
# 2 Data Link                Link                Ethernet, ARP, switches
# 1 Physical                  Link                Cables, radio, NICs

# TCP: connection-oriented, ordered, reliable (3-way handshake: SYN, SYN-ACK, ACK)
# UDP: connectionless, unordered, no delivery guarantee, lower overhead (DNS, VoIP, QUIC/HTTP3)


# =============================================================================
# 2. COMMON PORTS — MEMORIZE THESE
# =============================================================================

# 20/21   FTP (data/control)          22   SSH / SFTP / SCP
# 23      Telnet (insecure, avoid)     25   SMTP (mail send)
# 53      DNS                            67/68 DHCP (server/client)
# 80      HTTP                             110  POP3
# 143     IMAP                               161/162 SNMP (agent/trap)
# 389     LDAP                                 443  HTTPS
# 445     SMB (Windows file sharing)             465/587 SMTPS / SMTP submission (TLS)
# 636     LDAPS                                    993  IMAPS
# 995     POP3S                                      3306 MySQL/MariaDB
# 5432    PostgreSQL                                   6379 Redis
# 8080    HTTP alt / common app port                    8443 HTTPS alt
# 9200    Elasticsearch                                   9092 Kafka
# 27017   MongoDB                                          3389 RDP


# =============================================================================
# 3. IP ADDRESSING & SUBNETTING
# =============================================================================

# CIDR notation: 192.168.1.0/24 -> /24 = 24 network bits, 8 host bits = 256 addresses (254 usable)
#
# Quick /prefix -> host count reference (usable = total - 2 for network+broadcast):
#   /24 -> 256 addrs (254 usable)     /25 -> 128 (126)
#   /26 -> 64 (62)                     /27 -> 32 (30)
#   /28 -> 16 (14)                       /29 -> 8 (6)
#   /30 -> 4 (2, point-to-point links)     /32 -> 1 (single host)
#
# Private (RFC 1918) ranges — never routed on the public internet:
#   10.0.0.0/8            (10.0.0.0    - 10.255.255.255)
#   172.16.0.0/12          (172.16.0.0  - 172.31.255.255)
#   192.168.0.0/16          (192.168.0.0 - 192.168.255.255)
#
# Loopback: 127.0.0.0/8 (127.0.0.1 = localhost)
# Link-local: 169.254.0.0/16 (APIPA — auto-assigned when DHCP fails)
#
# Subnet mask <-> CIDR:
#   /24 = 255.255.255.0     /25 = 255.255.255.128     /26 = 255.255.255.192
#   /27 = 255.255.255.224     /28 = 255.255.255.240      /29 = 255.255.255.248
#
# Quick subnetting example: split 192.168.1.0/24 into 4 subnets of /26 each:
#   192.168.1.0/26   (.0   - .63)    192.168.1.64/26  (.64  - .127)
#   192.168.1.128/26 (.128 - .191)   192.168.1.192/26 (.192 - .255)

ipcalc 192.168.1.0/24                # Compute network/broadcast/range (if installed)
sipcalc 192.168.1.0/24                  # Alternative subnet calculator


# =============================================================================
# 4. INTERFACE & ROUTE INSPECTION
# =============================================================================

ip a                                # All interfaces + assigned IPs (Linux, modern)
ip link                                # Interfaces only, no IP info
ip route                                 # Routing table
ip route get 8.8.8.8                        # Which route/interface would be used to reach an IP
ifconfig                                       # Legacy equivalent of `ip a` (deprecated but common in the wild)
route -n                                          # Legacy equivalent of `ip route`

# Windows equivalents:
#   ipconfig /all                    # Interfaces + IPs
#   route print                        # Routing table
#   Get-NetIPAddress                     # PowerShell equivalent


# =============================================================================
# 5. DNS
# =============================================================================

dig example.com                     # Full DNS query (A record by default)
dig example.com MX                     # Mail exchange records
dig example.com NS                        # Nameservers
dig example.com TXT                          # TXT records (SPF/DKIM/verification)
dig +short example.com                          # Just the answer, no verbose output
dig @8.8.8.8 example.com                           # Query a specific DNS server
dig -x 8.8.8.8                                        # Reverse lookup (IP -> hostname)
dig example.com +trace                                   # Trace the full resolution path from root

nslookup example.com                 # Simpler alternative to dig
host example.com                        # One-line lookup

# Common record types: A (IPv4), AAAA (IPv6), CNAME (alias), MX (mail),
# TXT (arbitrary text — SPF/DKIM/domain verification), NS (nameserver),
# SOA (zone authority), PTR (reverse lookup), SRV (service location).

cat /etc/hosts                         # Local hostname overrides (checked before DNS)
cat /etc/resolv.conf                     # Configured DNS resolvers (Linux)
systemd-resolve --status                    # Active resolver config (systemd-based distros)


# =============================================================================
# 6. CONNECTIVITY & LATENCY TESTS
# =============================================================================

ping example.com                    # ICMP echo — basic reachability + latency
ping -c 4 example.com                  # Send exactly 4 packets, then stop

traceroute example.com               # Hop-by-hop path to a destination (Linux/macOS)
tracert example.com                     # Windows equivalent
mtr example.com                            # Live combination of ping + traceroute, per-hop stats

curl -I https://example.com          # Headers only, HEAD-like request
curl -v https://example.com             # Verbose: shows TLS handshake, headers, timing
curl -w "@curl-format.txt" -o /dev/null -s https://example.com  # Custom timing breakdown
curl -o /dev/null -s -w "%{time_total}\n" https://example.com     # Just total time

telnet host 443                       # Test raw TCP connectivity to a port (no TLS)
nc -zv host 443                          # Netcat: quick TCP port check ("zero I/O", verbose)
nc -zv -u host 53                          # Same, but for UDP


# =============================================================================
# 7. LISTENING PORTS & ACTIVE CONNECTIONS
# =============================================================================

ss -tulpn                            # TCP+UDP listeners, numeric, with process (modern, fast)
ss -tan state established               # All established TCP connections
netstat -tulpn                             # Legacy equivalent of `ss -tulpn`
lsof -i :8080                                 # What process is bound to port 8080
lsof -i -P -n | grep LISTEN                      # All listening sockets, no name resolution


# =============================================================================
# 8. PACKET CAPTURE: TCPDUMP & WIRESHARK
# =============================================================================

tcpdump -i eth0                      # Capture on a specific interface
tcpdump -i any -n                       # All interfaces, no DNS resolution (faster, cleaner)
tcpdump -i eth0 port 443                   # Filter by port
tcpdump -i eth0 host 192.168.1.10             # Filter by host
tcpdump -i eth0 'tcp[13] & 2 != 0'                # SYN packets only (raw flag match)
tcpdump -i eth0 -w capture.pcap                     # Write to a file for later analysis
tcpdump -r capture.pcap                                # Read back a saved capture
tcpdump -i eth0 -A                                        # Print packet contents as ASCII (plaintext protocols)

# Wireshark filter syntax (GUI, or `tshark` for CLI):
#   http                              # All HTTP traffic
#   tcp.port == 443                     # Traffic on a specific port
#   ip.addr == 192.168.1.10                # Traffic to/from an IP
#   tcp.flags.syn == 1 && tcp.flags.ack == 0  # SYN packets (connection attempts)
#   dns                                          # All DNS traffic
tshark -i eth0 -f "port 80"          # CLI Wireshark equivalent, BPF filter syntax


# =============================================================================
# 9. SSH: TUNNELING & PORT FORWARDING
# =============================================================================

ssh user@host                        # Basic connection
ssh -i key.pem user@host                # Use a specific private key
ssh -p 2222 user@host                      # Non-default port

ssh -L 8080:localhost:80 user@host      # Local forward: localhost:8080 -> host's port 80
ssh -R 9000:localhost:3000 user@host       # Remote forward: host's 9000 -> your local 3000
ssh -D 1080 user@host                         # Dynamic forward: SOCKS proxy through the tunnel
ssh -N -L 5432:db-internal:5432 user@bastion    # Access a private DB through a bastion, no shell

ssh-keygen -t ed25519 -C "you@example.com"   # Generate a modern keypair
ssh-copy-id user@host                           # Install your public key on a remote host
ssh-add ~/.ssh/id_ed25519                          # Add a key to the running ssh-agent

cat <<'EOF'
# --- ~/.ssh/config — named host shortcuts ---
Host bastion
  HostName 1.2.3.4
  User ec2-user
  IdentityFile ~/.ssh/prod-key.pem

Host internal-db
  HostName 10.0.1.20
  User admin
  ProxyJump bastion              # Hop through "bastion" automatically
EOF
# Usage after the config above:  ssh internal-db


# =============================================================================
# 10. FIREWALLS: IPTABLES, UFW, NFTABLES
# =============================================================================

# --- ufw (Ubuntu-friendly wrapper) ---
ufw status verbose                   # Show current rules
ufw allow 22/tcp                        # Allow SSH
ufw allow from 10.0.0.0/8 to any port 5432  # Allow a subnet to a specific port
ufw deny 23                                # Explicitly deny a port
ufw enable                                    # Turn the firewall on
ufw delete allow 22/tcp                          # Remove a rule

# --- iptables (lower-level, still common in the wild) ---
iptables -L -n -v                    # List current rules, numeric, verbose
iptables -A INPUT -p tcp --dport 22 -j ACCEPT   # Allow inbound SSH
iptables -A INPUT -s 203.0.113.5 -j DROP           # Block a specific source IP
iptables -A INPUT -j DROP                             # Default-deny (put LAST, after allow rules)
iptables-save > /etc/iptables/rules.v4                  # Persist rules across reboot

# --- nftables (modern replacement for iptables) ---
nft list ruleset                     # Show all current rules/tables/chains
nft add rule inet filter input tcp dport 22 accept


# =============================================================================
# 11. TLS/SSL DIAGNOSTICS
# =============================================================================

openssl s_client -connect example.com:443            # Inspect the TLS handshake + cert chain
openssl x509 -in cert.pem -text -noout                  # Decode a certificate's contents
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | openssl x509 -noout -dates
  # ^ Quickly check a cert's expiry (notBefore/notAfter)
curl -vI https://example.com 2>&1 | grep -i "SSL\|subject\|expire"  # Cert info via curl

# TLS handshake summary: ClientHello -> ServerHello + certificate -> key exchange
# -> Finished (both sides) -> encrypted application data. TLS 1.3 collapses this
# to a single round trip (vs 2 in TLS 1.2), improving latency.


# =============================================================================
# 12. HTTP-LEVEL DEBUGGING
# =============================================================================

curl -X POST https://api.example.com/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"alice"}'                     # Full request with headers + JSON body

curl -L https://example.com                   # Follow redirects
curl --resolve example.com:443:1.2.3.4 https://example.com  # Override DNS for one request (test a specific backend)
curl -v --http2 https://example.com               # Force HTTP/2

# Status code families:
#   1xx Informational   2xx Success (200 OK, 201 Created, 204 No Content)
#   3xx Redirect (301 permanent, 302/307 temporary, 304 not modified)
#   4xx Client error (400 bad request, 401 unauthenticated, 403 forbidden,
#                       404 not found, 429 too many requests)
#   5xx Server error (500 internal, 502 bad gateway, 503 unavailable, 504 timeout)


# =============================================================================
# 13. LOAD BALANCERS, PROXIES & CDNs — CONCEPT QUICK REFERENCE
# =============================================================================

# L4 (transport) load balancing: routes on IP/port only, no visibility into HTTP —
#   faster, protocol-agnostic (works for any TCP/UDP traffic).
# L7 (application) load balancing: routes on HTTP path/host/headers —
#   enables path-based routing, sticky sessions, WAF rules, TLS termination.
#
# Reverse proxy vs forward proxy:
#   Reverse proxy (nginx, Envoy, HAProxy) sits in front of servers, hides backend topology.
#   Forward proxy sits in front of clients, hides client identity from the destination.
#
# Common health-check pattern: LB polls a /health or /healthz endpoint on each
# backend; unhealthy backends are pulled from rotation without dropping live traffic.
#
# CDN edge caching: static assets cached at edge PoPs close to users; cache-control
# headers (max-age, s-maxage, no-cache, stale-while-revalidate) govern behavior.


# =============================================================================
# 14. VPNs & NETWORK TUNNELS — CONCEPT QUICK REFERENCE
# =============================================================================

# IPsec: network-layer VPN, site-to-site common, uses IKE for key exchange.
# WireGuard: modern, minimal-config VPN using Curve25519/ChaCha20 — increasingly
#   the default choice for new deployments over legacy IPsec/OpenVPN.
# OpenVPN: mature, flexible, TLS-based, higher overhead than WireGuard.
# VPC Peering / Transit Gateway (cloud): private routing between VPCs without
#   traversing the public internet.

wg show                              # WireGuard: show active tunnels/peers
wg-quick up wg0                         # Bring up a WireGuard tunnel from config


# =============================================================================
# 15. QUICK TRIAGE CHECKLIST — "THE SITE IS DOWN"
# =============================================================================

# 1. ping <host>                 -> is the host reachable at all (ICMP)?
# 2. dig <domain>                -> is DNS resolving to the expected IP?
# 3. curl -v https://<domain>     -> where does the request fail (DNS/connect/TLS/HTTP)?
# 4. ss -tulpn | grep <port>        -> is the service actually listening?
# 5. traceroute/mtr <host>            -> where in the path is latency/loss occurring?
# 6. Check firewall/security group rules -> is the port allowed both directions?
# 7. Check the app's own logs                 -> often the real answer is above the network layer.


# =============================================================================
# 16. LINUX NETWORK NAMESPACES — WHAT ACTUALLY ISOLATES A CONTAINER'S NETWORK
# =============================================================================

# Every "container has its own IP/ports" claim (Docker, Kubernetes Pods) rests
# on one Linux primitive: network namespaces. Each namespace gets its own
# interfaces, routing table, iptables rules, and /proc/net — completely
# separate from the host's, connected back to it via a veth (virtual
# ethernet) pair, one end in the namespace, one end plugged into a bridge.

ip netns add mynet                    # Create a new, empty network namespace
ip netns list                            # List namespaces on this host
ip netns exec mynet ip a                    # Run a command INSIDE that namespace (no interfaces yet)
ip link add veth0 type veth peer name veth1   # Create a veth pair
ip link set veth1 netns mynet                    # Move one end into the namespace
ip netns exec mynet ip addr add 10.0.0.2/24 dev veth1  # Assign it an IP inside the namespace
ip netns exec mynet ip link set veth1 up             # Bring it up

# This is EXACTLY what `docker run` automates for you under the hood: create
# a namespace, create a veth pair, attach one end to the docker0 bridge,
# assign an IP from the bridge's subnet, set up NAT so the container can
# reach the internet. `nsenter` (see Docker Notes section 17) walks into an
# existing namespace the same way `ip netns exec` does.


# =============================================================================
# 17. VXLAN & OVERLAY NETWORKING — HOW DOCKER/K8s SPAN MULTIPLE HOSTS
# =============================================================================

# A single host's bridge network can't span machines — VXLAN (Virtual
# eXtensible LAN) solves that by encapsulating an entire Ethernet frame
# inside a UDP packet (port 4789) and shipping it over the REAL underlying
# network to another host, which unwraps it and delivers it to the right
# local namespace. This is the "overlay" in Docker Swarm overlay networks
# and the default mechanism behind Flannel's VXLAN backend and Calico's
# IPIP/VXLAN encapsulation modes in Kubernetes.
#
# Why it matters operationally: overlay traffic has encapsulation overhead
# (a few % throughput, extra CPU for encap/decap) and MTU implications — the
# outer UDP+VXLAN header eats into the payload's available MTU, and forgetting
# to lower the inner interface's MTU to compensate is a classic "container-to-
# container traffic mysteriously drops large packets" bug.

ip -d link show vxlan0               # Inspect a VXLAN interface's config (VNI, remote, port)
bridge fdb show                         # Forwarding database — which MAC lives behind which VTEP


# =============================================================================
# 18. TRAFFIC SHAPING & QoS: tc
# =============================================================================

# `tc` (traffic control) manipulates the kernel's queuing disciplines (qdiscs)
# on an interface — used to simulate bad networks for testing, or to actually
# enforce bandwidth/latency limits in production (ISPs, multi-tenant hosts).

tc qdisc add dev eth0 root netem delay 100ms 20ms loss 1%
  # ^ Simulate 100ms latency (+-20ms jitter) and 1% packet loss — extremely
  #   common in resilience testing (does your retry/timeout logic actually work?)
tc qdisc add dev eth0 root tbf rate 1mbit burst 32kbit latency 400ms
  # ^ Hard bandwidth cap of 1 Mbit/s (token bucket filter)
tc qdisc show dev eth0                  # Show current qdisc config
tc qdisc del dev eth0 root                 # Remove all shaping, back to default (pfifo_fast)


# =============================================================================
# 19. VLANs, NAT TYPES & IPv6 BASICS
# =============================================================================

# VLANs (802.1Q): a single physical switch is logically split into isolated
# broadcast domains by tagging Ethernet frames with a 12-bit VLAN ID (1-4094).
# Traffic between VLANs must pass through a router/L3 switch even if the
# hosts are plugged into the same physical switch — this is the fundamental
# segmentation tool in enterprise/campus networks and cloud VPC subnet design.

ip link add link eth0 name eth0.10 type vlan id 10   # Create a tagged VLAN sub-interface

# NAT types, precisely (matters for VoIP/gaming/P2P and interview questions):
#   Full Cone     -> once mapped, ANY external host can reach the internal host via that port
#   Restricted    -> external host can reach it only if the internal host sent to that IP first
#   Port-Restricted -> same as Restricted, but the IP+PORT pair must match what was sent to
#   Symmetric     -> a DIFFERENT external port is mapped per destination — breaks most P2P/STUN
# STUN/TURN/ICE (used by WebRTC) exist specifically to negotiate connectivity
# across these NAT types without a relay when possible (STUN), or by falling
# back to a relay server when direct P2P can't traverse symmetric NAT (TURN).

# IPv6 essentials:
#   Address form: 8 groups of 16 bits, hex, colon-separated, "::" collapses
#     one run of zero groups (2001:db8::1 = 2001:0db8:0000:...:0001)
#   No NAT needed in the traditional sense — address space is large enough for
#     every device to get a real routable (or ULA) address
#   fe80::/10  -> link-local (auto-assigned, not routed off the local segment)
#   fc00::/7   -> Unique Local Address (ULA) — IPv6's rough equivalent of RFC 1918 private space
#   SLAAC (Stateless Address Autoconfiguration) lets a host self-assign an
#     address from router advertisements, without needing DHCP at all

ping6 example.com                     # or: ping -6 example.com
ip -6 addr                               # Show IPv6 addresses on this host
ip -6 route                                 # IPv6 routing table


# =============================================================================
# 20. BGP & ANYCAST — HOW TRAFFIC ACTUALLY FINDS ITS WAY ACROSS THE INTERNET
# =============================================================================

# BGP (Border Gateway Protocol) is the routing protocol that glues together
# every Autonomous System (AS — a network under one administrative control,
# e.g. an ISP or a large cloud provider) on the internet. Routers advertise
# "I can reach this IP prefix" to their peers, who propagate it onward — the
# entire global routing table is built from these announcements, with no
# central authority computing it.
#   BGP hijacking: a misconfigured or malicious AS announces a prefix it
#     doesn't own, and traffic for that IP range gets misrouted toward it —
#     a real, recurring internet-outage/security incident class (worth
#     recognizing by name even without operating BGP directly yourself).
#   RPKI (Resource Public Key Infrastructure) is the emerging mitigation:
#     cryptographically signed statements of "this AS is authorized to
#     announce this prefix," checked by increasingly many transit providers.

# Anycast: the SAME IP address is announced via BGP from many physically
# distinct locations; BGP's normal shortest-path routing then delivers each
# client to whichever announcing location is topologically closest. This is
# how Cloudflare/major DNS root servers/CDNs serve one IP globally with low
# latency everywhere AND get free DDoS-traffic-spreading (an attack against
# the anycast IP lands on many locations at once, none overwhelmed alone) —
# instead of one single, poundable origin.


# =============================================================================
# 21. MODERN APPLICATION PROTOCOLS: gRPC, HTTP/2, HTTP/3 & WEBSOCKETS
# =============================================================================

# HTTP/1.1: one request in flight per TCP connection at a time (browsers
#   work around this by opening several parallel connections per host).
# HTTP/2: multiplexes many requests over a SINGLE TCP connection (streams),
#   adds header compression (HPACK) and server push — fixes head-of-line
#   blocking AT THE HTTP LAYER, but a single lost TCP packet still stalls
#   EVERY multiplexed stream on that connection (TCP-level head-of-line
#   blocking remains — this is exactly what HTTP/3 exists to fix).
# HTTP/3: runs over QUIC (built on UDP, not TCP) — each stream is
#   independently reliable, so one dropped packet only stalls its own
#   stream, not the whole connection; also folds the TLS handshake into
#   QUIC's own handshake for fewer round trips than TCP+TLS ever achieves.

curl --http3 https://example.com          # Force HTTP/3 (needs curl built with an HTTP/3 backend)
curl -v --http2-prior-knowledge https://example.com  # Skip HTTP/1.1 upgrade negotiation, go straight to h2

# gRPC: RPC framework built ON TOP of HTTP/2, using Protocol Buffers for a
# compact binary wire format instead of JSON — the dominant choice for
# internal service-to-service calls where you control both ends (schema-first,
# strongly typed, supports client/server/bidirectional streaming natively).
grpcurl -plaintext localhost:50051 list         # List services exposed by a gRPC server (like `curl` for gRPC)
grpcurl -plaintext localhost:50051 describe my.Service  # Inspect a service's methods/message shapes
grpcurl -plaintext -d '{"id": 1}' localhost:50051 my.Service/GetItem  # Call a method directly

# WebSockets: upgrade an HTTP/1.1 connection (via the `Upgrade` header) into
# a persistent, full-duplex TCP-like channel for arbitrary framed messages —
# used for anything needing server-initiated pushes without polling (chat,
# live dashboards, collaborative editing). Unlike HTTP/2 streams, a
# WebSocket connection is its own long-lived thing, not multiplexed with
# other HTTP traffic on the same connection.
websocat wss://example.com/socket        # Quick CLI WebSocket client for manual testing
