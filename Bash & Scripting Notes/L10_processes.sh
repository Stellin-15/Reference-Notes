#!/usr/bin/env bash
# ==============================================================
# L10: Processes — ps, kill, jobs, bg, fg, &, wait, xargs
# ==============================================================
# WHAT: Managing processes: running commands in the background,
#       waiting for them, checking process status, sending signals,
#       and parallelising work with & + wait. Also covers xargs
#       for efficient parallel execution and process substitution.
# WHY: Long-running tasks (database dumps, file transfers, builds)
#      shouldn't block your script. Background jobs + wait lets
#      you parallelise work and collect results. kill + signals
#      let you manage runaway processes programmatically.
# TOPIC: Processes
# ==============================================================

set -euo pipefail
echo "=== L10: Processes ==="

# ── BACKGROUND JOBS ─────────────────────────────────────────
echo ""
echo "Background jobs:"

# & runs a command in the background
sleep 2 &
bg_pid=$!           # $! = PID of last background process
echo "  Launched sleep 2 in background, PID=$bg_pid"

# jobs: list background jobs (interactive shells only)
# jobs

# wait: wait for a background process to finish
wait $bg_pid
echo "  sleep 2 finished (exit code: $?)"

# ── PARALLEL WORK WITH WAIT ──────────────────────────────────
echo ""
echo "Parallel execution:"

# Run multiple tasks in parallel, collect results
TMPDIR_PARALLEL=$(mktemp -d /tmp/parallel_XXXXXX)
trap 'rm -rf "$TMPDIR_PARALLEL"' EXIT

run_task() {
    local id=$1
    local duration=$2
    local outfile="$TMPDIR_PARALLEL/task_$id.out"
    sleep "$duration"
    echo "task $id completed after ${duration}s" > "$outfile"
}

# Launch 4 tasks in parallel
start_time=$(date +%s)
pids=()
for i in 1 2 3 4; do
    run_task "$i" "0.1" &   # each task takes 0.1s
    pids+=($!)              # collect PIDs
done

# Wait for all and check results
all_ok=true
for pid in "${pids[@]}"; do
    wait "$pid" || all_ok=false
done

end_time=$(date +%s)
elapsed=$(( end_time - start_time ))
echo "  All 4 tasks done in ~${elapsed}s (would be 0.4s sequential, ~0.1s parallel)"

$all_ok && echo "  All tasks succeeded" || echo "  Some tasks failed"

