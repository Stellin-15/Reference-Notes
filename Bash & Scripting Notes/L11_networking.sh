#!/usr/bin/env bash
# ==============================================================
# L11: Networking — curl, wget, ssh, scp, nc, ping, DNS
# ==============================================================
# WHAT: Common networking tasks from bash: downloading files,
#       making HTTP requests, SSH automation, checking connectivity,
#       DNS lookups, and port scanning with nc/nmap.
# WHY: Deployment scripts download binaries. Health checks ping
#      endpoints. CI pipelines SSH into servers. API integrations
#      call curl. All of these live in bash scripts in production.
# TOPIC: Networking
# ==============================================================

set -euo pipefail
echo "=== L11: Networking ==="

# ── PING AND CONNECTIVITY ────────────────────────────────────
echo ""
echo "ping and connectivity:"

# Check if a host is reachable
ping_check() {
    local host="$1"
    if ping -c 1 -W 1 "$host" > /dev/null 2>&1; then
        echo "  $host is reachable"
        return 0
    else
        echo "  $host is NOT reachable"
        return 1
    fi
}

ping_check "1.1.1.1" || true    # Cloudflare DNS
ping_check "8.8.8.8" || true    # Google DNS

# ── DNS LOOKUPS ──────────────────────────────────────────────
echo ""
echo "DNS lookups:"

# dig: detailed DNS query (install: apt install dnsutils)
# host: simpler DNS query
# nslookup: interactive or one-shot DNS

if command -v dig &>/dev/null; then
    echo "  dig A record for google.com:"
    dig +short A google.com 2>/dev/null | head -3 | sed 's/^/    /'

    echo "  dig MX records:"
    dig +short MX gmail.com 2>/dev/null | head -3 | sed 's/^/    /'

    echo "  Reverse lookup (PTR):"
    dig +short -x 8.8.8.8 2>/dev/null | sed 's/^/    /'
elif command -v host &>/dev/null; then
    host -t A google.com 2>/dev/null | head -3 | sed 's/^/    /'
else
    echo "  (dig/host not available)"
fi

# ── PORT CHECKING ────────────────────────────────────────────
echo ""
echo "Port checking:"

# Check if a port is open using /dev/tcp (bash built-in)
check_port() {
    local host="$1"
    local port="$2"
    local timeout="${3:-3}"
    if timeout "$timeout" bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
        echo "  $host:$port is OPEN"
        return 0
    else
        echo "  $host:$port is CLOSED/unreachable"
        return 1
    fi
}

check_port "google.com" 443 || true    # HTTPS
check_port "localhost"  22  || true    # SSH (may or may not be running)
check_port "localhost"  9999 || true   # closed port

# nc (netcat): more powerful port checking
if command -v nc &>/dev/null; then
    echo "  nc port check:"
    nc -z -w2 google.com 443 2>/dev/null && echo "  google.com:443 open" || echo "  google.com:443 closed"
fi

# ── CURL ─────────────────────────────────────────────────────
echo ""
echo "curl:"

# -s: silent (no progress), -S: show errors, -L: follow redirects
# -f: fail silently on HTTP errors (returns exit code 22)
# --max-time N: timeout in seconds

# GET request
echo "  GET request to httpbin.org:"
curl -fsSL --max-time 5 "https://httpbin.org/get" 2>/dev/null | \
    python3 -m json.tool 2>/dev/null | grep '"url"' | sed 's/^/    /' || \
    echo "    (httpbin.org unreachable or python3 unavailable)"

# GET with headers
curl -fsSL --max-time 5 -H "Accept: application/json" \
    "https://api.github.com/repos/torvalds/linux/releases/latest" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print('  Latest kernel:', d.get('tag_name','unknown'))" \
    2>/dev/null || echo "  (GitHub API request failed or python3 unavailable)"

# POST request with JSON body
echo "  POST request:"
curl -fsSL --max-time 5 -X POST \
    -H "Content-Type: application/json" \
    -d '{"key": "value", "number": 42}' \
    "https://httpbin.org/post" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print('  Sent:', d.get('json','(unavailable'))" \
    2>/dev/null || echo "  (POST failed)"

# Download a file
echo "  Download a file:"
curl -fsSL --max-time 10 -o /tmp/robots.txt "https://www.google.com/robots.txt" 2>/dev/null && \
    echo "  Downloaded /tmp/robots.txt ($(wc -l < /tmp/robots.txt) lines)" || \
    echo "  Download failed"

# Check HTTP status code
http_status() {
    local url="$1"
    curl -o /dev/null -s -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000"
}
status=$(http_status "https://google.com")
echo "  google.com HTTP status: $status"

# Retry with backoff
curl_with_retry() {
    local url="$1"
    local max_retries="${2:-3}"
    local delay=1

    for ((i=1; i<=max_retries; i++)); do
        if curl -fsSL --max-time 10 "$url" -o /dev/null 2>/dev/null; then
            return 0
        fi
        echo "  Attempt $i failed. Retrying in ${delay}s..."
        sleep "$delay"
        (( delay *= 2 ))   # exponential backoff
    done
    echo "  All $max_retries attempts failed" >&2
    return 1
}

