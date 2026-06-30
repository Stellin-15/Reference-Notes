#!/bin/bash

# ============================================================
# L04: Docker Networking — Container Communication
# ============================================================
# WHAT: How Docker manages container networking: the built-in
#       network drivers, how containers find each other by name,
#       port publishing mechanics, and network security isolation.
# WHY:  Networking is the connective tissue of a microservices
#       architecture. Getting it wrong means services can't talk
#       to each other, security holes are opened, or performance
#       suffers. Understanding Docker networking prevents a whole
#       class of production incidents.
# LEVEL: Advanced
# ============================================================
# CONCEPT OVERVIEW:
#   Docker's networking is managed by the Docker daemon via
#   libnetwork. It uses a pluggable driver model:
#
#   DRIVER    | USE CASE
#   --------- | -----------------------------------------------
#   bridge    | Default. Containers on same host communicate.
#   host      | Container shares host network namespace.
#   none      | No networking (completely isolated).
#   overlay   | Multi-host networking (Docker Swarm, Kubernetes).
#   macvlan   | Container gets its own MAC/IP on physical network.
#
# PRODUCTION USE CASE:
#   A typical production app: web → api → postgres + redis.
#   All services need to talk to each other (bridge/overlay),
#   but only web should be reachable from the internet (-p 80:80).
#   postgres and redis must NEVER be exposed to the host network.
#
# COMMON MISTAKES:
#   - Using the default "bridge" network (loses DNS resolution)
#   - Hardcoding container IP addresses (they change on restart)
#   - Exposing database ports to the host in production
#   - Using host networking without understanding the security cost
#   - Not isolating services into separate networks by trust level
# ============================================================


# ============================================================
# PART 1: THE DEFAULT BRIDGE NETWORK (docker0)
# ============================================================
# When Docker installs, it creates a virtual bridge called "docker0"
# on the host: 172.17.0.0/16 by default.
#
# Every container started WITHOUT --network gets attached to this
# bridge and receives an IP like 172.17.0.2, 172.17.0.3, etc.
#
# THE PROBLEM: The default bridge does NOT support DNS resolution
# between containers. You cannot reach "my-api" by hostname.
# You must hardcode the IP — which changes every restart.
#
# THIS IS WHY: Always create custom bridge networks.
# Custom bridges support automatic DNS (containers resolve by name).

# See the default bridge:
docker network ls
# NETWORK ID     NAME      DRIVER    SCOPE
# abc123456789   bridge    bridge    local    ← docker0, default
# def987654321   host      host      local    ← host networking
# ghi111222333   none      null      local    ← no networking


# ============================================================
# PART 2: CUSTOM BRIDGE NETWORKS — The right way
# ============================================================
# Creating a custom bridge network enables:
#   1. Automatic DNS: containers find each other by container name
#   2. Isolation: containers on different networks can't talk
#   3. Custom subnet/gateway: control your IP address space
#   4. Network-scoped aliases: --network-alias for service discovery

docker network create \
    --driver bridge \
    --subnet 172.20.0.0/16 \
    --ip-range 172.20.240.0/20 \
    --gateway 172.20.0.1 \
    --label project=myapp \
    myapp-network
# --driver bridge:        Use the bridge driver (default, can omit)
# --subnet:               The full IP block for this network
# --ip-range:             Narrower range Docker assigns from (avoids
#                         conflicts if multiple networks share subnet)
# --gateway:              The host-side IP for this bridge interface
# --label:                Metadata for filtering/tooling

# List all networks:
docker network ls
# Filter by label:
docker network ls --filter "label=project=myapp"

# Inspect a network (shows connected containers + IPs):
docker network inspect myapp-network
# Key fields in the JSON output:
#   "Containers": { "<id>": { "Name": "...", "IPv4Address": "..." } }
#   "IPAM.Config": [ { "Subnet": "172.20.0.0/16", ... } ]


# ============================================================
# PART 3: CONTAINER DNS — How containers find each other
# ============================================================
# On a custom bridge network, Docker runs an embedded DNS server
# at 127.0.0.11 inside each container. It intercepts DNS queries
# and resolves container names to their current IP addresses.
#
# Start an API server:
docker run -d \
    --name my-api \
    --network myapp-network \
    my-api-image:1.0

# Start a web server on the SAME network:
docker run -d \
    --name my-web \
    --network myapp-network \
    my-web-image:1.0

# Inside my-web, you can now reach my-api by NAME:
#   curl http://my-api:8000/health
#   ping my-api
#
# Docker resolves "my-api" → 172.20.x.x automatically.
# No hardcoded IPs. Works even if my-api is restarted (new IP,
# same name — DNS re-resolves on the next query).

# NETWORK ALIASES: Multiple containers, one DNS name (load balancing)
docker run -d \
    --name api-1 \
    --network myapp-network \
    --network-alias api \
    my-api-image:1.0

