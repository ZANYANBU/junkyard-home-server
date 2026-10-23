---
title: Reading the solar inverter
---

Getting a rooftop solar inverter to report to me instead of to its manufacturer — and what the data revealed.

---

## The problem

A 4 kW grid-tied solar inverter sits on the wall. It knows its panel voltage, its output power, the grid
voltage and its lifetime yield. All of it goes to the manufacturer's cloud, visible through their phone app.

**The account belongs to the installer, not to me.** I could see a summary. I could not see history, could
not export anything, and could not answer the question I actually had: *why is this system producing less
than it should?*

The inverter's own Wi-Fi module reported it was not even reaching the vendor cloud successfully. So the data
was being generated and then going nowhere at all.

---

## The insight

**The inverter is on my network. It computes these values itself. It will tell me if I ask correctly.**

Grid-tied inverters almost universally speak **Modbus TCP** — an industrial protocol from 1979, openly
documented, designed for exactly this. It is how inverters talk to monitoring equipment, and it is usually
left enabled.

A quick port scan confirmed it: **port 502 open**, the standard Modbus port.

---

## Modbus in one page

Modbus is deliberately simple. A device exposes numbered 16-bit **registers**; you ask for a range and it
returns the values.

A read request is 12 bytes:

| Bytes | Meaning |
| --- | --- |
| 0–1 | Transaction ID (echoed back) |
| 2–3 | Protocol ID (always 0) |
| 4–5 | Length of what follows |
| 6 | Unit ID (which device — here, 1) |
| 7 | Function code (**3** = read holding registers) |
| 8–9 | Starting register address |
| 10–11 | How many registers |

The reply carries the same header and then two bytes per register.

**No library needed.** The whole client is `socket` and `struct` from the Python standard library:

```python
import socket, struct

def read_registers(host, addr, count, unit=1, timeout=8):
    """Read `count` holding registers starting at `addr` (Modbus function 3)."""
    req = struct.pack(">HHHBBHH", 0x0001, 0, 6, unit, 3, addr, count)
    with socket.create_connection((host, 502), timeout=timeout) as sock:
        sock.sendall(req)
        header = sock.recv(9)                      # MBAP header + byte count
        if len(header) < 9 or header[7] != 3:
            raise IOError("unexpected Modbus reply")
        payload = sock.recv(header[8])
        return list(struct.unpack(f">{count}H", payload))
```

That is the entire protocol implementation. Thirty lines including error handling.

---

## Finding the register map

Modbus tells you *how* to read registers but not *what they mean*. The mapping is vendor-specific and the
manufacturer does not publish it.

**Two routes, and I used both:**

1. **Someone has usually done it already.** A community project for this inverter family had a partial map.
   Searching for `<manufacturer> <model> modbus register map` is genuinely the first step.
2. **Verify everything against reality.** This is the part that matters. For each candidate register, read
   it and ask whether the number makes physical sense:
   - Grid voltage should be ~230–250 and move slowly
   - Frequency should sit within a whisker of 50.00 (or 60.00)
   - Output power should track the sun and be zero at night
   - A lifetime counter should only ever increase

Scaling is usually a power of ten. A reading of `2487` for grid voltage means the register is in tenths:
248.7 V.

### The register that lied

One 32-bit pair looked exactly like a lifetime energy counter — plausible magnitude, right position in the
block. I used it for days.

**It was the maximum PV input power rating.** A constant. It never changed, which is precisely the clue I
should have noticed earlier.

The real lifetime counter was two registers further along. **How I confirmed it: I watched it tick over from
3776 to 3777 while the sun was up.** A counter you have watched increment is a counter you can trust. A
number that merely looks right is a guess.

> **The lesson:** verify each register by watching it behave, not by matching it against expectation. Static
> values are especially suspicious — a reading that never changes is probably a nameplate rating, not a
> measurement.

### The map that resulted

