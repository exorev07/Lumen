"""Transport layer for a Tuya 3.3 colour bulb (category `dj`).

Nothing here is Syska-specific, and nothing here writes to stdout or exits.
Failures raise BulbError; the caller decides whether that means an error
message on a CLI or a panel in the TUI.

DPS codes: 20 = switch, 21 = mode, 22 = brightness, 23 = colour temp,
24 = HSV colour.
"""

import os
import re
import threading
from dataclasses import dataclass

import tinytuya

import config

COLORS = {
    "red":     (255, 0, 0),
    "green":   (0, 255, 0),
    "blue":    (0, 0, 255),
    "yellow":  (255, 255, 0),
    "cyan":    (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange":  (255, 100, 0),
    "purple":  (140, 0, 255),
    "pink":    (255, 60, 120),
    "white":   (255, 255, 255),
}

# This generation of bulbs takes 10-1000 rather than 0-100, so a set of 40%
# can read back as 39%. That rounding is expected, not a bug.
_RAW_MIN = 10
_RAW_SPAN = 990


class BulbError(Exception):
    """Anything that stops us talking to the bulb."""


class BulbNotConfigured(BulbError):
    pass


class BulbNotFound(BulbError):
    """Not on the network at all - powered off, or on another WiFi."""


class BulbRejected(BulbError):
    """Answered, but refused us. The local key has almost certainly rotated."""


def pct_to_raw(percent):
    return round(_RAW_MIN + percent / 100 * _RAW_SPAN)


def raw_to_pct(raw):
    # Clamped: a bulb sitting at raw 0 (which colour mode can produce) would
    # otherwise decode to -1%, and a negative percent blows up on the way back
    # into tinytuya's 0-100 setters.
    return max(0, min(100, round((raw - _RAW_MIN) / _RAW_SPAN * 100)))


def parse_color(value):
    """Accept a named colour or a #RRGGBB / RRGGBB hex string."""
    if value.lower() in COLORS:
        return COLORS[value.lower()]
    hexval = value.lstrip("#")
    if len(hexval) != 6:
        raise BulbError(
            f"Unrecognised color {value!r}. Use a name or #RRGGBB hex."
        )
    try:
        return tuple(int(hexval[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise BulbError(f"Invalid hex color {value!r}.") from None


# The bulb's two modes. DPS 21 carries these strings verbatim.
MODE_WHITE = "white"
MODE_COLOUR = "colour"


def hsv_value_pct(hsv):
    """Brightness percent out of an HSV payload, or None if unreadable.

    DPS 24 is 12 hex digits - hue, saturation, value - and the value shares
    DPS 22's 10-1000 scale, so raw_to_pct decodes it unchanged.
    """
    if not hsv or len(hsv) < 12:
        return None
    try:
        return raw_to_pct(int(hsv[8:12], 16))
    except ValueError:
        return None


@dataclass
class BulbState:
    """A decoded snapshot of the bulb."""

    power: bool = False
    mode: str = "-"
    brightness: int = 0     # percent
    warmth: int = 0         # percent, 0 = warm, 100 = cool
    hsv: str = ""

    @property
    def is_colour(self):
        return self.mode == MODE_COLOUR

    @classmethod
    def from_dps(cls, dps, previous=None):
        """Decode a status payload.

        The bulb sometimes answers with a *partial* frame carrying only the
        DPS that just changed. Anything absent keeps its previous value, or
        a missing key would read as zero and blank the display for a tick.
        """
        base = previous or cls()
        state = cls(
            power=bool(dps["20"]) if "20" in dps else base.power,
            mode=dps.get("21", base.mode),
        )
        state.brightness = (raw_to_pct(dps["22"]) if "22" in dps
                            else base.brightness)
        state.warmth = (round(dps["23"] / 1000 * 100) if "23" in dps
                        else base.warmth)
        state.hsv = dps.get("24") or base.hsv
        # In colour mode the bulb ignores DPS 22 entirely - brightness is the
        # V of the HSV in DPS 24, and 22 sits at whatever white mode left it.
        # Reading 22 here made the bar snap back to its white-mode value the
        # instant a colour was picked.
        if state.is_colour:
            value = hsv_value_pct(state.hsv)
            if value is not None:
                state.brightness = value
        return state


def _save_ip(ip, on_message=None):
    """Persist a newly discovered IP back into local_secrets.py."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "local_secrets.py")
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        if re.search(r'^IP\s*=', src, flags=re.M):
            src = re.sub(r'^IP\s*=.*$', 'IP        = "%s"' % ip, src,
                         count=1, flags=re.M)
        else:
            src = src.rstrip("\n") + '\nIP        = "%s"\n' % ip
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        if on_message:
            on_message("Bulb is at %s - local_secrets.py updated." % ip)
    except OSError as exc:
        if on_message:
            on_message("Found bulb at %s but could not save it: %s" % (ip, exc))


class Bulb:
    """One persistent connection to the bulb.

    The socket is held open, so a long-lived caller (the TUI, and later the
    music-reactive mode) pays the connection cost once rather than per command.
    """

    def __init__(self, on_message=None):
        # on_message reports progress that is not an error - a LAN scan, or a
        # saved address. The CLI sends it to stderr; the TUI shows it in-app.
        self._on_message = on_message
        self._dev = None
        # Last fully decoded state, used to fill in partial status frames.
        self._last_state = None
        # One persistent socket, but the TUI polls and writes from separate
        # worker threads. Interleaving two conversations on one TCP stream
        # corrupts the framing and tinytuya reports "Unexpected Payload from
        # Device", so every exchange takes this lock.
        self._lock = threading.RLock()

    # -- connection ------------------------------------------------------

    def _say(self, text):
        if self._on_message:
            self._on_message(text)

    def _build(self, ip):
        dev = tinytuya.BulbDevice(config.DEVICE_ID, ip, config.LOCAL_KEY)
        dev.set_version(config.VERSION)
        dev.set_socketPersistent(True)
        return dev

    @staticmethod
    def _reachable(dev):
        """True if the bulb answers a status poll on this address."""
        data = dev.status()
        return isinstance(data, dict) and "dps" in data

    def _rescan(self):
        """Look for the bulb on the network; return its current IP or None."""
        self._say("Locating the bulb on the network...")
        try:
            found = tinytuya.deviceScan(False, 12)
        except Exception as exc:
            self._say("Scan failed: %s" % exc)
            return None
        for ip, info in found.items():
            if info.get("gwId") == config.DEVICE_ID:
                return ip
        return None

    def open(self):
        """Connect, rediscovering the bulb if its address has changed."""
        if not config.DEVICE_ID or not config.LOCAL_KEY:
            raise BulbNotConfigured(
                "Bulb is not configured.\n"
                "Copy local_secrets.example.py to local_secrets.py and fill in "
                "DEVICE_ID and LOCAL_KEY.\nSee README.md for how to get them."
            )

        # Hold the lock across the whole reconnect: `r` can retry while a
        # poll is still in flight, and swapping self._dev underneath a
        # thread that is mid-exchange is the same framing corruption the
        # lock exists to prevent.
        with self._lock:
            return self._open_locked()

    def _open_locked(self):
        if config.IP:
            dev = self._build(config.IP)
            if self._reachable(dev):
                self._dev = dev
                return self

        # No IP yet, or the DHCP lease changed. Find it and remember where.
        ip = self._rescan()
        if not ip:
            raise BulbNotFound(
                "Could not find the bulb on this network.\n"
                "Check that it is powered on and connected to the same WiFi.\n"
                "See TROUBLESHOOTING.md if that does not help."
            )

        dev = self._build(ip)
        if not self._reachable(dev):
            raise BulbRejected(
                "Found the bulb at %s but it rejected the connection.\n"
                "The local key has probably rotated - see TROUBLESHOOTING.md."
                % ip
            )

        _save_ip(ip, self._on_message)
        self._dev = dev
        return self

    def close(self):
        with self._lock:
            self._last_state = None
            if self._dev is not None:
                try:
                    self._dev.close()
                except Exception:
                    pass
                self._dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_exc):
        self.close()
        return False

    # -- reads -----------------------------------------------------------

    @property
    def _device(self):
        if self._dev is None:
            raise BulbError("Not connected - call open() first.")
        return self._dev

    def read(self):
        """Current state, decoded."""
        with self._lock:
            data = self._device.status()
        if not isinstance(data, dict) or "dps" not in data:
            # tinytuya reports failures as a dict; surface its message rather
            # than the raw payload, which reads like a bug to a user.
            detail = ""
            if isinstance(data, dict):
                detail = data.get("Error") or data.get("Err") or ""
            raise BulbError(
                "Lost contact with the bulb%s." % (" (%s)" % detail if detail
                                                   else "")
            )
        state = BulbState.from_dps(data["dps"], self._last_state)
        self._last_state = state
        return state

    def heartbeat(self):
        """Keep the persistent socket alive between polls."""
        with self._lock:
            return self._device.heartbeat()

    # -- writes ----------------------------------------------------------

    def on(self):
        with self._lock:
            self._device.turn_on()

    def off(self):
        with self._lock:
            self._device.turn_off()

    def toggle(self):
        """Flip the power. Returns the new state."""
        # Read and write as one unit - the lock is reentrant, so the nested
        # read() and on()/off() below reuse it rather than deadlocking.
        with self._lock:
            is_on = self.read().power
            self.off() if is_on else self.on()
            return not is_on

    def set_brightness_pct(self, percent, state=None):
        """Brightness, in whichever mode the bulb is currently in.

        In colour mode this has to rewrite the V of the HSV in DPS 24 - the
        bulb does not dim on DPS 22 while a colour is showing. Pass `state`
        to save the extra read when the caller already has a fresh one.
        """
        with self._lock:
            if state is None:
                state = self.read()
            if state.is_colour:
                hsv = state.hsv or "000003e803e8"
                hue = int(hsv[0:4], 16)
                sat = int(hsv[4:8], 16)
                self._device.set_hsv(hue / 360.0, sat / 1000.0, percent / 100.0)
            else:
                self._device.set_brightness(pct_to_raw(percent))

    def set_color_rgb(self, r, g, b, brightness=None):
        """Switch to colour mode.

        tinytuya's set_colour sends the RGB at full value, so picking a swatch
        used to jump the bulb back to 100%. Carrying the current brightness
        across keeps it where the user left it.
        """
        with self._lock:
            if brightness is None:
                self._device.set_colour(r, g, b)
                return
            import colorsys
            hue, value, sat = colorsys.rgb_to_hsv(r / 255.0, g / 255.0,
                                                  b / 255.0)
            self._device.set_hsv(hue, sat, brightness / 100.0)

    def set_mode(self, mode, state=None):
        """Switch between white and colour, preserving brightness.

        Going to colour restores the last colour the bulb held rather than
        defaulting to one, so flipping modes back and forth is lossless.
        """
        with self._lock:
            if state is None:
                state = self.read()
            # `or 100` also catches a bulb sitting at 0 - writing value 0 back
            # would set the colour to black rather than dimming it.
            bright = state.brightness or 100
            if mode == MODE_COLOUR:
                hsv = state.hsv or "000003e803e8"
                hue = int(hsv[0:4], 16)
                sat = int(hsv[4:8], 16) or 1000
                self._device.set_hsv(hue / 360.0, sat / 1000.0, bright / 100.0)
            else:
                self._device.set_white_percentage(bright, state.warmth)

    def set_warmth_pct(self, percent):
        """White mode at a colour temperature, 0 = warm, 100 = cool.

        Reads the current brightness first and preserves it - this used to
        force 100%, which was wrong. Returns the brightness it kept.
        """
        # Read state, not just brightness: in colour mode the brightness now
        # comes out of the HSV, and set_white_percentage switches the bulb to
        # white mode anyway, so the value carried across is the visible one.
        with self._lock:
            bright = self.read().brightness or 100
            self._device.set_white_percentage(bright, percent)
            return bright
