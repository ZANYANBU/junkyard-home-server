---
title: Keeping it alive
---

A headless machine with a weak cooler, an unreliable network card and unstable mains, in a house with nobody
to look after it.

**Every watchdog here exists because the thing it guards against actually happened.** None of it was designed
in advance.

---

## The CPU temperature governor

### The problem

After reassembly the processor hit **89–94 °C while drawing only 17 watts.** For context, this CPU is rated
to 100 °C and should sit around 50 °C at that load. The cooler mount or the thermal paste was not right.

Thermal throttling would protect the silicon, but a machine sitting at 95 °C all day will not last, and it
makes every service slow and unpredictable.

**The proper fix is mechanical.** But the machine was in another city and needed to keep running.

### The solution

A service that reads the CPU temperature every 3 seconds and adjusts Windows' **maximum processor state** —
the same setting the power plan exposes, driven dynamically.

| Temperature | Action |
| --- | --- |
| ≥ 92 °C | Suspend video transcoding until back under 80 °C |
| ≥ 85 °C | Drop straight to the floor (30%), heavy background jobs to idle priority |
| ≥ 80 °C | Step down 10% every 9 seconds |
| ≤ 70 °C for 30 s | Step up 5%, to a ceiling of 85% |
| No reading | 50%, then the floor after a minute; restart the sensor |

Target: **never exceed 90 °C.**

### Reading the temperature

Windows does not expose CPU core temperature through any normal API. The usual route is a third-party tool.

This uses **Core Temp**, which publishes readings into a shared memory block that any process can read:

```python
FILE_MAP_READ = 0x0004
h = kernel32.OpenFileMappingW(FILE_MAP_READ, False, "CoreTempMappingObject")
p = kernel32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)

core_count = read_uint32(p + 1536)
tj_max     = read_uint32(p + 1024)
is_delta   = read_byte(p + 2685)      # some CPUs report distance-from-TjMax
temps      = [read_float(p + 1544 + 4*i) for i in range(core_count)]
if is_delta:
    temps = [tj_max - t for t in temps]
```

**The trap:** the mapping is readable only by `SYSTEM`. Running the same code over SSH gives "access denied"
and no hint why. Both the sensor and the governor run as scheduled tasks under `SYSTEM`.

### Results

| | Before | After fan fix + governor |
| --- | --- | --- |
| Idle | 51–68 °C | **31–38 °C** |
| Under load | 89–94 °C | **max 71 °C** |
| Minutes above 80 °C | frequent | **zero** |

Setting the BIOS fan profile to full speed did most of the heavy lifting. The governor is the safety net —
and it has not needed to intervene since, which is exactly what a safety net should look like.

> **A race condition worth knowing about:** the governor writes its state to a JSON file, and the dashboard
> reads it. On Windows, replacing a file that another process has open fails with a permission error. The
> write now retries five times at 200 ms intervals. On Linux the atomic rename would have worked; Windows
> file locking is stricter.

---

## The network watchdog

### The problem

Twice the machine **kept running, kept its cable link, and silently stopped passing traffic.** It could reach
neither the router, nor the DVR, nor the internet. The first time it was offline for 12 minutes; nothing
recovered it but time.

Windows logged `SuspectArpProbeFailed` — it could not get an ARP reply from the router. No link-down event,
no driver error.

### The solution

A watchdog with escalating responses:

| Condition | Action |
| --- | --- |
| Three failed checks (~30 s) | Disable and re-enable the network adapter |
| Still down 10 min after that | **Reboot the machine** |
| Mesh disconnected 6 min | Restart the mesh service |

```python
TARGETS = [("192.168.10.1", 80), ("192.168.10.2", 80), ("1.1.1.1", 443)]

def network_ok():
    """Any one of router, DVR or internet answering means the network works."""
    return any(reachable(host, port) for host, port in TARGETS)
```

**Checking three targets, not one.** A single target makes the watchdog fire whenever that one device
reboots. Requiring *all* of them would never fire. Any-of-three distinguishes "this device is down" from
"our network is down" — which is the distinction that matters.

**Rate limits on every action**, so a persistent fault cannot produce a reboot loop: adapter resets at most
every 3 minutes, reboots at most every 2 hours, recorded in a file that survives the reboot.

**Result:** a drop that previously lasted 12 minutes now resolves in about 2½, with nobody involved.

### Also done

- Disabled Energy-Efficient Ethernet, Green Ethernet and the adapter's power-saving mode
- Set `PnPCapabilities` so Windows cannot power the adapter down to save energy

Power management on a server's network card causes exactly this class of silent failure.

---

## Health logging

You cannot judge whether a machine is reliable from how it feels. **One sample a minute**, kept 30 days:

- CPU temperature, load, clock speed
- Free memory, page file use
- Whether each service is *actually answering* — not merely whether the process exists
- Uptime, so every reboot is visible whether planned or not

The service checks are real transactions, which matters:

```python
def dns_ok():
    """A real DNS query, not just a port check."""
    query = build_dns_query("example.com")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(query, ("127.0.0.1", 53))
        return sock.recv(512)[:2] == query[:2]      # matching transaction ID
```

A port check tells you something is listening. A real query tells you it is *working*. Those differ more
often than you would like.

### What it produces

An hourly summary over any window: temperature range, minimum free memory, percentage of minutes each service
answered, and every boot time.

**Measured over a 24-hour period:**

| | |
| --- | --- |
| Availability | **100%** on every check |
| CPU | 30.5–61.5 °C, averaging 33 °C |
| Lowest free memory | 1.1 GB of 3.9 GB |
| Unplanned restarts | none |

**This is the part people skip, and it is the part that tells you whether any of the rest worked.** Without
it I would have "felt" that the machine was fine. With it, I know the exact minute of every drop, how long
recovery took, and that the thermal governor has not had to act since the fan was fixed.

---

## Other protections

- **Disk health logged daily** — wear, temperature, reads/writes, errors. An SSD gives warning before it
  fails, if you are recording it.
- **Updates restricted to 23:00–07:00**, so a forced reboot never lands mid-film or mid-call.
- **Automatic sign-out** of any console session that appears within 5 minutes of boot, reclaiming the ~1 GB a
  desktop session costs.
- **Power loss recovery** — the BIOS is set to power on when mains returns, so a cut does not need a human.

---

## What I would still fix

**Backups are the weakest point in the whole design.** Everything described here protects *availability* —
the machine stays up, the services keep answering. None of it protects the *data*. A failed SSD today loses
the configuration, the solar history and the recovered photographs sitting on it.

This is the honest gap. Availability engineering is satisfying and visible; backups are neither, and I did
the satisfying part first. Automated encrypted backups are next on the roadmap, and they should arguably have
been first.

---

**Next:** [File sharing →](08-file-sharing.md)
