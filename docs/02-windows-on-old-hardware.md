---
title: Windows 11 on unsupported hardware
---

Getting a modern OS onto a 2015 processor, then cutting it down to fit 4 GB of RAM.

---

## Why Windows at all

The honest answer: **it was already licensed and already working, and everything I needed runs on it.**

The original plan was TrueNAS SCALE. I abandoned it, and the reasoning is worth stating because it is the
kind of decision that is easy to get wrong when you want the interesting option:

| | TrueNAS SCALE | This machine |
| --- | --- | --- |
| RAM wanted | 8 GB minimum, ECC preferred | 4 GB, non-ECC, one working slot |
| Disks | Multiple, for a ZFS pool | One SSD |
| ZFS overhead | Substantial | No headroom for it |

TrueNAS on 4 GB with a single disk would have been a worse NAS than Windows is, and it would have given up
the hardware video transcoding that makes the media server usable on this weak a CPU.

**The boring option that fits the hardware beat the interesting option that does not.** That is a recurring
theme in this project.

---

## The compatibility problem

Windows 11 refuses to install on this machine. Three checks fail:

| Requirement | This machine |
| --- | --- |
| 8th-generation Intel or newer | **i3-6098P — 6th gen (Skylake, 2015)** |
| TPM 2.0 | Present, but older spec |
| UEFI + Secure Boot | **Legacy BIOS, MBR disk** |

The CPU requirement is the real blocker, and it is a policy decision by Microsoft rather than a technical
one. Skylake runs Windows 11 perfectly well — it simply is not on the supported list.

---

## Flyby11

**[Flyby11](https://github.com/builtbybel/Flyby11)** is an open-source tool that performs the installation
using a path Microsoft itself provides — the Windows Server installation route skips the consumer CPU and
TPM checks. It is not a crack or a patch; it is a documented alternative installer behaviour.

Result: **Windows 11 Pro 24H2, build 26100**, running on a 2015 processor in legacy BIOS mode.

### What you should know before doing this

- **Updates keep working.** This machine has taken cumulative updates normally, including a security update
  during the test period.
- **Microsoft does not support this configuration.** It reserves the right to withhold updates from
  unsupported hardware. It has not so far, but that is not a guarantee.
- **Do not convert to UEFI afterwards.** This disk is MBR and the firmware is in legacy mode. Switching the
  BIOS to UEFI-only will stop Windows booting. I have left `CSM` alone deliberately.
- **Windows 10's end of support is what makes this worth doing.** Staying on an OS that no longer gets
  security patches, on a machine that runs the house DNS, was the worse option.

---

## Cutting Windows down to fit 4 GB

A default Windows 11 install uses most of 4 GB before you run anything. A headless server does not need
almost any of it.

### Services disabled

Each of these is unnecessary on a machine with no user sitting at it:

| Service | Why it goes |
| --- | --- |
| `WSearch` | Search indexing — nobody is searching |
| `SysMain` | Prefetch for apps that never launch |
| `DiagTrack` | Telemetry |
| Xbox services (4) | No games |
| `Audiosrv`, `AudioEndpointBuilder` | No sound hardware in use |
| `Spooler` | No printing |
| `StiSvc` | No scanner |
| `WerSvc`, `DPS`, `WdiSystemHost` | Diagnostics and error reporting |
| `upnphost`, `SSDPSRV`, `FDResPub` | Network discovery |
| `MapsBroker`, `RetailDemo`, `Fax` | Self-explanatory |

Recorded before/after in a CSV so any of it can be reversed.

### Features and apps removed

- Hyper-V, Virtual Machine Platform, WSL (and the hypervisor launch type set off — it reserves memory even
  when idle)
- Xbox overlays, Widgets, Phone Link, Cross-Device, Mail
- Teams removed from startup
- Policies set for: no background apps, no Widgets, no Copilot, no Edge startup boost

### Power settings

- **Never sleep**, hibernate off, Fast Startup off (it interferes with clean reboots on a headless box)
- Core parking disabled, so both cores stay available
- `DVMT` graphics memory reduced to 32 MB in the BIOS — it is carved out of system RAM, and the driver
  allocates more on demand anyway. This alone returned a meaningful slice of the 4 GB.

### The sign-in session

This one surprised me. **A signed-in desktop session costs around 1 GB** — Explorer, the Start menu,
SearchHost and its WebView2 helpers, the window manager.

A headless server should sit at the sign-in screen with nobody logged in. Every service runs as `SYSTEM` at
boot and does not care. There is a scheduled task that signs out any console session appearing within five
minutes of boot, to catch Windows' "use my sign-in info after restart" behaviour.

### Result

| | Memory free |
| --- | --- |
| Before | ~0.6 GB |
| After | **~2.0 GB of 3.9 GB** |

With everything running — media server, DNS filter, solar collector, camera viewer, Tailscale, Defender.

**Defender stays.** This machine answers DNS for the whole house and has SSH open. Trading away its antivirus
to reclaim 270 MB would be a bad bargain.

---

## Hardware video transcoding

The Intel HD 530 integrated graphics does hardware H.264/HEVC decode and encode (QuickSync). This is what
makes a 2-core CPU viable as a media server.

Configured for what this specific chip can do:
- Hardware decode: H.264, HEVC 8-bit, MPEG-2, VC-1
- **Not** 10-bit HEVC, VP9 or AV1 — Skylake-era graphics cannot, and enabling them causes silent fallback to
  software and a pegged CPU
- Software fallback limited to 2 threads so a transcode cannot starve everything else

**Measured: 60 seconds of 720p transcoded in 4.2 seconds — about 14× real time — with the CPU at 50 °C.**
Comfortably enough for several simultaneous streams, on a processor that would struggle to do one in
software.

---

**Next:** [The network →](03-network.md)
