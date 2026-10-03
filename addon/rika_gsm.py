"""Pretends to be the GSM modem a RIKA stove was built for.

Runs as a Home Assistant add-on, keeps a permanent TCP connection to a
serial bridge and answers every request the stove makes.

It must run continuously: the stove asks for its modem every five seconds
and switches GSM off after about thirty seconds of silence — and only a
person at the keypad can switch it back on.

Without a queued command it sends the stove nothing but `TEL`, which only
stores a phone number. Anything that lights a fire comes in over the HTTP
interface, so from a human or an automation someone wrote.

See docs/NOTES.md for what was measured and why the details matter.
"""
from __future__ import annotations

import datetime
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

CR = b"\r"
LF = b"\n"
SUB = 0x1A          # end of an outgoing SMS
EOL = CR + LF

OPTIONS = "/data/options.json"


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def log(text: str) -> None:
    print(f"{datetime.datetime.now():%H:%M:%S} {text}", flush=True)


class Stove:
    """Modem emulation and state. One connection, one thread."""

    def __init__(self, o: dict):
        self.host = o["host"]
        self.port = int(o.get("port", 8899))
        self.pin = str(o["pin"])
        self.phone = o.get("phone", "++430000000000")
        self.state_file = o.get("state_file", "/share/rika/state.json")

        self.queue: list[str] = []
        self.pending: str | None = None
        self.delivered = False
        self.lock = threading.Lock()

        self.sms_mode = False
        self.sms_text = ""
        self.line = ""

        self.last_request = 0.0
        self.last_message = None
        self.last_message_time = None
        self.last_command = None
        self.messages: list[dict] = []
        self.tel_done = False
        self.tel_last = 0.0
        self.sms_counter = 0

    # ------------------------------------------------------------------ state
    def write_state(self) -> None:
        d = {
            "updated": now(),
            "gsm_active": (time.time() - self.last_request) < 15,
            "last_message": self.last_message,
            "last_message_time": self.last_message_time,
            "last_command": self.last_command,
            "queued": len(self.queue) + (1 if self.pending else 0),
            "messages": self.messages[-20:],
        }
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.state_file)
        except OSError as err:
            log(f"cannot write state file: {err}")

    def enqueue(self, command: str) -> None:
        """Command text WITHOUT the receive code; the service prepends it."""
        with self.lock:
            self.queue.append(f"{self.pin} {command}")
        log(f"queued: {command}")

    def next_command(self) -> None:
        with self.lock:
            self.pending = self.queue.pop(0) if self.queue else None
        self.delivered = False

    # ----------------------------------------------------------------- output
    def send(self, raw: bytes) -> None:
        self.s.sendall(raw)

    def ok(self) -> None:
        self.send(b"OK" + EOL)

    def deliver(self, text: str) -> None:
        header = (f'+CMGR:"REC READ","{self.phone}",,'
                  f'"70/01/01,01:00:00+0"')
        # This exact shape is measured. "REC READ" (with "REC UNREAD" the
        # stove ignores the message), CR LF as line ending (CR alone is not
        # accepted), and TWO line endings after the text (with one, the
        # trailing OK runs into the message).
        self.send(EOL + header.encode() + EOL + text.encode() + EOL + EOL)
        self.ok()
        self.delivered = True
        self.last_command = text
        if text.endswith(" TEL"):
            self.tel_last = time.time()
        log(f"delivered: {text}")

    # ------------------------------------------------------------------ input
    def feed(self, raw: bytes) -> None:
        for b in raw:
            if self.sms_mode:
                if b == SUB:
                    self.sms_mode = False
                    message = self.sms_text.strip()
                    self.last_message = message
                    self.last_message_time = now()
                    self.messages.append({"time": now(), "text": message})
                    log(f"MESSAGE: {message}")
                    # A real modem acknowledges a sent SMS with
                    # "+CMGS: <n>" and only then OK.
                    self.sms_counter = (self.sms_counter % 255) + 1
                    self.send(EOL + f"+CMGS: {self.sms_counter}".encode() + EOL + EOL)
                    self.ok()
                    # The stove saying it has no number beats any guess about
                    # when it lost one. The one-minute lock stops a loop if it
                    # keeps asking after a successful TEL.
                    if "SAVE TEL" in message.upper():
                        if time.time() - self.tel_last > 60:
                            log("stove wants a phone number - sending TEL")
                            self.tel_done = False
                        else:
                            log("stove wants a phone number, but TEL just went "
                                "out - not retrying")
                    self.write_state()
                elif 32 <= b < 127:
                    self.sms_text += chr(b)
                continue

            if b in (13, 10):
                if self.line:
                    self.command(self.line)
                    self.line = ""
                continue
            if 32 <= b < 127:
                self.line += chr(b)

    def command(self, text: str) -> None:
        self.last_request = time.time()
        t = text.upper()

        if t.startswith("ATE"):
            # Fresh init: the stove was off or lost its modem, so the stored
            # phone number is gone too and must be set before anything else.
            if self.tel_done:
                log("stove is initialising again - will store the number")
            self.tel_done = False
            self.ok()
            return

        if t.startswith("AT+CMGR"):
            if self.pending is None:
                if not self.tel_done:
                    self.pending = f"{self.pin} TEL"
                    self.delivered = False
                else:
                    self.next_command()
            if self.pending:
                self.deliver(self.pending)
            else:
                self.send(EOL)
                self.ok()
            return

        if t.startswith("AT+CMGS"):
            self.send(EOL + b"> ")
            self.sms_mode = True
            self.sms_text = ""
            return

        if t.startswith("AT+CMGD"):
            # A message is only done once it actually went out. While
            # initialising the stove clears its slots with CMGD=1,2,3 —
            # advancing on those loses the command before it was delivered.
            if self.delivered:
                if self.pending and self.pending.endswith(" TEL"):
                    self.tel_done = True
                self.next_command()
            self.ok()
            return

        self.ok()

    # ------------------------------------------------------------------- loop
    def run(self) -> None:
        while True:
            try:
                log(f"connecting to {self.host}:{self.port}")
                self.s = socket.create_connection((self.host, self.port), timeout=15)
                self.s.settimeout(5.0)
                log("connected")
                # After a dropped connection the stored number is unknown.
                self.tel_done = False
                while True:
                    try:
                        raw = self.s.recv(4096)
                    except socket.timeout:
                        self.write_state()
                        continue
                    if not raw:
                        raise OSError("remote closed the connection")
                    self.feed(raw)
            except OSError as err:
                log(f"connection lost: {err}")
                self.write_state()
                time.sleep(10)


