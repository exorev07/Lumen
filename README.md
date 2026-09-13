# Lumen

A terminal app for Tuya / SmartLife smart bulbs. Local LAN control, no
cloud round-trip, no hub.

Commands land instantly and keep working with the internet down, because
nothing leaves your network.

```
pip install lumen-control
lumen
```

Press `s` on first run and the app walks you through getting your
device's key. There is no config file to hand-edit.

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

It holds your local key, so do not commit or share it. If you would
rather keep the key out of a file, set `LUMEN_DEVICE_ID`,
`LUMEN_LOCAL_KEY` and `LUMEN_IP` in the environment instead — those win
over the file.

## Supported devices

Developed against a Syska SSK-SMW-12W-5C (12W B22D RGB), but nothing here
is Syska-specific: it speaks Tuya protocol 3.3 to a category `dj`
(standard colour light) device, so most Tuya / SmartLife colour bulbs
should work. If yours does, or does not, please open an issue — that is
the most useful thing you can contribute right now.

Only one device at a time, for the moment.

## When it stops working

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md). The usual cause is a
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
