#!/usr/bin/env bash
# ==============================================================
# L12: Scripting Patterns — Logging, Config, Locking, Idempotency
# ==============================================================
# WHAT: Production-grade scripting patterns: structured logging
#       with levels, loading config from .env files, file-based
#       locking to prevent duplicate runs, idempotent operations,
#       script self-documentation (usage/help), and the canonical
#       main() pattern.
# WHY: Scripts that run in production need: logs you can grep,
#      config you can change without editing code, protection
#      against running twice simultaneously, and behaviour that's
#      safe to re-run. These patterns separate "works on my laptop"
#      from "runs in production at 3am unattended".
# TOPIC: Production Patterns
# ==============================================================

set -euo pipefail
IFS=$'\n\t'   # safer IFS: split on newlines and tabs, not spaces

# ── SCRIPT IDENTITY ─────────────────────────────────────────
readonly SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_VERSION="1.0.0"
readonly PID=$$

# ── STRUCTURED LOGGING ──────────────────────────────────────
# Colors (only when connected to a terminal)
if [[ -t 1 ]]; then
    RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; YELLOW=''; GREEN=''; BLUE=''; BOLD=''; RESET=''
fi

LOG_LEVEL="${LOG_LEVEL:-INFO}"   # can be overridden by environment

declare -A LOG_LEVELS=([DEBUG]=0 [INFO]=1 [WARN]=2 [ERROR]=3 [FATAL]=4)

log() {
    local level="$1"; shift
    local message="$*"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"

    # Filter by level
    local current_level="${LOG_LEVELS[$LOG_LEVEL]:-1}"
    local msg_level="${LOG_LEVELS[$level]:-1}"
    (( msg_level < current_level )) && return 0

    local color=""
    case "$level" in
        DEBUG) color="$BLUE"   ;;
        INFO)  color="$GREEN"  ;;
        WARN)  color="$YELLOW" ;;
        ERROR|FATAL) color="$RED" ;;
    esac

    # Print to stderr for WARN/ERROR/FATAL, stdout for DEBUG/INFO
    local out=1
    [[ "$level" == "WARN" || "$level" == "ERROR" || "$level" == "FATAL" ]] && out=2

    printf "${color}[%s] [%-5s] [%s] %s${RESET}\n" \
        "$timestamp" "$level" "$SCRIPT_NAME" "$message" >&$out
}

log_debug() { log "DEBUG" "$@"; }
log_info()  { log "INFO"  "$@"; }
log_warn()  { log "WARN"  "$@"; }
log_error() { log "ERROR" "$@"; }
log_fatal() { log "FATAL" "$@"; exit 1; }

# ── USAGE / HELP ─────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $SCRIPT_NAME [OPTIONS] [ARGS]

Description:
  A template demonstrating production scripting patterns.

Options:
  -h, --help          Show this help message
  -v, --verbose       Enable debug logging
  -c, --config FILE   Load configuration from FILE (default: .env)
  -n, --dry-run       Show what would be done without doing it
  --version           Show version and exit

Examples:
  $SCRIPT_NAME -v -c /etc/myapp/config.env
  $SCRIPT_NAME --dry-run
  LOG_LEVEL=DEBUG $SCRIPT_NAME

Environment Variables:
  LOG_LEVEL   Log verbosity: DEBUG, INFO, WARN, ERROR (default: INFO)
  DRY_RUN     Set to 'true' to enable dry-run mode
EOF
}

# ── CONFIG LOADING (.env file) ───────────────────────────────
# Load key=value pairs from a .env file (ignores comments and blank lines)
load_dotenv() {
    local env_file="${1:-.env}"

    [[ ! -f "$env_file" ]] && {
        log_warn "Config file not found: $env_file (using defaults)"
        return 0
    }

    log_debug "Loading config from: $env_file"
    while IFS= read -r line; do
        # Skip comments and blank lines
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]]           && continue

        # Split on first '=' only
        local key="${line%%=*}"
        local val="${line#*=}"

        # Strip optional surrounding quotes from value
        val="${val%\"}"
        val="${val#\"}"
        val="${val%\'}"
        val="${val#\'}"

        # Export the variable (so subprocesses see it too)
        export "$key=$val"
        log_debug "Config: $key=$val"
    done < "$env_file"
}

# ── FILE LOCKING (prevent duplicate runs) ────────────────────
LOCK_FILE="/tmp/${SCRIPT_NAME%.sh}.lock"

acquire_lock() {
    # Use a file descriptor + flock for atomic locking
    exec 200>"$LOCK_FILE"   # open LOCK_FILE on fd 200

    # flock -n: non-blocking (fail immediately if lock is held)
    if ! flock -n 200; then
        local held_by
        held_by=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
        log_fatal "Another instance is running (PID: $held_by). Exiting."
    fi

    echo $$ > "$LOCK_FILE"   # write our PID to the lock file
    log_debug "Lock acquired (PID=$$)"
}

release_lock() {
    flock -u 200 2>/dev/null || true   # release the lock
    rm -f "$LOCK_FILE"
    log_debug "Lock released"
}

# ── IDEMPOTENT OPERATIONS ────────────────────────────────────
# An idempotent operation produces the same result regardless of
# how many times it's run. Safe to retry or re-run.

