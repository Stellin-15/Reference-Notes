#!/usr/bin/env bash
# ==============================================================
# L09: Text Processing — grep, sed, awk, cut, sort, uniq, tr
# ==============================================================
# WHAT: The core Unix text-processing tools that every bash
#       scripter must know. grep for searching, sed for stream
#       editing, awk for structured data, cut/sort/uniq for
#       quick transforms, and tr for character translation.
# WHY: Log parsing, report generation, config file processing,
#      data extraction — all of these are done with these tools.
#      A one-liner that would take 30 lines of Python takes 3
#      lines with awk. Understanding these tools transforms you
#      from a scripter into a command-line power user.
# TOPIC: Text Processing
# ==============================================================

set -euo pipefail
echo "=== L09: Text Processing ==="

# Create a sample log file for demos
LOGFILE="/tmp/sample.log"
cat > "$LOGFILE" <<'EOF'
2024-01-15 09:00:01 INFO  server started on port 8080
2024-01-15 09:00:15 DEBUG connection from 192.168.1.10
2024-01-15 09:01:22 INFO  user alice logged in
2024-01-15 09:02:45 WARN  disk usage at 80%
2024-01-15 09:03:11 ERROR failed to write /var/log/app.log: permission denied
2024-01-15 09:04:00 INFO  user bob logged in
2024-01-15 09:05:33 DEBUG connection from 10.0.0.5
2024-01-15 09:06:12 ERROR database connection lost: timeout after 30s
2024-01-15 09:07:01 INFO  reconnected to database
2024-01-15 09:08:55 WARN  memory usage at 75%
2024-01-15 09:09:00 INFO  user alice logged out
EOF

CSV="/tmp/sample.csv"
cat > "$CSV" <<'EOF'
name,age,role,salary
alice,30,engineer,95000
bob,25,designer,72000
charlie,35,manager,110000
diana,28,engineer,88000
eve,32,analyst,65000
frank,40,director,150000
EOF

# ── GREP ─────────────────────────────────────────────────────
echo ""
echo "grep:"

echo "  ERROR lines:"
grep "ERROR" "$LOGFILE" | sed 's/^/    /'

echo "  Lines NOT containing DEBUG:"
grep -v "DEBUG" "$LOGFILE" | sed 's/^/    /'

echo "  Count of WARN or ERROR:"
grep -c -E "WARN|ERROR" "$LOGFILE"    # -c: count; -E: extended regex

echo "  Line numbers with ERROR:"
grep -n "ERROR" "$LOGFILE" | sed 's/^/    /'

echo "  Only the matched part:"
grep -o "192\.168\.[0-9.]*\|10\.[0-9.]*" "$LOGFILE" | sed 's/^/    /'

echo "  Context (1 line before+after each ERROR):"
grep -B1 -A1 "ERROR" "$LOGFILE" | sed 's/^/    /'

echo "  Case-insensitive:"
grep -i "warn" "$LOGFILE" | wc -l

echo "  Recursive grep in /etc for 'localhost':"
grep -rl "localhost" /etc 2>/dev/null | head -3 | sed 's/^/    /'

# ── SED ──────────────────────────────────────────────────────
echo ""
echo "sed:"

# sed 's/find/replace/'    — substitute first match per line
# sed 's/find/replace/g'   — substitute ALL matches per line
# sed 's/find/replace/2'   — substitute second match per line
# sed -n 'p'               — print only explicitly requested lines
# sed -i                   — in-place edit (use -i.bak for safety)

echo "  Replace INFO with [INFO]:"
sed 's/INFO/[INFO]/g' "$LOGFILE" | head -3 | sed 's/^/    /'

echo "  Delete DEBUG lines:"
sed '/DEBUG/d' "$LOGFILE" | sed 's/^/    /'

echo "  Print lines 3-5 only:"
sed -n '3,5p' "$LOGFILE" | sed 's/^/    /'

echo "  Print lines matching ERROR:"
sed -n '/ERROR/p' "$LOGFILE" | sed 's/^/    /'

echo "  Extract timestamp (first 19 chars):"
sed 's/^\(.\{19\}\).*/\1/' "$LOGFILE" | head -3 | sed 's/^/    /'

echo "  Remove leading spaces:"
echo "   trimmed   " | sed 's/^[[:space:]]*//'

echo "  Remove trailing spaces:"
echo "   trimmed   " | sed 's/[[:space:]]*$//'

echo "  Remove blank lines:"
printf "line1\n\nline2\n\nline3\n" | sed '/^[[:space:]]*$/d'

# In-place edit with backup:
cp "$LOGFILE" /tmp/sample_backup.log
sed -i.bak 's/localhost/127.0.0.1/g' /tmp/sample_backup.log 2>/dev/null || true
# Note: macOS sed -i requires an extension (even empty: -i '')

# ── AWK ──────────────────────────────────────────────────────
echo ""
echo "awk:"
# awk: processes text field by field
# Default field separator: whitespace. Fields: $1 $2 ... $NF (last)
# NR = line number, NF = number of fields

