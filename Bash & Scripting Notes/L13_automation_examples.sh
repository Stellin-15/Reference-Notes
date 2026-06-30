#!/usr/bin/env bash
# ==============================================================
# L13: Real Automation Examples
# ==============================================================
# WHAT: Complete, realistic automation scripts for common tasks:
#       log rotation, backup, deployment, system health check,
#       service monitor with alerting, and cron job setup.
# WHY: Seeing all the pieces come together is more valuable than
#      isolated examples. These are the kinds of scripts you'll
#      actually write: things that run at 2am, handle errors
#      gracefully, and leave a clear log trail when they're done.
# TOPIC: Real-World Automation
# ==============================================================

set -euo pipefail
echo "=== L13: Real Automation Examples ==="

# ── EXAMPLE 1: LOG ROTATION ──────────────────────────────────
echo ""
echo "=== Example 1: Log Rotation ==="

rotate_logs() {
    local log_dir="${1:-/var/log/myapp}"
    local max_days="${2:-7}"     # keep 7 days of logs
    local max_size_mb="${3:-100}" # rotate if log > 100MB

    echo "[LOG-ROTATE] Rotating logs in $log_dir (keep ${max_days}d, max ${max_size_mb}MB)"

    # Create a sandbox for the demo
    local DEMO_DIR
    DEMO_DIR=$(mktemp -d /tmp/logrotate_demo_XXXXXX)
    trap "rm -rf '$DEMO_DIR'" RETURN   # clean up when function returns

    log_dir="$DEMO_DIR"

    # Create some fake logs
    for i in 1 2 3 4 5; do
        echo "2024-01-$i log content" > "$log_dir/app.log.$i"
        # Set modification time to simulate age (touch -d requires GNU coreutils)
        touch -d "$i days ago" "$log_dir/app.log.$i" 2>/dev/null || true
    done
    echo "Current log" > "$log_dir/app.log"

    echo "[LOG-ROTATE] Before rotation:"
    ls -la "$log_dir/" | sed 's/^/    /'

    # Compress logs older than 1 day
    find "$log_dir" -name "*.log.*" -type f | while IFS= read -r f; do
        if [[ ! "$f" =~ \.gz$ ]]; then
            gzip -f "$f"
            echo "[LOG-ROTATE] Compressed: $f"
        fi
    done

    # Delete logs older than max_days
    find "$log_dir" -name "*.log*" -type f \
        -mtime +"$max_days" -delete -print 2>/dev/null | \
        while IFS= read -r f; do
            echo "[LOG-ROTATE] Deleted: $f"
        done

    echo "[LOG-ROTATE] After rotation:"
    ls -la "$log_dir/" 2>/dev/null | sed 's/^/    /'
    echo "[LOG-ROTATE] Done"
}

rotate_logs

# ── EXAMPLE 2: BACKUP SCRIPT ─────────────────────────────────
echo ""
echo "=== Example 2: Backup Script ==="

