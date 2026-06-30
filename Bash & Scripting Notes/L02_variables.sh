#!/usr/bin/env bash
# ==============================================================
# L02: Variables, Assignment, Quoting, and Scope
# ==============================================================
# WHAT: How to declare, assign, and read variables in bash.
#       Variable types (string, integer, array), quoting rules,
#       special variables, readonly, local scope, and export.
# WHY: Variables are the foundation of every script. Getting
#      quoting wrong is the #1 source of bash bugs — spaces in
#      filenames, word splitting, and glob expansion all bite
#      you when you forget double quotes.
# TOPIC: Foundations
# ==============================================================

echo "=== L02: Variables ==="

# ── ASSIGNMENT ──────────────────────────────────────────────
# NO spaces around = (this is different from most languages)
name="Alice"          # correct
# name = "Alice"      # WRONG: bash treats 'name' as a command!

# ── READING A VARIABLE ──────────────────────────────────────
echo $name            # Alice (works but risky — unquoted)
echo "$name"          # Alice (correct — always quote variable reads)
echo "${name}"        # Alice (brace form — clearest, prevents ambiguity)

# Braces are required when the variable name is followed by text:
fruit="apple"
echo "${fruit}s"      # apples (without braces: $fruits — undefined var)
echo "$fruits"        # (empty — different variable name!)

# ── QUOTING RULES ───────────────────────────────────────────
# Double quotes: expand variables and command substitutions
# Single quotes: everything is literal — NO expansion at all
# No quotes:     word splitting and glob expansion happen!

file="my file.txt"          # filename with a space

echo "$file"                # my file.txt (one word — correct)
echo $file                  # my file.txt (two words — BAD if used as arg!)

# Demonstration of word-splitting danger:
# touch $file    → would try to touch "my" and "file.txt" separately
# touch "$file"  → correctly touches "my file.txt"

# ── SPECIAL VARIABLES ───────────────────────────────────────
echo ""
echo "Special variables:"
echo "  Script name:   $0"      # name of the script
echo "  First arg:     $1"      # first command-line argument
echo "  Second arg:    $2"
echo "  All args:      $@"      # all args as separate words (use this)
echo "  All args (IFS):$*"      # all args joined by IFS (usually avoid)
echo "  Arg count:     $#"      # number of arguments
echo "  Last exit code:$?"      # exit code of last command
echo "  Script PID:    $$"      # process ID of this script
echo "  Last bg PID:   $!"      # PID of last background process

# ── UNSET AND DEFAULT VALUES ────────────────────────────────
echo ""
echo "Default values:"

unset undefined_var             # ensure it's unset

# ${var:-default}: use default if var is unset OR empty
echo "${undefined_var:-fallback}"   # fallback

# ${var-default}: use default only if var is UNSET (not if empty)
empty_var=""
echo "${empty_var:-use-if-empty}"   # use-if-empty (var is empty)
echo "${empty_var-use-if-unset}"    # (empty — var is set, just empty)

# ${var:=default}: assign default if unset or empty, then use it
echo "${unset2:=assigned_now}"      # assigns and prints "assigned_now"
echo "$unset2"                       # now it's "assigned_now"

# ${var:?error}: print error and exit if unset or empty
# echo "${must_exist:?ERROR: must_exist is required}"

# ${var:+replacement}: use replacement if var IS set (opposite of :-)
active="yes"
echo "${active:+option is on}"   # option is on

# ── INTEGER VARIABLES ───────────────────────────────────────
echo ""
echo "Integers:"

declare -i count=0     # declare as integer type
count=count+5          # arithmetic without $(( )) — works with declare -i
echo "count = $count"  # 5

# For math without declare -i: use $(( )) — arithmetic expansion
x=10
y=3
echo "x + y = $((x + y))"    # 13
echo "x * y = $((x * y))"    # 30
echo "x / y = $((x / y))"    # 3  (integer division — truncates)
echo "x % y = $((x % y))"    # 1  (modulo)
echo "x ** y = $((x ** y))"  # 1000 (exponentiation, bash 3+)

# Increment / decrement
((count++))           # increment (inside (( )) — no $ needed)
echo "count after ++: $count"

# ── READONLY VARIABLES ──────────────────────────────────────
readonly MAX_RETRIES=3
echo "MAX_RETRIES = $MAX_RETRIES"
# MAX_RETRIES=4   # would cause: bash: MAX_RETRIES: readonly variable

# ── export — ENVIRONMENT VARIABLES ──────────────────────────
# Variables are LOCAL to the current shell by default.
# Use export to make them visible to child processes.

MY_VAR="hello"
export MY_VAR          # now subprocesses can read $MY_VAR
# Or in one step:
export GREETING="good morning"

# Check: bash -c 'echo $MY_VAR' — child sees MY_VAR
# Without export: bash -c 'echo $MY_VAR' — prints empty

# ── LOCAL SCOPE IN FUNCTIONS ────────────────────────────────
echo ""
echo "Scope:"

global_var="I am global"

my_function() {
    local local_var="I am local"    # only visible inside this function
    global_var="modified by func"   # modifies the outer variable
    echo "Inside: local_var=$local_var"
    echo "Inside: global_var=$global_var"
}

my_function
echo "Outside: global_var=$global_var"   # sees the modification
echo "Outside: local_var='${local_var}'" # empty — local_var is gone

# ── ARRAYS ──────────────────────────────────────────────────
echo ""
echo "Arrays:"

fruits=("apple" "banana" "cherry")   # indexed array

echo "${fruits[0]}"          # apple (0-indexed)
echo "${fruits[1]}"          # banana
echo "${fruits[-1]}"         # cherry (negative index: from end)
echo "${fruits[@]}"          # apple banana cherry (all elements)
echo "${#fruits[@]}"         # 3 (length of array)

fruits+=("date")             # append an element
echo "After append: ${fruits[@]}"

# Iterate over array elements
for f in "${fruits[@]}"; do
    echo "  fruit: $f"
done

# Associative array (dictionary) — requires bash 4+
declare -A colors
colors["red"]="#FF0000"
colors["green"]="#00FF00"
colors["blue"]="#0000FF"

echo "Red is: ${colors[red]}"
echo "Keys: ${!colors[@]}"        # get all keys
echo "Values: ${colors[@]}"       # get all values

# ── VARIABLE TYPES SUMMARY ──────────────────────────────────
# Bash variables are strings by default.
# declare -i: integer   (arithmetic auto-applied on assignment)
# declare -a: indexed array
# declare -A: associative array (bash 4+)
# declare -r: readonly
# declare -x: export (same as export)
# declare -l: lowercase on assignment
# declare -u: uppercase on assignment

declare -l lower_var="HELLO"
echo "lower_var = $lower_var"    # hello (auto-lowercased)

declare -u upper_var="hello"
echo "upper_var = $upper_var"    # HELLO (auto-uppercased)

echo ""
echo "Done."
