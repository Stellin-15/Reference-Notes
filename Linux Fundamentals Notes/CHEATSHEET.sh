#!/usr/bin/env bash
# =============================================================================
# LINUX FUNDAMENTALS CHEATSHEET
# A fast reference for everyday Linux usage: filesystem, permissions,
# processes, users, package management, networking, and text processing.
# Every command below is safe to read top-to-bottom; run individually, not
# as a script.
# =============================================================================


# =============================================================================
# 1. FILESYSTEM NAVIGATION
# =============================================================================

pwd                         # Print working directory
ls -la                      # List all files, long format, including hidden
ls -lh                      # Human-readable sizes (K/M/G)
cd /path/to/dir             # Change directory
cd -                        # Go back to previous directory
cd ~                        # Go to home directory

mkdir -p a/b/c              # Create nested directories (no error if exists)
rmdir empty_dir             # Remove empty directory
rm file.txt                 # Remove a file
rm -r dir/                  # Remove directory recursively
rm -rf dir/                 # Force remove, no confirmation (DANGEROUS)

cp file.txt backup.txt      # Copy file
cp -r src/ dst/              # Copy directory recursively
mv old.txt new.txt          # Rename/move file
touch newfile.txt           # Create empty file / update timestamp

find . -name "*.log"        # Find files by name pattern
find . -type f -mtime -1     # Files modified in the last day
find . -size +100M           # Files larger than 100MB
find . -type f -exec rm {} \;  # Find and delete matching files

tree -L 2                   # Show directory tree, 2 levels deep
du -sh *                    # Disk usage per item in current dir
df -h                       # Disk free space, human-readable
readlink -f file.txt        # Resolve symlink to absolute path
ln -s /path/target linkname # Create a symbolic link


# =============================================================================
# 2. PERMISSIONS & OWNERSHIP
# =============================================================================

# Permission triplet: rwx for owner, group, other (e.g. rwxr-xr--)
# r=4, w=2, x=1 — sum digits per group: rwxr-xr-- = 754

chmod 755 script.sh          # rwxr-xr-x — common for executables
chmod 644 file.txt           # rw-r--r-- — common for regular files
chmod +x script.sh           # Add execute permission
chmod -R 755 dir/             # Recursive chmod

chown user:group file.txt    # Change owner and group
chown -R user:group dir/     # Recursive ownership change

umask                        # Show default permission mask for new files
sudo command                 # Run as root (one-off)
sudo -i                      # Interactive root shell
su - username                # Switch user (full login environment)


# =============================================================================
# 3. PROCESSES & JOBS
# =============================================================================

ps aux                        # List all running processes
ps aux | grep nginx           # Find a specific process
top                           # Live process/resource monitor
htop                          # Improved interactive process monitor

kill PID                      # Send SIGTERM (graceful stop) to a process
kill -9 PID                   # Send SIGKILL (force kill)
killall process_name          # Kill all processes matching a name
pkill -f "pattern"             # Kill processes matching a command-line pattern

command &                     # Run command in background
jobs                          # List background jobs in current shell
fg %1                         # Bring job 1 to foreground
bg %1                         # Resume job 1 in background
nohup command &                # Run immune to hangup (survives shell exit)
disown                        # Detach a job from the current shell

nice -n 10 command             # Run with lower CPU priority
renice 10 -p PID                # Change priority of a running process

# systemd service management
systemctl status nginx         # Check service status
systemctl start|stop|restart nginx
systemctl enable nginx         # Enable on boot
systemctl daemon-reload        # Reload unit files after editing
journalctl -u nginx -f          # Follow logs for a service
journalctl -xe                  # Recent logs with explanations


# =============================================================================
# 4. USERS & GROUPS
# =============================================================================

whoami                        # Current user
id                             # UID, GID, group memberships
useradd -m -s /bin/bash alice   # Create user with home dir + bash shell
passwd alice                   # Set/change password
usermod -aG sudo alice          # Add user to sudo group
deluser alice                  # Remove a user
groups alice                   # List groups a user belongs to
cat /etc/passwd                # List all users
cat /etc/group                 # List all groups


