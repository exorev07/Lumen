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
linked, and the key is configured.

**Do not re-run the Tuya wizard unless the key has actually rotated.**

Settings now live in a **per-user TOML file**, not in `local_secrets.py`:

```
Windows   %APPDATA%\lumen\config.toml
macOS     ~/Library/Application Support/lumen/config.toml
Linux     $XDG_CONFIG_HOME/lumen/config.toml, else ~/.config/lumen/
```

`lumen config` prints the path. `local_secrets.py` is still *read* as a
migration path so this machine kept working across the restructure, but
nothing writes it any more - see the settings notes below.

## Layout

```
pyproject.toml             packaging; deps and the `lumen` entry point
src/lumen/__init__.py      __version__ - the one place it is defined
src/lumen/device.py        transport - connect, DPS reads and writes
src/lumen/tui.py           the terminal interface (Textual)
src/lumen/cli.py           the CLI - argument parsing, dispatch
src/lumen/config.py        Settings: load, save, env precedence
README.md                  public front page; also the PyPI description
requirements.txt           just `-e .` now; deps live in pyproject
tuya-data/                 wizard/scan JSON output         [gitignored]
TROUBLESHOOTING.md         failure modes and recovery - public
CREDENTIALS.md             this machine's key + IDs         [gitignored]
local_secrets.py           pre-0.1 secrets, read only for migration
                                                           [gitignored]
```

Installed as **`lumen-bulb`** on PyPI (plain `lumen` is taken) but the
command it installs is `lumen`. The `src/` layout is deliberate: it makes
it impossible to import the package from the source tree by accident, so
a broken wheel cannot pass tests locally.

`bulb.cmd` and `local_secrets.example.py` are **gone.** Do not add a
launcher script back - `lumen` is the entry point, and the goal is an app
that behaves like any other installed terminal program.

## Usage

```
lumen                         opens the app
lumen status | on | off | toggle
lumen brightness 60           1-100
lumen color red               name or "#RRGGBB"
lumen warm 80                 0 = cool, 100 = warm
lumen config                  where settings are stored
lumen --version
```

From a checkout without installing:
`PYTHONPATH=src python -m lumen.cli <command>`.

In the interface: `↑/↓` (or `tab`) move between controls. On the mode row,
`←/→` switch between white and colour. On a bar, `←/→` adjust it -
`shift` for single steps, `home`/`end` to jump. On the swatch grid, `←/→`
move along the row and `enter` picks. The controls that do nothing in the
current mode are hidden: warmth in colour mode, the swatches and hex input
in white mode. `space` toggles power,
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
  This was why `bulb.cmd` sat in the project folder; the package's `lumen`
  entry point retires that problem entirely. The ReadOnly
  attribute on Documents is a red herring - Defender is the real blocker.
- **There was a `bulb.ps1` as well as `bulb.cmd`;** having both made
  `.\bulb` ambiguous in PowerShell. Both are gone now - `lumen` is the
  entry point. Do not add a launcher script of either kind back.
- **Brightness is 10-1000 internally,** so a set of 40% can read back as
  39%. That rounding is expected, not a bug.
- **The bulb keeps two separate brightnesses, one per mode.** In *white*
  mode brightness is DPS 22. In *colour* mode DPS 22 is ignored entirely
  and brightness is the **V of the HSV in DPS 24** (same 10-1000 scale, so
  `raw_to_pct` decodes it unchanged). `BulbState.from_dps` reads 22 only
  when not in colour mode - reading it unconditionally was why picking a
  colour and then dragging brightness made the bar snap back to the
  white-mode value. `set_brightness_pct` writes to whichever the current
  mode uses.
- **`set_colour` sends RGB at full value,** so picking a swatch used to
  jump the bulb to 100%. `set_color_rgb(..., brightness=)` converts to HSV
  and carries the current level across instead.
- **A raw value of 0 decodes to -1%** without the clamp in `raw_to_pct`,
  and a negative percent raises `ValueError` inside tinytuya's
  `set_white_percentage`. Colour mode really can leave DPS 24's value at 0.
- **Status frames are sometimes partial** - the bulb answers with only the
  DPS that just changed. `BulbState.from_dps` merges over the previous
  state (`Bulb._last_state`) so an absent key keeps its value instead of
  reading as zero and blanking the display for a tick. `close()` clears it
  so a reconnect never carries stale state across.
