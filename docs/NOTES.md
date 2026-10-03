# What was measured, and what it cost to find

Everything here was measured on one **RIKA Como from 2014** with a keypad
display, on 3 October 2026. It is written down because most of it is not in
any manual, and because the wrong guesses are as useful as the right answers.

## Four implementations, and what they disagree about

This is the strongest piece of evidence in the whole project, and it is not
ours alone. Three other people have emulated this modem, and comparing them
settles a question one stove cannot:

| | [YannickF](https://github.com/YannickF/Rika-REVO-GSM-modem-emulator) | [ruben-janssens](https://github.com/ruben-janssens/Rika-stove-GSM-modem-emulator) | [n-serrette](https://github.com/n-serrette/esphome_rika_gsm) | this project |
| --- | --- | --- | --- | --- |
| stove | Revo | Revo | Revo | **Como (2014)** |
| hardware | Arduino Mega + Ethernet | NodeMCU, inverted UART | ESP32 / ESPHome | serial-to-WiFi bridge |
| **baud** | **38400** | **115200** | 38400 | 38400 |
| header status | — | `REC UNREAD` | `REC READ` | `REC READ` |
| send ack | `+CMGS : 01` | `+CMGS : 1` | none | `+CMGS: 1` |
| commands used | `ON OFF heat room auto` | `M<n>`, `?` | — | `ON OFF h<n> room r<n>` |

**Three Revo stoves, two different baud rates.** YannickF's original has
`#define baudRIKA 38400`; the fork of that same project, for the same model,
runs at 115200. So these values follow the **firmware**, not the model name.
If something here does not work on your stove, that is the first thing to
doubt — not the wiring.

The same goes for `REC READ` versus `REC UNREAD`: our Como ignores a message
announced as `UNREAD`, Ruben's Revo expects exactly that. There is no
universally correct answer; there is only what your stove accepts.

**The send acknowledgement appears not to matter at all.** Four
implementations, four different answers — including none — and each works
on its own stove. We added `+CMGS: n` because a real modem sends it, not
because it changed anything; it did not.

Ruben's project is also the reason to keep expectations in check: his Revo
answers `?` with the current power level and room temperature, so his
component is a real `climate` entity. Ours cannot be, and now we know that
is the stove's doing rather than ours.

### Lineage

YannickF wrote the original for an Arduino Mega with two serial ports.
ruben-janssens forked it and rewrote it for a NodeMCU and ESPHome — reading
RS-232 directly with an inverted UART and no level shifter, which is a
clever shortcut and hard on the input. n-serrette's component is the one
this project was built from. We found the first two through a reference in
the third.

## The link

```
38400 baud, 8 data bits, no parity, 1 stop bit, no flow control

stove pin  3   stove transmits      -> bridge RX
stove pin  2   stove receives       -> bridge TX
stove pin  5   GND  (also the room sensor's ground)
stove pin 15   GND
stove pin  4   room sensor signal
stove pin  1   5 V, unused here
```

Pins 2 and 3 are **real RS-232**, not TTL. Pin 4 is the room sensor line and
is a different thing entirely — mixing those up cost half a day here.

The stove emits `ATE0<CR>` every 5.5 seconds until something answers, then
runs `AT+CMGF=1`, `AT+CNMI=2,1,0,0,1`, `AT+CMGD=1/2/3` and polls
`AT+CMGR=1`. **If nothing answers for about thirty seconds it switches GSM
off**, and only a person at the keypad can switch it back on.

## Four details that look optional and are not

**Keep the pending SMS until `AT+CMGD`.** Deliver it again on every
`AT+CMGR`. Discarding it after one delivery makes the stove read it
incompletely and answer `FAILURE: code Error` — which looks exactly like a
wrong receive code and sends you hunting in the wrong place.

**Announce it as `"REC READ"`.** With `"REC UNREAD"` the Como ignores the
message completely: no `CMGD`, no reply.

**Two line endings after the message body.** With one, the trailing `OK`
runs into the text and the stove echoes fragments of the header back.

**`CR LF`, not `CR`.** [PR #5](https://github.com/n-serrette/esphome_rika_gsm/pull/5)
of the ESPHome project drops the `LF` for a TOPO. On the Como that breaks
everything: the `OK` is not accepted and it loops on `ATE0` forever.

One more, specific to the init: the stove sends `AT+CMGD=1/2/3` **before**
the first `AT+CMGR`. A queued command must not be treated as delivered by
those.

## The phone number decides whether faults are reported at all

This is not cosmetic. **Without a stored number the stove sends no fault
messages on its own** — replies to commands still arrive, unprompted ones do
not. Since the add-on is the modem, no SMS ever leaves the house; the number
is only a flag telling the stove it has somewhere to report to.

### And it is stored one character short

`TEL` stores the sender number from the `+CMGR` header, and the Como drops
the first character:

```
sent "+436641234567"  ->  stored "436641234567"
sent  "06641234567"   ->  stored  "6641234567"
```

Without a leading `+` it considers the number incomplete and appends
`PLEASE SAVE TEL NUMBER` to every reply — and, per the manual, will not send
fault messages on its own. Send it with a doubled plus.

Five guesses were tested and wrong before this one: invalid area code, a
missing `+CMGS:` acknowledgement, using a real number instead of a dummy, a
`SAVE` command, and message framing. The answer had been in the stove's own
reply all along — it echoes back exactly what it stored.

## `FAILURE: text Error` does not mean "unknown command"

Before the room sensor was connected, `room` returned `text Error`;
afterwards the same word returned `STOVE ON - ROOM 21`. The stove answers the
same way when a prerequisite is missing.

Measured vocabulary on this stove:

| works | needs something | rejected |
| --- | --- | --- |
| `TEL`, `ON`, `OFF`, `h<percent>` | `room`, `r<degrees>` — room sensor | `?`, `?+`, `SYNC`, `SAVE`, `FON` |

`?` and `?+` were extracted from `model/Commands` in the official RIKA
WarmApp APK; `?+` is undocumented anywhere. Neither is accepted here. The
manual agrees: `?` exists only "from stove software 1.12". For `FON`, frost
protection was switched off in the stove menu at the time, so that one is
inconclusive.

## The stove and the sensor, from their labels

| | |
| --- | --- |
| stove | RIKA **COMO**, 9 kW (2.4–9 kW), built **2014**, made in Austria |
| electrical | 230 V, **250 W**, 1.2 A — the plate's figure, and close to the 277 W measured while igniting |
| room sensor | **RTF, sensor KTY81-210**, EAP Electric, −30…+60 °C, IP30 |

The sensor being a KTY81-210 matters: it is a plain two-wire resistor, so
polarity does not matter when you connect it.

## Power draw, for telling intent from reality

Since there is no status query, a power meter on the stove's plug is the only
honest answer to "is it burning?".

| | |
| --- | --- |
| standby | 2.5 W |
| igniting | 277 W |
| steady burn | ~40 W |

## Wrong turns, kept on purpose

**"The socket is 5 V TTL."** The ESPHome project's README says the stove uses
5 V logic on the serial connection. That sentence is about **pin 4**, the
room sensor line. Pins 2 and 3 are RS-232. Acting on the misreading led to
recommending an ESP32 and a level shifter that nobody needs.

**"The pin numbering is mirrored."** It is not. Pin 3 was the transmit line
from the first measurement; what looked like a pulse was a character read at
the wrong baud rate.

**Twelve single experiments before building the right tool.** Each run cost a
minute: change one thing, wait for the stove's poll, read the answer. The
answer came within two minutes of writing a harness that delivers eight
variants in one pass, one per poll. The lesson is not "read the upstream
project" — that happened too. It is: after the third single experiment, build
the thing that runs twelve.
