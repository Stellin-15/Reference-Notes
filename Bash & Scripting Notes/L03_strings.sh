#!/usr/bin/env bash
# ==============================================================
# L03: String Operations
# ==============================================================
# WHAT: Bash string manipulation: length, substring, search and
#       replace, case conversion, trimming, splitting, and the
#       most important string operators in ${...} syntax.
#       Also covers here-strings and here-documents.
# WHY: File paths, log parsing, config processing, and almost
#      every automation task involves string work. Knowing bash
#      built-in string operators means fewer external tools
#      (no sed/awk for simple cases) and faster scripts.
# TOPIC: Foundations
# ==============================================================

echo "=== L03: String Operations ==="

str="Hello, World!"

# ── LENGTH ──────────────────────────────────────────────────
echo ""
echo "Length:"
echo "${#str}"               # 13 — length of string

# ── SUBSTRING ───────────────────────────────────────────────
echo ""
echo "Substring:"
# ${var:offset:length}
echo "${str:0:5}"            # Hello    (5 chars from position 0)
echo "${str:7}"              # World!   (from position 7 to end)
echo "${str:7:5}"            # World    (5 chars starting at 7)
echo "${str: -6}"            # orld!    (6 chars from end — note the space!)
echo "${str: -6:5}"          # orld     (5 chars, starting 6 from end)

# ── SEARCH AND REPLACE ──────────────────────────────────────
echo ""
echo "Search and replace:"

path="/usr/local/bin:/usr/bin:/bin"

# ${var/find/replace} — replace FIRST match
echo "${path/bin/BIN}"       # /usr/local/BIN:/usr/bin:/bin

# ${var//find/replace} — replace ALL matches
echo "${path//bin/BIN}"      # /usr/local/BIN:/usr/BIN:/BIN

# ${var/#find/replace} — replace only if at START of string
echo "${path/#/usr/local/bin/}"    # strip if path starts with this
echo "${path/#\/usr/USR}"    # USR/local/bin:/usr/bin:/bin

# ${var/%find/replace} — replace only if at END of string
filename="report.txt"
echo "${filename/%.txt/.csv}"     # report.csv (change extension)

# ── PREFIX AND SUFFIX REMOVAL ───────────────────────────────
echo ""
echo "Prefix/suffix removal:"

url="https://www.example.com/path/to/page"

# ${var#pattern}  — remove SHORTEST match from the LEFT
echo "${url#*/}"             # /www.example.com/path/to/page
# ${var##pattern} — remove LONGEST match from the LEFT
echo "${url##*/}"            # page  (everything up to last /)

# ${var%pattern}  — remove SHORTEST match from the RIGHT
echo "${url%/*}"             # https://www.example.com/path/to
# ${var%%pattern} — remove LONGEST match from the RIGHT
echo "${url%%/*}"            # https:

# Common use: get filename without extension
file="archive.tar.gz"
echo "${file%.gz}"           # archive.tar
echo "${file%.*}"            # archive.tar  (remove last extension)
echo "${file%%.*}"           # archive      (remove all extensions)

# Get directory from path
filepath="/home/user/documents/report.pdf"
echo "${filepath%/*}"        # /home/user/documents  (like dirname)
echo "${filepath##*/}"       # report.pdf            (like basename)

# ── CASE CONVERSION (bash 4+) ───────────────────────────────
echo ""
echo "Case conversion:"

word="Hello World"
echo "${word,,}"             # hello world  (all lowercase)
echo "${word^^}"             # HELLO WORLD  (all uppercase)
echo "${word,}"              # hEllo World  (first char lowercase)  -- note: only first
echo "${word^}"              # Hello World  (first char uppercase)

# ── TESTING STRINGS ─────────────────────────────────────────
echo ""
echo "String tests:"

empty=""
nonempty="hello"

[[ -z "$empty" ]]    && echo "empty is empty"       # -z: zero length
[[ -n "$nonempty" ]] && echo "nonempty has content"  # -n: non-zero length
[[ "$nonempty" == "hello" ]] && echo "equals hello"
[[ "$nonempty" != "world" ]] && echo "not world"

# Pattern matching (not regex — glob patterns):
filename="report_2024.csv"
[[ "$filename" == *.csv ]] && echo "is a csv file"
[[ "$filename" == report_* ]] && echo "starts with report_"

# Regex matching with =~
[[ "$filename" =~ ^report_[0-9]{4}\.csv$ ]] && echo "matches date pattern"
# Capture groups go into BASH_REMATCH array:
if [[ "$filename" =~ ([0-9]{4}) ]]; then
    echo "Year found: ${BASH_REMATCH[1]}"   # 2024
fi

# ── SPLITTING STRINGS ───────────────────────────────────────
echo ""
echo "Splitting strings:"

csv_line="alice,30,engineer"

# Method 1: IFS (Internal Field Separator)
IFS=',' read -r name age role <<< "$csv_line"
echo "Name: $name | Age: $age | Role: $role"

# Method 2: read into an array
IFS=',' read -ra fields <<< "$csv_line"
echo "Fields: ${fields[@]}"         # alice 30 engineer
echo "Field count: ${#fields[@]}"   # 3

# Method 3: cut (for fixed-position fields)
echo "$csv_line" | cut -d',' -f1    # alice (first field)
echo "$csv_line" | cut -d',' -f2-3  # 30,engineer (fields 2-3)

# Reset IFS to default (space, tab, newline)
unset IFS

# ── STRING REPETITION ───────────────────────────────────────
echo ""
echo "Repetition:"

# printf can repeat a character
printf '─%.0s' {1..40}; echo   # prints 40 dashes
printf '%0.s*' {1..5}; echo    # prints 5 asterisks

# ── HERE-STRING ─────────────────────────────────────────────
echo ""
echo "Here-string:"

# <<< feeds a string as stdin to a command (no file, no subshell)
wc -w <<< "count the words in this string"   # 6

# Read a single line directly
read -r first_word rest <<< "hello world foo"
echo "First: $first_word | Rest: $rest"

# ── HERE-DOCUMENT ───────────────────────────────────────────
echo ""
echo "Here-document:"

# <<EOF ... EOF: multi-line string as stdin
# Variables ARE expanded (use <<'EOF' to prevent expansion)
cat <<EOF
This is a
multi-line
here document.
Script: $0
EOF

# Indented heredoc (bash 4+: <<- strips leading TABS, not spaces)
cat <<-BLOCK
	This line is indented with a tab
	But the tab is stripped in output
BLOCK

# Here-doc to a file:
cat > /tmp/example.conf <<EOF
[server]
host = localhost
port = 8080
EOF
echo "Config written. Contents:"
cat /tmp/example.conf

# ── USEFUL STRING PATTERNS ──────────────────────────────────
echo ""
echo "Useful patterns:"

# Check if string contains a substring
haystack="the quick brown fox"
needle="quick"
if [[ "$haystack" == *"$needle"* ]]; then
    echo "'$haystack' contains '$needle'"
fi

# Trim leading whitespace
trimmed_str="   hello world   "
trimmed="${trimmed_str#"${trimmed_str%%[![:space:]]*}"}"
echo "Leading trimmed: '${trimmed}'"

# Trim trailing whitespace
trimmed="${trimmed_str%"${trimmed_str##*[![:space:]]}"}"
echo "Trailing trimmed: '${trimmed}'"

# Both — combine with a function (see L06 for functions)
trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"   # remove leading spaces
    s="${s%"${s##*[![:space:]]}"}"   # remove trailing spaces
    echo "$s"
}
echo "Trimmed both: '$(trim "   hello   ")'"

echo ""
echo "Done."