- **A read straight after a write can return the pre-write value.** Mode in
  particular can lag one read behind the HSV. Allow ~1s to settle before
  asserting on state - this is the same staleness noted for back-to-back
  CLI commands, not a new bug.
- **`warm` preserves current brightness** by reading state first. It used
  to force 100%, which was wrong. The TUI's warmth bar does the same.
- **Warmth is inverted against the wire, on purpose.** DPS 23 is a *colour
  temperature*: raw 0 is the lowest colour temperature and therefore the
  **warmest** light, 1000 is cool blue-white. tinytuya passes the percentage
  straight through (`set_white_percentage` does `value_max * pct // 100`), so
  a bar labelled `warmth` that fed it directly went *cooler* as it rose - the
  reported bug. `raw_to_warmth` / `warmth_to_raw_pct` in `device.py` do the
  flip, and everything above the transport talks in warmth where **100 is
  warm**. Consequences: `.\bulb warm 80` now means warm, not cool, which is a
  deliberate reversal of what it used to do; `cli.py` prints `Warmth:` rather
  than `Colour temp:`. **`set_mode` has to re-encode** with `warmth_to_raw_pct`
  when it carries `state.warmth` back to `set_white_percentage` - passing the
  decoded value straight through would flip the temperature on every
  colour->white switch. The round-trip is exact at all 101 values, which is
  what keeps the TUI's `INTENT_TOLERANCE` reconciliation symmetric.
- **Warmth must not re-send brightness in white mode.** `set_white_percentage`
  takes brightness as a percent and does `1000 * pct // 100`, but `raw_to_pct`
  decodes with the 10-1000 offset - so a raw->percent->raw round trip loses up
  to 10 raw units, about 1%, *every call*. `set_warmth_pct` used to go through
  it unconditionally, so dragging the warmth bar walked brightness down a point
  per step: the reported "brightness changes erratically when I slide warmth".
  In white mode it now calls `set_colourtemp` instead, which writes DPS 23
  alone and leaves DPS 22 untouched. Verified: 12 warmth writes across the full
  range, zero drift.
- **But crossing from colour mode still has to carry brightness.** Colour
  temperature only exists in white mode, so a warmth write from colour mode
  switches modes, and the visible brightness moves from the HSV's V to DPS 22 -
  which holds whatever white mode last left. `set_warmth_pct` therefore
  branches on `state.is_colour`: `set_white_percentage` (carrying brightness)
  when crossing, `set_colourtemp` (brightness untouched) when already white.
  The TUI passes the state it holds, as it does for brightness. Verified with
  the white register parked at 90% and the colour at 24%: the crossing holds
  at 23%, where it used to jump to 90%.
- **`colorsys.rgb_to_hsv` returns `(h, s, v)`.** `set_color_rgb` unpacked it as
  `(hue, value, sat)`, swapping saturation and value. Invisible on the named
  swatches, which are all fully saturated (S and V both 1.0), but any muted hex
  colour came out oversaturated - teal `#508C82` (true S=0.43) was sent at
  S=1.0. Found while chasing the warmth bug, fixed alongside it.
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

## Settings and packaging

The app is a **package**, installed as `lumen-bulb`, providing the `lumen`
command. `pip install -e .` for development. Verified end to end: a wheel
builds, installs into a clean venv, and `lumen` works off PATH with no
`PYTHONPATH` and no project directory.

**Credentials cannot live next to the code.** `local_secrets.py` worked
only because the project folder was the working directory. Installed from
a wheel, that directory is read-only and may be shared between users, so
`config.py` became a `Settings` dataclass with `load()` / `save()` against
a TOML file in the per-user config dir. Consequences:

- **`_save_ip` no longer rewrites Python source.** It used to regex `IP =`
  inside `local_secrets.py`; now it calls `settings.save()`. Writing an
  importable module at runtime was always unpleasant and is impossible
  once installed.
- **Settings are injected, not imported.** `Bulb(settings=...)`, defaulting
  to `config.load()`. This is what lets the Settings screen hand over new
  credentials and reconnect without a restart - and it is the shape the
  planned device *list* needs, since two `Bulb`s can hold different
  settings. There is no module-level `DEVICE_ID` any more.
- **Saves are atomic** - written to `.toml.tmp` and `os.replace`d, so an
  interrupted save cannot leave half a key on disk. `chmod 600` on POSIX,
  best effort.
