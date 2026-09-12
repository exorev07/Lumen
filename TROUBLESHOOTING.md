# Troubleshooting

What breaks, and what to do about it. Nothing here needs your Tuya
credentials unless it says so.

## "Could not find the bulb on this network"

The bulb did not answer at the saved address, and a scan of the LAN did
not turn it up either. In order of likelihood:

- It is powered off at the wall. The bulb only speaks when it has power.
- It is on a different network - a 5 GHz band or a guest SSID your
  machine is not on. These bulbs are 2.4 GHz only.
- Your machine is on a VPN, so the scan never reaches the LAN.

To look for it manually:

```
python -m tinytuya scan
```

That needs no credentials. If the scan finds it but this tool did not,
open an issue - that is a bug.

## "Found the bulb but it rejected the connection"

The bulb is reachable, so the address is right, but it refused the
local key. That means **the key has rotated** and the one you have
saved is stale.

Re-pairing the bulb in the SmartLife app issues a new local key and
voids the old one. Two cases worth knowing apart:

- **Same SSID and password** - for example you replaced the router but
  kept the network name. The bulb reconnects by itself and the key
  stays valid; only the IP changes. Prefer this path if you have the
  choice.
- **New SSID, or a genuine re-pair** - the key is rotated and has to be
  fetched again.

To re-fetch it, re-run the wizard (see the README's setup section, or
press `s` in the app), then paste the new `key` into Settings.

## The bulb got a new IP

Handled automatically. Lumen tries the saved address first; if the
bulb does not answer, it rescans, finds the bulb by its device ID,
saves the new address and carries on. You just see a one-line notice
and about a 12-second pause.

To avoid the pause entirely, set a DHCP reservation for the bulb's MAC
in your router's admin page so it always lands on the same address.

## Commands hang

Only one local connection to the bulb is allowed at a time. If a
command hangs, make sure no other script is holding a socket open.

## My Tuya free trial expired

Nothing breaks. Local control never contacts Tuya - the saved key keeps
working offline, indefinitely. An expired IoT Core trial only stops you
re-running the wizard to fetch a key.

If you need to fetch a key and the trial has lapsed:

1. **Create a new cloud project.** Trials are granted per project, so a
   new one gets a fresh allowance. Re-link the SmartLife account and
   re-run the wizard.
2. **Request a trial extension** on the existing project, offered
   one-time under Cloud -> Cloud Services.
3. **Last resort:** flash open firmware (Tasmota/ESPHome) and drop Tuya
   entirely, via `tuya-convert` over OTA or by soldering if the
   firmware is patched against it. Risks bricking the bulb.

## Checking whether it works

```
lumen status
```

Expect a power/mode/brightness readout. If it hangs, the address is
stale. If it fails to decrypt, the key is stale.

## Keep your own key backed up

Your settings live outside the repository (run `lumen config` for the
path), so pushing this repo backs up your code and **not** your ability
to talk to your bulb. The local key is the one irreplaceable value -
keep a copy in a password manager.

## "Could not save" in Settings

Lumen writes your settings to a small file in your user config directory -
`lumen config` prints the path. A save can fail if that directory is not
writable: a locked-down profile, a full disk, or on Windows an antivirus
tool guarding the folder. Windows Defender's Controlled Folder Access does
this, and it does not always announce itself.

You can also skip the file entirely and set the values in the environment,
which always wins over it:

```
LUMEN_DEVICE_ID   your device id
LUMEN_LOCAL_KEY   your local key
LUMEN_IP          optional; blank to scan for the bulb
```
