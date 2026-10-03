# Getting it onto your Home Assistant server

Written for **Home Assistant OS** (the appliance install on a Raspberry Pi or
similar). Supervised works the same way. Container and Core have no add-ons;
see *Without add-ons* at the end.

Allow half an hour. Most of it is waiting for the stove to poll.

---

## 0. Before you start

- [ ] The serial bridge is wired to the stove and powered — see the
      README. **Polarity of the power supply measured.**
- [ ] The bridge is on your WiFi with a **fixed address** (DHCP reservation
      in the router). The add-on connects to it by address; if it moves, the
      connection breaks.
- [ ] Bridge set to **TCP server**, serial **38400, 8, None, 1**, no flow
      control.
- [ ] You know the stove's four-digit receive code: at the keypad, press
      MENU until `SETUP`, then `CODE`. `0000` is the factory value and is not
      accepted by the stove — set a real one.

> **Check before you build anything.** Connect to the bridge and watch. With
> the stove's GSM option on, `ATE0` must appear every 5.5 seconds:
>
> ```
> nc 192.168.1.100 8899
> ```
>
> Nothing? Then the wiring or the baud rate is wrong, and no amount of
> software will fix it. Garbled characters mean the baud rate specifically.

---

## 1. Put the add-on on the machine

Add-ons live in the `addons` share. Pick whichever way you already have:

**Samba share** (easiest if you have the Samba add-on): open
`\\homeassistant\addons` in Explorer or Finder and copy the `addon` folder
there, renamed to `rika_gsm`.

**SSH**: with the *Terminal & SSH* add-on,

```bash
mkdir -p /addons/rika_gsm
# then copy config.yaml, build.yaml, Dockerfile and rika_gsm.py into it
```

On newer Home Assistant OS the directory may be `/local_apps/` instead of
`/addons/` — look for the one that already exists.

**Studio Code Server / File editor**: create the folder and the four files by
hand. Tedious but works without any extra tooling.

Afterwards the structure must be:

```
addons/rika_gsm/config.yaml
addons/rika_gsm/build.yaml
addons/rika_gsm/Dockerfile
addons/rika_gsm/rika_gsm.py
```

## 2. Install it

Settings → Add-ons → Add-on store → three-dot menu → **Check for updates**.
*RIKA stove GSM emulator* appears under *Local add-ons*. Open it, press
**Install** and wait — the first build takes a few minutes, it is fetching
Alpine and Python.

## 3. Configure

On the add-on's **Configuration** tab:

```yaml
host: "192.168.1.100"      # your serial bridge
port: 8899
pin: "1234"                # the stove's receive code
phone: "++436641234567"    # doubled plus, see the README
http_port: 8098
state_file: "/share/rika/state.json"
```

Save, then **Start**, and switch on *Start on boot* and *Watchdog*.

### Does it work?

Open the add-on's **Log** tab:

```
HTTP interface on port 8098
connecting to 192.168.1.100:8899
connected
```

Now switch GSM on at the stove: MENU → `SETUP` → `GSM SET` → `GSM ON`, then
wait five seconds before pressing MENU again — the stove needs that for its
own initialisation. Within a minute the log must show:

```
delivered: 1234 TEL
delivered: 1234 TEL
MESSAGE: TELEPHONE NUMBER: ... - OK
```

Delivered twice is correct, not a bug: the message stays on offer until the
stove deletes it.

**This step is not optional.** Until the stove has a number it considers
valid, it will answer your commands but report no faults of its own — no
`no pellets`, no `door open`, nothing. If the reply keeps ending in
`PLEASE SAVE TEL NUMBER`, the number did not take; check the doubled plus.

**Nothing at all?** The stove has switched GSM off again — it does that after
about thirty seconds without an answer. Switch it on once more; from now on
the add-on keeps it awake.

## 4. The Home Assistant side

Copy `homeassistant/rika_stove.yaml` into `config/packages/`. If you have
never used packages, add this to `configuration.yaml` first:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Edit two things in the file:

- `notify.mobile_app_your_phone` → your own device
- the URL in `rest_command`. `http://homeassistant.local:8098/command` works
  on most installs; if not, use the machine's IP address.

Then **restart Home Assistant** — Developer tools → three-dot menu →
Restart. `reload_all` is not enough: it does not load `rest_command`, and
every button would silently do nothing. This one cost an afternoon to find.

### Does it work?

Developer tools → Actions → `rest_command.rika_stove_command`, with

```yaml
command: "TEL"
```

The add-on log must show `queued: TEL`. If it does not, the URL is wrong.

## 5. The dashboard

Settings → Dashboards → Add dashboard → Empty, then open it, three-dot menu →
**Raw configuration editor**, and paste `homeassistant/dashboard.yaml`.

It expects a power meter as `sensor.stove_plug_power`. Rename it to yours, or
delete the *What it does* section — but read the note in the file first about
why that section is there.

## 6. Everyday use

The add-on must keep running. If it stops for more than half a minute, the
stove drops its modem, and only someone standing at the keypad can switch
GSM back on. *Watchdog* in the add-on settings restarts it if it crashes.

---

## Without add-ons (Container, Core, or a different machine)

`rika_gsm.py` is a plain Python script with no dependencies. It reads its
settings from `/data/options.json`:

```json
{
  "host": "192.168.1.100",
  "port": 8899,
  "pin": "1234",
  "phone": "++436641234567",
  "http_port": 8098,
  "state_file": "/share/rika/state.json"
}
```

Run it under systemd, in Docker, or on any machine that is always on and can
reach the bridge. Home Assistant then needs to reach `http_port` and read the
state file — adjust the paths in `rika_stove.yaml` accordingly.

---

## When something is wrong

| symptom | cause |
| --- | --- |
| buttons do nothing, no error | `rest_command` not loaded — **restart** Home Assistant |
| `queued:` in the log, no reply from the stove | GSM is off at the stove |
| `FAILURE: code Error` | wrong receive code — or a port that discards the pending message |
| `FAILURE: text Error` | unknown command **or** a missing prerequisite (e.g. `room` without the room sensor) |
| `PLEASE SAVE TEL NUMBER` on every reply | `phone` is missing its doubled plus — **and until that is fixed the stove sends no fault messages at all** |
| garbled characters in a raw capture | wrong baud rate |
| nothing at all in a raw capture | wiring, or GSM off at the stove |
