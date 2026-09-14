# Lumen

A terminal app for Tuya / SmartLife smart bulbs. Local LAN control, no
cloud round-trip, no hub.

Commands land instantly and keep working with the internet down, because
nothing leaves your network.

## Install

**Windows, no Python needed** — download the zip from
[Releases](https://github.com/exorev07/Lumen/releases) and unzip it.
Either run `lumen\lumen.exe` as it is, or run the included
`install.ps1` to copy it to your user profile and add it to your PATH,
so `lumen` works in any new terminal. No admin rights needed, and
`uninstall.ps1` undoes it.

Requires **Windows 10 or 11, 64-bit (x64)**; there is no ARM64 build yet,
so it will not run on a Windows-on-ARM device such as a Surface Pro X.
Windows will probably warn you the first time — see
[below](#windows-may-warn-you-about-it).

**With Python** (3.11+, any platform):

```
git clone https://github.com/exorev07/Lumen
cd Lumen
pip install .
lumen
```

> `pip install lumen-control` will be the one-liner once the package is
> published to PyPI — that has not happened yet, so use the clone above
> for now.

Press `s` on first run and the app walks you through getting your
device's key. There is no config file to hand-edit.

## Windows may warn you about it

The first time you run `lumen.exe`, Windows SmartScreen will likely show
a blue "Windows protected your PC" box. Click **More info**, then **Run
anyway**.

Some antivirus tools may also flag it, or quietly quarantine it.

This happens because the binary is **unsigned**. A code-signing
certificate costs a few hundred dollars a year, which this project does
not currently justify, and unsigned installers bundled by PyInstaller
are a common source of false positives — the same warning appears for a
great deal of open-source Windows software. It is not a statement that
anything was found.

You do not have to take that on trust. Every release lists the SHA-256 of
the binary, and you can check the file you downloaded against it:

```powershell
Get-FileHash Lumen-0.1.0-win-x64.zip -Algorithm SHA256
```

If the hash matches the one on the release page, the file is byte for
byte what was published. You can also read every line of what went into
it — that is the whole repository — and
[build it yourself](packaging/README.md) if you would rather not run
someone else's binary at all.

## Project status

Lumen is early but usable: everything documented below works, and it is
what I use to drive my own bulb daily. It is still a work in progress
rather than a finished product, so expect the occasional rough edge and
expect things to keep arriving — music reactivity and support for more
than one device at a time are both planned.

Two limits are worth knowing before you start, both of them about
breadth of testing rather than anything known to be broken:

- **One bulb has actually been tested against it** — a Syska
  SSK-SMW-12W-5C. Nothing in the code is specific to it, so other Tuya /
  SmartLife colour bulbs should work, but that is reasoning rather than
  evidence until someone tries. See [Supported devices](#supported-devices).
- **Only Windows has been tested.** macOS and Linux should be fine —
  the code is pure Python and the platform-specific part is just
  choosing a config directory — but neither has been run in anger.

Reports either way are genuinely useful, working or not.

## Why this exists

Local Tuya control is well-covered ground, but almost all of it is a
*plugin* — `tuya-local` and `localtuya` run inside Home Assistant,
`homebridge-tuya` inside Homebridge. Standing up a hub to toggle one bulb
is absurd. The rest are libraries: `tinytuya` and `tuyapi` are things you
write code against, not things you run.

Lumen is the standalone app. No hub, no plugin, no writing code.

## Using it

Run `lumen` with no arguments and you get the interface:

| key | does |
| --- | --- |
| `↑` `↓` or `tab` | move between controls |
| `←` `→` | adjust a bar, or switch mode / pick a swatch |
| `shift` + `←` `→` | single steps |
| `home` / `end` | jump a bar to its limits |
| `space` | toggle power |
| `o` / `f` | force on / off |
| `r` | refresh, and reconnect if the bulb dropped |
| `s` | settings |
| `q` | quit |

Every key works at any window size. The hint bar along the bottom shows
fewer of them on a narrow terminal rather than cutting labels in half, so
it may list less than the table above — the keys themselves still work.

The mouse works too: click a colour to set it, click a mode to switch,
click anywhere on a bar to jump to that level, or drag to scrub.

Controls that mean nothing in the current mode are hidden — warmth in
colour mode, the swatches in white mode.

For scripts, each action is also a subcommand:

```
lumen status
lumen on | off | toggle
lumen brightness 60         # 1-100
lumen color red             # a name, or "#RRGGBB"
lumen warm 80               # 0 = cool, 100 = warm
lumen config                # where settings are stored
```

Named colours: red, green, blue, yellow, cyan, magenta, orange, purple,
pink, white.

> On PowerShell, quote hex colours. `#` starts a comment, so
> `lumen color #ff8800` silently drops the value — use `"#ff8800"`.

## Setup

The bulb encrypts every local command with a key that only Tuya issues,
so you need your device's ID and local key once. Press `s` in the app and
it explains each step; the short version:

1. Pair the bulb in the Smart Life app, if you have not already. Lumen
   controls devices already on your WiFi — it does not pair them.
2. Create a free Cloud project at [iot.tuya.com](https://iot.tuya.com),
   choosing the **data centre for your Smart Life account's region**. The
   wrong region returns no devices.
3. Subscribe the project to *IoT Core*, *Authorization* and *Smart Home
   Scene Linkage*.
4. **Devices → Link Tuya App Account**, and scan the QR code with the
   Smart Life app.
5. Run `pip install tinytuya && python -m tinytuya wizard`, giving it the
   Access ID and Access Secret from the project overview.
6. The wizard writes `devices.json`. Your bulb's `id` and `key` are the
   two values Lumen asks for.

The IP is optional — leave it blank and Lumen scans for the bulb, then
remembers where it found it. A DHCP change costs one ~12s rescan and
fixes itself.

### Where settings live

`lumen config` prints the path. It is a small TOML file in your user
config directory:

| | |
| --- | --- |
| Windows | `%APPDATA%\lumen\config.toml` |
| macOS | `~/Library/Application Support/lumen/config.toml` |
| Linux | `$XDG_CONFIG_HOME/lumen/config.toml`, else `~/.config/lumen/` |

The Windows path is the one in daily use; the macOS and Linux paths
follow the usual convention for each platform but have not yet been
exercised on a real machine. If Lumen puts its config somewhere
surprising on yours, that is worth an issue.

It holds your local key, so do not commit or share it. If you would
rather keep the key out of a file, set `LUMEN_DEVICE_ID`,
`LUMEN_LOCAL_KEY` and `LUMEN_IP` in the environment instead — those win
over the file.

## Supported devices

Developed against a Syska SSK-SMW-12W-5C (12W B22D RGB), but nothing here
is Syska-specific: it speaks Tuya protocol 3.3 to a category `dj`
(standard colour light) device, so most Tuya / SmartLife colour bulbs
should work — though that is an argument from how the protocol works,
not a claim anyone has verified. If yours does work, or does not, please
open an issue: with a sample size of one, that is the most useful thing
you can contribute right now.

Only one device at a time, for the moment. Multi-device support is
planned, but one bulb is getting finished first.

## If the app will not start

Almost always one of two things, both specific to the `.exe`:

- **The display is garbled, or colours and borders look wrong.** Run it
  from [Windows Terminal](https://aka.ms/terminal) rather than from the
  older `conhost` console window. Lumen draws a full-screen interface,
  and the legacy console renders it poorly. Windows 11 uses Windows
  Terminal by default, so this mostly affects Windows 10.
- **"VCRUNTIME140.dll was not found", or it exits instantly with no
  message.** Install the
  [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).
  It ships with Windows 10 and 11, so this is rare, but a freshly
  imaged machine can be missing it.

The Python install has neither problem. If something else goes wrong,
please [open an issue](https://github.com/exorev07/Lumen/issues) —
including what Windows version you are on is genuinely useful, since
this has so far only been run on a handful of machines.

## When it stops working

Once it is running and talking to the bulb, see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md). The usual cause is a
rotated local key: re-pairing the bulb to a new WiFi network rotates it,
and you will need to re-run the wizard. Moving routers while keeping the
same SSID does not. An expired Tuya free trial does not affect local
control at all — it only blocks re-fetching the key.

## Development

```
git clone https://github.com/exorev07/Lumen
cd Lumen
pip install -e .
```

`src/lumen/device.py` is the transport and knows nothing about the UI,
`tui.py` is the interface, `cli.py` is the command line, and `config.py`
loads and saves settings. The modules carry fairly dense comments about
the decisions behind them - particularly the threading rules in `tui.py`,
where every call into the bulb blocks on a socket.

## Licence

MIT — see [LICENSE](LICENSE).

The Windows download also bundles the Python runtime and seventeen
third-party libraries (MIT, BSD, Apache-2.0 and MPL-2.0). Their licences
ship with it as `THIRD-PARTY-LICENSES.txt`, and `lumen --licence` prints
Lumen's licence together with all of them.
