"""Gibt sich dem RIKA Como dauerhaft als GSM-Modem aus.

Laeuft als App auf dem Pi, haelt die Verbindung zum USR-DR162 offen und
beantwortet jede Abfrage des Ofens. Siehe doku/RIKA-OFEN.md.

---------------------------------------------------------------------------
WARUM ER DAUERHAFT LAUFEN MUSS
---------------------------------------------------------------------------
Der Ofen fragt alle fuenf Sekunden nach seinem Modem. Bleibt die Antwort rund
eine halbe Minute aus, schaltet er GSM ab, und es hilft nur noch der Gang ans
Tastendisplay. Waehrend der Versuche am 03.10.2026 ist das ein Dutzend Mal
passiert - nicht wegen eines Fehlers, sondern weil zwischen den Laeufen
niemand geantwortet hat.

Ein Dienst, der steht, kostet also mehr als nur Bedienbarkeit: Er kostet die
Betriebsart, und die kann nur ein Mensch vor Ort wiederherstellen.

---------------------------------------------------------------------------
DIE TELEFONNUMMER
---------------------------------------------------------------------------
Der Betreiber: *"die telefonnummer musst immer speichern wenn er off war"*.

Ohne hinterlegte Nummer schickt der Ofen keine Fehlermeldungen von selbst -
und die sind der eigentliche Gewinn der ganzen Anbindung. Er vergisst sie,
wenn er stromlos war. Deshalb schickt dieser Dienst nach JEDER Neueinrichtung
des Ofens als Erstes den TEL-Befehl, unaufgefordert. Erkennbar ist eine
Neueinrichtung am ATE0: Damit faengt sie an.

---------------------------------------------------------------------------
WAS ER NICHT TUT
---------------------------------------------------------------------------
Er schickt von sich aus KEINEN Steuerbefehl ausser TEL. TEL hinterlegt nur
eine Nummer. Alles, was eine Verbrennung startet, kommt ueber die
HTTP-Schnittstelle und damit aus Home Assistant - also von einem Menschen
oder einer Automatisierung, die jemand geschrieben hat.
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
SUB = 0x1A
ZE = CR + LF

OPTIONEN = "/data/options.json"


def jetzt() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def log(text: str) -> None:
    print(f"{datetime.datetime.now():%H:%M:%S} {text}", flush=True)


class Ofen:
    """Modem-Nachbildung und Zustandshaltung. Eine Verbindung, ein Faden."""

    def __init__(self, o: dict):
        self.host = o["host"]
        self.port = int(o.get("port", 8899))
        self.pin = str(o["pin"])
        self.telefon = o.get("phone", "++430000000000")
        self.zustandsdatei = o.get("state_file", "/share/rika/state.json")

        self.warteschlange: list[str] = []
        self.offen: str | None = None
        self.ausgeliefert = False
        self.sperre = threading.Lock()

        self.sms_modus = False
        self.sms_text = ""
        self.zeile = ""

        self.letzte_anfrage = 0.0
        self.letzte_meldung = None
        self.letzte_meldung_zeit = None
        self.letzter_befehl = None
        self.meldungen: list[dict] = []
        self.tel_erledigt = False
        self.tel_zuletzt = 0.0
        self.sms_nummer = 0

    # ---------------------------------------------------------------- Zustand
    def schreiben(self) -> None:
        d = {
            "stand": jetzt(),
            "gsm_aktiv": (time.time() - self.letzte_anfrage) < 15,
            "letzte_meldung": self.letzte_meldung,
            "letzte_meldung_zeit": self.letzte_meldung_zeit,
            "letzter_befehl": self.letzter_befehl,
            "wartend": len(self.warteschlange) + (1 if self.offen else 0),
            "meldungen": self.meldungen[-20:],
        }
        try:
            os.makedirs(os.path.dirname(self.zustandsdatei), exist_ok=True)
            vorlaeufig = self.zustandsdatei + ".neu"
            with open(vorlaeufig, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(vorlaeufig, self.zustandsdatei)
        except OSError as fehler:
            log(f"Zustandsdatei nicht schreibbar: {fehler}")

    def einreihen(self, befehl: str) -> None:
        """Vollstaendiger Befehlstext OHNE Code - den setzt der Dienst davor."""
        with self.sperre:
            self.warteschlange.append(f"{self.pin} {befehl}")
        log(f"eingereiht: {befehl}")

    def naechster(self) -> None:
        with self.sperre:
            self.offen = self.warteschlange.pop(0) if self.warteschlange else None
        self.ausgeliefert = False

    # ------------------------------------------------------------------ Senden
    def sende(self, roh: bytes) -> None:
        self.s.sendall(roh)

    def ok(self) -> None:
        self.sende(b"OK" + ZE)

    def liefere(self, text: str) -> None:
        kopf = (f'+CMGR:"REC READ","{self.telefon}",,'
                f'"70/01/01,01:00:00+0"')
        # Genau diese Form ist gemessen: "REC READ" (bei "REC UNREAD"
        # ignoriert der Como die Nachricht), CR LF als Zeilenende (nur CR
        # nimmt er nicht an) und ZWEI Zeilenenden nach dem Text (mit einem
        # laeuft das OK in den Text hinein).
        self.sende(ZE + kopf.encode() + ZE + text.encode() + ZE + ZE)
        self.ok()
        self.ausgeliefert = True
        self.letzter_befehl = text
        if text.endswith(" TEL"):
            self.tel_zuletzt = time.time()
        log(f"ausgeliefert: {text}")

    # ------------------------------------------------------------------ Lesen
    def verarbeite(self, roh: bytes) -> None:
        for b in roh:
            if self.sms_modus:
                if b == SUB:
                    self.sms_modus = False
                    meldung = self.sms_text.strip()
                    self.letzte_meldung = meldung
                    self.letzte_meldung_zeit = jetzt()
                    self.meldungen.append({"zeit": jetzt(), "text": meldung})
                    log(f"MELDUNG: {meldung}")
                    # Ein echtes Modem quittiert eine abgeschickte SMS mit
                    # "+CMGS: <laufende Nummer>" und erst danach mit OK. Wer
                    # nur OK sagt, hat fuer den Ofen moeglicherweise gar
                    # nicht gesendet - und genau darauf koennte sich sein
                    # "PLEASE SAVE TEL NUMBER" beziehen, das er auch nach
                    # erfolgreichem TEL weiter anhaengt.
                    self.sms_nummer = (self.sms_nummer % 255) + 1
                    self.sende(ZE + f"+CMGS: {self.sms_nummer}".encode() + ZE + ZE)
                    self.ok()
                    # Der Betreiber: "wenn please save tel number kommt, dann
                    # sollte man die nummer schicken". Das ist die direkte
                    # Aussage des Ofens, dass ihm die Nummer fehlt - sie
                    # schlaegt jede Vermutung darueber, wann sie verloren
                    # ging. Die Minutensperre verhindert einen Kreisverkehr,
                    # falls er den Hinweis auch nach einem erfolgreichen TEL
                    # weiter anhaengt.
                    if "SAVE TEL" in meldung.upper():
                        if time.time() - self.tel_zuletzt > 60:
                            log("Ofen vermisst die Telefonnummer - wird nachgereicht")
                            self.tel_erledigt = False
                        else:
                            log("Ofen vermisst die Telefonnummer, aber gerade erst "
                                "geschickt - kein zweiter Versuch")
                    self.schreiben()
                elif 32 <= b < 127:
                    self.sms_text += chr(b)
                continue

            if b in (13, 10):
                if self.zeile:
                    self.befehl(self.zeile)
                    self.zeile = ""
                continue
            if 32 <= b < 127:
                self.zeile += chr(b)

    def befehl(self, text: str) -> None:
        self.letzte_anfrage = time.time()
        t = text.upper()

        if t.startswith("ATE"):
            # Neueinrichtung. Der Ofen war aus oder hat das Modem verloren -
            # also ist auch die Telefonnummer weg und muss neu hinterlegt
            # werden, bevor irgendein anderer Befehl sinnvoll ist.
            if self.tel_erledigt:
                log("Ofen richtet sich neu ein - Telefonnummer wird erneut hinterlegt")
            self.tel_erledigt = False
            self.ok()
            return

        if t.startswith("AT+CMGR"):
            if self.offen is None:
                if not self.tel_erledigt:
                    self.offen = f"{self.pin} TEL"
                    self.ausgeliefert = False
                else:
                    self.naechster()
            if self.offen:
                self.liefere(self.offen)
            else:
                self.sende(ZE)
                self.ok()
            return

        if t.startswith("AT+CMGS"):
            self.sende(ZE + b"> ")
            self.sms_modus = True
            self.sms_text = ""
            return

        if t.startswith("AT+CMGD"):
            # Erledigt ist eine Nachricht erst, wenn sie auch hinausging.
            # Beim Hochlauf raeumt der Ofen mit CMGD=1,2,3 die Speicher-
            # plaetze; wer darauf weiterrueckt, verliert den Befehl, bevor er
            # je ausgeliefert wurde.
            if self.ausgeliefert:
                if self.offen and self.offen.endswith(" TEL"):
                    self.tel_erledigt = True
                self.naechster()
            self.ok()
            return

        self.ok()

    # ------------------------------------------------------------------- Lauf
    def laufen(self) -> None:
        while True:
            try:
                log(f"verbinde mit {self.host}:{self.port}")
                self.s = socket.create_connection((self.host, self.port), timeout=15)
                self.s.settimeout(5.0)
                log("verbunden")
                # Nach einem Verbindungsabriss ist unklar, ob der Ofen noch
                # dieselbe Sitzung meint. Die Nummer gilt als nicht hinterlegt.
                self.tel_erledigt = False
                while True:
                    try:
                        roh = self.s.recv(4096)
                    except socket.timeout:
                        self.schreiben()
                        continue
                    if not roh:
                        raise OSError("Gegenstelle hat geschlossen")
                    self.verarbeite(roh)
            except OSError as fehler:
                log(f"Verbindung weg: {fehler}")
                self.schreiben()
                time.sleep(10)


class Schnittstelle(BaseHTTPRequestHandler):
    """Kleine HTTP-Schnittstelle fuer Home Assistant."""

    ofen: Ofen = None  # wird beim Start gesetzt

    def _antwort(self, code: int, d: dict) -> None:
        roh = json.dumps(d, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/zustand"):
            o = self.ofen
            self._antwort(200, {
                "gsm_aktiv": (time.time() - o.letzte_anfrage) < 15,
                "letzte_meldung": o.letzte_meldung,
                "letzte_meldung_zeit": o.letzte_meldung_zeit,
                "letzter_befehl": o.letzter_befehl,
            })
        else:
            self._antwort(404, {"fehler": "unbekannt"})

    def do_POST(self):
        if self.path.rstrip("/") != "/befehl":
            self._antwort(404, {"fehler": "unbekannt"})
            return
        laenge = int(self.headers.get("Content-Length", 0))
        roh = self.rfile.read(laenge).decode("utf-8", "replace").strip()
        try:
            befehl = json.loads(roh).get("befehl", "").strip()
        except json.JSONDecodeError:
            befehl = roh
        if not befehl:
            self._antwort(400, {"fehler": "kein Befehl"})
            return
        self.ofen.einreihen(befehl)
        self._antwort(202, {"eingereiht": befehl})

    def log_message(self, *_):
        pass  # das Protokoll fuehrt der Dienst selbst


def main() -> int:
    with open(OPTIONEN, encoding="utf-8") as f:
        o = json.load(f)

    ofen = Ofen(o)
    Schnittstelle.ofen = ofen

    port = int(o.get("http_port", 8098))
    server = HTTPServer(("0.0.0.0", port), Schnittstelle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(f"Schnittstelle auf Port {port}")

    ofen.laufen()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
