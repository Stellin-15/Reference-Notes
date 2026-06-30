#!/usr/bin/env bash
# ==============================================================
# L07: Error Handling — set -e, set -u, trap, exit codes
# ==============================================================
# WHAT: Making scripts safe and robust. The set -euo pipefail
#       flags, trap for cleanup on exit/error/signal, checking
#       exit codes, the ERR trap, and building a reliable
#       error handling framework for production scripts.
# WHY: Without error handling, a script that fails halfway leaves
#      systems in a broken state — partial file writes, half-run
#      migrations, left-open connections. A single set -euo pipefail
#      at the top catches most bugs automatically.
# TOPIC: Foundations
# ==============================================================

# ── SAFE MODE FLAGS ─────────────────────────────────────────
# Put these at the top of EVERY production script.

set -e           # exit immediately if any command fails (non-zero exit)
set -u           # treat unset variables as errors (not silently empty)
set -o pipefail  # a pipe fails if ANY command in it fails (not just the last)
# Shorthand: set -euo pipefail

# Or combined: set -euo pipefail

echo "=== L07: Error Handling ==="

# ── set -e DEMO ─────────────────────────────────────────────
echo ""
echo "set -e: exits on first failure"
# Without set -e, this would continue silently:
# ls /nonexistent   # fails
# echo "This would print even though ls failed"

# With set -e: ls /nonexistent would kill the script.
# To run a command and ALLOW it to fail, use || true
ls /nonexistent 2>/dev/null || true   # failure is expected — continue
echo "Script continues (failure was expected)"

# Or use 'if' — commands in if conditions don't trigger set -e
if ls /nonexistent 2>/dev/null; then
    echo "found it"
else
    echo "not found — handled gracefully"
fi

# ── set -u DEMO ─────────────────────────────────────────────
echo ""
echo "set -u: unset variables are errors"
# echo $undefined_var   # would abort: "unset variable"

# Use a default to handle possibly-unset vars:
echo "Value: ${MAYBE_UNSET:-default_value}"

# Or check explicitly:
if [[ -v MY_VAR ]]; then   # -v: true if variable is set (even if empty)
    echo "MY_VAR is set: $MY_VAR"
else
    echo "MY_VAR is not set"
fi

# ── pipefail DEMO ───────────────────────────────────────────
echo ""
echo "pipefail: pipe fails if any stage fails"
# Without pipefail: ls /nonexistent | sort → exit code 0 (sort succeeded)
# With pipefail:    ls /nonexistent | sort → exit code 2 (ls failed)

# The overall exit status of a pipe is the exit of the last failed command:
if ls /nonexistent 2>/dev/null | sort > /dev/null 2>&1; then
    echo "pipeline succeeded"
else
    echo "pipeline failed (as expected with pipefail)"
fi

# ── TRAP ────────────────────────────────────────────────────
echo ""
echo "trap: cleanup on exit or signal"

# Create a temp file
TEMP_FILE=$(mktemp /tmp/script_XXXXXX)
echo "Created temp file: $TEMP_FILE"

# Register cleanup — runs on EXIT (normal or error) and on signals
cleanup() {
    local exit_code=$?
    echo ""
    echo "[CLEANUP] Removing temp file: $TEMP_FILE"
    rm -f "$TEMP_FILE"
    echo "[CLEANUP] Exiting with code: $exit_code"
}

trap cleanup EXIT         # runs when the script exits (any reason)
# trap cleanup EXIT INT TERM HUP  # also catch Ctrl+C, kill, hangup

# Now write something to the temp file
echo "temporary data" > "$TEMP_FILE"
echo "Wrote to temp file. File will be auto-deleted on exit."

# ── ERR TRAP ────────────────────────────────────────────────
echo ""
echo "ERR trap: called on any error"

# LINENO, BASH_COMMAND, and the exit code give you debugging info
on_error() {
    local exit_code=$?
    local line_number=$1
    echo "[ERROR] Command failed at line $line_number with exit code $exit_code" >&2
    echo "[ERROR] Failed command: $BASH_COMMAND" >&2
}

