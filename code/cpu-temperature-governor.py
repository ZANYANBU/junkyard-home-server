"""CPU temperature governor for the home server PC (ABI, i3-6098P). Keeps the CPU below 90 C.

Every 3 seconds it reads the hottest core from Core Temp's shared memory and moves Windows'
"maximum processor state" (the CPU speed limit) up or down:

  85 C or more ...... drop straight to the floor (30%), heavy background jobs to idle priority
  92 C or more ...... also pause video conversions (ffmpeg) until the CPU is back under 80 C
  80 C or more ...... step down 10% every 9 s
  70 C or less ...... after 30 s, step up 5% (never above the ceiling, 85%)
  no reading ......... 50% after 15 s, the floor after 60 s, and Core Temp is started again

It runs on its own (scheduled task "CPU temperature governor", SYSTEM, at boot), so it keeps working
if the solar service stops. State: C:\\thermal\\state.json. Log: C:\\thermal\\thermal-YYYY-MM.csv.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state.json")

TICK_S = 3
CEILING = 85            # highest speed limit it will ever set (%)
FLOOR = 30              # lowest (about 1.1 GHz on this CPU)
START = 50              # where it starts after boot, then climbs if cool
STEP_DOWN, STEP_UP = 10, 5
EMERGENCY_C = 85        # straight to the floor
PAUSE_C = 92            # pause ffmpeg (video conversions)
RESUME_C = 80           # ... until back under this
HIGH_C = 80             # step down
LOW_C = 70              # step up after COOL_S at or below this
DOWN_EVERY_S = 9
COOL_S = 30
NO_READING_SAFE_S, NO_READING_FLOOR_S = 15, 60
HEAVY = ("ffmpeg.exe", "TiWorker.exe", "MoUsoCoreWorker.exe", "CompatTelRunner.exe", "SearchIndexer.exe")

FILE_MAP_READ = 0x0004
PROCESS_SET_INFORMATION, PROCESS_SUSPEND_RESUME, PROCESS_QUERY_LIMITED = 0x0200, 0x0800, 0x1000
IDLE_PRIORITY_CLASS = 0x40
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
k32.OpenFileMappingW.restype = wintypes.HANDLE
k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
k32.MapViewOfFile.restype = ctypes.c_void_p
k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.GetCurrentProcess.restype = wintypes.HANDLE
ntdll.NtSuspendProcess.argtypes = [wintypes.HANDLE]
ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]


def hottest_core():
    """Hottest core in C from Core Temp, or None if Core Temp isn't running."""
    h = k32.OpenFileMappingW(FILE_MAP_READ, False, "CoreTempMappingObject")
    if not h:
        return None
    try:
        p = k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, 0)
        if not p:
            return None
        try:
            n = ctypes.c_uint32.from_address(p + 1536).value
            if not 0 < n <= 64:
                return None
            tj = ctypes.c_uint32.from_address(p + 1024).value
            delta = ctypes.c_ubyte.from_address(p + 2685).value
            temps = [ctypes.c_float.from_address(p + 1544 + 4 * i).value for i in range(n)]
            temps = [tj - t for t in temps] if delta else temps
            hottest = max(temps)
            return hottest if 5 < hottest < 125 else None
        finally:
            k32.UnmapViewOfFile(p)
    finally:
        k32.CloseHandle(h)


def powercfg(*args):
    return subprocess.run(["powercfg", *args], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout


def set_limit(pct):
    powercfg("/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PROCTHROTTLEMAX", str(pct))
    powercfg("/setdcvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PROCTHROTTLEMAX", str(pct))
    powercfg("/setactive", "SCHEME_CURRENT")


def pids(names):
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20,
                         creationflags=NO_WINDOW).stdout
    found = []
    for line in out.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) > 1 and parts[0].lower() in {n.lower() for n in names}:
            found.append((parts[0], int(parts[1])))
    return found


def to_idle(names):
    done = []
    for name, pid in pids(names):
        h = k32.OpenProcess(PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED, False, pid)
        if h:
            if k32.SetPriorityClass(h, IDLE_PRIORITY_CLASS):
                done.append(name)
            k32.CloseHandle(h)
    return done


def suspend(pid_list, resume=False):
    for pid in pid_list:
        h = k32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if h:
            (ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess)(h)
            k32.CloseHandle(h)


