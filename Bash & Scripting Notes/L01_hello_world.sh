#!/usr/bin/env bash
# ==============================================================
# L01: Hello World, Shebang, echo, and Basic Output
# ==============================================================
# WHAT: The very first bash script. Covers the shebang line,
#       how bash executes a script, the echo command, printf,
#       and the difference between stdout and stderr.
# WHY: Every script starts here. Understanding HOW bash runs
#      your file (shebang, permissions, PATH) prevents the most
#      common beginner errors: "command not found", "permission
#      denied", or running the wrong interpreter.
# TOPIC: Foundations
# ==============================================================

# ── SHEBANG ────────────────────────────────────────────────
# The first line (#!) tells the OS which interpreter to use.
# /usr/bin/env bash  — finds bash in PATH (portable, preferred)
# /bin/bash          — hardcoded path (faster but less portable)
# Without a shebang: the shell that ran THIS script interprets it.
# That might be sh, dash, zsh — each has different behaviour.

# ── COMMENTS ───────────────────────────────────────────────
# Everything after # on a line is a comment. Bash ignores it.
# There are no block comments in bash — use # on every line.

# ── MAKING A SCRIPT EXECUTABLE ─────────────────────────────
# To run: chmod +x L01_hello_world.sh && ./L01_hello_world.sh
# Or without chmod: bash L01_hello_world.sh

echo "=== L01: Hello World and Basic Output ==="

# ── echo ────────────────────────────────────────────────────
# echo prints its arguments followed by a newline.
# It's the simplest way to produce output.

echo "Hello, World!"          # prints: Hello, World!
echo 'Single quotes work too' # prints: Single quotes work too
echo                          # prints a blank line (no arguments)

# Double quotes vs single quotes:
#   Double: variables and special characters ARE expanded
#   Single: EVERYTHING is literal — no expansion at all
NAME="Alice"
echo "Hello, $NAME"   # Hello, Alice   (double: variable expanded)
echo 'Hello, $NAME'   # Hello, $NAME   (single: literal dollar sign)

# ── echo FLAGS ──────────────────────────────────────────────
echo -n "No newline after this"  # -n: suppress the trailing newline
echo " — same line continues"    # this prints on the same line

echo -e "Tab:\there\nNewline above"  # -e: enable escape sequences
# \t = tab, \n = newline, \\ = backslash

# NOTE: echo -e is not POSIX. Prefer printf for portable scripts.

# ── printf ──────────────────────────────────────────────────
# printf: more powerful and portable than echo.
# Same syntax as C's printf: format string + arguments.

printf "Hello, %s!\n" "World"      # Hello, World!
printf "Number: %d\n" 42           # Number: 42
printf "Float: %.2f\n" 3.14159     # Float: 3.14
printf "Hex: 0x%X\n" 255           # Hex: 0xFF
printf "%-10s %5d\n" "item" 99     # left-align string, right-align number

# ── STDOUT vs STDERR ────────────────────────────────────────
# stdout (fd 1): normal output — goes to terminal or can be piped
# stderr (fd 2): error messages — goes to terminal by default
#                but can be redirected separately

echo "This goes to stdout"           # file descriptor 1
echo "This is an error" >&2          # redirect to file descriptor 2

# Redirect stdout to a file:
echo "Saved to file" > /tmp/test_output.txt

# Redirect both stdout and stderr to a file:
echo "All output" > /tmp/all.txt 2>&1
# Or with bash 4+: &> /tmp/all.txt

# ── THE exit COMMAND ────────────────────────────────────────
# Every script exits with a status code (0-255).
# 0 = success, anything else = failure.
# The previous command's exit code is in $?

ls /tmp > /dev/null 2>&1   # suppress all output
echo "ls exit code: $?"    # 0 (success, /tmp exists)

ls /nonexistent > /dev/null 2>&1
echo "bad ls exit code: $?"  # non-zero (failure)

# ── RUNNING THIS SCRIPT ─────────────────────────────────────
echo ""
echo "Script path:      $0"         # $0 = name of the script itself
echo "Shell:            $SHELL"     # which shell is running
echo "Bash version:     $BASH_VERSION"

# ── TIPS ────────────────────────────────────────────────────
# Use 'bash -x script.sh' to trace execution (prints each command)
# Use 'bash -n script.sh' to check syntax without running
# Use 'shellcheck script.sh' to lint for common bugs (install separately)

echo ""
echo "Done. Exit code will be 0 (success)."
exit 0   # explicitly exit with success (optional — last command's code is used if omitted)