echo "  Log level and message only:"
awk '{print $3, $4, $5, $6}' "$LOGFILE" | head -3 | sed 's/^/    /'

echo "  Only ERROR lines, showing the message:"
awk '$3 == "ERROR" {print NR": "$4,$5,$6,$7,$8}' "$LOGFILE" | sed 's/^/    /'

echo "  Count lines by log level:"
awk '{count[$3]++} END {for (k in count) print k, count[k]}' "$LOGFILE" | sort | sed 's/^/    /'

echo "  CSV: engineers with salary > 85000:"
awk -F',' 'NR>1 && $3=="engineer" && $4>85000 {print $1, $4}' "$CSV" | sed 's/^/    /'

echo "  CSV: average salary:"
awk -F',' 'NR>1 {sum+=$4; n++} END {printf "  avg salary: %.0f\n", sum/n}' "$CSV"

echo "  CSV: add a 'senior' label to anyone over 32:"
awk -F',' 'BEGIN{OFS=","} NR==1{print $0,"level"} NR>1{print $0, ($2>32?"senior":"junior")}' "$CSV" | sed 's/^/    /'

echo "  Sum of salaries by role:"
awk -F',' 'NR>1 {sum[$3]+=$4} END {for (r in sum) print r, sum[r]}' "$CSV" | sort | sed 's/^/    /'

# ── CUT ──────────────────────────────────────────────────────
echo ""
echo "cut:"

echo "  CSV first column:"
cut -d',' -f1 "$CSV" | sed 's/^/    /'

echo "  CSV columns 1 and 3:"
cut -d',' -f1,3 "$CSV" | sed 's/^/    /'

echo "  Log: first 19 chars (timestamp):"
cut -c1-19 "$LOGFILE" | head -3 | sed 's/^/    /'

# ── SORT ─────────────────────────────────────────────────────
echo ""
echo "sort:"

echo "  CSV sorted by age (column 2, numeric):"
tail -n+2 "$CSV" | sort -t',' -k2 -n | sed 's/^/    /'

echo "  CSV sorted by salary descending:"
tail -n+2 "$CSV" | sort -t',' -k4 -rn | head -3 | sed 's/^/    /'

echo "  Log levels sorted and unique:"
awk '{print $3}' "$LOGFILE" | sort -u | sed 's/^/    /'

# ── UNIQ ─────────────────────────────────────────────────────
echo ""
echo "uniq:"

echo "  IP addresses that appear more than once:"
grep -oE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" "$LOGFILE" | sort | uniq -c | sort -rn | sed 's/^/    /'

echo "  Unique log levels with count:"
awk '{print $3}' "$LOGFILE" | sort | uniq -c | sort -rn | sed 's/^/    /'

# ── TR ───────────────────────────────────────────────────────
echo ""
echo "tr:"

echo "  Uppercase:"
echo "hello world" | tr '[:lower:]' '[:upper:]'

echo "  Spaces to underscores:"
echo "my file name" | tr ' ' '_'

echo "  Delete digits:"
echo "abc123def456" | tr -d '[:digit:]'

echo "  Squeeze repeated spaces:"
echo "too   many   spaces" | tr -s ' '

echo "  CSV to TSV (comma to tab):"
echo "alice,30,engineer" | tr ',' '\t'

# ── HEAD AND TAIL ─────────────────────────────────────────────
echo ""
echo "head and tail:"

echo "  First 3 log lines:"
head -3 "$LOGFILE" | sed 's/^/    /'

echo "  Last 3 log lines:"
tail -3 "$LOGFILE" | sed 's/^/    /'

echo "  Skip header (tail from line 2):"
tail -n +2 "$CSV" | head -3 | sed 's/^/    /'

echo "  Follow a file (tail -f — for live monitoring):"
echo "  (tail -f is interactive — not run here)"

# ── WC ───────────────────────────────────────────────────────
echo ""
echo "wc:"

echo "  Line count: $(wc -l < "$LOGFILE")"
echo "  Word count: $(wc -w < "$LOGFILE")"
echo "  Char count: $(wc -c < "$LOGFILE")"

# ── PRACTICAL EXAMPLE: LOG SUMMARY ──────────────────────────
echo ""
echo "=== Practical: Log Summary ==="

echo "  Total lines:    $(wc -l < "$LOGFILE")"
echo "  ERROR count:    $(grep -c ERROR "$LOGFILE")"
echo "  WARN count:     $(grep -c WARN  "$LOGFILE")"
echo "  INFO count:     $(grep -c INFO  "$LOGFILE")"
echo "  Unique IPs:     $(grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' "$LOGFILE" | sort -u | wc -l)"
echo "  Users logged in:$(grep 'logged in' "$LOGFILE" | awk '{print $5}' | sort -u | tr '\n' ' ')"

echo ""
echo "Done."
