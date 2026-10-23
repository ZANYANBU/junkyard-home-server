---
layout: default
title: Junkyard Home Server
---

<div class="stats">
  <div class="stat"><div class="n good">₹0</div><div class="l">Total cost</div></div>
  <div class="stat"><div class="n">200<span style="font-size:15px"> GB</span></div><div class="l">Data recovered</div></div>
  <div class="stat"><div class="n">6</div><div class="l">Services</div></div>
  <div class="stat"><div class="n">4<span style="font-size:15px"> GB</span></div><div class="l">RAM</div></div>
  <div class="stat"><div class="n">~0.6<span style="font-size:15px"> u/day</span></div><div class="l">Electricity</div></div>
  <div class="stat"><div class="n good">100<span style="font-size:15px">%</span></div><div class="l">Uptime, 24 h</div></div>
</div>

A non-functional PC pulled from e-waste, repaired, and turned into the machine that runs my house.
It serves films to the television, reads the solar inverter every minute, filters the internet for
the family, and streams the CCTV to my phone from anywhere.

<figure class="shot">
  <img src="photos/first-boot-on-the-bench.jpeg" alt="The rebuilt PC booted to a desktop, running open on the bench">
  <figcaption>First boot — salvaged board, CPU, RAM and a repaired power supply, running open on the bench.</figcaption>
</figure>

## Why

| Problem | Product answer | What I did |
| --- | --- | --- |
| Films on the TV and on phones | NAS, or a subscription | Jellyfin on the junk PC |
| Solar underperforming, cause unknown | Vendor cloud app, owned by the installer | Read the inverter over Modbus |
| CCTV when away from home | DVR maker's cloud service | Read the DVR directly, serve it privately |
| Block adult sites for a minor | Subscription filter | AdGuard Home as the house DNS |

Four problems, four subscriptions, four companies holding my data — or one dead computer and some
documentation.

## First principles

| # | Constraint | What follows from it |
| --- | --- | --- |
| 1 | **Budget is zero** | Measure the hardware first, then pick software that fits. 4 GB of RAM rules out Docker, Immich, Nextcloud, Home Assistant. |
| 2 | **The data already exists on the LAN** | The inverter and DVR compute everything already. Vendors just prefer you reach them via their cloud. Mostly protocol archaeology, not hardware. |
| 3 | **Expose nothing** | No port forwarding, no public IP. Once you accept that, you stop needing a trusted router, static IP or certificate. |
| 4 | **Survive unattended** | Headless, unstable mains, flaky network. Every watchdog exists because that failure actually happened. |

## What it runs

| Service | Does |
| --- | --- |
| **Jellyfin** | Films to TV, phones, laptops — hardware transcoding |
| **Solar dashboard** | Reads inverter every minute; web, TV view, printable reports |
| **AdGuard Home** | House DNS — ads, trackers, adult sites |
| **Camera viewer** | Live CCTV, fetched only while someone watches |
| **Tailscale** | Private mesh access from anywhere |
| **OpenSSH** | Remote administration |

Plus three with no interface: a **CPU temperature governor**, a **network watchdog**, and a
**health logger** sampling every minute.

## Hardware