class Api(BaseHTTPRequestHandler):
    """Small HTTP interface for Home Assistant."""

    stove: Stove = None  # set at startup

    def _reply(self, code: int, d: dict) -> None:
        raw = json.dumps(d, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/state"):
            s = self.stove
            self._reply(200, {
                "gsm_active": (time.time() - s.last_request) < 15,
                "last_message": s.last_message,
                "last_message_time": s.last_message_time,
                "last_command": s.last_command,
            })
        else:
            self._reply(404, {"error": "unknown path"})

    def do_POST(self):
        if self.path.rstrip("/") != "/command":
            self._reply(404, {"error": "unknown path"})
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace").strip()
        try:
            command = json.loads(raw).get("command", "").strip()
        except json.JSONDecodeError:
            command = raw
        if not command:
            self._reply(400, {"error": "no command"})
            return
        self.stove.enqueue(command)
        self._reply(202, {"queued": command})

    def log_message(self, *_):
        pass  # the service does its own logging


def main() -> int:
    with open(OPTIONS, encoding="utf-8") as f:
        o = json.load(f)

    stove = Stove(o)
    Api.stove = stove

    port = int(o.get("http_port", 8098))
    server = HTTPServer(("0.0.0.0", port), Api)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"HTTP interface on port {port}")

    stove.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
