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
device.py                  transport - connect, DPS reads and writes
tui.py                     the terminal interface (Textual)
bulb.py                    the CLI - argument parsing, dispatch
config.py                  settings loader; env vars, then local_secrets.py
local_secrets.py           DEVICE_ID, LOCAL_KEY, IP        [gitignored]
local_secrets.example.py   template
bulb.cmd                   wrapper for  .\bulb <command>
tuya-data/                 wizard/scan JSON output         [gitignored]
TROUBLESHOOTING.md         failure modes and recovery - public
CREDENTIALS.md             this machine's key + IDs         [gitignored]
```

## Usage

```
.\bulb                        opens the terminal interface
.\bulb status | on | off | toggle
.\bulb brightness 60          1-100
.\bulb color red              name or "#RRGGBB"
.\bulb warm 80                0 = warm, 100 = cool
```

`python bulb.py <command>` works identically.

In the interface: `↑/↓` (or `tab`) move between controls. On a bar, `←/→`
adjust it - `shift` for single steps, `home`/`end` to jump. On the swatch
grid, `←/→` move along the row and `enter` picks. `space` toggles power,
`o`/`f` force on/off, `r` refreshes (and reconnects if the bulb has
dropped), `q` quits.

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
  to force 100%, which was wrong. The TUI's warmth bar does the same.
- **`self._timers` is taken by Textual.** Naming an attribute that on an
  `App` subclass crashes on mount with `'dict' object has no attribute
  'add'`. The debounce timers are `self._debounce` for that reason.
- **Textual 8.x ships no `Slider` widget.** The bars are the custom `Bar`
  widget; do not go looking for a stock one.

## Behaviour worth knowing

`connect()` is self-healing: it tries the saved IP, and if the bulb does
not answer it scans the LAN, matches on device ID, writes the new address
into `local_secrets.py` and carries on. So a DHCP change costs one ~12s
pause and fixes itself. A blank `IP` is fine - it will be discovered.

It distinguishes two failures deliberately:
- *not found on scan* -> bulb is off or on another network
- *found but rejected* -> the local key has rotated, see `TROUBLESHOOTING.md`

## The TUI

`tui.py`, on Textual (`textual>=8.0,<9`, in `requirements.txt` - the
command-palette styling targets 8.x internals). One screen,
`LumenApp`, plus two small custom widgets.

**Threading is the thing to get right.** Every tinytuya call blocks on a
socket, so all of them run in `@work(thread=True)` workers and post back
with `call_from_thread`. Anything added later must do the same or it will
freeze the UI mid-render.

- `connect` / `poll` / `write` are each `exclusive` workers in their own
  group, so a newer one cancels an older one still waiting on the socket.
- `queue_write` is a **trailing debounce** (`WRITE_DEBOUNCE`, 150 ms).
  Holding an arrow key sends *one* write when you stop, not one per
  repeat. Verified: four rapid presses produce zero writes during the
  burst and one after.
- `poll` runs every `POLL_INTERVAL` (5 s) to catch changes made from the
  phone app, and **skips while a write is pending** so a stale read cannot
  yank a bar back under the user's fingers.
- The debounce timers live in `self._debounce`. Do not call it
  `self._timers` - that collides with an internal Textual attribute and
  crashes on mount.
- **The debounce must bind its value at schedule time.** The timer used to
  fire `self.write(what, self._pending.get(what))`, reading the dict when
  it fired. A write completing in between pops that entry, so the late
  timer sent `None` into `pct_to_raw` -> `TypeError: unsupported operand
  type(s) for /: 'NoneType' and 'int'`. It needs a burst straddling an
  in-flight write, so it only shows up when actually dragging a bar.
- **`_write_done` clears the pending entry only if it is still the value it
  sent.** Popping unconditionally lets a newer queued change stop blocking
  `poll`, and a stale read then yanks the bar back mid-drag. A *failed*
  write must clear it too, or one error blocks `poll` for the session.

**Verified against the real bulb** (2026-09-02), not just a fake: the
burst-across-an-in-flight-write pattern that produced the `None` crash,
`warm` preserving brightness, named and hex colours, and toggle. Also
measured for flakiness - 20 sequential reads and 12s of concurrent
poll+write traffic on two threads gave **zero** failures, which is why the
blip tolerance above is a small retry threshold rather than something
heavier. Note that back-to-back CLI commands can still read stale state:
a `warm` issued immediately after a `brightness` re-applied the old value.

**Custom widgets.** Textual 8.x has no `Slider`, hence `Bar` - a focusable
0-100 widget that renders its own track. `Swatch` is one named colour.
Both post messages (`Bar.Changed`, `Swatch.Picked`) rather than touching
the bulb directly.

**Layout rules that were arrived at by breaking them:**

- The UI is one bordered panel **filling the terminal**. It is the app,
  not a dialog - do not centre it or cap its width.
- The swatches are **one reflowing grid**, not fixed rows. They used to be
  two `Horizontal` rows of five, which meant a narrow terminal simply hid
  the colours past the right edge. `#swatches` is a `layout: grid` whose
  column count `reflow_swatches()` recomputes from the width, capped at
  `SWATCH_COLUMNS` (5) so a wide terminal keeps the tidy two rows.
  `grid-columns: 12` is fixed, otherwise the columns stretch apart to fill
  the panel. Checked 20-150 columns: all ten stay visible.