ensure_dir() {
    local dir="$1"
    [[ -d "$dir" ]] && return 0          # already exists — idempotent
    log_info "Creating directory: $dir"
    mkdir -p "$dir"
}

ensure_file() {
    local file="$1"
    local content="${2:-}"
    [[ -f "$file" ]] && return 0         # already exists — idempotent
    log_info "Creating file: $file"
    echo "$content" > "$file"
}

ensure_line_in_file() {
    # Add a line to a file only if it's not already there
    local file="$1"
    local line="$2"
    grep -qxF "$line" "$file" 2>/dev/null && return 0   # already present
    log_info "Adding to $file: $line"
    echo "$line" >> "$file"
}

ensure_symlink() {
    local target="$1"
    local link="$2"
    [[ -L "$link" && "$(readlink "$link")" == "$target" ]] && return 0
    log_info "Creating symlink: $link → $target"
    ln -sf "$target" "$link"
}

# ── RETRY LOGIC ──────────────────────────────────────────────
retry() {
    local max="${1:-3}"
    local delay="${2:-5}"
    shift 2
    local cmd=("$@")

    for ((attempt=1; attempt<=max; attempt++)); do
        log_debug "Attempt $attempt/$max: ${cmd[*]}"
        if "${cmd[@]}"; then
            return 0
        fi
        if (( attempt < max )); then
            log_warn "Attempt $attempt failed. Retrying in ${delay}s..."
            sleep "$delay"
            (( delay = delay * 2 ))   # exponential backoff
        fi
    done
    log_error "All $max attempts failed: ${cmd[*]}"
    return 1
}

# ── DRY RUN SUPPORT ──────────────────────────────────────────
DRY_RUN="${DRY_RUN:-false}"

# Wrapper: skip execution if DRY_RUN=true, just log what would happen
run() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] would run: $*"
    else
        "$@"
    fi
}

# ── CLEANUP FRAMEWORK ────────────────────────────────────────
CLEANUP_TASKS=()   # array of commands to run on exit

register_cleanup() {
    CLEANUP_TASKS+=("$*")
}

run_cleanup() {
    local exit_code=$?
    log_debug "Running cleanup (${#CLEANUP_TASKS[@]} tasks)"

    # Run in reverse order (LIFO — like destructors)
    for (( i=${#CLEANUP_TASKS[@]}-1; i>=0; i-- )); do
        eval "${CLEANUP_TASKS[$i]}" 2>/dev/null || true
    done

    (( exit_code != 0 )) && log_error "Script failed with exit code $exit_code"
    return $exit_code
}

trap run_cleanup EXIT
trap 'log_error "Interrupted"; exit 130' INT TERM

# ── ARGUMENT PARSING ─────────────────────────────────────────
CONFIG_FILE=".env"
VERBOSE=false

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)    usage; exit 0 ;;
            --version)    echo "$SCRIPT_NAME version $SCRIPT_VERSION"; exit 0 ;;
            -v|--verbose) VERBOSE=true; LOG_LEVEL="DEBUG" ;;
            -n|--dry-run) DRY_RUN="true" ;;
            -c|--config)
                [[ -z "${2:-}" ]] && log_fatal "--config requires a file argument"
                CONFIG_FILE="$2"
                shift
                ;;
            --)           shift; break ;;
            -*)           log_fatal "Unknown option: $1 (use --help for usage)" ;;
            *)            break ;;   # end of flags, remaining are positional
        esac
        shift
    done
    POSITIONAL_ARGS=("$@")
}

# ── MAIN ─────────────────────────────────────────────────────
main() {
    parse_args "$@"

    log_info "Starting $SCRIPT_NAME v$SCRIPT_VERSION (PID=$$)"
    log_debug "Working directory: $(pwd)"
    log_debug "Args: ${POSITIONAL_ARGS[*]:-<none>}"

    # Load config
    load_dotenv "$CONFIG_FILE"

    # Acquire lock (prevent duplicate runs)
    acquire_lock
    register_cleanup "release_lock"

    # Demo: create temp files that are auto-cleaned
    local WORK_DIR
    WORK_DIR="$(mktemp -d /tmp/${SCRIPT_NAME%.sh}_XXXXXX)"
    register_cleanup "rm -rf '$WORK_DIR'"
    log_debug "Work dir: $WORK_DIR"

    # Demo idempotent operations
    ensure_dir "$WORK_DIR/output"
    ensure_dir "$WORK_DIR/output"    # safe to call twice
    ensure_file "$WORK_DIR/output/marker" "created by $SCRIPT_NAME"
    ensure_file "$WORK_DIR/output/marker" "this won't overwrite"   # idempotent

    # Demo dry-run
    run echo "This command respects DRY_RUN mode"
    run mkdir -p "$WORK_DIR/dry_run_dir"

    # Demo retry
    local call_count=0
    flaky() {
        (( ++call_count < 2 )) && return 1 || return 0
    }
    retry 3 0 flaky && log_info "Retry demo: succeeded on attempt $call_count"

    # Demo logging levels
    log_debug "This is debug (only visible with LOG_LEVEL=DEBUG)"
    log_info  "This is info"
    log_warn  "This is a warning"
    log_error "This is an error (but we continue)"

    log_info "Script completed successfully"
}

# Entry point — only run main if this script is executed directly
# (not sourced by another script)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
