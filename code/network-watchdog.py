"""Network watchdog for the home server PC: keeps it reachable from outside the house.

Twice the machine kept its cable link but stopped passing traffic: it could
reach neither the router nor the DVR nor the internet, until the network card was reset.

Every 10 s this checks three things: the router (192.168.10.1, web port), the DVR (192.168.10.2, web port) and
the internet (1.1.1.1, port 443). The network counts as working if ANY of them answers.
  - 3 failed checks in a row (about 30 s): turn the Ethernet adapter off and on again (at most every 3 minutes).
  - Still down 10 minutes after the first reset: restart the PC (at most once every 2 hours), since every
    service is unreachable anyway and a restart brings the network card up from scratch.
  - Tailscale (the way in from outside the house): checked every 2 minutes while the network works; if it is
    not connected 3 times in a row, its service is restarted (at most every 15 minutes).
Log: C:\\netwatch\\netwatch.log. Runs as the scheduled task "Network watchdog" (SYSTEM, at boot).
"""
import json
import os
import socket
import subprocess
import time
from datetime import datetime

TARGETS = [("192.168.10.1", 80), ("192.168.10.2", 80), ("1.1.1.1", 443)]
ADAPTER = "Ethernet"
EVERY_S, MISSES = 10, 3
RESET_COOLDOWN_S = 180
REBOOT_AFTER_S, REBOOT_COOLDOWN_S = 600, 7200
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "netwatch.log")
LAST_REBOOT = os.path.join(HERE, "last-reboot.txt")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TAILSCALE = r"C:\Program Files\Tailscale\tailscale.exe"
TS_EVERY_S, TS_MISSES, TS_COOLDOWN_S = 120, 3, 900


def log(msg):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 1_000_000:
            os.replace(LOG, LOG + ".old")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def network_ok():
    return any(reachable(h, p) for h, p in TARGETS)


def reset_adapter():
    for state in ("disabled", "enabled"):
        subprocess.run(["netsh", "interface", "set", "interface", ADAPTER, f"admin={state}"],
                       capture_output=True, timeout=30, creationflags=NO_WINDOW)
        time.sleep(5)


def last_reboot():
    try:
        with open(LAST_REBOOT, encoding="ascii") as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return 0.0


def reboot(down_s):
    with open(LAST_REBOOT, "w", encoding="ascii") as f:
        f.write(str(time.time()))
    log(f"network down for {down_s:.0f} s even after resets: restarting the PC")
    subprocess.run(["shutdown", "/r", "/t", "30", "/d", "p:4:1", "/c", "Network watchdog: no network, restarting"],
                   capture_output=True, timeout=30, creationflags=NO_WINDOW)


def tailscale_state():
    try:
        out = subprocess.run([TAILSCALE, "status", "--json"], capture_output=True, text=True, timeout=20,
                             creationflags=NO_WINDOW).stdout
        return json.loads(out).get("BackendState", "?")
    except (OSError, ValueError, subprocess.SubprocessError):
        return "?"


def restart_tailscale():
    subprocess.run(["powershell", "-NoProfile", "-Command", "Restart-Service Tailscale -Force"],
                   capture_output=True, timeout=90, creationflags=NO_WINDOW)


def main():
    misses, last_reset, down_since, first_reset = 0, 0.0, None, None
    ts_last_check, ts_misses, ts_last_restart = 0.0, 0, 0.0
    log("watchdog started")
    while True:
        if network_ok():
            if down_since:
                log(f"network back after {time.time() - down_since:.0f} s")
            misses, down_since, first_reset = 0, None, None
            if time.time() - ts_last_check >= TS_EVERY_S:
                ts_last_check = time.time()
                state = tailscale_state()
                ts_misses = 0 if state == "Running" else ts_misses + 1
                if ts_misses == 1:
                    log(f"Tailscale not connected (state {state})")
                if ts_misses >= TS_MISSES and time.time() - ts_last_restart > TS_COOLDOWN_S:
                    log("Tailscale not connected for 6 minutes: restarting its service")
                    restart_tailscale()
                    ts_last_restart, ts_misses = time.time(), 0
        else:
            misses += 1
            now = time.time()
            down_since = down_since or now
            if misses == 1:
                log("router, DVR and internet not answering")
            if misses >= MISSES and now - last_reset > RESET_COOLDOWN_S:
                log(f"network down for {now - down_since:.0f} s: resetting the {ADAPTER} adapter")
                reset_adapter()
                last_reset = time.time()
                first_reset = first_reset or last_reset
            elif first_reset and now - first_reset > REBOOT_AFTER_S and now - last_reboot() > REBOOT_COOLDOWN_S:
                reboot(now - down_since)
        time.sleep(EVERY_S)


if __name__ == "__main__":
    main()
