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
from textual.containers import Container, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Static

from device import COLORS, Bulb, BulbError, BulbState, parse_color

# Trailing debounce on slider writes. Long enough to swallow a held arrow
# key, short enough that a single tap still feels immediate.
WRITE_DEBOUNCE = 0.15

# How often to reconcile with the bulb, in seconds. Catches changes made
# from the phone app or another terminal.
POLL_INTERVAL = 5.0

# Consecutive failed reads before the bulb counts as gone. One dropped reply
# is routine; three in a row (~15s of silence) means it really has left.
POLL_FAILURES_BEFORE_LOST = 3

# Failures older than this start a fresh streak, so unrelated blips minutes
# apart never add up to a false "lost contact".
POLL_FAILURE_WINDOW = POLL_INTERVAL * 3

BAR_WIDTH = 24

# Caret, block, space and the longest colour name ("magenta"). The swatch
# grid divides the available width by this to decide how many fit per row.
SWATCH_WIDTH = 12

# Preferred columns when there is room - two rows of five. A narrower
# terminal uses fewer and wraps onto more rows.
SWATCH_COLUMNS = 5


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
        """Track fills whatever is left after the label and the readout, so
        the bar still works when the panel is narrower than its maximum."""
        if width is None:
            width = self.size.width
        return max(4, min(BAR_WIDTH, width - 17))

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

    #message {
        height: auto;
        margin: 1 0 0 0;
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
        self._read_failures = 0     # consecutive failed polls
        self._last_failure = 0.0    # when the last one was

    # -- layout ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        panel = Vertical(id="panel")
        panel.border_title = "LUMEN"
        panel.border_subtitle = "tuya · local"
        with panel:
            yield Label("connecting...", id="power")

            yield Bar("brightness", minimum=1, id="brightness")
            yield Bar("warmth", id="warmth")

            yield Label("colour", classes="section")
            with Container(id="swatches"):
                for name in COLORS:
                    yield Swatch(name, COLORS[name])

            yield Input(placeholder="#rrggbb", id="hex")
            yield Static("", id="message")

        yield Footer()

    def on_mount(self):
        self.reflow_swatches()
        self.connect()
        self.set_interval(POLL_INTERVAL, self.poll)

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
        # SWATCH_WIDTH. Capped at SWATCH_COLUMNS so a wide terminal keeps the
        # two tidy rows rather than stretching into one long line.
        usable = width - 6
        columns = max(1, min(SWATCH_COLUMNS, usable // SWATCH_WIDTH))
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
        widget = self.query_one("#message", Static)
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
        self.call_from_thread(self._on_connected, state)

    def _on_connected(self, state):
        self.connected = True
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
        self._read_failures = 0
        self.call_from_thread(self.apply_state, state)

    def apply_state(self, state):
        self.state = state
        power = self.query_one("#power", Label)
        dot = "[$success]●[/]" if state.power else "[$text-muted]○[/]"
        power.update(
            f"{dot}  [$text]{'on' if state.power else 'off'}[/]"
            f"   [$text-muted]{state.brightness}% · {state.mode}[/]"
        )
        power.set_classes(["on" if state.power else "off"])
        if not self._pending:
            self.query_one("#brightness", Bar).set_quietly(state.brightness)
            self.query_one("#warmth", Bar).set_quietly(state.warmth)

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
                self.bulb.set_brightness_pct(value)
            elif what == "warmth":
                self.bulb.set_warmth_pct(value)
            elif what == "power":
                self.bulb.on() if value else self.bulb.off()
            elif what == "color":
                self.bulb.set_color_rgb(*value)
        except BulbError as exc:
            # Clear the entry too, or a single failed write leaves poll
            # blocked for the rest of the session.
            self.call_from_thread(self._write_failed, what, value, str(exc))
            return

        # The write landed. Reading back to confirm is the most contended
        # moment on the socket, so a failure here is not worth reporting -
        # the next poll picks the state up anyway.
        try:
            state = self.bulb.read()
        except BulbError:
            state = None
        self.call_from_thread(self._write_done, what, value, state)

    def _write_failed(self, what, value, text):
        if self._pending.get(what) == value:
            self._pending.pop(what, None)
        self._set_message(text, error=True)

    def _write_done(self, what, value, state):
        # Only clear the pending entry if it is still the value we just sent.
        # A newer change queued while this write was on the socket must keep
        # blocking poll, or a stale read yanks the bar back under the user.
        if self._pending.get(what) == value:
            self._pending.pop(what, None)
        if state is not None:
            self.apply_state(state)

    def queue_write(self, what, value):
        """Coalesce rapid changes - only the last value in a burst is sent."""
        self._pending[what] = value
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
                        self.query_one("#warmth", Bar).focus()
                    else:
                        self.query_one("#hex", Input).focus()
                    return

        # Everything else is a simple vertical stack. Entering the swatch
        # grid from below lands on its bottom row, so up/down retrace.
        entry = rows[0][0] if delta > 0 else rows[-1][0]
        order = [
            self.query_one("#brightness", Bar),
            self.query_one("#warmth", Bar),
            entry,
            self.query_one("#hex", Input),
        ]
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
        self.bulb.close()


def run():
    LumenApp().run()


if __name__ == "__main__":
    run()
