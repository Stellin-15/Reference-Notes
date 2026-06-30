#!/usr/bin/env bash
# ==============================================================
# L04: Control Flow — if, case, while, for, until, break, continue
# ==============================================================
# WHAT: All conditional and loop constructs in bash. The [[ ]]
#       test syntax, numeric comparisons, file tests, case
#       statements, C-style for loops, while/until loops, and
#       loop control (break, continue, return).
# WHY: Control flow is the skeleton of every non-trivial script.
#      Getting test syntax right ([ ] vs [[ ]] vs (( ))) prevents
#      subtle bugs with empty variables, special characters, and
#      unexpected glob expansion.
# TOPIC: Foundations
# ==============================================================

echo "=== L04: Control Flow ==="

# ── IF / ELIF / ELSE ────────────────────────────────────────
# [[ ]] is the bash-specific test — use this, not [ ]
# Why [[ ]] over [ ]:
#   - No word splitting on variables → safer with spaces
#   - Supports && and || inside ([ ] requires -a and -o)
#   - Supports regex with =~
#   - Supports pattern matching with == *glob*

score=75

if [[ $score -ge 90 ]]; then
    echo "Grade: A"
elif [[ $score -ge 80 ]]; then
    echo "Grade: B"
elif [[ $score -ge 70 ]]; then
    echo "Grade: C"
else
    echo "Grade: F"
fi

# ── TEST CONDITIONS ─────────────────────────────────────────
echo ""
echo "Test conditions:"

# Numeric comparisons (use -eq -ne -lt -le -gt -ge inside [[ ]])
a=5; b=10
[[ $a -lt $b ]] && echo "$a < $b"
[[ $a -ne $b ]] && echo "$a != $b"

# Or use (( )) for arithmetic — more natural syntax
(( a < b )) && echo "arithmetic: $a < $b"
(( a == 5 )) && echo "arithmetic: a is 5"

# String comparisons
s1="apple"; s2="banana"
[[ "$s1" < "$s2" ]] && echo "'$s1' comes before '$s2' alphabetically"
[[ "$s1" == "apple" ]] && echo "s1 equals apple"

# File tests
echo ""
echo "File tests:"
[[ -f "/etc/hostname" ]]  && echo "/etc/hostname is a regular file"
[[ -d "/tmp" ]]           && echo "/tmp is a directory"
[[ -e "/etc/passwd" ]]    && echo "/etc/passwd exists"
[[ -r "/etc/passwd" ]]    && echo "/etc/passwd is readable"
[[ -w "/tmp" ]]           && echo "/tmp is writable"
[[ -x "/bin/bash" ]]      && echo "/bin/bash is executable"
[[ -s "/etc/passwd" ]]    && echo "/etc/passwd is non-empty"
[[ -L "/bin" ]]           && echo "/bin is a symlink (common on modern Linux)"
[[ "/etc/passwd" -nt "/etc/hostname" ]] && echo "passwd is newer than hostname"

# Combining conditions
[[ -f "/etc/passwd" && -r "/etc/passwd" ]] && echo "passwd: file and readable"
[[ -d "/nonexistent" || -d "/tmp" ]]       && echo "at least one dir exists"
[[ ! -d "/nonexistent" ]]                  && echo "negation: /nonexistent is not a dir"

# ── CASE STATEMENT ──────────────────────────────────────────
echo ""
echo "case statement:"

day="Monday"
case "$day" in
    Monday|Tuesday|Wednesday|Thursday|Friday)
        echo "$day is a weekday"
        ;;
    Saturday|Sunday)
        echo "$day is the weekend"
        ;;
    *)
        echo "$day is unknown"
        ;;
esac

# Case with glob patterns
version="v2.3.1"
case "$version" in
    v1.*)  echo "major version 1" ;;
    v2.*)  echo "major version 2" ;;
    v[3-9]*) echo "major version 3 or higher" ;;
    *)     echo "unknown version format" ;;
esac

# ── FOR LOOP (lists) ────────────────────────────────────────
echo ""
echo "for loop (list):"

for fruit in apple banana cherry; do
    echo "  fruit: $fruit"
done

# Iterate over an array
files=("a.txt" "b.log" "c.csv")
for f in "${files[@]}"; do
    echo "  file: $f"
done

# Iterate over files matching a glob
echo "  sh files in /etc/profile.d/:"
for script in /etc/profile.d/*.sh; do
    [[ -f "$script" ]] && echo "    $script"
done

# ── FOR LOOP (C-style) ──────────────────────────────────────
echo ""
echo "for loop (C-style):"

for ((i = 0; i < 5; i++)); do
    printf "  i=%d\n" "$i"
done

# With step
for ((i = 0; i <= 20; i += 5)); do
    printf "  %d " "$i"
done; echo

# ── FOR LOOP (brace expansion) ──────────────────────────────
echo ""
echo "brace expansion:"

# {start..end} — generates a sequence
for i in {1..5}; do
    printf "  %d " "$i"
done; echo

# {start..end..step}
for i in {0..20..4}; do
    printf "  %d " "$i"
done; echo

# ── WHILE LOOP ──────────────────────────────────────────────
echo ""
echo "while loop:"

count=1
while [[ $count -le 3 ]]; do
    echo "  count = $count"
    ((count++))
done

# Read lines from a file (or command output) with while
echo "  Lines from /etc/hostname:"
while IFS= read -r line; do
    echo "  | $line"
done < /etc/hostname

# Read from command output
echo "  First 3 entries in /etc/passwd:"
count=0
while IFS=: read -r user _ uid _ _ _ _; do
    echo "  user=$user uid=$uid"
    ((count++))
    [[ $count -ge 3 ]] && break
done < /etc/passwd

# ── UNTIL LOOP ──────────────────────────────────────────────
echo ""
echo "until loop (runs WHILE condition is FALSE):"

n=5
until [[ $n -le 0 ]]; do
    printf "  %d " "$n"
    ((n--))
done; echo

# ── BREAK AND CONTINUE ──────────────────────────────────────
echo ""
echo "break and continue:"

for i in {1..10}; do
    [[ $((i % 2)) -eq 0 ]] && continue   # skip even numbers
    [[ $i -gt 7 ]] && break              # stop after 7
    printf "  %d " "$i"
done; echo  # prints: 1 3 5 7

# break N / continue N — break/continue N levels of nested loops
echo "break 2 from nested loops:"
for i in {1..3}; do
    for j in {1..3}; do
        [[ $i -eq 2 && $j -eq 2 ]] && { echo "  breaking at i=$i j=$j"; break 2; }
        echo "  i=$i j=$j"
    done
done

# ── INFINITE LOOP ───────────────────────────────────────────
# while true; do ... done   — common pattern for daemons and retry loops
# for (( ; ; )); do ... done — equivalent C-style

echo ""
echo "Infinite loop with break:"
attempt=0
while true; do
    ((attempt++))
    echo "  attempt $attempt"
    [[ $attempt -ge 3 ]] && break
done

# ── SELECT ──────────────────────────────────────────────────
# select: interactive menu (not useful in non-interactive scripts)
# Shown here for reference — skip in automation
echo ""
echo "select (interactive menu — skip in automation):"
echo "(Would show a numbered menu if stdin were a terminal)"
# select choice in "Option A" "Option B" "Quit"; do
#     case "$choice" in
#         "Quit") break ;;
#         *) echo "You chose: $choice" ;;
#     esac
# done

echo ""
echo "Done."
