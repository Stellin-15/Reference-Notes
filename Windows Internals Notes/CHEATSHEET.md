# Windows Internals — In-Depth Reference

The Windows-side parallel to Linux Fundamentals Notes — essential for
enterprise IT, security (a huge fraction of Active Directory attacks
target Windows internals — see Ethical Hacking Notes), and Windows Server administration.


## 1. THE WINDOWS ARCHITECTURE, BRIEFLY

Windows separates USER MODE (applications, most services) from KERNEL
MODE (the NT kernel, drivers) — analogous to the Linux user/kernel
boundary, but Windows's kernel architecture (a hybrid kernel, with
significant subsystems like the Win32 subsystem historically running in
kernel mode for performance) has real, distinct history from Linux's
monolithic kernel design. The **Windows Registry** — a hierarchical
database (`HKEY_LOCAL_MACHINE`, `HKEY_CURRENT_USER`, etc.) storing system
and application configuration — has no direct Linux equivalent (Linux
config is scattered across `/etc` text files); understanding registry
hives/keys is genuinely necessary for Windows systems administration and troubleshooting.


## 2. PROCESSES, SERVICES & THE TASK SCHEDULER

```powershell
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10  # Top CPU consumers
Get-Service | Where-Object {$_.Status -eq "Running"}                    # Running services
Start-Service -Name "ServiceName"                                          # Start a service
Set-Service -Name "ServiceName" -StartupType Automatic                       # Configure startup behavior

# Scheduled Tasks — Windows's equivalent of cron
Get-ScheduledTask | Where-Object {$_.State -eq "Ready"}
Register-ScheduledTask -TaskName "Backup" -Trigger $trigger -Action $action
```

**Windows Services** run as background processes managed by the Service
Control Manager (SCM) — the closest Windows equivalent to a systemd
service (see Linux Fundamentals Notes), with their own start/stop/
recovery configuration, running under specific service accounts (LocalSystem,
NetworkService, or a dedicated domain service account) — the service
account's PRIVILEGES are a genuinely common security review point,
since an overprivileged service account is a real, common
privilege-escalation target (see Ethical Hacking Notes' Active Directory section).


## 3. ACTIVE DIRECTORY & GROUP POLICY — THE ENTERPRISE CORE

Active Directory (AD) is the centralized directory service almost every
mid-to-large enterprise runs — see Identity & Access Management Notes for
the protocol-level (LDAP/Kerberos) depth, and Ethical Hacking Fundamentals
Notes section 13 for the attack techniques that target it directly.
**Group Policy Objects (GPOs)** are how AD pushes CONFIGURATION (password
policy, software restrictions, drive mappings, security settings) to
every joined machine/user centrally — genuinely the primary mechanism
enterprise IT uses to enforce baseline security configuration at scale,
the Windows-world parallel to Ansible/Puppet's configuration management
(see DevOps & SRE Practices Notes) but Microsoft-ecosystem-native and identity-integrated.


## 4. POWERSHELL — THE ADMINISTRATION LANGUAGE

Unlike bash (text-stream-based), PowerShell pipes actual OBJECTS between
commands — `Get-Process | Where-Object {$_.CPU -gt 100}` filters on the
CPU property of actual Process OBJECTS, not a text-parsed column,
eliminating an entire class of fragile text-parsing bugs bash scripts
are prone to (see Bash & Scripting Notes' quoting/parsing pitfalls for the contrast).

```powershell
# PowerShell Remoting — running commands on remote machines (like SSH, but WinRM-based)
Invoke-Command -ComputerName Server01 -ScriptBlock { Get-Service }
Enter-PSSession -ComputerName Server01                    # Interactive remote session

# DSC (Desired State Configuration) — PowerShell's own config-management framework
Configuration WebServerConfig {
    Node "Server01" {
        WindowsFeature IIS { Ensure = "Present"; Name = "Web-Server" }
    }
}
```


## 5. NICHE BUT REAL

- **WMI (Windows Management Instrumentation)** — the underlying management
  framework PowerShell's `Get-CimInstance`/`Get-WmiObject` query — a real,
  historically significant Windows systems-management API, and notably a
  common LATERAL MOVEMENT technique in Windows-focused penetration testing
  (WMI can execute commands remotely, similar to `psexec`, see Ethical
  Hacking Notes section 13).
- **Event Viewer & Windows Event Logs** — the Windows equivalent of
  syslog/journald; Security, System, and Application logs are the
  standard first place to check for both troubleshooting AND security
  incident investigation (failed logon events, Event ID 4625, are a
  classic first signal of a brute-force attempt).
- **NTFS permissions & ACLs** — genuinely more granular than traditional
  Unix rwx permissions (explicit Allow/Deny entries per user/group, with
  inheritance rules) — `icacls`/`Get-Acl` are the CLI tools; a common
  real misconfiguration is an inherited Deny rule silently overriding an
  otherwise-correct Allow, a genuinely non-obvious NTFS behavior worth knowing.
- **Windows Server container support & WSL2** — Windows Server can run
  Windows-native containers (not just Linux containers via a VM); WSL2
  (Windows Subsystem for Linux, running a real lightweight Linux VM) is
  now the standard way most Windows-based developers run Linux tooling
  locally — worth knowing WSL2's architecture (an actual Hyper-V-based
  Linux VM, not a compatibility shim like the original WSL1) explains why WSL2 supports Docker natively while WSL1 could not.
- **BitLocker & Credential Guard** — Windows's native disk encryption and
  credential-isolation (VBS/virtualization-based-security, isolating LSASS
  credential material even from a compromised kernel) — the Windows-
  ecosystem answer to some of the exact Mimikatz-style credential-theft
  attacks covered in Ethical Hacking Fundamentals Notes section 13, worth
  knowing as the DEFENSIVE counterpart to that offensive material.