- **There is no stdlib TOML writer,** only a reader (`tomllib`). The three
  values are hand-quoted rather than taking a dependency; `_quote` escapes
  backslash and quote, verified round-tripping both.
- **A malformed config is not fatal.** It is treated as absent, so the app
  opens on Settings instead of tracebacking on a hand-edited typo.
- **Env vars are `LUMEN_*`,** with `SYSKA_*` kept as aliases - nothing here
  is Syska-specific. They win over the file, so the Settings screen says
  which fields the environment has pinned rather than letting an edit
  appear to work and then be ignored.

**The Settings screen (`s`) carries the setup instructions.** `SETUP_STEPS`
in `tui.py` walks from the Smart Life app to a local key. It lives next to
the fields on purpose: sending a stranger to a README defeats the point of
an app you just run. It is a `ModalScreen`; the steps scroll in a
`VerticalScroll` while the fields stay put, so Save is always reachable.
`enter` on the last field saves, `ctrl+s` anywhere, `escape` backs out.

- **It opens itself on first run** when nothing is configured. "Not
  connected" is the wrong message when the real answer is that setup has
  not happened.
- **Saving posts `SettingsScreen.Saved`;** the app swaps `bulb.settings`,
  clears `_intent` and calls `connect()`, which closes the old socket
  first. No restart, and a key change cannot leave the previous device
  open.
- The key field is `password=True`, so it is masked on screen.
- A failed save reports the error rather than dismissing - Controlled
  Folder Access is a real possibility on this machine.

Not done yet: **publishing.** `lumen-bulb` is confirmed free on PyPI but
nothing is uploaded; a first upload is irreversible, so it wants a
deliberate `twine upload`. After that, a **PyInstaller `.exe` on GitHub
Releases** is the goal for non-technical users - it must be a
*console-subsystem* build, since Textual needs a real terminal and a
double-clicked windowed binary has none.

## The TUI

`tui.py`, on Textual (`textual>=8.0,<9`, in `requirements.txt` - the
command-palette styling targets 8.x internals). One screen,
`LumenApp`, plus two small custom widgets.

**Threading is the thing to get right.** Every tinytuya call blocks on a
socket, so all of them run in `@work(thread=True)` workers and post back
with `call_from_thread`. Anything added later must do the same or it will
freeze the UI mid-render.

**One socket, one conversation at a time.** `poll` and `write` are in
different worker groups, so they genuinely run at the same time on
different threads - and they share the single persistent socket. Two
interleaved exchanges corrupt the stream's framing, and tinytuya surfaces
that as **`Unexpected Payload from Device`** (`ERR_PAYLOAD`, a decode
failure), which the TUI then showed as a red "Lost contact with the bulb"
while the bulb was perfectly fine. `Bulb` therefore holds an `RLock` and
every socket-touching method takes it. Reproduced at will by polling and
writing on two threads at ~0.15s: 4 errors in 20s before the lock, 0
after - and throughput roughly doubled, since nothing is lost to failed
exchanges and retries. The lock is **reentrant** because several writes
(`toggle`, `set_warmth_pct`, `set_mode`, `set_brightness_pct`) do a read
first and must hold it across both halves. Anything added to `device.py`
that touches `self._device` must take it too.

- `connect` / `poll` / `write` are each `exclusive` workers in their own
  group, so a newer one cancels an older one still waiting on the socket.
- `queue_write` is a **trailing debounce** (`WRITE_DEBOUNCE`, 150 ms).
  Holding an arrow key sends *one* write when you stop, not one per
  repeat. Verified: four rapid presses produce zero writes during the
  burst and one after.
- `poll` runs every `POLL_INTERVAL` (1.5 s) to catch changes made from the
  phone app, and **skips while a write is pending** so a stale read cannot
  yank a bar back under the user's fingers. It was 5 s, which made the status
  line feel stale - a change made on the phone took that long to appear, as
  did any value the bulb was slow to publish. Polling this hard is only safe
  because the socket is serialised (see the lock above).
- **Loss detection is in seconds, not polls.** `POLL_FAILURES_BEFORE_LOST` is
  derived from `SECONDS_BEFORE_LOST` (12 s) and the poll interval, so
  changing `POLL_INTERVAL` cannot quietly make the app trigger-happy. With a
  bare count of 3, dropping the interval to 1.5 s would have declared the
  bulb lost after 4.5 s of silence - well inside a normal blip, and the
  "lost contact" flicker would have come straight back.
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
- **The status line reports the bulb; the bars follow the user.** These are
  deliberately different. `apply_state` leaves `state` exactly as read, so
  the header always shows what the bulb actually said - if a write is
  refused, the bar shows what was asked for and the header keeps telling the
  truth. Only the *bars* consult `_intent`. An earlier attempt had the header
  echo the pending value to make it feel snappier; that defeats the point of
  a status line and was reverted.
