# Syska Smart Bulb - local control

Controls a Syska SSK-SMW-12W-5C (Tuya-based) bulb directly over the LAN.
No cloud round-trip, no internet needed once set up.

## Device

Syska SSK-SMW-12W-5C (12W B22D RGB), Tuya protocol 3.3.

Your device's own ID, key and IP go in `local_secrets.py`, which is not
committed. Copy `local_secrets.example.py` to start.

## Layout

See `CLAUDE.md` for project context, design decisions and the gotchas
that are easy to trip over again.

```
bulb.py                    the CLI
config.py                  settings loader (env vars, then local_secrets)
local_secrets.py           device ID, key, IP - gitignored
local_secrets.example.py   template to copy
bulb.cmd                   wrapper so you can type  .\bulb <command>
requirements.txt           tinytuya
tuya-data/                 wizard/scan output - gitignored, not read at runtime
CREDENTIALS.md             credentials and recovery notes - gitignored
```

## Install

```
pip install -r requirements.txt
copy local_secrets.example.py local_secrets.py
```

Then fill in `DEVICE_ID` and `LOCAL_KEY` (see setup below). `IP` can be
left blank - the bulb is found automatically on first run.

## Status: working

The local key is configured in `local_secrets.py` and all commands are
verified against the bulb. Nothing below needs redoing unless the key
stops working.

## One-time setup: get the local key (already done)

The bulb encrypts every local command with a key that only Tuya issues.
Pulling it out takes about 10 minutes.

1. Sign up at <https://iot.tuya.com> (free).
2. **Cloud -> Development -> Create Cloud Project.**
   - Industry: Smart Home, Development Method: Smart Home, Data Centre:
     **India** (must match the region your SmartLife account is in).
   - After creating, note the **Access ID** and **Access Secret**.
3. On the project's **Service API** tab, subscribe to *IoT Core*,
   *Authorization*, and *Smart Home Scene Linkage* if not already added.
4. **Devices -> Link Tuya App Account -> Add App Account**, then scan the
   QR code from the SmartLife app (Me -> top-right scan icon).
   The bulb now appears under Devices.
5. Back on this machine, run the wizard and paste the Access ID / Secret /
   region when prompted:

   ```
   python -m tinytuya wizard
   ```

   It writes `devices.json` containing the bulb's `key`.
6. Copy that key into `LOCAL_KEY` in `local_secrets.py`.

## Usage

From the project folder, `.\bulb` is a shorter alias for `python bulb.py`:

```
.\bulb status
python bulb.py status
python bulb.py on
python bulb.py off
python bulb.py toggle
python bulb.py brightness 60
python bulb.py color red
python bulb.py color "#ff8800"
python bulb.py warm 80
```

Named colours: red, green, blue, yellow, cyan, magenta, orange, purple,
pink, white. Anything else can be given as `#RRGGBB`.

## Notes

- If the bulb's IP changes, the script notices, rescans the network and
  updates `local_secrets.py` by itself - you just see a one-line notice.
- A **DHCP reservation** for the bulb on your router avoids even that
  pause. Recommended but not required.
- The local key is rotated if you remove and re-pair the bulb in
  SmartLife. Re-run the wizard if commands suddenly fail.
- Only one local connection at a time - if a command hangs, make sure no
  other script is holding a persistent socket open.
