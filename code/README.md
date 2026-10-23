---
title: Code
---

The working pieces, as they actually run on the server. Standard library only — no pip, no
`requirements.txt`, no virtualenv. That is a consequence of having 4 GB of RAM, and it turned out to be a
feature: nothing to install, nothing to update, nothing to rot.

| File | What it is | Runs on |
| --- | --- | --- |
| [`cpu-temperature-governor.py`](cpu-temperature-governor.py) | Keeps a badly-cooled CPU below 90 °C by moving Windows' processor speed limit | Windows |
| [`network-watchdog.py`](network-watchdog.py) | Recovers the network when the adapter silently stops passing traffic | Windows |
| [`read-solar-inverter.py`](read-solar-inverter.py) | Reads a grid-tied inverter over Modbus TCP | Any OS |
| [`control-lg-tv.py`](control-lg-tv.py) | Drives an LG webOS television from the server — no cloud, no app | Any OS |

Addresses in these files are illustrative. Change them to suit your network.

---

## cpu-temperature-governor.py

**The problem it solves:** after reassembly this CPU hit 89–94 °C while drawing only 17 W. Thermal throttling
would protect the silicon, but a machine sitting at 95 °C all day will not last, and the proper fix —
remounting the cooler — was not possible with the machine in another city.

**What it does:** reads the hottest core every 3 seconds and adjusts Windows' *maximum processor state* — the
same percentage the power plan exposes, driven dynamically.

| Temperature | Response |
| --- | --- |
| ≥ 92 °C | Suspend video transcoding until back under 80 °C |
| ≥ 85 °C | Straight to the floor (30%), heavy background jobs to idle priority |
| ≥ 80 °C | Step down 10% every 9 s |
| ≤ 70 °C for 30 s | Step up 5%, ceiling 85% |
| No reading | 50%, then the floor after a minute, and restart the sensor |

### Reading the temperature