# Set the ERR trap — $LINENO is passed as an argument
trap 'on_error $LINENO' ERR

# This will trigger the ERR trap:
false || true   # false fails, but || true makes the overall result OK (no ERR trap)
false   # this WILL trigger ERR trap... but wait, set -e would exit first!
# So ERR trap + set -e: the ERR trap fires, then the script exits.

# To allow a failure without triggering set -e AND call the ERR trap handler:
# Temporarily disable set -e with: set +e
set +e
( exit 5 )  # subshell exits with 5
echo "After subshell: exit code=$?"
set -e    # re-enable

# ── EXPLICIT EXIT CODE CHECKING ─────────────────────────────
echo ""
echo "Explicit exit code checks:"

run_check() {
    local cmd=("$@")
    "${cmd[@]}"
    local code=$?
    if [[ $code -ne 0 ]]; then
        echo "[FAIL] '${cmd[*]}' exited with code $code" >&2
        return $code
    fi
    return 0
}

run_check ls /tmp > /dev/null     # succeeds
run_check ls /nonexistent 2>/dev/null || echo "handled the failure"

# ── die() HELPER ────────────────────────────────────────────
echo ""
echo "die() — print error and exit:"

die() {
    # Print error message to stderr, then exit with given code (default 1)
    echo "[FATAL] $*" >&2
    exit "${LAST_EXIT_CODE:-1}"
}

check_command() {
    command -v "$1" > /dev/null 2>&1 || die "Required command not found: $1"
    echo "  $1 is available"
}

check_command bash
check_command ls
# check_command definitely_missing_cmd   # would call die() and exit

# ── REQUIRE_ROOT ────────────────────────────────────────────
echo ""
echo "require_root check:"

require_root() {
    [[ $EUID -eq 0 ]] || die "This script must be run as root (current UID: $EUID)"
}

if [[ $EUID -ne 0 ]]; then
    echo "Not root (UID=$EUID) — skipping require_root demo"
else
    require_root
    echo "Running as root"
fi

# ── SIGNAL HANDLING ─────────────────────────────────────────
echo ""
echo "Signal handling:"

# INT: Ctrl+C   HUP: terminal closed   TERM: kill (graceful)
# KILL: kill -9 (cannot be trapped)    USR1/USR2: custom signals

interrupted=false
handle_interrupt() {
    interrupted=true
    echo ""
    echo "[SIGNAL] Interrupted — will exit gracefully..."
}

trap handle_interrupt INT TERM

echo "Running a long operation (press Ctrl+C to test interrupt)..."
for i in {1..3}; do
    sleep 0.1
    $interrupted && { echo "Exiting due to interrupt."; exit 130; }
    echo "  step $i"
done

# Restore default INT handling
trap - INT TERM

# ── SUBSHELL ERROR ISOLATION ────────────────────────────────
echo ""
echo "Subshell for error isolation:"

# A subshell ( ... ) inherits but isolates: changes to vars/traps don't leak
result=0
(
    set -e
    echo "In subshell"
    false   # would exit the subshell, not the outer script
    echo "Not reached"
) || result=$?

echo "Subshell exited with: $result"
echo "Outer script continues"

# ── PRODUCTION TEMPLATE ─────────────────────────────────────
cat <<'TEMPLATE'

# ── PRODUCTION SCRIPT TEMPLATE ──────────────────────────────
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'    # safer IFS — prevents word splitting on spaces

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_NAME="$(basename "$0")"

log()   { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
error() { log "ERROR: $*" >&2; }
die()   { error "$*"; exit 1; }

cleanup() {
    local code=$?
    # rm -f "$TEMP_FILE"
    (( code != 0 )) && error "Script failed with exit code $code"
}
trap cleanup EXIT
trap 'die "Interrupted"' INT TERM

main() {
    log "Starting $SCRIPT_NAME"
    # ... your logic here ...
    log "Done"
}

main "$@"
TEMPLATE

echo ""
echo "Done."