backup_directory() {
    local src="${1:-/etc}"
    local backup_root="${2:-/tmp/backups}"
    local max_backups="${3:-5}"   # keep last 5 backups

    local timestamp
    timestamp="$(date '+%Y%m%d_%H%M%S')"
    local backup_name="backup_${timestamp}.tar.gz"
    local backup_path="$backup_root/$backup_name"

    mkdir -p "$backup_root"

    echo "[BACKUP] Source: $src"
    echo "[BACKUP] Destination: $backup_path"

    # Create the backup
    if tar -czf "$backup_path" --exclude='*.tmp' --exclude='.git' \
        "$src" 2>/dev/null; then
        local size
        size=$(du -sh "$backup_path" | cut -f1)
        echo "[BACKUP] Created: $backup_name ($size)"
    else
        echo "[BACKUP] ERROR: backup failed" >&2
        rm -f "$backup_path"
        return 1
    fi

    # Keep only the last N backups
    local backup_count
    backup_count=$(find "$backup_root" -name "backup_*.tar.gz" | wc -l)

    if (( backup_count > max_backups )); then
        echo "[BACKUP] Pruning old backups (keeping $max_backups of $backup_count)..."
        find "$backup_root" -name "backup_*.tar.gz" | \
            sort | head -$(( backup_count - max_backups )) | \
            while IFS= read -r old; do
                echo "[BACKUP] Removing: $(basename "$old")"
                rm -f "$old"
            done
    fi

    # Verify the backup is readable
    if tar -tzf "$backup_path" > /dev/null 2>&1; then
        echo "[BACKUP] Verified: backup is valid"
    else
        echo "[BACKUP] ERROR: backup file is corrupt" >&2
        return 1
    fi

    echo "[BACKUP] Done. Backups in $backup_root:"
    ls -lh "$backup_root"/*.tar.gz 2>/dev/null | sed 's/^/    /'
}

backup_directory "/etc/hostname" "/tmp/bash_backups" 3

# ── EXAMPLE 3: DEPLOYMENT SCRIPT ─────────────────────────────
echo ""
echo "=== Example 3: Deployment Skeleton ==="

# A realistic deployment script skeleton with rollback
deploy() {
    local app_name="${1:-myapp}"
    local version="${2:-latest}"
    local deploy_dir="/tmp/deploy_demo_$$"

    echo "[DEPLOY] Deploying $app_name version $version"

    # Simulate app directories
    mkdir -p "$deploy_dir"/{current,releases,shared}

    trap "rm -rf '$deploy_dir'" RETURN

    local release_dir="$deploy_dir/releases/$version"
    mkdir -p "$release_dir"

    echo "[DEPLOY] Step 1: download artifact"
    # In reality: curl -fsSL "https://releases/$app_name/$version.tar.gz" | tar -xz -C "$release_dir"
    echo "fake app code v$version" > "$release_dir/app.sh"
    chmod +x "$release_dir/app.sh"

    echo "[DEPLOY] Step 2: run migrations"
    # ./migrate.sh up

    echo "[DEPLOY] Step 3: update symlink (atomic swap)"
    local old_release
    old_release=$(readlink -f "$deploy_dir/current" 2>/dev/null || echo "none")

    ln -sfn "$release_dir" "$deploy_dir/current"
    echo "[DEPLOY] current → $release_dir"

    echo "[DEPLOY] Step 4: reload service"
    # systemctl reload myapp || { rollback "$old_release"; exit 1; }

    echo "[DEPLOY] Step 5: health check"
    # if ! wait_for_health "http://localhost:8080/health" 30; then
    #     rollback "$old_release"; exit 1
    # fi

    echo "[DEPLOY] Step 6: cleanup old releases (keep 3)"
    ls -dt "$deploy_dir"/releases/*/ 2>/dev/null | tail -n +4 | \
        while IFS= read -r old; do
            echo "[DEPLOY] Removing old release: $(basename "$old")"
            rm -rf "$old"
        done

    echo "[DEPLOY] Deployment complete: $app_name $version"
    ls -la "$deploy_dir/current" | sed 's/^/    /'
}

deploy "myapp" "v2.3.1"

# ── EXAMPLE 4: SYSTEM HEALTH CHECK ──────────────────────────
echo ""
echo "=== Example 4: System Health Check ==="

