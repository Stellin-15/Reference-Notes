# ============================================================
# L04: Linux Systems Administration Fundamentals
# ============================================================
# WHAT: The core Linux system-administration knowledge every DevOps/SRE
#       engineer needs beneath the higher-level tools (Ansible, Docker,
#       Kubernetes) — systemd service management, process/resource
#       management, filesystem/disk management, and package management.
# WHY: Every tool covered elsewhere in this repo (Docker, Kubernetes,
#      Ansible) ultimately runs ON a Linux host, and debugging a
#      production incident frequently means dropping below those
#      abstractions to the actual OS-level tools — this lesson is the
#      "what to check when nothing else explains the problem" foundation.
# LEVEL: Foundation
# ============================================================

"""
CONCEPT OVERVIEW:
SYSTEMD is the init system and service manager on virtually every modern
Linux distribution — it starts services at boot, manages their
dependencies, restarts them on failure (if configured), and centralizes
their logs (via journald). A SERVICE UNIT FILE declares how a service
should run (its start command, restart policy, resource limits,
dependencies on other services) — understanding unit files is essential
for both writing new services and debugging why an existing one won't
start or keeps restarting.

PROCESS AND RESOURCE MANAGEMENT: understanding what's actually consuming
CPU/memory/IO on a host in real time (`top`/`htop`, `ps`, `iostat`,
`vmstat`) is the first diagnostic step in almost any "this server is
slow/unresponsive" incident. CGROUPS (control groups — the same
underlying kernel mechanism Docker containers use for resource isolation,
covered in this repo's Docker Notes L01) can also be used DIRECTLY to
bound a specific process's resource consumption on a non-containerized host.

FILESYSTEM AND DISK MANAGEMENT covers: understanding disk usage
(`df`, `du`) and the specific, common failure mode of a FULL DISK causing
cascading application failures (a full disk can prevent logging, writing
temp files, or even accepting new connections, depending on the
application); LVM (Logical Volume Manager) for flexible disk space
allocation across multiple physical/virtual disks; and mount points/
filesystem types relevant to understanding where data actually lives.

PACKAGE MANAGEMENT (`apt`/`dpkg` on Debian-family, `yum`/`dnf`/`rpm` on
RHEL-family) is how software gets installed/updated/removed at the OS
level — understanding dependency resolution, held/pinned package
versions (preventing an unwanted automatic upgrade), and how to
investigate exactly what version of a package is installed and where its
files live, is a frequent debugging need distinct from application-level
dependency management (Python's pip, Node's npm, etc.).

PRODUCTION USE CASE:
A service is intermittently failing to write log files — `df -h` reveals
the root filesystem is at 100% capacity, caused by an unrotated,
unbounded log file from an unrelated service on the same host filling
the disk — a diagnosis requiring exactly this OS-level toolkit
(disk usage inspection), not anything the application's own
higher-level monitoring (which was reporting request-level errors, not
their root cause) surfaced directly.

COMMON MISTAKES:
- Debugging "the service won't start" purely by staring at application
  logs without checking `systemctl status <service>` and
  `journalctl -u <service>` first — systemd's own status output
  frequently reveals the actual failure reason (a missing dependency, a
  permission error, a bad exit code) faster than digging through
  application-level logs alone.
- Not understanding the difference between DISK SPACE (`df`, whole
  filesystem usage) and a single directory's/file's size (`du`) —
  conflating these leads to either missing a full-disk problem entirely
  or wasting time investigating the wrong directory.
- Blindly running `apt-get upgrade`/`yum update` on a production system
  without understanding what's about to change — an unplanned major
  version bump of a critical dependency (a database client library, a
  language runtime) can introduce breaking changes; production systems
  typically pin/hold specific versions and upgrade deliberately, not automatically.
"""

import textwrap


# ------------------------------------------------------------------
# 1. systemd — service unit files and management commands
# ------------------------------------------------------------------
SYSTEMD_UNIT_EXAMPLE = textwrap.dedent("""\
    # /etc/systemd/system/myapp.service
    [Unit]
    Description=My Application
    After=network.target postgresql.service   # start AFTER these are up
    Requires=postgresql.service                 # a HARD dependency — if
                                                  # postgresql fails, this fails too

    [Service]
    ExecStart=/usr/bin/python3 /opt/myapp/main.py
    Restart=on-failure          # automatically restart if it exits non-zero
    RestartSec=5                 # wait 5s between restart attempts
    User=myapp                   # run as a dedicated, non-root user
    MemoryMax=2G                  # a cgroup-enforced hard memory limit
    LimitNOFILE=65536             # raise the open-file-descriptor limit

    [Install]
    WantedBy=multi-user.target    # start automatically at boot, in the
                                    # normal multi-user runlevel/target
""")

