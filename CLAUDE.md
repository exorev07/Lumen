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