| Register block | Contents |
| --- | --- |
| `0x1001+` | Grid voltage (÷10), current (÷100), AC power (÷10), frequency (÷100), PV voltage/current/power, temperature |
| `0x1021+` | Lifetime kWh (32-bit pair), today's Wh (32-bit pair), peak power (÷10) |
| `0x1047` | Days since commissioning |

32-bit values span two consecutive registers, high word first: `(high << 16) | low`.

---

## Treating the device gently

The inverter's Wi-Fi module is small, cheap, and easily overwhelmed. Early attempts hammered it and it simply
stopped answering.

**The rules that made it reliable:**

- **One connection, two reads, then close.** Do not hold connections open.
- **Once a minute.** Nothing in solar data changes faster than that matters.
- **Back off when it fails.** If the inverter is asleep (no sun), poll every five minutes instead of every
  minute.
- **Treat a timeout as normal**, not as an error. Log it, carry on, and only raise an alarm after several in
  a row.

Over a day this yields roughly 550 successful readings during daylight with one or two misses. That is a
perfectly healthy ratio for a cheap radio.

### ⚠️ Read only

Modbus function 3 reads. Functions 6 and 16 **write**. This device also exposes a password-less web console
with firmware-upload, reboot and factory-reset endpoints.

**I never write to it.** Grid-tied inverters have safety parameters — voltage trip thresholds, frequency
windows, reconnection delays — that exist to protect the grid and the people working on it. Changing them is
unsafe and in most places illegal.

Reading is observation. Writing is tampering with safety equipment. The line is not subtle.

---

## What the data showed

This is why it was worth building.

**Performance was running at about 74% of what the available sunlight should have produced.** To establish
that I needed a baseline, which is itself a nice piece of free data:

- **[Open-Meteo](https://open-meteo.com)** provides free solar irradiance figures, including *global tilted
  irradiance* for a given panel angle and orientation. No API key.
- **[PVGIS](https://joint-research-centre.ec.europa.eu/pvgis-online-tool_en)** (the EU's tool, which covers
  India) gives a typical-year yield and a system performance ratio.

Expected daily output ≈ **system kW × tilted irradiance × performance ratio**. Compare against actual, every
day, and the gap becomes undeniable rather than a feeling.

**Then the cause showed itself in the voltage data.**

Grid-tied inverters must disconnect if grid voltage rises too high — a safety requirement everywhere. This
one trips at 270 V.

The data showed:
- Grid voltage sitting at **~249 V with no solar generation at all** — already above the normal limit of
  230 V +6% (244 V)
- Voltage climbing roughly **1.1–1.6 V per amp exported**, which indicates high resistance in the supply
  line
- At full output that arithmetic reaches ~270 V — exactly the cut-off
- Logged cut-off events clustering on the brightest days

**So the inverter was being switched off by the grid, on precisely the days it should have produced most.**
Not a fault in the panels, not a fault in the inverter.

This reframed the problem entirely. Cross-checking the inverter's readings against the utility meter showed
agreement within 1 V, which cleared the house wiring and placed the problem on the supply side. That became a
complaint to the electricity board, supported by a printable report the dashboard generates: voltage over
time, minutes spent above threshold, each cut-off with estimated energy lost.

**A monitoring project turned into evidence.** That is the part I did not anticipate, and it is the single
most valuable thing this build produced.

---

## What runs

A single Python service, standard library only:

- **Collector thread** — one Modbus read per minute into SQLite
- **Weather thread** — fetches irradiance, computes expected output
- **Web server** — dashboard, TV view, JSON API, printable report
- **TV watcher** — detects the television powering on and opens the dashboard on it
- **Evening summary** — one notification a day: produced, expected, tomorrow's forecast

Storage is a single SQLite file. A year of minute-resolution data is a few hundred megabytes.

**No frameworks, no dependencies, no container.** It starts in under a second and survives reboots without
help — which on a 4 GB machine is not asceticism, it is necessity.

---

**Next:** [Reading the CCTV →](06-cctv.md)
