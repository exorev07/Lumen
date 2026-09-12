"""Terminal interface for the bulb.

Every call into tinytuya blocks on a socket, so all of them run in worker
threads and post their results back to the UI thread. Slider moves are
coalesced behind a short timer - dragging brightness end to end should be
one write at the end, not forty on the way.
"""

import time
import threading

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Static

from . import config
from .device import (COLORS, MODE_COLOUR, MODE_WHITE, Bulb, BulbError,
                     BulbState, parse_color)

# Trailing debounce on slider writes. Long enough to swallow a held arrow
# key, short enough that a single tap still feels immediate.
WRITE_DEBOUNCE = 0.15

# How often to reconcile with the bulb, in seconds. Catches changes made
# from the phone app or another terminal. 5s made the status line feel
# stale - a change from the phone took that long to show, and so did a
# reading the bulb was slow to publish. The socket is serialised now, so
# polling harder no longer risks colliding with a write.
POLL_INTERVAL = 1.5

# Consecutive failed reads before the bulb counts as gone. One dropped reply
# is routine. Expressed in seconds of silence rather than a count, so that
# changing POLL_INTERVAL cannot quietly make the app trigger-happy about
# declaring the bulb lost - at 1.5s a bare count of 3 would give up after
# 4.5s, which is well inside a normal blip.
SECONDS_BEFORE_LOST = 12.0
POLL_FAILURES_BEFORE_LOST = max(3, round(SECONDS_BEFORE_LOST / POLL_INTERVAL))

# Failures older than this start a fresh streak, so unrelated blips minutes
# apart never add up to a false "lost contact".
POLL_FAILURE_WINDOW = SECONDS_BEFORE_LOST

# Bar track bounds. The track grows with the panel rather than stopping at a
# fixed width: at 120 columns a 24-cell bar left most of the panel empty and
# made the app look like a dialog that had been stretched. BAR_WIDTH_MAX keeps
# a very wide terminal from turning the bars into one long thin line, where a
# 1% step is several cells and the eye cannot judge the level.
BAR_WIDTH_MIN = 8
BAR_WIDTH_MAX = 72

# The caret and the label that sit before the track. The click hit-testing
# and render() both work off this, so a click cannot land on a different
# cell than the one it appears to be over.
BAR_CARET_CELLS = 1
BAR_LABEL_CELLS = BAR_CARET_CELLS + 12

# Everything on the row that is not track: the above, plus the gap, the
# space and the 3-cell readout after it, plus the panel's right padding.
BAR_CHROME = BAR_LABEL_CELLS + 1 + 3 + 3

# Caret, block, space and the longest colour name ("magenta").
SWATCH_WIDTH = 12

# Swatch columns. Ten colours, so 5 gives the tidy two rows; a wide terminal
# is allowed to go to 10 and put them on one line rather than leaving the
# space unused. A narrower one wraps onto more rows.
SWATCH_COLUMNS_MIN = 1
SWATCH_COLUMNS_PREFERRED = 5
SWATCH_COLUMNS_MAX = 10


