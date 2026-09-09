# Mac Basics — Principal Engineer Deep Dive

Companion to the existing lessons. Narrative depth, then a comprehensive
common-to-uncommon reference for engineers using macOS as a daily dev machine.


## macOS as a Unix — What's the Same and What Genuinely Differs

**Beyond the lesson**: macOS is a genuine, certified Unix (Darwin, built
on a BSD-derived kernel with Mach microkernel components) — most POSIX
tools/shell knowledge (see Linux Fundamentals Notes) transfers directly.
The real gotchas engineers hit: macOS's BSD-flavored core utilities have
DIFFERENT flags than Linux's GNU coreutils for the same commands (`sed -i
''` requires an explicit empty string argument on macOS/BSD sed, but not
on Linux/GNU sed — a genuinely common cross-platform shell script bug),
and the default shell changed from bash to `zsh` (Catalina, 2019)
specifically because bash's license (GPLv3) was incompatible with
Apple's distribution preferences, not a technical decision.

**Worked example**: Homebrew's role as THE de facto package manager
(unlike Linux distros, macOS ships with no first-party package manager
comparable to `apt`/`dnf`) — worth knowing Homebrew installs to
`/opt/homebrew` on Apple Silicon vs `/usr/local` on Intel Macs, a real
source of "why can't this script find the binary" confusion when
following instructions written before Apple Silicon's PATH convention shifted.

**Interview Q&A**:
- *Q: A shell script that works on a Linux CI runner fails on a developer's Mac. What's a likely first thing to check?* A: BSD vs GNU utility flag differences (`sed`, `grep -P`, `date` formatting flags all differ meaningfully between BSD/macOS and GNU/Linux versions) — installing GNU coreutils via Homebrew (`brew install coreutils` and using the `g`-prefixed commands, or adjusting PATH) is the standard fix for scripts that need to run identically on both.


## Apple Silicon & Rosetta 2 — What Actually Changed for Developers

**Beyond the lesson**: The Intel-to-ARM (Apple Silicon/M-series)
transition wasn't just "faster chips" for engineering workflows — it
meant every compiled dependency (native Node modules, Python C
extensions, Docker base images) needed an ARM64 build, and for years
after the transition, missing ARM builds of niche dependencies were a
real, recurring "why won't this install" friction point. Rosetta 2
(Apple's binary translation layer) runs unmodified x86_64 binaries via
JIT translation, genuinely fast for most workloads, but NOT a substitute
for native ARM builds of anything performance-sensitive or long-running (translation overhead compounds).

**Interview Q&A**:
- *Q: A Docker image built and tested on an Apple Silicon Mac fails when deployed to a standard x86_64 cloud VM. Why?* A: The image was built for `linux/arm64` by default on Apple Silicon unless explicitly cross-compiled — `docker build --platform linux/amd64` (or a `buildx` multi-arch build, see Docker Notes deep dive section 16) is required to produce an image that actually runs on typical x86_64 cloud infrastructure.


## COMPREHENSIVE REFERENCE — COMMON TO UNCOMMON

### Developer environment setup
- **Homebrew** — the standard package manager; `brew bundle` (a
  `Brewfile`) lets a team version-control and reproduce an entire dev
  machine's installed tools/apps declaratively, genuinely useful for
  onboarding consistency.
- **Xcode Command Line Tools** — the minimal compiler toolchain (clang,
  git, make) many other tools (Homebrew itself, native npm module
  compilation) silently depend on — a common "why is this failing to
  build" root cause on a freshly reset machine that skipped this step.
- **mise / asdf** — version managers for MULTIPLE language runtimes
  (Node, Python, Ruby, Go) in one consistent tool, rather than a separate
  version manager per language (nvm, pyenv, rbenv individually) — `mise`
  specifically has gained traction as a faster, Rust-based alternative to `asdf`.

### System internals worth knowing
- **launchd** — macOS's init system/service manager (the actual
  equivalent of Linux's systemd) — background daemons/agents are
  configured via `.plist` files in specific LaunchAgents/LaunchDaemons
  directories, the mechanism underneath anything that needs to "start automatically" on macOS.
- **Spotlight/mdfind indexing** — can cause real, noticeable I/O
  contention on large repos/node_modules directories if not excluded via
  Spotlight privacy settings — a genuine, common "why is my machine
  churning disk for no reason after a big npm install" cause.
- **Gatekeeper & code signing** — macOS blocks execution of unsigned/
  unnotarized binaries by default (`xattr -d com.apple.quarantine` is the
  common workaround for a downloaded, unsigned dev tool) — a real,
  frequent friction point when installing internal/unsigned tooling.

### Virtualization & containers on macOS
- **Docker Desktop** runs containers inside a LIGHTWEIGHT LINUX VM on
  macOS (containers are a Linux-kernel concept; macOS has no native
  container support) — this is why container resource limits/file-sharing
  performance on macOS have real, structural overhead Linux-native Docker doesn't have.
- **UTM / Parallels / VMware Fusion** — full virtualization options,
  Apple Silicon's built-in Virtualization.framework (which UTM/Docker
  Desktop use under the hood) enabling reasonably efficient ARM Linux VMs
  natively on Apple Silicon.


## NICHE BUT REAL

- **The `.DS_Store` file nuisance** — macOS silently creates these
  metadata files in every browsed directory; committing them to a shared
  Git repo is a common, avoidable annoyance (a global `.gitignore` entry
  is the standard fix, see Git & GitHub Notes) — genuinely one of the
  first things a cross-platform team notices about a Mac-using teammate's commits.
- **Keychain Access** — macOS's system-level credential store; many CLI
  tools (git credential helpers, cloud CLIs) integrate with it directly,
  worth knowing as the underlying mechanism when a tool claims to
  "remember" a password without an obvious config file storing it in plaintext.
- **Little Snitch / network monitoring tools** — third-party outbound
  firewall tools genuinely useful for a security-conscious engineer
  wanting visibility into what installed tools are actually phoning home to.
- **System Integrity Protection (SIP)** — a kernel-level protection
  preventing even root from modifying certain system files/directories —
  the reason some low-level debugging/instrumentation tools require
  explicitly disabling SIP (a real, deliberate security tradeoff, not
  just an obstacle) to function on modern macOS.
