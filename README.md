# RIKA pellet stove over serial instead of GSM
### Memo · Pico · Como · Revo · Topo → Home Assistant

**English** · [Deutsch](README.de.md) · [Français](README.fr.md)


These stoves have a 15-pin socket that was meant for a GSM modem: you texted
the stove, it texted back. The modem is long gone and the mobile contract
with it — but **the socket still speaks**, and it is a plain serial line.

This project puts a WiFi-to-serial bridge where the modem used to sit and
lets Home Assistant talk to the stove directly. No SMS, no SIM card, no
monthly fee. No soldering and no microcontroller either: screw terminals and
an add-on.

Measured on a **RIKA Como, 2014**. The same interface and the same keypad
menu exist on Memo, Pico, Revo and Topo — untested there, but the protocol
is the stove's, not the model's.

| | |
| --- | --- |
| on / off | yes |
| heating power in percent | yes |
| room temperature in °C | yes, with the RIKA room sensor connected |
| fault messages pushed to your phone | yes |
| status on demand | **no** — see *Limitations* |

Cost: about 56 €. The commercial box for the same job is 299 €.

---

## Why this exists

RIKA stoves of this generation have a 15-pin socket meant for a
**Cinterion BGS2RT-RS232 GSM modem**. You sent the stove an SMS, it answered
with one. The modem is long gone; the stove's interface is not.

[n-serrette/esphome_rika_gsm](https://github.com/n-serrette/esphome_rika_gsm)
already emulates that modem on an ESP32, and this project was built by
reading it — credit where it is due. The difference:

| | esphome_rika_gsm | this |
| --- | --- | --- |
| hardware | ESP32 wired to the stove | **WiFi-to-serial bridge** |
| wiring | soldering / level shifter | screw terminals |
| runs as | ESPHome component | **Home Assistant add-on** |
| tested on | Revo | **Como (keypad display)** |

If you are happy to solder, use the ESPHome component — it is the more
elegant solution. This one exists for people who want screw terminals.

---

## Hardware

| part | note | ≈ |
| --- | --- | --- |
| **PUSR USR-DR162** | RS232 variant, **not** DR164 (that is RS485) | 32 € |
| **DA-15 breakout cable, male, 1.5 m** | two rows, 8 + 7 pins. *Not* the three-row VGA shell | 15 € |
| 12 V power supply | the case says `DC 5-24V`; 12 V leaves headroom | 9 € |

**The power supply is the only step where a mistake destroys something.**
Ours came with a barrel plug, so: cut it off, strip the two wires, and
**measure which one is positive** before connecting. Plug it in, hold the
bare ends apart, meter on DC volts — +12 V means that lead is positive.
Everything else in this build merely fails to work; reversed supply kills
the bridge.

That is the whole bill of materials. Other WiFi-to-serial bridges exist and
would presumably do the same job, but **this is the one that was measured** —
nothing here is claimed for hardware that was not on the bench.

One thing is not interchangeable: the bridge must speak **real RS-232**, not
3.3 V TTL. The stove's pins 2 and 3 are RS-232 levels.

### Wiring

```
stove pin  3   ->  bridge  RX     the stove's transmit line
stove pin  2   ->  bridge  TX     leave open until you can read it
stove pin 15   ->  bridge  GND
```

With the optional RIKA room sensor, in the same connector:

```
stove pin  4   ->  sensor signal
stove pin  5   ->  sensor ground   (pin 5 and pin 15 are the same potential)
```

Pin 1 carries 5 V. This project does not use it.

**Serial settings: 38400, 8, None, 1, no flow control.** Other models differ
— the ESPHome project lists 38400 for Revo and TOPO, 115200 for ROKO.

> **Start by listening only.** Wire pin 3 and pin 15, leave TX unconnected,
> and run the bridge in TCP server mode. If the stove's GSM option is on, you
> will see `ATE0` every 5.5 seconds. Nothing you do can reach the stove while
> TX is open — a good place to be while you are still unsure of the pinout.

---

## Install

1. Copy `addon/` into your Home Assistant add-on directory as
   `rika_gsm/`, then reload the add-on store and install it.
2. Configure:

```yaml
host: "192.168.1.100"      # the serial bridge
port: 8899
pin: "1234"                # four-digit receive code, stove menu SETUP -> CODE
phone: "++436641234567"    # see below — the doubled plus is deliberate
http_port: 8098
state_file: "/share/rika/state.json"
```

3. Copy `homeassistant/rika_stove.yaml` into `config/packages/` and
   **restart Home Assistant** — `reload_all` does not load `rest_command`.

### The doubled plus is not a typo

The stove stores the sender's number when it receives the `TEL` command, and
it **drops the first character**:

```
sent "+436641234567"  ->  stored "436641234567"
sent  "06641234567"   ->  stored  "6641234567"
```

Without a leading `+` it treats the number as incomplete, appends
`PLEASE SAVE TEL NUMBER` to every reply, and will not send fault messages on
its own. A sacrificial first character fixes it.

No SMS is ever sent anywhere — the number is only a label inside the stove.

---

## What you get

| entity | |
| --- | --- |
| `sensor.rika_stove_message` | the stove's last message, verbatim |
| `binary_sensor.rika_stove_gsm` | whether the stove currently sees its modem |
| `binary_sensor.rika_stove_fault` | last message starts with `FAILURE` |
| `script.rika_stove_off` / `_on` | |
| `script.rika_stove_power_30/60/100` | heating power |
| `script.rika_stove_room_temperature` | uses `input_number.rika_stove_setpoint` |

Send any command yourself:

```yaml
action: rest_command.rika_stove_command
data:
  befehl: "h75"
```

The add-on puts the receive code in front, so the code never appears in your
configuration.

---

## Commands

Measured on a Como, keypad display:

| works | needs something | rejected (`FAILURE: text Error`) |
| --- | --- | --- |
| `TEL`, `ON`, `OFF`, `h<percent>` | `room`, `r<degrees>` — room sensor | `?`, `?+`, `SYNC`, `SAVE`, `FON` |

Replies are plain text: `STOVE ON - HEAT 60%`, `STOVE OFF`,
`FAILURE: no pellets`, `WARNING: door open`, and so on.

**`FAILURE: text Error` does not mean "unknown command".** Before the room
sensor was connected, `room` returned `text Error`; afterwards the same word
returned `STOVE ON - ROOM 21`. The stove answers the same way when a
prerequisite is missing.

---

## Limitations

**There is no status query.** `?` exists only from stove software 1.12; on
this generation it is rejected. You only ever know the *last message*, not
the current state. Pair it with a power meter on the stove's plug — ours
draws 2.5 W idle and 270 W while igniting. That is what tells you whether it
is actually burning.

**The add-on must run continuously.** The stove asks for its modem every five
seconds and switches GSM off after about thirty seconds of silence — and only
a person standing at the keypad can switch it back on.

**Warnings are not pushed.** Per the manual, the stove sends faults on its
own but attaches warnings only to replies.

**Scope.** Tested on one stove, one bridge, one house. Reports about other
models are welcome; support is not something I can promise.

---

## License

MIT. Use it, change it, sell it — and note the second paragraph of the
licence, the one about no warranty. This switches a fire on and off.

## Credits

[n-serrette/esphome_rika_gsm](https://github.com/n-serrette/esphome_rika_gsm)
— the modem emulation logic is modelled on it. Three of its design decisions
are essential and easy to get wrong: keep the pending SMS until the stove
deletes it with `AT+CMGD`, announce it as `"REC READ"` (not `UNREAD`), and
put **two** line endings after the message body.
