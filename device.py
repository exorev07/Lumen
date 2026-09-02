"""Transport layer for a Tuya 3.3 colour bulb (category `dj`).

Nothing here is Syska-specific, and nothing here writes to stdout or exits.
Failures raise BulbError; the caller decides whether that means an error
message on a CLI or a panel in the TUI.

DPS codes: 20 = switch, 21 = mode, 22 = brightness, 23 = colour temp,
24 = HSV colour.
"""

import os
import re
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
    return round((raw - _RAW_MIN) / _RAW_SPAN * 100)


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


@dataclass
class BulbState:
    """A decoded snapshot of the bulb."""

    power: bool = False
    mode: str = "-"
    brightness: int = 0     # percent
    warmth: int = 0         # percent, 0 = warm, 100 = cool
    hsv: str = ""

    @classmethod
    def from_dps(cls, dps):
        state = cls(power=bool(dps.get("20")), mode=dps.get("21", "-"))
        if "22" in dps:
            state.brightness = raw_to_pct(dps["22"])
        if "23" in dps:
            state.warmth = round(dps["23"] / 1000 * 100)
        state.hsv = dps.get("24") or ""
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
        return BulbState.from_dps(data["dps"])

    def heartbeat(self):
        """Keep the persistent socket alive between polls."""
        return self._device.heartbeat()

    # -- writes ----------------------------------------------------------

    def on(self):
        self._device.turn_on()

    def off(self):
        self._device.turn_off()

    def toggle(self):
        """Flip the power. Returns the new state."""
        is_on = self.read().power
        self.off() if is_on else self.on()
        return not is_on

    def set_brightness_pct(self, percent):
        self._device.set_brightness(pct_to_raw(percent))

    def set_color_rgb(self, r, g, b):
        self._device.set_colour(r, g, b)

    def set_warmth_pct(self, percent):
        """White mode at a colour temperature, 0 = warm, 100 = cool.

        Reads the current brightness first and preserves it - this used to
        force 100%, which was wrong. Returns the brightness it kept.
        """
        bright = self.read().brightness or 100
        self._device.set_white_percentage(bright, percent)
        return bright
