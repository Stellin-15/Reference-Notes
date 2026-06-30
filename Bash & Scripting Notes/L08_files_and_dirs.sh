#!/usr/bin/env bash
# ==============================================================
# L08: Files and Directories — find, stat, cp, mv, mkdir, chmod
# ==============================================================
# WHAT: Working with the filesystem: creating, copying, moving,
#       and deleting files and directories. File metadata (stat,
#       permissions, ownership). Finding files with find. Symbolic
#       links. Disk usage with du/df.
# WHY: Automation lives in the filesystem. Deployment scripts move
#      binaries, log rotation deletes old files, backup scripts
#      copy directories, and monitoring checks disk space. These
#      are daily sysadmin tasks encoded as repeatable scripts.
# TOPIC: File System
# ==============================================================

set -euo pipefail
echo "=== L08: Files and Directories ==="

# ── WORKING DIRECTORY ───────────────────────────────────────
echo ""
echo "Working directory:"
echo "  Current: $(pwd)"
echo "  Script dir: $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create a sandbox for demos
SANDBOX="/tmp/bash_demo_$$"   # $$ = PID makes it unique
mkdir -p "$SANDBOX"
echo "  Sandbox: $SANDBOX"

# Cleanup on exit
trap 'rm -rf "$SANDBOX"' EXIT

cd "$SANDBOX"   # work in the sandbox for the rest of this script

# ── CREATING FILES AND DIRECTORIES ──────────────────────────
echo ""
echo "Creating:"

# Create directories
mkdir mydir                      # single directory
mkdir -p a/b/c/d                 # create nested path; -p: no error if exists
mkdir -p logs/{2023,2024}/{jan,feb,mar}  # brace expansion: multiple dirs at once
echo "  Created dirs:" && find a logs -type d | head -8 | sort

# Create files
touch file1.txt                  # create empty file (or update timestamp)
echo "hello" > file2.txt         # create with content
printf "line1\nline2\n" > file3.txt
echo "  Created files: $(ls *.txt 2>/dev/null | tr '\n' ' ')"

# ── COPYING ─────────────────────────────────────────────────
echo ""
echo "Copying:"

cp file1.txt file1_copy.txt          # copy a file
cp -v file2.txt file2_copy.txt       # -v: verbose (print what's done)
cp -p file3.txt file3_preserved.txt  # -p: preserve permissions/timestamps
cp -r a/ a_backup/                   # -r: recursive (copy directory)
echo "  After copy: $(ls | tr '\n' ' ')"

# ── MOVING AND RENAMING ─────────────────────────────────────
echo ""
echo "Moving and renaming:"

mv file1_copy.txt renamed.txt        # rename (same filesystem: instant)
mv -n file2_copy.txt renamed.txt     # -n: no overwrite if target exists
mv renamed.txt mydir/                # move into a directory
echo "  After move: mydir=$(ls mydir/)"

# Rename a batch of files (change extension)
touch report_{1..5}.log
for f in report_*.log; do
    mv "$f" "${f%.log}.txt"           # replace .log with .txt
done
echo "  Renamed .log → .txt: $(ls report_*.txt | tr '\n' ' ')"

# ── DELETING ────────────────────────────────────────────────
echo ""
echo "Deleting:"

rm file3.txt                         # delete a file
rm -f nonexistent.txt                # -f: no error if file doesn't exist
rm -rf a_backup/                     # -rf: recursive force (delete directory)
# CAUTION: rm -rf is permanent. Always double-check paths.
# Safety pattern: build the path and print before deleting
DELETE_PATH="$SANDBOX/logs"
echo "  Would delete: $DELETE_PATH"
rm -rf "$DELETE_PATH"

# Safe delete: check the path is what you think it is
safe_rm() {
    local path="$1"
    local marker="$2"   # a file that MUST exist inside the directory
    [[ -d "$path" ]] || { echo "Not a directory: $path" >&2; return 1; }
    [[ -e "$path/$marker" ]] || { echo "Safety marker not found: $path/$marker" >&2; return 1; }
    rm -rf "$path"
}
# Example: safe_rm /some/dir ".deploy_marker"

# ── FILE METADATA (stat) ─────────────────────────────────────
echo ""
echo "File metadata:"

stat file2.txt 2>/dev/null || stat -f "%Sp %Su %Sg %z %Sm %N" file2.txt 2>/dev/null || true

# Portable way to get file size in bytes
file_size=$(wc -c < file2.txt)
echo "  file2.txt size: $file_size bytes"

