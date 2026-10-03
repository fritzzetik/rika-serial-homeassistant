"""Smoke test: plays the stove, checks the service answers like a modem.

    python tests/test_against_fake_stove.py

No hardware needed. The fake stove speaks the sequence a real RIKA Como was
measured to speak, and the test asserts the four things that are easy to get
wrong and that cost a day to find:

  1. the service answers the init sequence with OK
  2. it stores the phone number on its own, before anything else
  3. a queued command is re-delivered on every poll until AT+CMGD
  4. an outgoing SMS from the stove is acknowledged and captured
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "addon"))
import rika_gsm  # noqa: E402

CR, LF = b"\r", b"\n"


class FakeStove(threading.Thread):
    """Listens, then drives the conversation the way a Como does."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.seen: list[str] = []
        self.failures: list[str] = []
        self.done = threading.Event()

    def ask(self, c: socket.socket, text: str, expect: str | None = None) -> str:
        c.sendall(text.encode() + CR)
        time.sleep(0.3)
        try:
            answer = c.recv(4096).decode("ascii", "replace")
        except socket.timeout:
            answer = ""
        self.seen.append(f"{text} -> {answer!r}")
        if expect is not None and expect not in answer:
            self.failures.append(f"after {text!r} expected {expect!r}, got {answer!r}")
        return answer

    def run(self):
        c, _ = self.srv.accept()
        c.settimeout(2.0)

        # 1. init sequence, every line must be answered with OK
        for befehl in ("ATE0", "AT+CMGF=1", "AT+CNMI=2,1,0,0,1",
                       "AT+CMGD=1", "AT+CMGD=2", "AT+CMGD=3"):
            self.ask(c, befehl, "OK")

        # 2. first poll: the service must offer TEL unasked
        a = self.ask(c, "AT+CMGR=1", "+CMGR:")
        if " TEL" not in a:
            self.failures.append(f"expected an unprompted TEL, got {a!r}")

        # 3. not deleted yet -> must be offered again
        b = self.ask(c, "AT+CMGR=1", "+CMGR:")
        if " TEL" not in b:
            self.failures.append("TEL was dropped before AT+CMGD")

        self.ask(c, "AT+CMGD=1", "OK")
        leer = self.ask(c, "AT+CMGR=1")
        if "+CMGR:" in leer:
            self.failures.append("something was delivered although nothing is queued")

        # 4. a queued command, same game
        rika_gsm_stove.enqueue("OFF")
        time.sleep(0.2)
        a = self.ask(c, "AT+CMGR=1", "OFF")
        b = self.ask(c, "AT+CMGR=1", "OFF")
        if a.count("OFF") == 0 or b.count("OFF") == 0:
            self.failures.append("the command was not re-delivered")
        self.ask(c, "AT+CMGD=1", "OK")

        # 5. the stove reports something
        c.sendall(b"AT+CMGS=\"\"" + CR)
        time.sleep(0.3)
        prompt = c.recv(4096).decode("ascii", "replace")
        if ">" not in prompt:
            self.failures.append(f"expected the '> ' prompt, got {prompt!r}")
        c.sendall(b"STOVE OFF" + bytes([0x1A]))
        time.sleep(0.4)
        quittung = c.recv(4096).decode("ascii", "replace")
        if "+CMGS:" not in quittung or "OK" not in quittung:
            self.failures.append(f"outgoing SMS not acknowledged: {quittung!r}")

        c.close()
        self.done.set()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stove = FakeStove()

    rika_gsm_stove = rika_gsm.Stove({
        "host": "127.0.0.1",
        "port": stove.port,
        "pin": "1234",
        "phone": "++436641234567",
        "state_file": str(Path(__file__).resolve().parent / "state.json"),
    })
    stove.start()
    threading.Thread(target=rika_gsm_stove.run, daemon=True).start()

    if not stove.done.wait(40):
        print("the fake stove never finished")
        raise SystemExit(1)

    print("conversation:\n")
    for z in stove.seen:
        print("  ", z)

    print()
    if stove.failures:
        print(f"{len(stove.failures)} FAILURES:")
        for f in stove.failures:
            print("  -", f)
        raise SystemExit(1)

    print(f"captured message: {rika_gsm_stove.last_message!r}")
    assert rika_gsm_stove.last_message == "STOVE OFF", rika_gsm_stove.last_message
    print("all checks passed")
