"""Read a grid-tied solar inverter over Modbus TCP, using nothing but the standard library.

Most grid-tied inverters speak Modbus TCP on port 502. It is an openly documented protocol from
1979, and vendors usually leave it enabled even when they would rather you used their cloud app.

    python3 read-solar-inverter.py 192.168.10.5
    python3 read-solar-inverter.py 192.168.10.5 --raw 0x1001 32

IMPORTANT, and not a formality:

  * This reads only. Modbus function 3 reads holding registers; functions 6 and 16 WRITE them.
    Grid-tied inverters hold safety parameters - voltage trip thresholds, frequency windows,
    reconnection delays - that exist to protect the grid and the people working on it. Changing
    them is unsafe and in most places illegal. Reading is observation; writing is tampering with
    safety equipment.

  * The register map below is for one inverter family and is almost certainly wrong for yours.
    Registers are vendor-specific and rarely published. Use --raw to explore, and verify every
    register against physical reality before trusting it. See verify() at the bottom.

  * Inverter Wi-Fi modules are small and cheap. One connection, a couple of reads, then close.
    Poll once a minute, not once a second, or it will stop answering.
"""
import argparse
import socket
import struct
import sys

PORT = 502
UNIT = 1            # Modbus slave/unit id; 1 is almost always correct for a single inverter
READ_HOLDING = 3    # function code


def read_registers(host, addr, count, unit=UNIT, timeout=8.0):
    """Read `count` 16-bit holding registers starting at `addr`. Returns a list of ints.

    The request is a 12-byte MBAP header plus PDU:
        transaction id (2) | protocol id (2) | length (2) | unit (1)
        function (1) | start address (2) | register count (2)
    """
    if not 1 <= count <= 125:
        raise ValueError("Modbus allows 1-125 registers per read")

    request = struct.pack(">HHHBBHH", 1, 0, 6, unit, READ_HOLDING, addr, count)

    with socket.create_connection((host, PORT), timeout=timeout) as sock:
        sock.sendall(request)

        header = _recv_exactly(sock, 9)             # MBAP (7) + function (1) + byte count (1)
        function = header[7]
        if function != READ_HOLDING:
            # The high bit set means an exception reply; the next byte says why.
            if function & 0x80:
                raise IOError(f"Modbus exception {header[8]} (addr 0x{addr:04X})")
            raise IOError(f"unexpected function {function} in reply")

        payload = _recv_exactly(sock, header[8])
        return list(struct.unpack(f">{count}H", payload))


def _recv_exactly(sock, n):
    """recv() may return short reads; keep going until we have n bytes."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise IOError("connection closed mid-reply")
        buf += chunk
    return buf


def u32(regs, i):
    """Two consecutive registers as one 32-bit value, high word first."""
    return (regs[i] << 16) | regs[i + 1]


# --- A register map. Yours will differ. Verify before believing any of it. ----------------
#
# Scaling is nearly always a power of ten: a grid voltage of 2487 means 248.7 V.

def read_inverter(host):
    live = read_registers(host, 0x1001, 32)
    energy = read_registers(host, 0x1021, 32)
    return {
        "grid_v":      live[0] / 10,
        "grid_a":      live[1] / 100,
        "ac_w":        live[3] / 10,
        "frequency":   live[4] / 100,
        "pv_v":        live[15] / 10,
        "pv_a":        live[16] / 100,
        "pv_w":        live[18] / 10,
        "inverter_c":  live[27],
        "lifetime_kwh": u32(energy, 2),     # NOT index 0 - see the note in verify()
        "today_kwh":   u32(energy, 6) / 1000,
        "peak_w":      energy[27] / 10,
    }


def verify(host):
    """Sanity-check a candidate register map against physical reality.

    This is the part that matters. A number that merely looks plausible is a guess; a number you
    have watched behave correctly is a measurement. Specifically:

      * Grid voltage should be ~230-250 V and drift slowly.
      * Frequency should sit within a whisker of 50.00 or 60.00 Hz.
      * Output power should track the sun, and be zero at night.
      * A lifetime counter should ONLY EVER INCREASE. Watch it tick over before trusting it.

    A register that never changes is the classic trap - it is probably a nameplate rating rather
    than a measurement. One 32-bit pair here looked exactly like a lifetime energy counter and was
    in fact the maximum PV input power rating. The giveaway was that it never moved.
    """
    d = read_inverter(host)
    checks = [
        ("grid voltage plausible",   180 <= d["grid_v"] <= 280,        f'{d["grid_v"]} V'),
        ("frequency plausible",      45 <= d["frequency"] <= 65,       f'{d["frequency"]} Hz'),
        ("inverter temp plausible",  0 <= d["inverter_c"] <= 100,      f'{d["inverter_c"]} C'),
        ("AC power not absurd",      0 <= d["ac_w"] <= 20000,          f'{d["ac_w"]} W'),
        ("PV >= AC (conversion loss)", d["pv_w"] >= d["ac_w"] - 50,    f'{d["pv_w"]} -> {d["ac_w"]} W'),
    ]
    width = max(len(name) for name, _, _ in checks)
    for name, ok, value in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {value}")
    print("\n  Now re-run in daylight and confirm lifetime_kwh has increased.")
    print("  A counter you have watched increment is a counter you can trust.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", help="inverter IP address")
    ap.add_argument("--raw", nargs=2, metavar=("ADDR", "COUNT"),
                    help="dump raw registers, e.g. --raw 0x1001 32")
    ap.add_argument("--verify", action="store_true", help="sanity-check the register map")
    args = ap.parse_args()

    try:
        if args.raw:
            addr, count = int(args.raw[0], 0), int(args.raw[1])
            regs = read_registers(args.host, addr, count)
            for i, value in enumerate(regs):
                # Showing /10 and /100 makes the right scaling obvious at a glance.
                print(f"  [{i:3d}] 0x{addr + i:04X}  {value:6d}   /10={value / 10:<10.1f} /100={value / 100:.2f}")
        elif args.verify:
            verify(args.host)
        else:
            for key, value in read_inverter(args.host).items():
                print(f"  {key:<14} {value}")
    except (OSError, IOError) as e:
        # A timeout usually means the inverter is asleep (no sun), not that anything is broken.
        print(f"could not read {args.host}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
