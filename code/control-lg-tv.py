"""Control an LG webOS television from a PC, over its own websocket. Standard library only.

LG's webOS sets provide a local control API on wss://TV:3001. No cloud account, no vendor app,
no internet. The server uses it to put the solar dashboard on screen when the TV is switched on,
and to show a short summary in the evening.

    python3 control-lg-tv.py 192.168.10.3 pair          # once, accept the prompt on the TV
    python3 control-lg-tv.py 192.168.10.3 state         # on / off / screen saver
    python3 control-lg-tv.py 192.168.10.3 toast "Solar today: 13.2 units"
    python3 control-lg-tv.py 192.168.10.3 open http://192.168.10.200:8099/tv

SECURITY NOTES, because this is a device on your network that accepts commands:

  * Pairing produces a CLIENT KEY. Anything holding that key can control the television -
    switch inputs, launch apps, display messages. Treat it like a password: keep it out of
    version control, out of screenshots, and off shared machines. This script stores it in a
    separate file and never prints it.

  * The TV presents a SELF-SIGNED certificate, so certificate verification is disabled below.
    That means the encryption protects against passive snooping but not against an attacker
    positioned to impersonate the TV on your LAN. Acceptable for a television on a home
    network; do not reuse this pattern for anything that matters.

  * Port 3001 should never be reachable from the internet. Nothing here needs it to be.

  * This is read-mostly control of a display. It cannot see or hear anything - there is no
    camera or microphone access in the permissions requested.
"""
import argparse
import base64
import json
import os
import socket
import ssl
import struct
import sys
from pathlib import Path

PORT = 3001
KEY_FILE = Path(__file__).resolve().parent / "lg-tv-key.txt"   # keep this out of git

# The permission set requested at pairing. The TV shows a prompt listing these the first time.
REGISTER = {
    "type": "register",
    "id": "register_0",
    "payload": {
        "forcePairing": False,
        "pairingType": "PROMPT",
        "manifest": {
            "manifestVersion": 1,
            "appVersion": "1.1",
            "permissions": [
                "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CONTROL_AUDIO",
                "CONTROL_DISPLAY", "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_RECORDING",
                "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV", "CONTROL_POWER",
                "READ_APP_STATUS", "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST",
                "READ_NETWORK_STATE", "READ_RUNNING_APPS", "READ_TV_CHANNEL_LIST",
                "WRITE_NOTIFICATION_TOAST", "READ_POWER_STATE", "READ_COUNTRY_INFO",
            ],
        },
    },
}


class TVError(Exception):
    pass


