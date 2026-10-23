# 6. Reading the CCTV

Watching the house cameras from anywhere, without the manufacturer's cloud and without exposing the DVR.

---

## The problem

A standalone DVR runs the CCTV cameras. To watch them away from the house, the manufacturer's answer is their
phone app, their cloud account, and a peer-to-peer service that punches out through the router.

I did not want that, for reasons that are not paranoia:

- **The video leaves the house** and traverses infrastructure I cannot inspect.
- **The DVR firmware is old.** It is the kind of device that appears in botnet reports. Its P2P service
  connects outward to the vendor continuously.
- **The account is theirs, not mine.** Access depends on a service that can change terms or disappear.

What I wanted: the cameras visible on my phone from anywhere, over my own private network, with the DVR
itself never reachable from outside.

---

## The insight

Same as the inverter. **The DVR already decodes the cameras and already serves images on the LAN.**

A quick look at what it exposes on port 80 found two useful endpoints:

| Endpoint | Returns |
| --- | --- |
| `/cgi-bin/snapshot.cgi?chn=N&...` | A single JPEG from channel N |
| `/cgi-bin/gw.cgi?xml=...` | Device info — model, channel count, firmware |

That is enough. A live view is just a sequence of snapshots.

---

## The architecture

```
   Cameras ──▶ DVR ──▶ Home server ──▶ You, anywhere
              (LAN)     (fetches,        (private mesh)
                        caches, serves)
```

The server sits in the middle, and that placement is the whole design:

- **The DVR is never exposed.** It stays on the LAN, reachable only by the server.
- **The viewer is served from the server**, so the browser talks to one origin.
- **Access requires the private mesh plus an access key.** Two independent barriers.

---

## The firmware limitation that shaped everything

**This DVR cannot serve two snapshot requests at once.** Ask for two channels simultaneously and you get one
failure, or — worse — the *wrong camera's image* returned for a request.

That single constraint dictated the design:

**One fetcher thread per channel, every DVR request serialised behind a single lock, feeding a frame cache
that all viewers read from.**

```python
DVR_LOCK = threading.Lock()   # the DVR firmware cannot handle concurrent requests

def grabber(channel):
    """One per channel. All DVR access serialised through DVR_LOCK."""
    while True:
        if not viewers_present():
            time.sleep(1)          # nobody watching: do not touch the DVR
            continue
        with DVR_LOCK:
            frame = dvr_snapshot(channel)
        if frame:
            publish(channel, frame)      # wake every waiting viewer
        time.sleep(interval)
```

**The consequence is a good one:** load on the DVR is constant no matter how many people are watching. One
viewer or five, it sees the same single stream of requests. Viewers read from the cache, never from the
device.

---

## On-demand only

Early on, the server fetched frames continuously whether anyone was watching or not. On a 4 GB machine with a
weak CPU, that is waste — and it keeps a fragile DVR permanently busy.

Now frames are only fetched when there is an actual viewer: an open stream, or a request within the last 20
seconds.

**Measured:**

| State | Server CPU | DVR |
| --- | --- | --- |
| Someone watching | ~1.2% | ~4 frames/sec per camera |
| Nobody watching | **0.00%** | **not contacted at all** |

The browser side cooperates: when the window is hidden, minimised or the laptop sleeps, it stops requesting
and the server goes idle within seconds. The native viewer does the same by unloading the page when its
window is not visible.

---

## Adapting to the connection

Full-resolution frames are ~550 KB each. Two cameras at a few frames a second is roughly 18 Mbit/s — fine on
the LAN, far too much over a relayed mesh connection from another city. The streams simply stalled.

The DVR offers a lower-detail mode at ~90 KB per frame, about six times smaller.

**So the server chooses automatically:**

- Any viewer on the **local network** → full resolution
- **All viewers remote** → the smaller feed

Away from home the picture is lower resolution but *smooth*, which is what actually matters when checking a
camera. There is still a manual override for when the connection is good.

---

## Lessons from the streaming

**A stalled MJPEG stream does not report an error.** It simply stops delivering. The browser fires no error
event, so nothing reconnects and the viewer sits on a frozen frame indefinitely.

The fix is a watchdog on the client: if no new frame has arrived in 10 seconds, restart the stream.

```javascript
setInterval(() => {
  if (document.hidden) return;                 // paused on purpose
  const now = performance.now();
  for (const cam of cameras) {
    const last = cam.lastFrame || cam.startedAt || now;
    if (now - last > 10000 && now - (cam.restartAt || 0) > 10000) {
      cam.restartAt = now;
      startStream(cam);
    }
  }
}, 2000);
```

**Browsers block plain HTTP to some addresses.** macOS App Transport Security permits unencrypted HTTP to
local addresses but blocks it to mesh addresses — and it fails *silently*, with no visible error. The fix was
to use the mesh **hostname** rather than its IP, and declare an exception for that domain, since the policy
can name domains but not IP addresses. Hours lost to a connection that was never attempted.

**Slow device, generous timeout.** The DVR answers a snapshot in under a second but takes ~6.5 seconds to
answer the device-info query. A 4-second timeout made the server declare it offline while it was working
perfectly. Measure each endpoint separately before choosing timeouts.

---

## Access control

Two independent barriers, because one is not enough for a camera feed:

1. **The private mesh.** The server is not reachable from the internet at all. An attacker must first be a
   device on my account.
2. **An access key.** Required on first visit, then exchanged for a session cookie so it does not sit in the
   address bar or in browser history. Rotating the key signs out every device at once.

Plus limits on concurrent streams per client, and throttling after repeated failed attempts.

> **A public tunnel was tried briefly and removed the same day.** It worked — and that was the problem. A
> publicly-reachable camera feed guarded only by a key in a URL is one accidental paste away from being a
> public camera. The key was rotated immediately afterwards. **Convenience is not worth that failure mode**,
> and the mesh gives the same access with none of the exposure.

---

## Still to do

- **The DVR is still on DHCP.** It has changed address once already and broke the viewer until it was
  tracked down. It needs a static address set in its own menu.
- **Its authentication needs hardening.** The device is isolated on the LAN with no route in from the
  internet, which contains the risk, but containment is not the same as fixing it.

---

**Next:** [Keeping it alive →](07-keeping-it-alive.md)
