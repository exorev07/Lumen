"""Where the device credentials live, and how they are read and written.

Installed from a wheel, the package directory is read-only and may be shared
between users, so settings cannot live next to the code the way the old
`local_secrets.py` did. They go in the per-user config directory instead:

    Windows   %APPDATA%\\lumen\\config.toml
    macOS     ~/Library/Application Support/lumen/config.toml
    Linux     $XDG_CONFIG_HOME/lumen/config.toml, else ~/.config/lumen/

Precedence is environment, then that file, then empty. The environment is
there for CI and for anyone who would rather not have a key on disk; it is
read at load() time, so a shell variable always wins over the Settings
screen.

Nothing in this module identifies a device. The file it writes does, and it
is deliberately outside the repository.
"""

import os
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

# Tuya protocol version spoken by this generation of bulbs. Not user config -
# it is a property of the devices we support, so it stays in code.
VERSION = 3.3

APP_NAME = "lumen"
_FILENAME = "config.toml"

# The env vars were SYSKA_* when this only drove one bulb. Nothing here is
# Syska-specific, so LUMEN_* is the name now; the old spelling still works so
# an existing setup does not break on upgrade.
_ENV = {
    "device_id": ("LUMEN_DEVICE_ID", "SYSKA_DEVICE_ID"),
    "local_key": ("LUMEN_LOCAL_KEY", "SYSKA_LOCAL_KEY"),
    "ip": ("LUMEN_IP", "SYSKA_IP"),
}


def config_dir():
    """The per-user config directory, respecting the platform convention."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def config_path():
    return config_dir() / _FILENAME


def _quote(value):
    """Minimal TOML basic string.

    There is no TOML writer in the stdlib and the three values we store are
    hex-ish identifiers and an IP, so hand-rolling this is cheaper than taking
    a dependency for it. Escaping backslash and quote keeps a pasted value
    with stray punctuation from producing a file we cannot read back.
    """
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"%s"' % escaped


@dataclass
class Settings:
    """One device's connection details.

    Deliberately an instance rather than module constants: the Settings screen
    writes these at runtime and reconnects without a restart, and a device list
    later needs more than one of them alive at once.
    """

    device_id: str = ""
    local_key: str = ""
    ip: str = ""
    # Where this came from, so the Settings screen can say whether a value is
    # pinned by the environment and therefore not editable here.
    from_env: frozenset = frozenset()

    @property
    def is_configured(self):
        """True if there is enough to attempt a connection.

        The IP is not required - device.py discovers it by scanning.
        """
        return bool(self.device_id and self.local_key)

    def locked_by_env(self, field):
        return field in self.from_env

    def save(self, path=None):
        """Write the settings to disk, creating the directory if needed.

        Returns the path written. Raises OSError, which every caller is
        expected to surface rather than swallow - a save that silently did
        nothing is worse than an error message.
        """
        target = Path(path) if path else config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        body = (
            "# Lumen device settings.\n"
            "# Written by the app; safe to edit by hand while it is closed.\n"
            "# This file identifies your device - do not commit or share it.\n"
            "\n"
            "[device]\n"
            "device_id = %s\n"
            "local_key = %s\n"
            "ip        = %s\n"
        ) % (_quote(self.device_id), _quote(self.local_key), _quote(self.ip))

        # Write via a temporary file in the same directory and replace, so an
        # interrupted save cannot leave a half-written key behind.
        tmp = target.with_suffix(".toml.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, target)

        try:
            # Best effort on POSIX; the key is a credential. No-op on Windows,
            # where the user profile ACL already covers it.
            os.chmod(target, 0o600)
        except OSError:
            pass
        return target


def _read_file(path):
    """Parse the config file, returning a dict of whatever it holds.

    A malformed file is treated as absent rather than fatal: the app opens on
    the Settings screen and the user can retype the values, which is a better
    outcome than a traceback on a typo in a hand-edited file.
    """
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    section = data.get("device")
    return section if isinstance(section, dict) else {}


def _legacy_values():
    """Values from an old top-level local_secrets.py, if one is importable.

    Pre-0.1 installs kept the key in a Python module next to the code. Reading
    it here means an existing checkout keeps working after the restructure
    without the user re-running the Tuya wizard. Only ever read, never written.
    """
    try:
        import local_secrets
    except Exception:
        # ImportError normally, but a broken hand-edited file can raise
        # anything at all on import, and that must not stop the app starting.
        return {}
    return {
        "device_id": getattr(local_secrets, "DEVICE_ID", ""),
        "local_key": getattr(local_secrets, "LOCAL_KEY", ""),
        "ip": getattr(local_secrets, "IP", ""),
    }


def load(path=None):
    """Build Settings from the environment, then the file, then the legacy
    module. Never raises."""
    target = Path(path) if path else config_path()
    values = _read_file(target)

    if not any(values.get(k) for k in ("device_id", "local_key")):
        # Nothing on disk yet - fall back to a pre-0.1 local_secrets.py so an
        # upgrade in place does not look like a fresh install.
        values = {**_legacy_values(), **values}

    resolved = {}
    from_env = set()
    for field, names in _ENV.items():
        value = next((os.environ[n] for n in names if os.environ.get(n)), None)
        if value:
            resolved[field] = value
            from_env.add(field)
        else:
            resolved[field] = str(values.get(field) or "")

    return Settings(from_env=frozenset(from_env), **resolved)


def with_ip(settings, ip):
    """A copy of settings carrying a rediscovered address."""
    return replace(settings, ip=ip)