# =============================================================================
# 5. PACKAGE MANAGEMENT
# =============================================================================

# Debian/Ubuntu (apt)
sudo apt update                  # Refresh package index
sudo apt upgrade                 # Upgrade installed packages
sudo apt install package_name     # Install a package
sudo apt remove package_name      # Remove a package
apt list --installed              # List installed packages

# RHEL/CentOS/Fedora (dnf/yum)
sudo dnf install package_name
sudo dnf update
sudo dnf remove package_name

# Universal
which command_name               # Show path of a command
command -v command_name           # POSIX-portable alternative to `which`


# =============================================================================
# 6. NETWORKING
# =============================================================================

ip a                            # Show all network interfaces + IPs
ip route                        # Show routing table
hostname -I                     # Show local IP addresses

ping host                       # Test reachability
curl -I https://example.com      # Fetch headers only
curl -s https://example.com/api   # Fetch body silently
curl -X POST -d '{"k":"v"}' -H "Content-Type: application/json" url
wget https://example.com/file.zip # Download a file

ss -tulpn                        # List listening ports (modern netstat)
netstat -tulpn                    # Legacy equivalent
lsof -i :8080                     # Find process using a port

dig example.com                   # DNS lookup (detailed)
nslookup example.com               # DNS lookup (simple)
traceroute example.com             # Trace network path to host

ssh user@host                      # Connect via SSH
ssh -i key.pem user@host            # Connect using a specific key
scp file.txt user@host:/remote/path # Copy file over SSH
rsync -avz src/ user@host:/dst/      # Efficient sync (archive, verbose, compress)


# =============================================================================
# 7. TEXT PROCESSING & PIPES
# =============================================================================

cat file.txt                     # Print file contents
head -n 20 file.txt                # First 20 lines
tail -n 20 file.txt                 # Last 20 lines
tail -f file.log                    # Follow a growing file (live logs)

grep "error" file.log                # Find matching lines
grep -i "error" file.log              # Case-insensitive
grep -r "TODO" src/                    # Recursive search in directory
grep -v "debug" file.log                # Invert match (exclude lines)
grep -c "error" file.log                 # Count matches

sed 's/foo/bar/' file.txt                 # Replace first match per line
sed 's/foo/bar/g' file.txt                 # Replace all matches per line
sed -i 's/foo/bar/g' file.txt               # Edit file in place

awk '{print $1}' file.txt                   # Print first column
awk -F',' '{print $2}' file.csv               # Custom delimiter
awk '$3 > 100 {print $0}' file.txt             # Filter rows by condition

sort file.txt                                 # Sort lines alphabetically
sort -n file.txt                                # Numeric sort
sort -r file.txt                                # Reverse sort
uniq file.txt                                   # Remove adjacent duplicates
sort file.txt | uniq -c                          # Count occurrences

wc -l file.txt                                   # Count lines
cut -d',' -f1,3 file.csv                          # Extract columns 1 and 3
tr 'a-z' 'A-Z' < file.txt                          # Translate lowercase to uppercase

command1 | command2                                # Pipe: chain commands
command > out.txt                                   # Redirect stdout (overwrite)
command >> out.txt                                   # Redirect stdout (append)
command 2> err.txt                                    # Redirect stderr
command > out.txt 2>&1                                 # Redirect both to same file
command < input.txt                                    # Redirect stdin from file


# =============================================================================
# 8. ENVIRONMENT & SHELL
# =============================================================================

env                             # List all environment variables
export VAR=value                 # Set an environment variable for this shell
echo $VAR                         # Print a variable's value
alias ll='ls -la'                  # Create a shortcut command
history | grep ssh                  # Search command history
!123                                # Re-run history entry #123
source ~/.bashrc                     # Reload shell config

df -h                                 # Disk usage
free -h                                # Memory usage
uname -a                                # Kernel/system info
uptime                                  # System uptime + load average