# Last modification time
if stat --format="%Y" file2.txt &>/dev/null; then
    # GNU stat (Linux)
    mod_time=$(stat --format="%y" file2.txt)
else
    # BSD stat (macOS)
    mod_time=$(stat -f "%Sm" file2.txt 2>/dev/null || echo "unknown")
fi
echo "  file2.txt modified: $mod_time"

# ── PERMISSIONS ─────────────────────────────────────────────
echo ""
echo "Permissions:"

# chmod: change mode (permissions)
# Symbolic: u=user, g=group, o=other, a=all
chmod u+x file2.txt           # add execute for user
chmod go-w file2.txt          # remove write for group and other
chmod a=r  file3_preserved.txt # set read-only for everyone

# Octal (most common in scripts)
chmod 755 file2.txt     # rwxr-xr-x (owner: full, group/other: read+exec)
chmod 644 file3_preserved.txt  # rw-r--r-- (owner: rw, others: r)
chmod 600 file3_preserved.txt  # rw------- (owner only — for secrets/keys)

ls -la *.txt 2>/dev/null | head -5

# Check if we have permission to read/write/exec
[[ -r file2.txt ]] && echo "  file2.txt is readable"
[[ -w file2.txt ]] && echo "  file2.txt is writable"
[[ -x file2.txt ]] && echo "  file2.txt is executable"

# ── SYMBOLIC LINKS ──────────────────────────────────────────
echo ""
echo "Symbolic links:"

ln -s file2.txt link_to_file2        # create a symlink
ln -sf file2.txt link_to_file2       # -f: overwrite if link already exists
echo "  Symlink: $(ls -la link_to_file2)"
[[ -L link_to_file2 ]] && echo "  It is a symlink"
[[ -f link_to_file2 ]] && echo "  It resolves to a regular file"

# Resolve symlink to real path
real_path=$(readlink -f link_to_file2 2>/dev/null || realpath link_to_file2 2>/dev/null || echo "unknown")
echo "  Resolved: $real_path"

# ── FIND ─────────────────────────────────────────────────────
echo ""
echo "find:"

# Create some test structure
mkdir -p search_me/{scripts,data,config}
touch search_me/scripts/run.sh search_me/scripts/helper.sh
touch search_me/data/report.csv search_me/data/backup.csv
touch search_me/config/app.conf
chmod 755 search_me/scripts/*.sh

# Basic find
echo "  All files under search_me:"
find search_me -type f | sort | sed 's/^/    /'

echo "  Only .sh files:"
find search_me -type f -name "*.sh" | sort | sed 's/^/    /'

echo "  Only directories:"
find search_me -type d | sort | sed 's/^/    /'

echo "  Executable files:"
find search_me -type f -executable | sort | sed 's/^/    /'

# Find and act on results
echo "  Find and act:"
find search_me -type f -name "*.csv" -exec echo "    Found CSV: {}" \;

# Find with multiple conditions (AND is implicit, -o for OR)
find search_me -type f \( -name "*.sh" -o -name "*.conf" \) | sort | sed 's/^/    /'

# Find files modified in the last N minutes
find /tmp -type f -newer /tmp -mmin -60 2>/dev/null | head -3 | sed 's/^/    /'

# Find and delete old files (safe: -mtime +N = older than N days)
# find /tmp -type f -name "*.tmp" -mtime +7 -delete

# Find and process (xargs is faster than -exec for many files)
find search_me -type f -name "*.sh" | xargs chmod 644
find search_me -type f -name "*.sh" | xargs ls -la | sed 's/^/    /'

# ── DISK USAGE ──────────────────────────────────────────────
echo ""
echo "Disk usage:"

# du: disk usage of a directory
du -sh "$SANDBOX"          # -s: summary, -h: human-readable
du -sh /tmp 2>/dev/null    # /tmp total

# du sorted by size (most common pattern)
echo "  Top 3 by size in $SANDBOX:"
du -sh "$SANDBOX"/* 2>/dev/null | sort -rh | head -3 | sed 's/^/    /'

# df: free disk space
echo "  Filesystem usage:"
df -h /tmp | tail -1 | sed 's/^/    /'

# Check if disk usage exceeds a threshold
used_pct=$(df / | awk 'NR==2 {print int($5)}')
echo "  / is ${used_pct}% full"
(( used_pct > 90 )) && echo "  WARNING: disk almost full!" || echo "  OK: disk usage acceptable"

echo ""
echo "Done. Sandbox will be auto-cleaned."