# ── WGET ─────────────────────────────────────────────────────
echo ""
echo "wget:"

if command -v wget &>/dev/null; then
    echo "  wget example:"
    wget -q --timeout=5 -O /tmp/google_home.html "https://google.com" 2>/dev/null && \
        echo "  Downloaded google.com ($(wc -c < /tmp/google_home.html) bytes)" || \
        echo "  wget failed"

    # Mirror a directory (recursive download)
    # wget --mirror --no-parent https://example.com/docs/
fi

# ── SSH ──────────────────────────────────────────────────────
echo ""
echo "SSH patterns:"

# Non-interactive SSH (for scripts — requires key-based auth)
# ssh -o StrictHostKeyChecking=no user@host "command"

# Common SSH options for scripts:
# -i ~/.ssh/id_rsa       : specify key file
# -o BatchMode=yes       : fail if password prompt appears
# -o ConnectTimeout=10   : connection timeout
# -o StrictHostKeyChecking=no : skip host key verification (risky)

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no)

echo "  Typical SSH usage in scripts:"
cat <<'CODE'
  # Check if remote host is accessible
  if ssh "${SSH_OPTS[@]}" user@remote-host "echo ok" 2>/dev/null; then
      echo "SSH connection successful"
  fi

  # Run a command and capture output
  remote_df=$(ssh "${SSH_OPTS[@]}" user@host "df -h /")

  # Run a heredoc of commands
  ssh user@host <<'REMOTE'
  set -euo pipefail
  cd /opt/myapp
  git pull
  systemctl restart myapp
  REMOTE

  # Forward a port (SSH tunnel)
  ssh -L 5432:localhost:5432 user@db-server -N &
  tunnel_pid=$!
  # ... use localhost:5432 ...
  kill $tunnel_pid
CODE

# ── SCP ──────────────────────────────────────────────────────
echo ""
echo "SCP patterns:"

cat <<'CODE'
  # Copy file TO remote
  scp -i ~/.ssh/id_rsa local_file.tar.gz user@remote:/opt/deploy/

  # Copy file FROM remote
  scp user@remote:/var/log/app.log /tmp/app.log

  # Copy directory recursively
  scp -r ./dist/ user@remote:/var/www/html/

  # Prefer rsync for large/incremental transfers:
  rsync -avz --progress ./dist/ user@remote:/var/www/html/
CODE

# ── RSYNC ─────────────────────────────────────────────────────
echo ""
echo "rsync patterns:"

cat <<'CODE'
  # Sync local dir to remote (incremental, much faster than scp for large dirs)
  rsync -avz --delete ./myapp/ user@remote:/opt/myapp/
  #   -a: archive (preserve perms, timestamps, symlinks, etc.)
  #   -v: verbose
  #   -z: compress during transfer
  #   --delete: remove remote files not in source

  # Dry run (see what would change):
  rsync -avzn ./myapp/ user@remote:/opt/myapp/

  # Exclude files:
  rsync -avz --exclude='*.log' --exclude='.git/' ./myapp/ user@remote:/opt/myapp/
CODE

# ── IP AND NETWORK INFO ──────────────────────────────────────
echo ""
echo "IP and network info:"

# Get local IP address(es)
echo "  Local IPs:"
ip addr show 2>/dev/null | grep "inet " | awk '{print "    " $2}' || \
    ifconfig 2>/dev/null | grep "inet " | awk '{print "    " $2}' || \
    echo "    (ip/ifconfig not available)"

# Get public IP
echo "  Public IP:"
curl -fsSL --max-time 5 "https://api.ipify.org" 2>/dev/null | sed 's/^/    /' && echo || \
    echo "    (ipify.org unreachable)"

# Network interfaces
echo "  Network interfaces:"
ip link show 2>/dev/null | grep "^[0-9]" | awk '{print "    " $2}' | tr -d ':' || \
    ifconfig 2>/dev/null | grep "^[a-z]" | awk '{print "    " $1}' || true

# ── PRACTICAL: HEALTH CHECK SCRIPT ───────────────────────────
echo ""
echo "Health check example:"

health_check() {
    local name="$1"
    local url="$2"
    local expected_code="${3:-200}"

    local actual_code
    actual_code=$(curl -o /dev/null -s -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")

    if [[ "$actual_code" == "$expected_code" ]]; then
        echo "  OK    [$actual_code] $name ($url)"
    else
        echo "  FAIL  [$actual_code] $name ($url)" >&2
        return 1
    fi
}

health_check "Google"     "https://google.com"     "200" || true
health_check "GitHub"     "https://github.com"     "200" || true
health_check "Bad URL"    "https://httpbin.org/status/503" "200" || true

echo ""
echo "Done."