health_check_system() {
    local issues=0
    local report="/tmp/health_report_$$.txt"
    exec 3>"$report"   # open report file on fd 3

    check() {
        local name="$1"
        local status="$2"
        local detail="$3"
        if [[ "$status" == "OK" ]]; then
            echo "[OK]   $name: $detail" | tee /dev/fd/3
        else
            echo "[FAIL] $name: $detail" | tee /dev/fd/3 >&2
            ((issues++))
        fi
    }

    echo "=== Health Report $(date) ===" >&3

    # CPU usage
    cpu_idle=$(top -bn1 2>/dev/null | grep "Cpu" | awk '{print $8}' | tr -d '%' || echo "0")
    cpu_used=$(echo "100 - ${cpu_idle:-0}" | bc 2>/dev/null || echo "unknown")
    [[ "$cpu_used" =~ ^[0-9]+$ && "$cpu_used" -lt 90 ]] && \
        check "CPU" "OK" "${cpu_used}% used" || \
        check "CPU" "WARN" "usage=${cpu_used}%"

    # Memory
    if command -v free &>/dev/null; then
        mem_line=$(free | grep Mem)
        mem_total=$(echo "$mem_line" | awk '{print $2}')
        mem_used=$(echo "$mem_line"  | awk '{print $3}')
        mem_pct=$(( mem_used * 100 / mem_total ))
        (( mem_pct < 90 )) && \
            check "Memory" "OK" "${mem_pct}% used" || \
            check "Memory" "FAIL" "${mem_pct}% used — HIGH!"
    fi

    # Disk
    disk_pct=$(df / | awk 'NR==2 {print int($5)}')
    (( disk_pct < 85 )) && \
        check "Disk (/)" "OK" "${disk_pct}% used" || \
        check "Disk (/)" "FAIL" "${disk_pct}% used — HIGH!"

    # Load average
    load=$(cat /proc/loadavg 2>/dev/null | awk '{print $1}' || uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | tr -d ',')
    check "Load" "OK" "1min average: $load"

    # DNS resolution
    if nslookup google.com > /dev/null 2>&1 || host google.com > /dev/null 2>&1; then
        check "DNS" "OK" "resolving google.com"
    else
        check "DNS" "FAIL" "cannot resolve google.com"
    fi

    # Services (check a list)
    for svc in sshd cron; do
        if pgrep -x "$svc" > /dev/null 2>&1 || pgrep "$svc" > /dev/null 2>&1; then
            check "Service:$svc" "OK" "running"
        else
            check "Service:$svc" "WARN" "not detected (may be normal)"
        fi
    done

    exec 3>&-   # close report fd

    echo ""
    echo "[HEALTH] Report saved to: $report"
    echo "[HEALTH] Issues found: $issues"

    rm -f "$report"
    return $issues
}

health_check_system || echo "[HEALTH] Some checks failed (non-fatal for demo)"

# ── EXAMPLE 5: CRON JOB SETUP ────────────────────────────────
echo ""
echo "=== Example 5: Cron Job Patterns ==="

cat <<'CRON_EXAMPLES'
# Install a cron job idempotently (add if not already present):

CRON_JOB="0 2 * * * /opt/myapp/scripts/backup.sh >> /var/log/backup.log 2>&1"
MARKER="backup.sh"  # unique string to identify this job

install_cron_job() {
    local job="$1"
    local marker="$2"

    # Check if already installed
    if crontab -l 2>/dev/null | grep -qF "$marker"; then
        echo "Cron job already installed: $marker"
        return 0
    fi

    # Add the new job
    (crontab -l 2>/dev/null; echo "$job") | crontab -
    echo "Installed cron job: $job"
}

remove_cron_job() {
    local marker="$1"
    crontab -l 2>/dev/null | grep -vF "$marker" | crontab - 2>/dev/null || true
    echo "Removed cron job: $marker"
}

# Cron timing reference:
# ┌──────────── minute (0-59)
# │ ┌────────── hour (0-23)
# │ │ ┌──────── day of month (1-31)
# │ │ │ ┌────── month (1-12)
# │ │ │ │ ┌──── day of week (0-7, 0=Sun)
# │ │ │ │ │
# * * * * * command

# Examples:
# 0 2 * * *       every day at 2:00 AM
# */15 * * * *    every 15 minutes
# 0 */6 * * *     every 6 hours
# 0 9 * * 1-5     9 AM on weekdays
# 0 0 1 * *       first of every month at midnight
# @reboot         on system boot
# @daily          once a day (same as 0 0 * * *)
# @hourly         once an hour

CRON_EXAMPLES

echo ""
echo "=== All Examples Complete ==="
echo ""
echo "Key takeaways:"
echo "  1. Always use set -euo pipefail in production scripts"
echo "  2. Log everything to a file (not just stdout)"
echo "  3. Use traps for cleanup and lock release"
echo "  4. Make operations idempotent — safe to re-run"
echo "  5. Test with --dry-run before running live"
echo "  6. Use file locking to prevent duplicate runs"
echo "  7. Keep last N backups — not infinite"
echo "  8. Health checks before AND after deployment"
