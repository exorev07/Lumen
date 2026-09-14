# Building the Windows executable

Produces a single self-contained `lumen.exe` for people who do not have
Python. Run from the repository root:

```
python -m venv .buildenv
.buildenv\Scripts\pip install . pyinstaller
.buildenv\Scripts\pyinstaller packaging/lumen.spec --noconfirm
```

The binary lands in `dist/lumen.exe` (~20 MB). Both `dist/` and
`release/` are gitignored — the exe belongs on a GitHub Release, not in
git history, where it could never be removed.

Build from a **clean venv with the package installed**, not from the
source tree: PyInstaller bundles what it can import, so building against
`src/` on `PYTHONPATH` can hide a packaging mistake that a user would
hit. Same reasoning as the `src/` layout itself.

## Two things in `lumen.spec` that are load-bearing

**`console=True`.** Textual needs a real terminal. A windowed
(GUI-subsystem) build has none, so it would flash and exit with no way to
see why. Verify after any change to the spec — the PE subsystem field
must read 3, not 2:

```python
import struct
d = open("dist/lumen.exe", "rb").read()
pe = struct.unpack_from("<I", d, 0x3C)[0]
print(struct.unpack_from("<H", d, pe + 24 + 68)[0])   # 3 = console
```

**`collect_all("textual")`.** Textual loads `.tcss` stylesheets and some
widget modules at runtime. Stylesheets are data files that import
analysis cannot see, and losing them gives a binary that starts and then
renders unstyled or raises on mount. `tinytuya` gets the same treatment
for its device-profile data.

## Testing the result

A headless Textual test cannot cover this: it never allocates a console,
and a console-subsystem problem only appears in one. Test the actual
binary, in a real terminal, from a directory that is **not** the repo and
with Python off PATH — that is what proves it is self-contained.

One trap worth knowing if you automate it. Driving the exe from another
process means `AttachConsole`, and after attaching, this process's cached
std handles still point at the console you detached from — every read
fails with `ERROR_INVALID_HANDLE`. Open `CONOUT$` / `CONIN$` instead of
calling `GetStdHandle`. And a synthetic key record needs its real
`UnicodeChar`: Textual reads the console as a character stream, so
`escape` sent as virtual-key `0x1B` with a NUL character does nothing at
all, while page-down works because the Windows driver maps that from the
virtual-key code.

Also check the **first-run** path from a working directory with no
`local_secrets.py` in it. The legacy migration reads one from the cwd, so
running a "fresh install" test from the repo root silently configures
itself from your own credentials and the test proves nothing.
