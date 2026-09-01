#!/usr/bin/env python3
"""Control the Syska SMW-12W-5C smart bulb over the local network."""

import argparse
import os
import re
import sys

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


def _build(ip):
    bulb = tinytuya.BulbDevice(config.DEVICE_ID, ip, config.LOCAL_KEY)
    bulb.set_version(config.VERSION)
    bulb.set_socketPersistent(True)
    return bulb


def _reachable(bulb):
    """True if the bulb answers a status poll on this address."""
    data = bulb.status()
    return isinstance(data, dict) and "dps" in data


def _rescan():
    """Look for the bulb on the network; return its current IP or None."""
    print("Locating the bulb on the network...", file=sys.stderr)
    try:
        found = tinytuya.deviceScan(False, 12)
    except Exception as exc:
        print("Scan failed: %s" % exc, file=sys.stderr)
        return None
    for ip, info in found.items():
        if info.get("gwId") == config.DEVICE_ID:
            return ip
    return None


def _save_ip(ip):
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
        print("Bulb is at %s - local_secrets.py updated." % ip,
              file=sys.stderr)
    except OSError as exc:
        print("Found bulb at %s but could not save it: %s" % (ip, exc),
              file=sys.stderr)


def connect():
    if not config.DEVICE_ID or not config.LOCAL_KEY:
        sys.exit(
            "Bulb is not configured.\n"
            "Copy local_secrets.example.py to local_secrets.py and fill in "
            "DEVICE_ID and LOCAL_KEY.\nSee README.md for how to get them."
        )

    if config.IP:
        bulb = _build(config.IP)
        if _reachable(bulb):
            return bulb

    # No IP yet, or the DHCP lease changed. Find it and remember where.
    ip = _rescan()
    if not ip:
        sys.exit(
            "Could not find the bulb on this network.\n"
            "Check that it is powered on and connected to the same WiFi.\n"
            "See TROUBLESHOOTING.md if that does not help."
        )

    bulb = _build(ip)
    if not _reachable(bulb):
        sys.exit(
            "Found the bulb at %s but it rejected the connection.\n"
            "The local key has probably rotated - see TROUBLESHOOTING.md." % ip
        )

    _save_ip(ip)
    return bulb


def parse_color(value):
    """Accept a named color or a #RRGGBB / RRGGBB hex string."""
    if value.lower() in COLORS:
        return COLORS[value.lower()]
    hexval = value.lstrip("#")
    if len(hexval) != 6:
        sys.exit(f"Unrecognised color {value!r}. Use a name or #RRGGBB hex.")
    try:
        return tuple(int(hexval[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        sys.exit(f"Invalid hex color {value!r}.")


def show_status(bulb):
    data = bulb.status()
    if not isinstance(data, dict) or "dps" not in data:
        sys.exit(f"Could not read status: {data}")
    dps = data["dps"]
    power = dps.get("20")
    print(f"Power      : {'on' if power else 'off'}")
    print(f"Mode       : {dps.get('21', '-')}")
    if "22" in dps:
        print(f"Brightness : {round((dps['22'] - 10) / 990 * 100)}%")
    if "23" in dps:
        print(f"Colour temp: {round(dps['23'] / 1000 * 100)}%")
    if dps.get("24"):
        print(f"Colour HSV : {dps['24']}")


def main():
    parser = argparse.ArgumentParser(
        description="Control the Syska smart bulb.",
        epilog="Colors: " + ", ".join(COLORS),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("on", help="turn the bulb on")
    sub.add_parser("off", help="turn the bulb off")
    sub.add_parser("toggle", help="flip the current power state")
    sub.add_parser("status", help="show the current state")

    p = sub.add_parser("brightness", help="set brightness 1-100")
    p.add_argument("percent", type=int, choices=range(1, 101), metavar="1-100")

    p = sub.add_parser("color", help="set an RGB colour")
    p.add_argument("value", help="a colour name or #RRGGBB")

    p = sub.add_parser("warm", help="white mode at a colour temperature 0-100")
    p.add_argument("percent", type=int, choices=range(0, 101), metavar="0-100")

    args = parser.parse_args()
    bulb = connect()

    if args.cmd == "status":
        show_status(bulb)
        return

    if args.cmd == "on":
        bulb.turn_on()
        print("Bulb on")
    elif args.cmd == "off":
        bulb.turn_off()
        print("Bulb off")
    elif args.cmd == "toggle":
        data = bulb.status()
        is_on = data.get("dps", {}).get("20") if isinstance(data, dict) else None
        if is_on is None:
            sys.exit(f"Could not read current state: {data}")
        bulb.turn_off() if is_on else bulb.turn_on()
        print(f"Bulb {'off' if is_on else 'on'}")
    elif args.cmd == "brightness":
        # Tuya expects 10-1000 for this generation of bulbs.
        bulb.set_brightness(round(10 + args.percent / 100 * 990))
        print(f"Brightness {args.percent}%")
    elif args.cmd == "color":
        r, g, b = parse_color(args.value)
        bulb.set_colour(r, g, b)
        print(f"Colour {args.value} -> RGB({r}, {g}, {b})")
    elif args.cmd == "warm":
        # Keep the brightness the bulb is already at rather than forcing 100%.
        data = bulb.status()
        raw = data.get("dps", {}).get("22", 1000) if isinstance(data, dict) else 1000
        bright = round((raw - 10) / 990 * 100) or 100
        bulb.set_white_percentage(bright, args.percent)
        print(f"White mode, colour temp {args.percent}% (brightness {bright}%)")


if __name__ == "__main__":
    main()