SYSTEMD_COMMANDS = textwrap.dedent("""\
    systemctl daemon-reload          # reload after editing a unit file
    systemctl start myapp
    systemctl enable myapp           # start automatically at boot
    systemctl status myapp           # THE first command to run when
                                       # "the service isn't working" —
                                       # shows current state, recent log
                                       # lines, and the exact failure reason
    journalctl -u myapp -f            # follow this service's LOGS live
    journalctl -u myapp --since "1 hour ago"
    systemctl list-units --failed     # show every service currently failed
""")

# ------------------------------------------------------------------
# 2. Process and resource inspection
# ------------------------------------------------------------------
PROCESS_INSPECTION_COMMANDS = textwrap.dedent("""\
    top / htop              # live, sorted view of CPU/memory usage per process
    ps aux --sort=-%mem      # a snapshot, sorted by memory usage descending
    ps aux --sort=-%cpu      # sorted by CPU usage descending
    iostat -x 1               # disk I/O statistics, refreshed every 1 second —
                                # reveals if disk I/O (not CPU/memory) is the
                                # actual bottleneck
    vmstat 1                   # overall system activity: CPU, memory, swap,
                                # I/O — a quick, single-glance health overview
    free -h                    # memory usage summary, human-readable units

    # cgroups — the SAME kernel mechanism Docker uses (Docker Notes L01),
    # usable directly to bound a process's resources on a non-containerized host:
    systemd-run --scope -p MemoryMax=500M my_memory_hungry_script.sh
""")

# ------------------------------------------------------------------
# 3. Disk and filesystem management
# ------------------------------------------------------------------
DISK_MANAGEMENT_COMMANDS = textwrap.dedent("""\
    df -h                      # disk usage per MOUNTED FILESYSTEM —
                                 # "is the disk full" starts here
    du -sh /var/log/*           # size of each item within a directory —
                                 # "WHAT is filling the disk" starts here
    lsblk                        # list block devices and their mount points

    # LVM (Logical Volume Manager) — flexible disk allocation across
    # physical/virtual disks, letting you EXTEND a filesystem's size
    # without reformatting, as long as the underlying volume group has
    # free space:
    lvextend -L +10G /dev/mapper/vg-data
    resize2fs /dev/mapper/vg-data   # grow the filesystem to use the new space
""")

FULL_DISK_FAILURE_MODE_NOTE = (
    "A FULL DISK is a classic, cascading production failure mode: once "
    "a filesystem hits 100%, applications can fail to write logs "
    "(sometimes CRASHING on that failure, rather than degrading "
    "gracefully), fail to write temp files, and in some database "
    "configurations, refuse new writes entirely — the actual USER-"
    "FACING symptom (a request failing) can look completely unrelated to "
    "disk space until `df -h` is checked, which is why it belongs in "
    "the FIRST few diagnostic steps for an unexplained failure, not a "
    "late-stage guess."
)

# ------------------------------------------------------------------
# 4. Package management
# ------------------------------------------------------------------
PACKAGE_MANAGEMENT_COMMANDS = textwrap.dedent("""\
    # Debian/Ubuntu family
    apt list --installed | grep nginx     # what version is installed
    apt-cache policy nginx                 # available vs installed versions
    apt-mark hold nginx                     # PIN this package — prevent it
                                              # from being upgraded by a
                                              # general `apt upgrade`
    dpkg -L nginx                            # list every FILE this package installed

    # RHEL/CentOS/Fedora family
    dnf list installed | grep nginx
    dnf versionlock add nginx                # the dnf equivalent of apt-mark hold
    rpm -ql nginx                             # list files, equivalent to dpkg -L
""")


if __name__ == "__main__":
    print(SYSTEMD_UNIT_EXAMPLE)
    print(SYSTEMD_COMMANDS)
    print(PROCESS_INSPECTION_COMMANDS)
    print(DISK_MANAGEMENT_COMMANDS)
    print(FULL_DISK_FAILURE_MODE_NOTE, "\n")
    print(PACKAGE_MANAGEMENT_COMMANDS)

"""
PRODUCTION CONTEXT EXAMPLE:
An on-call engineer investigating a service returning intermittent 500
errors runs `systemctl status myapp` first (showing it's been silently
restarting every few minutes due to an OOM-kill), then `free -h` and
`ps aux --sort=-%mem` (revealing a memory leak in a specific worker
process growing unbounded over time), narrowing the investigation from
"the whole application is broken" to "one specific process has a memory
leak, mitigated short-term by systemd's Restart=on-failure policy" within
minutes — entirely through OS-level tooling, before ever needing to dig
into application-level code or logs.
"""