class Bar(Widget, can_focus=True):
    """A focusable 0-100 bar. Left/right adjust, home/end jump."""

    DEFAULT_CSS = """
    Bar {
        height: 1;
        width: 1fr;
        layout: horizontal;
    }
    Bar:focus { text-style: bold; }
    """

    BINDINGS = [
        Binding("left", "adjust(-5)", "-5", show=False),
        Binding("right", "adjust(5)", "+5", show=False),
        Binding("shift+left", "adjust(-1)", "-1", show=False),
        Binding("shift+right", "adjust(1)", "+1", show=False),
        Binding("home", "set_value(0)", "min", show=False),
        Binding("end", "set_value(100)", "max", show=False),
    ]

    value = reactive(0)

    class Changed(Message):
        """The user moved this bar."""

        def __init__(self, bar, value):
            super().__init__()
            self.bar = bar
            self.value = value

        @property
        def control(self):
            return self.bar

    def __init__(self, label, minimum=0, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.minimum = minimum

    def track_width(self, width=None):
        """Track fills whatever the label and readout leave, within bounds.

        It grows with the panel instead of stopping at a fixed width - a
        24-cell bar in a 120-column terminal was most of why the app looked
        like a stretched dialog. Still clamped at both ends: below
        BAR_WIDTH_MIN there is nothing to read, and past BAR_WIDTH_MAX a
        single step is several cells wide and the level gets harder, not
        easier, to judge.
        """
        if width is None:
            width = self.size.width
        return max(BAR_WIDTH_MIN, min(BAR_WIDTH_MAX, width - BAR_CHROME))

    def render(self):
        width = self.track_width()
        filled = round(self.value / 100 * width)
        rest = "─" * (width - filled)
        if self.has_focus:
            caret = "[$primary]›[/]"
            track = f"[$primary]{'█' * filled}[/][$panel]{rest}[/]"
            label = f"[$text]{self.label:<12}[/]"
        else:
            caret = " "
            track = f"[$text-muted]{'█' * filled}[/][$panel]{rest}[/]"
            label = f"[$text-muted]{self.label:<12}[/]"
        return f"{caret}{label}{track} [$text-muted]{self.value:>3}[/]"

    def action_adjust(self, delta):
        self.action_set_value(self.value + delta)

    def action_set_value(self, value):
        value = max(self.minimum, min(100, int(value)))
        if value != self.value:
            self.value = value
            self.post_message(self.Changed(self, value))

    def set_quietly(self, value):
        """Update from a poll without echoing a write back to the bulb."""
        self.value = max(self.minimum, min(100, int(value)))

    def on_resize(self, event):
        # The track is clamped to BAR_WIDTH, so most resize steps do not
        # change it at all. Repainting anyway is what makes a drag-resize
        # look like it is shaking.
        if self.track_width(event.size.width) != self.track_width():
            self.refresh()


class ModeTabs(Widget, can_focus=True):
    """White / colour selector.

    The bulb is only ever in one of these, and they are not cosmetic: white
    mode dims on DPS 22 and has a colour temperature, colour mode dims on the
    V of its HSV and ignores temperature entirely. Making the mode explicit is
    what stops the two sets of controls looking like they contradict.
    """

    DEFAULT_CSS = """
    ModeTabs {
        height: 1;
        width: 1fr;
        margin: 0 0 1 0;
    }
    ModeTabs:focus { text-style: bold; }
    """

    BINDINGS = [
        Binding("left", "step(-1)", "prev", show=False),
        Binding("right", "step(1)", "next", show=False),
        Binding("enter", "pick", "set", show=False),
    ]

    MODES = (MODE_WHITE, MODE_COLOUR)
    LABELS = {MODE_WHITE: "white", MODE_COLOUR: "colour"}

    mode = reactive(MODE_WHITE)

    class Changed(Message):
        def __init__(self, mode):
            super().__init__()
            self.mode = mode

    def render(self):
        caret = "[$primary]›[/]" if self.has_focus else " "
        cells = []
        for name in self.MODES:
            label = self.LABELS[name]
            if name == self.mode:
                cells.append(f"[$primary reverse] {label} [/]")
            elif self.has_focus:
                cells.append(f"[$text] {label} [/]")
            else:
                cells.append(f"[$text-muted] {label} [/]")
        tabs = " ".join(cells)
        # "mode" + two padded labels needs ~28 cells. Below that, drop the
        # label rather than let the tabs run off the right edge - the same
        # thing Bar does with its track.
        if self.size.width and self.size.width < 28:
            return f"{caret}{tabs}"
        return f"{caret}{'mode':<12}" + tabs

    def on_resize(self, event):
        # Only the crossing of the 28-cell threshold changes the output.
        was = (self.size.width or 0) < 28
        if was != (event.size.width < 28):
            self.refresh()

    def set_quietly(self, mode):
        """Reflect the bulb without asking it to switch back."""
        if mode in self.MODES:
            self.mode = mode

    def action_step(self, delta):
        index = self.MODES.index(self.mode) + delta
        if 0 <= index < len(self.MODES):
            self.mode = self.MODES[index]
            self.post_message(self.Changed(self.mode))

    def action_pick(self):
        self.post_message(self.Changed(self.mode))


class Swatch(Static, can_focus=True):
    """One named colour. Enter or space sets it."""

    DEFAULT_CSS = """
    Swatch {
        width: 12;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("enter", "pick", "set", show=False),
        Binding("space", "pick", "set", show=False),
        Binding("left", "step(-1)", "prev", show=False),
        Binding("right", "step(1)", "next", show=False),
    ]

    class Picked(Message):
        def __init__(self, rgb, name):
            super().__init__()
            self.rgb = rgb
            self.name = name

    def __init__(self, name, rgb, **kwargs):
        super().__init__(**kwargs)
        self.color_name = name
        self.rgb = rgb

    def render(self):
        r, g, b = self.rgb
        block = f"[rgb({r},{g},{b})]██[/]"
        if self.has_focus:
            return f"[$primary]›[/]{block} [$text]{self.color_name}[/]"
        return f" {block} [$text-muted]{self.color_name}[/]"

    def action_pick(self):
        self.post_message(self.Picked(self.rgb, self.color_name))

    def action_step(self, delta):
        """Move along the swatches. They are one wrapping grid, so left at the
        start of a row steps back onto the end of the row above."""
        swatches = list(self.parent.query(Swatch))
        index = swatches.index(self) + delta
        if 0 <= index < len(swatches):
            swatches[index].focus()


def _unexpected(exc):
    """Text for an exception that is not a BulbError.

    Those are bugs, not the bulb being unreachable, so they read differently -
    but they still have to reach the message line. An exception escaping a
    worker takes the worker down and paints a traceback over the panel.
    """
    return "Unexpected %s: %s" % (type(exc).__name__, exc)


# Shown in the Settings screen. Kept here rather than in a README because the
# whole point is that someone who has only ever used the SmartLife app can get
# from nothing to a working key without leaving the app.
SETUP_STEPS = """Lumen talks to your bulb directly over WiFi, so it needs two values that
only your Tuya account can give you: the device ID and its local key.

  1. Pair the bulb in the Smart Life app first, if you have not already.
     Lumen does not pair devices - it controls ones already on your WiFi.

  2. Sign up at iot.tuya.com (free) and create a Cloud project. Pick the
     data centre for the region your Smart Life account is in - the wrong
     one returns no devices.

  3. In that project, subscribe to IoT Core, Authorization and Smart Home
     Scene Linkage. All three are free.

  4. Open Devices -> Link Tuya App Account and link your Smart Life
     account by scanning the QR code with the app.

  5. Install tinytuya's wizard and run it:

         pip install tinytuya
         python -m tinytuya wizard

     Give it the Access ID and Access Secret from your project's overview
     page, and the data centre you chose.

  6. The wizard writes devices.json. Your bulb's entry holds "id" and
     "key" - those are the two values below.

The IP is optional: leave it blank and Lumen scans your network for the
bulb, then remembers where it found it.
"""


class SettingsScreen(ModalScreen):
    """Credentials, and the instructions for obtaining them.

    A stranger installing this has no key and no idea where to get one, and
    sending them to a README defeats the point of an app you just run. So the
    walkthrough lives next to the fields it is describing.

    Saving writes the config file and hands the new settings back to the app,
    which reconnects without a restart.
    """

    BINDINGS = [
        Binding("escape", "cancel", "back"),
        Binding("ctrl+s", "save", "save"),
    ]

    CSS = """
    SettingsScreen {
        align: center middle;
        background: $surface 60%;
    }

    #settings-box {
        width: 90%;
        max-width: 100;
        height: 90%;
        padding: 1 2;
        border: round $primary;
        border-title-color: $primary;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        background: $surface;
    }

    /* The steps scroll; the fields below them stay put, so the Save row is
       always reachable without scrolling to the bottom. */
    #steps {
        height: 1fr;
        min-height: 6;
        padding: 0 1;
        color: $text-muted;
        scrollbar-size-vertical: 1;
    }

    #fields { height: auto; padding-top: 1; }

    #fields Label { padding-left: 1; color: $text-muted; }
    #fields Input { margin-bottom: 1; }

    #settings-message { padding-left: 1; height: auto; }
    #settings-message.error { color: $error; }
    #settings-message.ok { color: $success; }
    """

    class Saved(Message):
        """New settings were written; the app should reconnect."""

        def __init__(self, settings):
            super().__init__()
            self.settings = settings

    def __init__(self, settings):
        super().__init__()
        self._settings = settings

    def compose(self) -> ComposeResult:
        box = Vertical(id="settings-box")
        box.border_title = "SETTINGS"
        box.border_subtitle = "ctrl+s save · esc back"
        with box:
            with VerticalScroll(id="steps"):
                yield Static(SETUP_STEPS)
            with Vertical(id="fields"):
                yield Label("device id")
                yield Input(
                    value=self._settings.device_id,
                    placeholder="e.g. bf1a2b3c4d5e6f7a8b9c0d",
                    id="f-device-id",
                )
                yield Label("local key")
                yield Input(
                    value=self._settings.local_key,
                    placeholder="22 characters from devices.json",
                    password=True,
                    id="f-local-key",
                )
                yield Label("ip address (optional)")
                yield Input(
                    value=self._settings.ip,
                    placeholder="blank to scan the network",
                    id="f-ip",
                )
            yield Static("", id="settings-message")
        yield Footer()

    def on_mount(self):
        # Env vars override the file, so editing a field the environment has
        # pinned would appear to work and then be silently ignored on load.
        # Say so instead, and leave the field alone.
        pinned = [f for f in ("device_id", "local_key", "ip")
                  if self._settings.locked_by_env(f)]
        if pinned:
            self._say(
                "Set in the environment, so changes here will not apply: "
                + ", ".join(pinned),
            )
        self.query_one("#f-device-id", Input).focus()

    def _say(self, text, error=False, ok=False):
        widget = self.query_one("#settings-message", Static)
        widget.update(text)
        widget.set_class(error, "error")
        widget.set_class(ok, "ok")

    def _collect(self):
        return (
            self.query_one("#f-device-id", Input).value.strip(),
            self.query_one("#f-local-key", Input).value.strip(),
            self.query_one("#f-ip", Input).value.strip(),
        )

    @on(Input.Submitted)
    def submitted(self):
        """Enter on the last field saves; on the others it moves on.

        Filling three fields and pressing enter is the obvious gesture, and
        it should not require finding ctrl+s.
        """
        if self.focused is self.query_one("#f-ip", Input):
            self.action_save()
        else:
            self.focus_next()

    def action_cancel(self):
        self.dismiss(None)

    def action_save(self):
        device_id, local_key, ip = self._collect()
        if not device_id or not local_key:
            self._say("Device id and local key are both required.", error=True)
            return

        settings = config.Settings(
            device_id=device_id,
            local_key=local_key,
            ip=ip,
            from_env=self._settings.from_env,
        )
        try:
            path = settings.save()
        except OSError as exc:
            # Disk full, a read-only profile, Defender's Controlled Folder
            # Access. Report it rather than pretending the save worked.
            self._say("Could not save: %s" % exc, error=True)
            return
        except Exception as exc:                      # noqa: BLE001
            self._say(_unexpected(exc), error=True)
            return

        self.post_message(self.Saved(settings))
        self.dismiss(str(path))


class LumenApp(App):
    """The whole interface - one screen."""

    TITLE = "lumen"

    CSS = """
    Screen {
        background: $surface;
    }

    /* The one box everything lives in. It fills the terminal rather than
       floating in the middle of it - this is the whole app, not a dialog. */
    #panel {
        width: 100%;
        height: 100%;
        padding: 1 2;
        border: round $primary;
        border-title-color: $primary;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        background: $surface;
    }

    /* One cell of left padding lines these up with the bars, whose first
       cell is the focus caret. */
    #power, .section, #hex, #message { padding-left: 1; }

    /* Warmth is meaningless in colour mode, so it is hidden there rather than
       left on screen doing nothing. [hidden] removes it from the layout. */
    #warmth.hidden, #swatches.hidden, #hex.hidden, #colour-label.hidden {
        display: none;
    }

    #power {
        height: 1;
        margin: 0 0 1 0;
        color: $text-muted;
    }
    #power.on { color: $success; }
    #power.off { color: $text-muted; }

    Bar { margin: 0 0 0 0; }

    .section {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
        text-style: dim;
    }

    /* A grid rather than fixed rows, so a narrow terminal wraps the colours
       onto more rows instead of hiding the ones past the right edge. The
       column count is recomputed from the width in reflow_swatches(). */
    #swatches {
        width: 100%;
        height: auto;
        layout: grid;
        grid-size: 5;
        grid-rows: 1;
        grid-gutter: 0;
        /* Fixed columns, so the swatches stay tightly spaced instead of
           being stretched apart to fill a wide panel. */
        grid-columns: 12;
    }

    #hex {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        border: none;
        padding: 0;
        background: $surface;
        color: $text;
    }
    #hex:focus { background: $boost; }

    /* Absorbs the leftover height, pushing #message to the bottom of the
       panel. min-height 0 so a short terminal gives it nothing rather than
       squeezing a control off the screen. */
    #spacer {
        height: 1fr;
        min-height: 0;
    }

    #message {
        height: auto;
        margin: 0;
        color: $text-muted;
        text-style: dim;
    }
    #message.error { color: $error; text-style: none; }

    Footer { background: $surface; }

    /* Textual's built-in palette (ctrl+p) is full-width and top-anchored by
       default, which looks nothing like the rest of this app. Make it a
       compact centred overlay with the same rounded border as the panel.
       These selectors track textual 8.x internals - see CLAUDE.md. */
    CommandPalette > Vertical {
        width: 60;
        max-width: 90%;
        margin-top: 6;
        height: auto;
        border: round $primary;
        background: $surface;
    }
    /* The outer #--container is visibility:hidden, so a background set on it
       never paints - the panel behind shows through the overlay. The opaque
       background has to go on the visible children instead. */
    CommandPalette #--input {
        background: $panel;
        border: round $primary;
        border-bottom: none;
        /* Fixed, not auto: auto adds a trailing blank line under the input.
           The leading blank line is SearchIcon's own margin-top, which has to
           stay or the icon and the text land on different rows. */
        height: 3;
    }
    CommandPalette #--input.--list-visible {
        border-bottom: none;
    }
    CommandList {
        background: $panel;
        border-top: none;
        border-bottom: round $primary;
        border-left: round $primary;
        border-right: round $primary;
        max-height: 12;
        padding: 0 1;
    }
    CommandInput, CommandInput:focus {
        background: $panel;
        padding-left: 1;
    }
    /* Leave SearchIcon's own margin-top alone - it is what keeps the icon on
       the same line as the input text. */
    SearchIcon { color: $primary; background: $panel; }
    """

    BINDINGS = [
        Binding("space", "toggle_power", "toggle"),
        Binding("o", "power_on", "on"),
        Binding("f", "power_off", "off"),
        Binding("r", "refresh_state", "refresh"),
        Binding("s", "settings", "settings"),
        Binding("q", "quit", "quit"),
        Binding("down", "move(1)", "next", show=False),
        Binding("up", "move(-1)", "prev", show=False),
        Binding("tab", "focus_next", "next", show=False),
        Binding("shift+tab", "focus_previous", "prev", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.bulb = Bulb(on_message=self.note)
        self.state = BulbState()
        self.connected = False
        self._pending = {}      # what a debounced write should send
        self._debounce = {}     # per-control debounce timers
        self._poll_timer = None     # stopped on unmount
        self._read_failures = 0     # consecutive failed polls
        self._last_failure = 0.0    # when the last one was
        # What the user last asked each control to be, kept until the bulb
        # reports that value back. A reading that disagrees is pre-write
        # state that arrived late, and must not move the control.
        self._intent = {}

    # -- layout ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        panel = Vertical(id="panel")
        panel.border_title = "LUMEN"
        panel.border_subtitle = "tuya · local"
        with panel:
            yield Label("connecting...", id="power")

            yield ModeTabs(id="mode")

            yield Bar("brightness", minimum=1, id="brightness")
            yield Bar("warmth", id="warmth")

            yield Label("colour", id="colour-label", classes="section")
            with Container(id="swatches"):
                for name in COLORS:
                    yield Swatch(name, COLORS[name])

            yield Input(placeholder="#rrggbb", id="hex")

            # Takes up the slack, so the message line sits on the panel's
            # bottom edge rather than floating under the controls with the
            # rest of the panel empty beneath it - and fills that space with
            # the bulb's current colour instead of nothing. Height 1fr, so a
            # short terminal gives it nothing and the controls still fit.
            # Takes up the slack so the message line sits on the panel's
            # bottom edge instead of floating under the controls with the
            # rest of the panel empty beneath it. Height 1fr, so it is
            # whatever is left after the fixed-height controls above - and
            # nothing at all when the terminal is too short to spare any.
            yield Static("", id="spacer")

            yield Static("", id="message")

        yield Footer()

    def on_mount(self):
        self.reflow_swatches()
        self._poll_timer = self.set_interval(POLL_INTERVAL, self.poll)
        # A first run has no credentials, and "not connected" is unhelpful
        # when the real answer is that nothing has been set up yet. Open
        # Settings straight away instead of failing a connection first.
        if not self.bulb.settings.is_configured:
            self._on_disconnected(
                "No device configured yet - fill in Settings to begin."
            )
            self.action_settings()
        else:
            self.connect()

    def on_resize(self, event):
        # Take the width from the event: self.size still holds the old one
        # at this point, so reflowing from it lags a resize behind.
        self.reflow_swatches(event.size.width)

    def reflow_swatches(self, width=None):
        """Fit as many swatches per row as the width allows.

        Fixed rows meant the last colours simply vanished off the right edge
        of a narrow terminal. As a grid they wrap onto another row instead.
        """
        try:
            grid = self.query_one("#swatches")
        except NoMatches:
            return
        if width is None:
            width = self.size.width
        # The panel's border and padding cost 6 cells; each swatch needs
        # SWATCH_WIDTH.
        usable = width - 6
        fits = usable // SWATCH_WIDTH

        # Prefer the tidy 5-wide pair of rows. Only go wider when *all ten*
        # fit on one line - anything between leaves a ragged half-row (7
        # columns puts 3 on the second), which looks worse than the pair.
        # Narrower wraps onto more rows rather than hiding the colours past
        # the right edge, which is what fixed rows used to do.
        if fits >= SWATCH_COLUMNS_MAX:
            columns = SWATCH_COLUMNS_MAX
        elif fits >= SWATCH_COLUMNS_PREFERRED:
            columns = SWATCH_COLUMNS_PREFERRED
        else:
            columns = max(SWATCH_COLUMNS_MIN, fits)

        if grid.styles.grid_size_columns != columns:
            grid.styles.grid_size_columns = columns

    # -- messages --------------------------------------------------------

    def note(self, text, error=False):
        """Progress or failure, shown in-app. Safe to call from any thread -
        Bulb calls this from the connect worker while it scans the LAN."""
        if threading.current_thread() is threading.main_thread():
            self._set_message(text, error)
        else:
            self.call_from_thread(self._set_message, text, error)

    def _set_message(self, text, error=False):
        """Write to the message line, if there is one to write to.

        `#message` lives on the main panel, so it is absent in two situations
        that both reach here: before compose has mounted it (a DescendantFocus
        fires as the first Bar takes focus, which is early enough to lose the
        race) and while a modal screen is on top. Neither is worth an
        exception - a hint nobody can see is not an error, and raising from a
        focus handler crashes the app with a traceback over the panel.
        """
        try:
            widget = self.query_one("#message", Static)
        except NoMatches:
            return
        widget.update(text)
        widget.set_class(error, "error")

    # -- connection and polling -----------------------------------------

    @work(thread=True, exclusive=True, group="connect")
    def connect(self):
        # Drop any half-open socket first, so a retry after a failure starts
        # clean rather than reusing a device that has already gone away.
        self.bulb.close()
        try:
            self.bulb.open()
            state = self.bulb.read()
        except BulbError as exc:
            self.call_from_thread(
                self._on_disconnected, "%s\nPress r to try again." % exc
            )
            return
        except Exception as exc:                      # noqa: BLE001
            # Not a BulbError, so a bug rather than an unreachable bulb -
            # tinytuya's DecodeError, a socket error, a missing attribute.
            self.call_from_thread(
                self._on_disconnected,
                "%s\nPress r to try again." % _unexpected(exc),
            )
            return
        self.call_from_thread(self._on_connected, state)

    def _on_connected(self, state):
        self.connected = True
        self._intent.clear()
        self._read_failures = 0
        self._last_failure = 0.0
        self._set_message("")
        self.apply_state(state)
        self.query_one("#brightness", Bar).focus()

    def _on_disconnected(self, text):
        self.connected = False
        power = self.query_one("#power", Label)
        power.update("[$error]○[/]  not connected")
        power.set_classes([])
        self._set_message(text, error=True)

    @work(thread=True, exclusive=True, group="poll")
    def poll(self):
        """Reconcile with the bulb. Skips while a write is in flight so a
        stale read cannot yank a slider back under the user's fingers."""
        if not self.connected or self._pending:
            return
        try:
            state = self.bulb.read()
        except BulbError as exc:
            # One dropped reply is normal - tinytuya's socket timeout is 5s
            # and the bulb misses the odd status. Only call it lost after
            # several in a row, or the display flickers "lost contact" while
            # the bulb is in fact fine.
            # Count only *consecutive recent* failures. Without the window,
            # three unrelated blips minutes apart would eventually add up and
            # report a healthy bulb as gone.
            now = time.monotonic()
            if now - self._last_failure > POLL_FAILURE_WINDOW:
                self._read_failures = 0
            self._last_failure = now
            self._read_failures += 1
            if self._read_failures >= POLL_FAILURES_BEFORE_LOST:
                self.call_from_thread(
                    self._on_disconnected,
                    "%s\nPress r to reconnect." % exc,
                )
            return
        except Exception as exc:                      # noqa: BLE001
            # A bug, not a dropped reply: retrying will not help, so report it
            # at once instead of counting it toward the blip tolerance.
            self.call_from_thread(
                self._on_disconnected,
                "%s\nPress r to reconnect." % _unexpected(exc),
            )
            return
        self._read_failures = 0
        self.call_from_thread(self.apply_state, state)

    # How close a reading has to be before it counts as confirming what the
    # user asked for. Brightness is 10-1000 internally, so a set of 40% can
    # legitimately read back as 39% - see CLAUDE.md.
    INTENT_TOLERANCE = 2

    def apply_state(self, state, override=None):
        """Render a reading from the bulb.

        A poll can land while the app is shutting down, when the widgets are
        already gone - so every query here has to tolerate NoMatches rather
        than take the worker down with it.

        Readings routinely arrive stale: the bulb publishes a write a beat
        after accepting it, and a poll already blocked in read() when the
        write went out returns pre-write data. Applying those verbatim is
        what made a bar jump back to its old value for a few seconds before
        settling on the new one.

        So a control the user has just moved keeps showing their value until
        a reading confirms it. `override` is the value we have this instant
        written, which is newer than any reading in flight.
        """
        for name, value in (override or {}).items():
            self._intent[name] = value
        # Release the hold on any control the bulb has caught up with. This
        # only decides which value each *bar* shows - `state` itself is left
        # exactly as the bulb reported it, because the status line above is
        # meant to report the bulb, not echo what was typed.
        for name, current in (("brightness", state.brightness),
                              ("warmth", state.warmth)):
            want = self._intent.get(name)
            if want is not None and abs(current - want) <= self.INTENT_TOLERANCE:
                self._intent.pop(name, None)
        self.state = state
        try:
            self.render_status()
        except NoMatches:
            return      # unmounting; nothing left to draw on
        # A control with a write still queued must not be touched at all, or
        # the reading yanks it back under the user's fingers mid-drag. Where
        # intent is still held the bar keeps showing it, so a stale reading
        # cannot bounce it back; everything else follows the bulb.
        try:
            for name, selector in (("brightness", "#brightness"),
                                   ("warmth", "#warmth")):
                if name in self._pending:
                    continue
                reading = (state.brightness if name == "brightness"
                           else state.warmth)
                self.query_one(selector, Bar).set_quietly(
                    self._intent.get(name, reading)
                )
            if "mode" not in self._pending:
                self.query_one("#mode", ModeTabs).set_quietly(state.mode)
            self.show_mode_controls(state.mode)
        except NoMatches:
            return

    def render_status(self):
        """The line at the top. Reads self.state, corrected by any intent.

        Kept separate from apply_state so a keypress can refresh it straight
        away: waiting for the write to make its round trip left the header
        showing the old percentage for up to a second after the bar moved.
        """
        state = self.state
        power = self.query_one("#power", Label)
        dot = "[$success]●[/]" if state.power else "[$text-muted]○[/]"
        power.update(
            f"{dot}  [$text]{'on' if state.power else 'off'}[/]"
            f"   [$text-muted]{state.brightness}% · {state.mode}[/]"
        )
        power.set_classes(["on" if state.power else "off"])

    def show_mode_controls(self, mode):
        """Only show the controls that do anything in this mode.

        Warmth is a white-mode setting; the swatches and the hex input are
        colour-mode ones. Leaving all of them on screen made the panel look
        like it was ignoring half of them.
        """
        colour = mode == MODE_COLOUR
        self.query_one("#warmth", Bar).set_class(colour, "hidden")
        for selector in ("#swatches", "#hex", "#colour-label"):
            self.query_one(selector).set_class(not colour, "hidden")
        # Never leave focus on something that just disappeared.
        focused = self.focused
        if focused is not None and not focused.display:
            self.query_one("#brightness", Bar).focus()

    def action_settings(self):
        """Open Settings, prefilled with whatever is configured now."""
        self.push_screen(SettingsScreen(self.bulb.settings))

    @on(SettingsScreen.Saved)
    def settings_saved(self, event):
        """Adopt new credentials and reconnect, without a restart.

        The Bulb keeps its settings, so handing it the new ones and calling
        connect() is the whole operation - connect() closes the old socket
        first, so a key change cannot leave the previous device open.
        """
        self.bulb.settings = event.settings
        self._intent.clear()
        self.note("Settings saved - reconnecting...")
        self.connect()

    def action_refresh_state(self):
        """Sync with the bulb. While disconnected this retries the connection
        instead - pressing refresh on the failure screen should be worth
        something, and a rescan is the only way back from a DHCP change."""
        if self.connected:
            self.poll()
        else:
            self._set_message("reconnecting...")
            self.connect()

    # -- writes ----------------------------------------------------------

    @work(thread=True, exclusive=True, group="write")
    def write(self, what, value):
        """Send one change. Exclusive, so a newer write cancels an older
        one still waiting on the socket."""
        if not self.connected:
            return
        try:
            if what == "brightness":
                # Pass the state we already hold: in colour mode brightness
                # has to be written into the HSV, and re-reading here would
                # cost another round trip on an already contended socket.
                self.bulb.set_brightness_pct(value, state=self.state)
            elif what == "warmth":
                # Same reason as brightness: warmth forces white mode, and
                # the state we hold says which register the visible
                # brightness is currently in.
                self.bulb.set_warmth_pct(value, state=self.state)
            elif what == "power":
                self.bulb.on() if value else self.bulb.off()
            elif what == "color":
                # Keep the current brightness rather than letting the bulb
                # jump to full whenever a swatch is picked.
                self.bulb.set_color_rgb(*value, brightness=self.state.brightness)
            elif what == "mode":
                self.bulb.set_mode(value, state=self.state)
        except BulbError as exc:
            # Clear the entry too, or a single failed write leaves poll
            # blocked for the rest of the session.
            self.call_from_thread(self._write_failed, what, value, str(exc))
            return
        except Exception as exc:                      # noqa: BLE001
            # This is the path that motivated the whole clause: a missing
            # attribute killed the write worker, painted a traceback over the
            # panel, and left _pending set so poll never resumed.
            self.call_from_thread(self._write_failed, what, value,
                                  _unexpected(exc))
            return

        # The write landed. Reading back to confirm is the most contended
        # moment on the socket, so a failure here is not worth reporting -
        # the next poll picks the state up anyway.
        try:
            state = self.bulb.read()
        except Exception:                             # noqa: BLE001
            # Swallowed deliberately, whatever the type: the write landed and
            # the next poll re-syncs.
            state = None
        self.call_from_thread(self._write_done, what, value, state)

    def _write_failed(self, what, value, text):
        if self._pending.get(what) == value:
            self._pending.pop(what, None)
        # The bulb never took this value, so stop holding the control at it -
        # otherwise a failed write pins the bar to a lie until the next one.
        if self._intent.get(what) == value:
            self._intent.pop(what, None)
        self._set_message(text, error=True)

    def _write_done(self, what, value, state):
        # Only clear the pending entry if it is still the value we just sent.
        # A newer change queued while this write was on the socket must keep
        # blocking poll, or a stale read yanks the bar back under the user.
        settled = self._pending.get(what) == value
        if settled:
            self._pending.pop(what, None)
        if state is not None:
            # The read-back happens within milliseconds of the write, and the
            # bulb has usually not published the new value yet - so `state`
            # still carries the OLD one. Applying it wholesale made the bar
            # jump back to where it started and sit there until the next poll
            # corrected it, which is the twitch. What we just wrote is the
            # authority for this control; take everything else from the read.
            self.apply_state(state, override={what: value} if settled else None)

    def queue_write(self, what, value):
        """Coalesce rapid changes - only the last value in a burst is sent."""
        self._pending[what] = value
        # Record the intent immediately, not when the write completes: a poll
        # can land in between, and without this it would show the old value.
        if what in ("brightness", "warmth"):
            self._intent[what] = value
        timer = self._debounce.get(what)
        if timer is not None:
            timer.stop()
        # Bind the value now rather than reading self._pending when the timer
        # fires. A write that completes in between pops the entry, and the
        # late timer would then send None straight into pct_to_raw.
        self._debounce[what] = self.set_timer(
            WRITE_DEBOUNCE, lambda: self._fire_write(what, value)
        )

    def _fire_write(self, what, value):
        self._debounce.pop(what, None)
        self.write(what, value)

    # -- input -----------------------------------------------------------

    @on(Bar.Changed, "#brightness")
    def brightness_changed(self, event):
        self.queue_write("brightness", event.value)

    @on(Bar.Changed, "#warmth")
    def warmth_changed(self, event):
        self.queue_write("warmth", event.value)

    @on(ModeTabs.Changed)
    def mode_changed(self, event):
        if not self.connected:
            return
        self._set_message(f"{event.mode} mode")
        # Show the right controls immediately rather than waiting for the
        # write to land and the next poll to report it back.
        self.show_mode_controls(event.mode)
        self.queue_write("mode", event.mode)

    @on(Swatch.Picked)
    def swatch_picked(self, event):
        self._set_message(f"set {event.name}")
        self.queue_write("color", event.rgb)

    @on(events.DescendantFocus)
    def focus_moved(self, event):
        """A hint for whatever is focused."""
        if not self.connected:
            return      # leave the failure text in place
        widget = event.widget
        if isinstance(widget, Swatch):
            self._set_message("enter to set")
        elif isinstance(widget, Bar):
            self._set_message("← → to adjust")
        elif isinstance(widget, ModeTabs):
            self._set_message("← → to switch mode")
        elif isinstance(widget, Input):
            self._set_message("type a hex colour, enter to set")

    @on(Input.Submitted, "#hex")
    def hex_submitted(self, event):
        value = event.value.strip()
        if not value:
            return
        try:
            rgb = parse_color(value)
        except BulbError as exc:
            self._set_message(str(exc), error=True)
            return
        self._set_message(f"colour {value}")
        self.queue_write("color", rgb)
        event.input.value = ""

    def swatch_rows(self):
        """The swatches chunked into the rows they are currently rendered in.

        The grid reflows with the terminal width, so the row structure is a
        function of the live column count, not a fixed pair of rows.
        """
        swatches = list(self.query("#swatches Swatch"))
        columns = self.query_one("#swatches").styles.grid_size_columns or 1
        return [swatches[i:i + columns] for i in range(0, len(swatches), columns)]

    def action_move(self, delta):
        """Up/down between controls, treating the swatch grid as a grid -
        from a swatch, down lands on the one below it, not the next along."""
        focused = self.focused
        rows = self.swatch_rows()
        if isinstance(focused, Swatch):
            for index, row in enumerate(rows):
                if focused in row:
                    target = index + delta
                    if 0 <= target < len(rows):
                        column = min(row.index(focused), len(rows[target]) - 1)
                        rows[target][column].focus()
                    elif target < 0:
                        # Warmth is hidden in colour mode, which is the only
                        # mode the swatches are visible in - so this lands on
                        # brightness in practice. Check anyway.
                        warmth = self.query_one("#warmth", Bar)
                        (warmth if warmth.display
                         else self.query_one("#brightness", Bar)).focus()
                    else:
                        self.query_one("#hex", Input).focus()
                    return

        # Everything else is a simple vertical stack, minus whatever this
        # mode hides - stepping onto an invisible control would look like the
        # key had done nothing.
        entry = None
        if rows and rows[0]:
            entry = rows[0][0] if delta > 0 else rows[-1][0]
        candidates = [
            self.query_one("#mode", ModeTabs),
            self.query_one("#brightness", Bar),
            self.query_one("#warmth", Bar),
            entry,
            self.query_one("#hex", Input),
        ]
        order = [w for w in candidates if w is not None and w.display]
        if focused in order:
            index = order.index(focused) + delta
            if 0 <= index < len(order):
                order[index].focus()
        else:
            order[0].focus()

    def action_toggle_power(self):
        if not self.connected:
            return
        self.queue_write("power", not self.state.power)

    def action_power_on(self):
        self.queue_write("power", True)

    def action_power_off(self):
        self.queue_write("power", False)

    # -- teardown --------------------------------------------------------

    def on_unmount(self):
        # Stop polling before dropping the socket, so a poll cannot land on a
        # half-torn-down screen. apply_state also guards for this, but not
        # scheduling the work at all is the better half of the fix.
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        self.bulb.close()


def run():
    LumenApp().run()


if __name__ == "__main__":
    run()
