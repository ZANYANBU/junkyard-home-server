# 3. The network

Including an old Wi-Fi router pressed into service as an access point, and a broadcast problem that cost a
day to find.

---

## The layout

```
                    Internet (fibre)
                           │
                  ┌────────▼────────┐
                  │   ISP router    │  192.168.1.1
                  │  (gateway/DHCP) │  Wi-Fi 2.4 + 5 GHz
                  └───┬────────┬────┘
            Ethernet  │        │  Ethernet
          ┌───────────▼──┐  ┌──▼──────────────┐
          │  HOME SERVER │  │  Old Wi-Fi router│  192.168.1.250
          │ 192.168.1.200│  │  as access point │
          │   (static)   │  │   (DHCP OFF)     │
          └──────────────┘  └─────────┬────────┘
                                      │ Wi-Fi
                            Devices in the far rooms
```

Also on the LAN: the solar inverter, the DVR and the television — each with a fixed address.

---

## Reusing an old router as an access point

When the ISP replaced the router, the old one went in a drawer. It is now extending Wi-Fi to the far end of
the house, for free.

**The important part: it is not acting as a router.** Plugging a second router in normally creates a second
network behind a second NAT — "double NAT" — and devices on either side cannot see each other. That would
break the whole design, because the server must be reachable from every device in the house.

### How to convert a router into an access point

The principle is to **disable everything that makes it a router** and leave only the radio and the switch.

1. **Turn off its DHCP server.** This is the critical step. Two DHCP servers on one network hand out
   conflicting addresses and cause intermittent, maddening failures.
2. **Give it a static IP** on the main network, outside the main router's DHCP range — here `192.168.1.250`.
   This is purely so you can reach its admin page later.
3. **Cable it LAN port → LAN port.** Never use its WAN/Internet port — that is what activates routing and
   NAT. Using a LAN port makes it a dumb switch with a radio attached.
4. **Set the wireless channel manually** (see below).
5. Optionally give it the same SSID and password as the main router, so devices roam between them
   seamlessly. Different passwords on the same SSID will silently prevent devices from using one of them.

Some routers have an explicit "Access Point mode" that does all of this — worth checking before doing it by
hand.

### Channel planning

2.4 GHz has only **three non-overlapping channels: 1, 6 and 11.** Every other channel overlaps its
neighbours and makes interference worse, not better.

With two access points and a neighbour's network, the correct arrangement is one on each:

| Access point | Channel |
| --- | --- |
| Neighbour's network | 1 |
| ISP router | 6 |
| Old router (AP) | 11 |

**Pin these manually.** Left on "Auto", two of your own access points will eventually choose the same channel
and spend their time competing with each other.

> Use 20 MHz width on 2.4 GHz, not 40 MHz. In any normal neighbourhood 40 MHz causes more interference than
> the extra throughput is worth.

---

## The broadcast problem that cost a day

This one is worth documenting because the symptom made no sense.

**Symptom:** devices connected to the old access point could not reach a device connected to the ISP
router's Wi-Fi. Both were on the same subnet, same address range, same netmask. Everything *should* have
worked. Pings vanished.

**Diagnosis:** packet capture showed the machine sending **120 ARP requests and receiving zero replies.** ARP
is how a device finds the hardware address behind an IP, and it works by broadcast. No ARP reply means no
communication, no matter how correct the IP configuration is.

**Cause:** the ISP router does not forward broadcast traffic from its *wireless* clients out to its *wired*
LAN ports. Broadcasts in the other direction worked fine. It is an undocumented quirk of that firmware and
there is no setting for it.

**Fixes, in order of preference:**

1. **Wire the server.** A wired device is on the LAN side and is reachable by everything. This is why the
   server is on Ethernet and not Wi-Fi — the decision came directly from this bug.
2. **Use the mesh network.** Tailscale addresses work regardless, because they do not depend on local
   broadcast at all.

**The general lesson:** when two devices on the same subnet cannot see each other, check ARP before checking
anything else. Consumer router firmware does surprising things with broadcast traffic between its wired and
wireless segments.

---

## Static addressing

Infrastructure gets fixed addresses; everything else uses DHCP.

| Device | Address | Why fixed |
| --- | --- | --- |
| ISP router | `.1` | Gateway |
| DVR | `.2` | The camera viewer must find it reliably |
| Inverter | `.5` | The solar collector polls it every minute |
| TV | `.3` | So the server can push the dashboard to it |
| **Home server** | **`.200`** | Everything else points at it |
| Old router (AP) | `.250` | Admin access |

The server's address was chosen to **match the address the previous server used**, so the television, the
phones and every saved bookmark kept working through the migration without a single client-side change.

> The switch script sets the static address, verifies internet connectivity, and **automatically falls back
> to DHCP if that check fails** — so a typo cannot leave a headless machine unreachable.

---

## Network reliability

The link negotiates at **100 Mbps on a gigabit card**, and the network has dropped twice in the observed
period — the machine kept running, kept its cable link, but silently stopped passing traffic.

**What was done:**
- Disabled Energy-Efficient Ethernet, Green Ethernet and the adapter's power-saving mode. Power management on
  a server's network card causes exactly this class of fault.
- Set `PnPCapabilities` so Windows cannot power the adapter down.
- Built a watchdog that detects it and recovers — see [keeping it alive](07-keeping-it-alive.md).

**Still unresolved:** the root cause. Prime suspects are the cable, the router port, or the 2021 network
driver. The driver has deliberately *not* been updated remotely, because a failed driver install on a
headless machine means no way back in.

---

**Next:** [Remote access →](04-remote-access.md)
