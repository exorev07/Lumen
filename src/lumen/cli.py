"""The `lumen` command.

With no arguments this opens the app, which is the primary way in. With a
subcommand it does one thing and exits, which is what scripts want.
"""

import argparse
import pathlib
import sys

from . import __version__, config
from .device import COLORS, Bulb, BulbError, parse_color


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
        prog="lumen",
        description="Control a Tuya / SmartLife smart bulb over the local "
                    "network. Run with no command to open the app.",
        epilog="Colors: " + ", ".join(COLORS),
    )
    parser.add_argument("--version", action="version",
                        version="lumen %s" % __version__)
    # Both spellings: the code says "licence", pip and PyPI say "license".
    parser.add_argument("--licence", "--license", dest="licence",
                        action="store_true",
                        help="show the licence, including bundled libraries")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("ui", help="open the app (the default)")
    sub.add_parser("on", help="turn the bulb on")
    sub.add_parser("off", help="turn the bulb off")
    sub.add_parser("toggle", help="flip the current power state")
    sub.add_parser("status", help="show the current state")
    sub.add_parser("config", help="show where settings are stored")

    p = sub.add_parser("brightness", help="set brightness 1-100")
    p.add_argument("percent", type=int, choices=range(1, 101), metavar="1-100")

    p = sub.add_parser("color", help="set an RGB colour")
    p.add_argument("value", help="a colour name or #RRGGBB")

    p = sub.add_parser("warm",
                       help="white mode at a warmth 0-100, 100 = warmest")
    p.add_argument("percent", type=int, choices=range(0, 101), metavar="0-100")

    return parser


def show_config():
    """Where the settings live and whether they are filled in.

    Printed without connecting, so it still answers when the bulb is
    unreachable - which is exactly when someone goes looking for the file.
    """
    settings = config.load()
    print(f"Config file : {config.config_path()}")
    print(f"Configured  : {'yes' if settings.is_configured else 'no'}")
    if settings.ip:
        print(f"Saved IP    : {settings.ip}")
    if settings.from_env:
        print(f"From env    : {', '.join(sorted(settings.from_env))}")


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


def _bundled_dir():
    """Where our data files live.

    Frozen by PyInstaller, the bundle is unpacked to a temp directory named
    by `sys._MEIPASS`; running from source or an installed wheel, the
    licence sits at the repository root, two levels above this module.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return pathlib.Path(base)
    return pathlib.Path(__file__).resolve().parent.parent.parent


def show_licence():
    """Print Lumen's licence and those of everything bundled with it.

    The exe is a binary redistribution of seventeen third-party libraries
    whose licences require their text to travel with it. Embedding the
    text is only half of that - this is how someone actually reads it.
    """
    base = _bundled_dir()
    shown = False
    for name, heading in (("LICENSE", "Lumen"),
                          ("THIRD-PARTY-LICENSES.txt", None)):
        f = base / name
        if not f.exists():
            continue
        if heading:
            print("%s is licensed as follows." % heading)
            print()
        print(f.read_text(encoding="utf-8", errors="replace").rstrip())
        print()
        shown = True
    if not shown:
        print("Lumen is MIT licensed. Copyright (c) 2026 Ekansh Arohi.")
        print("Full text: https://github.com/exorev07/Lumen/blob/main/LICENSE")


def main():
    args = build_parser().parse_args()

    if getattr(args, "licence", False):
        show_licence()
        return

    if args.cmd in (None, "ui"):
        from . import tui
        tui.run()
        return

    # Answered without a connection, so it works when the bulb does not.
    if args.cmd == "config":
        show_config()
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
