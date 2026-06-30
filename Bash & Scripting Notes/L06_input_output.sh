#!/usr/bin/env bash
# ==============================================================
# L06: Input / Output — read, pipes, redirection, /dev/null, tee
# ==============================================================
# WHAT: Reading user input (read), command-line argument parsing,
#       file redirection (>, >>, <), pipes (|), process substitution
#       (<()), tee, /dev/null, and file descriptors.
# WHY: I/O is the core of automation. Scripts read config files,
#      process logs, accept user input, and produce reports. Getting
#      redirection right is critical — sending errors to stderr keeps
#      pipelines clean and makes debugging possible.
# TOPIC: Foundations
# ==============================================================

echo "=== L06: Input / Output ==="

# ── READING USER INPUT ──────────────────────────────────────
echo ""
echo "read:"

# read: read one line from stdin into a variable
# -r: raw mode (don't interpret backslash escapes)
# Always use -r unless you specifically need backslash interpretation
echo -n "Enter your name (or press Enter to skip): "
read -r user_name
echo "Hello, ${user_name:-Anonymous}"

# Read with a prompt (-p) — same as printing then reading
read -r -p "Enter a number: " user_num 2>/dev/null || user_num=42
echo "You entered (or default): $user_num"

# Read with a timeout (-t N seconds)
echo "Timed input (1 second):"
if read -r -t 1 timed_input; then
    echo "Got: $timed_input"
else
    echo "Timed out — using default"
fi

# Read a password without echoing (-s: silent)
# read -r -s -p "Password: " password
# echo  # newline after silent input
# echo "Password length: ${#password}"

# Read into multiple variables (splits on IFS)
echo "alice 30 engineer" | (IFS=' ' read -r name age role && echo "name=$name age=$age role=$role")

# Read all remaining tokens into an array with -a
read -r -a words <<< "one two three four"
echo "Words: ${words[@]}"     # one two three four
echo "Third: ${words[2]}"     # three

# ── COMMAND-LINE ARGUMENT PARSING ───────────────────────────
echo ""
echo "Argument parsing:"

# Simple positional: $1, $2, ... $N
# $0 = script name, $@ = all args, $# = count

# Manual parsing (simple scripts)
parse_simple() {
    local host="${1:-localhost}"
    local port="${2:-8080}"
    echo "host=$host port=$port"
}
parse_simple "example.com" "443"
parse_simple  # uses defaults

# Flag-based parsing with getopts (POSIX — single-char flags only)
parse_flags() {
    local verbose=false
    local output="/dev/stdout"
    local count=1

    # : after a letter means it takes an argument
    while getopts "vo:c:" opt; do
        case "$opt" in
            v) verbose=true ;;
            o) output="$OPTARG" ;;    # OPTARG holds the value
            c) count="$OPTARG" ;;
            ?) echo "Usage: parse_flags [-v] [-o output] [-c count]" >&2; return 1 ;;
        esac
    done
    shift $(( OPTIND - 1 ))   # remove parsed flags; remaining are positional args
    local remaining=("$@")

    echo "verbose=$verbose output=$output count=$count"
    echo "remaining args: ${remaining[*]}"
}

parse_flags -v -o /tmp/out.txt -c 3 file1.txt file2.txt

# Long-option parsing (manual — getopt is not POSIX and varies by OS)
# For complex CLIs, use a dedicated parser or structure the script differently

# ── FILE REDIRECTION ────────────────────────────────────────
echo ""
echo "Redirection:"

# > : overwrite a file with stdout
echo "line 1" > /tmp/demo.txt
echo "line 2" > /tmp/demo.txt    # overwrites!

# >> : append stdout to a file
echo "line 1" > /tmp/demo.txt
echo "line 2" >> /tmp/demo.txt
echo "line 3" >> /tmp/demo.txt
echo "Contents of /tmp/demo.txt:"
cat /tmp/demo.txt

# < : redirect file to stdin
wc -l < /tmp/demo.txt            # count lines without cat

# 2> : redirect stderr to a file
ls /nonexistent 2> /tmp/err.txt
echo "Error file contents: $(cat /tmp/err.txt)"

# 2>&1 : redirect stderr to wherever stdout currently goes
ls /nonexistent > /tmp/combined.txt 2>&1
cat /tmp/combined.txt

# &> : redirect both stdout and stderr (bash shorthand)
ls /nonexistent &> /tmp/both.txt

# ── FILE DESCRIPTORS ────────────────────────────────────────
echo ""
echo "File descriptors:"

# Open a file for reading on fd 3
exec 3< /etc/hostname
read -r -u 3 hostname_line    # read from fd 3
echo "Hostname from fd 3: $hostname_line"
exec 3<&-                     # close fd 3

# Open a file for writing on fd 4
exec 4> /tmp/fd4_output.txt
echo "Writing to fd 4" >&4
exec 4>&-                     # close fd 4
cat /tmp/fd4_output.txt

# ── /dev/null ───────────────────────────────────────────────
echo ""
echo "/dev/null:"
# /dev/null: discard output entirely

ls /nonexistent > /dev/null 2>&1   # suppress all output
echo "Suppressed ls exit code: $?"

# Discard stderr only (keep stdout)
ls /etc /nonexistent 2>/dev/null   # shows /etc content, hides error

# ── PIPES ───────────────────────────────────────────────────
echo ""
echo "Pipes:"

# Pipe connects stdout of one command to stdin of the next
echo "one two three four five" | tr ' ' '\n' | sort | uniq | wc -l

# Count unique words in a file
cat /etc/passwd | cut -d: -f1 | sort | head -5   # first 5 usernames

# Chain: grep lines, extract field, sort, count
echo "Pipeline:"
getent passwd 2>/dev/null | cut -d: -f1 | sort | head -3 || \
    cut -d: -f1 /etc/passwd | sort | head -3

# ── TEE ─────────────────────────────────────────────────────
echo ""
echo "tee:"

# tee: write to stdout AND to a file simultaneously
echo "test output" | tee /tmp/tee_demo.txt | tr '[:lower:]' '[:upper:]'
echo "tee wrote to /tmp/tee_demo.txt:"
cat /tmp/tee_demo.txt

# Append with tee -a
echo "more output" | tee -a /tmp/tee_demo.txt > /dev/null

# ── PROCESS SUBSTITUTION ────────────────────────────────────
echo ""
echo "Process substitution:"

# <(cmd): treats command output as a virtual file
# Useful when a command needs a filename, not stdin

# Compare two sorted lists without temp files:
diff <(echo -e "apple\nbanana\ncherry") <(echo -e "apple\ndate\ncherry")

# Paste two command outputs side by side:
paste <(seq 1 3) <(seq 4 6)

# ── READING A FILE LINE BY LINE ─────────────────────────────
echo ""
echo "Reading files:"

# Best practice: while IFS= read -r line
echo -e "line one\nline two\nline three" > /tmp/lines.txt

while IFS= read -r line; do
    echo "  | $line"
done < /tmp/lines.txt

# Process each line with the filename as argument:
while IFS= read -r line; do
    [[ "$line" == \#* ]] && continue   # skip comments
    [[ -z "$line" ]] && continue       # skip blank lines
    echo "  processing: $line"
done < /etc/hosts

echo ""
echo "Done."