docker run -d \
    --name api-2 \
    --network myapp-network \
    --network-alias api \
    my-api-image:1.0

# Now "api" resolves to BOTH api-1 and api-2.
# Docker DNS returns both IPs (round-robin).
# Your app can use "http://api:8000" and Docker load-balances.
# This is the primitive behind Docker Swarm VIPs.


# ============================================================
# PART 4: HOST NETWORKING — Maximum performance, no isolation
# ============================================================
# With host networking, the container shares the HOST's network
# namespace entirely. There is no bridge, no NAT, no port
# mapping overhead.
#
# USE WHEN:
#   - Network throughput is critical (HFT, high-speed trading,
#     packet capture, network monitoring tools)
#   - The app opens many dynamic ports (FTP passive mode, WebRTC)
#   - Latency is measured in microseconds and you can't afford NAT
#
# DO NOT USE WHEN:
#   - You care about security isolation (container can bind to
#     any host port, including privileged ports <1024)
#   - Running multiple containers with the same port requirement
#     (they'd conflict — only one can own port 80)
#   - Running in Kubernetes (host networking requires special
#     pod security policy; prefer hostPort if necessary)

docker run -d \
    --network host \
    --name metrics-collector \
    prometheus:v2.51.0
# Prometheus now binds to 0.0.0.0:9090 on the HOST.
# No -p needed (there's no bridge to publish through).
# Access at http://host-ip:9090

# HOST NETWORKING AND LINUX NAMESPACES:
# --network host = share net namespace with host
# The container still has its own PID, mnt, uts namespaces.
# It's not full host access — just the network stack is shared.


# ============================================================
# PART 5: NONE NETWORK — Total isolation
# ============================================================
# --network none gives the container only a loopback interface.
# No external connectivity whatsoever.
#
# USE CASES:
#   - Running untrusted code in a sandbox
#   - Batch processing jobs that only need filesystem, not network
#   - Security-sensitive operations (key generation, hashing)

docker run --rm \
    --network none \
    --read-only \
    alpine \
    sh -c "echo hello | sha256sum"
# This container can compute but cannot make any network calls.
# Even if the code inside is malicious, it can't exfiltrate data.


# ============================================================
# PART 6: OVERLAY NETWORKS — Multi-host container networking
# ============================================================
# Bridge networks work on a SINGLE Docker host.
# For containers across MULTIPLE hosts (production clusters),
# you need overlay networking.
#
# Overlay creates a virtual network that spans hosts by encapsulating
# traffic in VXLAN (Virtual Extensible LAN) packets over UDP 4789.
#
# Container A on Host 1 → VXLAN tunnel → Container B on Host 2
# The containers see each other as if on the same L2 network.
#
# Docker Swarm mode creates overlay networks automatically.
# Kubernetes uses its own CNI plugins (Calico, Flannel, Cilium)
# which operate on similar principles.
#
# PRODUCTION: Most teams use Kubernetes, which abstracts this.
# But understanding overlay helps debug pod networking issues.

# Initialize Docker Swarm (needed for overlay networks):
docker swarm init --advertise-addr 10.0.0.1
# --advertise-addr: The IP other nodes should use to reach this manager.

# Create an overlay network:
docker network create \
    --driver overlay \
    --subnet 10.10.0.0/16 \
    --attachable \
    production-overlay
# --attachable: Allows standalone containers (not just Swarm services)
#   to connect to the overlay. Required for docker run --network.
#   Without it, only "docker service" can use the network.


# ============================================================
# PART 7: MACVLAN — Container as a first-class network citizen
# ============================================================
# Macvlan gives each container its own MAC address and IP address
# on your PHYSICAL network. The container appears as a distinct
# device to your router/switch — like a physical machine.
#
# USE CASES:
#   - Legacy apps that need to be on a specific network segment
#   - Apps that receive broadcast/multicast traffic
#   - Network equipment monitoring (sniffers, IDS)
#   - When containers need IPs visible to the corporate network
#
# REQUIREMENTS:
#   - The host NIC must be in PROMISCUOUS mode
#   - Your switch/router must allow multiple MACs per port
#   - You need a block of IP addresses from your network admin

docker network create \
    --driver macvlan \
    --subnet 192.168.1.0/24 \
    --gateway 192.168.1.1 \
    --ip-range 192.168.1.128/25 \
    --opt parent=eth0 \
    macvlan-production
# parent=eth0: The physical interface to attach to.
# ip-range: Containers get IPs from .128-.255 (upper half).
#   Lower half (.1-.127) used by real network devices.

docker run -d \
    --network macvlan-production \
    --ip 192.168.1.130 \
    --name legacy-app \
    legacy-image:2.0
# This container is now reachable at 192.168.1.130 from anywhere
# on the 192.168.1.0/24 network — no port mapping needed.