class WebOsTV:
    """A very small websocket client, speaking just enough of LG's ssap:// protocol."""

    def __init__(self, host, key=None, timeout=15):
        self.host, self.key, self.timeout = host, key, timeout
        self.sock, self.buf, self.next_id = None, b"", 0

    # --- websocket plumbing -------------------------------------------------------------

    def _connect(self):
        raw = socket.create_connection((self.host, PORT), timeout=self.timeout)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE      # the TV's certificate is self-signed; see the notes above
        sock = ctx.wrap_socket(raw, server_hostname=self.host)

        nonce = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            f"GET / HTTP/1.1\r\nHost: {self.host}:{PORT}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                raise TVError("connection closed during handshake")
            head += chunk
        status, rest = head.split(b"\r\n\r\n", 1)
        if b" 101 " not in status.split(b"\r\n")[0]:
            raise TVError("websocket upgrade refused")
        self.sock, self.buf = sock, rest

    def _frame(self, opcode, data):
        """Client frames must be masked, per RFC 6455."""
        header = bytearray([0x80 | opcode])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _take(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise TVError("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self):
        while True:
            b0, b1 = self._take(2)
            opcode, length = b0 & 0x0F, b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._take(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._take(8))[0]
            data = self._take(length)
            if opcode == 0x8:                       # close
                raise TVError("TV closed the connection")
            if opcode == 0x9:                       # ping -> pong
                self._frame(0xA, data)
                continue
            if opcode in (0x1, 0x2):
                return json.loads(data.decode("utf-8", "replace"))

    def _send(self, obj):
        self._frame(0x1, json.dumps(obj).encode())

    # --- webOS protocol -----------------------------------------------------------------

    def request(self, uri, payload=None):
        self.next_id += 1
        rid = f"r{self.next_id}"
        self._send({"id": rid, "type": "request", "uri": f"ssap://{uri}", "payload": payload or {}})
        while True:
            msg = self._recv()
            if msg.get("id") == rid:
                if msg.get("type") == "error":
                    raise TVError(msg.get("error"))
                return msg.get("payload", {})

    def open(self, allow_pairing=False):
        self._connect()
        try:
            # Newer webOS versions want a request before registration; a failure here is harmless.
            self.request("system/getSystemInfo")
        except TVError:
            pass

        reg = json.loads(json.dumps(REGISTER))       # copy, so the template is not mutated
        if self.key:
            reg["payload"]["client-key"] = self.key
        self._send(reg)

        while True:
            msg = self._recv()
            if msg.get("type") == "registered":
                self.key = msg.get("payload", {}).get("client-key", self.key)
                return self
            if msg.get("type") == "error":
                raise TVError(msg.get("error"))
            if msg.get("payload", {}).get("pairingType") == "PROMPT":
                if allow_pairing:
                    print("Accept the prompt on the television...", file=sys.stderr)
                    continue
                # Stop rather than leave a pairing prompt sitting on a family TV screen.
                self.close()
                raise TVError("the TV asked to pair again - the stored key was not accepted")

    def close(self):
        if self.sock:
            try:
                self._frame(0x8, b"")
            except OSError:
                pass
            self.sock.close()
            self.sock = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # --- the handful of commands actually used ------------------------------------------

    def power_state(self):
        return self.request("com.webos.service.tvpower/power/getPowerState").get("state")

    def foreground_app(self):
        return self.request("com.webos.applicationManager/getForegroundAppInfo").get("appId")

    def open_url(self, url):
        return self.request("system.launcher/launch",
                            {"id": "com.webos.app.browser", "params": {"target": url}})

    def toast(self, text):
        return self.request("system.notifications/createToast", {"message": text})


def port_open(host, timeout=2):
    """True if the TV is awake. Cheaper than a full connection, and safe to call often."""
    try:
        socket.create_connection((host, PORT), timeout=timeout).close()
        return True
    except OSError:
        return False


def load_key():
    try:
        return KEY_FILE.read_text(encoding="ascii").strip() or None
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", help="TV IP address")
    ap.add_argument("command", choices=["pair", "state", "app", "toast", "open", "awake"])
    ap.add_argument("argument", nargs="?", help="message for toast, URL for open")
    args = ap.parse_args()

    if args.command == "awake":
        print("on" if port_open(args.host) else "off")
        return 0

    if not port_open(args.host):
        print(f"{args.host} is not answering on port {PORT} - the TV is off or unreachable",
              file=sys.stderr)
        return 1

    try:
        if args.command == "pair":
            tv = WebOsTV(args.host)
            tv.open(allow_pairing=True)
            KEY_FILE.write_text(tv.key, encoding="ascii")
            try:
                os.chmod(KEY_FILE, 0o600)        # no-op on Windows, worth doing elsewhere
            except OSError:
                pass
            tv.close()
            # Deliberately not printed: anything holding this key can control the TV.
            print(f"paired; key saved to {KEY_FILE.name} (keep it private, do not commit it)")
            return 0

        key = load_key()
        if not key:
            print(f"no key found - run: python3 {Path(sys.argv[0]).name} {args.host} pair",
                  file=sys.stderr)
            return 1

        with WebOsTV(args.host, key) as tv:
            if args.command == "state":
                print(tv.power_state())
            elif args.command == "app":
                print(tv.foreground_app())
            elif args.command == "toast":
                tv.toast(args.argument or "")
            elif args.command == "open":
                if not args.argument:
                    print("open needs a URL", file=sys.stderr)
                    return 1
                tv.open_url(args.argument)
    except (TVError, OSError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