- **A bar holds the user's value until the bulb confirms it** (`self._intent`).
  This is what stops the bars visibly twitching back and forth. Two separate
  sources of stale readings make it necessary, and `_pending` alone stops
  neither:
  - the bulb accepts a write but publishes the new value a beat later, so the
    read-back straight after a write still reports the *old* one;
  - a `poll` already blocked in `read()` when the write goes out returns
    pre-write data and lands *after* `_pending` has been cleared.

  So `apply_state` overrides a control with `_intent[name]` until a reading
  comes back within `INTENT_TOLERANCE` (2%, since brightness is 10-1000
  internally and 40% can read back as 39%), then releases it. `queue_write`
  records the intent at *keypress* time, not on completion, or a poll landing
  in between still shows the old value.

  Three things must stay true, and each has a test: intent **releases** on
  confirmation (or a change made from the phone app never reaches the bar
  again), a **failed** write drops its intent (or the bar is pinned to a value
  the bulb never took), and reconnecting clears it. A timestamp-based
  "discard readings older than the last write" was tried first and does not
  work - there is always a window where an in-flight read looks newer.
- **Guard each bar separately, not on `self._pending` as a whole.** The old
  `if not self._pending` froze brightness *and* warmth whenever any write was
  outstanding, so a pending colour write stopped both bars updating.

**Verified against the real bulb** (2026-09-02): the bars no longer twitch -
dragging brightness or warmth gives a clean 40-45-50-55-60 with no bounce,
in both modes, with the poll running 5x faster than normal to provoke the
race. Confirmed by *disabling* the intent hold and watching the real bulb
reproduce the reported 59 -> 39 -> 59 bounce, then restoring it. Also the
two-brightness behaviour - picking a colour then dragging brightness holds at 30%
and 75% instead of snapping back, brightness survives a mode switch in
both directions, warmth forces white mode and keeps its level. Also, and
earlier: the
burst-across-an-in-flight-write pattern that produced the `None` crash,
`warm` preserving brightness, named and hex colours, and toggle. Also
measured for flakiness - 20 sequential reads and 12s of concurrent
poll+write traffic on two threads gave **zero** failures, which is why the
blip tolerance above is a small retry threshold rather than something
heavier. Note that back-to-back CLI commands can still read stale state:
a `warm` issued immediately after a `brightness` re-applied the old value.

**Custom widgets.** Textual 8.x has no `Slider`, hence `Bar` - a focusable
0-100 widget that renders its own track. `Swatch` is one named colour.
`ModeTabs` is the white/colour selector. All three post messages
(`Bar.Changed`, `Swatch.Picked`, `ModeTabs.Changed`) rather than touching
the bulb directly.

**The mode row is not cosmetic.** White and colour are genuinely different
states on the bulb, with different brightness registers and only white
having a colour temperature. `show_mode_controls()` therefore hides the
controls that do nothing in the current mode - the warmth bar in colour
mode, the swatches, the `colour` label and the hex input in white mode -
via a `.hidden` class that sets `display: none`. Three consequences:

- `action_move` builds its order from `w.display`, so up/down never steps
  onto something invisible.
- `show_mode_controls` refocuses `#brightness` if the focused widget just
  disappeared, or focus would be stranded on a hidden control.
- `mode_changed` calls it *immediately* rather than waiting for the write
  and the next poll, so the panel updates the moment the key is pressed.

`ModeTabs.render` drops its `mode` label below 28 columns, the same way
`Bar` shrinks its track, instead of letting the tabs clip off the edge.

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

**A poll can land while the app is quitting.** `apply_state` queries
`#power`, `#brightness` and friends from a worker callback, and on unmount
those nodes are gone - the worker then dies with
`NoMatches: No nodes match '#power'`. Two halves to the fix: `on_unmount`
stops the poll timer *before* closing the socket so the work is never
scheduled, and `apply_state` catches `NoMatches` anyway. Pressing `q` during
an in-flight poll used to take a worker down with it.

