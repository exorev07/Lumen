"""Bulb connection settings.

Nothing identifying lives in this file - it is safe to commit.

The device ID, local key and IP are secrets/identifiers and live in
local_secrets.py, which is gitignored. Copy local_secrets.example.py to
local_secrets.py and fill it in, or set the environment variables
SYSKA_DEVICE_ID, SYSKA_LOCAL_KEY and SYSKA_IP.
"""

import os

try:
    import local_secrets as _s
except ImportError:
    _s = None


def _get(name, attr, default=""):
    """Environment variable wins, then local_secrets.py, then the default."""
    value = os.environ.get(name)
    if value:
        return value
    return getattr(_s, attr, default) if _s else default


DEVICE_ID = _get("SYSKA_DEVICE_ID", "DEVICE_ID")
LOCAL_KEY = _get("SYSKA_LOCAL_KEY", "LOCAL_KEY")
IP        = _get("SYSKA_IP", "IP")

VERSION   = 3.3
