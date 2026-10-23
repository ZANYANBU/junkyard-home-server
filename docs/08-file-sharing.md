# 8. File sharing

Reaching the server's files from any device, at home or away — without a NAS.

---

## What this replaces

The original plan was TrueNAS with a ZFS pool. On 4 GB of RAM and a single disk, that was never going to
work well. What was actually needed was simpler: **shared folders, reachable from anywhere, visible to
phones and laptops.**

Windows already does this. Combined with the private mesh, it does it from anywhere.

---

## Windows sharing over the mesh

Windows file sharing (SMB) normally works only on the local network. Carry a laptop elsewhere and the shares
vanish.

**The mesh changes that.** Because every device gets a stable private address that works from anywhere, a
share reached by that address works from anywhere too:

```
\\100.x.x.x\ShareName          # Windows
smb://100.x.x.x/ShareName      # macOS
```

Same credentials, same share, from the next room or another city. **No port forwarding, nothing exposed.**

> **SMB must never be exposed to the internet directly.** Port 445 is among the most-attacked ports there is
> — it is how ransomware has spread repeatedly. Inside an encrypted mesh with cryptographic device identity
> it is fine. On a public IP it is negligence. There is no middle position worth taking.

---

## Getting the permissions right

Windows has **two** layers of permission, and both apply. Getting one right and the other wrong is the usual
cause of "it says I have access but I cannot open anything".

| Layer | Set where | Governs |
| --- | --- | --- |
| **Share permissions** | Right-click → Sharing | Who may connect over the network |
| **NTFS permissions** | Right-click → Security | Who may read the files at all |

**The effective permission is the more restrictive of the two.**

A share set to `Everyone: Full Control` sounds alarming but is harmless if the NTFS permissions underneath
only allow specific accounts — which is exactly what happens by default on a user's folder.

> **Verified rather than assumed.** Connecting as a guest from another machine listed the share names but
> could not open anything inside: NTFS blocked it. That is the layering working. It is still worth checking
> yourself rather than trusting the theory — an actual guest connection attempt takes thirty seconds.

### Hygiene worth doing

- **Disable the Guest account** — `net user Guest /active:no`. An enabled, password-less Guest account is a
  standing invitation if a share is ever loosened.
- **Remove shares you do not use.** This machine had an old `Users` share covering the entire user directory,
  from an earlier configuration. `net share Users /delete` stops sharing it without touching any files.
- **Share the narrowest folder that works**, not its parent.
- **Check the administrative shares** (`C$`, `ADMIN$`). They need administrator credentials, which is
  reasonable, but know they exist.

---

## What is actually shared

| Share | Contents | Who |
| --- | --- | --- |
| Media | Films, served to the TV and phones | Family, via the media server |
| Rescued data | Photographs recovered from the salvaged disk | Administrator only |
| Tools | Utilities kept on the server | Administrator only |

The media is reached through the **media server** rather than the file share for everyday use — it handles
transcoding, resuming, and works on the television, which cannot mount an SMB share usefully.

**The file share is for administration**, not for daily viewing. That distinction keeps the share surface
small.

---

## Alternatives considered

| Option | Why not |
| --- | --- |
| **TrueNAS / ZFS** | Wants 8 GB RAM and multiple disks. One SSD, 4 GB. |
| **Nextcloud** | A web stack and a database for what SMB already does natively |
| **Syncthing** | Genuinely good, and still on the roadmap — but it is *sync*, not *shared storage* |
| **Samba on Linux** | Would mean giving up the hardware transcoding that makes the media server viable |

**Windows sharing was already present, already understood, and cost nothing to enable.** The project is full
of decisions like this one: the question is never "what is best in the abstract", it is "what works on 4 GB
of RAM at a cost of zero".

---

## The honest gap

**There are no backups yet.**

Shared storage is not a backup. The recovered family photographs sit on a single SSD with no second copy. If
that drive fails, they are gone a second time — and the original disk they came from already reports read
errors.

This is the single most important unfinished item in the project, and it is next on the roadmap. Everything
in [keeping it alive](07-keeping-it-alive.md) protects *uptime*. Nothing yet protects *data*.

Worth stating plainly rather than leaving someone to infer that a server implies safety. It does not.

---

**Back to:** [README →](../README.md)