**`open()` holds the lock for the whole reconnect** (`_open_locked`). `r`
can retry while a poll is still in flight, and swapping `self._dev`
underneath a thread mid-exchange is the same framing corruption the lock
exists to prevent. This means a reconnect's ~12s LAN scan blocks reads for
its duration, which is correct - there is no usable socket during it anyway.

**Failures render in-app**, never as a traceback: `Bulb` raises, the
worker catches, and the text lands in `#message` with the same guidance
the CLI prints. **That has to hold for unexpected exception types too.**
Every worker catches `BulbError` for the expected failures and then
`Exception` for everything else, formatted by `_unexpected()` as
`Unexpected <Type>: <message>`. Without the second clause an exception
escaping a `@work(thread=True)` worker kills it and Textual paints the
traceback over the panel - and in `write` it also leaves `_pending` set,
so `poll` stays blocked and the app is dead until restarted. This is not
hypothetical: tinytuya exports `DecodeError`, which does not inherit from
`BulbError`, and a socket dropped mid-call raises `OSError`. It was found
when a stub missing `set_colourtemp` took the write worker down with an
`AttributeError`. The two kinds read differently on purpose - a
`BulbError` is the bulb being unreachable, an `Unexpected` is a bug worth
reporting. The one place the distinction does not matter is the
confirming read after a write, which swallows everything: the write
already landed and the next poll re-syncs. `focus_moved` writes hints to that same line but bails
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

**The goal: a terminal app anyone with a Tuya/SmartLife device can
install and run.** Not a personal script that happens to be shared - a
thing a stranger installs, points at their own bulb, and uses. That is
the bar every decision here should be measured against, and it is mostly
a packaging and onboarding problem now rather than a protocol one: the
hard part (local control without the cloud) works.

What that implies, roughly in order:

- ~~**Onboarding a stranger.**~~ - **done.** The Settings screen (`s`,
  and it opens itself on first run) carries the walkthrough and writes
  the config, so nobody hand-edits a file. `README.md` repeats it for
  people reading on GitHub.
- **Installable** - **half done.** `pip install lumen-bulb` works from a
  built wheel and puts `lumen` on PATH; `bulb.cmd` is gone. Still to do:
  the actual PyPI upload, and a single `.exe` for people who do not have
  Python. See the packaging section above.
- **Multiple devices,** later. `Bulb` is deliberately one device with one
  socket, and `config` holds a single `DEVICE_ID`/`LOCAL_KEY`/`IP`. Going
  multi-device means a device *list* and a picker in the UI, with each
  device holding its own connection. Worth keeping in mind when touching
  either file - do not add anything that assumes there is exactly one
  bulb forever - but not worth building until one device is genuinely
  finished.

Nothing here is Syska-specific, and that is load-bearing rather than
incidental: `device.py` speaks Tuya 3.3 to a `dj` device, so it should
already work on most Tuya/SmartLife colour bulbs. Keep that generality.
Anything that only makes sense for this one bulb belongs behind a check,
not baked into the transport.

The **terminal interface** is built - `tui.py`, on Textual. The split it
needed is done: `device.py` holds the transport (`Bulb`, DPS reads and
writes) and knows nothing about argument parsing, `cli.py` is the CLI on
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

- ~~**Write a `README.md`**~~ - **done.** Written for a stranger: install,
  keys, usage, the wizard walkthrough, where settings live, supported
  devices. It is also the PyPI description, so `pyproject.toml` reads it -
  **deleting it breaks the build.**

  It deliberately does *not* repeat the old personal-log framing ("Status:
  working", "already done"). The pre-deletion version is still in history
  at `git show 7ccdb55:README.md` if something turns out to be missing.

- ~~Dead `CREDENTIALS.md` links~~ - **done.** The generic recovery
  procedure now lives in `TROUBLESHOOTING.md`, which is committed, and
  the `cli.py` error messages point there instead. `CREDENTIALS.md`
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
hub, no plugin, no writing code against a library. The TUI now exists, so
half of that is true; what is still missing is the *just run* part - a
stranger currently has to clone the repo and hand-fill a key. Closing
that gap (see the onboarding and packaging points above) matters more to
the pitch than any further feature does, music reactivity included.

Pitch accordingly. Not "local Tuya control" - that ground is well
covered and Home Assistant owns it. Rather: *control your bulb from the
terminal, no hub required.* Keep the `tuya-local` topic anyway, to catch
people who searched it and did not want to install Home Assistant.
