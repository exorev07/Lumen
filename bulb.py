#!/usr/bin/env python3
"""Control a Tuya / SmartLife smart bulb over the local network.

With no arguments this opens the terminal interface. With a subcommand it
does one thing and exits, which is what scripts want.
"""

import argparse
import sys

from device import COLORS, Bulb, BulbError, parse_color


def _note(text):
    """Progress that is not output - keep it off stdout."""
    print(text, file=sys.stderr)


def connect():
    try:
        return Bulb(on_message=_note).open()
    except BulbError as exc:
        sys.exit(str(exc))


def show_status(bulb):
    state = bulb.read()
    print(f"Power      : {'on' if state.power else 'off'}")
    print(f"Mode       : {state.mode}")
    print(f"Brightness : {state.brightness}%")
    print(f"Warmth     : {state.warmth}%")
    if state.hsv:
        print(f"Colour HSV : {state.hsv}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Control a Tuya / SmartLife smart bulb. "
                    "Run with no command to open the terminal interface.",
        epilog="Colors: " + ", ".join(COLORS),
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("ui", help="open the terminal interface (the default)")
    sub.add_parser("on", help="turn the bulb on")
    sub.add_parser("off", help="turn the bulb off")
    sub.add_parser("toggle", help="flip the current power state")
    sub.add_parser("status", help="show the current state")

    p = sub.add_parser("brightness", help="set brightness 1-100")
    p.add_argument("percent", type=int, choices=range(1, 101), metavar="1-100")

    p = sub.add_parser("color", help="set an RGB colour")
    p.add_argument("value", help="a colour name or #RRGGBB")

    p = sub.add_parser("warm",
                       help="white mode at a warmth 0-100, 100 = warmest")
    p.add_argument("percent", type=int, choices=range(0, 101), metavar="0-100")

    return parser


def run_command(bulb, args):
    if args.cmd == "status":
        show_status(bulb)
    elif args.cmd == "on":
        bulb.on()
        print("Bulb on")
    elif args.cmd == "off":
        bulb.off()
        print("Bulb off")
    elif args.cmd == "toggle":
        print("Bulb on" if bulb.toggle() else "Bulb off")
    elif args.cmd == "brightness":
        bulb.set_brightness_pct(args.percent)
        print(f"Brightness {args.percent}%")
    elif args.cmd == "color":
        r, g, b = parse_color(args.value)
        bulb.set_color_rgb(r, g, b)
        print(f"Colour {args.value} -> RGB({r}, {g}, {b})")
    elif args.cmd == "warm":
        bright = bulb.set_warmth_pct(args.percent)
        print(f"White mode, warmth {args.percent}% "
              f"(brightness {bright}%)")


def main():
    args = build_parser().parse_args()

    if args.cmd in (None, "ui"):
        import tui
        tui.run()
        return

    bulb = connect()
    try:
        run_command(bulb, args)
    except BulbError as exc:
        sys.exit(str(exc))
    finally:
        bulb.close()


if __name__ == "__main__":
    main()