Windows exposes no CPU core temperature through any normal API. This reads
**[Core Temp](https://www.alcpu.com/CoreTemp/)**'s shared memory block directly via `ctypes`:

```python
h = k32.OpenFileMappingW(FILE_MAP_READ, False, "CoreTempMappingObject")
p = k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)

core_count = ctypes.c_uint32.from_address(p + 1536).value
tj_max     = ctypes.c_uint32.from_address(p + 1024).value
is_delta   = ctypes.c_ubyte.from_address(p + 2685).value   # some CPUs report distance from TjMax
temps      = [ctypes.c_float.from_address(p + 1544 + 4*i).value for i in range(core_count)]
if is_delta:
    temps = [tj_max - t for t in temps]
```

Those offsets come from Core Temp's published shared-memory layout.

**The trap:** the mapping is readable only by `SYSTEM`. The same code over SSH gives "access denied" with no
hint why. Both Core Temp and this governor must run as scheduled tasks under `SYSTEM`.

### Installing

Core Temp must be running first, also as `SYSTEM`:

```powershell
# Core Temp at boot, as SYSTEM, so its shared memory is readable
$sys = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'Core Temp' `
  -Action (New-ScheduledTaskAction -Execute 'C:\Program Files\Core Temp\Core Temp.exe') `
  -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $sys -Force

# The governor itself, restarting if it ever stops
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
         -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName 'CPU temperature governor' `
  -Action (New-ScheduledTaskAction -Execute 'C:\python312\python.exe' `
           -Argument 'C:\thermal\cpu-temperature-governor.py' -WorkingDirectory 'C:\thermal') `
  -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $set -Principal $sys -Force
```

Check it is reading correctly before trusting it:

```
python cpu-temperature-governor.py --once
{"cpu_c": 38.5}
```

### Output

- `state.json` — current temperature, limit, today's peak, last 50 events
- `thermal-YYYY-MM.csv` — one sample a minute, plus every action taken

### Tuning

Edit the constants at the top. `CEILING` is the most useful: raise it once the cooling is fixed. `FLOOR` of
30% is roughly 1.1 GHz on this CPU — still enough to serve media and DNS.

> **A Windows quirk worth knowing:** the state file is written to a temp name and renamed. On Windows,
> renaming over a file another process has open fails with `PermissionError`. The write retries five times at
> 200 ms. On Linux the atomic rename would simply have worked.

---

## network-watchdog.py

**The problem it solves:** twice the machine kept running, kept its cable link, and silently stopped passing
traffic — no link-down event, no driver error. The first outage lasted 12 minutes because nothing but time
recovered it.

**What it does:**

| Condition | Response |
| --- | --- |
| 3 failed checks (~30 s) | Disable and re-enable the network adapter |
| Still down 10 min after that | **Reboot the machine** |
| Mesh disconnected 6 min | Restart the Tailscale service |

```python
TARGETS = [("192.168.10.1", 80), ("192.168.10.2", 80), ("1.1.1.1", 443)]

def network_ok():
    """Any one of router, local device or internet answering means the network works."""
    return any(reachable(host, port) for host, port in TARGETS)
```

**Why three targets.** A single target fires the watchdog whenever that one device reboots. Requiring all of
them would never fire. Any-of-three distinguishes "that device is down" from "our network is down" — which is
the only distinction that matters.

**Every action is rate-limited** so a persistent fault cannot cause a reboot loop: adapter resets at most
every 3 minutes, reboots at most every 2 hours, recorded in a file that survives the reboot.

**Result:** a drop that previously lasted 12 minutes now clears in about 2½, unattended.

### Installing

```powershell
Register-ScheduledTask -TaskName 'Network watchdog' `
  -Action (New-ScheduledTaskAction -Execute 'C:\python312\python.exe' `
           -Argument 'C:\netwatch\network-watchdog.py' -WorkingDirectory 'C:\netwatch') `
  -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $set -Principal $sys -Force
```

Set `ADAPTER` to match your interface name (`Get-NetAdapter` will tell you).

> Also disable Energy-Efficient Ethernet, Green Ethernet and the adapter's power-saving mode. Power
> management on a server's network card causes exactly this class of silent failure.

---

## read-solar-inverter.py

**The problem it solves:** the inverter sends everything to the manufacturer's cloud, under an account owned
by the installer. I could see a summary and nothing else — no history, no export, no way to answer *why is
this system underproducing?*

**What it does:** reads the inverter directly over Modbus TCP. The entire protocol implementation is `socket`
and `struct` — about 30 lines including error handling. No library.

```
$ python3 read-solar-inverter.py 192.168.10.5
  grid_v         248.7
  ac_w           1203.0
  pv_w           1256.0
  inverter_c     52
  today_kwh      13.34
  lifetime_kwh   3802
```

### Finding your register map

Modbus tells you *how* to read registers, not what they mean. That mapping is vendor-specific and rarely
published.

> The map in this script was worked out against a **Polycab PSIS-4K0** (4 kW single-phase). It will likely
> suit other inverters in that family, and is a reasonable starting point for any brand — but treat it as a
> hypothesis to test, not a specification.

1. **Search first** — `<manufacturer> <model> modbus register map`. Someone has often done it already.
2. **Explore** — `--raw 0x1001 32` dumps a block, showing each value at ÷10 and ÷100 so the right scaling is
   obvious at a glance.
3. **Verify** — `--verify` sanity-checks against physics.

### The register that lied

One 32-bit pair looked exactly like a lifetime energy counter: plausible magnitude, right position in the
block. **It was the maximum PV input power rating.** A constant.

The clue was that it never changed — which I should have noticed much sooner. The real counter was two
registers further along, and I confirmed it by **watching it tick from 3776 to 3777 while the sun was up.**

> **A counter you have watched increment is a counter you can trust. A number that merely looks right is a
> guess.** Static values are especially suspicious: a reading that never moves is probably a nameplate rating,
> not a measurement.

### ⚠️ Read only

Function 3 reads. Functions 6 and 16 **write**.

Grid-tied inverters hold safety parameters — voltage trip thresholds, frequency windows, reconnection delays
— that exist to protect the grid and the people working on it. Changing them is unsafe and in most places
illegal.

This script cannot write. That is deliberate, and if you extend it, keep it that way.

### Being gentle with the device

Inverter Wi-Fi modules are small and cheap. Early attempts hammered this one and it stopped answering
entirely.

- One connection, a couple of reads, then close — never hold connections open
- Once a minute; nothing in solar data changes faster than that matters
- Back off to every five minutes when it is asleep (no sun)
- **Treat a timeout as normal**, not an error — log it and carry on

That yields ~550 good readings across a day with one or two misses, which is healthy for a cheap radio.

---

## control-lg-tv.py

**The problem it solves:** the television is the best screen in the house, and it sits idle. LG's own answer
to "show something on it" is their app and their account. But webOS exposes a **local control API** on
`wss://TV:3001` — no cloud, no account, no internet.

The server uses it to put the solar dashboard on screen the moment the TV is switched on, and to show a
one-line summary in the evening.

```
$ python3 control-lg-tv.py 192.168.10.3 pair       # once; accept the prompt on the TV
paired; key saved to lg-tv-key.txt (keep it private, do not commit it)

$ python3 control-lg-tv.py 192.168.10.3 awake      # cheap check, safe to poll
on
$ python3 control-lg-tv.py 192.168.10.3 state      # Active / Screen Off / Suspend
Active
$ python3 control-lg-tv.py 192.168.10.3 toast "Solar today: 13.2 units, 96% of expected"
$ python3 control-lg-tv.py 192.168.10.3 open http://192.168.10.200:8099/tv
```

### How it works

LG's protocol is JSON over a websocket, with requests addressed as `ssap://…` URIs. The whole client is
`socket`, `ssl`, `struct` and `json` — including a minimal RFC 6455 websocket implementation, because client
frames must be masked and nothing in the standard library does that for you.

Pairing happens once. The TV shows a prompt listing the permissions requested; accepting it returns a
**client key**, which is stored and replayed on every later connection so the prompt never appears again.

### ⚠️ Security, honestly

This is a device on your network that accepts commands, so the details matter:

- **The client key is a credential.** Anything holding it can control the television — switch inputs, launch
  apps, put messages on screen. The script writes it to `lg-tv-key.txt`, sets `0600` where the OS supports
  it, and **never prints it**. That file is in `.gitignore`, along with a `*key*.txt` catch-all.
- **Certificate verification is disabled**, because the TV presents a self-signed certificate. The encryption
  therefore protects against passive snooping but *not* against someone positioned to impersonate the TV on
  your LAN. Acceptable for a television; do not copy this pattern anywhere it matters.
- **Port 3001 must never be reachable from the internet.** Nothing here requires it to be.
- **No camera or microphone.** The permissions requested cover launching apps, reading power state and
  showing notifications. It cannot see or hear anything.
- **It refuses to re-pair silently.** If the stored key stops being accepted, the script closes the
  connection and reports it, rather than leaving a pairing prompt sitting on a family TV screen.

### Polling it gently

`awake` is a bare TCP connection test — far cheaper than a full websocket handshake, and safe to call every
few seconds. The server polls that, and only opens a real connection when the state actually changes from
off to on. A TV that is off simply does not answer, which is not an error and should not be logged as one.

---

## What is not here

The media server, DNS filter and camera viewer are off-the-shelf software
([Jellyfin](https://jellyfin.org), [AdGuard Home](https://adguard.com/adguard-home/overview.html),
[Tailscale](https://tailscale.com)) with configuration rather than code.

The solar dashboard and camera viewer are larger applications tied closely to this specific setup. The
interesting, reusable parts of both — the Modbus client above, and the serialised frame-cache pattern
described in [the CCTV document](../docs/06-cctv.md) — are documented rather than dumped wholesale.