| Part | Found as | Now |
| --- | --- | --- |
| Gigabyte H110M-H | 6+ bent socket pins | Straightened, works |
| Core i3-6098P | Untested scrap | 2 cores / 4 threads |
| Mercury PSU | Swollen 450 V capacitor | Replaced, rails verified |
| 4 GB DDR4 | Salvaged | Works — and the bottleneck |
| 320 GB HDD | No partitions, presumed dead | **200 GB recovered** via [TestDisk](https://www.cgsecurity.org/wiki/TestDisk) |
| Old Wi-Fi router | Replaced, in a drawer | Access point |

<div class="gallery" markdown="0">
  <figure>
    <img src="photos/motherboard-socket.jpeg" alt="The Gigabyte H110M-H motherboard with its CPU socket exposed">
    <figcaption>Six or more bent pins in the LGA1151 socket, straightened one at a time under magnification.</figcaption>
  </figure>
  <figure>
    <img src="photos/psu-opened.jpeg" alt="The power supply opened for the capacitor replacement">
    <figcaption>The power supply opened to replace a swollen 450 V capacitor — the one genuinely dangerous step.</figcaption>
  </figure>
  <figure>
    <img src="photos/assembled-in-the-case.jpeg" alt="The parts fitted into the salvaged case, showing the Gigabyte splash screen">
    <figcaption>Assembled in the salvaged case, posting to the Gigabyte splash screen.</figcaption>
  </figure>
</div>

## Measured

| Metric | Value |
| --- | --- |
| Idle CPU, before fan fix → after | 68 °C → **38 °C** |
| Peak under load, before → after | 94 °C → **71 °C** |
| Minutes above 80 °C, 24 h | **0** |
| Free RAM, before trim → after | 0.6 GB → **2.0 GB** |
| 720p transcode speed | **14× real time** |
| Network outage, before watchdog → after | 12 min → **2.5 min** |
| Service availability, 24 h | **100%** |

## Honest limitations

| Issue | Status |
| --- | --- |
| Memory slot 2 dead | Board fault. Fix is one 8 GB stick, not two 4 GB |
| CPU cooler weak | Hit 94 °C at 17 W. Fan at full rescued it; paste wants redoing |
| Ethernet links at 100 Mbps | Gigabit card. Cable or port suspected |
| Salvaged HDD, 16 read errors | Unplugged and stored. Not trusted with any sole copy |
| **No backups** | **The weakest point. Uptime is protected; data is not.** |

## Documentation {#documentation}

<div class="cards">
<a class="card" href="docs/01-hardware-rebuild.html"><b>1 · The rebuild</b><span>Socket pins, PSU capacitor, BIOS recovery, data recovery</span></a>
<a class="card" href="docs/02-windows-on-old-hardware.html"><b>2 · Windows on old hardware</b><span>Flyby11, and cutting Windows down to fit 4 GB</span></a>
<a class="card" href="docs/03-network.html"><b>3 · The network</b><span>Old router as an access point; an ARP bug that cost a day</span></a>
<a class="card" href="docs/04-remote-access.html"><b>4 · Remote access</b><span>Tailscale, Windows OpenSSH, driving it from a Mac</span></a>
<a class="card" href="docs/05-solar-inverter.html"><b>5 · Solar inverter</b><span>Modbus TCP, the register map, what the data exposed</span></a>
<a class="card" href="docs/06-cctv.html"><b>6 · CCTV</b><span>The DVR's snapshot endpoint, served without exposing it</span></a>
<a class="card" href="docs/07-keeping-it-alive.html"><b>7 · Keeping it alive</b><span>Thermal governor, network watchdog, health logging</span></a>
<a class="card" href="docs/08-file-sharing.html"><b>8 · File sharing</b><span>Windows sharing over the private mesh</span></a>
</div>

## Code {#code}

Standard library only — no pip, no requirements.txt. A consequence of 4 GB that turned out to be a feature.

| File | What it is |
| --- | --- |
| [`cpu-temperature-governor.py`](https://github.com/{{ site.github_username }}/{{ site.repo_name }}/blob/main/code/cpu-temperature-governor.py) | Holds a badly-cooled CPU under 90 °C via Windows' processor speed limit |
| [`network-watchdog.py`](https://github.com/{{ site.github_username }}/{{ site.repo_name }}/blob/main/code/network-watchdog.py) | Recovers the network when the adapter silently stops passing traffic |
| [`read-solar-inverter.py`](https://github.com/{{ site.github_username }}/{{ site.repo_name }}/blob/main/code/read-solar-inverter.py) | Modbus TCP client in ~30 lines — `--raw` to explore, `--verify` to sanity-check |
| [`control-lg-tv.py`](https://github.com/{{ site.github_username }}/{{ site.repo_name }}/blob/main/code/control-lg-tv.py) | Drives an LG webOS TV — no cloud, no app |

[How each works, and how to install it →](code/)

## Cost

| Item | Cost |
| --- | --- |
| Board, CPU, RAM, case, cooler | ₹0 — e-waste |
| PSU capacitor | ₹0 — salvaged |
| SSD, HDD, access point | ₹0 — already owned |
| Jellyfin, AdGuard, Tailscale, Python | ₹0 — open source |
| **Total** | **₹0** |

Running cost is the only ongoing one. Measured CPU package power averages **1.7 W** at 2% load (peak 22 W);
a whole-system estimate is **20–30 W**, so roughly **0.5–0.7 units a day** — about 15–21 units a month.
Solar covers the daylight share.

> **Estimate, not measurement.** 1.7 W is the CPU package only, read from its own sensor. Board, RAM, SSD,
> fans and power-supply losses are inferred, and an old PSU is inefficient at low load. A plug-in energy
> meter would settle it; I do not have one.

## Lessons

| | |
| --- | --- |
| **Measure before optimising** | I tuned Wi-Fi channels for hours before testing the line speed. The ceiling was the internet plan. Every band gave the same ~40 Mbps. |
| **The constraint is the design** | 4 GB produced small standard-library services instead of containers. Starts in seconds, no dependency tree to rot. Better than what I'd have chosen with more memory. |
| **Your devices already talk** | Both the inverter and DVR wanted a vendor cloud. Both answer fine on the LAN, in documented protocols. |
| **Design for observed failures** | Every watchdog exists because something actually broke. I'd have predicted neither. |
| **Repair is a budget** | A swollen capacitor is ₹10 and twenty minutes. |

<hr>

<p style="color:var(--dim);font-size:14px">Built by a CS student with a soldering iron, a pile of e-waste and an objection to subscriptions.
Full write-up on <a href="https://github.com/{{ site.github_username }}/{{ site.repo_name }}">GitHub</a>.</p>
