# CLAUDE.md

Local control of a Syska SSK-SMW-12W-5C smart bulb (12W B22D RGB) from
this Windows machine, over the LAN, with no cloud round-trip.

## What this is

The bulb is Tuya-based (SmartLife is Tuya's app) and speaks Tuya protocol
**3.3** on the local network. `tinytuya` talks to it directly once it has
the device's *local key*. Commands are near-instant and work with the
internet down.

Device category is `dj` (standard Tuya colour light), so the usual DPS
codes apply: 20 = switch, 21 = mode, 22 = brightness, 23 = colour temp,
24 = HSV colour.

## Setup state

Fully working. The Tuya cloud project exists, the SmartLife account is
linked, and the local key is in `local_secrets.py`.

**Do not re-run the Tuya wizard unless the key has actually rotated.**

## Layout

```
bulb.py                    the CLI - all logic lives here
config.py                  settings loader; env vars, then local_secrets.py
local_secrets.py           DEVICE_ID, LOCAL_KEY, IP        [gitignored]
local_secrets.example.py   template
bulb.cmd                   wrapper for  .\bulb <command>
tuya-data/                 wizard/scan JSON output         [gitignored]
CREDENTIALS.md             key + recovery procedures       [gitignored]
```

## Usage

```
.\bulb status | on | off | toggle
.\bulb brightness 60          1-100
.\bulb color red              name or "#RRGGBB"
.\bulb warm 80                0 = warm, 100 = cool
```

`python bulb.py <command>` works identically.

## Things that were learned the hard way

- **Quote hex colours in PowerShell.** `#` starts a comment, so
  `bulb color #ff8800` silently drops the value. `"#ff8800"` works.
- **Do not name the secrets file `secrets.py`** - it shadows the stdlib
  `secrets` module. Hence `local_secrets.py`.
- **Writing to `~\Documents` is blocked** by Windows Defender's
  Controlled Folder Access, even as Administrator. A PowerShell `$PROFILE`
  shortcut cannot be installed without allowing `pwsh.exe` through it.
  This is why `bulb.cmd` sits in the project folder instead. The ReadOnly
  attribute on Documents is a red herring - Defender is the real blocker.
- **There was a `bulb.ps1` as well as `bulb.cmd`;** having both made
  `.\bulb` ambiguous in PowerShell. Only `bulb.cmd` remains - do not add
  a `.ps1` back.
- **Brightness is 10-1000 internally,** so a set of 40% can read back as
  39%. That rounding is expected, not a bug.
- **`warm` preserves current brightness** by reading state first. It used
  to force 100%, which was wrong.

## Behaviour worth knowing

`connect()` is self-healing: it tries the saved IP, and if the bulb does
not answer it scans the LAN, matches on device ID, writes the new address
into `local_secrets.py` and carries on. So a DHCP change costs one ~12s
pause and fixes itself. A blank `IP` is fine - it will be discovered.

It distinguishes two failures deliberately:
- *not found on scan* -> bulb is off or on another network
- *found but rejected* -> the local key has rotated, see `CREDENTIALS.md`

## Secrets policy

Nothing identifying the hardware is committed - not the key, Access
Secret, Access ID, device ID, MAC or IP. `config.py` is a loader only.
**Before adding any file that touches device values, check it against
`.gitignore`.**

Consequence: pushing this repo backs up *nothing*. `local_secrets.py` and
`CREDENTIALS.md` exist only on this drive.

## If the key stops working

Full recovery procedure is in `CREDENTIALS.md` (gitignored, on this
machine). Summary: re-pairing the bulb to new WiFi rotates the key;
moving routers while keeping the same SSID does not. An expired Tuya free
tier does not affect local control at all - it only blocks re-fetching
the key, and a fresh cloud project restores that.

## Where this is going

Planned, not built yet:

- a **terminal interface** (TUI) rather than one-shot commands
- **music reactivity** - drive the colour from live audio

Both need the device layer without the argument parsing, so `bulb.py`
should be split before either lands: transport (`connect`, DPS reads and
writes) in its own module, command/CLI layer on top. Doing it early is
much cheaper than retrofitting it.

The bigger constraint is that the current design opens a fresh connection
per command, which is fine for a one-shot CLI and useless for audio -
that path needs one persistent connection held open, and a cap on update
rate so the bulb is not flooded.

Nothing here is Syska-specific. `bulb.py` speaks Tuya 3.3 to a `dj`
device, so it should work on most Tuya/SmartLife bulbs - worth keeping
that generality when refactoring.

## Before making the repo public

Planned name is `lumen`; topics and description are chosen (tuya,
smartlife, tuya-local, tinytuya, smart-bulb, local-control, tui, cli,
music-reactive, syska among them). Start the remote **private** - it can
be flipped public later, but not unpublished.

Still to do:

- **Rewrite `README.md` for someone else.** It currently reads as a
  personal log - "setup state: fully working", "the local key is in
  `local_secrets.py`" - which assumes a machine that is already
  configured. A stranger arrives with no key, no device ID and no cloud
  project, so it needs the from-zero path: install `tinytuya`, make a
  Tuya IoT project, link the SmartLife account, run the wizard, copy
  `local_secrets.example.py` to `local_secrets.py`, fill it in.
- `CLAUDE.md` and `README.md` both point at `CREDENTIALS.md`, which is
  gitignored. Those are dead links for anyone cloning - inline whatever
  is not sensitive, or say plainly that the file is local-only.
- Add a `LICENSE` (MIT unless there is a reason not to). Without one the
  repo is not legally reusable, which defeats the point of publishing.
- Re-check `.gitignore` against the tree one more time, and read the
  diff in the GitHub UI before flipping public.

## What `lumen` does that the alternatives do not

Searching GitHub for "tuya" returns ~5k repos, so it is worth being
clear about which ones overlap. Most do not:

- `tuya-convert`, `tuya-cloudcutter` - reflash the device to escape Tuya
  entirely. Far more invasive; stock firmware stays put here.
- `TuyaOpen` - Tuya's SDK for *building* devices. Wrong side of the wire.
- `tuya-home-assistant`, `tuya-homebridge` - go through the cloud API,
  which is the round-trip this project exists to avoid.

Two are genuinely adjacent:

- `tuya-local`, `localtuya-homeassistant`, `homebridge-tuya` - local
  control, same as here, but they are **plugins**: they only run inside
  Home Assistant or Homebridge. Standing up a hub to toggle one bulb is
  absurd, and that is the gap.
- `tuyapi` - standalone and local, but a **Node library**, not a tool.
  You write JS against it.

And `tinytuya`, which this depends on, is a Python library plus a scan
tool - not an application.

So the differentiator is **a standalone terminal app you just run**: no
hub, no plugin, no writing code against a library. Note that this is
only true *once the TUI and music reactivity exist*. As it stands
`bulb.py` is a thin CLI over `tinytuya` and is not novel enough to be
worth publishing - hence: build those first, publish after.

Pitch accordingly. Not "local Tuya control" - that ground is well
covered and Home Assistant owns it. Rather: *control your bulb from the
terminal, no hub required.* Keep the `tuya-local` topic anyway, to catch
people who searched it and did not want to install Home Assistant.