# ============================================================
# PART 8: PORT PUBLISHING — EXPOSE vs -p
# ============================================================
# EXPOSE in Dockerfile: Documentation only. Does NOT open a port.
#   It says "this container listens here" for human/tool reference.
#   It also works as a hint for --publish-all.
#
# -p (--publish): Actually binds a host port.

# -p HOST_PORT:CONTAINER_PORT
docker run -d -p 80:8000 myapp
# Host port 80 → Container port 8000.
# curl http://host-ip:80 → hits the app on port 8000 in container.

# -p IP:HOST_PORT:CONTAINER_PORT (bind to specific host interface)
docker run -d -p 127.0.0.1:8080:8000 myapp
# Only localhost can reach port 8080. Not exposed externally.
# Use for admin interfaces, metrics endpoints, debug ports.

# -p HOST_PORT:CONTAINER_PORT/udp
docker run -d -p 53:53/udp -p 53:53/tcp dns-server
# Specify protocol (tcp is default). DNS needs both UDP and TCP.

# --publish-all (-P): Publish ALL EXPOSED ports to random host ports
docker run -d -P myapp
# Each EXPOSE in Dockerfile gets a random host port.
# Find mappings: docker port <container>

# Check port mappings on a running container:
docker port my-web
# 80/tcp -> 0.0.0.0:32768
# 443/tcp -> 0.0.0.0:32769

# NAT MECHANICS:
# Docker sets up iptables rules for port publishing.
# Incoming packet on host:80 → iptables DNAT → container IP:8000.
# This is why --network host is faster: no DNAT overhead.


# ============================================================
# PART 9: CONNECTING CONTAINERS ACROSS NETWORKS
# ============================================================
# A container can be connected to MULTIPLE networks.
# Use this to create tiers with different trust levels.

# Example: 3-tier architecture
# Tier 1 (frontend): nginx — accessible from internet
# Tier 2 (backend): api — only accessible from frontend
# Tier 3 (data): postgres, redis — only accessible from backend

docker network create frontend-net
docker network create backend-net
docker network create data-net

# Nginx is on frontend-net (receives internet traffic)
# AND backend-net (can reach the API)
docker run -d --name nginx \
    --network frontend-net \
    -p 80:80 -p 443:443 \
    nginx:1.25

docker network connect backend-net nginx
# Connect nginx to backend-net AFTER starting it.
# Nginx now has interfaces on BOTH networks.

# API is only on backend-net (not internet-accessible)
docker run -d --name api \
    --network backend-net \
    my-api-image:1.0
# api has NO exposure to frontend-net or data-net.

# Connect api to data-net so it can reach DB
docker network connect data-net api

# Postgres is only on data-net (maximum isolation)
docker run -d --name postgres \
    --network data-net \
    -e POSTGRES_PASSWORD=secret \
    postgres:16
# postgres cannot be reached from frontend-net or the host at all.
# The only route to postgres is through api, which is on data-net.

# Result: even if nginx is compromised, the attacker cannot
# directly reach postgres. They'd need to also compromise the api.
# Defense in depth through network segmentation.

# Disconnect a container from a network:
docker network disconnect frontend-net api
# Now api cannot reach frontend-net at all.

# Remove a network (must disconnect all containers first):
docker network rm data-net


# ============================================================
# PART 10: DOCKER COMPOSE NETWORKING
# ============================================================
# Docker Compose automatically creates a network named:
#   <project_name>_default
#
# All services in the compose file join this network by default
# and can reach each other by SERVICE NAME (not container name).
#
# Service name resolution example:
#   Service "web" can reach service "api" at http://api:8000
#   Service "api" can reach service "db" at postgresql://db:5432
#
# In compose, define custom networks to control isolation:
#
# networks:
#   frontend:
#   backend:
#     internal: true    # ← no external connectivity (like --network none but still inter-container)
#
# services:
#   nginx:
#     networks: [frontend, backend]
#   api:
#     networks: [backend]
#   postgres:
#     networks: [backend]
#     # postgres has NO network called "frontend" — nginx can't reach it directly
#
# See L06 for the full Compose file with networking.


# ============================================================
# QUICK REFERENCE
# ============================================================
# docker network ls                          # List networks
# docker network create NAME                 # Create custom bridge
# docker network inspect NAME               # Show network details
# docker network connect NET CONTAINER      # Add container to network
# docker network disconnect NET CONTAINER   # Remove container from network
# docker network rm NAME                    # Delete network
# docker network prune                      # Remove unused networks
#
# docker run --network NETNAME              # Start on specific network
# docker run --network host                 # Use host network stack
# docker run --network none                 # No networking
# docker run -p HOST:CONTAINER              # Publish a port
# docker port CONTAINER                     # Show port mappings
# docker run --network-alias ALIAS          # DNS alias on network

echo "L04 complete: You understand Docker's full networking model."
