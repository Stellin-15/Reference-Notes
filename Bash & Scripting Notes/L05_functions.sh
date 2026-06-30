#!/usr/bin/env bash
# ==============================================================
# L05: Functions — Declaration, Arguments, Return Values, Scope
# ==============================================================
# WHAT: How to write, call, and structure bash functions.
#       Arguments ($1..$n, $@), return values (exit codes vs echo),
#       local variables, recursive functions, and passing functions
#       as callbacks.
# WHY: Functions are the key to reusable, testable scripts. Without
#      them, complex scripts become unreadable 500-line spaghetti.
#      Common patterns: helper functions, error handlers, retry
#      wrappers, and library-style sourced function files.
# TOPIC: Foundations
# ==============================================================

echo "=== L05: Functions ==="

# ── DEFINING A FUNCTION ─────────────────────────────────────
# Two equivalent syntaxes:
greet() {
    echo "Hello, $1!"     # $1 = first argument to the function
}

function greet2 {         # 'function' keyword is optional
    echo "Hi, $1!"
}

greet "World"             # Hello, World!
greet2 "Alice"            # Hi, Alice!

# ── ARGUMENTS ───────────────────────────────────────────────
echo ""
echo "Arguments:"

show_args() {
    echo "Function: $0"        # $0 = script name (NOT function name)
    echo "FUNCNAME: ${FUNCNAME[0]}"  # current function name
    echo "Arg count: $#"
    echo "All args: $@"
    echo "First: $1"
    echo "Second: $2"

    # Iterate over all arguments
    local i=1
    for arg in "$@"; do
        echo "  arg[$i] = $arg"
        ((i++))
    done
}

show_args "alpha" "beta" "gamma"

# Passing an array to a function (quirk: arrays don't pass directly)
arr=("one" "two" "three")
print_array() {
    local -n ref=$1     # nameref: reference to the array by name (bash 4.3+)
    for item in "${ref[@]}"; do
        echo "  item: $item"
    done
}
print_array arr          # pass array name (not value)

# Alternative (older bash): use "${arr[@]}" and rebuild inside
print_array_old() {
    local items=("$@")  # rebuild from positional args
    for item in "${items[@]}"; do
        echo "  item: $item"
    done
}
print_array_old "${arr[@]}"

# ── RETURN VALUES ───────────────────────────────────────────
echo ""
echo "Return values:"

# Bash functions return an EXIT CODE (0-255), not a value.
# 0 = success, non-zero = failure.
# To return a "real" value, use echo + command substitution.

is_even() {
    local n=$1
    (( n % 2 == 0 ))  # last command's exit code becomes function's exit code
}

is_even 4 && echo "4 is even"
is_even 7 || echo "7 is odd"

# Return a value via echo (caller captures with $(...))
add() {
    echo $(( $1 + $2 ))   # "return" the value by printing it
}

result=$(add 3 4)          # capture via command substitution
echo "3 + 4 = $result"

# Return multiple values via echo (separated by delimiter)
get_stats() {
    local arr=("$@")
    local min=${arr[0]} max=${arr[0]} sum=0
    for v in "${arr[@]}"; do
        (( v < min )) && min=$v
        (( v > max )) && max=$v
        (( sum += v ))
    done
    echo "$min $max $sum"   # print space-separated
}

read -r min max sum <<< "$(get_stats 3 1 4 1 5 9 2 6)"
echo "min=$min max=$max sum=$sum"

# ── LOCAL VARIABLES ─────────────────────────────────────────
echo ""
echo "Local variables:"

x=100   # global

modify() {
    local x=999          # local — doesn't affect outer x
    echo "Inside: x=$x"
}

modify
echo "Outside: x=$x"    # still 100

# ── ERROR HANDLING IN FUNCTIONS ─────────────────────────────
echo ""
echo "Error handling:"

find_file() {
    local path="$1"
    if [[ ! -f "$path" ]]; then
        echo "ERROR: file not found: $path" >&2   # errors to stderr
        return 1                                   # non-zero = failure
    fi
    echo "$path"   # success: print the found path
    return 0
}

if result=$(find_file "/etc/passwd"); then
    echo "Found: $result"
else
    echo "Not found"
fi

if result=$(find_file "/nonexistent/file"); then
    echo "Found: $result"
else
    echo "Not found (as expected)"
fi

# ── DEFAULT ARGUMENT VALUES ─────────────────────────────────
echo ""
echo "Default arguments:"

greet_with_default() {
    local name="${1:-World}"    # use "World" if $1 is unset or empty
    local greeting="${2:-Hello}"
    echo "$greeting, $name!"
}

greet_with_default                    # Hello, World!
greet_with_default "Alice"            # Hello, Alice!
greet_with_default "Bob" "Goodbye"    # Goodbye, Bob!

# ── RECURSIVE FUNCTIONS ─────────────────────────────────────
echo ""
echo "Recursion:"

factorial() {
    local n=$1
    (( n <= 1 )) && echo 1 && return
    local sub=$(factorial $(( n - 1 )))
    echo $(( n * sub ))
}

echo "5! = $(factorial 5)"   # 120
echo "7! = $(factorial 7)"   # 5040

# ── FUNCTION AS A PATTERN: RETRY WRAPPER ────────────────────
echo ""
echo "Retry wrapper:"

# A general-purpose retry function — very useful in automation
retry() {
    local max_attempts="${1:-3}"
    local delay="${2:-1}"
    shift 2
    local cmd=("$@")    # remaining args are the command to retry

    local attempt=1
    while (( attempt <= max_attempts )); do
        echo "  Attempt $attempt/$max_attempts: ${cmd[*]}"
        if "${cmd[@]}"; then
            echo "  Success on attempt $attempt"
            return 0
        fi
        echo "  Failed. Retrying in ${delay}s..."
        sleep "$delay"
        ((attempt++))
    done
    echo "  All $max_attempts attempts failed." >&2
    return 1
}

# Demo: command that fails twice then succeeds
attempt_count=0
flaky_command() {
    ((attempt_count++))
    (( attempt_count < 3 )) && return 1   # fail first 2 times
    return 0
}

retry 4 0 flaky_command

# ── FUNCTION LIBRARIES (sourcing) ───────────────────────────
echo ""
echo "Sourcing function libraries:"

# Write a mini library to /tmp
cat > /tmp/my_lib.sh <<'EOF'
#!/usr/bin/env bash
# My reusable functions

log_info()  { echo "[INFO]  $(date '+%H:%M:%S') $*"; }
log_warn()  { echo "[WARN]  $(date '+%H:%M:%S') $*" >&2; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $*" >&2; }

die() {
    log_error "$*"
    exit 1
}
EOF

# Source it into the current script
# shellcheck source=/dev/null
source /tmp/my_lib.sh   # or: . /tmp/my_lib.sh (dot is equivalent)

log_info  "Library loaded successfully"
log_warn  "This is a warning"
log_error "This is an error (goes to stderr)"

# ── PIPELINES AND FUNCTIONS ─────────────────────────────────
echo ""
echo "Functions in pipelines:"

# Functions can be part of pipes
double_lines() {
    while IFS= read -r line; do
        echo "$line"
        echo "$line"
    done
}

printf "alpha\nbeta\ngamma\n" | double_lines | head -4

echo ""
echo "Done."