- **`on_resize` must use `event.size`, not `self.size`.** `self.size` still
  holds the *old* width when the handler runs, so reflowing from it leaves
  the layout one resize behind.
- Anything walking the swatches must derive rows from the live column
  count - `LumenApp.swatch_rows()` - rather than assuming two.
- **Repaint only when the rendered output would actually differ.** Dragging
  a window from 120 to 28 columns fires ~46 resize events but changes the
  swatch column count 3 times and the `Bar` track ~5 times. Both handlers
  compare before refreshing (`Bar.track_width(event.size.width)` against
  the current one). Some flicker during a drag is the terminal repainting
  its whole buffer and is not ours to fix - but do not add to it.
- The focused control is marked with `›` in its first cell, so everything
  else carries `padding-left: 1` to line up.
- `Bar` computes its track length from its own width and refreshes on
  resize, so a narrow terminal shrinks the bar instead of overflowing.
  Checked at 20, 30, 38, 46, 66, 100 and 150 columns.

**Failures render in-app**, never as a traceback: `Bulb` raises, the
worker catches, and the text lands in `#message` with the same guidance
the CLI prints. `focus_moved` writes hints to that same line but bails
out while disconnected, so it cannot wipe an error message.

**A dropped reply is not a disconnection.** tinytuya's socket timeout is
5s and the bulb misses the odd status, so treating one failed read as
"lost contact" made the message flicker while the bulb was fine. `poll`
now needs `POLL_FAILURES_BEFORE_LOST` (3) failures *in a row* before it
gives up, and `POLL_FAILURE_WINDOW` expires stale ones so isolated blips
minutes apart never add up. The read-back after a write is the most
contended moment on the socket - its failure is swallowed entirely, since
the write already landed and the next poll re-syncs anyway.

**Disconnection is recoverable without restarting.** `r`
(`action_refresh_state`) polls while connected and **retries the
connection while not** - which also re-runs the LAN scan, so it is the
way back from a DHCP change. `connect()` calls `bulb.close()` first so a
retry never reuses a dead socket. A failed `poll` marks the app
disconnected rather than swallowing the error, which used to leave a
stale reading on screen indefinitely after the bulb was switched off.
`Bulb.read()` reports tinytuya's error text, not its raw payload dict.

`ctrl+p` opens Textual's built-in command palette. The *commands* in it are
free with `App` - they are not ours - but its **styling is**. By default it
is a full-width slab pinned to the top of the terminal; `tui.py` restyles it
into a centred overlay box (`width: 60`, `max-width: 90%`) with the same
`round $primary` border as the panel. Removable with
`ENABLE_COMMAND_PALETTE = False` if it ever gets in the way.

Those selectors reach into textual 8.x internals, so **check them after a
Textual upgrade**. Three things that are not obvious:

- `CommandPalette > Vertical` (`#--container`) is `visibility: hidden`, so a
  `background` set on it never paints and the panel shows through the
  overlay. The opaque background and the border have to go on the visible
  children - `#--input`, `CommandList`, `CommandInput`, `SearchIcon`.
- `#--input` needs a fixed `height: 3`. `auto` adds a trailing blank line.
- `SearchIcon` ships `margin-top: 1`. It looks like the stray blank line
  above the search row, but zeroing it drops the icon and the input onto
  different rows - leave it.