# Print results
for f in "$TMPDIR_PARALLEL"/*.out; do
    echo "  $(cat "$f")"
done

# ── PARALLEL WITH RESULT COLLECTION ─────────────────────────
echo ""
echo "Parallel with exit-code tracking:"

run_with_status() {
    local id=$1
    # Simulate: odd IDs succeed, even IDs fail
    if (( id % 2 == 0 )); then
        return 0
    else
        sleep 0.05
        return 0  # all succeed in demo (change to 1 to see failure handling)
    fi
}

declare -A job_pids  # associative: pid → job_id
declare -A job_results

for id in {1..5}; do
    run_with_status "$id" &
    job_pids[$!]=$id   # map PID to job ID
done

for pid in "${!job_pids[@]}"; do
    job_id="${job_pids[$pid]}"
    if wait "$pid"; then
        job_results[$job_id]="OK"
    else
        job_results[$job_id]="FAIL"
    fi
done

for id in $(echo "${!job_results[@]}" | tr ' ' '\n' | sort -n); do
    echo "  job $id: ${job_results[$id]}"
done

# ── PS: CHECKING RUNNING PROCESSES ──────────────────────────
echo ""
echo "ps:"

echo "  Current shell process:"
ps -p $$ -o pid,ppid,cmd | sed 's/^/    /'

echo "  bash processes:"
ps aux 2>/dev/null | grep "[b]ash" | head -3 | awk '{print "    pid="$2, "cmd="$11}' || \
    ps -ef 2>/dev/null | grep "[b]ash" | head -3 | awk '{print "    pid="$2, "cmd="$8}'

echo "  Top 5 processes by CPU:"
ps aux --sort=-%cpu 2>/dev/null | head -6 | awk '{printf "    %-20s %5s%%\n", $11, $3}' || \
    ps -eo pid,pcpu,comm --sort=-pcpu 2>/dev/null | head -5 | sed 's/^/    /'

# ── KILL AND SIGNALS ─────────────────────────────────────────
echo ""
echo "Signals:"

# Start a background process to demonstrate kill
sleep 100 &
demo_pid=$!
echo "  Started sleep 100, PID=$demo_pid"

# Check if a process is running
if kill -0 "$demo_pid" 2>/dev/null; then
    echo "  Process $demo_pid is running"
fi

# Send TERM signal (graceful shutdown)
kill -TERM "$demo_pid" 2>/dev/null || true
sleep 0.1

# Verify it's gone
if ! kill -0 "$demo_pid" 2>/dev/null; then
    echo "  Process $demo_pid terminated"
fi

# Common signals:
# SIGTERM (15): graceful termination (default for kill)
# SIGKILL (9):  force kill — cannot be caught or ignored
# SIGHUP  (1):  hangup — often used to reload config
# SIGINT  (2):  interrupt (Ctrl+C)
# SIGUSR1 (10): user-defined signal 1
# SIGUSR2 (12): user-defined signal 2

# Kill all processes with a given name:
# pkill -f "my_script.sh"   # -f: match full command line
# killall my_program

# ── XARGS ────────────────────────────────────────────────────
echo ""
echo "xargs:"

# xargs: build and execute commands from stdin
# Much faster than 'for ... in $(...)' for many files

# Basic: one item per run
echo "  echo via xargs:"
echo -e "alpha\nbeta\ngamma" | xargs -I{} echo "  item: {}"

# Parallel: -P N runs N processes simultaneously
echo "  Parallel xargs (-P4):"
seq 1 5 | xargs -P4 -I{} bash -c 'echo "  processing item {}"'

# With find (classic pattern):
echo "  Find + xargs to get sizes:"
find /tmp -maxdepth 1 -type f 2>/dev/null | head -5 | \
    xargs -I{} wc -c {} 2>/dev/null | sort -n | head -3 | sed 's/^/    /'

# NULL-separated (handles filenames with spaces)
find /tmp -maxdepth 1 -type f -print0 2>/dev/null | \
    xargs -0 ls -la 2>/dev/null | head -3 | sed 's/^/    /' || true

# ── COMMAND SUBSTITUTION ─────────────────────────────────────
echo ""
echo "Command substitution:"

# $(cmd): run cmd, capture stdout as a string
current_user=$(whoami)
current_date=$(date '+%Y-%m-%d')
num_cpus=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)

echo "  User: $current_user"
echo "  Date: $current_date"
echo "  CPUs: $num_cpus"

# Nesting command substitutions
longest_path=$(find /usr -maxdepth 2 -type f 2>/dev/null | \
    awk '{print length, $0}' | sort -rn | head -1 | cut -d' ' -f2-)
echo "  Longest /usr path: $longest_path"

# ── TIMEOUT ──────────────────────────────────────────────────
echo ""
echo "timeout:"

# timeout: kill a command if it takes too long
if timeout 1 sleep 0.1; then
    echo "  Command finished within 1 second"
else
    echo "  Command timed out or failed"
fi

if timeout 0.05 sleep 1 2>/dev/null; then
    echo "  Should not print"
else
    echo "  Correctly timed out (exit code: $?)"
fi

# ── NOHUP ─────────────────────────────────────────────────────
echo ""
echo "nohup (keep running after logout):"
echo "  nohup ./long_running_script.sh > output.log 2>&1 &"
echo "  nohup: immune to SIGHUP — process keeps running after terminal closes"
echo "  Useful for: deployment scripts, long imports, ML training runs"

# ── PROCESS SUBSTITUTION ─────────────────────────────────────
echo ""
echo "Process substitution:"

# diff two command outputs without temp files
diff <(ls /bin 2>/dev/null | sort | head -5) \
     <(ls /usr/bin 2>/dev/null | sort | head -5) | head -10 | sed 's/^/  /'

# ── MONITORING PATTERN ───────────────────────────────────────
echo ""
echo "Wait-for-condition pattern:"

# Common pattern: wait until a service is ready (with timeout)
wait_for_port() {
    local host="$1"
    local port="$2"
    local max_wait="${3:-30}"
    local elapsed=0

    while (( elapsed < max_wait )); do
        if bash -c "echo >/dev/tcp/$host/$port" 2>/dev/null; then
            echo "  $host:$port is ready"
            return 0
        fi
        sleep 1
        ((elapsed++))
    done
    echo "  Timed out waiting for $host:$port" >&2
    return 1
}

# Demo (try localhost:22 — SSH, usually available)
wait_for_port localhost 22 2 || true

echo ""
echo "Done."
