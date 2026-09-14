r"""Assemble the downloadable zip from a finished onedir build.

Run after PyInstaller, from the repository root:

    .buildenv\Scripts\python packaging/make_release.py dist/lumen

Produces release/Lumen-<version>-win-x64.zip containing the app folder,
the install scripts, the licences and a short README, plus a .sha256 of
the zip. Nothing here is committed - see .gitignore.
"""

import hashlib
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REL = ROOT / "release"
PKG = ROOT / "packaging"

README = r"""Lumen {version}
=====================================================================

A terminal app for Tuya / SmartLife smart bulbs. Local control over your
own network - no cloud, no hub.

    https://github.com/exorev07/Lumen


To use it
---------------------------------------------------------------------

Just run lumen\lumen.exe. That is all - it does not need installing.

First run opens Settings and walks you through getting your device ID
and local key.


To install it (optional)
---------------------------------------------------------------------

Right-click install.ps1 and choose "Run with PowerShell", or from a
PowerShell window:

    .\install.ps1

That copies the app to %LOCALAPPDATA%\Programs\Lumen and adds it to
your PATH, so you can type `lumen` in any NEW terminal. No admin rights
needed. uninstall.ps1 undoes it.

If PowerShell refuses to run the script, it is the execution policy, not
the script failing. Either run it as

    powershell -ExecutionPolicy Bypass -File .\install.ps1

or skip installing entirely and run lumen\lumen.exe directly.


Windows may warn you
---------------------------------------------------------------------

SmartScreen will likely say "Windows protected your PC" the first time.
Click More info, then Run anyway. Some antivirus tools may flag it too.

That is because the binary is unsigned - a code-signing certificate
costs a few hundred dollars a year, which this project does not yet
justify. It is not a statement that anything was found. The SHA-256 of
this zip is published on the release page, and the whole source is on
GitHub if you would rather build it yourself.


Requirements
---------------------------------------------------------------------

Windows 10 or 11, 64-bit (x64). There is no ARM64 build yet.

If the display looks garbled, use Windows Terminal rather than the old
console window.


Licence
---------------------------------------------------------------------

Lumen is MIT licensed - see LICENSE.

It bundles the Python runtime and several third-party libraries, whose
licences are in THIRD-PARTY-LICENSES.txt. `lumen --licence` prints them.
"""


def version():
    text = (ROOT / "src" / "lumen" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=")[1].strip().strip('"').strip("'")
    raise SystemExit("could not read __version__")


def main():
    app = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dist/lumen")
    if not (app / "lumen.exe").exists():
        raise SystemExit("no lumen.exe in %s - build it first" % app)

    licences = REL / "THIRD-PARTY-LICENSES.txt"
    if not licences.exists():
        raise SystemExit(
            "release/THIRD-PARTY-LICENSES.txt is missing - run "
            "packaging/gen_licenses.py first. The zip must not ship "
            "without it; the bundled libraries' licences require it.")

    ver = version()
    stage = REL / ("Lumen-%s-win-x64" % ver)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    shutil.copytree(app, stage / "lumen")
    for src in (PKG / "install.ps1", PKG / "uninstall.ps1",
                ROOT / "LICENSE", licences):
        shutil.copy2(src, stage / src.name)
    (stage / "README.txt").write_text(README.replace("{version}", ver), encoding="utf-8")

    out = REL / ("Lumen-%s-win-x64.zip" % ver)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(stage.parent))

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (REL / (out.name + ".sha256")).write_text(
        "%s  %s\n" % (digest, out.name), encoding="utf-8")

    shutil.rmtree(stage)
    raw = sum(f.stat().st_size for f in app.rglob("*") if f.is_file())
    print("%s" % out.name)
    print("  %.1f MB zipped (from %.1f MB of files)"
          % (out.stat().st_size / 1048576, raw / 1048576))
    print("  sha256 %s" % digest)


if __name__ == "__main__":
    main()