## Secrets policy

Nothing identifying the hardware is committed - not the key, Access
Secret, Access ID, device ID, MAC or IP. `config.py` is a loader only.
**Before adding any file that touches device values, check it against
`.gitignore`.**

Consequence: pushing this repo backs up *nothing*. `local_secrets.py` and
`CREDENTIALS.md` exist only on this drive.

## If the key stops working

Public procedure is in `TROUBLESHOOTING.md`; this machine's actual key
and IDs are in `CREDENTIALS.md` (gitignored). Summary: re-pairing the
bulb to new WiFi rotates the key;
moving routers while keeping the same SSID does not. An expired Tuya free
tier does not affect local control at all - it only blocks re-fetching
the key, and a fresh cloud project restores that.

## Where this is going

The **terminal interface** is built - `tui.py`, on Textual. The split it
needed is done: `device.py` holds the transport (`Bulb`, DPS reads and
writes) and knows nothing about argument parsing, `bulb.py` is the CLI on
top, and both drive the same `Bulb` class.

Still planned:

- **music reactivity** - drive the colour from live audio

Two pieces of the TUI exist specifically for it and should be reused
rather than rebuilt:

- `Bulb` holds **one persistent connection** (`set_socketPersistent`),
  so the per-command connection cost is paid once. Audio cannot afford a
  fresh connect per update.
- `LumenApp.queue_write` is a **trailing debounce** (150 ms) and the
  write worker is `exclusive`, so a burst of changes collapses to one
  write and a newer write cancels an older one still on the socket. That
  is the rate cap that keeps the bulb from being flooded; audio needs the
  same thing with a shorter window.

Ideas parked deliberately, not forgotten: adding the bulb's own commands
(colours, presets) to the `ctrl+p` palette via a `Provider`. It works -
it was built and then rewound - but the UI wants other tweaks first.

Nothing here is Syska-specific. `device.py` speaks Tuya 3.3 to a `dj`
device, so it should work on most Tuya/SmartLife bulbs - worth keeping
that generality.

## Before making the repo public

The repo exists: **https://github.com/exorev07/Lumen** (note the
capital L). It is MIT licensed - `LICENSE` came from GitHub's dropdown
at creation, so the first push merged that commit in with
`--allow-unrelated-histories`.

Topics to set: tuya, smartlife, tuya-local, tinytuya, smart-bulb,
smart-home, home-automation, local-control, iot, cli, tui, python,
rgb-lighting, music-reactive, syska.

Description while private (the TUI now exists, but music reactivity does
not, so hold off on the second version until it does):

> Terminal app for Tuya / SmartLife smart bulbs - local LAN control, no
> cloud round-trip.

Swap to this when flipping public:

> Terminal app for Tuya / SmartLife smart bulbs - local LAN, no cloud,
> music-reactive. No hub required.

Keep it under ~90 characters; GitHub truncates around 100-110 in search
results. Public is a one-way door - it can be flipped later, but not
unpublished.

Still to do:

- **Write a `README.md`.** There is no README at all right now - the
  old one was deleted deliberately, because it read as a personal log
  ("Status: working", "One-time setup (already done)") that assumed an
  already-configured machine. A stranger arrives with no key, no device
  ID and no cloud project.

  The deleted file is not lost: it is in git history, and most of it was
  reusable. Recover it with

  ```
  git show 7ccdb55:README.md
  ```

  and keep the parts that were already fine - the device blurb, the
  layout table, install, the full usage list with named colours, and
  especially the **step-by-step Tuya wizard walkthrough** (create the
  cloud project in the matching data centre, subscribe to IoT Core /
  Authorization / Scene Linkage, link the SmartLife account by QR, run
  `python -m tinytuya wizard`, copy the key out of `devices.json`). That
  walkthrough is the hard-won part and should not be rewritten from
  scratch.

  What to drop or rephrase: the "Status: working" section and the
  "(already done)" framing, which only make sense on this machine.
- ~~Dead `CREDENTIALS.md` links~~ - **done.** The generic recovery
  procedure now lives in `TROUBLESHOOTING.md`, which is committed, and
  the `bulb.py` error messages point there instead. `CREDENTIALS.md`
  keeps only this machine's actual identifiers and stays gitignored.
  Keep it that way: procedure is public, values are not.
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