class Governor:
    def __init__(self):
        self.limit = None
        self.cool_since = None
        self.last_down = 0
        self.no_reading_since = None
        self.paused = []            # ffmpeg pids we paused
        self.events = []
        self.peak_today = (datetime.now().date(), 0.0)
        self.last_sample_min = None
        self.last_state = 0
        self.load_events()

    def load_events(self):
        try:
            with open(STATE, encoding="utf-8") as f:
                self.events = json.load(f).get("events", [])[-50:]
        except (OSError, ValueError):
            self.events = []

    def log(self, temp, action):
        now = datetime.now()
        path = os.path.join(HERE, f"thermal-{now:%Y-%m}.csv")
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write("time,cpu_c,limit_pct,action\n")
            f.write(f"{now:%Y-%m-%d %H:%M:%S},{'' if temp is None else f'{temp:.0f}'},{self.limit},{action}\n")

    def event(self, level, text, temp):
        self.events.append({"t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "level": level, "text": text})
        self.events = self.events[-50:]
        self.log(temp, text)
        self.last_state = 0

    def apply(self, pct, temp, why):
        pct = max(FLOOR, min(CEILING, int(pct)))
        if pct != self.limit:
            set_limit(pct)
            self.log(temp, f"limit {self.limit} -> {pct}% ({why})")
            self.limit = pct
            self.last_state = 0

    def write_state(self, temp, force=False):
        if not force and time.time() - self.last_state < 15:
            return
        self.last_state = time.time()
        day = datetime.now().date()
        if self.peak_today[0] != day:
            self.peak_today = (day, 0.0)
        if temp is not None and temp > self.peak_today[1]:
            self.peak_today = (day, temp)
        state = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cpu_c": temp, "limit_pct": self.limit,
                 "ceiling_pct": CEILING, "floor_pct": FLOOR, "emergency_c": EMERGENCY_C, "target_max_c": 90,
                 "peak_today_c": round(self.peak_today[1], 1), "paused_ffmpeg": len(self.paused), "events": self.events}
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        for _ in range(5):   # Windows refuses the swap while a reader (dashboard, antivirus) has the file open
            try:
                os.replace(tmp, STATE)
                return
            except PermissionError:
                time.sleep(0.2)
        self.last_state = 0   # try again on the next tick

    def tick(self):
        now = time.time()
        temp = hottest_core()
        if temp is None:
            self.no_reading_since = self.no_reading_since or now
            gone = now - self.no_reading_since
            if gone >= NO_READING_FLOOR_S:
                self.apply(FLOOR, None, "no temperature reading for a minute")
            elif gone >= NO_READING_SAFE_S:
                if self.limit is None or self.limit > START:
                    self.apply(START, None, "no temperature reading")
                if int(gone) % 30 < TICK_S:
                    subprocess.run(["schtasks", "/run", "/tn", "Core Temp (server)"], capture_output=True,
                                   timeout=20, creationflags=NO_WINDOW)
            self.write_state(None)
            return
        self.no_reading_since = None

        if temp >= PAUSE_C:
            fresh = [pid for name, pid in pids(["ffmpeg.exe"]) if pid not in self.paused]
            if fresh:
                suspend(fresh)
                self.paused += fresh
                self.event("critical", f"{temp:.0f} C: paused {len(fresh)} video conversion(s)", temp)
        elif self.paused and temp < RESUME_C:
            suspend(self.paused, resume=True)
            self.event("info", f"{temp:.0f} C: video conversions resumed", temp)
            self.paused = []

        if temp >= EMERGENCY_C:
            if self.limit != FLOOR:
                self.apply(FLOOR, temp, f"{temp:.0f} C")
                slowed = to_idle(HEAVY)
                self.event("hot", f"{temp:.0f} C: CPU limited to {FLOOR}%"
                           + (f", {', '.join(sorted(set(slowed)))} set to low priority" if slowed else ""), temp)
            self.cool_since = None
            self.last_down = now
        elif temp >= HIGH_C:
            if now - self.last_down >= DOWN_EVERY_S:
                self.apply((self.limit or START) - STEP_DOWN, temp, f"{temp:.0f} C")
                self.last_down = now
            self.cool_since = None
        elif temp <= LOW_C:
            self.cool_since = self.cool_since or now
            if now - self.cool_since >= COOL_S and (self.limit or 0) < CEILING:
                self.apply((self.limit or START) + STEP_UP, temp, f"{temp:.0f} C, cool for {COOL_S} s")
                self.cool_since = now
        else:
            self.cool_since = None

        minute = int(now // 60)
        if minute != self.last_sample_min:
            self.last_sample_min = minute
            self.log(temp, "sample")
        self.write_state(temp)

    def run(self):
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x8000)   # above normal, so it keeps up under load
        self.apply(START, None, "start")
        self.event("info", f"governor started at {START}%", None)
        while True:
            try:
                self.tick()
            except Exception as e:  # keep governing whatever happens
                try:
                    self.log(None, f"error {type(e).__name__}: {e}")
                except OSError:
                    pass
            time.sleep(TICK_S)


if __name__ == "__main__":
    if "--once" in sys.argv:
        print(json.dumps({"cpu_c": hottest_core()}))
    else:
        Governor().run()
