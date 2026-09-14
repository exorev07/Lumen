# Building the Windows executable

Produces a single self-contained `lumen.exe` for people who do not have
Python. Run from the repository root:

```
python -m venv .buildenv
.buildenv\Scripts\pip install . pyinstaller
.buildenv\Scripts\pyinstaller packaging/lumen.spec --noconfirm
```

The app lands in `dist/lumen/` — `lumen.exe` plus an `_internal`
folder. Then package it for download:

```
.buildenv\Scripts\python packaging/gen_licenses.py build/lumen > release/THIRD-PARTY-LICENSES.txt
.buildenv\Scripts\python packaging/make_release.py dist/lumen
```

That produces `release/Lumen-<version>-win-x64.zip` (~20 MB) with the
app, `install.ps1`, `uninstall.ps1`, both licence files and a README,
plus a `.sha256` of the zip. Both `dist/` and `release/` are gitignored
— a 20 MB artifact belongs on a GitHub Release, not in git history,
where it could never be removed.

**It is a onedir build, not onefile,** and that is deliberate. A onefile
binary unpacks itself to a temp directory on every run: measured here,
that is the difference between 1.03s and 0.25s of startup, and the
self-extraction is exactly the behaviour antivirus heuristics flag on an
unsigned executable. The zip compresses to about the same size a onefile
exe did, so it costs nothing to ship the folder.

Build from a **clean venv with the package installed**, not from the
source tree: PyInstaller bundles what it can import, so building against
`src/` on `PYTHONPATH` can hide a packaging mistake that a user would
hit. Same reasoning as the `src/` layout itself.

## Licences are part of the build, not an afterthought

The exe is a **binary redistribution** of seventeen third-party libraries
(MIT, BSD, Apache-2.0, MPL-2.0), and all of those licences require their
text to travel with the binary. Shipping the exe alone is a violation, so
regenerate the licence file whenever dependencies change:

```
.buildenv\Scripts\python packaging/gen_licenses.py build/lumen > release/THIRD-PARTY-LICENSES.txt
```

Run it **after** the build and against the same environment, because it
derives the package list from PyInstaller's own TOC files rather than
from a hand-written list - a hand-kept list goes stale silently the
moment a dependency is added, which is the failure mode worth designing
out. It exits non-zero if the build directory is missing, and warns on
stderr for any package that ships no licence file.

The result is also **embedded in the exe** (the `datas` entry in the
spec) and printed by `lumen --licence`, so the obligation is met by the
artifact itself and not only by the files next to it. `version_info.txt`
puts the copyright and MIT notice in the binary's Windows version
resource, where Explorer shows it under Properties > Details.

One trap if you edit `gen_licenses.py`: modern wheels keep their licence
at `dist-info/licenses/LICENSE`, and `importlib.metadata`'s
`dist.read_text()` resolves relative to site-packages and returns `None`
for it. Read the path from `dist._path` instead. Getting this wrong
reports "ships no licence file" for *every* package, which looks like a
finding about the packages rather than a bug in the script.

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
