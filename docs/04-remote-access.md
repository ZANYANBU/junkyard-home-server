---
title: Remote access
---

Reaching a headless Windows machine from anywhere, without opening a single port.

---

## The rule

**Nothing is exposed to the internet.** No port forwarding, no public IP, no dynamic DNS, no reverse proxy
with a certificate. Not one service listens where a stranger can reach it.

This is not excessive caution. The DVR firmware is old and unauditable. The media server holds family
photographs. I am one person and I will not reliably keep a public-facing service patched. The honest
assessment is that I *cannot* secure an exposed service properly — so I do not expose one.

Accepting that constraint makes everything downstream simpler.

---

## Tailscale: the private mesh

[Tailscale](https://tailscale.com) builds an encrypted private network (a WireGuard mesh) between your own
devices. Each gets a stable address in the `100.64.0.0/10` range that works from anywhere.

**Why it fits this project:**

- **Free** for personal use, well within the device limit
- **No port forwarding.** Devices connect outward and meet in the middle, so it works behind the ISP's NAT
  with no router configuration at all
- **Stable addresses.** The server's mesh address never changes, regardless of what the ISP does to the
  public IP
- **Cryptographic identity.** Only devices signed into my account can connect. There is no password to
  guess and no open port to scan
- **Direct when possible.** It negotiates a direct peer-to-peer path and only falls back to a relay when the
  network blocks it

**Measured:** from a different city, 21 ms over a direct IPv6 path. When direct negotiation failed it fell
back to a relay automatically — slower, but it kept working without intervention.

### Configuration that matters

- **Unattended mode** — connects at boot with nobody signed in. Essential on a headless machine.
- **Accept-routes off.** This one bit me. A stale device on the account was advertising a route for
  `192.168.10.0/24`, and the client accepted it by default — which broke the server's access to its *own
  local network*. Symptoms were bizarre and took a while to trace. Unless you are deliberately using subnet
  routing, turn it off.
- **Key expiry disabled** for the server, so it does not drop off the mesh months later while nobody is
  watching.

---

## Windows OpenSSH

Windows 10 and 11 ship an OpenSSH server. It is not installed by default, but it is Microsoft's own build
and it integrates with Windows properly.

### Installing it

The usual route is Settings → Optional Features → OpenSSH Server. **On this machine that hung for about 40
minutes** before eventually completing.

The reliable alternative is the MSI from Microsoft's [Win32-OpenSSH
releases](https://github.com/PowerShell/Win32-OpenSSH/releases). If you take that route, **verify it before
installing**: check the SHA-256 against the published checksum, and confirm the Authenticode signature is
valid and signed by Microsoft. A setup script that downloads and installs an MSI without verifying it is a
supply-chain problem waiting to happen.

### Key-based authentication

Passwords are disabled; only keys work.

**The Windows-specific trap:** for accounts in the Administrators group, Windows OpenSSH does **not** read
`~/.ssh/authorized_keys`. It reads a single shared file:

```
C:\ProgramData\ssh\administrators_authorized_keys
```

And it is strict about permissions. The file must grant access only to `Administrators` and `SYSTEM`, with
inheritance disabled:

```powershell
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
```

If the permissions are wrong, sshd silently ignores the file and you will be debugging an authentication
failure that gives no useful error.

### Firewall

The SSH rule allows **only** the home subnet and the Tailscale range:

```powershell
New-NetFirewallRule -Name OpenSSH-Server-In-TCP -DisplayName 'OpenSSH Server' `
  -Direction Inbound -Protocol TCP -LocalPort 22 -Profile Private `
  -RemoteAddress 192.168.10.0/24,100.64.0.0/10 -Action Allow
```

Every service follows the same pattern — media server, DNS, dashboard, cameras. Private profile, two address
ranges, nothing else.

---

## Driving the server from a Mac

A small shell script runs PowerShell on the server over SSH, reading the script from standard input:

```bash
#!/bin/bash
# Run a PowerShell script (from stdin) on the home server over SSH.
script="\$ProgressPreference = 'SilentlyContinue'
$(cat)"
b64=$(printf '%s' "$script" | iconv -f UTF-8 -t UTF-16LE | base64 | tr -d '\n')

# Home address first; fall back to the mesh address when away.
host=192.168.10.200
nc -z -G 3 "$host" 22 >/dev/null 2>&1 || host=<tailscale-address>

ssh -o BatchMode=yes -o ConnectTimeout=10 "user@$host" \
    "powershell -NoProfile -NonInteractive -EncodedCommand $b64"
```

Used as:

```bash
./pc.sh <<'EOF'
Get-Service AdGuardHome, Tailscale | Format-Table Name, Status
EOF
```

**Why the base64 encoding:** PowerShell's `-EncodedCommand` takes UTF-16LE base64. Passing a script this way
avoids every layer of quoting and escaping between bash, ssh and PowerShell. Without it, anything containing
`$`, quotes or newlines gets mangled — and the failures are confusing because the script arrives subtly
altered rather than obviously broken.

**The limit:** Windows caps the command line at roughly 32,000 characters, so a long script exceeds what
`-EncodedCommand` can carry. For those, copy the file over with `scp` and run it with `-File` instead.

**The fallback line is what makes it work from anywhere.** It tries the LAN address first (fast, direct) and
silently switches to the mesh address when away from home. The same command works from the next room or
another city.

---

**Next:** [Reading the solar inverter →](05-solar-inverter.md)
